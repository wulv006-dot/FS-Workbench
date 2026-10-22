"""Read and validate P2PAH price rows without saving or syncing."""
from __future__ import annotations

import sys as _order_sys
from pathlib import Path as _OrderPath
for _order_root in ('/opt/fs-order-session', '/opt/fc27-collector', '/opt/madden-workbench', '/srv'):
    if _OrderPath(_order_root, 'fs_order_client.py').is_file():
        _order_sys.path.insert(0, _order_root)
        break
import fs_order_client as _global_order

from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import sys
import uuid

from playwright.sync_api import sync_playwright


PRICE_URL = "https://order.p2pah.cn/game/admin_game_price/index.html?gid=1322"


def failure_reason(exc):
    if isinstance(exc, RuntimeError) and str(exc).startswith('global_order_unavailable:'):
        # Keep the actionable category without exposing the session broker's details.
        return 'global_order_session_unavailable'
    return str(exc)[:100] if isinstance(exc, ValueError) else type(exc).__name__


def preview(run_id: str):
    quote_file = Path("/run/quotes") / f"{run_id}.json"
    quote_bytes = quote_file.read_bytes()
    quote = json.loads(quote_bytes)
    if quote.get("run_id") != run_id or quote.get("status") not in {
            "ready_for_preview", "margin_review_required"}:
        raise ValueError("quote_not_ready")
    created = datetime.fromisoformat(quote["created_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if created.tzinfo is None or not 0 <= (now - created).total_seconds() <= 3600:
        raise ValueError("quote_stale")
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ.get("FC27_CDP_ENDPOINT", "http://127.0.0.1:9225"),
            timeout=8000, no_defaults=True)
        if len(browser.contexts) != 1:
            raise ValueError("browser_context_ambiguous")
        _global_order.apply(browser.contexts[0])
        page = browser.contexts[0].new_page()
        try:
            page.goto(PRICE_URL, wait_until="domcontentloaded", timeout=35000)
            page.add_script_tag(path="/opt/repricing_logic.js")
            page.add_script_tag(path="/opt/repricing_dom.js")
            data = None
            last_reason = "backend_not_ready"
            for _ in range(35):
                try:
                    if not page.evaluate("!!globalThis.FC27RepricingLogic && !!globalThis.FC27RepricingDOM"):
                        page.add_script_tag(path="/opt/repricing_logic.js")
                        page.add_script_tag(path="/opt/repricing_dom.js")
                    data = page.evaluate("""async payload => {
                      const logic=globalThis.FC27RepricingLogic;
                      const dom=globalThis.FC27RepricingDOM;
                      const quote=logic.buildPreview(payload,Date.now());
                      const state=await dom.readAdminSnapshot();
                      if(!state?.isRoute || state.login) throw new Error('backend_login_or_route_invalid');
                      if(state.gameId!=='1322'||state.rows.length!==3||state.allServerChecked||
                         state.selectedWebsites!==0||!state.b2cSelected) {
                        await dom.prepareAdminFilter();
                        return {pending:true};
                      }
                      logic.validateBackendSnapshot(state,quote.targets);
                      return {pending:false,backend:state,quote};
                    }""", {"evidence": quote["evidence"], "edits": quote.get("edits") or {}, "result": quote["result"]})
                    if data and not data.get("pending"):
                        break
                except Exception as exc:
                    last_reason = str(exc).splitlines()[0][:100]
                    if "backend_login_or_route_invalid" in last_reason:
                        raise ValueError("backend_login_expired") from None
                page.wait_for_timeout(500)
            if not data or data.get("pending"):
                raise ValueError("backend_validation_failed:" + last_reason)
            expected = {row["platform"]: row["proposal"] for row in quote["result"]["rows"]}
            targets = data["quote"]["targets"]
            if [x["platform"] for x in targets] != ["PS", "XBOX", "PC"]:
                raise ValueError("platform_order_invalid")
            if any(x["quote"] != expected[x["platform"]] for x in targets):
                raise ValueError("python_js_quote_mismatch")
            preview_id = str(uuid.uuid4())
            return {"preview_id": preview_id, "run_id": run_id,
                    "automation_policy_revision": quote['automation_policy_revision'],
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(minutes=15)).isoformat(),
                    "status": "review_only", "quote_status": quote["status"],
                    "snapshot_sha256": quote["snapshot_sha256"],
                    "quote_sha256": hashlib.sha256(quote_bytes).hexdigest(),
                    "quote_engine_sha256": quote["quote_engine_sha256"],
                    "backend_before": data["backend"], "targets": targets}
        finally:
            page.close()


if __name__ == "__main__":
    try:
        print(json.dumps(preview(sys.argv[1])))
    except Exception as exc:
        reason = failure_reason(exc)
        print(json.dumps({"status": "NO_PREVIEW", "reason": reason[:100]}))
        raise SystemExit(1)
