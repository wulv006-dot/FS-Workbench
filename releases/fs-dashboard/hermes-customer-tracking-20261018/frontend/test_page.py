"""Isolated browser contract for the FC27 administrator customer tracking page."""
import json
import hashlib
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
ENTRY = HERE / "entry"
PAGE = "https://fs.invalid/dashboard/fs-home/hermes/customer-tracking/"
UI = HERE.parents[3] / "ui-system"
SHARED = {"fs-tokens.css": (UI / "tokens/fs-tokens.css", "c88351ce12f9ab3e3ada169bb5e9ee6fe8d82bb53f93b2073050be93f3569df6"),
          "fs-ui.css": (UI / "components/fs-ui.css", "4cfd403f6958ed235159adaf65d882099f36fb310619a558fa89cb83217c0615"),
          "fs-theme.js": (UI / "adapters/fs-theme.js", "b9fa6f6a30fafab089db7a9b7d3f5190c08ca05b8232b57064cd5171cbe54910")}
CONFIG = {"profile": "FC27", "site_id": 266, "product_types": ["Coins", "Items"],
          "min_order_usd_exclusive": "500", "max_discount_usd_exclusive": "25",
          "customer_flags": ["new", "old"], "enabled": True, "version": 1, "last_request_id": None}
VERIFIED = {"candidate_id": "a" * 32, "order_no": "ORDER-1", "email": "customer@example.invalid",
            "uid": 0, "identity_status": "verified", "product_type": "货币(Gold)",
            "customer_flag": "old", "order_usd": "600", "discount_usd": "20", "paid_at": "2026-10-17T12:00:00+08:00"}
MISSING = dict(VERIFIED, candidate_id="b" * 32, order_no="ORDER-2", email=None,
               uid=None, identity_status="unavailable", identity_reason="email_missing_or_invalid")
EMAIL_ONLY = dict(VERIFIED, candidate_id="f" * 32, order_no="ORDER-3", email="other@example.invalid", uid=None)


def run(role, visual=None):
    state = {"posts": [], "urls": [], "tracked": [], "errors": [], "fail_track_once": True, "receipt": None, "denied_after": False, "partial": False, "scheduled_once": False, "detail_reads": 0}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: state["errors"].append(str(error)))

        def route(req):
            url = urlparse(req.request.url)
            path = url.path
            if path == "/dashboard/fs-home/hermes/customer-tracking/":
                return req.fulfill(body=(HERE / "index.html").read_bytes(), content_type="text/html")
            if path.endswith("/customer-tracking/page.js"):
                return req.fulfill(body=(HERE / "page.js").read_bytes(), content_type="text/javascript")
            if path.endswith("/customer-tracking/page.css"):
                return req.fulfill(body=(HERE / "page.css").read_bytes(), content_type="text/css")
            for name, (source, _) in SHARED.items():
                if path.endswith("/" + name):
                    return req.fulfill(body=source.read_bytes(), content_type="text/javascript" if name.endswith(".js") else "text/css")
            if path == "/__hub/hubnav.js":
                return req.fulfill(body="", content_type="text/javascript")
            if path.endswith(".css"):
                return req.fulfill(body="", content_type="text/css")
            if path == "/dashboard/fs-home/advisor.json":
                state["urls"].append(req.request.url)
                if role != "admin" or state["denied_after"]:
                    return req.fulfill(status=403, body='{"error":"admin_required"}', content_type="application/json")
                if req.request.method == "POST":
                    body = req.request.post_data_json
                    state["posts"].append((body, req.request.headers))
                    assert req.request.headers.get("x-fs-advisor-action") == "submit"
                    if body["action"] == "track":
                        state["tracked"].append({"tracking_id": "c" * 32, "candidate_id": body["candidate_id"],
                                                 "email": VERIFIED["email"], "uid": 0, "tracked_at": "2026-10-18T12:00:00+08:00", "status": "active"})
                        state["receipt"] = {"status": "available", "action": "track", "result": {"state": "tracked", "tracking_id": "c" * 32}}
                        if state["fail_track_once"]:
                            state["fail_track_once"] = False
                            return req.fulfill(status=503, body='{"error":"response_uncertain"}', content_type="application/json")
                        return req.fulfill(body=json.dumps(dict(state["receipt"]["result"], request_id=body["request_id"], reused=False)), content_type="application/json")
                    if body["action"] == "save_config":
                        CONFIG["version"] += 1
                        return req.fulfill(body=json.dumps(dict(body["config"], version=CONFIG["version"])), content_type="application/json")
                    return req.fulfill(body='{"status":"pending"}', content_type="application/json")
                query = parse_qs(url.query)
                view = query.get("view", [""])[0]
                if view == "config": value = CONFIG
                elif view == "candidates": value = {"status": "partial" if state["partial"] else "available", "date": query["day"][0], "captured_at": "2026-10-18T08:00:00+08:00", "coverage": {"summary": "覆盖不足" if state["partial"] else "完整"}, "items": [] if state["partial"] else [VERIFIED, MISSING, EMAIL_ONLY]}
                elif view == "tracked": value = {"status": "available", "items": state["tracked"]}
                elif view == "request": value = state["receipt"] or {"status": "unknown"}
                elif view == "detail":
                    state["detail_reads"] += 1
                    milestones = [{"days": 0, "due_at": "2026-10-18T12:00:00+08:00", "state": "needs_review", "conversation_id": "a" * 32, "turn_id": "9" * 32, "artifact_id": None}, {"days": 7, "due_at": "2026-10-25T12:00:00+08:00", "state": "completed", "conversation_id": "d" * 32, "artifact_id": "e" * 32}]
                    if state["scheduled_once"]:
                        milestones = [{"days": 0, "due_at": "2026-10-18T12:00:00+08:00", "state": "scheduled"}, {"days": 7, "due_at": "2026-10-25T12:00:00+08:00", "state": "scheduled"}]
                        state["scheduled_once"] = False
                    elif state["detail_reads"] > 1:
                        milestones[0] = {"days": 0, "due_at": "2026-10-18T12:00:00+08:00", "state": "completed", "conversation_id": "a" * 32, "artifact_id": "f" * 32}
                        milestones[1] = {"days": 7, "due_at": "2026-10-25T12:00:00+08:00", "state": "scheduled"}
                    value = {"status": "active", "tracking_id": "c" * 32, "email": VERIFIED["email"], "uid": 0, "tracked_at": "2026-10-18T12:00:00+08:00", "history_status": "available", "orders": [dict(VERIFIED, status="paid")], "milestones": milestones}
                else: value = {"status": "unknown"}
                return req.fulfill(body=json.dumps(value, ensure_ascii=False), content_type="application/json")
            return req.fulfill(status=404)

        page.route("**/*", route)
        page.goto(PAGE)
        if role != "admin":
            page.get_by_text("当前账号没有智体客单追踪权限。", exact=False).wait_for()
            assert page.locator("#app").is_hidden()
            assert not state["posts"]
        else:
            page.get_by_text("ORDER-1").wait_for()
            assert page.get_by_text("游客（UID 0）").count() >= 1
            cards = page.locator("#candidate-list .record")
            assert cards.count() == 3
            assert cards.nth(0).get_by_role("button", name="加入持续观察").is_enabled()
            assert cards.nth(1).get_by_role("button", name="加入持续观察").is_disabled()
            assert cards.nth(2).get_by_role("button", name="加入持续观察").is_enabled(), "verified email is enough without UID"
            cards.nth(0).get_by_role("button", name="加入持续观察").click()
            page.get_by_role("button", name="核对上次操作").click()
            page.get_by_role("button", name="查看订单与节点").wait_for()
            page.get_by_role("button", name="查看订单与节点").click()
            page.get_by_role("link", name="打开 Hermes 报告原稿").wait_for()
            assert page.get_by_text("已有模型输出，但完整 HTML 原稿未就绪", exact=False).count() == 1
            assert page.get_by_role("link", name="查看 Hermes 建议").count() == 1
            state["scheduled_once"] = True
            page.get_by_role("button", name="刷新观察").click()
            page.get_by_text("首次维护建议 · 首次建议待派发").wait_for()
            page.get_by_text("首次维护建议 · 完整 HTML 原稿已就绪").wait_for(timeout=8000)
            assert state["detail_reads"] == 3, "only day-0 scheduled must resume polling; day-7 scheduled remains dormant"
            assert "2026-10-17 12:00" in page.locator("#candidate-list").inner_text()
            assert "T12:00:00" not in page.locator("main").inner_text()
            if visual:
                visual.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(visual / "light-desktop.png"), full_page=True)
                page.locator("#theme").select_option("dark")
                assert page.locator("html").get_attribute("data-fs-theme") == "dark"
                page.screenshot(path=str(visual / "dark-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "mobile horizontal page overflow"
                page.screenshot(path=str(visual / "dark-mobile.png"), full_page=True)
            assert len(state["posts"]) == 1 and state["posts"][0][0]["action"] == "track"
            assert any("view=request" in url and "request_id=" in url for url in state["urls"])
            assert any("view=candidates" in url and "day=" in url for url in state["urls"])
            assert all("customer@example.invalid" not in url and "ORDER-1" not in url for url in state["urls"])
            state["partial"] = True
            page.get_by_role("button", name="查看名单").click()
            page.get_by_text("采集覆盖不足，不能确认", exact=False).wait_for()
            state["partial"] = False
            page.get_by_role("button", name="查看名单").click()
            page.get_by_text("ORDER-1").wait_for()
            page.locator('input[name="min_order_usd_exclusive"]').fill("700")
            page.get_by_role("button", name="保存条件").click()
            page.get_by_text("配置版本 2").wait_for()
            assert state["posts"][-1][0]["expected_version"] == 1
            assert state["posts"][-1][0]["config"]["min_order_usd_exclusive"] == "700"
            assert "ORDER-1" not in page.locator("#candidate-list").inner_text(), "old-filter candidates must clear after config change"
            state["denied_after"] = True
            page.get_by_role("button", name="刷新名单").click()
            page.get_by_text("当前账号没有智体客单追踪权限。", exact=False).wait_for()
            assert page.locator("#app").is_hidden() and page.locator("#detail").inner_text() == ""
        assert not state["errors"], state["errors"]
        browser.close()


def check_entry():
    html = (ENTRY / "brain-index.html").read_text(encoding="utf-8")
    script = (ENTRY / "brain.js").read_text(encoding="utf-8")
    assert "智体决策报告" in html and "智体客单追踪" in html
    assert 'id="customer-tracking-entry"' in html and 'hidden' in html
    assert "response.status !== 200" in script and "Array.isArray(value?.product_types)" in script


if __name__ == "__main__":
    for source, expected in SHARED.values():
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected, source
    check_entry()
    run("admin", HERE / "visual" if "--visual" in sys.argv else None)
    run("ordinary")
    print("customer tracking frontend: pass")
