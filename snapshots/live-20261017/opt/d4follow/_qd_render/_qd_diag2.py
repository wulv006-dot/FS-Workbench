# -*- coding: utf-8 -*-
"""最小复现：注册 scrape_books 的那两个 route 之后，页面还能不能渲染出商品列表。

跑法：docker exec qd-render python /app/_qd_render/_qd_diag2.py
只读，不改任何线上东西。
"""
import json
import sys

sys.path.insert(0, "/app")
import core_qd                                            # noqa: E402
from playwright.sync_api import sync_playwright           # noqa: E402

cfg = json.load(open("/app/config.json", encoding="utf-8"))
qd = cfg["千岛"]
URL = qd["url"]
specs = [str(x) for x in (qd.get("抓取区服") or [])]
names = ["精良巢穴钥匙", "伪先知的奥义", "巢穴钥匙", "强力巢穴钥匙"]

COUNT_JS = """(n) => {
  const a = [...document.querySelectorAll('div,span,a,li,p')];
  return a.filter(e => (e.textContent || '').trim() === n).length;
}"""


def run(with_routes):
    print("=" * 62)
    print("with_routes = %s" % with_routes)
    print("=" * 62)
    hits = []
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(viewport={"width": 1500, "height": 950},
                             locale="zh-CN", user_agent=core_qd.UA)
        page = ctx.new_page()

        if with_routes:
            def route_price(route):
                # ← 完全照抄 scrape_books 里的实现（无条件带 post_data 重放）
                hits.append(("price", route.request.method,
                             len(route.request.post_data or "")))
                try:
                    b = json.loads(route.request.post_data or "{}")
                    if "specIds" in b:
                        b["specIds"] = [specs[0]]
                    route.continue_(post_data=json.dumps(b, ensure_ascii=False))
                except Exception as e:
                    hits.append(("price_ERR", repr(e)[:100]))
                    try:
                        route.continue_()
                    except Exception as e2:
                        hits.append(("price_ERR2", repr(e2)[:100]))

            def route_book(route):
                hits.append(("book", route.request.method,
                             len(route.request.post_data or "")))
                try:
                    route.continue_()
                except Exception as e:
                    hits.append(("book_ERR", repr(e)[:100]))

            page.route("**/currency-spu-price-list*", route_price)
            page.route("**/spu-list-v2*", route_book)

        page.goto(URL, wait_until="commit", timeout=120000)
        page.wait_for_timeout(12000)
        print("  route 命中        :", hits[:8])
        print("  列表精确匹配      :", [(nm, page.evaluate(COUNT_JS, nm))
                                        for nm in names])
        got = [(nm, page.evaluate(core_qd.JS_OPEN_SPU, nm)) for nm in names]
        print("  点击结果          :", got)
        page.wait_for_timeout(9000)
        print("  点击后 route 命中 :", hits[:20])
        ctx.close()
        br.close()


run(False)
print()
run(True)
print()
print("完")
