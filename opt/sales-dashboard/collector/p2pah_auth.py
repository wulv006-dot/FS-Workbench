# -*- coding: utf-8 -*-
"""P2PAH 双后台会话（Admin + Order）—— 本地看板专用。

来源：复用 fs-workbench `opt/d4follow/_p2pah_srv/p2pah_autologin.py` 已验证方案
（Playwright 持久化 profile + ddddocr 离线破图形验证码），仅保留本看板需要的部分。

对外：
    session()                 -> Session（含 admin token + 两侧 cookies）
    s.get_admin(path, **q)    -> (status, json)
    s.get_order_html(path, **q) -> (status, text)
    s.refresh(force=False)
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
PROFILES = DATA / "_profiles"
STATE_F = DATA / "_session.json"

ADMIN_SITE = "https://admin.p2pah.cn"
ADMIN_API = "https://admin-api.p2pah.cn"
ORDER_SITE = "https://order.p2pah.cn"

# 与 fs-workbench 一致的本机兜底凭据（_accounts.json 优先）
FALLBACK_USER = "chenchao"
FALLBACK_PW = "Fsnet@Cc.2026"

# 本机默认 Edge（更像真人、验证码命中更稳）；无 Edge 时自动回落 chromium
CHANNEL = os.environ.get("P2PAH_CHANNEL", "msedge") or None

_OCR = None


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def accounts():
    """读本机凭据文件；没有就用兜底。"""
    user, pw = FALLBACK_USER, FALLBACK_PW
    for cand in (DATA / "_accounts.json", ROOT / "_accounts.json"):
        if cand.exists():
            try:
                d = json.loads(cand.read_text(encoding="utf-8-sig"))
                a = d.get("admin") or d.get("order") or d
                if isinstance(a, dict) and a.get("username") and a.get("password"):
                    user, pw = a["username"], a["password"]
                    break
            except Exception:
                pass
    return user, pw


# ----------------------------------------------------------------- OCR
def solve(png: bytes) -> str:
    global _OCR
    if not png:
        return ""
    if _OCR is None:
        import ddddocr
        _OCR = ddddocr.DdddOcr(show_ad=False)
    try:
        s = _OCR.classification(png)
    except Exception:
        return ""
    return re.sub(r"[^0-9A-Za-z]", "", s or "")


# ----------------------------------------------------------------- 登录
_IMG_JS = """(sel) => {
  const im = document.querySelector(sel);
  if(!im || !im.complete || !im.naturalWidth) return null;
  const c = document.createElement('canvas');
  c.width = im.naturalWidth; c.height = im.naturalHeight;
  c.getContext('2d').drawImage(im, 0, 0);
  try { return c.toDataURL('image/png'); } catch(e) { return null; }
}"""


def _launch(p, name):
    prof = PROFILES / name
    prof.mkdir(parents=True, exist_ok=True)
    kw = dict(user_data_dir=str(prof), headless=True,
              viewport={"width": 1440, "height": 900},
              args=["--disable-blink-features=AutomationControlled"])
    if CHANNEL:
        try:
            return p.chromium.launch_persistent_context(channel=CHANNEL, **kw)
        except Exception as e:
            log("channel=%s 启动失败(%s)，回落自带 chromium" % (CHANNEL, type(e).__name__))
    return p.chromium.launch_persistent_context(**kw)


def login_admin(pg, user, pw, tries=6):
    """登录 admin.p2pah.cn，成功返回 batoken（UUID）。"""
    cap = {"b": None}

    def _on(r):
        if "common/captcha" in (r.url or "").lower():
            try:
                cap["b"] = r.body()
            except Exception:
                pass

    pg.on("response", _on)
    try:
        for i in range(1, tries + 1):
            cap["b"] = None
            try:
                if "admin.p2pah.cn" in (pg.url or ""):
                    pg.reload(wait_until="domcontentloaded", timeout=90000)
                else:
                    pg.goto(ADMIN_SITE + "/#/admin/login",
                            wait_until="domcontentloaded", timeout=90000)
            except Exception as e:
                log("  admin 打开登录页异常：%r" % e)
                continue
            pg.wait_for_timeout(5000)
            tok = _admin_token(pg)
            if tok:
                log("  admin 已是登录态")
                return tok
            for _ in range(25):
                if cap["b"]:
                    break
                pg.wait_for_timeout(200)
            if not cap["b"]:
                log("  admin 第%d/%d 次：未截获验证码图" % (i, tries))
                continue
            ans = solve(cap["b"])
            if len(ans) != 4:
                log("  admin 第%d/%d 次：识别=%r（长度不足，重试）" % (i, tries, ans))
                continue
            log("  admin 第%d/%d 次 识别=%r" % (i, tries, ans))
            try:
                pg.fill("input[placeholder*='账号']", user, timeout=8000)
                pg.fill("input[type=password]", pw, timeout=8000)
                pg.fill("input[placeholder*='验证码']", ans, timeout=8000)
                pg.click("button:has-text('登录')", timeout=8000)
            except Exception as e:
                log("  admin 填表异常：%r" % e)
                break
            pg.wait_for_timeout(6000)
            tok = _admin_token(pg)
            if tok:
                log("  ✅ admin 登录成功（第 %d 次，验证码=%s）" % (i, ans))
                return tok
        log("  ✗ admin %d 次内未登录成功" % tries)
        return None
    finally:
        try:
            pg.remove_listener("response", _on)
        except Exception:
            pass


def _admin_token(pg):
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


def login_order(pg, user, pw, tries=8):
    """登录 order.p2pah.cn，成功返回 True（cookie 留在上下文里）。"""
    login_url = ORDER_SITE + "/admin"
    for i in range(1, tries + 1):
        if "login.html" not in (pg.url or ""):
            try:
                pg.goto(login_url, wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(1200)
            except Exception as e:
                log("  order 打开登录页异常：%r" % e)
            if "login.html" not in (pg.url or ""):
                log("  order 已是登录态")
                return True
        w = 0
        for _ in range(25):
            try:
                w = pg.evaluate("()=>{const i=document.querySelector('img.captcha');"
                                "return (i&&i.complete)?i.naturalWidth:0}")
            except Exception:
                w = 0
            if w:
                break
            pg.wait_for_timeout(200)
        if not w:
            log("  order 第%d/%d 次：验证码图未出现" % (i, tries))
            try:
                pg.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            continue
        d = None
        try:
            d = pg.evaluate(_IMG_JS, "img.captcha")
        except Exception as e:
            log("  order 取图异常：%r" % e)
        ans = ""
        if d and "," in d:
            ans = solve(base64.b64decode(d.split(",", 1)[1]))
        if len(ans) != 4:
            log("  order 第%d/%d 次：识别=%r（长度不足，重试）" % (i, tries, ans))
            try:
                pg.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            continue
        log("  order 第%d/%d 次 识别=%r" % (i, tries, ans))
        try:
            pg.fill("input[name=username]", user, timeout=8000)
            pg.fill("input[name=password]", pw, timeout=8000)
            pg.fill("input[name=captcha]", ans, timeout=8000)
            pg.click("button.js-ajax-submit", timeout=8000)
        except Exception as e:
            log("  order 填表异常：%r" % e)
            break
        pg.wait_for_timeout(3500)
        if "login.html" not in (pg.url or ""):
            log("  ✅ order 登录成功（第 %d 次，验证码=%s）" % (i, ans))
            return True
        try:
            pg.goto(login_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
    log("  ✗ order %d 次内未登录成功" % tries)
    return False


# ----------------------------------------------------------------- 会话
def _retry(fn, tries=5, base=0.8):
    """网络抖动（SSL record layer failure / 连接重置）重试退避。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            if i == tries - 1:
                break
            time.sleep(base * (i + 1))
    raise last


class Session:
    def __init__(self, token=None, admin_cookies=None, order_cookies=None):
        self.token = token
        self.admin_cookies = admin_cookies or {}
        self.order_cookies = order_cookies or {}

    def save(self):
        STATE_F.parent.mkdir(parents=True, exist_ok=True)
        STATE_F.write_text(json.dumps({
            "token": self.token,
            "admin_cookies": self.admin_cookies,
            "order_cookies": self.order_cookies,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- Admin 侧（JSON） ----------
    def get_admin(self, path, **params):
        import requests
        url = ADMIN_API + path
        h = {"batoken": self.token or "",
             "server": "1", "think-lang": "zh-cn",
             "Origin": ADMIN_SITE, "Referer": ADMIN_SITE + "/",
             "Accept": "application/json, text/plain, */*",
             "Connection": "close"}

        def _do():
            r = requests.get(url, params=params, headers=h,
                             cookies=self.admin_cookies, timeout=30)
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, {"_raw": r.text[:500]}
        return _retry(_do)

    def post_admin(self, path, payload=None, **params):
        import requests
        url = ADMIN_API + path
        h = {"batoken": self.token or "",
             "server": "1", "think-lang": "zh-cn",
             "Origin": ADMIN_SITE, "Referer": ADMIN_SITE + "/",
             "Content-Type": "application/json",
             "Accept": "application/json, text/plain, */*",
             "Connection": "close"}

        def _do():
            r = requests.post(url, json=payload or {}, params=params, headers=h,
                              cookies=self.admin_cookies, timeout=40)
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, {"_raw": r.text[:500]}
        return _retry(_do)

    # ---------- Order 侧（HTML） ----------
    def get_order(self, path, **params):
        import requests
        url = ORDER_SITE + path
        h = {"User-Agent": "Mozilla/5.0", "Referer": ORDER_SITE + "/",
             "Connection": "close"}

        def _do():
            r = requests.get(url, params=params, headers=h,
                             cookies=self.order_cookies, timeout=40)
            return r.status_code, r.text
        return _retry(_do)


def bootstrap(headless=True, force=False):
    """建立两侧会话并落盘。force=True 时忽略本地缓存强制重登。"""
    if not force and STATE_F.exists():
        try:
            d = json.loads(STATE_F.read_text(encoding="utf-8-sig"))
            if d.get("token") and d.get("order_cookies"):
                s = Session(d["token"], d.get("admin_cookies"), d.get("order_cookies"))
                log("载入本地会话缓存")
                return s
        except Exception:
            pass

    from playwright.sync_api import sync_playwright
    user, pw = accounts()
    log("使用账号 %s 登录（密码不外显）" % user)
    with sync_playwright() as p:
        # admin
        ctx = _launch(p, "admin")
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        token = None
        try:
            token = login_admin(pg, user, pw)
            admin_cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        finally:
            try:
                ctx.close()
            except Exception:
                pass
        # order
        ctx2 = _launch(p, "order")
        pg2 = ctx2.pages[0] if ctx2.pages else ctx2.new_page()
        try:
            ok = login_order(pg2, user, pw)
            order_cookies = {c["name"]: c["value"] for c in ctx2.cookies()}
        finally:
            try:
                ctx2.close()
            except Exception:
                pass

    s = Session(token, admin_cookies, order_cookies)
    s.save()
    if not token:
        log("⚠️ admin token 未取得")
    if not ok:
        log("⚠️ order 未登录成功")
    return s


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    u, _ = accounts()
    print("凭据账号：", u)
    ss = bootstrap(force=("--force" in sys.argv))
    print("admin token:", (ss.token or "无")[:8] + "...")
    print("admin cookies:", len(ss.admin_cookies))
    print("order cookies:", len(ss.order_cookies))
