# -*- coding: utf-8 -*-
"""两个后台的「缓存/会话过期 → 账号密码兜底自动登录」。

背景（为什么以前必须人工）
--------------------------
  · order.p2pah.cn（改价后台）  PHP 会话，闲置过久被踢回 /login.html
  · admin.p2pah.cn（清缓存主后台）batoken 约 1.5 天过期，接口回 {"code":302,"msg":"Please login first"}
两者的登录页都要**图形验证码**，所以历史上只能人工重登 —— 也就是「下班后执行器卡住、
第二天来一看全是失败单」的根因之一。

本模块用 **ddddocr（本地离线 OCR，纯 CPU，无网络）** 自动识别验证码，
把「账号密码」变成真正可用的兜底：过期 → 自动重登 → 继续干活，全程无人值守。

验证码实测（2026-09-26，两个后台各连续 2 次首识别即通过）
--------------------------------------------------------
  order  GET /new_captcha.html?height=32&width=150&font_size=18
         → 4 位字母数字，纯色背景、**无干扰线**、仅带旋转（PNG 约 450~510 字节）
  admin  GET /api/common/captcha?server=1&id=<前端生成的 uuid>
         → 4 位数字，深色粗体 + 大片浅色细字干扰（PNG 约 1.4K）

⚠️ 两个坑（都已经绕开，改动时别踩回去）
  1. admin 的验证码图在 **admin-api.p2pah.cn**，与页面 admin.p2pah.cn **跨域** ——
     在页面里用 canvas 导出会 `SecurityError: Tainted canvases may not be exported`。
     正确做法：监听 response，直接取**页面自己那一次 captcha 请求的 body**，
     这样「识别的图」和「前端持有的 captcha id」严格对应。
  2. 页面里 page.evaluate 传参必须写成 `(sel) => ...`，
     写成 `() => ... arguments[0]` 会报 `ReferenceError: arguments is not defined`。

对外
----
  accounts()                    → {"order":{...},"admin":{...}}（凭据 + profile 名）
  solve(png_bytes)              → 验证码文本（只保留字母数字）
  login_order_in(pg, u, p)      → 在**已打开的页面**里登录 order（不抢 profile，返回 bool）
  login_admin_in(pg, u, p)      → 在已打开的页面里登录 admin（返回 token）
  login_admin(profile=None)     → 新开浏览器登录 admin，成功后把 token 写进 _admin_token.json
  admin_token(force=False)      → 读本地 admin token（force=True 时先自动重登）

凭据存放：同目录 `_accounts.json`（**明文，仅限本机**）；缺失时回退读 config.json 的
`p2pah.账号`，再回退内置默认（与 config 一致）。
"""
import base64
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_F = os.path.join(HERE, "_accounts.json")
ADMIN_TOKEN_F = os.path.join(HERE, "_admin_token.json")
ORDER_COOKIE_F = os.path.join(HERE, "p2pah_cookies.json")

ORDER_SITE = "https://order.p2pah.cn"
ADMIN_SITE = "https://admin.p2pah.cn"
ADMIN_API = "https://admin-api.p2pah.cn"

# 浏览器「通道」（2026-09-27）：本机用系统装好的 Edge（channel="msedge"，更像真人、
# 验证码命中更稳）；服务器容器 p2pah-srv:1 里只有 Playwright 自带 chromium、没有 Edge，
# 所以容器里用环境变量 P2PAH_CHANNEL=""（空）让它回落到自带 chromium。
# 不设该环境变量时行为与本机历史行为完全一致（默认仍是 msedge）。
CHANNEL = os.environ.get("P2PAH_CHANNEL", "msedge") or None

# 兜底凭据（与 config.json → p2pah.账号 一致；_accounts.json 优先）
FALLBACK = {"username": "chenchao", "password": "Fsnet@Cc.2026"}

_OCR = None


def log_default(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# ------------------------------------------------------------------ OCR
def ocr():
    """懒加载 ddddocr（import onnxruntime 要 1~2 秒，正常路径不该付这个代价）。"""
    global _OCR
    if _OCR is None:
        import ddddocr
        _OCR = ddddocr.DdddOcr(show_ad=False)
    return _OCR


def solve(png):
    """PNG bytes → 验证码文本。只保留字母数字（'*' '?' 这类识别噪声直接剔除，
    长度不够会被上层判成「这次不算」并换一张图重试）。"""
    if not png:
        return ""
    try:
        s = ocr().classification(png)
    except Exception:
        return ""
    return re.sub(r"[^0-9A-Za-z]", "", s or "")


def solve_dataurl(d):
    if not d or "," not in d:
        return ""
    try:
        return solve(base64.b64decode(d.split(",", 1)[1]))
    except Exception:
        return ""


# ------------------------------------------------------------------ 凭据
def accounts():
    """返回 {"order":{...}, "admin":{...}}；每项至少含 username / password / profile。"""
    d = {}
    if os.path.exists(ACCOUNTS_F):
        try:
            d = json.load(io.open(ACCOUNTS_F, encoding="utf-8")) or {}
        except Exception:
            d = {}
    out = {}
    for k, prof in (("order", "_edge_p2pah"), ("admin", "_edge_adminp2pah")):
        it = dict(d.get(k) or {})
        if not it.get("username") or not it.get("password"):
            # 回退 1：config.json → p2pah.账号
            for cand in ("改造后v18", "改造后v10"):
                p = os.path.normpath(os.path.join(HERE, "..", cand, "config.json"))
                if os.path.exists(p):
                    try:
                        c = json.load(io.open(p, encoding="utf-8"))
                        acc = ((c.get("p2pah") or {}).get("账号") or {})
                        if acc.get("username") and acc.get("password"):
                            it.setdefault("username", acc["username"])
                            it.setdefault("password", acc["password"])
                            break
                    except Exception:
                        pass
        it.setdefault("username", FALLBACK["username"])
        it.setdefault("password", FALLBACK["password"])
        it.setdefault("profile", prof)
        it.setdefault("site", ORDER_SITE if k == "order" else ADMIN_SITE)
        out[k] = it
    return out


def profile_path(name_or_abs):
    return name_or_abs if os.path.isabs(name_or_abs) else os.path.join(HERE, name_or_abs)


# ------------------------------------------------------------------ order 页内登录
_IMG_JS = """(sel) => {
  const im = document.querySelector(sel);
  if(!im || !im.complete || !im.naturalWidth) return null;
  const c = document.createElement('canvas');
  c.width = im.naturalWidth; c.height = im.naturalHeight;
  c.getContext('2d').drawImage(im, 0, 0);
  try { return c.toDataURL('image/png'); } catch(e) { return null; }
}"""

_WAIT_IMG_JS = ("()=>{const i=document.querySelector('img.captcha');"
                "return (i&&i.complete)?i.naturalWidth:0}")


def login_order_in(pg, user, pw, tries=8, log=log_default, site=ORDER_SITE):
    """在**已经打开的页面**上用账号密码 + 自动验证码登录 order。

    刻意不新开浏览器：执行器（p2pah_local.Session）正持有 `_edge_p2pah` 这个
    user-data-dir，Chromium 互斥，另开一个必然起不来。就地重登还能顺手把
    新 cookie 留在同一个上下文里（后续请求直接复用）。

    成功 → True；tries 次都没过 → False（调用方再退人工）。
    """
    login_url = site + "/admin"

    def reload():
        try:
            pg.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(1200)
        except Exception as e:
            log("   [自动登录] 打开登录页异常：%r" % e)

    for i in range(1, tries + 1):
        if "login.html" not in (pg.url or ""):
            reload()
            if "login.html" not in pg.url:
                log("   [自动登录] 已是登录态（无需重登）")
                return True
        w = 0
        for _ in range(25):
            try:
                w = pg.evaluate(_WAIT_IMG_JS)
            except Exception:
                w = 0
            if w:
                break
            pg.wait_for_timeout(200)
        if not w:
            log("   [自动登录] 第%d/%d 次：验证码图没出来，换一张" % (i, tries))
            reload()
            continue
        try:
            ans = solve_dataurl(pg.evaluate(_IMG_JS, "img.captcha"))
        except Exception as e:
            log("   [自动登录] 取图异常：%r" % e)
            reload()
            continue
        if len(ans) != 4:
            log("   [自动登录] 第%d/%d 次：识别=%r（长度不足，换一张）" % (i, tries, ans))
            reload()
            continue
        log("   [自动登录] 第%d/%d 次 识别=%r" % (i, tries, ans))
        try:
            pg.fill("input[name=username]", user, timeout=8000)
            pg.fill("input[name=password]", pw, timeout=8000)
            pg.fill("input[name=captcha]", ans, timeout=8000)
            pg.click("button.js-ajax-submit", timeout=8000)
        except Exception as e:
            log("   [自动登录] 填表/提交异常：%r" % e)
            break
        pg.wait_for_timeout(3500)
        if "login.html" not in (pg.url or ""):
            log("   [自动登录] ✅ order 重登成功（第 %d 次，识别=%s）" % (i, ans))
            return True
        reload()
    log("   [自动登录] ✗ order %d 次内未成功（可退人工：p2pah_local.py login）" % tries)
    return False


# ------------------------------------------------------------------ admin 页内登录
def _admin_token_from_page(pg):
    try:
        ai = pg.evaluate("()=>localStorage.getItem('adminInfo')")
    except Exception:
        return None
    if not ai:
        return None
    try:
        return (json.loads(ai) or {}).get("token") or None
    except Exception:
        return None


def login_admin_in(pg, user, pw, tries=6, log=log_default, site=ADMIN_SITE,
                   force=False):
    """在已打开的页面里登录 admin.p2pah.cn，成功返回 token（UUID），否则 None。

    ⚠️ `force=True`（兜底场景必须开）：持久化 profile 的 localStorage 里可能残留
       **已经过期**的 `adminInfo`。只看「有没有 token」会把过期凭据当成已登录，
       原样返回旧 token —— 实测就踩了这个坑（自动重登「成功」但 token 没变、
       清缓存依旧 302）。兜底重登的语义是**不信本地状态**，所以先清干净再登。
    """
    cap = {"b": None}

    def _on(r):
        if "common/captcha" in (r.url or "").lower():
            try:
                cap["b"] = r.body()
            except Exception:
                pass

    pg.on("response", _on)
    try:
        if force:
            try:
                pg.goto(site + "/", wait_until="domcontentloaded", timeout=90000)
                pg.wait_for_timeout(1500)
                pg.evaluate("()=>{try{localStorage.clear();sessionStorage.clear()}"
                            "catch(e){}}")
                pg.context.clear_cookies()
                log("   [自动登录] admin 已清掉本地残留（cookie + localStorage），强制重登")
            except Exception as e:
                log("   [自动登录] 清本地残留失败（继续尝试）：%r" % e)
        for i in range(1, tries + 1):
            cap["b"] = None
            try:
                pg.goto(site + "/#/admin/login", wait_until="domcontentloaded",
                        timeout=90000)
            except Exception as e:
                log("   [自动登录] admin 打开登录页异常：%r" % e)
                continue
            pg.wait_for_timeout(5000)
            tok = _admin_token_from_page(pg)
            if tok:
                log("   [自动登录] admin 已是登录态")
                return tok
            for _ in range(25):
                if cap["b"]:
                    break
                pg.wait_for_timeout(200)
            if not cap["b"]:
                log("   [自动登录] admin 第%d/%d 次：没截获到验证码图" % (i, tries))
                continue
            ans = solve(cap["b"])
            if len(ans) != 4:
                log("   [自动登录] admin 第%d/%d 次：识别=%r（长度不足，换一张）"
                    % (i, tries, ans))
                continue
            log("   [自动登录] admin 第%d/%d 次 识别=%r" % (i, tries, ans))
            try:
                pg.fill("input[placeholder*='账号']", user, timeout=8000)
                pg.fill("input[type=password]", pw, timeout=8000)
                pg.fill("input[placeholder*='验证码']", ans, timeout=8000)
                pg.click("button:has-text('登录')", timeout=8000)
            except Exception as e:
                log("   [自动登录] admin 填表异常：%r" % e)
                break
            pg.wait_for_timeout(6000)
            tok = _admin_token_from_page(pg)
            if tok:
                log("   [自动登录] ✅ admin 重登成功（第 %d 次，识别=%s）" % (i, ans))
                return tok
        log("   [自动登录] ✗ admin %d 次内未成功" % tries)
        return None
    finally:
        try:
            pg.remove_listener("response", _on)
        except Exception:
            pass


def save_admin_token(tok, user="", source="auto_login"):
    io.open(ADMIN_TOKEN_F, "w", encoding="utf-8").write(json.dumps(
        {"token": tok, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "site": ADMIN_SITE, "user": user, "source": source},
        ensure_ascii=False, indent=1))
    return ADMIN_TOKEN_F


def login_admin(profile=None, user=None, pw=None, headless=True,
                log=log_default, save=True, tries=6):
    """新开一个浏览器登录 admin（用 admin 专用 profile），成功写回 _admin_token.json。

    ⚠️ 只在**没有别的进程占用该 profile** 时用（admin_cache_local 是纯 HTTP 脚本，
       平时没人占 `_edge_adminp2pah`）。order 那边因为执行器可能常驻，一律走
       login_order_in(pg, ...) 就地登录。
    """
    from playwright.sync_api import sync_playwright
    acc = accounts()["admin"]
    prof = profile_path(profile or acc["profile"])
    user = user or acc["username"]
    pw = pw or acc["password"]
    if not user or not pw:
        log("   [自动登录] 缺 admin 账号密码，无法兜底")
        return None
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            prof, channel=CHANNEL, headless=headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            tok = login_admin_in(pg, user, pw, tries=tries, log=log, force=True)
            if tok and save:
                save_admin_token(tok, user, "auto_login")
                log("   [自动登录] token 已更新 → %s" % ADMIN_TOKEN_F)
            return tok
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def read_admin_token():
    if not os.path.exists(ADMIN_TOKEN_F):
        return None
    try:
        return (json.load(io.open(ADMIN_TOKEN_F, encoding="utf-8")) or {}).get("token")
    except Exception:
        return None


def admin_token(force=False, log=log_default):
    """拿一个可用的 admin token。force=True 时无视本地缓存直接自动重登。"""
    if not force:
        t = read_admin_token()
        if t:
            return t
    log("   [自动登录] 本地没有可用 admin token → 用账号密码自动重登")
    return login_admin(log=log)


# ------------------------------------------------------------------ 自检
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    acc = accounts()
    print("凭据：")
    for k in ("order", "admin"):
        a = acc[k]
        print("  %-6s user=%-10s pw=%s  profile=%s"
              % (k, a["username"], "*" * len(a["password"]), a["profile"]))
    print("admin 本地 token：", (read_admin_token() or "（无）")[:12])
