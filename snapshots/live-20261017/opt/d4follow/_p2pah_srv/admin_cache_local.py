#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""admin.p2pah.cn（主后台）清缓存 —— **本机执行器**

用户原话（2026-09-24）：
  「点了同步价格后，前端当然不会立即变动，要去另外一个后台找到**工具箱**，
    点击**缓存管理 - 一键清除所有**，前端才会显示；这个清除缓存的操作得在我本机执行。」

真实接口（从 admin.p2pah.cn 的 SPA（Vue+avue）逆向得到，2026-09-24）：
    POST https://admin-api.p2pah.cn/admin/tools.Caches/clear
    headers : batoken: <登录后拿到的 token>   ← axios 请求拦截器统一加
    body    : {"type": "<类型>", "file": ""}
    type    : tp=清理系统缓存 | opcache=清除PHP全部缓存
              storage=清理浏览器缓存 | all=一键清理所有  ← 用户说的那个
    成功    : {"code":1,"msg":"..."}；未登录 → 302 跳登录，拿不到 token

命令
----
    python admin_cache_local.py login            # 打开登录页 → 导出验证码图 → 等答案文件 → 登录并保存 token
    python admin_cache_local.py login --user X --password Y
    python admin_cache_local.py clear            # 用已存 token 清缓存（默认 type=all 一键清理所有）
    python admin_cache_local.py clear --type tp  # 只清系统缓存
    python admin_cache_local.py status           # 看本地 token 是否还在

⚠️ 为什么必须本机：admin.p2pah.cn / admin-api.p2pah.cn 有来源 IP 白名单，
   服务器（47.253.252.55）访问不到 —— 与本项目 order.p2pah.cn 的约束一致。
"""
import argparse
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, "_edge_adminp2pah")
TOKEN_F = os.path.join(HERE, "_admin_token.json")
CAP_PNG = os.path.join(HERE, "_admin_captcha.png")
CAP_ANS = os.path.join(HERE, "_admin_capans.txt")

# 浏览器「通道」（2026-09-27）：与 p2pah_autologin 保持一致 —— 本机用系统装好的 Edge
# （channel="msedge"）；服务器容器 p2pah-srv:1 里没有 Edge，用环境变量 P2PAH_CHANNEL=""
# 让它回落到 Playwright 自带 chromium。不设该变量时行为与本机历史行为完全一致。
CHANNEL = os.environ.get("P2PAH_CHANNEL", "msedge") or None

SITE = "https://admin.p2pah.cn"
API = "https://admin-api.p2pah.cn"
LOGIN_HASH = "/#/admin/login"
DASH_HASH = "/#/admin/dashboard"
CLEAR_URL = API + "/admin/tools.Caches/clear"

TYPES = {"tp": "清理系统缓存", "opcache": "清除PHP全部缓存",
         "storage": "清理浏览器缓存", "all": "一键清理所有"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def log(msg):
    print("[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def _sslctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


# ---------------------------------------------------------------- token
def save_token(tok, extra=None):
    d = {"token": tok, "ts": dt.datetime.now().isoformat(timespec="seconds"),
         "site": SITE}
    if extra:
        d.update(extra)
    with open(TOKEN_F, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    log("token 已存 %s（%d 字符）" % (TOKEN_F, len(tok or "")))


def load_token():
    if not os.path.exists(TOKEN_F):
        return None
    try:
        d = json.load(open(TOKEN_F, encoding="utf-8"))
    except Exception:
        return None
    return d.get("token") or None


# ---------------------------------------------------------------- 清缓存
def clear_cache(type_="all", token=None):
    """POST /admin/tools.Caches/clear → (http_status, body_text)

    🔴 三个必备条件（2026-09-24 实测，缺一不可）：
      ① header **`server: 1`** —— SPA 的 axios 实例默认头：
           axios.create({ baseURL, headers: {"think-lang":.., server: !0}, responseType:"json" })
         少了它后端直接 **302 跳 /index.html**，返回一段 HTML，很容易被误读成「没登录」。
      ② header **`batoken: <token>`** —— 少了它返回 {"code":302,"msg":"Please login first"}。
      ③ URL 带 `?server=1` 双保险（captcha / suffixSvg 等接口也都这么带）。
    另：同类型全量清理**有频控**（30 秒内重复会返回 code=0「操作过于频繁」）。
    """
    body = json.dumps({"type": type_, "file": ""}).encode("utf-8")
    req = urllib.request.Request(
        CLEAR_URL + "?server=1", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/plain, */*",
                 "X-Requested-With": "XMLHttpRequest",
                 "server": "1",
                 "batoken": token or "",
                 "think-lang": "zh-cn",
                 "Origin": SITE,
                 "Referer": SITE + "/",
                 "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45, context=_sslctx()) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, repr(e)


def _auto_relogin(user=None, password=None, headless=True):
    """用账号密码 + 本地离线 OCR 自动重登 admin，拿到新 token 并落盘。

    这是「token 过期」的兜底：以前只能人工认验证码，现在全自动。
    模块缺失（没装 ddddocr 等）时返回 None，调用方退人工。
    """
    try:
        import p2pah_autologin as al
    except Exception as e:
        log("⚠ 自动重登模块不可用（%r），请人工：python admin_cache_local.py login --manual" % e)
        return None
    log("   [自动重登] 用账号密码登录 %s（自动识别验证码）…" % SITE)
    try:
        return al.login_admin(profile=PROFILE, user=user, pw=password,
                              headless=headless, log=log, save=True)
    except Exception as e:
        log("   [自动重登] 异常：%r" % e)
        return None


def cmd_clear(a):
    t = a.type
    tok = a.token or load_token()
    no_auto = bool(getattr(a, "no_auto", False))
    for attempt in (1, 2):
        if not tok:
            if attempt == 1 and not no_auto:
                tok = _auto_relogin(headless=not getattr(a, "headful", False))
            if not tok:
                log("✗ 本地没有可用 token，且自动重登未成功。"
                    "可人工：python admin_cache_local.py login --manual")
                return 3
        log("清缓存 type=%s（%s）…%s"
            % (t, TYPES.get(t, "?"), "" if attempt == 1 else "（重登后重试）"))
        st, body = clear_cache(t, tok)
        log("HTTP %s" % st)
        log("返回：%s" % (body or "")[:400])
        code, msg = None, ""
        try:
            j = json.loads(body)
            code = j.get("code")
            msg = j.get("msg") or ""
        except Exception:
            pass
        if st in (302, 401, 0) or code == 302:
            if attempt == 1 and not no_auto:
                log("⚠ 未登录（HTTP %s / code=%s）→ **用账号密码自动重登**后重试" % (st, code))
                tok = _auto_relogin(headless=not getattr(a, "headful", False))
                if tok:
                    continue
                log("✗ 自动重登失败")
            else:
                log("⚠ 未登录（HTTP %s / code=%s）—— token 已过期" % (st, code))
            return 4
        if code == 1:
            log("✓ %s 成功：%s" % (TYPES.get(t, t), msg))
            return 0
        # 同类型全量清理有 30 秒频控，code=0「操作过于频繁」不算失败
        log("⚠ 已送达但未成功：code=%s msg=%s" % (code, msg))
        return 1
    return 4


def cmd_status(a):
    if not os.path.exists(TOKEN_F):
        log("没有 token 文件（%s）" % TOKEN_F)
        return 1
    d = json.load(open(TOKEN_F, encoding="utf-8"))
    tk = d.get("token") or ""
    log("token 文件：%s" % TOKEN_F)
    log("  存于   : %s" % d.get("ts"))
    log("  账号   : %s" % d.get("user"))
    log("  token  : %s…（%d 字符）" % (tk[:16], len(tk)))
    if a.probe and tk:
        st, body = clear_cache("all", tk)   # 只探活？会真的清一次，注意
        log("  probe  : HTTP %s %s" % (st, (body or "")[:120]))
    return 0


# ---------------------------------------------------------------- 登录
def wait_answer(path, timeout=600):
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    log("等验证码答案：请看图 %s，把字符写进 %s（最多等 %d 秒）"
        % (CAP_PNG, CAP_ANS, timeout))
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(path):
            s = open(path, encoding="utf-8", errors="ignore").read().strip()
            if s:
                return s
        time.sleep(1.5)
    return None


def cmd_login(a):
    from playwright.sync_api import sync_playwright

    user = a.user
    pw = a.password
    if not user or not pw:
        cfgp = os.path.join(HERE, "_admin_account.json")
        if os.path.exists(cfgp):
            c = json.load(open(cfgp, encoding="utf-8"))
            user = user or c.get("username")
            pw = pw or c.get("password")
    if not user or not pw:
        try:                                  # 兜底：_accounts.json / config.json
            import p2pah_autologin as _al
            _a = _al.accounts()["admin"]
            user = user or _a.get("username")
            pw = pw or _a.get("password")
        except Exception:
            pass
    if not user or not pw:
        log("✗ 缺账号密码：用 --user / --password，或写进 %s" % os.path.join(HERE, "_admin_account.json"))
        return 2

    # ① 默认先全自动（ddddocr 本地离线识别验证码），失败才转人工
    if not a.manual:
        log("① 先试全自动（本地 OCR 认验证码，账号 %s）…" % user)
        tok = _auto_relogin(user=user, password=pw, headless=not a.headful)
        if tok:
            log("✓ 全自动登录成功，token 已保存 → %s" % TOKEN_F)
            return 0
        log("自动登录未成功 → 转人工：请看图 %s，把字符写进 %s" % (CAP_PNG, CAP_ANS))

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, channel=CHANNEL, headless=not a.headful,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            pg.goto(SITE + LOGIN_HASH, wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_timeout(6000)
            log("打开 %s → %s" % (LOGIN_HASH, pg.url))
            if "login" not in pg.url.lower():
                log("看起来已是登录态，直接读 localStorage")
            else:
                pg.fill("input[placeholder*='账号']", user, timeout=15000)
                pg.fill("input[type=password]", pw, timeout=15000)
                cap = None
                for im in pg.query_selector_all("img"):
                    src = (im.get_attribute("src") or "")
                    if "captcha" in src.lower():
                        cap = im
                        break
                if cap:
                    cap.screenshot(path=CAP_PNG)
                    log("验证码图已存 %s" % CAP_PNG)
                else:
                    pg.screenshot(path=CAP_PNG, full_page=True)
                    log("未定位到验证码 <img>，已存整页截图 %s" % CAP_PNG)
                ans = wait_answer(CAP_ANS, a.wait)
                if not ans:
                    log("✗ 等验证码超时")
                    return 5
                log("收到验证码答案：%s" % ans)
                pg.fill("input[placeholder*='验证码']", ans, timeout=15000)
                pg.click("button:has-text('登录')", timeout=15000)
                pg.wait_for_timeout(7000)
                log("登录后 URL：%s" % pg.url)
                if "login" in pg.url.lower():
                    body = ""
                    try:
                        body = pg.inner_text("body")
                    except Exception:
                        pass
                    log("✗ 仍在登录页 —— 页面提示：%s" % body[:300].replace("\n", " | "))
                    return 6

            ls = pg.evaluate(
                "()=>{const o={};for(let i=0;i<localStorage.length;i++)"
                "{const k=localStorage.key(i);o[k]=localStorage.getItem(k)}return o}")
            log("localStorage keys: %s" % list(ls.keys()))
            for k, v in ls.items():
                log("   %s = %s" % (k, (str(v) or "")[:90]))

            # ⚠ token **不在** localStorage 的独立 key 里，而是藏在 adminInfo 这个 JSON 里：
            #   adminInfo = {"id":11089,"username":"chenchao","nickname":"陈超",
            #                "token":"8511a106-1935-467f-af54-d6166f5efeb1","refreshToken":"",...}
            tok = None
            ai = ls.get("adminInfo")
            if ai:
                try:
                    tok = (json.loads(ai) or {}).get("token")
                except Exception:
                    pass
            if not tok:
                for k in ("token", "admin-token", "Admin-Token", "batoken", "access_token"):
                    if ls.get(k):
                        tok = ls[k]
                        break
            if not tok:
                import re as _re
                _uuid = _re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                                    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
                for v in ls.values():
                    if isinstance(v, str) and _uuid.match(v.strip()):
                        tok = v.strip()
                        break
            if not tok:
                log("✗ localStorage 里找不到 token")
                return 7
            save_token(tok, {"user": user, "localstorage_keys": list(ls.keys())})
            log("✓ 登录成功，token 已保存。可用：python admin_cache_local.py clear")
            return 0
        finally:
            if a.keep_open:
                input("按回车关闭浏览器…")
            ctx.close()


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="admin.p2pah.cn 清缓存（本机执行器）")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("login", help="登录一次并保存 token（默认全自动，失败转人工）")
    p1.add_argument("--user")
    p1.add_argument("--password")
    p1.add_argument("--wait", type=int, default=600, help="等验证码答案的秒数")
    p1.add_argument("--headful", action="store_true")
    p1.add_argument("--keep-open", action="store_true")
    p1.add_argument("--manual", action="store_true",
                    help="跳过自动识别，直接人工认验证码（自动失败时的退路）")
    p1.set_defaults(func=cmd_login)

    p2 = sub.add_parser("clear", help="清缓存（默认 一键清理所有）")
    p2.add_argument("--type", default="all", choices=list(TYPES.keys()))
    p2.add_argument("--token", help="直接给 token（默认读本地文件）")
    p2.add_argument("--no-auto", action="store_true",
                    help="token 过期时不自动重登，直接报错")
    p2.add_argument("--headful", action="store_true",
                    help="自动重登时显示浏览器窗口（默认无头）")
    p2.set_defaults(func=cmd_clear)

    p3 = sub.add_parser("status", help="看本地 token")
    p3.add_argument("--probe", action="store_true", help="顺便真打一次 clear 探活")
    p3.set_defaults(func=cmd_status)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 0
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
