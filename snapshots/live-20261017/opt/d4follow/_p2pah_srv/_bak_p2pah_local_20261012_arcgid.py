# -*- coding: utf-8 -*-
"""后台改价 · 本机执行器（order.p2pah.cn）

为什么必须在本机跑
------------------
2026-09-23 实测对照：**同一个会话 cookie**请求后台产品列表，
  本机（家用 IP）→ HTTP 200、450KB、201 行商品
  服务器（47.253.252.55，阿里云美区）→ **HTTP 404、0 字节**
⇒ order.p2pah.cn 按来源 IP 挡住了机房 IP。改价的写请求只能在能打开后台的机器上发。
（服务器侧仍负责：采集 / 算价 / 出计划 / 存历史 —— 那些都不碰后台。）

为什么用「真浏览器 + 页面内 fetch」而不是 urllib
-----------------------------------------------
- 登录是图形验证码，脚本没法长期免人工 → 用 Playwright 持久化 profile 做**会话复用**：
  登录一次，之后每次自动复用（失效时用 `login` 子命令再登一次，人工认 4 位码）。
- 用**页面内 fetch**（同源）发请求，cookie 由浏览器自动带上，
  不用手工搬运/拼 Cookie 头，也不会踩「cookie 没发出去」这类坑。

子命令
------
  python p2pah_local.py login                 # 打开登录页，导出验证码，等答案文件，登录
  python p2pah_local.py read                  # 只读：核对 9 个对标商品（绝不动数据）
  python p2pah_local.py write --plan plan.json [--confirm]
                                              # 按计划改「物品」价；不加 --confirm 只预演
  python p2pah_local.py writegold --plan gold_plan.json [--confirm]
                                              # 按计划改「金币」采购成本 → 同步价格 → 清缓存
  python p2pah_local.py clearcache            # 单独清一次后台缓存

金币与物品是**两套机制**（2026-09-24 探明）
------------------------------------------
· 物品：改「产品价格管理」的 `$每个价格`（goodsEdit，JSON 数组）。
· 金币：改「金币价格管理」的 `采购成本`（itemEdit，urlencoded data_type/data_val）。一行 = 一个服务区。
  换算：b2c($/M) = 采购成本(￥/M) ÷ 汇率 ÷ (1−利润率)；前端每 M 价 = b2c；N 档价 = b2c × N。
· 🔴 金币改完**必须点右上角「同步价格」**前端才刷新，且该弹窗里的**「所有区」永不勾选**。


安全
----
- `read` 只发 GET，永远不改数据。
- `write` 必须显式 `--confirm`；改完自动复核一遍列表，逐件比对目标价。
- 每个 key 的**重复上架**（如 CRUX_X10 两条）会一起改 —— 少改一条前端可能仍显示旧价。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time

# 主后台 admin.p2pah.cn 的「工具箱 → 缓存管理 → 一键清理所有」—— **前端刷新的关键一步**。
# 用户 2026-09-24 原话：「点了同步价格后，前端当然不会立即变动，我都说了要去另外一个后台
#   找到工具箱，点击缓存管理 - 一键清除所有，前端才会显示；这个清除缓存的操作得在我本机执行」
# 同目录模块；缺失时降级成「请手动清」，绝不猜接口。
try:
    import admin_cache_local as admin_cache
except Exception:                                     # pragma: no cover
    admin_cache = None
from urllib.parse import quote_plus, parse_qs, urlparse

# 🔴 2026-09-26 必修：**别删这段**。
#   worker 用 `subprocess.run(..., stdout=PIPE)` 起本脚本，并**按 UTF-8 解**输出；
#   而本脚本的 stdout 默认取 Windows 本地代码页（GBK，cp936）。于是 `log()` 里
#   随便一个 `✓`（U+2713）就会抛 UnicodeEncodeError：
#       UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'
#   实测后果很严重 —— 金币单**写价已经成功**，却在打印结果那行崩掉：
#   进程直接死，后面的「复核 + 清缓存」全没跑，工单被记成 failed。
#   （09:29 那单侥幸成过：当时 worker 是从带 PYTHONUTF8 的会话里起的。）
#   这里把两个流强制成 UTF-8 + errors=replace：与 worker 的 UTF-8 解码对齐，
#   且即使某个字符真编不出来也只会替换成 `?`，**永远不会因为打日志而中断业务**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from playwright.sync_api import sync_playwright

# 会话过期的兜底：用账号密码 + 本地离线 OCR（ddddocr）自动重登，见 p2pah_autologin.py。
# 模块缺失只是「失去兜底能力」，不该让整个执行器起不来 —— 所以吞掉异常降级。
try:
    import p2pah_autologin as autologin
except Exception:                                     # pragma: no cover
    autologin = None

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://order.p2pah.cn"
LOGIN_URL = BASE_URL + "/admin"
LIST_TMPL = "/game/admin_game_price/index_item.html?gid=456&aid=15711&cid=&keyword=&page="
WRITE_URL = "/game/admin_game_price/goodsEdit"
# ── 金币（金币价格管理，一行 = 一个服务区；行 ID 就是服务区 ID） ──
#    金币和物品是**两套机制**：金币唯一可改的量是「采购成本」，
#    改完必须点右上角「同步价格」前端才会刷新（2026-09-24 实测确认）。
GOLD_LIST_URL = "/game/admin_game_price/index.html?gid=456&keyword=&page=1"   # 兼容：暗黑4
# 2026-10-01：金币工单可能属于**任意游戏**（D4 / AION2 / …），而「金币价格管理」
# 列表页是按 gid 分表的 —— 写死 456 会去读暗黑4的表，AION2 的行永远找不到，
# 且**不报错**（gold_rows 返回空 dict，看起来像"后台没有数据"）。
# ⇒ 一律走 gold_list_url(gid)，gid 由工单的「游戏」字段决定。
GOLD_GID = {"暗黑破坏神4": "456", "D4": "456", "AION2": "826", "永恒之塔2": "826",
            # 2026-10-08 接入：gid 1300 = 「MapleStory Classic World」（冒险岛怀旧服国际服）
            #   实测金币价格管理页 5 行（21746 雪吉拉 / 21748 菇菇寶貝 / 21754 Global World /
            #   22434 US / 22600 Main Server [US]），我们只改 21754。
            "MapleStory Classic World": "1300", "MSCW": "1300",
            "冒险岛怀旧服": "1300", "冒险岛怀旧服国际服": "1300",
            "MapleStory": "1300", "MapleStory Classic": "1300"}


def gold_gid_of(cfg, game_or_key):
    """游戏名/key → 金币价格管理的 gid。

    ① 先查内置表 GOLD_GID（游戏中文名 / 短码）
    ② 再查 config.p2pah.游戏.<短码>.game_id
    ③ 查不到 → 抛错（**绝不默认 456**，否则会把 AION2 写到暗黑4）
    """
    s = str(game_or_key or "").strip()
    if s in GOLD_GID:
        return GOLD_GID[s]
    games = ((cfg or {}).get("p2pah") or {}).get("游戏") or {}
    ent = games.get(s)
    if isinstance(ent, dict) and ent.get("game_id"):
        return str(ent["game_id"])
    # 反向匹配：条目里的 我方名 / 中文名 命中
    for k, v in games.items():
        if not isinstance(v, dict):
            continue
        if s and s in (str(v.get("我方名") or ""), str(v.get("中文名") or "")):
            return str(v.get("game_id") or "")
    raise KeyError("取不到 %r 的金币 gid（config.p2pah.游戏 里没登记？）" % s)


def gold_list_url(gid=None):
    """金币价格管理列表页 URL。⭐ gid 必须按游戏给（见 GOLD_GID 注释）。"""
    g = str(gid) if gid else "456"
    return "/game/admin_game_price/index.html?gid=%s&keyword=&page=1" % g
GOLD_EDIT_URL = "/game/admin_game_price/itemEdit"        # + ?ids=<行ID>
GOLD_ROW_ID_FIELD = "ids"
# 「清除全部」（后台 设置 → 清除缓存 → 清除全部；也叫"一键清除所有"）
# ⚠ 它是**对话框式页面**，不是 JSON ajax：直接跳转过去，页面正文就是「缓存已更新！」。
#    用 fetch 打它回的是 HTML —— 那不代表没执行，别据此判断成败（2026-09-24 踩过）。
CLEAR_CACHE_URL = BASE_URL + "/admin/setting/clearcachepost.html"
CLEAR_CACHE_OK = "缓存已更新"

DEFAULT_PROFILE = os.path.join(HERE, "_edge_p2pah")
DEFAULT_CFG = os.path.join(HERE, "..", "改造后v10", "config.json")
CAPTCHA_PNG = os.path.join(HERE, "_captcha.png")
CAPTCHA_ANS = os.path.join(HERE, "_capans.txt")
COOKIE_OUT = os.path.join(HERE, "p2pah_cookies.json")

ROW_RE = re.compile(
    r'<tr\s+data-id="(?P<id>\d+)"\s+data-gid="(?P<gid>[^"]*)"\s+class="jq-each-item">'
    r'(?P<body>.*?)</tr>', re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
UP_RE = re.compile(r'name="unit_price"[^>]*value="([^"]*)"')
CP_RE = re.compile(r'name="cprice"[^>]*value="([^"]*)"')
# 金币价格管理页：<tr data-id="15711" data-url="/game/admin_game_price/itemEdit">
GOLD_TR_RE = re.compile(r'<tr\s+data-id="(\d+)"[^>]*>(.*?)</tr>', re.S)
TD_ATTR_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
# 分页链接里的页码（2026-09-25 晚加：ARC 后台单服 660 行 = 4 页，只读第 1 页会漏 460 行）
PAGE_NUM_RE = re.compile(r"[\?&]page=(\d+)")
# 一个游戏的后台商品超过这么多 key 时，逐 key 关键词搜索就太慢了
# （626 个 key × 2~3 秒 = 半小时）。改为直接翻完整个 gid 的列表。
KEYWORD_SEARCH_MAX = 40

# 会话过期时的自动重登开关（main() 按 --no-auto-login 覆盖；用 list 是为了可写）
AUTO_LOGIN = [True]


def log(msg):
    """打印一行日志。**绝不抛异常** —— 曾经的 UnicodeEncodeError 让整个改价流程死在
    打印结果那一步（写已成功，复核与清缓存却没跑）。"""
    ts = dt.datetime.now().strftime("%H:%M:%S")
    try:
        print("[%s] %s" % (ts, msg), flush=True)
    except Exception:
        try:
            print("[%s] %s" % (ts, str(msg).encode("ascii", "replace").decode("ascii")),
                  flush=True)
        except Exception:
            pass


def text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    for a, b in (("&amp;", "&"), ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"')):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or "").replace(",", ""))
    return float(m.group(0)) if m else None


def parse_rows(html):
    """按 <tr> 解析。列序（后台表头）：ID/所属游戏/所属服务区/产品类型/产品名/
    每份数量/最少购买量/库存总量/折扣/$每个价格/销售价格(单价)/￥采购成本
    ⇒ 产品名固定是第 5 个 td（索引 4），别用「第一个像名字的」猜（会取到「Diablo 4」）。

    2026-09-25 晚：额外带出 `area`（索引 2 = 所属服务区）与 `ptype`（索引 3 = 产品类型）。
    多游戏接入（ARC 的 PC/PS/XBOX、DND 的 Main Server）靠 `area` 才能把前台商品
    对应到该平台那一行；否则 1940 行混在一起，跨平台同规格会认错行。
    """
    out = []
    for m in ROW_RE.finditer(html or ""):
        tds = [text(x) for x in TD_RE.findall(m.group("body"))]
        name = tds[4] if len(tds) > 4 else ""
        if not name or name.isdigit():
            name = next((t for t in tds if t and not t.isdigit()
                         and "$" not in t and "￥" not in t and t != "Diablo 4"), "")
        up, cp = UP_RE.search(m.group("body")), CP_RE.search(m.group("body"))
        out.append({"id": m.group("id"), "gid": m.group("gid"), "name": name,
                    "area": tds[2] if len(tds) > 2 else "",
                    "ptype": tds[3] if len(tds) > 3 else "",
                    "per": tds[5] if len(tds) > 5 else "",
                    "min_qty": tds[6] if len(tds) > 6 else "",
                    "unit_price": num(up.group(1)) if up else None,
                    "cprice": num(cp.group(1)) if cp else None,
                    "discount": next((num(t) for t in tds if t in ("90", "100", "95")), None)})
    return out


class Session(object):
    def __init__(self, profile, keep_open=False):
        self._p = sync_playwright().start()
        self.ctx = self._p.chromium.launch_persistent_context(
            profile, channel="msedge", headless=not keep_open,
            viewport={"width": 1400, "height": 950})
        self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self._inject_saved_cookies()
        # 会话过期兜底所需的账号密码（_accounts.json → config.json → 内置默认）
        self.auto_login = bool(AUTO_LOGIN[0]) and (autologin is not None)
        try:
            _a = autologin.accounts()["order"]
            self.user = _a.get("username") or ""
            self.pw = _a.get("password") or ""
        except Exception:
            self.user = self.pw = ""

    def _inject_saved_cookies(self):
        """把导出的 cookie 注回浏览器。

        ⚠ 必须这么做：`PHPSESSID` 是**会话级 cookie**（expires=-1），浏览器关闭后
        不会落盘到 profile，下次打开就没了 —— 只靠 profile 会每次都被弹回登录页。
        """
        if not os.path.exists(COOKIE_OUT):
            return 0
        try:
            ck = json.load(io.open(COOKIE_OUT, encoding="utf-8"))
        except Exception:
            return 0
        exp = time.time() + 30 * 86400
        out = []
        for c in ck:
            if not c.get("domain", "").endswith("order.p2pah.cn"):
                continue
            c = dict(c)
            c["expires"] = exp          # 会话级 → 给个 30 天过期，才会被持久化
            c["secure"] = False
            c.pop("sameSite", None)
            out.append(c)
        if out:
            self.ctx.add_cookies(out)
        return len(out)

    def save_cookies(self):
        """把当前 cookie 落盘。

        **必须做**：`PHPSESSID` 是会话级 cookie（expires=-1），浏览器一关就不会写进
        profile；靠这个文件在下次启动时 `add_cookies` 注入，会话才能跨进程复用。
        """
        try:
            ck = [c for c in self.ctx.cookies()
                  if c.get("domain", "").endswith("order.p2pah.cn")]
            io.open(COOKIE_OUT, "w", encoding="utf-8").write(
                json.dumps(ck, ensure_ascii=False, indent=1))
            return len(ck)
        except Exception:
            return 0

    def _auto_relogin(self):
        """被弹回登录页时的兜底：账号密码 + 本地离线 OCR 自动重登（无人值守）。

        为什么不另起一个浏览器：`_edge_p2pah` 这个 user-data-dir 是**互斥**的，
        常驻执行器正占着它时另开一个必然失败。就地重登顺带把新 cookie 留在同一上下文。
        """
        if not self.auto_login:
            return False
        if not (self.user and self.pw):
            log("   ⚠ 会话已失效，但没有账号密码（_accounts.json / config.json → p2pah.账号）")
            return False
        log("   ⚠ order 会话已失效（被弹回登录页）→ 用账号密码自动重登…")
        try:
            ok = autologin.login_order_in(self.pg, self.user, self.pw, log=log)
        except Exception as e:
            log("   ⚠ 自动重登异常：%r" % e)
            return False
        if not ok:
            log("   ✘ 自动重登失败（退人工：python p2pah_local.py login）")
            return False
        log("   ✓ 已自动重登，会话恢复（cookie 已刷新 %d 个）" % self.save_cookies())
        return True

    def logged_in(self, auto=None):
        """探活。会话已失效时**默认自动重登**（`--no-auto-login` 可关掉）。"""
        self.pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        self.pg.wait_for_timeout(1500)
        if "login.html" not in self.pg.url:
            self.save_cookies()            # 顺手刷新落盘，保证跨进程可复用
            return True
        if auto is None:
            auto = self.auto_login
        return self._auto_relogin() if auto else False

    def reopen(self, opener):
        """目标页被弹回登录页（会话中途失效）时的补救：自动重登 → 重开一次。

        `logged_in()` 通过之后、真正打开列表页之前，会话仍可能刚好过期；
        这时不该直接把工单判死，而是重登一次再开。
        """
        if "login.html" not in self.pg.url:
            return True
        log("   ⚠ 目标页被弹回登录页（会话中途失效）")
        if not self._auto_relogin():
            return False
        opener()
        return "login.html" not in self.pg.url

    def read_rows(self, url=LIST_TMPL, wait=2500, keyword=None):
        if keyword:
            url = (LIST_TMPL.replace("keyword=", "keyword=" + quote_plus(keyword))
                   .replace("&page=", "&page="))

        def _open():
            self.pg.goto(BASE_URL + url, wait_until="domcontentloaded", timeout=60000)
            self.pg.wait_for_timeout(wait)

        _open()
        if not self.reopen(_open):
            raise SystemExit("会话已失效（被弹回登录页），自动重登也没成功。"
                             "请人工跑：python p2pah_local.py login")
        return parse_rows(self.pg.content())

    def write_rows(self, rows):
        """在页面内做同源 fetch —— cookie 由浏览器自动带上"""
        js = """
        async (rows) => {
          const r = await fetch(%r, {
            method: 'POST',
            headers: {'Content-Type': 'application/json',
                      'X-Requested-With': 'XMLHttpRequest'},
            body: JSON.stringify(rows)
          });
          const t = await r.text();
          return {status: r.status, body: t.slice(0, 400)};
        }
        """ % WRITE_URL
        res = self.pg.evaluate(js, rows)
        try:
            j = json.loads(res.get("body") or "{}")
        except Exception:
            j = {"code": 0, "msg": (res.get("body") or "")}
        return {"ok": int(j.get("code") or 0) == 1, "msg": j.get("msg") or res.get("body"),
                "http": res.get("status"), "raw": res.get("body")}

    # ------------------------------------------------------------ 金币（金币价格管理）
    def gold_rows(self, wait=2500, gid=None):
        """读「金币价格管理」的行：一行 = 一个服务区，行 ID 就是服务区 ID。

        ⚠ 页面里 c2c / g2g / eldorado 三列被 **HTML 注释**包着，注释里还留着一份
          `<input value="0.2/0.1/0.15">` —— 不剥注释直接按 td 正则扫，注释里的值会
          覆盖真值（实测 b2c 被读成 0.200000，而真值是 3.8E-5，极难发现）。
        返回 {行ID: {"costprice":..., "lirunlv":..., "b2c":..., "title":...}}
        """
        _url = gold_list_url(gid)

        def _open():
            self.pg.goto(BASE_URL + _url, wait_until="domcontentloaded", timeout=60000)
            self.pg.wait_for_timeout(wait)

        _open()
        if not self.reopen(_open):
            raise SystemExit("会话已失效（被弹回登录页），自动重登也没成功。"
                             "请人工跑：python p2pah_local.py login")
        html = re.sub(r"<!--[\s\S]*?-->", "", self.pg.content())
        out = {}
        for m in GOLD_TR_RE.finditer(html):
            rid, body = m.group(1), m.group(2)
            if "toggle-input" not in body:
                continue
            rec = {"id": rid}
            for attrs, inner in TD_ATTR_RE.findall(body):
                t = re.search(r'data-type="([^"]*)"', attrs)
                v = re.search(r'<input[^>]*value="([^"]*)"', inner)
                if t:
                    rec[t.group(1)] = v.group(1) if v else None
            out[rid] = rec
        return out

    def set_gold_cost(self, row_id, value):
        """改「金币价格管理」某行的**采购成本**。

        这是照抄页面行为：双击单元格后 $.post(row.data-url + ?ids=<行ID>,
        {data_type:'costprice', data_val:<值>})。金币只能改这一个量；
        利润率/b2c 都是只读派生值，改不了也不该改。
        """
        js = """
        async (a) => {
          const [url, dt, dv] = a;
          const body = 'data_type=' + encodeURIComponent(dt) + '&data_val=' + encodeURIComponent(dv);
          const r = await fetch(url, {method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                      'X-Requested-With': 'XMLHttpRequest'},
            body: body});
          const t = await r.text();
          return {status: r.status, body: t.slice(0, 400)};
        }
        """
        res = self.pg.evaluate(js, [GOLD_EDIT_URL + "?" + GOLD_ROW_ID_FIELD + "=" + str(row_id),
                                    "costprice", str(value)])
        try:
            j = json.loads(res.get("body") or "{}")
        except Exception:
            j = {"code": 0, "msg": res.get("body") or ""}
        return {"ok": int(j.get("code") or 0) == 1, "msg": j.get("msg") or res.get("body"),
                "http": res.get("status")}

    def sync_gold_price(self, wait_ms=8000, timeout_ms=25000, gid=None):
        """把金币算好的价**真正推给前端**（前端刷新必需的一步）。

        ⚠️ 2026-09-24 实测纠正（关键）：
          金币页右上角其实有**两个**东西，效果不同 ——
            · 刷新图标 `.jq-getweb`（title「更新b2c网站」）→ JS 里把 getweb 置 1 再触发下面的按钮
                → 实际请求 `saveprice.html?getweb=1&...`，返回 **{"code":1,"msg":"更新网站成功"}**
            · 按钮 `.jq-update-button`（文案「同步价格」，title「列表选中的网站」）→ 用当前的 getweb
                → 实际请求 `saveprice.html?getweb=0&...`，返回 {"code":1,"msg":"修改价格已推送"}
          **只点「同步价格」getweb=0 前端不会变**，必须走 `.jq-getweb`（getweb=1）。
          所以本方法默认点 `.jq-getweb`；找不到该元素时才回退点 `.jq-update-button`。

        🔴 硬闸：**「所有区」(allserver) 复选框永不勾选**（用户明确要求）。
           本方法点击前会先把 allserver 取消勾选，并把实际请求 URL 记下来，
           供调用方断言 URL 里**没有** allserver 参数。

        返回 {"ok":bool, "url":真实请求URL, "msg":返回提示, "getweb":str, "allserver":bool}
        """
        _url = gold_list_url(gid)

        def _open():
            self.pg.goto(BASE_URL + _url, wait_until="domcontentloaded", timeout=60000)
            self.pg.wait_for_timeout(2000)

        _open()
        if not self.reopen(_open):
            raise SystemExit("会话已失效（被弹回登录页），自动重登也没成功。"
                             "请人工跑：python p2pah_local.py login")
        # 硬闸：绝不勾「所有区」
        for el in self.pg.query_selector_all("input[name=allserver]"):
            try:
                if el.is_checked():
                    el.uncheck()
            except Exception:
                pass
        box = {"url": None, "status": None, "body": None}
        def _on_resp(r):
            if "saveprice" in r.url:
                box["url"] = r.url
                box["status"] = r.status
                try:
                    box["body"] = r.text()[:400]
                except Exception:
                    pass
        self.pg.on("response", _on_resp)
        try:
            # 优先走会真正推前端的路径：刷新图标（getweb=1）
            if self.pg.query_selector(".jq-getweb"):
                self.pg.click(".jq-getweb")
            else:
                self.pg.click(".jq-update-button")
            self.pg.wait_for_timeout(wait_ms)
        finally:
            try:
                self.pg.remove_listener("response", _on_resp)
            except Exception:
                pass
        url = box.get("url") or ""
        body = box.get("body") or ""
        ok = False
        try:
            j = json.loads(body)
            ok = int(j.get("code") or 0) == 1
            msg = j.get("msg") or body
        except Exception:
            msg = body
        try:
            getweb = parse_qs(urlparse(url).query).get("getweb", [""])[0]
        except Exception:
            getweb = ""
        return {"ok": ok, "url": url, "msg": msg, "getweb": getweb,
                "allserver": ("allserver=1" in url) or ("allserver%5B%5D=1" in url)}

    def log_gold_price(self, wait_ms=8000, gid=None):
        """补写后台「修改价格日志」——**点按钮「同步价格」(.jq-update-button)，即 saveprice getweb=0**。

        🔴 2026-10-01 实测定位（决定性 A/B 对照）：
          · 同一个 saveprice.html，两个入口写日志的行为**完全不同**：
              - `.jq-getweb`（刷新图标）    → `saveprice.html?getweb=1&...` → **不写日志**（零新增）
              - `.jq-update-button`（「同步价格」）→ `saveprice.html?getweb=0&...` → **写一条批量日志**
          实测：点 getweb=1 后日志不新增；点 getweb=0 后立刻新增一条，内容 = 当时后台
          全部行的（网站/游戏/服务区/区ID/利润率/成本/价格），一条日志含该次同步涉及的所有区。

        ⚠️ 与 `sync_gold_price`（getweb=1）的分工：
          · `sync_gold_price`（getweb=1）= **把价推给下游网站 / 让前端刷新**，必须保留；
          · `log_gold_price`（getweb=0）= **只为了让后台留下「修改价格日志」**，对价格无副作用
            （它只是把当前值提交一次，值本来就已写好）。
          两者都要点，缺一不可：只点 1 → 前台刷新但后台查不到日志（用户反馈的问题）；
          只点 0 → 有日志但前端不刷新。

        ⚠️ 硬闸同 `sync_gold_price`：**永不勾「所有区」(allserver)**。
        返回 {"ok", "url", "msg", "getweb", "allserver"}
        """
        _url = gold_list_url(gid)

        def _open():
            self.pg.goto(BASE_URL + _url, wait_until="domcontentloaded", timeout=60000)
            self.pg.wait_for_timeout(2000)

        _open()
        if not self.reopen(_open):
            raise SystemExit("会话已失效（被弹回登录页），自动重登也没成功。"
                             "请人工跑：python p2pah_local.py login")
        # 硬闸：绝不勾「所有区」
        for el in self.pg.query_selector_all("input[name=allserver]"):
            try:
                if el.is_checked():
                    el.uncheck()
            except Exception:
                pass
        box = {"url": None, "status": None, "body": None}

        def _on_resp(r):
            if "saveprice" in r.url:
                box["url"] = r.url
                box["status"] = r.status
                try:
                    box["body"] = r.text()[:400]
                except Exception:
                    pass
        self.pg.on("response", _on_resp)
        try:
            # 🔴 必须点「同步价格」按钮（getweb=0）——只有它写日志。
            #    千万不要改用 .jq-getweb：那是给前端刷新用的，不写日志。
            if self.pg.query_selector(".jq-update-button"):
                # 该按钮用的是隐藏域 getweb 的当前值；先确保它是 0
                try:
                    self.pg.evaluate(
                        "() => { const h=document.querySelector('[name=getweb]');"
                        " if(h) h.value='0'; }")
                except Exception:
                    pass
                self.pg.click(".jq-update-button")
            else:
                raise SystemExit("找不到「同步价格」按钮 .jq-update-button，无法补写日志")
            self.pg.wait_for_timeout(wait_ms)
        finally:
            try:
                self.pg.remove_listener("response", _on_resp)
            except Exception:
                pass
        url = box.get("url") or ""
        body = box.get("body") or ""
        ok = False
        try:
            j = json.loads(body)
            ok = int(j.get("code") or 0) == 1
            msg = j.get("msg") or body
        except Exception:
            msg = body
        try:
            getweb = parse_qs(urlparse(url).query).get("getweb", [""])[0]
        except Exception:
            getweb = ""
        return {"ok": ok, "url": url, "msg": msg, "getweb": getweb,
                "allserver": ("allserver=1" in url) or ("allserver%5B%5D=1" in url)}

    def clear_cache(self):
        """清空后台缓存（= 后台「设置 → 清除缓存 → 清除全部」按钮），让前端立即刷新。

        做法与真人一致：直接跳转到该端点。返回 (是否确认成功, 页面正文摘要)。
        ⚠ 清缓存是**延迟生效**的（实测 5~15 分钟前端才变），别紧接着抓一次没变就说没生效。
        """
        self.pg.goto(CLEAR_CACHE_URL, wait_until="domcontentloaded", timeout=60000)
        self.pg.wait_for_timeout(800)
        try:
            txt = self.pg.inner_text("body")
        except Exception:
            txt = self.pg.content()
        txt = re.sub(r"\s+", " ", txt or "").strip()
        return (CLEAR_CACHE_OK in txt), txt[:200]

    def close(self):
        try:
            self.ctx.close()
        finally:
            self._p.stop()


def load_cfg(path):
    p = os.path.normpath(path)
    if not os.path.exists(p):
        raise SystemExit("找不到 config.json：%s（用 --config 指定）" % p)
    return json.load(io.open(p, encoding="utf-8"))


def ids_of(cfg, key):
    """后台商品ID（含重复上架）"""
    p = (cfg.get("p2pah") or {})
    m = p.get("商品ID映射") or {}
    ids = []
    if isinstance(m.get(key), str):
        ids.append(m[key])
    dup = (m.get("_重复上架") or {}).get(key)
    if isinstance(dup, list):
        ids += [str(x) for x in dup]
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        if it.get("key") == key:
            v = (it.get("p2pah") or {}).get("后台商品ID")
            if v:
                ids.append(str(v))
    seen, out = set(), []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def mapping(cfg):
    """{key: 后台ID}，剔除 `_说明` / `_重复上架` 这类下划线开头的元数据键"""
    m = (cfg.get("p2pah") or {}).get("商品ID映射") or {}
    return {k: v for k, v in m.items() if isinstance(v, str) and not k.startswith("_")}


def keywords_of(cfg):
    """对照项里配的后台搜索关键词（列表默认分页，200 行/页，靠关键词才能精确定位）"""
    m = {}
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        kw = (it.get("p2pah") or {}).get("商品名关键词")
        if kw:
            m[it["key"]] = kw
    return m


# 撇号的各种写法（ASCII 直引号 + 全角/弯引号 + 修饰字母撇号 + 角分符号）
_APOS_CHARS = ("'", "\u2019", "\u2018", "\u02bc", "\u2032")


def _search_kw(kw):
    """把配置里的关键词转成**能送后台搜索**的形式。

    ⚠ 2026-09-26 加：order.p2pah.cn 的列表搜索**遇撇号 `'` 直接返回 0 行**。
    实测 6/6（D4 `Judicator's Mask`→0 行 / ARC `Dockmaster's Detector`→0 行 /
    DND `Dryad's Wrath(~)`→0 行 …），而截到撇号之前立刻命中同一行 ——
    因为后台是「包含」匹配，撇号前的部分仍是完整子串。

    截断结果 < 2 字符时退回原词（防止退化成「空关键词 = 拉全量列表」）。
    注意：配置里的关键词**不改**，前台匹配（core_front）还在用它。
    """
    if not kw:
        return kw
    best = None
    for a in _APOS_CHARS:
        i = kw.find(a)
        if i > 0 and (best is None or i < best):
            best = i
    if best is None:
        return kw
    head = kw[:best].strip()
    return head if len(head) >= 2 else kw


def game_of(cfg, key):
    """该 key 属于哪个游戏（对照项.游戏）；查不到按暗黑4"""
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        if it.get("key") == key:
            return it.get("游戏") or "暗黑破坏神4"
    return "暗黑破坏神4"


def game_gid_of(cfg, key):
    """按 key 取后台 gid（暗黑4=456、POE2=552）。

    ⚠ 2026-09-25 修：原来直接 `p2pah.游戏.get(对照项.游戏)`，但对照项写的是中文名
    （流放之路2），p2pah.游戏 的键是短码（POE2）→ 静默回退 456，POE2 会读到/写到
    D4 的表。现在带 `p2pah.游戏别名` + 条目内「我方名」三重兼容，与服务器侧
    engine.game_entry 同口径。
    """
    g = (cfg.get("p2pah") or {}).get("游戏") or {}
    p = cfg.get("p2pah") or {}
    gname = game_of(cfg, key)
    gm = g.get(gname) if isinstance(g.get(gname), dict) else None
    if gm is None:
        code = (p.get("游戏别名") or {}).get(gname)
        if code and isinstance(g.get(code), dict):
            gm = g[code]
    if gm is None:
        for _k, v in g.items():
            if isinstance(v, dict) and gname in (v.get("我方名"), v.get("中文名")):
                gm = v
                break
    if isinstance(gm, dict) and gm.get("game_id"):
        return str(gm["game_id"])
    return str((g.get("D4") or {}).get("game_id") or "456")


def list_url_of(gid, keyword="", aid="", cid="", page=""):
    """后台产品列表 URL。⭐ gid 必须按游戏给 —— 写死 456 会让 POE2 读到 D4 的表。

    ⚠ 2026-10-08 加 `cid`（原来写死空）：D4 赛季普通（gid=456 / aid=15711）后台全量
      **307 页 ≈ 6.1 万件**，配置登记的 359 个档位散在第 31~307 页。旧的两处硬上限
      （本机脚本 `--pages 30`、本文件 `read_all_pages(max_pages=40)`）只拿到最新约 10%
      ⇒ 闸一判「后台已找不到 ID」⇒ 359 档全部停手。按**产品类目** cid 定位每类目只需几页。
      cid 留空 = 老行为（全量列表，逐页翻）。
    """
    return ("/game/admin_game_price/index_item.html?gid=%s&aid=%s&cid=%s&keyword=%s&page=%s"
            % (gid, aid, cid or "", quote_plus(keyword or ""), page))


def read_all_pages(s, gid, aid="", wait=2000, max_pages=40, keyword="", need_ids=None,
                   cid=""):
    """把某个 gid 的商品列表**翻完**（默认一页 200 行）。

    ⚠ 2026-09-25 晚加：原 fetch_all_needed 只 `read_rows(url=list_url_of(gid))`，
      即只读第 1 页 = 200 行。ARC Raiders 后台单服 660 行（gid=864 共 1940 行 3 个服务区），
      只读 200 行 ⇒ 对照项里的「后台商品ID」大部分在 byid 里找不到 ⇒
      改价时被 `跳过 xxx：没有后台商品ID` 静默漏掉。这里按页面里的分页链接翻到底。

    ⭐ 2026-09-26 加 `need_ids`：只关心「这几个后台ID 找到没有」时，**找齐就提前收工**。
       不传 = 老行为（一直翻完，`readgame` 的 dump 就靠这个拿全量）。
       这是本项目最大的一个性能开关：D4 后台 gid=456 有 40 页 / 7900 行，
       一次全量翻页 ≈ 3.5 分钟 —— 而写价要「写前 + 复核」各跑一次。
       为了找 5 个后台ID 却翻满 40 页，就是那张 16 分钟改价单的根因。

    ⚠ 2026-10-08 更正上面的 40 页前提**是错的**：`min(页面最大页, max_pages)` 让人
       以为「D4 就 40 页」，其实 D4 赛季普通是 **307 页**，40 页只是被这个上限砍出来的
       假象。现在：
         · 新增 `cid`：按产品类目翻，每个类目几页（定位 D4 深页档位用这个）
         · `max_pages=None` = 不封顶，按页面分页控件真实最大页码翻完
       默认仍是 40，**对现有调用方零影响**。
    """
    need = set(str(x) for x in (need_ids or []))
    seen, rows = set(), []

    def _enough():
        return bool(need) and need <= seen

    first = s.read_rows(url=list_url_of(gid, keyword=keyword, aid=aid, cid=cid), wait=wait)
    for r in first:
        if r["id"] not in seen:
            seen.add(r["id"])
            rows.append(r)
    if _enough():
        log("    （需要的 %d 个后台ID 第 1 页就找齐，不翻后续页）" % len(need))
        return rows, 1
    nums = [int(x) for x in PAGE_NUM_RE.findall(s.pg.content() or "")]
    _real = max(nums) if nums else 1
    last = _real if max_pages is None else min(_real, max_pages)
    if max_pages is not None and _real > last:
        log("    ⚠ 分页控件最大 %d 页 > 上限 %d → 本轮只翻 %d 页（清单会被截断）"
            % (_real, max_pages, last))
    for p in range(2, last + 1):
        got = s.read_rows(url=list_url_of(gid, keyword=keyword, aid=aid, cid=cid,
                                          page=str(p)),
                          wait=wait)
        for r in got:
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
        if _enough():
            log("    （需要的 %d 个后台ID 第 %d 页找齐 → 提前收工，共 %d 页）"
                % (len(need), p, last))
            return rows, p
    return rows, last


# ── 商品类目映射（2026-10-08）──────────────────────────────────────────────
# 为什么需要它：D4 赛季普通（gid=456）全量列表 **335 页 ≈ 6.7 万件**，而配置登记的
# 359 个档位散在第 31~335 页。写价时 `fetch_all_needed` 对「> KEYWORD_SEARCH_MAX(40)
# 个 key」的 gid 会跳过逐条关键词搜索、直接翻全量兜底 —— 而全量兜底原来被
# `max_pages=40` 封顶 ⇒ 登记的深页档位永远找不到 ⇒ 「写后复核」必判不一致。
# 反过来把上限去掉，又要翻 335 页 ≈ 8 分钟 × 2 次（写前 + 复核）。
# 登记档位所属的**产品类目 cid 是已知的**（由 `_dump_by_cat.py` 按类目抓清单时落盘），
# 按 cid 逐类目读，每个类目只要 1~2 页 —— D4 全量 ≈ 15 页 / 30 秒。
CID_MAP_FILE = "item_cid.json"
_CID_MAP_CACHE = {}


def load_cid_map():
    """读 {gid: {"aid":.., "id2cid": {后台ID: cid}}}；文件缺失/坏掉一律返回 {}。

    查找顺序：脚本同目录 → 脚本同目录/data → /srv/data（容器内）。
    文件 mtime 变了就重读（`_dump_by_cat.py` 重新落盘后无需重启）。
    """
    paths = [os.path.join(HERE, CID_MAP_FILE),
             os.path.join(HERE, "data", CID_MAP_FILE),
             "/srv/data/" + CID_MAP_FILE]
    p = next((x for x in paths if os.path.exists(x)), None)
    if not p:
        return {}
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    if _CID_MAP_CACHE.get("path") == p and _CID_MAP_CACHE.get("mtime") == mt:
        return _CID_MAP_CACHE.get("map") or {}
    m = {}
    try:
        with io.open(p, encoding="utf-8") as f:
            j = json.load(f)
        if isinstance(j, dict) and isinstance(j.get("games"), dict):
            m = j["games"]
        elif isinstance(j, dict):
            m = {str(j.get("gid") or ""): {"aid": j.get("aid"),
                                           "id2cid": j.get("id2cid") or {}}}
    except Exception as e:                            # noqa: BLE001
        log("  ⚠ 读商品类目映射失败（%r）→ 退回全量翻页" % (e,))
        m = {}
    _CID_MAP_CACHE.update({"path": p, "mtime": mt, "map": m})
    return m


def read_needed_by_cid(s, gid, need_ids, aid="", wait=2000):
    """按「产品类目 cid」分组读列表，只翻每个类目自己的几页。

    返回 (byid, nocid, ncat)：
      byid  = {后台ID: 行}
      nocid = 没有 cid 映射、上层需要自己兜底的 ID 集合
      ncat  = 实际读的类目数（0 = 没有该 gid 的映射，等于什么都没做）

    2026-10-08 新增：D4 全量 335 页，全量兜底要么被 40 页封顶（找不到）、要么不封顶
    （8 分钟）—— 两者都不能接受。按类目读只要 ~15 页。
    """
    g = str(gid)
    ent = (load_cid_map() or {}).get(g) or {}
    id2cid = {str(k): str(v) for k, v in (ent.get("id2cid") or {}).items() if v}
    if not id2cid:
        return {}, set(str(x) for x in need_ids), 0
    _aid = str(aid or ent.get("aid") or "")
    need = set(str(x) for x in need_ids)

    todo = {}                                   # cid -> [ids]
    for i in need:
        c = id2cid.get(i)
        if c:
            todo.setdefault(c, []).append(i)
    nocid = need - set(i for v in todo.values() for i in v)

    byid = {}
    for cid, ids in sorted(todo.items(), key=lambda kv: -len(kv[1])):
        sub = set(ids)
        try:
            rows, npg = read_all_pages(s, gid, aid=_aid, wait=wait, cid=cid,
                                       need_ids=sub, max_pages=None)
        except Exception as e:                        # noqa: BLE001
            log("    ⚠ cid=%s 读类目失败：%r" % (cid, e))
            continue
        for r in rows:
            byid.setdefault(str(r["id"]), r)
        log("    · cid=%-6s 需要 %2d 个 → %d 页 / %d 行（本类目找齐 %d/%d）"
            % (cid, len(sub), npg, len(rows),
               len([i for i in sub if i in byid]), len(sub)))
    return byid, nocid, len(todo)


def fetch_all_needed(s, cfg, keys):
    """按 (游戏 gid + 关键词) 逐个搜索，汇总 {后台ID: 行}；最后再补一次各 gid 的全量兜底

    2026-09-25 多游戏改造：原来只有一条 D4 的 URL（gid=456&aid=15711），
    现在按 key 的游戏分组，POE2 走 gid=552。
    2026-09-25 晚：① 每个 gid 的全量兜底改成**翻完所有页**；
                    ② 该 gid 的 key 数 > KEYWORD_SEARCH_MAX 时跳过逐 key 搜索
                       （ARC/DND 一次接进来 500+ 个商品，逐 key 搜要跑半小时），
                       直接靠全量翻页拿齐。
    """
    byid = {}
    kws = keywords_of(cfg)
    by_gid = {}                      # gid -> [(key, kw)]
    for k in keys:
        gid = game_gid_of(cfg, k)
        by_gid.setdefault(gid, []).append((k, kws.get(k)))
    for gid, pairs in by_gid.items():
        used = set()
        if len(pairs) <= KEYWORD_SEARCH_MAX:
            for k, kw in pairs:
                if not kw or kw in used:
                    continue
                used.add(kw)
                # 2026-09-26 加：送搜索前按撇号截断（配置保持原文，见 _search_kw）。
                _kw2 = _search_kw(kw)
                try:
                    # 2026-09-26 修：原来只读第 1 页（200 行）。关键词偏宽时
                    # （例如为绕开后端搜不了撇号，只能用「Adept」= 252 行）
                    # 目标行在第 2 页就永远读不到 → 复核假不一致 → 连清缓存一起跳过。
                    # 改用 read_all_pages + 该 key 自己的 need_ids：找齐即收工，
                    # 关键词只有几行时仍只读 1 页，无性能回退。
                    _need_k = set(str(x) for x in (ids_of(cfg, k) or []))
                    rows, _npg = read_all_pages(s, gid, keyword=_kw2, need_ids=_need_k)
                    log("  搜索 gid=%s %-26s → %d 行（%d 页）%s"
                        % (gid, _kw2, len(rows), _npg,
                           ("  ← 原文 %r 含撇号，后端搜不了已截断" % kw)
                           if _kw2 != kw else ""))
                    for r in rows:
                        byid.setdefault(r["id"], r)
                except Exception as e:
                    log("  ⚠ 搜索 gid=%s %r 失败：%r" % (gid, kw, e))
        else:
            log("  gid=%s 有 %d 个对标商品（> %d）→ 跳过逐条搜索，直接翻全量列表"
                % (gid, len(pairs), KEYWORD_SEARCH_MAX))
        # ⭐ 2026-09-26：逐条搜索已经把该 gid 需要的后台ID 全找到了 → 不必再翻全量。
        #   单这一步就把 D4 改价单从「40 页 / 3.5 分钟 ×2 次」压到只翻必要的几页。
        need_ids = set()
        for k, _kw in pairs:
            for i in (ids_of(cfg, k) or []):
                need_ids.add(str(i))
        missing = need_ids - set(byid.keys())
        if need_ids and not missing:
            log("  gid=%s：需要的 %d 个后台ID 已全部找到，跳过全量翻页"
                % (gid, len(need_ids)))
            continue
        # ⭐ 2026-10-08：先按**产品类目**定位还没找到的 ID。
        #   D4 全量 335 页，全量兜底要么被 40 页封顶（登记的深页档位永远找不到 ⇒
        #   写后复核必判不一致）、要么不封顶（8 分钟 × 写前+复核 两次）。
        #   类目映射已知时，每个类目只要 1~2 页，D4 全部 ≈ 15 页 / 30 秒。
        if missing:
            try:
                got, nocid, ncat = read_needed_by_cid(s, gid, missing)
                if ncat:
                    for i, r in got.items():
                        byid.setdefault(i, r)
                    log("  gid=%s 按类目定位 → 读了 %d 个类目；缺 %d 个ID，"
                        "找到 %d 个，剩 %d 个无类目映射"
                        % (gid, ncat, len(missing),
                           len(missing) - len(nocid), len(nocid)))
                missing = nocid - set(byid.keys())
            except Exception as e:                    # noqa: BLE001
                log("  ⚠ gid=%s 按类目定位失败：%r（退回全量兜底）" % (gid, e))
        if not missing:
            log("  gid=%s：需要的后台ID 已全部拿到（按类目），跳过全量翻页" % gid)
            continue
        try:
            # 剩下的（没有类目映射的）才翻全量；`max_pages=None` = 不封顶，
            # 免得再被 40 页砍出「假象全量」。列表 < 40 页的游戏行为不变。
            rows, last = read_all_pages(s, gid, need_ids=missing, max_pages=None)
            log("  gid=%s 全量列表兜底 → %d 页 / %d 行（原还差 %d 个ID）"
                % (gid, last, len(rows), len(missing)))
            for r in rows:
                byid.setdefault(r["id"], r)
        except Exception as e:
            log("  ⚠ gid=%s 全量列表失败：%r" % (gid, e))
    return byid


# ---------------------------------------------------------------- 子命令
def cmd_login(a):
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            a.profile, channel="msedge", headless=False,
            viewport={"width": 1280, "height": 900})
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2000)
        log("当前地址：%s" % pg.url)
        if "login.html" not in pg.url:
            log("已经是登录态，不用重新登。cookie 已导出 → %s" % COOKIE_OUT)
            dump_cookies(ctx, a)
            ctx.close()
            return 0
        acc = (a.username, a.password)
        for attempt in range(1, 5):
            log("=== 第 %d 次验证码 ===" % attempt)
            if os.path.exists(CAPTCHA_ANS):
                os.remove(CAPTCHA_ANS)
            el = pg.query_selector("img.captcha")
            el.screenshot(path=CAPTCHA_PNG)
            log("验证码已存：%s —— 请打开它，把 4 位字符写进 %s" % (CAPTCHA_PNG, CAPTCHA_ANS))
            ans = None
            for _ in range(a.wait):
                if os.path.exists(CAPTCHA_ANS):
                    ans = io.open(CAPTCHA_ANS, encoding="utf-8").read().strip()
                    break
                time.sleep(1)
            log("收到答案：%r" % ans)
            if not ans:
                log("超时，退出")
                break
            pg.fill("input[name=username]", acc[0])
            pg.fill("input[name=password]", acc[1])
            pg.fill("input[name=captcha]", ans)
            pg.click("button.js-ajax-submit")
            pg.wait_for_timeout(4000)
            if "login.html" not in pg.url:
                log("✅ 登录成功：%s" % pg.url)
                dump_cookies(ctx, a)
                ctx.close()
                return 0
            log("✘ 没通过，换一张再来")
            pg.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(1500)
        log("登录未成功。也可以直接在弹出的浏览器窗口里手工登录（本命令 headless=False）。")
        ctx.close()
        return 1


def dump_cookies(ctx, a):
    ck = [c for c in ctx.cookies()
          if c.get("domain", "").endswith("order.p2pah.cn")]
    io.open(COOKIE_OUT, "w", encoding="utf-8").write(json.dumps(ck, ensure_ascii=False, indent=1))
    log("cookie 已导出（%d 个）→ %s" % (len(ck), COOKIE_OUT))


def disc_of(cfg, key):
    """该 key 的后台折扣系数（前端价 = 标价 × 折扣）。

    与服务器侧 engine.disc_of 同口径：对照项.后台折扣 → 游戏字典.<游戏>.后台折扣 →
    前端.后台折扣 → 1.0。2026-09-25：暗黑4=0.9、POE2=1.0。
    """
    it = {}
    for x in ((cfg.get("商品映射") or {}).get("对照项") or []):
        if x.get("key") == key:
            it = x
            break
    gd = ((cfg.get("商品映射") or {}).get("游戏字典") or {}).get(it.get("游戏")) or {}
    for v in (it.get("后台折扣"), gd.get("后台折扣"),
              (cfg.get("前端") or {}).get("后台折扣")):
        try:
            d = float(v)
            if d > 0:
                return d / 100.0
        except (TypeError, ValueError):
            continue
    return 1.0


def cmd_read(a):
    cfg = load_cfg(a.config)
    s = Session(a.profile, a.show)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效，请先跑：python p2pah_local.py login")
        mp = mapping(cfg)
        byid = fetch_all_needed(s, cfg, list(mp.keys()))
        log("汇总 %d 行候选" % len(byid))
        print()
        print("%-22s %-6s %-11s %-34s %-10s %-10s %s" %
              ("我方 key", "gid", "后台ID", "后台产品名", "$每个价格", "折后(前端)", "成本￥"))
        print("-" * 118)
        miss = []
        for key, pid in mp.items():
            r = byid.get(str(pid))
            gid = game_gid_of(cfg, key)
            if not r:
                miss.append(key)
                print("%-22s %-6s %-11s %s" % (key, gid, pid, "✘ 列表里没找到"))
                continue
            k = disc_of(cfg, key)
            sale = "%.5f" % (r["unit_price"] * k) if r["unit_price"] else "-"
            print("%-22s %-6s %-11s %-34s %-10s %-10s %s" %
                  (key, gid, pid, r["name"][:34], r["unit_price"], sale, r["cprice"]))
        print("-" * 118)
        if miss:
            log("⚠ 有 %d 个 key 在后台列表里找不到：%s" % (len(miss), miss))
        for key in ["CRUX_X10"]:
            d = ids_of(cfg, key)
            log("重复上架 %s → %s" % (key, d))
    finally:
        s.close()


def cmd_readgame(a):
    """只读：按 gid / aid / 关键词 dump 后台产品列表（多游戏排查 + 生成接入配置表要用）

    python p2pah_local.py readgame --gid 552 --aid 20106
    python p2pah_local.py readgame --gid 552 --keyword "Divine Orb"
    python p2pah_local.py readgame --gid 864 --all-pages --dump "..\\侦察\\_backend_864.json"

    `--dump` 出来的 JSON 就是「新游戏接入.py」要的 `后台商品IDdump`：
      {"gid":..,"name":..,"pages":N,"rows":[{id,name,area,ptype,unit_price,discount,...}]}
    2026-09-25 晚：默认翻完所有页（ARC 后台 gid=864 有 1940 行 / 单服 660 行 = 4 页）。
    """
    cfg = load_cfg(a.config) if a.config else {}
    s = Session(a.profile, a.show)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效，请先跑：python p2pah_local.py login")
        gid = str(a.gid)
        if getattr(a, "all_pages", True) and not (a.keyword or ""):
            rows, last = read_all_pages(s, gid, aid=a.aid or "",
                                        wait=int(getattr(a, "wait", 2500) or 2500))
            log("gid=%s 翻页 → %d 页 / %d 行" % (gid, last, len(rows)))
        else:
            rows = s.read_rows(url=list_url_of(gid, keyword=a.keyword or "",
                                               aid=a.aid or ""), wait=3000)
            last = 1
        print("%-12s %-14s %-10s %-40s %-12s %-8s %s"
              % ("后台ID", "服务区", "类型", "产品名", "$每个价格", "折扣", "成本￥"))
        print("-" * 118)
        for r in rows:
            print("%-12s %-14s %-10s %-40s %-12s %-8s %s"
                  % (r["id"], r.get("area", ""), r.get("ptype", ""),
                     (r["name"] or "")[:40], r["unit_price"], r["discount"], r["cprice"]))
        print("-" * 118)
        log("gid=%s aid=%s keyword=%r → %d 页 / %d 行"
            % (gid, a.aid or "", a.keyword or "", last, len(rows)))
        dp = getattr(a, "dump", "") or ""
        if dp:
            dp = os.path.abspath(dp)
            payload = {"gid": gid, "name": gid, "pages": last, "n": len(rows), "rows": rows}
            with io.open(dp, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, indent=1))
            log("已 dump → %s（%d 行）" % (dp, len(rows)))
    finally:
        s.close()


def cache_wanted(a, plan):
    """要不要清缓存（清缓存只能由本机执行）。

    优先级：命令行 --clearcache / --no-clearcache  >  工单里的 clearcache 字段  >  默认清。
    工单由服务器侧 app.py 生成；服务器 IP 不在 order.p2pah.cn 白名单（既改不了价
    也清不了缓存），所以工单只带「意图」，真正的「清除全部」在这里执行。
    """
    v = getattr(a, "clearcache", None)
    if v is not None:
        return bool(v), "命令行 %s" % ("--clearcache" if v else "--no-clearcache")
    if isinstance(plan, dict) and "clearcache" in plan:
        b = bool(plan.get("clearcache"))
        return b, "工单 clearcache=%s" % b
    return True, "旧工单没带 clearcache（按默认：清）"


def _throttled(msg):
    """后台返回的是「操作过于频繁」这类频控提示（**不是失败**，等窗口过了就能成）。"""
    m = msg or ""
    return ("频繁" in m) or ("too frequent" in m.lower()) or ("rate limit" in m.lower())


def clear_main_cache(log=log):
    """主后台 admin.p2pah.cn → 工具箱 → 缓存管理 → 一键清理所有。

    🔴 必须**本机执行**（admin.p2pah.cn / admin-api.p2pah.cn 有来源 IP 白名单，
       服务器 47.253.252.55 访问不到 —— 与 order.p2pah.cn 的约束一致）。
    请求：POST https://admin-api.p2pah.cn/admin/tools.Caches/clear?server=1
          headers: server: 1   ← 少了它后端直接 302 跳 /index.html（返回一段 HTML，极易误判）
                   batoken: <token>  ← 少了它返回 {"code":302,"msg":"Please login first"}
          body   : {"type":"all","file":""}
    返回 (ok, 文本)。token 存在 admin_cache_local 的 _admin_token.json；
    **过期会自动用账号密码重登**（p2pah_autologin + 本地离线 OCR）后重试一次。
    """
    if admin_cache is None:
        return False, "没找到 admin_cache_local.py（应与本脚本同目录），请手动清缓存"

    def _once(tk):
        st, body = admin_cache.clear_cache("all", tk)
        try:
            j = json.loads(body)
            return ((j.get("code") == 1), (j.get("msg") or body), j.get("code"), st)
        except Exception:
            return False, "HTTP %s %s" % (st, (body or "")[:160]), None, st

    tok = admin_cache.load_token()
    if tok:
        ok, msg, code, st = _once(tok)
        if ok:
            return True, msg
        if _throttled(msg):
            # 后台对「全部站点」的全量清理有 30 秒频控。**多张工单连着跑必然撞上**
            # （2026-09-26 实测：09:28:34 清过 → 09:29:09 第二张单被拒），
            # 这不是失败，等满窗口再试一次即可（工单多花 31 秒，好过误报失败）。
            log("  后台频控：%s → 等 31 秒后重试" % msg)
            time.sleep(31)
            ok, msg, code, st = _once(tok)
            if ok:
                return True, "（频控等待后）" + msg
            return False, msg
        if code != 302 and st not in (302, 401, 0):
            return False, msg          # 其它错（网络等）不该触发重登
        log("  token 已过期（%s）→ 用账号密码自动重登后重试" % (msg or st))
    else:
        log("  本地没有 admin token → 用账号密码自动登录")

    if autologin is None:
        return False, "自动重登模块不可用，请人工：python admin_cache_local.py login"
    # 🔴 2026-09-27 修复：**不能在已有 Playwright 会话的进程内再起一个 sync_playwright**。
    #   cmd_write 里 Session 已经 `sync_playwright().start()`（浏览器开着），此时再调
    #   `autologin.login_admin()`（内部 `with sync_playwright() as p:`）会抛：
    #       Error: It looks like you are using Playwright Sync API inside the asyncio loop.
    #   实测（工单 J20260927103525 / J20260927113244）后果很严重：**写价已经成功**，
    #   异常却一路抛出 cmd_write → 后面的「② order 清除全部」与「结果落盘」全被跳过，
    #   工单被记成 failed，前端也失去刷新机会。
    #   ⇒ 重登 + 清缓存改到**子进程**里做（独立 Playwright，天然无嵌套冲突）。
    return _relogin_and_clear_subprocess(log)


def _relogin_and_clear_subprocess(log=log):
    """用子进程跑 `admin_cache_local.py clear`（自动重登 + 清缓存），避开 Playwright 嵌套。

    独立进程 = 独立事件循环，绝不会撞上「Sync API inside asyncio loop」。
    返回 (ok, 文本)。
    """
    script = os.path.join(HERE, "admin_cache_local.py")
    if not os.path.exists(script):
        return False, "没找到 admin_cache_local.py，请人工：python admin_cache_local.py clear"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    flags = 0x08000000 if os.name == "nt" else 0        # CREATE_NO_WINDOW：绝不弹黑窗
    try:
        r = subprocess.run([sys.executable, script, "clear", "--type", "all"],
                           capture_output=True, timeout=420, env=env, cwd=HERE,
                           creationflags=flags)
    except Exception as e:
        return False, "子进程清缓存启动失败：%r" % e
    txt = ((r.stdout or b"").decode("utf-8", "replace")
           + (r.stderr or b"").decode("utf-8", "replace"))
    for ln in txt.strip().splitlines():
        if ln.strip():
            log("    [admin子进程] %s" % ln.strip()[:200])
    if r.returncode == 0:
        return True, "（子进程自动重登后）缓存已清理"
    if "频控" in txt or "过于频繁" in txt:
        return False, "子进程清缓存撞上 30 秒频控（不是失败，可稍后重跑 clearcache）"
    return False, "子进程清缓存失败（退出码 %s）：%s" % (
        r.returncode, txt[-240:].replace("\n", " "))


def cmd_write(a):
    cfg = load_cfg(a.config)
    plan = json.load(io.open(a.plan, encoding="utf-8"))
    items = plan.get("items") if isinstance(plan, dict) else plan
    if not isinstance(items, list):
        raise SystemExit("计划格式不对：应为 {\"items\":[...]} 或 [...]")

    jobs = []
    for it in items:
        key = it.get("key")
        tgt = it.get("new", it.get("unit_price", it.get("target")))
        if key is None or tgt is None:
            continue
        ids = ids_of(cfg, key)
        if not ids:
            log("跳过 %s：没有后台商品ID" % key)
            continue
        jobs.append({"key": key, "ids": ids, "unit_price": float(tgt),
                     "old": it.get("old"), "gid": it.get("gid")})
    if not jobs:
        log("计划里没有可执行的改价项")
        return 0

    log("待改 %d 件（%d 行）" % (len(jobs), sum(len(j["ids"]) for j in jobs)))
    for j in jobs:
        log("  %-24s 后台ID %s  $%.5f → $%.5f" %
            (j["key"], ",".join(j["ids"]), j.get("old") or 0, j["unit_price"]))
    if not a.confirm:
        log("★ 预演结束（没加 --confirm，未发任何写请求）")
        return 0

    s = Session(a.profile, a.show)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效，请先跑：python p2pah_local.py login")
        byid = fetch_all_needed(s, cfg, [j["key"] for j in jobs])
        ok = fail = 0
        for j in jobs:
            changed = [i for i in j["ids"]
                       if not byid.get(i) or (byid[i]["unit_price"] or 0) != round(j["unit_price"], 5)]
            if not changed:
                log("  = %s 已经是目标价，跳过" % j["key"])
                continue
            # gid 按游戏取（暗黑4=456 / POE2=552）。工单里带了 gid 就用工单的。
            body = [{"id": int(i), "gid": str(j.get("gid") or game_gid_of(cfg, j["key"])),
                     "min_qty": 0,
                     "unit_price": "%.5f" % j["unit_price"], "cprice": None} for i in changed]
            r = s.write_rows(body)
            if r["ok"]:
                ok += 1
                log("  ✓ %s → $%.5f（%s）" % (j["key"], j["unit_price"], r["msg"]))
            else:
                fail += 1
                log("  ✗ %s 失败：%s" % (j["key"], r["msg"]))
            time.sleep(1.5)

        log("写请求完成：成功 %d / 失败 %d。开始复核…" % (ok, fail))
        after = fetch_all_needed(s, cfg, [j["key"] for j in jobs])
        bad = []
        for j in jobs:
            for i in j["ids"]:
                got = (after.get(i) or {}).get("unit_price")
                if got is None or abs(got - round(j["unit_price"], 5)) > 1e-9:
                    bad.append((j["key"], i, got, j["unit_price"]))
        if bad:
            log("⚠ 复核不一致 %d 处：" % len(bad))
            for k, i, got, want in bad:
                log("   %s id=%s 实际 %s / 目标 %s" % (k, i, got, want))
        else:
            log("✅ 复核通过：所有目标行都已是目标价")

        # 改完顺手清缓存，让前端立即刷新（等同人工在后台点一次「清除全部」）
        # 清缓存只能由本机执行：要不要清由工单里的 clearcache 带过来，命令行可覆盖。
        cache_ok = None
        want_cache, cache_src = cache_wanted(a, plan)
        if ok and not bad and want_cache:
            # ① 主后台 admin.p2pah.cn「工具箱 → 缓存管理 → 一键清理所有」—— 前端刷新的关键一步
            log("① 主后台 admin.p2pah.cn「缓存管理 → 一键清理所有」…［意图来源：%s］" % cache_src)
            # 🔴 2026-09-27：清缓存**绝不允许影响已经完成的写价**。以前它一抛异常，
            #   整段（含 ② order 清缓存、结果落盘）全被跳过、工单误记 failed。
            try:
                mok, mtxt = clear_main_cache()
            except Exception as e:
                mok, mtxt = False, "清缓存异常（写价已成功，不受影响）：%r" % e
            log(("  ✓ %s" if mok else "  ⚠ %s") % mtxt)
            # ② order 后台自带的「清除全部」（保留，无害）
            log("② order 后台「清除全部」…")
            try:
                cok2, txt2 = s.clear_cache()
            except Exception as e:
                cok2, txt2 = False, repr(e)
            log(("  ✓ %s" if cok2 else "  ⚠ %s") % (txt2 or ""))
            cache_ok = bool(mok)
        elif ok and not bad:
            log("（本次跳过清缓存 —— %s）" % cache_src)

        out = os.path.join(HERE, "p2pah_write_result_%s.json"
                           % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        io.open(out, "w", encoding="utf-8").write(json.dumps(
            {"ts": dt.datetime.now().isoformat(timespec="seconds"), "ok": ok, "fail": fail,
             "mismatch": bad, "clearcache_ok": cache_ok,
             "clearcache_wanted": want_cache, "clearcache_意图来源": cache_src,
             "jobs": jobs},
            ensure_ascii=False, indent=1))
        log("结果已存：%s" % out)
        return 0 if not fail and not bad else 1
    finally:
        s.close()


def _fnum(s):
    """安全转 float。⚠ 不要用 num()：它先 str() 再正则，会把科学计数法截断
    （str(3.09e-05)='3.09e-05' → 只匹配到 '3.09'）。"""
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def cmd_writegold(a):
    """金币工单：改采购成本 → 点「更新b2c网站」(saveprice getweb=1) → 清缓存。

    金币和物品是两套机制：金币唯一可改的量是「采购成本」，而且**改完必须推送
    前端**才会刷新（2026-09-24 实测：改价是两步不是一步）。
    ⚠️ 推送必须走 `.jq-getweb`（getweb=1，返回「更新网站成功」）；
       只点文案为「同步价格」的 `.jq-update-button`（getweb=0）前端**不会**变。

    工单结构（服务器 app.py / 本机 gold_follow_plan.py 生成）：
      {"ts":"...","clearcache":true,
       "items":[{"key":"GOLD_S15_HC","中文名":"赛季专家 (S15 Hardcore)",
                 "后台行ID":"15712","采购成本_旧":9.99,"采购成本_新":0.002655,
                 "动作":"follow_down"}, ...]}
    """
    plan = json.load(io.open(a.plan, encoding="utf-8"))
    items = plan.get("items") if isinstance(plan, dict) else plan
    if not isinstance(items, list):
        raise SystemExit("计划格式不对：应为 {\"items\":[...]} 或 [...]")

    jobs = []
    for it in items:
        rid = it.get("后台行ID") or it.get("row_id")
        new = it.get("采购成本_新")
        if new is None:
            new = it.get("new")
        if rid is None or new is None:
            continue
        if str(it.get("动作") or "").lower() == "hold":
            log("跳过 %s：工单标记为 hold（不需要改）" % it.get("key"))
            continue
        if a.only and it.get("key") not in a.only:
            continue
        jobs.append({"key": it.get("key"),
                     "名称": it.get("中文名") or it.get("name") or it.get("key"),
                     "row_id": str(rid), "旧": it.get("采购成本_旧"), "新": float(new),
                     # 2026-10-01：金币列表页按 gid 分表，必须知道这行属于哪个游戏
                     "游戏": it.get("游戏") or it.get("game") or ""})
    if not jobs:
        log("工单里没有可执行的金币项")
        return 0

    # ── 2026-10-01：按「游戏」取各自的金币 gid ─────────────────────────
    # 金币价格管理的列表页 URL 带 gid；写死 456（暗黑4）会去读暗黑4的表，
    # AION2 的行永远找不到 —— 而且不报错。这里先解析出 gid，再断言能命中。
    _cfg = {}
    try:
        _cfg = json.load(io.open(DEFAULT_CFG, encoding="utf-8"))
    except Exception:
        pass
    for j in jobs:
        _g = j.get("游戏") or ""
        if not _g:
            raise SystemExit(
                "✘ 工单缺少「游戏」字段，无法确定金币 gid —— 拒绝执行。"
                "（2026-10-01 后金币工单必须带 游戏，否则可能把 AION2 写到暗黑4。）"
                "请让服务器重新生成工单，或手工补 '游戏' 字段后再跑。")
        j["gid"] = gold_gid_of(_cfg, _g)
    _gids = sorted({j["gid"] for j in jobs})
    if len(_gids) > 1:
        raise SystemExit("✘ 本单混了多个游戏的金币（gid=%s），拒绝执行。"
                         "请拆成每游戏一张工单。" % ",".join(_gids))

    log("待改 %d 个服务区的采购成本：" % len(jobs))
    for j in jobs:
        log("  %-12s %-24s 行%-6s %s → %.6f"
            % (j["key"], j["名称"], j["row_id"], j["旧"], j["新"]))

    s = Session(a.profile, a.show)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效，请先跑：python p2pah_local.py login")

        # 金币列表页必须带对 gid（本单已断言只有一组，取第一个即可）
        _gid0 = jobs[0]["gid"]
        log("金币价格管理列表 gid=%s（游戏：%s）"
            % (_gid0, "、".join(sorted({j.get("游戏") for j in jobs}))))
        before = s.gold_rows(gid=_gid0)
        _miss = [j for j in jobs if j["row_id"] not in before]
        if _miss:
            raise SystemExit(
                "✘ 有 %d 行的后台ID 在 gid=%s 的列表里找不到：%s"
                " ⇒ gid 与实际游戏不匹配（或行ID 写错）。已中止，未发任何写请求。"
                " 请核对 config.p2pah.游戏.<游戏>.game_id 与工单的「游戏」字段。"
                % (len(_miss), _gid0,
                   "、".join("%s(行%s)" % (j["key"], j["row_id"]) for j in _miss[:6])))
        for j in jobs:
            rec = before.get(j["row_id"]) or {}
            j["改前实际"] = rec.get("costprice")
            log("  改前核对 %-12s 行%-6s 采购成本 = %s（利润率 %s / b2c %s）"
                % (j["key"], j["row_id"], rec.get("costprice"),
                   rec.get("lirunlv"), rec.get("b2c")))
        if any(j["row_id"] not in before for j in jobs):
            log("⚠ 有行在页面上找不到（行ID 写错？），请人工确认后再跑")

        # ── 无效果闸（2026-09-26 patch8）───────────────────────────────
        # 服务器侧只判「相对差 %」、且看不到后台现值，所以「目标恰好等于现值」
        # 的空单仍会派过来（实测：赛季普通每小时一张，改前/改后都是 0.000100）。
        # 这里拿现场真值再拦一道：改前已等于目标的直接跳过 ——
        # 不写入、不推送前端、不清缓存。全单都无效果时整个流程短路。
        _all = list(jobs)          # 全量留档（含「改前实际」= 现场读到的后台真值）
        _same = [j for j in jobs
                 if _fnum(j.get("改前实际")) is not None
                 and abs(_fnum(j["改前实际"]) - float(j["新"])) <= 1e-12]
        if _same:
            for j in _same:
                log("  ⏭ 跳过 %-12s 行%-6s：改前 %s 已等于目标 %.6f（无效果）"
                    % (j["key"], j["row_id"], j["改前实际"], j["新"]))
            _skip = set(j["row_id"] for j in _same)
            jobs = [j for j in jobs if j["row_id"] not in _skip]
        if not jobs:
            log("★ 本单所有服务区的采购成本都已等于目标值 —— 无实际改动，"
                "跳过写入 / 推送前端 / 清缓存（省一张空单）")
            # 2026-09-26（patch10）：无效果也要落结果文件。
            # 以前这里直接 return 0，结果文件不落 ⇒ worker 的 newest_result 拿不到
            # jobs ⇒ 服务器永远收不到「改前实际」= 本机现场读到的后台真值 ——
            # 偏偏这张单是最需要真值的那张（服务器是按前端取整价判出的变化）。
            _out = os.path.join(HERE, "p2pah_writegold_result_%s.json"
                                % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
            io.open(_out, "w", encoding="utf-8").write(json.dumps(
                {"ts": dt.datetime.now().isoformat(timespec="seconds"),
                 "ok": 0, "fail": 0, "mismatch": [], "noop": True,
                 "sync_price": {}, "clearcache_ok": None, "clearcache_wanted": False,
                 "jobs": _all}, ensure_ascii=False, indent=1))
            log("结果已存（无效果单，供服务器回填真值）：%s" % _out)
            return 0

        if not a.confirm:
            log("★ 预演结束（没加 --confirm，未发任何写请求）")
            return 0

        ok = fail = 0
        for j in jobs:
            r = s.set_gold_cost(j["row_id"], "%.6f" % j["新"])
            if r["ok"]:
                ok += 1
                log("  ✓ %s 行%-6s 采购成本 → %.6f（%s）"
                    % (j["key"], j["row_id"], j["新"], r["msg"]))
            else:
                fail += 1
                log("  ✗ %s 行%-6s 改价失败：%s" % (j["key"], j["row_id"], r["msg"]))
            time.sleep(1.2)

        log("写请求完成：成功 %d / 失败 %d。复核…" % (ok, fail))
        # 2026-10-01 修复：复核必须用**同一张游戏列表**（gid=_gid0）。
        #   漏传 gid ⇒ 退回默认 456（暗黑4）⇒ AION2 的行全查不到 ⇒ 全判 mismatch
        #   ⇒ 跳过「更新b2c网站」+ 跳过清缓存 ⇒ 后台改了但前端永不刷新。
        after = s.gold_rows(gid=_gid0)
        bad = []
        for j in jobs:
            rec = after.get(j["row_id"]) or {}
            got = _fnum(rec.get("costprice"))
            if got is None or abs(got - j["新"]) > 1e-9:
                bad.append((j["key"], j["row_id"], rec.get("costprice"), j["新"]))
            else:
                log("  ✓ 复核 %-12s 行%-6s 采购成本 = %s（b2c %s）"
                    % (j["key"], j["row_id"], rec.get("costprice"), rec.get("b2c")))
        if bad:
            log("⚠ 复核不一致 %d 处：" % len(bad))
            for k, i, got, want in bad:
                log("   %s 行%s 实际 %s / 目标 %s" % (k, i, got, want))

        # ---- 同步价格（🔴 不勾「所有区」）----
        sync = {}
        lg = {}
        if ok and not bad:
            log("点后台右上角「更新b2c网站」刷新图标（= saveprice getweb=1，保证不勾『所有区』）…")
            try:
                sync = s.sync_gold_price(gid=_gid0)
            except Exception as e:
                sync = {"ok": False, "url": "", "msg": repr(e), "getweb": "", "allserver": False}
            if sync.get("allserver"):
                log("  ✗✗ 严重：请求 URL 里带了 allserver！请立刻人工检查后台状态")
            elif sync.get("ok"):
                log("  ✓ 已推送前端：%s（getweb=%s）" % (sync.get("msg") or "", sync.get("getweb")))
            else:
                log("  ⚠ 未确认推送成功：%s" % (sync.get("msg") or ""))
            if str(sync.get("getweb")) != "1":
                log("  ⚠ 注意：本次 getweb=%s（非 1），前端可能不会刷新"
                    % sync.get("getweb"))
            log("  实际请求：%s" % (sync.get("url") or "-"))

            # 🔴 2026-10-01 新增：补写后台「修改价格日志」。
            #   实测 A/B：saveprice getweb=1（.jq-getweb）**不写**日志；
            #   getweb=0（.jq-update-button「同步价格」）**写**一条批量日志。
            #   执行器过去只点 .jq-getweb ⇒ 后台「修改价格日志」里 AION2 一条都没有
            #   （用户 2026-10-01 反馈）。这里再点一次 getweb=0 把日志补上。
            #   对价格无副作用（值已写好，只是把当前值再提交一次），且同样不勾「所有区」。
            log("补写后台「修改价格日志」（= saveprice getweb=0，点按钮「同步价格」）…")
            try:
                lg = s.log_gold_price(gid=_gid0)
            except Exception as e:
                lg = {"ok": False, "url": "", "msg": repr(e), "getweb": "", "allserver": False}
            if lg.get("allserver"):
                log("  ✗✗ 严重：补写日志的请求 URL 里带了 allserver！请立刻人工检查后台状态")
            elif lg.get("ok"):
                log("  ✓ 日志已补写：%s（getweb=%s）" % (lg.get("msg") or "", lg.get("getweb")))
            else:
                log("  ⚠ 日志补写未确认成功：%s" % (lg.get("msg") or ""))
            log("  实际请求：%s" % (lg.get("url") or "-"))
        elif ok and bad:
            log("（复核没过，跳过「同步价格」）")

        cache_ok = None
        want_cache, cache_src = cache_wanted(a, plan)
        if ok and not bad and want_cache:
            # ① 主后台 admin.p2pah.cn「工具箱 → 缓存管理 → 一键清理所有」
            #    —— **金币价前端刷新就差这一步**（用户 2026-09-24 强调）
            log("① 主后台 admin.p2pah.cn「缓存管理 → 一键清理所有」…［意图来源：%s］" % cache_src)
            # 🔴 2026-09-27：清缓存异常不得影响已完成的写价（同 cmd_write）
            try:
                mok, mtxt = clear_main_cache()
            except Exception as e:
                mok, mtxt = False, "清缓存异常（写价已成功，不受影响）：%r" % e
            log(("  ✓ %s" if mok else "  ⚠ %s") % mtxt)
            # ② order 后台自带的「清除全部」（保留，无害）
            log("② order 后台「清除全部」…")
            try:
                cok2, txt2 = s.clear_cache()
            except Exception as e:
                cok2, txt2 = False, repr(e)
            log(("  ✓ %s" if cok2 else "  ⚠ %s") % (txt2 or ""))
            cache_ok = bool(mok)
        elif ok and not bad:
            log("（本次跳过清缓存 —— %s）" % cache_src)

        out = os.path.join(HERE, "p2pah_writegold_result_%s.json"
                           % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        io.open(out, "w", encoding="utf-8").write(json.dumps(
            {"ts": dt.datetime.now().isoformat(timespec="seconds"), "ok": ok, "fail": fail,
             "mismatch": bad, "sync_price": sync, "log_price": lg, "clearcache_ok": cache_ok,
             "clearcache_wanted": want_cache, "jobs": jobs},
            ensure_ascii=False, indent=1))
        log("结果已存：%s" % out)
        return 0 if not fail and not bad else 1
    finally:
        s.close()


def cmd_clearcache(a):
    """单独清一次缓存。

    ① 主后台 admin.p2pah.cn →「工具箱 → 缓存管理 → 一键清理所有」
       —— **前端刷新的关键一步**，只依赖 _admin_token.json，**不需要 order 会话**。
    ② order 后台自带的「清除全部」（附带；order 会话失效不影响①）。
    """
    log("① 主后台 admin.p2pah.cn「缓存管理 → 一键清理所有」…")
    try:
        mok, mtxt = clear_main_cache()
    except Exception as e:
        mok, mtxt = False, "清缓存异常：%r" % e
    log(("  ✓ %s" if mok else "  ⚠ %s") % mtxt)

    s = Session(a.profile, a.show)
    try:
        if not s.logged_in():
            log("② 跳过 order 清缓存（order 会话已失效；先跑 login 可恢复）")
            return 0 if mok else 1
        ok, txt = s.clear_cache()
        log(("  ✓ order：%s" if ok else "  ⚠ order：%s") % (txt or ""))
    finally:
        s.close()
    return 0 if mok else 1


def cmd_ping(a):
    """只读探活：打开后台首页，判断登录态是否还有效。**零写入、零副作用。**

    专门给常驻执行器的「会话保活」用：
    `order.p2pah.cn` 是 PHP 会话，按「最后访问时间 + 存活期」过期。无人值守时
    长时间没有访问 → 会话过期 → write 一进去就 raise SystemExit（"会话已失效"）
    → 工单 failed，表现就是「只检测不执行」。定期 ping 一次即可把会话续上。

    返回码：0 = 登录态有效；2 = 已失效（需人工跑 login 认验证码）。
    """
    s = Session(a.profile, a.show)
    try:
        ok = s.logged_in()
    finally:
        s.close()
    if ok:
        log("✓ 后台登录态有效（会话保活成功）")
        return 0
    log("✘ 后台登录态**已失效** —— 改价会失败！请在本机跑：python p2pah_local.py login")
    return 2


def main():
    ap = argparse.ArgumentParser(description="后台改价 · 本机执行器")
    ap.add_argument("cmd", choices=["login", "read", "readgame", "write", "writegold",
                                    "clearcache", "ping"])
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--config", default=DEFAULT_CFG)
    ap.add_argument("--plan", help="计划 JSON（write / writegold 用）")
    ap.add_argument("--only", nargs="*", help="只处理这些 key（writegold 用）")
    ap.add_argument("--confirm", action="store_true", help="真的提交写请求")
    ap.add_argument("--clearcache", dest="clearcache", action="store_true", default=None,
                    help="write 后强制清缓存（覆盖工单里的 clearcache）")
    ap.add_argument("--no-clearcache", dest="clearcache", action="store_false",
                    help="write 后不清缓存（覆盖工单里的 clearcache）")
    ap.add_argument("--show", action="store_true", help="显示浏览器窗口")
    ap.add_argument("--wait", type=int, default=240, help="login 等答案的秒数")
    ap.add_argument("--username", default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--gid", default="456",
                    help="readgame：后台 gid（D4=456 / POE2=552 / ARC=864 / DnD=588）")
    ap.add_argument("--aid", default="", help="readgame：后台服务区 ID")
    ap.add_argument("--keyword", default="", help="readgame：产品名关键词")
    ap.add_argument("--dump", default="", help="readgame：把结果写成 JSON（新游戏接入用）")
    ap.add_argument("--all-pages", dest="all_pages", action="store_true", default=True,
                    help="readgame：翻完所有页（默认开）")
    ap.add_argument("--no-all-pages", dest="all_pages", action="store_false",
                    help="readgame：只读第 1 页（200 行）")
    ap.add_argument("--no-auto-login", dest="no_auto_login", action="store_true",
                    help="会话失效时不要用账号密码自动重登，直接报错（调试用）")
    a = ap.parse_args()
    AUTO_LOGIN[0] = not a.no_auto_login
    if a.username is None or a.password is None:
        try:
            cfg = load_cfg(a.config)
            acc = (cfg.get("p2pah") or {}).get("账号") or {}
            a.username = a.username or acc.get("username")
            a.password = a.password or acc.get("password")
        except SystemExit:
            pass
    return {"login": cmd_login, "read": cmd_read, "readgame": cmd_readgame,
            "write": cmd_write,
            "writegold": cmd_writegold, "clearcache": cmd_clearcache,
            "ping": cmd_ping}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
