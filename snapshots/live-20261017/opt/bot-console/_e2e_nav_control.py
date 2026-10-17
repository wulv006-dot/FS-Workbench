# -*- coding: utf-8 -*-
"""对照实验：同一浏览器访问 /bots/ 与既有页面 /dashboard/，比较失败请求集合。
若两者失败项一致 -> 说明是全局导航（nginx sub_filter 注入）的固有行为，与本次新页面无关。
"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://47.85.224.112"
HOST = "47.85.224.112"
TOKEN = sys.argv[1]

PAGES = [("/bots/", "新页面 机器人控制台"), ("/dashboard/", "既有页面 仪表盘")]

out = {}
with sync_playwright() as p:
    browser = p.chromium.launch()
    for path, label in PAGES:
        ctx = browser.new_context(viewport={"width": 1400, "height": 900},
                                  ignore_https_errors=True)
        ctx.add_cookies([{"name": "MMOEXP_AUTH", "value": TOKEN, "domain": HOST,
                          "path": "/", "secure": False, "httpOnly": False,
                          "sameSite": "Lax"}])
        page = ctx.new_page()
        failed = []
        page.on("requestfailed", lambda r: failed.append(r.url))
        try:
            r = page.goto(BASE + path, wait_until="networkidle", timeout=60000)
            code = r.status if r else "?"
        except Exception as exc:
            code = "ERR:%s" % exc
        page.wait_for_timeout(2500)
        out[label] = sorted(set(failed))
        print("=== %s %s  HTTP=%s  失败请求 %d 条" % (label, path, code, len(out[label])))
        for u in out[label]:
            print("    ", u)
        ctx.close()
    browser.close()

# 归一化路径后比较（去掉 query）
def norm(urls):
    return sorted({u.split("?")[0] for u in urls})

a = norm(out["新页面 机器人控制台"])
b = norm(out["既有页面 仪表盘"])
print("\n=== 归一化后比较 ===")
print("新页面 :", json.dumps(a, ensure_ascii=False))
print("既有页 :", json.dumps(b, ensure_ascii=False))
print("新页面独有 :", json.dumps(sorted(set(a) - set(b)), ensure_ascii=False))
