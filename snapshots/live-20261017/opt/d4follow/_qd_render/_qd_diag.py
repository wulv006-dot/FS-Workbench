# -*- coding: utf-8 -*-
"""容器内诊断：订单簿为什么点不到商品（只读，不改任何东西）

跑法：docker exec qd-render python /app/_qd_render/_qd_diag.py
"""
import json
import sys

sys.path.insert(0, "/app")
import core_qd                                            # noqa: E402
from playwright.sync_api import sync_playwright           # noqa: E402

cfg = json.load(open("/app/config.json", encoding="utf-8"))
qd = cfg["千岛"]
URL = qd["url"]

print("=" * 62)
print("A. 打开聚合价页（与 scrape 同参数）")
print("=" * 62)
reqs = []
with sync_playwright() as p:
    br = p.chromium.launch(headless=True,
                           args=["--disable-blink-features=AutomationControlled"])
    ctx = br.new_context(viewport={"width": 1500, "height": 950}, locale="zh-CN",
                         user_agent=core_qd.UA)
    page = ctx.new_page()
    page.on("request", lambda r: reqs.append(r.url.split("?")[0].rsplit("/", 1)[-1]))
    page.goto(URL, wait_until="commit", timeout=120000)
    page.wait_for_timeout(12000)
    try:
        title = page.title()
    except Exception as e:
        title = "取标题失败 %r" % e
    body = ""
    try:
        body = page.inner_text("body") or ""
    except Exception as e:
        body = "取正文失败 %r" % e
    print("  标题      :", title[:90])
    print("  正文长度  :", len(body))
    print("  正文前200 :", body[:200].replace("\n", " | "))
    print("  含'手速太快':", "手速太快" in body)
    print("  UA        :", page.evaluate("() => navigator.userAgent")[:80])
    print("  chromium  :", br.version)

    print()
    print("=" * 62)
    print("B. 找商品名（JS_OPEN_SPU 的精确匹配口径）")
    print("=" * 62)
    names = ["精良巢穴钥匙", "伪先知的奥义", "巢穴钥匙", "强力巢穴钥匙", "腐化根藤"]
    for nm in names:
        n = page.evaluate("""(n) => {
          const all=[...document.querySelectorAll('div,span,a,li,p')];
          return all.filter(e=>(e.textContent||'').trim()===n).length;
        }""", nm)
        c = page.evaluate("""(n) => {
          const all=[...document.querySelectorAll('div,span,a,li,p')];
          return all.filter(e=>(e.textContent||'').includes(n)).length;
        }""", nm)
        print("  %-12s 精确=%-3d 包含=%-3d" % (nm, n, c))

    print()
    print("  -- 页面里含「钥匙」的文本片段（前 15 个）--")
    frag = page.evaluate("""() => {
      const out=[];
      document.querySelectorAll('*').forEach(e=>{
        const t=(e.textContent||'').trim();
        if(t.includes('钥匙') && t.length<30) out.push(t);
      });
      return [...new Set(out)].slice(0,15);
    }""")
    for t in frag:
        print("     ", t)

    print()
    print("=" * 62)
    print("C. 尝试滚动到底后再找一次（scrape 里有滚动，orders 里没有）")
    print("=" * 62)
    try:
        n = page.evaluate(core_qd.SCROLL_JS)
        print("  滚动容器数:", n)
    except Exception as e:
        print("  滚动异常:", repr(e))
    page.wait_for_timeout(2500)
    for nm in names[:3]:
        n = page.evaluate("""(n) => {
          const all=[...document.querySelectorAll('div,span,a,li,p')];
          return all.filter(e=>(e.textContent||'').trim()===n).length;
        }""", nm)
        print("  滚动后 %-12s 精确=%d" % (nm, n))

    print()
    print("=" * 62)
    print("D. 本次页面发出过的接口（去重）")
    print("=" * 62)
    for u in sorted(set(reqs)):
        print("  ", u)

    print()
    print("=" * 62)
    print("E. 直接点一下「巢穴钥匙」看会不会发 spu-list-v2")
    print("=" * 62)
    hits = []
    page.on("response", lambda r: hits.append(
        (r.url.split("?")[0].rsplit("/", 1)[-1], r.status))
        if "spu-list-v2" in r.url or "spu-static" in r.url else None)
    for nm in names:
        got = page.evaluate(core_qd.JS_OPEN_SPU, nm)
        print("  点击 %-12s -> %s" % (nm, got))
        page.wait_for_timeout(3000)
        if hits:
            break
    print("  命中接口:", hits[:5] if hits else "（无）")

    ctx.close()
    br.close()
print()
print("诊断结束")
