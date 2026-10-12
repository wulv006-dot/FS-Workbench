# -*- coding: utf-8 -*-
"""看板实测：pending 单上的「改用服务器」按钮（容器内跑，--network host）。

前置：chan_test.py 已把执行方式切到 local，并留下 pending 的 local 单 A（jid 在
      /srv/_jobs/chan_A.txt）。所以这一单本该由本机执行 —— 我们点「改用服务器」，
      验证：① 按钮真的出现在 pending 行上 ② 点击后 exec_mode 真的翻成 server
      ③ 服务器执行器即便在 mode=local 下也会把这单执行掉（zero-op 单，无副作用）。
"""
import json
import os
import sys
from playwright.sync_api import sync_playwright

JID = open("/srv/_jobs/chan_A.txt", encoding="utf-8").read().strip()
print("目标工单 A =", JID)

errs = []
SH = "/srv/_shots"
os.makedirs(SH, exist_ok=True)


def row_text(pg):
    return pg.evaluate("""(jid) => {
      for (const tr of document.querySelectorAll('#localJobs tr')) {
        if (tr.innerText.includes(jid)) return tr.innerText.replace(/\\s+/g,' ').trim();
      }
      return null;
    }""", JID)


with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    pg = b.new_page(viewport={"width": 1500, "height": 1000})
    pg.on("console", lambda m: errs.append("%s: %s" % (m.type, m.text)) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append("pageerror: %s" % e))

    pg.goto("http://127.0.0.1:8900/", wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_timeout(3500)

    # 首屏渲染有竞态：轮询 renderLocal 直到目标行出现（最多 30s）
    t = None
    for i in range(10):
        pg.evaluate("async () => { try { await renderLocal(); } catch(e) {} }")
        pg.wait_for_timeout(3000)
        t = row_text(pg)
        if t:
            break
        print("   …第 %d 次仍未见目标行" % (i + 1))
    print("1) 点击前该行 =", t)
    print("   含「改用服务器」按钮 =", bool(t and "改用服务器" in t))
    pg.screenshot(path=os.path.join(SH, "chan_before.png"), full_page=True)

    btn = pg.locator("#localJobs tr", has_text=JID).get_by_text("改用服务器")
    print("2) 按钮个数 =", btn.count())
    btn.first.click()
    pg.wait_for_timeout(3500)
    toast = pg.evaluate("() => (document.getElementById('toast')||{}).innerText || ''")
    print("3) 点击后提示 =", repr(toast))
    pg.evaluate("async () => { await renderLocal(); }")
    pg.wait_for_timeout(2000)
    print("4) 点击后该行 =", row_text(pg))
    pg.screenshot(path=os.path.join(SH, "chan_after_click.png"), full_page=True)

    print("5) 等服务器执行器认领并跑完（最多 150s）...")
    for i in range(10):
        pg.wait_for_timeout(15000)
        pg.evaluate("async () => { await renderLocal(); }")
        pg.wait_for_timeout(1500)
        tx = row_text(pg) or ""
        print("   [%02ds] %s" % ((i + 1) * 15, tx))
        if "成功" in tx and "进行中" not in tx:
            break

    pg.screenshot(path=os.path.join(SH, "chan_done.png"), full_page=True)
    print("6) 执行器状态区 =", pg.evaluate(
        "() => (document.getElementById('localHint')||{}).innerText || ''").replace("\n", " | "))
    print("7) JS 错误:", json.dumps(errs[:12], ensure_ascii=False))
    b.close()
sys.stdout.flush()
