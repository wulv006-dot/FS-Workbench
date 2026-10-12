# -*- coding: utf-8 -*-
"""用真实 Chromium 登录门户，取回会话 Cookie，再用它验证执行器 API 链路。

这是最贴近「用户真机双击 bat」的验证方式：
  浏览器登录 -> 导出 Cookie -> 执行器带上 Cookie 调 API

凭据从环境变量读；没给就跳过正向部分。
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client"))
from mlb_agent import Hub  # noqa: E402

SITE = os.environ.get("MLB_TEST_SERVER", "https://47.85.224.112")
USER = os.environ.get("MLB_TEST_USER", "")
PWD = os.environ.get("MLB_TEST_PASSWORD", "")

res = []


def check(name, ok, detail=""):
    res.append((name, ok, detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- " + detail) if detail else ""))


def main():
    if not (USER and PWD):
        print("[SKIP] 未提供 MLB_TEST_USER / MLB_TEST_PASSWORD，跳过浏览器验证")
        return 0

    from playwright.sync_api import sync_playwright

    cookie_name = None
    cookie_val = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()

        # 1) 打开门户登录页
        page.goto(SITE + "/__auth/login", wait_until="domcontentloaded", timeout=60000)
        title = page.title()
        check("1.1 登录页可打开", "登录" in title or "MMOEXP" in title, title[:60])

        # 2) 填表提交
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        try:
            page.check('input[name="remember"]')
        except Exception:
            pass
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        cur = page.url
        logged_in = "__auth/login" not in cur
        check("2.1 提交后跳离登录页（= 登录成功）", logged_in, cur[:90])

        # 3) 直接拿浏览器里的会话 Cookie
        for c in ctx.cookies():
            if c.get("name", "").upper().startswith("MMOEXP_AUTH") or "AUTH" in c.get("name", "").upper():
                cookie_name, cookie_val = c["name"], c["value"]
                break
        check("3.1 取得门户会话 Cookie", bool(cookie_val),
              ("%s=***" % cookie_name) if cookie_name else "没找到")

        # 4) 浏览器里能打开 MLB 工作台首页
        if logged_in:
            page.goto(SITE + "/mlb/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1200)
            body = page.locator("body").inner_text()[:400]
            ok = "__auth/login" not in page.url
            check("4.1 浏览器可访问 /mlb/（门禁通过）", ok, page.url[:90])

        browser.close()

    if not cookie_val:
        return 1

    # 5) 把浏览器会话交给执行器逻辑，验证 API
    h = Hub(SITE, USER, PWD, timeout=30, log=lambda m: print("      |", m))
    h.cookie = "%s=%s" % (cookie_name, cookie_val)
    agent = "browser-e2e-%d" % int(time.time())
    try:
        hb = h.heartbeat(agent, "mlb-agent/1.1-e2e", "浏览器会话验证")
        check("5.1 用浏览器会话调心跳成功", bool(hb and hb.get("ok")), str(hb)[:90])
    except Exception as e:
        check("5.1 用浏览器会话调心跳成功", False, str(e)[:130])

    try:
        r = h.claim(agent)
        check("5.2 用浏览器会话调认领成功", r is not None, str(r)[:110])
    except Exception as e:
        check("5.2 用浏览器会话调认领成功", False, str(e)[:130])

    return 0


if __name__ == "__main__":
    print("=" * 64)
    print("真实浏览器 · 门户登录 -> 执行器 API 链路验证")
    print("=" * 64)
    rc = main()
    print("-" * 64)
    p = sum(1 for _, ok, _ in res if ok)
    print("结果：%d/%d 通过" % (p, len(res)))
    sys.exit(0 if p == len(res) else 1)
