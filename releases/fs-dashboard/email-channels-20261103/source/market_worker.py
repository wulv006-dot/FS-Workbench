# -*- coding: utf-8 -*-
"""营销系统 · 本机执行服务（Marketing Local Worker）

为什么必须跑在本机
------------------
admin-api.p2pah.cn 有来源 IP 白名单，服务器 47.85.224.112 访问会被 403
（`No permission request`）。所以「页面」可以挂在 FS 运作台，但真正调接口的
动作必须由这台机器发起。

职责
----
  1. chenchaoapi 自动登录（无 2FA，验证码 ddddocr 本地识别）+ token 续命
  2. 拉游戏列表（582 个）并缓存，供「链接 → 游戏」匹配
  3. 拉现有广告位（store_entrance / ad_image），判断「已有→编辑 / 无→新建」
  4. 按业务规则预填 payload（标题拼接、位置、权重、状态、样式）
  5. 提交（默认 dry-run，只有显式 confirm=true 才真的写）
  6. 写完自动清缓存（前台才生效）

启动
----
    python market_worker.py            # 默认 127.0.0.1:8791
    python market_worker.py 8899       # 指定端口
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
CACHE = os.path.join(HERE, "_cache")
os.makedirs(CACHE, exist_ok=True)

BASE = "https://admin-api.p2pah.cn"
SITE = "https://admin.p2pah.cn"
USER = os.environ.get("P2PAH_USER", "chenchaoapi")
PW = os.environ.get("P2PAH_PW", "")
if not PW:
    # 本机凭据文件（不进仓库、不进日志）
    _cf = os.path.join(HERE, "_cache", "cred.json")
    if os.path.exists(_cf):
        try:
            _c = json.load(open(_cf, encoding="utf-8")) or {}
            USER = _c.get("user") or USER
            PW = _c.get("pw") or ""
        except Exception:
            pass
TOKEN_F = os.path.join(CACHE, "_token.json")
CK = os.path.join(CACHE, "_ck.txt")
CAP = os.path.join(CACHE, "_cap.png")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
HDR = ["-H", "User-Agent: " + UA,
       "-H", "Sec-Fetch-Dest: empty", "-H", "Sec-Fetch-Mode: cors",
       "-H", "Sec-Fetch-Site: same-site",
       "-H", "Origin: " + SITE, "-H", "Referer: " + SITE + "/",
       "-H", "server: true", "-H", "think-lang: zh-cn",
       "-H", "Accept: application/json, text/plain, */*"]

_lock = threading.Lock()


def log(msg):
    """pythonw 下 sys.stdout 可能是 None —— 所有输出都必须容错。"""
    try:
        print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)
    except Exception:
        pass


# ------------------------------------------------------------------ HTTP
def call(method, path, data=None, token=None, raw=False, out=None):
    dst = out or os.path.join(CACHE, "_body.tmp")
    cmd = ["curl", "-sS", "-g", "-o", dst, "-w", "%{http_code}", "--max-time", "45",
           "-X", method] + HDR
    if token:
        cmd += ["-H", "batoken: " + token]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json",
                "--data-binary", json.dumps(data, ensure_ascii=False)]
    if os.path.exists(CK):
        cmd += ["-b", CK, "-c", CK]
    cmd.append(BASE + path + ("&" if "?" in path else "?") + "server=1")
    r = subprocess.run(cmd, capture_output=True)
    body = open(dst, "rb").read() if os.path.exists(dst) else b""
    if raw:
        return r.stdout.decode().strip(), body
    txt = body.decode("utf-8", "ignore")
    try:
        return r.stdout.decode().strip(), json.loads(txt)
    except Exception:
        return r.stdout.decode().strip(), txt


def saved_token():
    try:
        return (json.load(open(TOKEN_F, encoding="utf-8")) or {}).get("token")
    except Exception:
        return None


def save_token(tok):
    json.dump({"token": tok, "ts": time.time()},
              open(TOKEN_F, "w", encoding="utf-8"))


# ------------------------------------------------------------------ 登录
def do_login():
    if not PW:
        raise RuntimeError("缺少 P2PAH_PW 环境变量（chenchaoapi 密码）")
    import ddddocr
    ocr = ddddocr.DdddOcr(show_ad=False)
    cap_f = os.path.join(CACHE, "_cap.png")
    for i in range(1, 13):
        cid = str(uuid.uuid4())
        st, png = call("GET", "/api/common/captcha?server=1&id=%s" % cid,
                       raw=True, out=cap_f)
        if not png or len(png) < 400:
            continue
        ans = re.sub(r"[^0-9A-Za-z]", "", ocr.classification(png) or "")
        if len(ans) != 4:
            continue
        st, j = call("POST", "/admin/login",
                     data={"username": USER, "password": PW, "captcha": ans,
                           "captcha_id": cid, "keep": True, "loading": False})
        if isinstance(j, dict) and j.get("code") == 1:
            tok = ((j.get("data") or {}).get("userInfo") or {}).get("token")
            if tok:
                save_token(tok)
                log("登录成功（第%d次，验证码=%s）" % (i, ans))
                return tok
    raise RuntimeError("登录失败：多次重试未通过")


def token(auto=True):
    with _lock:
        t = saved_token()
        if t:
            st, j = call("GET", "/admin/doc.NewsDetailAd/index?page=1&limit=1", token=t)
            if isinstance(j, dict) and j.get("code") == 1:
                return t
            log("token 失效，重新登录…")
        if not auto:
            return None
        return do_login()


def api_get(path, data=None):
    t = token()
    st, j = call("GET", path, data=data, token=t)
    if isinstance(j, dict) and j.get("code") == 302:
        t = do_login()
        st, j = call("GET", path, data=data, token=t)
    return j


def api_post(path, data):
    t = token()
    st, j = call("POST", path, data=data, token=t)
    if isinstance(j, dict) and j.get("code") == 302:
        t = do_login()
        st, j = call("POST", path, data=data, token=t)
    return j


# ------------------------------------------------------------------ 缓存
def games(force=False):
    f = os.path.join(CACHE, "games.json")
    if not force and os.path.exists(f) and time.time() - os.path.getmtime(f) < 86400:
        return json.load(open(f, encoding="utf-8"))
    j = api_get("/admin/site.game/gamelist")
    lst = []
    if isinstance(j, dict) and j.get("code") == 1:
        d = j.get("data")
        lst = d if isinstance(d, list) else (d.get("list") if isinstance(d, dict) else [])
    if lst:
        json.dump(lst, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return lst


def all_ads(force=False):
    """全量广告位（103 条规模，翻页取全）。"""
    f = os.path.join(CACHE, "ads.json")
    if not force and os.path.exists(f) and time.time() - os.path.getmtime(f) < 120:
        return json.load(open(f, encoding="utf-8"))
    out, page = [], 1
    while True:
        j = api_get("/admin/doc.NewsDetailAd/index?page=%d&limit=100" % page)
        if not (isinstance(j, dict) and j.get("code") == 1):
            break
        d = j.get("data") or {}
        rows = d.get("list") or []
        out += rows
        if len(out) >= (d.get("total") or 0) or not rows:
            break
        page += 1
    json.dump(out, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


# ------------------------------------------------------------------ 链接 → 游戏
def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def url_slug(url):
    """https://www.mmoexp.com/Path-of-exile/Currency.html -> path-of-exile"""
    try:
        p = urlparse(url).path.strip("/")
        seg = p.split("/")[0] if p else ""
        seg = re.sub(r"\.html?$", "", seg)
        return seg
    except Exception:
        return ""


def build_game_index(games_list, ads):
    """游戏匹配索引。

    游戏自带 `code` / `new_code`，就是前台 URL 的第一段路径
    （POE=path-of-exile / POE2=poe-2 / Diablo 4=diablo-4），
    所以「链接 → 游戏」可以精确匹配，不靠模糊猜。
    """
    idx = []
    for g in games_list:
        gid = str(g.get("id"))
        title = g.get("title") or g.get("name") or ""
        slugs = set()
        for k in ("code", "new_code"):
            v = norm(g.get(k))
            if v:
                slugs.add(v)
        aliases = {norm(title), norm(re.sub(r"\d+$", "", title))}
        idx.append({"id": gid, "title": title, "aliases": aliases,
                    "slugs": slugs, "link": g.get("link") or ""})

    by_id = {x["id"]: x for x in idx}
    # 用现有广告的 buy_url/link_url 再反学一批 slug（覆盖 code 缺失的游戏）
    for a in ads:
        gid = str(a.get("game_id"))
        ex = a.get("extra")
        if isinstance(ex, str):
            try:
                ex = json.loads(ex)
            except Exception:
                ex = {}
        for u in ((ex or {}).get("buy_url"), (ex or {}).get("link_url")):
            if u and str(u).startswith("http"):
                s = norm(url_slug(u))
                if s and gid in by_id:
                    by_id[gid]["slugs"].add(s)
    return idx


def match_game(url, idx):
    """链接 → 游戏：① code 精确 ② code 前缀(≥4位) ③ 标题别名"""
    slug = norm(url_slug(url))
    if not slug:
        return None, "无法解析链接路径"

    for g in idx:
        if slug in g["slugs"]:
            return g, "游戏 code 精确匹配"

    cands = []
    for g in idx:
        for s in g["slugs"]:
            if len(s) >= 4 and (slug.startswith(s) or s.startswith(slug)):
                cands.append((len(s), g, s))
    if cands:
        cands.sort(key=lambda x: -x[0])
        return cands[0][1], "游戏 code 前缀匹配（%s）" % cands[0][2]

    best = None
    for g in idx:
        for a in g["aliases"]:
            if a and len(a) >= 4 and (a == slug or a in slug or slug in a):
                if best is None or len(a) > len(best[1]):
                    best = (g, a)
    if best:
        return best[0], "标题匹配（%s）" % best[1]
    return None, "未匹配到游戏，请手动指定"


# ------------------------------------------------------------------ 业务规则
def plan_store_entrance(payload):
    """商店入口：链接列表 → 每条的计划（编辑/新建 + 预填字段）"""
    links = [x.strip() for x in (payload.get("links") or []) if x.strip()]
    festival = (payload.get("festival") or "").strip()
    cta = (payload.get("cta") or "").strip()
    manual = payload.get("game_id") or {}

    gs = games()
    ads = all_ads()
    idx = build_game_index(gs, ads)
    existing = {}
    for a in ads:
        if a.get("ad_type") == "store_entrance":
            existing.setdefault(str(a.get("game_id")), []).append(a)

    plans = []
    for url in links:
        gid = manual.get(url)
        if gid:
            g = next((x for x in idx if x["id"] == str(gid)), None)
            why = "手动指定"
        else:
            g, why = match_game(url, idx)
        item = {"url": url, "game": None, "why": why, "action": None,
                "target_id": None, "payload": None, "warn": []}
        if not g:
            item["warn"].append("未匹配到游戏")
            plans.append(item)
            continue
        item["game"] = {"id": g["id"], "title": g["title"]}
        cur = existing.get(g["id"]) or []
        # 一个游戏可以有多个入口（如 POE2 的「通货入口」和「物品入口」），
        # 所以必须先按 buy_url 精确对号：同链接 = 编辑那条；不同 = 新建一条，
        # 绝不能拿「第一条」去覆盖，否则会把通货入口改成物品入口。
        target, same = None, None
        for a in cur:
            ex = a.get("extra")
            if isinstance(ex, str):
                try:
                    ex = json.loads(ex)
                except Exception:
                    ex = {}
            if norm(str((ex or {}).get("buy_url") or "")) == norm(url):
                target = a
                break
        if target:
            item["action"] = "edit"
            item["target_id"] = target.get("id")
            base = dict(target)
            item["warn"].append("链接与现有 #%s 一致，将编辑该条"
                                % target.get("id"))
        elif cur:
            item["action"] = "create"
            base = {}
            ids = "、".join("#%s" % a.get("id") for a in cur[:5])
            item["warn"].append("该游戏已有 %d 个其他入口（%s），链接不同→按新入口新建"
                                % (len(cur), ids))
        else:
            item["action"] = "create"
            base = {}

        title = "%s%s商店入口" % (festival, g["title"]) if festival else \
                "%s商店入口" % g["title"]
        extra = {"goods_id": 0, "buy_url": url}
        if cta:
            extra["cta_text"] = cta
        item["payload"] = {
            "id": base.get("id") or 0,
            "site_id": base.get("site_id") or 266,
            "ad_type": "store_entrance",
            "position": "right",          # 用户规则：固定右
            "game_id": int(g["id"]) if str(g["id"]).isdigit() else g["id"],
            "title": title,
            "tag_ids": base.get("tag_ids") or [],   # 默认不填
            "weigh": 0,                   # 用户规则：默认 0
            "status": 1,                  # 用户规则：默认打开
            "extra": extra,   # 已验证：save 接受对象（与 get 返回同构）
        }
        plans.append(item)
    return {"ok": True, "plans": plans, "festival": festival, "cta": cta}


def plan_ad_image(payload):
    """广告图批量：图片 + 跳转链接 → 每条计划"""
    items = payload.get("items") or []
    plans = []
    gs = games()
    ads = all_ads()
    idx = build_game_index(gs, ads)
    for it in items:
        url = (it.get("link_url") or "").strip()
        up = it.get("upload_id")
        gid = it.get("game_id")
        item = {"link_url": url, "game": None, "action": "create",
                "payload": None, "warn": []}
        g = None
        if gid:
            g = next((x for x in idx if x["id"] == str(gid)), None)
        if not g and url:
            g, why = match_game(url, idx)
            if why:
                item["warn"].append(why)
        if not g:
            item["warn"].append("未匹配到游戏")
            plans.append(item)
            continue
        item["game"] = {"id": g["id"], "title": g["title"]}
        if not up:
            item["warn"].append("缺图片 upload_id（待上传）")
        extra = {"image_style": "simple", "upload_id": up or 0, "link_url": url}
        item["payload"] = {
            "id": 0,
            "site_id": 266,
            "ad_type": "ad_image",
            "position": (it.get("position") or "top"),
            "game_id": int(g["id"]) if str(g["id"]).isdigit() else g["id"],
            "title": it.get("title") or ("广告图 #%s" % g["id"]),
            "tag_ids": [],
            "weigh": 0,
            "status": 1,
            "extra": extra,   # 已验证：save 接受对象（与 get 返回同构）
        }
        plans.append(item)
    return {"ok": True, "plans": plans}


# ------------------------------------------------------------------ 提交
SAVE_PATH = "/admin/doc.NewsDetailAd/save"
CLEAR_PATH = "/admin/doc.NewsDetailAd/clearCache"


def execute(plans, confirm=False):
    """dry-run 默认；confirm=True 才真的写。写完清缓存。"""
    results = []
    for p in plans:
        body = p.get("payload")
        if not body:
            results.append({"skip": True, "reason": "无 payload"})
            continue
        if not confirm:
            results.append({"dry_run": True, "payload": body})
            continue
        j = api_post(SAVE_PATH, body)
        ok = isinstance(j, dict) and j.get("code") == 1
        results.append({"ok": ok, "resp": j if not ok else {"code": 1,
                                                            "id": (j.get("data") or {}).get("id")
                                                            if isinstance(j.get("data"), dict) else None}})
    if confirm and any(r.get("ok") for r in results):
        try:
            api_post(CLEAR_PATH, {})
            log("已清缓存")
        except Exception as e:
            log("清缓存失败：%r" % e)
    return results


# ------------------------------------------------------------------ HTTP 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "FSMarketing/0.1"

    def log_message(self, fmt, *args):
        """pythonw 下 stderr 为 None，默认实现会崩，这里静默。"""
        pass

    def _send(self, obj, code=200, ctype="application/json; charset=utf-8"):
        data = obj if isinstance(obj, bytes) else \
            json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self._send({}, 204)

    def do_GET(self):
        if self.path.startswith("/api/email/"):
            from email_channels import handle
            if handle(self):
                return
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            if p in ("/", "/index.html", "/marketing.html"):
                f = os.path.join(WEB, "marketing.html")
                return self._send(open(f, "rb").read(), 200,
                                  "text/html; charset=utf-8")
            if p == "/api/health":
                return self._send({"ok": True, "login": bool(token(auto=False)),
                                   "time": time.strftime("%Y-%m-%d %H:%M:%S")})
            if p == "/api/games":
                gs = games()
                return self._send({"ok": True, "count": len(gs), "games": gs})
            if p == "/api/ads":
                ads = all_ads(force="fresh" in q)
                t = (q.get("type") or [""])[0]
                if t:
                    ads = [a for a in ads if a.get("ad_type") == t]
                return self._send({"ok": True, "count": len(ads), "ads": ads})
            self._send({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._send({"ok": False, "error": repr(e)}, 500)

    def do_POST(self):
        if self.path.startswith("/api/email/"):
            from email_channels import handle
            if handle(self):
                return
        u = urlparse(self.path)
        p = u.path
        try:
            body = self._body()
            if p == "/api/plan/store_entrance":
                return self._send(plan_store_entrance(body))
            if p == "/api/plan/ad_image":
                return self._send(plan_ad_image(body))
            if p == "/api/execute":
                return self._send({"ok": True,
                                   "results": execute(body.get("plans") or [],
                                                      bool(body.get("confirm")))})
            if p == "/api/relogin":
                return self._send({"ok": True, "token": bool(do_login())})
            self._send({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._send({"ok": False, "error": repr(e)}, 500)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    # 允许端口被快速重用（重启服务时不至于卡在 TIME_WAIT）
    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log("=" * 52)
    log(" 营销系统 · 本机执行服务 已启动")
    log(" 打开： http://127.0.0.1:%d/" % port)
    log(" 账号： %s（自动登录，无需人工）" % USER)
    log("=" * 52)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("已停止")


if __name__ == "__main__":
    # pythonw 下 sys.stdout 为 None，reconfigure 会抛异常直接退出，必须容错
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        main()
    except Exception:
        # 无窗口模式下把崩溃原因落盘，便于排查
        try:
            import traceback
            with open(os.path.join(CACHE, "worker_error.log"), "a",
                      encoding="utf-8") as f:
                f.write("\n=== %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise
