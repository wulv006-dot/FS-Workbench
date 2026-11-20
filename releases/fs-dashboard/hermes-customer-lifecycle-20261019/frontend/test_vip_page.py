"""Browser regression for the original FS tracking entry and weekly follow-up workflow."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path.cwd()
ASSETS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
CAPTURE = Path(sys.argv[2]) if len(sys.argv) > 2 else None
ROUTE = "/dashboard/fs-home/hermes/customer-tracking/"
WEB = "https://fs.invalid" + ROUTE
WEEK = "2026-11-16"
CASE_ID = "7" * 32
RETURNED_ID = "8" * 32
NOW = "2026-11-20T02:00:00Z"
EMAIL = "player-follow-up@example.invalid"
CONFIG = {
    "profile": "FC27", "site_id": 266, "product_types": ["Coins", "Items"],
    "min_order_usd_exclusive": "500", "max_discount_usd_exclusive": "25",
    "customer_flags": ["new", "old"], "enabled": True, "version": 1,
}
SHARED = {
    "fs-tokens.css": ("ui-system/tokens/fs-tokens.css", "text/css"),
    "fs-ui.css": ("ui-system/components/fs-ui.css", "text/css"),
    "fs-theme.js": ("ui-system/adapters/fs-theme.js", "text/javascript"),
    "nav.js": ("releases/fs-dashboard/hermes-navigation-range-20261019/candidate/nav.js", "text/javascript"),
    "hermes-nav.css": ("releases/fs-dashboard/hermes-navigation-range-20261019/candidate/hermes-nav.css", "text/css"),
}
CUSTOMERS = [
    {"case_id": CASE_ID, "email": EMAIL, "uid": 204800, "country": "United States", "owner": None,
     "guidance": {"priority": "after_sales", "reason": "上一笔付款已有售后标记，优先核实交付进度。"},
     "status": "queued", "can_update": True, "last_paid_at": "2026-11-02T02:00:00Z",
     "events": [], "outcome": {"status": "immature", "kind": "unknown"}},
    {"case_id": "9" * 32, "email": "long-customer-identifier-for-layout@example.invalid", "uid": None,
     "owner": "DY", "can_update": False, "carried_over": True,
     "guidance": {"priority": "due", "reason": "近半月暂无已付款记录，安排本周复核。"}, "status": "assigned",
     "next_review_day": "2026-11-21", "events": [],
     "outcome": {"status": "partial", "kind": "unknown"}},
    {"case_id": RETURNED_ID, "email": "returning-player@example.invalid", "uid": 104819,
     "guidance": {"priority": "review", "reason": "观察单已付款。"}, "status": "returned",
     "can_update": False, "events": [], "outcome": {"kind": "natural", "status": "immature", "paid_usd": "575.20"}},
]
CUSTOMERS.extend({
    "case_id": f"{100 + i:032x}", "email": f"fixture-player-{i}@example.invalid", "uid": 300000 + i,
    "owner": "wulv" if i < 2 else None, "can_update": True,
    "status": "contacted" if i < 2 else "queued",
    "events": [{"event": "contacted", "actor": "wulv", "at": NOW}] + (
        [{"event": "feedback", "actor": "wulv", "at": NOW}] if i == 1 else []
    ) if i < 2 else [],
    "guidance": {"priority": "due", "reason": "需复核近半月付款证据。"},
    "outcome": {"status": "immature", "kind": "unknown"},
} for i in range(24))
SUMMARY = {
    "people": len(CUSTOMERS), "new_people": len(CUSTOMERS) - 1, "carried_people": 1, "closed_people": 0,
    "contacted_people": 2, "natural_people": 1, "natural_usd": "575.20",
    "post_contact_people": 0, "post_contact_usd": "0.00", "immature_people": 1, "unknown_people": 1,
}


def install(page, *, admin=True):
    items = json.loads(json.dumps(CUSTOMERS))
    state = {"events": [], "receipt": {}, "queries": [], "deny_week": False, "errors": []}

    def route(request):
        url = urlparse(request.request.url)
        name = url.path.rsplit("/", 1)[-1]
        if url.path == ROUTE:
            return request.fulfill(body=(ASSETS / "index.html").read_bytes(), content_type="text/html")
        if url.path.startswith(ROUTE) and name in ("page.js", "page.css"):
            return request.fulfill(body=(ASSETS / name).read_bytes(),
                                   content_type="text/javascript" if name.endswith(".js") else "text/css")
        if name in SHARED:
            source, content_type = SHARED[name]
            return request.fulfill(body=(ROOT / source).read_bytes(), content_type=content_type)
        if not url.path.endswith("/advisor.json"):
            return request.fulfill(status=404)
        if not admin:
            return request.fulfill(status=403, json={"error": "admin_required"})
        if request.request.method == "POST":
            body = request.request.post_data_json
            assert body["kind"] == "hermes_customer_tracking" and body["action"] == "vip_feedback"
            assert request.request.headers["x-fs-advisor-action"] == "submit"
            assert body["case_id"] == CASE_ID and len(body["request_id"]) == 32
            state["events"].append(body)
            item = items[0]
            event = {**body, "actor": "wulv", "at": NOW}
            item["events"].append(event)
            new_state = {"claim": "assigned", "contacted": "contacted", "close": "closed"}.get(body["event"], item["status"])
            item.update(owner="wulv", status=new_state)
            state["receipt"][body["request_id"]] = {"status": "available", "action": body["action"], "result": {"status": "recorded", "case_id": CASE_ID, "event": body["event"], "request_id": body["request_id"]}}
            if body["event"] == "claim":
                return request.fulfill(status=503, json={"error": "uncertain"})
            return request.fulfill(json=state["receipt"][body["request_id"]]["result"])
        query = parse_qs(url.query)
        view = query["view"][0]
        state["queries"].append((view, query))
        if view == "config":
            value = CONFIG
        elif view == "vip_week":
            if state["deny_week"]:
                return request.fulfill(status=403, json={"error": "admin_required"})
            week = query["week"][0]
            value = {"status": "ready", "week": WEEK, "items": items, "summary": SUMMARY, "as_of": NOW} if week == WEEK else {
                "status": "pending", "week": week, "items": [], "summary": None,
            }
        elif view == "request":
            value = state["receipt"].get(query["request_id"][0], {"status": "unknown"})
        else:
            value = {"status": "available", "items": []}
        return request.fulfill(json=value)

    page.on("pageerror", lambda error: state["errors"].append(str(error)))
    page.route("**/*", route)
    page.clock.install(time=datetime(2026, 11, 20, 2, tzinfo=timezone.utc))
    page.goto(WEB)
    return state


def check_desktop(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    state = install(page)
    card = page.locator(f'[data-case-id="{CASE_ID}"]')
    expect(card.get_by_text(EMAIL)).to_be_visible()
    expect(card.get_by_text("UID 204800")).to_be_visible()
    expect(card.get_by_text("售后优先")).to_be_visible()
    expect(page.get_by_text("UID 未取得")).to_be_visible()
    expect(page.locator("#vip-performance meter")).to_have_count(3)
    expect(page.get_by_text("已回购与已结案（1）")).to_be_visible()
    expect(page.get_by_text("returning-player@example.invalid")).to_be_hidden()
    expect(page.get_by_role("heading", name="筛选条件")).to_be_hidden()
    expect(page.locator("#vip-list-count")).to_have_text("优先待跟进 25 人 · 本周名单 27 人")
    visible_rows = page.locator("#vip-list > ol > li")
    expect(visible_rows).to_have_count(8)
    if CAPTURE:
        page.screenshot(path=CAPTURE / "vip-maintenance-desktop.png")
    page.get_by_role("button", name="显示更多", exact=False).click()
    expect(visible_rows).to_have_count(16)
    expect(visible_rows.nth(8)).to_be_focused()
    filters = page.get_by_label("跟进状态")
    filters.select_option("needs_feedback")
    expect(visible_rows).to_have_count(1)
    expect(visible_rows.first).to_contain_text("fixture-player-0@example.invalid")
    filters.select_option("mine")
    expect(visible_rows).to_have_count(2)
    filters.select_option("queued")
    expect(visible_rows).to_have_count(8)
    search = page.get_by_label("搜索客户")
    search.fill("300023")
    expect(visible_rows).to_have_count(1)
    expect(visible_rows.first).to_contain_text("fixture-player-23@example.invalid")
    search.fill("returning-player")
    expect(page.get_by_text("没有符合当前搜索和筛选的客户。")).to_be_visible()
    filters.select_option("all")
    expect(page.get_by_text("returning-player@example.invalid")).to_be_visible()
    search.clear()
    page.get_by_role("button", name="上一周").click()
    expect(page.get_by_text("本周名单尚在准备。")).to_be_visible()
    expect(page.locator("#vip-performance")).to_be_hidden()
    page.get_by_role("button", name="下一周").click()
    card.get_by_role("button", name="领取跟进").click()
    card.get_by_role("button", name="核对上次操作").click()
    expect(card.get_by_text("领取人 wulv")).to_be_visible()
    assert len(state["events"]) == 1
    assert any(view == "request" and query["request_id"] == [state["events"][0]["request_id"]]
               for view, query in state["queries"])
    card.get_by_role("button", name="记录联系").click()
    card.get_by_label("实际联系时间（北京时间）").fill("2026-11-20T09:30")
    card.get_by_role("button", name="保存联系").click()
    expect(card.get_by_text("已联系", exact=True)).to_be_visible()
    assert state["events"][-1]["contacted_at"] == "2026-11-20T09:30:00+08:00"
    card.get_by_role("button", name="填写反馈").click()
    card.get_by_label("维护反馈（可选）").fill("<b>已核对交付</b>")
    card.get_by_label("反馈原因（可选）").select_option("fulfillment")
    card.get_by_role("button", name="保存反馈").click()
    card.get_by_text("跟进记录（3）").click()
    expect(card.get_by_text("<b>已核对交付</b>", exact=True)).to_be_visible()
    assert card.locator("b").count() == 0
    assert state["events"][-1]["reason"] == "fulfillment"
    card.get_by_role("button", name="结案", exact=True).click()
    card.get_by_label("结案原因").select_option("no_contact")
    card.get_by_role("button", name="保存结案").click()
    expect(card.get_by_text("已结案", exact=True)).to_be_visible()
    assert state["events"][-1]["reason"] == "no_contact"
    page.locator("#legacy-tools summary").click()
    expect(page.get_by_role("heading", name="筛选条件")).to_be_visible()
    expect(page.locator("#pool-reports")).to_contain_text("尚无全局追踪报告")
    state["deny_week"] = True
    page.locator("#vip-week-form").get_by_role("button", name="查看").click()
    expect(page.locator("#app")).to_be_hidden()
    assert page.get_by_text(EMAIL, exact=True).count() == 0
    assert not state["errors"], state["errors"]


def check_narrow_and_denied(browser):
    page = browser.new_page(viewport={"width": 390, "height": 844}, color_scheme="dark", is_mobile=True, has_touch=True)
    state = install(page)
    expect(page.get_by_text(EMAIL)).to_be_visible()
    page.locator("#theme").select_option("dark")
    expect(page.locator("html")).to_have_attribute("data-fs-theme", "dark")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#vip-list > ol > li")).to_have_count(8)
    link = page.get_by_role("link", name="查看周维护效果")
    expect(link).to_be_visible()
    if CAPTURE:
        page.screenshot(path=CAPTURE / "vip-maintenance-mobile.png")
    link.click()
    expect(page.locator("#vip-performance")).to_be_in_viewport()
    if CAPTURE:
        page.screenshot(path=CAPTURE / "vip-maintenance-mobile-effect.png")
    assert not state["errors"], state["errors"]
    page = browser.new_page()
    denied = install(page, admin=False)
    expect(page.get_by_text("当前账号没有智体客单追踪权限。", exact=False)).to_be_visible()
    assert page.get_by_text(EMAIL, exact=True).count() == 0
    assert not denied["queries"] and not denied["events"] and not denied["errors"]


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        check_desktop(browser)
        check_narrow_and_denied(browser)
        browser.close()
    print("VIP tracking browser checks passed")
