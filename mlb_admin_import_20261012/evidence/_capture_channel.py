# -*- coding: utf-8 -*-
"""MLB 后台「产品模型管理」通道逆向 —— 只读抓包。

目标：回答老大「MLB 是不是跟 FC 不同的单独通道」。
做法：
  1. 真实 Chrome 登录 admin.p2pah.cn（用 ddddocr 过码）
  2. 打开「产品模型管理」页（/#/admin/goods/goodsMould），筛 游戏=927 | MLB 26
  3. 记录页面加载的所有 JS chunk 名 + 所有 XHR/fetch 请求 URL
  4. 【关键】找出前端加载的 goodsMould 业务模块 chunk，从里面挖"新增/导入"调用的接口

⛔ 红线：本脚本**只读**。绝不点击「添加/提交/保存/导入」，绝不发任何非 GET 请求。
"""
import json
import re
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from playwright.sync_api import sync_playwright

ADMIN_PAGE = "https://admin.p2pah.cn"
OUT = HERE / "capture_20261012"
OUT.mkdir(exist_ok=True)

# 读取凭据
cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
USER, PWD = cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"]


def main():
    oss = None
    try:
        import ddddocr
        oss = ddddocr.DdddOcr(show_ad=False)
        print("[ocr] ddddocr ready", flush=True)
    except Exception as e:
        print("[ocr] ddddocr 不可用:", e, flush=True)

    js_chunks = []
    xhr_log = []
    doc_log = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 950})
        page = ctx.new_page()

        def on_req(req):
            u = req.url
            if req.resource_type in ("xhr", "fetch"):
                xhr_log.append({"m": req.method, "u": u,
                                "post": (req.post_data or "")[:400]})
            elif req.resource_type == "script" and ".js" in u:
                js_chunks.append(u)
            elif req.resource_type == "document":
                doc_log.append(u)

        page.on("request", on_req)

        print("[nav] 打开登录页", flush=True)
        page.goto(ADMIN_PAGE + "/#/admin", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # ---- 过码登录 ----
        # 找验证码图片元素
        img = None
        for sel in ("img[src*='captcha']", ".login-captcha img", "img.login-code"):
            el = page.query_selector(sel)
            if el:
                img = el
                break
        print("[login] 验证码元素:", bool(img), flush=True)
        if img:
            png = img.screenshot()
            (OUT / "captcha.png").write_bytes(png)
            code = (oss.classification(png) or "").strip() if oss else ""
            print("[login] ocr =", code, flush=True)
            # 填表
            try:
                page.fill("input[placeholder*='账号'], input[name='username'], input[type='text']", USER)
            except Exception as e:
                print("[login] 填账号失败:", e, flush=True)
            try:
                page.fill("input[type='password']", PWD)
            except Exception as e:
                print("[login] 填密码失败:", e, flush=True)
            try:
                page.fill("input[placeholder*='验证码'], input[name='captcha']", code)
            except Exception as e:
                print("[login] 填验证码失败:", e, flush=True)
            page.wait_for_timeout(500)
            for sel in ("button:has-text('登录')", "button:has-text('登 录')", ".login-btn"):
                b = page.query_selector(sel)
                if b:
                    b.click()
                    print("[login] 已点登录", flush=True)
                    break
            page.wait_for_timeout(6000)

        # ---- 打开产品模型管理 ----
        url = ADMIN_PAGE + "/#/admin/goods/goodsMould"
        print("[nav] 打开", url, flush=True)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        body = page.content()
        (OUT / "goodsMould_page.html").write_text(body, encoding="utf-8")
        print("[page] 已存页面快照", len(body), "chars", flush=True)

        # 记录标题/是否登录成功
        title = page.title()
        print("[page] title =", title, flush=True)

        ctx.close()
        browser.close()

    (OUT / "requests_xhr.json").write_text(
        json.dumps(xhr_log, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "js_chunks.json").write_text(
        json.dumps(sorted(set(js_chunks)), ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "docs.json").write_text(
        json.dumps(doc_log, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== XHR/fetch 请求 (%d) ===" % len(xhr_log), flush=True)
    for r in xhr_log:
        print("  %-4s %s" % (r["m"], r["u"]), flush=True)
    print("\n=== JS chunks (%d) ===" % len(set(js_chunks)), flush=True)
    for u in sorted(set(js_chunks)):
        print("  ", u, flush=True)


if __name__ == "__main__":
    main()
