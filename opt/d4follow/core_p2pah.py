# -*- coding: utf-8 -*-
"""order.p2pah.cn 后台客户端 —— 登录 / 只读列表 / 改价写入 / 清缓存。

为什么需要这个模块
------------------
`apply_price.py`（唯一会真正动钱的执行器）第 30 行写着
`from core_p2pah import P2PAHClient, CacheRefresher`，但这个模块**一直不存在**，
所以控制台点「执行改价（真改）」只会抛
`RuntimeError("改价执行器未启用（等待你明确授权并接通后台）")`。
本模块就是那个缺失的解锁点。

依赖
----
只用标准库（urllib + http.cookiejar）—— 线上 venv 里**没有 requests**，
和 core_iggm.py / core_front.py 保持一致。

═══ 登录（2026-09-23 实测确认） ═══
- 入口 `https://order.p2pah.cn/admin`（`/login.html` 是 404）
- 验证码 `GET /new_captcha.html?height=32&width=150&font_size=18`
  （4 位图形码，120x38 PNG）。**必须先取验证码**——这一步会下发 PHPSESSID，
  再带着同一个 cookie 去 POST 登录，否则验证码对不上。
- 登录 `POST /admin/public/dologin.html`，body: `username` / `password` / `captcha`
- 成功返回 `{"code":1,"msg":"登录成功！"}`
- 服务端下发 **3 个 cookie，缺一不可**：`PHPSESSID` + `user` + `admin_username`
  （只带 PHPSESSID 会被判未登录 —— 实测踩过）

图形验证码无法长期免人工，所以做成**会话复用**：登录成功把 cookie 存
`data/p2pah/session.json`，之后每次先试会话；失效了才要求重新过验证码。

═══ 改价（逆向自页面内联「同步价格」按钮的 JS，逻辑照抄，不能改） ═══
```
POST /game/admin_game_price/goodsEdit     Content-Type: application/json
[{"id":169819827,"gid":"456","min_qty":0,"unit_price":"0.6345","cprice":null}]
```
- body 是**数组**，只提交**改动过**的行
- 未改动的字段必须传**哨兵**：`min_qty` / `unit_price` 传 `0`，`cprice` 传 `null`
  —— PHP 端靠这个区分「没改」和「改成空」，传错会把价格清掉
- 成功 `{"code":1,"msg":...,"wait":n}`

═══ 价格口径 ═══
后台列表列：`$每个价格`(unit_price) / `销售价格(单价)`(只读) / `￥采购成本`(cprice)
`销售价格(单价) = unit_price × 折扣/100`（D4 各规格折扣均为 90）
⇒ 「$每个价格」就是前端价的原料。要设前端价 T，提交 `unit_price = T ÷ 0.9`。
本模块**只负责把 unit_price 原样提交**，口径换算由 engine.py 负责。

═══ 安全边界 ═══
本模块只提供「能力」：不做业务判断、不读开关、不决定改不改。
**是否真的发出写请求**由 `apply_price.py`（CLI，四道闸）与
`app.py::task_apply`（控制台，总开关闸 + 确认短语闸）决定。
"""
import base64
import http.cookiejar
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 列表页一行（<tr data-id=".." data-gid=".." class="jq-each-item">）
ROW_RE = re.compile(
    r'<tr\s+data-id="(?P<id>\d+)"\s+data-gid="(?P<gid>[^"]*)"\s+class="jq-each-item">'
    r'(?P<body>.*?)</tr>', re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
UNIT_PRICE_RE = re.compile(r'name="unit_price"[^>]*value="([^"]*)"')
MIN_QTY_RE = re.compile(r'name="min_qty"[^>]*value="([^"]*)"')
CPRICE_RE = re.compile(r'name="cprice"[^>]*value="([^"]*)"')
PACK_RE = re.compile(r"^\s*\((?P<n>\d+)\)\s*(?P<base>.+?)\s*$")


def _text(s):
    """去标签 + 去实体 + 压空白"""
    s = re.sub(r"<[^>]+>", " ", s or "")
    for a, b in (("&amp;", "&"), ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"'),
                 ("&lt;", "<"), ("&gt;", ">")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or "").replace(",", ""))
    return float(m.group(0)) if m else None


def split_pack(name):
    """`(100) Lair Key` → ('Lair Key', 100)"""
    m = PACK_RE.match(name or "")
    return (m.group("base").strip(), int(m.group("n"))) if m else ((name or "").strip(), 1)


class P2PAHClient(object):
    """order.p2pah.cn 后台客户端（登录 / 读 / 写）"""

    def __init__(self, cfg, log=print, session_path=None):
        p = cfg.get("p2pah") or {}
        self.cfg = cfg
        self.p = p
        self.log = log or (lambda *a: None)
        self.base = str(p.get("base") or "https://order.p2pah.cn").rstrip("/")
        self.host = urllib.parse.urlsplit(self.base).hostname or "order.p2pah.cn"
        self.acc = p.get("账号") or {}
        self.insecure = bool(p.get("allow_insecure_tls", True))
        self.timeout = int(p.get("超时秒") or 45)
        self.logged_in = False
        # 落盘位置
        wd = p.get("工作目录") or "data/p2pah"
        self.workdir = os.path.join(ROOT, wd) if not os.path.isabs(str(wd)) else str(wd)
        self.session_path = session_path or os.path.join(
            self.workdir, os.path.basename(str(p.get("会话文件") or "data/p2pah/session.json")))
        self.pending_path = os.path.join(self.workdir, "captcha_pending.json")
        self.captcha_path = os.path.join(self.workdir, "captcha.png")
        try:
            os.makedirs(self.workdir, exist_ok=True)
        except Exception:
            pass
        # cookie 容器
        self.jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(self.jar)]
        if self.insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*handlers)
        self.opener.addheaders = [
            ("User-Agent", UA),
            ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
            ("Accept", "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"),
        ]
        self.last_status = None
        self.last_url = None
        self._load_session(self.session_path)   # 优先用已登录的会话

    # ------------------------------------------------------------ 底层 HTTP
    def _url(self, path):
        path = str(path or "")
        return path if path.startswith("http") else self.base + (path if path.startswith("/") else "/" + path)

    def request(self, path, data=None, json_body=None, method=None, headers=None,
                referer=None, decode=True):
        url = self._url(path)
        hd = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            hd.setdefault("Content-Type", "application/json")
            hd.setdefault("Accept", "application/json, text/javascript, */*; q=0.01")
            hd.setdefault("X-Requested-With", "XMLHttpRequest")
        if referer:
            hd["Referer"] = self._url(referer)
        if method is None:
            method = "POST" if data is not None else "GET"
        req = urllib.request.Request(url, data=data, headers=hd, method=method)
        last = None
        for i in range(3):
            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    body = r.read()
                    self.last_status = getattr(r, "status", None) or r.getcode()
                    self.last_url = r.geturl()
                    break
            except urllib.error.HTTPError as e:
                self.last_status = e.code
                self.last_url = url
                body = e.read()
                break
            except Exception as e:            # 网络抖动重试
                last = e
                time.sleep(1.2 * (i + 1))
        else:
            raise last
        if not decode:
            return body
        return body.decode("utf-8", "replace")

    # ------------------------------------------------------------ 会话存取
    def _cookie_dict(self):
        return {c.name: c.value for c in self.jar}

    def _load_session(self, path):
        """把落盘的 cookie 灌回 cookie jar（跨进程也能续用登录态）"""
        if not path or not os.path.exists(path):
            return False
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            return False
        ck = d.get("cookies") or {}
        # ⚠ domain 不能带前导点、secure 要跟实际一致，否则 cookiejar 不会把 cookie 发出去
        #   （踩过：写成 ".order.p2pah.cn" + secure=True，jar 里有值但请求头里没有）
        secure = self.base.startswith("https")
        for k, v in ck.items():
            self.jar.set_cookie(http.cookiejar.Cookie(
                version=0, name=k, value=str(v), port=None, port_specified=False,
                domain=self.host, domain_specified=True, domain_initial_dot=False,
                path="/", path_specified=True, secure=secure, expires=None,
                discard=False, comment=None, comment_url=None, rest={}, rfc2109=False))
        return bool(ck)

    def _save(self, path, extra=None):
        ck = self._cookie_dict()
        need = [c for c in (self.p.get("会话", {}) or {}).get("cookie",
                ["PHPSESSID", "user", "admin_username"]) if c in ck]
        d = {"base": self.base, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cookies": ck}
        if extra:
            d.update(extra)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return need

    def session_info(self):
        """不联网，只看本地会话状态（给控制台用）"""
        ck = self._cookie_dict()
        need = list((self.p.get("会话", {}) or {}).get("cookie",
                     ["PHPSESSID", "user", "admin_username"]))
        miss = [c for c in need if not ck.get(c)]
        path = self.session_path
        saved_at = None
        if os.path.exists(path):
            try:
                saved_at = json.load(open(path, encoding="utf-8")).get("saved_at")
            except Exception:
                saved_at = None
        return {"ok": not miss, "missing": miss, "saved_at": saved_at,
                "file": os.path.relpath(path, ROOT) if path.startswith(ROOT) else path}

    # ------------------------------------------------------------ 验证码 + 登录
    def fetch_captcha(self, save_to=None, keep=False):
        """取一张新验证码（同时下发 PHPSESSID）。

        ⚠ 必须用它返回的这张图去换 captcha 字符串，并**紧接着**调 login()，
        因为验证码绑在这条会话上。keep=True 时不覆盖 session.json。
        """
        path = save_to or self.captcha_path
        cpath = (self.p.get("验证码") or "/new_captcha.html?height=32&width=150&font_size=18")
        raw = self.request(cpath, decode=False, headers={"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw)
        # 把「还没登录」的会话连同 PHPSESSID 一起暂存，供下一步 login() 使用
        self._save(self.pending_path, extra={"stage": "captcha"})
        return {"path": path, "b64": base64.b64encode(raw).decode("ascii"),
                "bytes": len(raw), "cookie": self._cookie_dict().get("PHPSESSID", "")}

    def login(self, captcha=None):
        """登录。captcha 为空则先试会话复用；会话失效且没给验证码 → 返回 False。"""
        if not self.acc.get("username"):
            self.log("  [p2pah] 未配置后台账号，无法登录")
            return False
        # ① 会话复用：本地已有完整 cookie，先探一下还活着没
        if not captcha:
            if self.session_info()["ok"]:
                if self.probe():
                    self.logged_in = True
                    self.log("  [p2pah] 复用已有会话（%s）" % (self.session_info().get("saved_at") or "?"))
                    return True
                self.log("  [p2pah] 本地会话已失效，需要重新过验证码")
            else:
                self.log("  [p2pah] 本地没有可用会话，需要先取验证码")
            return False
        # ② 真登录：补上验证码阶段暂存的 cookie，再 POST
        if not self._cookie_dict().get("PHPSESSID") and os.path.exists(self.pending_path):
            self._load_session(self.pending_path)
        captcha = str(captcha).strip()
        try:
            raw = self.request(self.p.get("登录接口") or "/admin/public/dologin.html",
                               data=urllib.parse.urlencode({
                                   "username": self.acc.get("username", ""),
                                   "password": self.acc.get("password", ""),
                                   "captcha": captcha,
                               }).encode("utf-8"),
                               headers={"Content-Type": "application/x-www-form-urlencoded",
                                        "X-Requested-With": "XMLHttpRequest"},
                               referer="/admin")
        except Exception as e:
            self.log("  [p2pah] 登录请求异常：%r" % e)
            return False
        try:
            j = json.loads(raw)
        except Exception:
            self.log("  [p2pah] 登录响应不是 JSON（验证码可能已过期）：%s" % raw[:160].replace("\n", " "))
            return False
        if int(j.get("code") or 0) != 1:
            self.log("  [p2pah] 登录失败：%s" % (j.get("msg") or j))
            return False
        need = self._save(self.session_path)
        if len(need) < 3:
            self.log("  [p2pah] ⚠ 登录返回成功，但 cookie 不全（只有 %s）—— 后续请求可能被判未登录" % need)
        self.logged_in = True
        try:
            os.remove(self.pending_path)
        except Exception:
            pass
        self.log("  [p2pah] 登录成功，会话已存（%s）" % os.path.basename(self.session_path))
        return True

    def logout_local(self):
        """清掉本地会话（换账号 / 强制重登时用）"""
        for p in (self.session_path, self.pending_path):
            try:
                os.remove(p)
            except Exception:
                pass
        self.jar = http.cookiejar.CookieJar()
        return True

    # ------------------------------------------------------------ 只读：列表
    def probe(self):
        """探活：拉一次产品列表页，能解析出商品行 = 登录态有效"""
        try:
            html = self.request(self.list_path(), headers={"Accept": "text/html,*/*;q=0.8"})
        except Exception:
            return False
        if "dologin" in html and "jq-each-item" not in html:
            return False
        return bool(ROW_RE.search(html))

    def list_path(self):
        return ((self.p.get("菜单") or {}).get("产品价格管理") or {}).get(
            "路径") or "/game/admin_game_price/index_item.html"

    def list_url(self, gid=None, aid=None, cid=None, keyword=None, page=None):
        g = (self.p.get("游戏") or {}).get("D4") or {}
        q = {
            "gid": gid if gid is not None else g.get("game_id", ""),
            "aid": aid if aid is not None else ((g.get("服务区") or [{}])[0].get("id", "")),
            "cid": cid or "",
            "keyword": keyword or "",
            "page": page if page is not None else "",
        }
        return self.list_path() + "?" + urllib.parse.urlencode(q)

    def parse_items(self, html):
        """把列表页解析成 [{id, gid, name, pack, min_qty, unit_price, sale_price, cprice, discount, stock}]"""
        out = []
        for m in ROW_RE.finditer(html or ""):
            body = m.group("body")
            tds = [_text(x) for x in TD_RE.findall(body)]
            name = ""
            for t in tds:
                if t and not t.isdigit() and "$" not in t and "￥" not in t:
                    name = t
                    break
            up = UNIT_PRICE_RE.search(body)
            mq = MIN_QTY_RE.search(body)
            cp = CPRICE_RE.search(body)
            base, pack = split_pack(name)
            # 折扣列：位于 产品名 之后的纯数字列（截图实测顺序 折扣 在 $每个价格 前）
            disc = None
            try:
                i_up = next(i for i, t in enumerate(tds) if "每" in t or t == "")
            except StopIteration:
                i_up = -1
            for t in tds:
                if t in ("90", "100", "95", "80", "85", "70"):
                    disc = _num(t)
            out.append({
                "id": int(m.group("id")),
                "gid": m.group("gid"),
                "name": name,
                "base_name": base,
                "pack": pack,
                "min_qty": _num(mq.group(1)) if mq else None,
                "unit_price": _num(up.group(1)) if up else None,
                "sale_price": next((_num(t) for t in reversed(tds) if t and _num(t) is not None), None),
                "cprice": _num(cp.group(1)) if cp else None,
                "discount": disc,
                "cells": tds,
            })
        return out

    def fetch_items(self, gid=None, aid=None, cid=None, keyword=None, page=None, log_page=False):
        """读产品列表（只读，GET）。返回 [{...}]"""
        html = self.request(self.list_url(gid, aid, cid, keyword, page),
                            headers={"Accept": "text/html,*/*;q=0.8"})
        items = self.parse_items(html)
        if log_page:
            self.log("  [p2pah] 列表页解析到 %d 条" % len(items))
        return items

    def fetch_list(self, path, params=None, log_page=False):
        """tracker.py 兼容接口：返回 {"rows": [...], "raw": html}

        rows 的键同时给出中英文两套，方便 tracker._pick_fields 命中。
        """
        url = self._url(path)
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        html = self.request(url, headers={"Accept": "text/html,*/*;q=0.8"})
        rows = []
        for it in self.parse_items(html):
            rows.append({
                "ID": it["id"],
                "产品名": it["name"],
                "商品名称": it["name"],
                "前端价": it["unit_price"],
                "$每个价格": it["unit_price"],
                "销售价格(单价)": it["sale_price"],
                "采购成本": it["cprice"],
                "成本": it["cprice"],
                "折扣": it["discount"],
                "每份数量": it["pack"],
                "_raw": it,
            })
        if log_page:
            self.log("  [p2pah] %s → %d 条" % (path, len(rows)))
        return {"rows": rows, "raw": html, "url": url}

    # ------------------------------------------------------------ 商品ID 解析
    def game_of(self, key):
        """该 key 属于哪个游戏（对照项.游戏；查不到按暗黑4）"""
        for it in ((self.cfg.get("商品映射") or {}).get("对照项") or []):
            if it.get("key") == key:
                return it.get("游戏") or "暗黑破坏神4"
        return "暗黑破坏神4"

    def gid(self, game=None):
        """后台 gid。game 为空 → 暗黑4（保持旧行为）；给 key 用 gid_of()。

        ⚠ 2026-09-25 修：`game` 可能是短码（"POE2"）也可能是对照项里的中文名
        （"流放之路2"），这里都用 engine.game_entry 解析，避免静默回退 456。
        """
        import engine as _engine
        if game is None:
            game = "暗黑破坏神4"
        gm = _engine.game_entry(self.cfg, game)
        if gm.get("game_id"):
            return str(gm["game_id"])
        # 兜底：短码直接命中
        g = self.p.get("游戏") or {}
        if isinstance(g.get(game), dict) and g[game].get("game_id"):
            return str(g[game]["game_id"])
        return str((g.get("D4") or {}).get("game_id") or "456")

    def gid_of(self, key):
        """按我方 key 取后台 gid（暗黑4=456 / POE2=552）"""
        return self.gid(self.game_of(key))

    def ids_of(self, key):
        """后台商品ID：先查 p2pah.商品ID映射（权威），再查 对照项[].p2pah.后台商品ID。
        重复上架的（如 CRUX_X10 有两条）一并返回 —— 少改一条前端可能仍显示旧价。
        """
        ids = []
        m = ((self.p.get("商品ID映射") or {}).get(key))
        if m:
            ids.append(str(m))
        dup = ((self.p.get("商品ID映射") or {}).get("_重复上架") or {}).get(key)
        if isinstance(dup, (list, tuple)):
            ids += [str(x) for x in dup]
        if not ids:
            for it in ((self.cfg.get("商品映射") or {}).get("对照项") or []):
                if it.get("key") == key:
                    v = ((it.get("p2pah") or {}).get("后台商品ID"))
                    if v:
                        ids.append(str(v))
        seen, out = set(), []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out

    # ------------------------------------------------------------ 写入
    def write_path(self):
        return (((self.p.get("写接口") or {}).get("产品价格管理") or {}).get("路径")
                or "/game/admin_game_price/goodsEdit")

    def set_prices(self, rows):
        """底层写：rows = [{"id":..,"gid":..,"min_qty":0,"unit_price":..,"cprice":None}]"""
        if not rows:
            return {"ok": False, "msg": "没有要提交的行"}
        try:
            raw = self.request(self.write_path(), json_body=rows, method="POST",
                               referer=self.list_path())
        except Exception as e:
            return {"ok": False, "msg": "请求异常：%r" % e}
        try:
            j = json.loads(raw)
        except Exception:
            return {"ok": False, "msg": "响应不是 JSON（登录态可能已失效）：%s"
                                        % raw[:200].replace("\n", " ")}
        if int(j.get("code") or 0) == 1:
            return {"ok": True, "msg": j.get("msg") or "成功", "wait": j.get("wait"), "rows": rows}
        return {"ok": False, "msg": j.get("msg") or json.dumps(j, ensure_ascii=False)[:200]}

    def set_price_by_key(self, key, unit_price, gid=None, min_qty=0):
        """按我方 key 改后台「$每个价格」（= 标价）。

        口径提醒：这里提交的就是 unit_price 本身，**不要再除折扣** ——
        engine 的目标价 ours_new 已经是标价口径。
        """
        ids = self.ids_of(key)
        if not ids:
            return {"ok": False, "msg": "没有 %s 的后台商品ID（config → p2pah.商品ID映射）" % key}
        g = str(gid or self.gid_of(key))
        try:
            v = float(unit_price)
        except Exception:
            return {"ok": False, "msg": "目标价不是数字：%r" % (unit_price,)}
        rows = [{"id": int(i), "gid": g, "min_qty": int(min_qty or 0),
                 "unit_price": "%.5f" % v, "cprice": None} for i in ids]
        res = self.set_prices(rows)
        res["key"] = key
        res["ids"] = ids
        res["unit_price"] = v
        return res

    def preview_by_key(self, key, unit_price):
        """不发请求：只算出「会提交什么」，给 DRY-RUN / 控制台预览用"""
        ids = self.ids_of(key)
        try:
            v = float(unit_price)
        except Exception:
            v = None
        return {"key": key, "ids": ids, "unit_price": v,
                "rows": [{"id": int(i), "gid": self.gid_of(key), "min_qty": 0,
                          "unit_price": ("%.5f" % v) if v is not None else None,
                          "cprice": None} for i in ids]}


class CacheRefresher(object):
    """改价成功之后清缓存，前端才会立刻刷出新价。

    ⚠ 未完全验证：后台菜单里确实有「清空缓存」→ `/admin/setting/clearcache.html`，
    但**触发方式是 GET 还是 POST 没实测过**（上一轮只做了只读探查）。
    所以这里按「先 POST 再 GET」尽力尝试，失败一律返回 False，
    由调用方降级成「请手动清缓存」的提示 —— 绝不因为清缓存失败去猜接口。
    """

    def __init__(self, host, user=None, pw=None, log=print):
        self.base = str(host or "").rstrip("/")
        self.acc = {"username": user or "", "password": pw or ""}
        self.log = log or (lambda *a: None)
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=self._ctx()))
        self.opener.addheaders = [("User-Agent", UA)]

    @staticmethod
    def _ctx():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _get(self, path, data=None):
        url = self.base + (path if str(path).startswith("/") else "/" + str(path))
        req = urllib.request.Request(url, data=data,
                                     headers={"X-Requested-With": "XMLHttpRequest"})
        with self.opener.open(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def login(self):
        """这个主后端的登录方式**没验证过**，所以只做「能不能打开清缓存页」的探活。"""
        if not self.acc.get("username"):
            return False
        try:
            html = self._get("/admin/setting/clearcache.html")
        except Exception as e:
            self.log("  [缓存] 打开清缓存页失败：%r" % e)
            return False
        return "clearcache" in html.lower() or "缓存" in html

    def clear_all(self):
        cand = [(self.base + "/admin/setting/clearcache.html", b"", "POST"),
                (self.base + "/admin/setting/clearcache.html", None, "GET")]
        for url, data, method in cand:
            try:
                if method == "GET":
                    html = self._get("/admin/setting/clearcache.html")
                    if "缓存" in html:
                        self.log("  [缓存] 已请求清缓存页（GET，未验证是否真清）")
                        return True
                else:
                    r = urllib.request.Request(url, data=data or b"",
                                               headers={"X-Requested-With": "XMLHttpRequest"})
                    with self.opener.open(r, timeout=30) as resp:
                        resp.read()
                    self.log("  [缓存] 已提交清缓存（POST，未验证是否真清）")
                    return True
            except Exception as e:
                self.log("  [缓存] %s 失败：%r" % (method, e))
        return False


# ------------------------------------------------------------------ 自检
def _selftest():
    import argparse
    ap = argparse.ArgumentParser(description="core_p2pah 自检（默认只读）")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--captcha", help="已识别的验证码（不给则先试会话复用）")
    ap.add_argument("--captcha-out", help="把验证码图存到这里")
    ap.add_argument("--items", action="store_true", help="登录后列出 D4 商品")
    ap.add_argument("--status", action="store_true", help="只看本地会话状态，不联网")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    cli = P2PAHClient(cfg)
    if a.status:
        print(json.dumps(cli.session_info(), ensure_ascii=False, indent=1))
        return 0
    if not a.captcha:
        r = cli.fetch_captcha(save_to=a.captcha_out)
        print(json.dumps({"captcha_png": r["path"], "bytes": r["bytes"],
                          "phpsessid": r["cookie"][:12] + "…"}, ensure_ascii=False, indent=1))
        print("→ 看完图后加 --captcha XXXX 再跑一次")
        return 0
    if not cli.login(a.captcha):
        print("登录失败")
        return 1
    if a.items:
        for it in cli.fetch_items(page=1):
            print("%-12s %-34s unit=%-10s sale=%-10s 折扣=%s 成本=%s" % (
                it["id"], it["name"][:34], it["unit_price"], it["sale_price"],
                it["discount"], it["cprice"]))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
