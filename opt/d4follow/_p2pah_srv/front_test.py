# -*- coding: utf-8 -*-
"""看板前端实测（在容器里跑，--network host 直连宿主机 8900）。

验证四件事：
  1. 执行器段能渲染（#execMode / #localHint / #localJobs 有内容）
  2. 显示「执行方式」切换条 + 服务器执行器状态卡
  3. 工单表出现「执行方」列（server/local）
  4. pending 单有「改用本机/改用服务器」按钮
另外把整页截图落盘，回本地肉眼看一眼。
"""
import json
import os
import sys
from playwright.sync_api import sync_playwright

SHOTS = "/srv/_shots"
os.makedirs(SHOTS, exist_ok=True)

errs = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
    pg = b.new_page(viewport={"width": 1500, "height": 1000})
    pg.on("console", lambda m: errs.append("%s: %s" % (m.type, m.text)) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append("pageerror: %s" % e))

    pg.goto("http://127.0.0.1:8900/", wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_timeout(3500)

    api = pg.evaluate("""() => ({
      title: document.title,
      hasExecMode: !!document.getElementById('execMode'),
      hasLocalJobs: !!document.getElementById('localJobs'),
      fns: { renderLocal: typeof renderLocal, setExecMode: typeof setExecMode,
             reassign: typeof reassign, showSrvLog: typeof showSrvLog },
      tocExec: /执行器/.test(document.body.innerText),
    })""")
    print("A. 结构:", json.dumps(api, ensure_ascii=False))

    # 直接驱动渲染（等价于点进第⑥段）
    err = pg.evaluate("""async () => { try { await renderLocal(); return null; }
                                        catch(e) { return String(e); } }""")
    print("B. renderLocal 异常:", err)
    pg.wait_for_timeout(3000)

    out = pg.evaluate("""() => {
      const t = id => (document.getElementById(id)||{}).innerText || '';
      return {
        execModeText: t('execMode'),
        hint: t('localHint'),
        st: t('localSt'),
        ts: t('localTs'),
        jobsLen: (document.getElementById('localJobs').innerHTML||'').length,
        jobsText: t('localJobs').slice(0, 1500),
        hasReassign: /改用本机|改用服务器/.test(document.body.innerHTML),
        hasExecCol: /执行方/.test(t('localJobs')),
      };
    }""")
    print("C. 渲染结果:")
    print(json.dumps(out, ensure_ascii=False, indent=1))

    sp = os.path.join(SHOTS, "front_exec.png")
    pg.screenshot(path=sp, full_page=True)
    print("D. 截图:", sp, os.path.getsize(sp), "bytes")
    print("E. JS 错误:", json.dumps(errs[:12], ensure_ascii=False))
    b.close()
sys.stdout.flush()
