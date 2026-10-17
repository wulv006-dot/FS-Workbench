# -*- coding: utf-8 -*-
"""精确复刻 scrape_books 的 route_book（含 route.fetch 重放），逐步打印状态。

跑法：docker exec qd-render python /app/_qd_render/_qd_diag3.py
只读，不改任何线上东西。
"""
import json
import sys
import time

sys.path.insert(0, "/app")
import core_qd                                            # noqa: E402
from playwright.sync_api import sync_playwright           # noqa: E402

cfg = json.load(open("/app/config.json", encoding="utf-8"))
qd = cfg["千岛"]
URL = qd["url"]
specs = [str(x) for x in (qd.get("抓取区服") or [])]
targets = [("1016203402339694177", "精良巢穴钥匙"),
           ("992552021389241012", "伪先知的奥义"),
           ("992557524316091173", "巢穴钥匙"),
           ("992557706852224435", "强力巢穴钥匙"),
           ("998071421584289615", "腐化根藤")]

bk = dict(core_qd.DEFAULT_BOOK)
bk.update(qd.get("订单簿") or {})
spec_labels = {str(k): core_qd.canon_spec(v)
               for k, v in (qd.get("区服") or {}).items()}
attr_id = str(qd.get("attribute_id") or "")

state = {"busy": False, "done": False, "books": {}, "err": None,
         "blocked": False, "ms": 0}
events = []
T0 = time.time()


def ev(*a):
    events.append("[%6.1fs] %s" % (time.time() - T0, " ".join(str(x) for x in a)))


def route_book(route):
    ev("book_in method=%s post=%d" % (route.request.method,
                                      len(route.request.post_data or "")))
    if state["done"] or state["busy"]:
        ev("book_skip busy=%s done=%s" % (state["busy"], state["done"]))
        return route.continue_()
    state["busy"] = True
    t0 = time.time()
    try:
        tmpl = json.loads(route.request.post_data or "{}")
        first = None
        n_fetch = 0
        for spu, name in targets:
            for sid in specs:
                body = json.loads(json.dumps(tmpl))
                body["spuId"] = spu
                body["offset"] = 0
                core_qd._force_spec(body, sid, spec_labels.get(sid, sid), attr_id)
                items, total, more, off, pages = [], None, True, 0, 0
                while more and pages < core_qd._int(bk.get("最大翻页"), 8):
                    body["offset"] = off
                    r = route.fetch(post_data=json.dumps(body, ensure_ascii=False))
                    n_fetch += 1
                    if first is None:
                        first = r
                    d = (r.json() or {}).get("data") or {}
                    got = d.get("items") or []
                    items += got
                    total = d.get("total", total)
                    more = bool(d.get("more")) and len(got) > 0
                    off += 100
                    pages += 1
                state["books"]["%s|%s" % (sid, spu)] = {
                    "items": items, "total": total if total is not None else len(items),
                    "name": name}
        state["done"] = True
        ev("book_done fetch=%d books=%d" % (n_fetch, len(state["books"])))
        if first is not None:
            route.fulfill(response=first)
        else:
            route.continue_()
    except Exception as e:
        state["err"] = repr(e)[:200]
        ev("book_ERR %s" % repr(e)[:200])
        try:
            route.continue_()
        except Exception as e2:
            ev("book_ERR2 %s" % repr(e2)[:120])
    finally:
        state["ms"] += int((time.time() - t0) * 1000)
        state["busy"] = False
        ev("book_out ms=%d" % state["ms"])


def route_price(route):
    try:
        b = json.loads(route.request.post_data or "{}")
        if "specIds" in b:
            b["specIds"] = [specs[0]]
        route.continue_(post_data=json.dumps(b, ensure_ascii=False))
    except Exception:
        route.continue_()


with sync_playwright() as p:
    br = p.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled"])
    ctx = br.new_context(viewport={"width": 1500, "height": 950},
                         locale="zh-CN", user_agent=core_qd.UA)
    page = ctx.new_page()
    page.route("**/%s*" % core_qd.API_MARK, route_price)
    page.route("**/%s*" % core_qd.BOOK_MARK, route_book)
    try:
        page.goto(URL, wait_until="commit", timeout=120000)
        ev("goto 返回")
        page.wait_for_timeout(int(bk.get("打开等待毫秒", 12000)))
        ev("等待结束 state.done=%s state.err=%s state.ms=%d"
           % (state["done"], state["err"], state["ms"]))
        if core_qd._throttled(page):
            ev("被限流")
        else:
            for nm in [n for _, n in targets]:
                try:
                    ok = page.evaluate(core_qd.JS_OPEN_SPU, nm)
                except Exception as e:
                    ev("点击 %s 异常 %r" % (nm, e))
                    continue
                ev("点击 %-12s -> %s" % (nm, ok))
                if not ok:
                    continue
                for _ in range(int(bk.get("等待轮数", 40))):
                    page.wait_for_timeout(500)
                    if state["done"] or state["err"]:
                        break
                if state["done"] or state["err"]:
                    break
    finally:
        ctx.close()
        br.close()

print("=" * 62)
for e in events[:40]:
    print(" ", e)
print("=" * 62)
print("state: done=%s err=%s blocked=%s ms=%d"
      % (state["done"], state["err"], state["blocked"], state["ms"]))
print("books: %d" % len(state["books"]))
for k in sorted(state["books"])[:10]:
    print("   %-26s items=%d total=%s"
          % (k, len(state["books"][k]["items"]), state["books"][k]["total"]))
print("完")
