"""Browser contract for the separate data analysis tools page."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent
WORKSPACE = next((base for base in HERE.parents if (base / "ui-system/tokens/fs-tokens.css").is_file()), HERE.parents[2])
UI = WORKSPACE / "ui-system" if (WORKSPACE / "ui-system").is_dir() else WORKSPACE / ".agent_runtime/traffic-hermes-20261017/repo/ui-system"
ACTIVE = WORKSPACE / ".agent_runtime/hermes-data-workspace-20261018/tools-page-active-shell.js"


def check_shell():
    if not ACTIVE.is_file():
        candidate = (HERE / "analytics-shell.js").read_text(encoding="utf-8")
        assert "mountBusinessDataWorkspace" not in candidate
        return
    active = ACTIVE.read_bytes()
    assert hashlib.sha256(active).hexdigest() == "1d0d5f40e7941c8cb8d56788ffb2f2c44864a12771bb4bc60cbea6a6ccc6d3df"
    expected = active.replace(b"import {mountBusinessDataWorkspace} from './data-workspace.js';\n", b"")
    expected = expected.replace(b"if(state.mode==='business')mountBusinessDataWorkspace(scope,state,url=>location.assign(url),halt);", b"")
    assert (HERE / "analytics-shell.js").read_bytes() == expected


def check_page(role):
    state = {"reads": 0, "denied": False}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.add_init_script(f"window.mockRole = {json.dumps(role)}")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request):
            path = urlparse(request.request.url).path
            if path == "/dashboard/data-tools/":
                return request.fulfill(body=(HERE / "index.html").read_bytes(), content_type="text/html")
            if path == "/dashboard/data-tools/page.js":
                return request.fulfill(body=(HERE / "page.js").read_bytes(), content_type="text/javascript")
            if path == "/dashboard/data-tools/page.css":
                return request.fulfill(body=(HERE / "page.css").read_bytes(), content_type="text/css")
            if path.endswith("/runtime.js"):
                code = ("export async function sessionIdentity(){return {name:'test',groups:['dashboard'],role:window.mockRole}}\n"
                        "export async function protectedRead(url,options,deny){const r=await fetch(url,options);if(r.status===403){deny(403);const e=Error('denied');e.status=403;throw e}return r}\n")
                return request.fulfill(body=code, content_type="text/javascript")
            if path == "/__hub/hubnav.js":
                return request.fulfill(body="", content_type="text/javascript")
            if path.endswith("/data-workspace.js"):
                return request.fulfill(body=(FRONTEND / "data-workspace.js").read_bytes(), content_type="text/javascript")
            if path.endswith("/fs-theme.js"):
                return request.fulfill(body=(UI / "adapters/fs-theme.js").read_bytes(), content_type="text/javascript")
            styles = {"fs-tokens.css": "tokens/fs-tokens.css", "fs-ui.css": "components/fs-ui.css",
                      "native-alias.css": "adapters/native-alias.css", "business.css": "modules/native/business.css",
                      "workspace.css": "modules/native/workspace.css"}
            if path.rsplit("/", 1)[-1] in styles:
                return request.fulfill(body=(UI / styles[path.rsplit("/", 1)[-1]]).read_bytes(), content_type="text/css")
            if path.endswith(".css"):
                return request.fulfill(body="", content_type="text/css")
            if path == "/dashboard/fs-home/advisor.json":
                state["reads"] += 1
                if state["denied"]:
                    return request.fulfill(status=403, body='{"error":"forbidden"}', content_type="application/json")
                return request.fulfill(body=json.dumps({"status": "available", "evidence_id": "query_test_123",
                                                       "totals": {"distinct_orders": 0, "order_amount_usd": "0"}, "products": []}),
                                       content_type="application/json")
            return request.fulfill(status=404, body="missing")

        page.route("http://localhost/**", route)
        page.goto("http://localhost/dashboard/data-tools/")
        assert page.locator('script[src^="/__hub/hubnav.js"]').count() == 1
        page.get_by_role("heading", name="单品跟踪").wait_for()
        assert state["reads"] == 0
        assert page.get_by_role("heading", name="优惠摘要").is_visible()
        assert page.get_by_role("heading", name="新客复购追踪").is_visible()
        product = page.locator("article").first
        product.locator("[name=model_id]").fill("123")
        product.get_by_role("button", name="查询", exact=True).click()
        product.get_by_text("去重关联订单 0 单", exact=False).wait_for()
        assert state["reads"] == 1
        assert product.get_by_role("button", name="交给 Hermes 提炼一句结论").is_enabled() == (role == "admin")
        page.locator("#theme").select_option("dark")
        assert page.evaluate("document.documentElement.dataset.fsTheme") == "dark"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        screenshot = WORKSPACE / ".agent_runtime/hermes-data-workspace-20261018/tools-page-dark-mobile.png"
        if role == "admin" and screenshot.parent.is_dir():
            page.screenshot(path=str(screenshot), full_page=True)
        if role == "admin":
            page.evaluate("window.mockRole='member';document.dispatchEvent(new Event('visibilitychange'))")
        else:
            state["denied"] = True
            product.get_by_role("button", name="查询", exact=True).click()
        page.get_by_text("当前账号未获此工具页授权。", exact=True).wait_for()
        assert page.locator("#workspace-host").is_hidden()
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    check_shell()
    check_page("admin")
    check_page("member")
    print("separate data tools page: pass")
