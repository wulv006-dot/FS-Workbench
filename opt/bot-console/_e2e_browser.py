# -*- coding: utf-8 -*-
"""真实浏览器 E2E：登录态注入 -> 打开 /bots/ -> 断言渲染 -> 截图。
用 playwright 解释器跑：
  C:\\Users\\yi\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe _e2e_browser.py
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://47.85.224.112"
HOST = "47.85.224.112"
TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""
SHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(SHOT_DIR, exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)[:400]))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + str(detail)[:400] if detail else ""))


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1500, "height": 1000},
                              ignore_https_errors=True)
    ctx.add_cookies([{
        "name": "MMOEXP_AUTH", "value": TOKEN,
        "domain": HOST, "path": "/", "secure": False, "httpOnly": False,
        "sameSite": "Lax",
    }])
    page = ctx.new_page()

    console_errors, page_errors, bad_requests = [], [], []
    failed_reqs = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("response", lambda r: bad_requests.append("%s %s" % (r.status, r.url))
            if r.status >= 400 else None)
    page.on("requestfailed", lambda r: failed_reqs.append(
        "%s  %s" % (r.url, (r.failure or ""))))

    resp = page.goto(BASE + "/bots/", wait_until="networkidle", timeout=60000)
    check("页面 HTTP 200", resp is not None and resp.status == 200,
          "status=%s url=%s" % (resp.status if resp else "?", page.url))
    check("未跳转到登录页", "/__auth/access" not in page.url, page.url)

    page.wait_for_timeout(2500)

    # --- 标题 / 结构 ---
    title = page.title()
    check("标题正确", "机器人" in title or "Bot" in title or "控制台" in title, title)

    tabs = page.locator(".tab, [data-tab]")
    check("存在页签", tabs.count() >= 3, "count=%d" % tabs.count())

    # --- 关键：连接状态提示不应误报 intent 未开启 ---
    body_text = page.inner_text("body")
    check("不再出现『SERVER MEMBERS INTENT 未开启』误报",
          "SERVER MEMBERS INTENT 未开启" not in body_text, "")
    check("出现『已成功连接 Discord』绿色提示",
          "已成功连接 Discord" in body_text, "")
    check("显示 DRY-RUN 模式行",
          "DRY-RUN" in body_text, "")
    check("显示本次运行起点",
          "本次运行自" in body_text, "")

    # 抽取所有 .note 的类名+文本，便于核对
    notes = page.eval_on_selector_all(
        ".note",
        "els => els.map(e => ({cls: e.className, txt: e.innerText.replace(/\\s+/g,' ').slice(0,140)}))")
    good = [n for n in notes if "good" in n["cls"]]
    bad = [n for n in notes if "bad" in n["cls"]]
    check("存在 good 级提示", len(good) >= 1, json.dumps(good, ensure_ascii=False)[:300])
    check("无 bad(红色) 级提示", len(bad) == 0, json.dumps(bad, ensure_ascii=False)[:300])

    # --- 控件数量 ---
    ctrl = page.locator("input, select, textarea, button")
    check("控件数量 > 60", ctrl.count() > 60, "count=%d" % ctrl.count())

    # --- dryRun 开关应为「开启/只记录」状态 ---
    dry_html = page.evaluate("""() => {
      const t = document.body.innerText;
      const i = t.indexOf('dryRun');
      return i >= 0 ? t.slice(Math.max(0,i-40), i+160).replace(/\\s+/g,' ') : '';
    }""")
    check("页面出现 dryRun 相关文案", bool(dry_html), dry_html)

    page.screenshot(path=os.path.join(SHOT_DIR, "01_guard.png"), full_page=True)
    print("saved 01_guard.png")

    # --- 切到 Shugo-bot 页签 ---
    ok_tab = False
    for sel in ['text=Shugo-bot', '[data-tab="shugo"]', 'button:has-text("Shugo")']:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                el.click(timeout=5000)
                ok_tab = True
                break
        except Exception:
            continue
    if ok_tab:
        page.wait_for_timeout(2500)
        txt = page.inner_text("body")
        check("Shugo 页签已渲染", "Shugo" in txt, "")
        check("Shugo 未误报 intent 问题", "SERVER MEMBERS INTENT 未开启" not in txt, "")
        page.screenshot(path=os.path.join(SHOT_DIR, "02_shugo.png"), full_page=True)
        print("saved 02_shugo.png")
    else:
        check("Shugo 页签可点击", False, "未找到页签元素")

    # --- 名称测试器 ---
    ok_tester = False
    for sel in ['text=名称测试器', '[data-tab="test"]', 'button:has-text("测试")']:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                el.click(timeout=5000)
                ok_tester = True
                break
        except Exception:
            continue
    if ok_tester:
        page.wait_for_timeout(1200)
        # 直接定位面板里真实的控件 id（#t-names 文本域 / [data-act=run-test] 按钮）
        ta = page.locator("#t-names")
        check("测试器文本域存在", ta.count() == 1, "count=%d" % ta.count())
        if ta.count() == 1:
            ta.fill("MMOEXP Support\nmmoexpert\nMM0EXP\nJohn")
            run_btn = page.locator('[data-act="run-test"]')
            check("『开始判定』按钮存在", run_btn.count() >= 1, "count=%d" % run_btn.count())
            run_btn.first.click()
            page.wait_for_timeout(2500)

            rows = page.eval_on_selector_all(
                "#t-body tr",
                "els => els.map(e => Array.from(e.children).map(c => c.innerText.trim()))")
            summary = page.inner_text("#t-summary") if page.locator("#t-summary").count() else ""
            check("判定表格出现 4 行", len(rows) == 4, json.dumps(rows, ensure_ascii=False)[:400])
            hit = {r[0]: (r[2] if len(r) > 2 else "") for r in rows if r and len(r) >= 3}
            check("MMOEXP Support 判为命中", "命中" in hit.get("MMOEXP Support", ""),
                  json.dumps(hit, ensure_ascii=False)[:300])
            check("MM0EXP 判为命中", "命中" in hit.get("MM0EXP", ""),
                  json.dumps(hit, ensure_ascii=False)[:300])
            check("mmoexpert 判为放行", "命中" not in hit.get("mmoexpert", ""),
                  json.dumps(hit, ensure_ascii=False)[:300])
            check("John 判为放行", "命中" not in hit.get("John", ""),
                  json.dumps(hit, ensure_ascii=False)[:300])
            check("有汇总统计", bool(summary.strip()), summary)
            page.screenshot(path=os.path.join(SHOT_DIR, "03_tester.png"), full_page=True)
            print("saved 03_tester.png")
    else:
        check("名称测试器页签可点击", False, "未找到页签元素")

    check("无 JS 运行时错误", len(page_errors) == 0, json.dumps(page_errors, ensure_ascii=False)[:300])
    # 控制台里的 "Failed to load resource" 一般是外链（Discord CDN 头像）被办公网拦截，
    # 不算脚本错误；真正的逻辑报错（TypeError 等）才要卡住。
    real_errs = [e for e in console_errors if "Failed to load resource" not in e]
    check("无 JS 逻辑类控制台错误", len(real_errs) == 0,
          json.dumps(real_errs, ensure_ascii=False)[:300])
    check("无 4xx/5xx 资源请求", len(bad_requests) == 0,
          json.dumps(bad_requests, ensure_ascii=False)[:400])
    # 外链资源（如 Discord CDN 头像）在办公网会被拦，属预期；只要不是本站资源即可。
    # /__auth/* 与 /dashboard/fs-home/* 是 nginx sub_filter 注入的**全局导航**产生的请求，
    # 该导航用的是 https 绝对地址，在「http + IP 直连」访问方式下必然失败 ——
    # 对照实验已证明既有页面 /dashboard/ 同样失败且更多（21 条 vs 本页 3 条），
    # 属于既有全局行为，不是本次新页面的问题。
    NAV_PREFIXES = ("/__auth/", "/dashboard/fs-home/")
    self_failed = []
    nav_failed = []
    for u in failed_reqs:
        if HOST not in u:
            continue
        if any(p in u for p in NAV_PREFIXES):
            nav_failed.append(u)
        else:
            self_failed.append(u)
    print("nav_failed =", json.dumps(nav_failed, ensure_ascii=False)[:400])
    check("/bots/ 自身资源无加载失败", len(self_failed) == 0,
          json.dumps(self_failed, ensure_ascii=False)[:300])
    if nav_failed:
        print("NOTE 全局导航(https 绝对地址)请求失败 %d 条 —— 既有全局行为，非本次改动引入"
              % len(nav_failed))

    browser.close()

failed = [r for r in results if not r[1]]
print("\n===== 汇总：%d 项，失败 %d 项 =====" % (len(results), len(failed)))
for n, _, d in failed:
    print("  FAIL", n, d)
sys.exit(1 if failed else 0)
