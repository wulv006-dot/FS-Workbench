"""Small browser contract check for the independent Hermes conversation page."""
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
UI = next((base / "ui-system" for base in HERE.parents if (base / "ui-system/tokens/fs-tokens.css").is_file()),
          HERE.parents[1] / ".agent_runtime/traffic-hermes-20261017/repo/ui-system")
CONVERSATION = "a" * 32
TURN = "b" * 32
RUN = "run_" + "c" * 32


def check():
    state = {"turn": None, "calls": [], "steers": [], "stops": [], "reject_once": True, "stop_reject_once": True,
             "denied": False, "seq": 0, "emit": False, "cancel_event": False, "items_empty": False, "created": False}

    def route(request):
        path = urlparse(request.request.url).path
        if path == "/":
            return request.fulfill(body=(HERE / "index.html").read_bytes(), content_type="text/html")
        if path == "/conversation.css":
            return request.fulfill(body=(HERE / "conversation.css").read_bytes(), content_type="text/css")
        if path == "/conversation.js":
            return request.fulfill(body=(HERE / "conversation.js").read_bytes(), content_type="text/javascript")
        if path.endswith("fs-tokens.css"):
            return request.fulfill(body=(UI / "tokens/fs-tokens.css").read_bytes(), content_type="text/css")
        if path.endswith("fs-ui.css"):
            return request.fulfill(body=(UI / "components/fs-ui.css").read_bytes(), content_type="text/css")
        if path.endswith("fs-theme.js"):
            return request.fulfill(body=(UI / "adapters/fs-theme.js").read_bytes(), content_type="text/javascript")
        if path == "/api/hermes/conversations":
            if state["denied"]:
                return request.fulfill(status=403, body='{"error":"forbidden"}', content_type="application/json")
            if request.request.method == "POST":
                assert request.request.headers.get("x-fs-advisor-action") == "submit"
                state["created"] = True
                return request.fulfill(status=201, body=json.dumps({"conversation_id": CONVERSATION}), content_type="application/json")
            if state["items_empty"] and not state["created"]:
                return request.fulfill(body='{"items":[]}', content_type="application/json")
            return request.fulfill(body=json.dumps({"items": [{"conversation_id": CONVERSATION, "title": "测试会话"}]}), content_type="application/json")
        if path == f"/api/hermes/conversations/{CONVERSATION}":
            turns = [] if state["turn"] is None else [state["turn"]]
            return request.fulfill(body=json.dumps({"conversation_id": CONVERSATION, "title": "测试会话", "turns": turns, "last_seq": state["seq"]}), content_type="application/json")
        if path == f"/api/hermes/conversations/{CONVERSATION}/events":
            if state["cancel_event"]:
                state["cancel_event"] = False
                state["turn"]["state"] = "cancelled"
                state["seq"] += 1
                event = {"seq": state["seq"], "type": "run.cancelled", "turn_id": TURN, "run_id": RUN, "payload": {}}
                return request.fulfill(body="data: " + json.dumps(event) + "\n\n", content_type="text/event-stream")
            if state["emit"]:
                state["emit"] = False
                state["turn"]["reply"] = "最终原文"
                state["turn"]["state"] = "completed"
                state["seq"] = 3
                delta = {"seq": 2, "type": "message.delta", "turn_id": TURN, "run_id": RUN, "payload": {"delta": "片段"}}
                done = {"seq": 3, "type": "run.completed", "turn_id": TURN, "run_id": RUN, "payload": {"output": "最终原文"}}
                return request.fulfill(body="data: " + json.dumps(delta, ensure_ascii=False) + "\n\ndata: " + json.dumps(done, ensure_ascii=False) + "\n\n", content_type="text/event-stream")
            return request.fulfill(body=": connected\n\n", content_type="text/event-stream")
        if path == f"/api/hermes/conversations/{CONVERSATION}/turns":
            assert request.request.headers.get("x-fs-advisor-action") == "submit"
            body = json.loads(request.request.post_data)
            state["calls"].append(body)
            if state["reject_once"]:
                state["reject_once"] = False
                return request.fulfill(status=503, body='{"error":"temporary"}', content_type="application/json")
            state["turn"] = {"turn_id": TURN, "text": body["text"], "state": "completed", "run_id": RUN,
                             "reply": "已完成。", "progress": None,
                             "artifacts": [{"artifact_id": "d" * 32, "filename": "original.html", "mime": "text/html"}]}
            state["seq"] = 1
            return request.fulfill(body=json.dumps({"conversation_id": CONVERSATION, "turn_id": TURN, "run_id": RUN, "state": "completed"}), content_type="application/json")
        if path == f"/api/hermes/conversations/{CONVERSATION}/runs/{RUN}/stop":
            assert request.request.headers.get("x-fs-advisor-action") == "submit"
            state["stops"].append(json.loads(request.request.post_data))
            if state["stop_reject_once"]:
                state["stop_reject_once"] = False
                return request.fulfill(status=503, body='{"error":"temporary"}', content_type="application/json")
            if len(state["stops"]) == 2:
                return request.fulfill(status=202, body='{"state":"unknown"}', content_type="application/json")
            state["turn"]["state"] = "cancelled"
            return request.fulfill(status=202, body='{"state":"accepted"}', content_type="application/json")
        if path == f"/api/hermes/conversations/{CONVERSATION}/runs/{RUN}/steer":
            assert request.request.headers.get("x-fs-advisor-action") == "submit"
            state["steers"].append(json.loads(request.request.post_data))
            status = ["rejected", "unknown", "accepted"][min(len(state["steers"]) - 1, 2)]
            return request.fulfill(status=202, body=json.dumps({"state": status}), content_type="application/json")
        return request.fulfill(status=404, body="missing")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("http://localhost/**", route)
        page.goto("http://localhost/")
        page.get_by_role("button", name="测试会话").wait_for()
        page.get_by_role("button", name="发送", exact=True).wait_for(state="visible")
        page.wait_for_function("!document.querySelector('#send-message').disabled")
        page.get_by_label("给 Hermes 发消息").fill("今天先看什么？")
        page.get_by_role("button", name="发送", exact=True).click()
        page.wait_for_timeout(1000)
        assert state["calls"], (page.locator("#status").inner_text(), page.locator("#send-message").inner_text())
        page.get_by_role("button", name="核对上次发送").wait_for()
        page.get_by_role("button", name="核对上次发送").click()
        page.get_by_text("已生成 HTML，可打开原稿查看。").wait_for()
        assert not page.get_by_text("已完成。").is_visible()
        page.get_by_text("展开 Hermes 原始回复").click()
        page.get_by_text("已完成。").wait_for(state="visible")
        assert state["calls"][0]["client_request_id"] == state["calls"][1]["client_request_id"]
        assert page.evaluate("getComputedStyle(document.querySelector('#stop-run')).display") == "none"
        assert page.evaluate("parseInt(getComputedStyle(document.querySelector('.skip')).top) < 0")
        assert page.locator(".artifact-list a").first.get_attribute("target") == "_blank"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.evaluate("FSTheme.set('dark')")
        assert page.evaluate("document.documentElement.dataset.fsTheme") == "dark"
        page.wait_for_timeout(400)
        screenshot = HERE.parents[1] / ".agent_runtime/hermes-conversation-20261018/frontend-dark-mobile.png"
        if screenshot.parent.is_dir():
            page.screenshot(path=str(screenshot), full_page=True)
        state["turn"]["state"] = "running"
        state["turn"]["reply"] = ""
        state["emit"] = True
        page.reload()
        page.get_by_text("已生成 HTML，可打开原稿查看。").wait_for()
        page.get_by_text("展开 Hermes 原始回复").click()
        page.get_by_text("最终原文").wait_for(state="visible")
        assert page.get_by_text("今天先看什么？").count() == 1
        assert page.evaluate("document.documentElement.dataset.fsTheme") == "dark"
        state["turn"]["artifacts"] = []
        state["turn"]["reply"] = "<!doctype html><html><body>原始标记</body></html>"
        state["turn"]["state"] = "running"
        page.reload()
        page.get_by_text("HTML 原稿正在归档，稍后可打开。", exact=True).wait_for()
        assert not page.get_by_text("原始标记").is_visible()
        state["turn"]["state"] = "completed"
        state["turn"]["reply"] = "前言 <article>外套</article> <!doctype html><html><body>文本归档原稿</body></html> 后言"
        state["turn"]["artifacts"] = [{"artifact_id": "e" * 32, "filename": "original.txt", "mime": "text/plain"}]
        page.reload()
        page.get_by_text("回复已归档为文本，可打开原稿查看。", exact=True).wait_for()
        assert page.get_by_role("link", name="打开原稿 · original.txt").get_attribute("target") == "_blank"
        assert not page.get_by_text("文本归档原稿").is_visible()
        page.get_by_text("展开 Hermes 原始回复").click()
        page.get_by_text("前言", exact=False).wait_for(state="visible")
        state["turn"]["artifacts"] = []
        state["turn"]["state"] = "running"
        page.reload()
        page.get_by_label("给 Hermes 发消息").fill("补充证据")
        page.get_by_role("button", name="补充当前任务").click()
        page.get_by_text("本次提交未被接受", exact=False).wait_for()
        assert page.get_by_label("给 Hermes 发消息").input_value() == "补充证据"
        page.get_by_role("button", name="补充当前任务").click()
        page.get_by_role("button", name="核对上次发送").wait_for()
        first_unknown_id = state["steers"][1]["client_request_id"]
        page.get_by_role("button", name="核对上次发送").click()
        page.get_by_text("补充请求已接受；是否被模型处理请以回复为准。").wait_for()
        assert state["steers"][2]["client_request_id"] == first_unknown_id
        assert state["steers"][0]["client_request_id"] != first_unknown_id
        assert page.get_by_label("给 Hermes 发消息").input_value() == ""
        state["turn"]["state"] = "running"
        state["turn"]["reply"] = ""
        page.reload()
        page.get_by_role("button", name="停止当前任务").click()
        page.get_by_role("button", name="停止当前任务").click()
        page.get_by_text("停止状态待核对", exact=False).wait_for()
        page.get_by_role("button", name="停止当前任务").click()
        assert state["stops"][0]["client_request_id"] == state["stops"][1]["client_request_id"]
        assert state["stops"][1]["client_request_id"] == state["stops"][2]["client_request_id"]
        page.get_by_text("已停止；本轮未产生回复。", exact=True).wait_for()
        page.get_by_text("任务已停止。", exact=True).wait_for()
        assert page.get_by_role("button", name="发送", exact=True).is_enabled()
        state["turn"]["state"] = "running"
        state["turn"]["reply"] = "停止前已有的片段"
        state["cancel_event"] = True
        page.reload()
        page.get_by_text("停止前已有的片段", exact=True).wait_for()
        page.get_by_text("已停止；上方保留停止前的回复。", exact=True).wait_for()
        page.get_by_text("任务已停止。", exact=True).wait_for()
        state["turn"].update(state="interrupted", reply="中断前片段", error="连接中断")
        page.reload()
        page.get_by_text("中断前片段", exact=True).wait_for()
        page.get_by_text("任务已中断：连接中断", exact=True).wait_for()
        state["denied"] = True
        page.get_by_role("button", name="新对话").click()
        page.get_by_text("当前账号没有持续对话权限。", exact=True).wait_for()
        assert page.get_by_role("button", name="新对话").is_disabled()
        page.close()

        denied = browser.new_page()
        denied.route("http://localhost/**", route)
        denied.goto("http://localhost/")
        denied.get_by_text("当前账号没有持续对话权限。", exact=True).wait_for()
        assert denied.get_by_role("button", name="新对话").is_disabled()
        assert denied.get_by_role("link", name="返回获准的快捷报告").get_attribute("href") == "/dashboard/fs-home/brain/index.html"
        denied.close()

        state.update(denied=False, items_empty=True, created=False, turn=None, seq=0, reject_once=False)
        fresh = browser.new_page()
        fresh.route("http://localhost/**", route)
        fresh.goto("http://localhost/")
        fresh.get_by_role("button", name="发送", exact=True).wait_for()
        fresh.wait_for_function("!document.querySelector('#send-message').disabled")
        fresh.get_by_label("给 Hermes 发消息").fill("新会话问题")
        fresh.get_by_role("button", name="发送", exact=True).click()
        fresh.get_by_text("已生成 HTML，可打开原稿查看。").wait_for()
        assert state["created"]
        fresh.close()
        browser.close()


if __name__ == "__main__":
    check()
    print("conversation browser contract: pass")
