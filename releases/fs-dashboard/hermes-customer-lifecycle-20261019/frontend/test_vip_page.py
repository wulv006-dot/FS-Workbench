"""Browser regression for the original FS tracking entry and weekly follow-up workflow."""
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path.cwd()
ASSETS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
CAPTURE = Path(sys.argv[2]) if len(sys.argv) > 2 else None
ROUTE = "/dashboard/customers/"
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
     "guidance": {"priority": "after_sales", "reason": "上一笔付款已有售后标记，优先核实交付进度。"
                  "过去30天订单比较已归档，首轮维护需要保留订单、退款、时间、平台和站点的完整背景。"
                  "确认客户得到协助后再考虑下一步。"},
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


def install(page, *, admin=True, bulk=False, weekly=True, late_phase=False):
    items = json.loads(json.dumps(CUSTOMERS))
    state = {"events": [], "receipt": {}, "queries": [], "deny_week": False, "errors": [],
             "viewer": "wulv", "bulk_requests": [], "phase_posts": [], "bad_bulk_read": False, "first_bulk_unknown": True, "deny_config": False}
    if bulk:
        items = [
            dict(case_id=f"{i + 1000:032x}", email=f"bulk-{i}@example.invalid", uid=f"{i + 2000}",
                 country="United States", status="queued", guidance={"priority": "due", "reason": "测试复核"},
                 can_update=True, can_bulk_claim=i < 103, events=[], outcome={"kind": "unknown"})
            for i in range(107)
        ]
        items[0].update(email=' =SUM(1,2)', uid='0000000123', country='United "States", test',
                        days_since_last_paid=0, last_paid_at="2026-11-20T02:15:00Z",
                        windows={"month":{"salesUsd":"31.25"}, "firstHalf":{"salesUsd":"31.25"},
                                 "secondHalf":{"salesUsd":"0.00"}})
        items[0]["guidance"].update(reason='第一行含"引号",逗号\n第二行', purchase_days=0, median_gap_days=4.5)
        items[1]["uid"] = "12345678901234567"
        items[2]["uid"] = None
        items[-1].update(status="returned", outcome={"kind": "natural"})

    def route(request):
        url = urlparse(request.request.url)
        name = url.path.rsplit("/", 1)[-1]
        if url.path == ROUTE:
            return request.fulfill(body=(ASSETS / "index.html").read_bytes(), content_type="text/html")
        if url.path == ROUTE + 'reconcile/':
            return request.fulfill(body=(ASSETS / 'reconcile.html').read_bytes(), content_type='text/html')
        if url.path.startswith(ROUTE) and name == "phase.js" and late_phase:
            # Simulate phase.js finishing after page.js has already loaded the config.
            body = b"setTimeout(function(){" + (ASSETS / name).read_bytes() + b"\n}, 600);"
            return request.fulfill(body=body, content_type="text/javascript")
        if url.path.startswith(ROUTE) and name in ("page.js", "page.css", "phase.js"):
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
            assert body["kind"] == "hermes_customer_tracking"
            assert request.request.headers["x-fs-advisor-action"] == "submit"
            if body['action'] in ('phase_decide', 'phase_result'):
                state['phase_posts'].append(body)
                if body['action'] == 'phase_decide':
                    assert isinstance(body['ids'], list) and 1 <= len(body['ids']) <= 100
                    return request.fulfill(json=dict(changed=body['ids'], skipped=0))
                return request.fulfill(json=dict(changed=True))
            if body["action"] == "vip_bulk_claim":
                state["bulk_requests"].append(body)
                assert body["week"] == WEEK and body["scope"] == "global_preferred"
                assert len(body["request_id"]) == 32 and len(body["case_ids"]) <= 100
                assert len(set(body["case_ids"])) == len(body["case_ids"])
                found = {item["case_id"]: item for item in items}
                assert all(found[case_id]["can_bulk_claim"] for case_id in body["case_ids"])
                results = []
                for case_id in body["case_ids"]:
                    target = found[case_id]
                    skipped = case_id == items[0]["case_id"]
                    target.update(status="assigned", owner="DY" if skipped else state["viewer"], can_bulk_claim=False)
                    results.append({"case_id": case_id, "status": "skipped" if skipped else "claimed",
                                    "reason_code": "assigned_to_other" if skipped else "claimed"})
                claimed = sum(row["status"] == "claimed" for row in results)
                receipt = {"status": "recorded", "action": body["action"], "request_id": body["request_id"],
                           "week": WEEK, "scope": body["scope"], "claimed": claimed,
                           "skipped": len(results) - claimed, "items": results}
                state["receipt"][body["request_id"]] = {"status": "available", "action": body["action"], "result": receipt}
                if len(state["bulk_requests"]) == 1 and state["first_bulk_unknown"]:
                    return request.fulfill(status=503, json={"error": "uncertain"})
                return request.fulfill(json=receipt)
            assert body["action"] == "vip_feedback"
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
            if state["deny_config"]:
                return request.fulfill(status=403, json={"error": "admin_required"})
            value = CONFIG
        elif view == 'phase_groups':
            ids = {ident for post in state['phase_posts'] if post['action'] == 'phase_decide' for ident in post['ids']}
            value = dict(status='ready', items=[],
                         last_run=dict(day='2026-11-23', config_version=1),
                         groups=[dict(tier='ultra', stage='silent', customer_type='new', count=12),
                                 dict(tier='ultra', stage='recent', customer_type='old', count=6),
                                 dict(tier='high', stage='lost', customer_type='old', count=20)],
                         queue_counts=dict(ready=3-len(ids), reviewing=2, confirmed=1, issued=4))
        elif view == 'phase_rules':
            value = dict(items=[
                dict(id='rule-A', version=2, enabled=True, tier='ultra', stage='silent',
                     customer_type='new', alert=True, owner='fixture-operator', coupon_id=123,
                     template=dict(mode_type='2', reduce='88', max_reduce='50.00', time_effect='2', days='7')),
                dict(id='rule-B', version=2, enabled=True, tier='high', stage='lost', coupon_id=124),
                dict(id='rule-C', version=2, enabled=True, tier='ultra', stage='long_lost', coupon_id=125),
                dict(id='rule-D', version=1, enabled=True, tier='high', stage='silent', alert=True, owner='wulv'),
            ], dispatch_enabled=False)
        elif view == 'phase_config':
            value = dict(version=1, stages=[14, 30, 60], tiers=dict(high=500, ultra=1000))
        elif view == 'phase_review':
            row = dict(id='review-entry', email=EMAIL, rule_id='rule-A', state='reviewing',
                       identity_status='pending_identity', identity_reason='uid_case_conflict',
                       identity_checked_at='2026-11-24T02:35:00+00:00')
            value = dict(items=[] if state.get('phase_review_resolved') else [row])
        elif view == 'phase_delivery':
            value = dict(items=[dict(id='fixture-entry', email=EMAIL, rule_id='rule-A', state='confirmed',
                                     identity_status='pending_identity', identity_reason='email_conflict')])
        elif view == 'phase_ready':
            if state.get('phase_ready_unavailable'):
                return request.fulfill(status=503, json={'error': 'ready_unavailable'})
            rows = [dict(id=ident, email=email, state='ready', rule_id=rule, rule_version=version, tier=tier, stage=stage,
                         amount_usd=total, unknown_amount_orders=0, ready_at='2026-11-24T02:00:00+00:00',
                         review=dict(decision='pass', manual_coupon_notice='人工券：仅核对已使用记录；另有 1 条用券记录无法归属客户'),
                         coupon=dict(mode_type=2, reduce=reduce, max_reduce=cap, time_effect=2, days=days))
                    for ident, email, rule, version, tier, stage, total, reduce, cap, days in [
                        ('fixture-entry', EMAIL, 'rule-A', 1, 'ultra', 'silent', '1200.00', '89', '50', 7),
                        ('other-entry', 'second@example.invalid', 'rule-B', 2, 'high', 'lost', '800.00', '92', '30.25', 14),
                        ('next-page-entry', 'next-page@example.invalid', 'rule-C', 1, 'ultra', 'silent', None, '90', '50', 7)]]
            removed = {ident for post in state['phase_posts'] if post['action'] == 'phase_decide' for ident in post['ids']}
            rest = [row for row in rows if row['id'] not in removed]
            offset = int(query.get('offset', ['0'])[0])
            value = dict(items=rest[offset:offset+2], next_offset=offset+2 if len(rest) > offset+2 else None)
        elif view == 'phase_manual':
            row = dict(id='fixture-entry', email=EMAIL, rule_id='rule-A', state='unknown', batch='FCSM_'+'A'*32,
                       job_id='original-job', result=dict(identity_conflicts=['grant_batch_no']))
            value = dict(items=[] if any(post['action']=='phase_result' for post in state['phase_posts']) else [row])
        elif view == "vip_week":
            if state["deny_week"]:
                return request.fulfill(status=403, json={"error": "admin_required"})
            week = query["week"][0]
            scope = query["scope"][0]
            assert scope in {"uk_us", "global_preferred"}
            data = items
            summary = SUMMARY
            if scope == "global_preferred":
                data = [dict(item, cycle={"status": "due", "review_day": "2026-11-19"},
                             checks_before_contact=["known_problem_orders"],
                             guidance=dict(item["guidance"], band="P1",
                                           headline="先核实售后，再安排复核",
                                           evidence=["末次付款距今23天", "上一单有售后标记"],
                                           detail="长背景只在展开后显示",
                                           question="上次交付目前解决了吗？")) if item["case_id"] == CASE_ID
                        else dict(item, can_update=False,
                                  cycle={"status": "unknown" if index == 1 else "due" if index in (3, 4) else "normal",
                                         "review_day": None},
                                  guidance=dict(item["guidance"], band="P2" if index in (3, 4) else "watch"))
                        for index, item in enumerate(items)]
                summary = dict(SUMMARY, due_people=3, normal_cycle_people=23, unknown_cycle_people=1, p1_people=1, p2_people=2)
            if bulk:
                data = [dict(item, cycle={"status": "due" if i < 103 else "normal",
                                          "review_day": "2026-11-19"},
                             guidance=dict(item["guidance"], band="P1" if i < 103 else "watch"))
                        for i, item in enumerate(items)]
                summary = dict(SUMMARY, people=len(data))
            value = {"status": "ready", "week": WEEK, "scope": scope, "viewer": state["viewer"],
                     "items": data, "summary": summary, "as_of": NOW} if week == WEEK else {
                "status": "pending", "week": week, "scope": scope, "viewer": state["viewer"], "items": [], "summary": None,
            }
        elif view == "request":
            value = state["receipt"].get(query["request_id"][0], {"status": "unknown"})
            if state["bad_bulk_read"] and value.get("action") == "vip_bulk_claim":
                value = dict(value, result=dict(value["result"], request_id="d" * 32))
        else:
            value = {"status": "available", "items": []}
        return request.fulfill(json=value)

    page.on("pageerror", lambda error: state["errors"].append(str(error)))
    page.route("**/*", route)
    page.clock.install(time=datetime(2026, 11, 20, 2, tzinfo=timezone.utc))
    page.goto(WEB)
    if admin and not late_phase:
        # Stage maintenance is the default tab; the weekly-list checks open their tab explicitly.
        expect(page.locator('#phase-scope')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#phase-panel')).to_be_visible()
        if weekly:
            page.get_by_role('button', name='英美队列', exact=True).click()
    return state


def check_desktop(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    state = install(page)
    card = page.locator(f'[data-case-id="{CASE_ID}"]')
    expect(card.get_by_text(EMAIL)).to_be_visible()
    expect(card.get_by_text("UID 204800")).to_be_visible()
    expect(card.get_by_text("售后优先")).to_be_visible()
    expect(card.get_by_text("优先核对售后进展")).to_be_visible()
    expect(card.get_by_text("过去30天订单比较", exact=False)).to_be_hidden()
    expect(page.get_by_text("UID 未取得")).to_be_visible()
    expect(page.get_by_role("button", name="英美队列")).to_have_attribute("aria-pressed", "true")
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
    page.get_by_role("button", name="全国家优选").click()
    expect(page.get_by_role("button", name="全国家优选")).to_have_attribute("aria-pressed", "true")
    expect(card.get_by_text("领取人 wulv")).to_be_visible()
    expect(card.get_by_text("P1", exact=True)).to_be_visible()
    expect(card.get_by_text("末次付款距今23天", exact=False)).to_be_visible()
    expect(card.get_by_text("联系前需核对 1 项")).to_be_visible()
    expect(card.get_by_text("建议复核 2026-11-19")).to_be_visible()
    expect(card.get_by_text("长背景只在展开后显示")).to_be_hidden()
    card.get_by_text("背景与建议问法", exact=True).click()
    expect(card.get_by_text("长背景只在展开后显示")).to_be_visible()
    expect(card.get_by_text("核对已有问题订单")).to_be_visible()
    expect(card.get_by_text("上次交付目前解决了吗？")).to_be_visible()
    expect(page.locator("#vip-cycle-overview")).to_contain_text("到期复核 3 人 · 正常周期 23 人 · 周期待核 1 人 · P1 1 人 · P2 2 人")
    cycle = page.get_by_label("复核周期")
    cycle.select_option("due")
    expect(visible_rows).to_have_count(3)
    expect(visible_rows.nth(1).get_by_text("P2", exact=True)).to_be_visible()
    cycle.select_option("unknown")
    expect(visible_rows).to_have_count(1)
    expect(visible_rows.first).to_contain_text("周期待核")
    expect(visible_rows.first).to_contain_text("下次复核 2026-11-21")
    cycle.select_option("all")
    if CAPTURE:
        page.screenshot(path=CAPTURE / "vip-maintenance-global-desktop.png")
    assert len(state["events"]) == 1 and "scope" not in state["events"][0]
    card.get_by_role("button", name="记录联系").click()
    card.get_by_label("实际联系时间（北京时间）").fill("2026-11-20T09:30")
    card.get_by_role("button", name="保存联系").click()
    expect(card.get_by_text("已联系", exact=True)).to_be_visible()
    assert state["events"][-1]["contacted_at"] == "2026-11-20T09:30:00+08:00"
    assert state["events"][-1]["scope"] == "global_preferred"
    page.get_by_role("button", name="英美队列").click()
    expect(card.get_by_text("领取人 wulv")).to_be_visible()
    expect(card.get_by_text("已联系", exact=True)).to_be_visible()
    expect(page.locator("#vip-cycle-overview")).to_be_hidden()
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
    expect(page.locator("#vip-list").get_by_text(EMAIL)).to_be_visible()
    page.locator("#theme").select_option("dark")
    expect(page.locator("html")).to_have_attribute("data-fs-theme", "dark")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#vip-list > ol > li")).to_have_count(8)
    page.get_by_role("button", name="全国家优选").click()
    expect(page.get_by_label("复核周期")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#vip-list-count")).to_be_in_viewport()
    link = page.get_by_role("link", name="查看周维护效果")
    expect(link).to_be_visible()
    if CAPTURE:
        page.screenshot(path=CAPTURE / "vip-maintenance-global-mobile.png")
    link.click()
    expect(page.locator("#vip-performance")).to_be_in_viewport()
    if CAPTURE:
        page.screenshot(path=CAPTURE / "vip-maintenance-global-mobile-effect.png")
    assert not state["errors"], state["errors"]
    page = browser.new_page()
    denied = install(page, admin=False)
    expect(page.get_by_text("当前账号没有智体客单追踪权限。", exact=False)).to_be_visible()
    assert page.get_by_text(EMAIL, exact=True).count() == 0
    assert not denied["queries"] and not denied["events"] and not denied["errors"]


def check_bulk_selection_and_csv(browser):
    page = browser.new_page(viewport={"width":1440,"height":900})
    state = install(page, bulk=True)
    selected = page.locator("#vip-selection-status")
    progress = page.locator("#vip-bulk-status")
    choose_all = page.locator("#vip-select-all")
    bulk_claim = page.locator("#vip-bulk-claim")
    first = page.locator("#vip-list > ol > li").first
    expect(first).to_be_visible()
    first.locator("[data-vip-select]").check()
    expect(selected).to_contain_text("已选 1 人 · 可领取 1 人")
    page.locator("#vip-clear-selection").click()
    expect(selected).to_contain_text("已选 0 人")
    choose_all.check()
    expect(selected).to_contain_text("当前筛选 107 人（含折叠及后续行） · 已选 107 人 · 可领取 103 人")
    expect(page.locator("#vip-list > ol > li")).to_have_count(8)
    page.get_by_role("button",name="显示更多",exact=False).click()
    expect(page.locator("#vip-list > ol > li").nth(8).locator("[data-vip-select]")).to_be_checked()
    search = page.locator("#vip-search")
    search.fill("bulk-103@")
    expect(selected).to_contain_text("当前筛选 1 人（含折叠及后续行） · 已选 1 人 · 可领取 0 人")
    expect(bulk_claim).to_be_disabled()
    search.clear()
    expect(selected).to_contain_text("已选 1 人")
    choose_all.check()
    with page.expect_download() as event:
        page.locator("#vip-export").click()
    download = event.value
    assert download.suggested_filename == "FC27-uk_us-2026-11-16.csv"
    raw = download.path().read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"\r\n")
    csv_rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    assert len(csv_rows) == 107 and not state["bulk_requests"]
    assert csv_rows[0]["客户邮箱"] == "' =SUM(1,2)"
    assert csv_rows[0]["付款国家"] == 'United "States", test'
    assert csv_rows[0]["优先理由"] == '第一行含"引号",逗号\n第二行'
    assert csv_rows[0]["会员 UID"] == "'0000000123"
    assert csv_rows[1]["会员 UID"] == "'12345678901234567"
    assert csv_rows[2]["会员 UID"] == ""
    structured = {"距末购天数":"0", "最近有效付款时间（北京时间）":"2026-11-20 10:15",
                  "入组30日实付 USD":"31.25", "入组窗口前15日实付 USD":"31.25", "入组窗口后15日实付 USD":"0.00",
                  "观察购买日数":"0", "本人购买间隔中位数（天）":"4.5"}
    assert all(csv_rows[0][field] == expected and csv_rows[1][field] == "" for field, expected in structured.items())
    assert csv_rows[-1]["跟进状态"] == "已回购"
    page.get_by_role("button",name="全国家优选",exact=True).click()
    expect(selected).to_contain_text("全国家优选 · 2026-11-16 周")
    expect(selected).to_contain_text("已选 0 人")
    search.fill("bulk-1")
    page.locator("#vip-filter").select_option("queued")
    expected = [f"bulk-{i}@example.invalid" for i in range(106) if str(i).startswith("1")]
    expect(selected).to_contain_text(f"当前筛选 {len(expected)} 人")
    rows = page.locator("#vip-list > ol > li")
    expect(rows).to_have_count(8)
    choose_all.check()
    # Keep the same filters as the list expands through its last page.
    more = page.get_by_role("button", name="显示更多", exact=False)
    for _ in range((len(expected) - 1) // 8):
        more.click()
    expect(more).to_have_count(0)
    expect(rows).to_have_count(len(expected))
    expect(rows.last.locator("[data-vip-select]")).to_be_checked()
    with page.expect_download() as event:
        page.locator("#vip-export").click()
    exported = event.value.path().read_text(encoding="utf-8-sig")
    assert [row["客户邮箱"] for row in csv.DictReader(io.StringIO(exported))] == expected
    search.clear()
    page.locator("#vip-filter").select_option("all")
    choose_all.check()
    page.get_by_role("button",name="上一周",exact=True).click()
    expect(choose_all).to_be_hidden()
    page.get_by_role("button",name="下一周",exact=True).click()
    expect(selected).to_contain_text("已选 0 人")
    choose_all.check()
    state["viewer"] = "DY"
    page.locator("#vip-week-form button[type=submit]").click()
    expect(selected).to_contain_text("已选 0 人")
    state["viewer"] = "wulv"
    page.locator("#vip-week-form button[type=submit]").click()
    choose_all.check()
    if CAPTURE:
        page.screenshot(path=CAPTURE / "vip-bulk-scope-selection.png")
    bulk_claim.click()
    expect(progress).to_contain_text("待核 100 人 · 未发送 3 人")
    expect(bulk_claim).to_be_disabled()
    assert [len(row["case_ids"]) for row in state["bulk_requests"]] == [100]
    original = state["bulk_requests"][0]["request_id"]
    state["bad_bulk_read"] = True
    page.locator("#vip-bulk-reconcile").click()
    expect(progress).to_contain_text("原批次仍待核对")
    assert len(state["bulk_requests"]) == 1
    state["bad_bulk_read"] = False
    page.locator("#vip-bulk-reconcile").click()
    expect(progress).to_contain_text("已确认领取 99 人 · 已跳过 1 人 · 未发送 3 人")
    assert [query["request_id"][0] for view, query in state["queries"] if view == "request"] == [original,original]
    assert len(state["bulk_requests"]) == 1
    search.fill("bulk-102@")
    expect(bulk_claim).to_be_disabled()
    search.clear()
    expect(bulk_claim).to_have_text("继续领取剩余（3 人）")
    bulk_claim.click()
    expect(progress).to_contain_text("已确认领取 102 人 · 已跳过 1 人")
    assert "已由其他同事领取 1 人" in progress.inner_text()
    assert [len(row["case_ids"]) for row in state["bulk_requests"]] == [100,3]
    assert state["bulk_requests"][1]["request_id"] != original
    assert not set(state["bulk_requests"][0]["case_ids"]) & set(state["bulk_requests"][1]["case_ids"])
    assert not state["errors"], state["errors"]

    mobile = browser.new_page(viewport={"width":390,"height":844}, is_mobile=True, has_touch=True)
    direct = install(mobile, bulk=True)
    direct["first_bulk_unknown"] = False
    mobile.get_by_role("button",name="全国家优选",exact=True).click()
    mobile.locator("#vip-select-all").check()
    assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if CAPTURE:
        mobile.screenshot(path=CAPTURE / "vip-bulk-mobile.png")
    mobile.locator("#vip-bulk-claim").click()
    expect(mobile.locator("#vip-bulk-status")).to_contain_text("已确认领取 102 人 · 已跳过 1 人")
    assert [len(row["case_ids"]) for row in direct["bulk_requests"]] == [100,3]
    assert not direct["errors"], direct["errors"]


def check_phase_default_view(browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    state = install(page, late_phase=True)
    # phase.js arrives after the config: it must still open the default stage view.
    expect(page.locator('#phase-panel')).to_be_visible()
    expect(page.locator('#phase-overview')).to_contain_text('客户分层与对应动作')
    expect(page.locator('#vip-week-panel')).to_be_hidden()
    # A denied refresh clears the stage view; the next successful refresh reloads it.
    state['deny_config'] = True
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator('#app')).to_be_hidden()
    expect(page.locator('#phase-overview')).to_be_empty()
    state['deny_config'] = False
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator('#phase-overview')).to_contain_text('客户分层与对应动作')
    assert not state['errors'], state['errors']
    page.close()


def check_phase(browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    state = install(page, weekly=False)
    assert page.locator('#vip-scopes button').first.get_attribute('id') == 'phase-scope'
    page.clock.set_fixed_time(datetime.fromisoformat('2026-11-25T01:30:00+00:00'))
    phase = page.get_by_role('button', name='阶段维护', exact=True)
    phase.click()
    expect(page.locator('#phase-overview')).to_contain_text('观察日 2026-11-23')
    expect(page.locator('#phase-overview')).to_contain_text('客户分层与对应动作')
    matrix = page.get_by_role('region', name='客户分层与对应动作')
    offer = matrix.locator('.phase-offer[title="券 #123"]')
    expect(offer).to_contain_text('12% OFF')
    expect(offer).to_contain_text('最多减 $50，7 天有效')
    expect(matrix.locator('.phase-offer[title="券 #124"]')).to_contain_text('最多减 $30.25，14 天有效')
    expect(matrix.locator('.phase-offer[title="券 #125"]')).to_contain_text('条款读取失败')
    expect(matrix.locator('.phase-chip', has_text='分配 wulv').first).to_be_visible()
    expect(matrix.locator('.phase-chip-alert').first).to_have_text('预警')
    assert not matrix.evaluate("el => /\u00b7/.test([...el.querySelectorAll('.phase-cell')].map(c => c.innerText).join(' '))")

    state['phase_ready_unavailable'] = True
    page.locator('#phase-refresh').click()
    expect(matrix.locator('.phase-offer-missing')).to_have_count(2)
    expect(matrix.locator('.phase-offer[title="券 #123"]')).to_contain_text('12% OFF')
    assert not state['phase_posts']
    state['phase_ready_unavailable'] = False
    page.locator('#phase-view').select_option('groups')
    expect(matrix.locator('.phase-offer[title="券 #124"]')).to_contain_text('最多减 $30.25，14 天有效')
    expect(page.locator('#vip-week-panel')).to_be_hidden()
    page.locator('#phase-view').select_option('review')
    review = page.locator('#phase-content')
    expect(review).to_contain_text('案件归属待核：UID 关联到另一未结案件')
    checked = review.locator('time')
    expect(checked).to_have_attribute('datetime', '2026-11-24T02:35:00+00:00')
    expect(checked).to_contain_text('10:35:00')
    state['phase_review_resolved'] = True
    page.locator('#phase-view').select_option('groups')
    page.locator('#phase-view').select_option('review')
    expect(review).to_contain_text('暂无条目')
    page.locator('#phase-view').select_option('ready')
    ready = page.locator('#phase-content')
    expect(ready).to_contain_text('另有 1 条用券记录无法归属客户')
    expect(ready).to_contain_text('11% OFF')
    expect(ready).to_contain_text('最多减 $50.00')
    expect(ready).to_contain_text('7 天')
    expect(ready).to_contain_text('剩 48 小时 30 分')
    expect(ready).to_contain_text('$1,200.00')
    expect(ready).to_contain_text('next-page@example.invalid')
    for theme, width, tag in [('light', 1440, 'light'), ('dark', 1440, 'dark'), ('light', 390, '390')]:
        page.set_viewport_size(dict(width=width, height=900))
        page.locator('#theme').select_option(theme)
        expect(page.locator('html')).to_have_attribute('data-fs-theme', theme)
        assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
        if width == 390:
            table = ready.get_by_role('region', name='待发区客户名单')
            table.focus()
            page.keyboard.press('ArrowRight')
            assert table.evaluate("node => new Promise(resolve => setTimeout(() => resolve(node.scrollLeft > 0), 200))")
            table.evaluate('(node) => { node.scrollLeft = 0; node.blur(); }')
            page.evaluate('scrollTo(0, 0)')
        if CAPTURE:
            page.screenshot(path=str(CAPTURE / f'care-{tag}.png'), full_page=True, animations='disabled')
    page.get_by_label('待发价值档').select_option('ultra')
    expect(ready).not_to_contain_text('second@example.invalid')
    page.get_by_role('checkbox', name='全选当前筛选').check()
    expect(ready.get_by_role('checkbox', name='选择 ' + EMAIL)).to_be_checked()
    expect(ready.get_by_role('checkbox', name='选择 next-page@example.invalid')).to_be_checked()
    page.get_by_role('button', name='确认所选').click()
    expect(ready).to_contain_text('当前筛选暂无条目')
    assert state['phase_posts'][0]['action'] == 'phase_decide'
    assert state['phase_posts'][0]['ids'] == ['fixture-entry', 'next-page-entry']
    page.get_by_label('待发价值档').select_option('high')
    page.get_by_role('checkbox', name='选择 second@example.invalid').check()
    page.get_by_role('button', name='剔除所选').click()
    dialog = page.get_by_role('dialog', name='剔除所选待发条目？')
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role('button', name='取消')).to_be_focused()
    dialog.get_by_role('button', name='取消').click()
    assert len(state['phase_posts']) == 1
    page.get_by_role('button', name='剔除所选').click()
    dialog.get_by_role('button', name='确认剔除').click()
    expect(ready).to_contain_text('暂无条目')
    assert state['phase_posts'][1]['ids'] == ['other-entry']
    assert state['phase_posts'][1]['decision'] == 'removed'
    page.locator('#phase-view').select_option('delivery')
    expect(page.locator('#phase-content')).to_contain_text('已确认 · 身份待核：邮箱与其他客户冲突')
    page.get_by_role('button', name='英美队列', exact=True).click()
    expect(page.locator('#vip-week-panel')).to_be_visible()
    page.goto('https://fs.invalid/dashboard/customers/reconcile/')
    expect(page.get_by_role('heading', name='待人工核对')).to_be_visible()
    expect(page.locator('#phase-content')).to_contain_text('FCSM_' + 'A'*32)
    expect(page.locator('#phase-content')).to_contain_text('回执身份冲突（grant_batch_no）')
    page.get_by_label('核对依据').fill('Admin 原批次已确认')
    page.get_by_role('button', name='登记结果').click()
    expect(page.locator('#phase-content')).to_contain_text('暂无条目')
    assert state['phase_posts'][-1]['action'] == 'phase_result'
    assert state['phase_posts'][-1]['batch'] == 'FCSM_' + 'A'*32
    assert not state['errors']


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('FS_BROWSER_EXECUTABLE'))
        check_desktop(browser)
        check_narrow_and_denied(browser)
        check_bulk_selection_and_csv(browser)
        check_phase_default_view(browser)
        check_phase(browser)
        browser.close()
    print("VIP tracking browser checks passed")
