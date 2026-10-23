"""FC27 browser writer with preview, source, before-value and readback guards."""
from __future__ import annotations
from isolated_backend import open_backend, close_backend

import sys as _order_sys
from pathlib import Path as _OrderPath
for _order_root in ('/opt/fs-order-session', '/opt/fc27-collector', '/opt/madden-workbench', '/srv'):
    if _OrderPath(_order_root, 'fs_order_client.py').is_file():
        _order_sys.path.insert(0, _order_root)
        break
import fs_order_client as _global_order

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

from playwright.sync_api import sync_playwright
from automation_policy import load_policy, check_write, hooks_before_write
from coin_all_sync_job import mirror_confirmed


ROOT = Path("/run/fc27")
PRICE_URL = "https://order.p2pah.cn/game/admin_game_price/index.html?gid=1322"
PLATFORMS = ("PS", "XBOX", "PC")


def parse_uuid(value):
    if str(uuid.UUID(value)) != value:
        raise ValueError("invalid_id")
    return value


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp_without_timezone")
    return result


def fresh(value, seconds):
    age = (datetime.now(timezone.utc) - utc(value)).total_seconds()
    return 0 <= age <= seconds


def same_money(left, right):
    return Decimal(str(left)) == Decimal(str(right))


def save_audit(record):
    path = ROOT / "executions" / f"{record['execution_id']}.json"
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def stage(record, name, **fields):
    record.update(fields)
    record["stage"] = name
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_audit(record)


def load_authorized(preview_id):
    preview = read_json(ROOT / "previews" / f"{preview_id}.json")
    if preview.get("preview_id") != preview_id or preview.get("status") != "review_only":
        raise ValueError("preview_invalid")
    if not fresh(preview["created_at"], 900) or datetime.now(timezone.utc) >= utc(preview["expires_at"]):
        raise ValueError("preview_expired")
    run_id = parse_uuid(preview["run_id"])
    quote_path = ROOT / "quotes" / f"{run_id}.json"
    quote = read_json(quote_path)
    if hashlib.sha256(quote_path.read_bytes()).hexdigest() != preview.get("quote_sha256"):
        raise ValueError("quote_changed_since_preview")
    run_path = ROOT / "runs" / f"{run_id}.json"
    run = read_json(run_path)
    if quote.get("run_id") != run_id or run.get("run_id") != run_id:
        raise ValueError("run_mismatch")
    if run.get("status") != "ready_for_quote" or quote.get("status") not in {
            "ready_for_preview", "margin_review_required"}:
        raise ValueError("source_incomplete")
    if not fresh(run["created_at"], 3600) or not fresh(quote["created_at"], 3600):
        raise ValueError("source_stale")
    if hashlib.sha256(run_path.read_bytes()).hexdigest() != quote["snapshot_sha256"]:
        raise ValueError("snapshot_hash_changed")
    if quote["snapshot_sha256"] != preview["snapshot_sha256"]:
        raise ValueError("preview_snapshot_mismatch")
    if quote["quote_engine_sha256"] != preview["quote_engine_sha256"]:
        raise ValueError("quote_engine_mismatch")
    current_engine = Path(__file__).with_name("fc27_quote_engine.py")
    if hashlib.sha256(current_engine.read_bytes()).hexdigest() != quote["quote_engine_sha256"]:
        raise ValueError("quote_engine_changed_since_preview")
    newest = max((p for p in (ROOT / "runs").glob("*.json")), key=lambda p: p.stat().st_mtime)
    if newest != run_path:
        raise ValueError("newer_run_exists")
    return preview, quote


def current_cycle_quote(preview_id, selected, revision):
    _, quote = load_authorized(preview_id)
    policy = load_policy()
    if policy.get('revision') != revision:
        raise ValueError('automation_policy_changed')
    check_write(policy, quote, selected, automatic=True)
    return quote


def inject(page):
    if not page.evaluate("!!globalThis.FC27RepricingLogic && !!globalThis.FC27RepricingDOM"):
        page.add_script_tag(path="/opt/repricing_logic.js")
        page.add_script_tag(path="/opt/repricing_dom.js")


def read_backend(page, targets, prepare=False):
    for _ in range(30):
        try:
            inject(page)
            snapshot = page.evaluate("async () => await FC27RepricingDOM.readAdminSnapshot()")
            if not snapshot or not snapshot.get("isRoute") or snapshot.get("login"):
                raise ValueError("backend_login_or_route_invalid")
            needs_prep = (snapshot.get("gameId") != "1322" or len(snapshot.get("rows") or []) != 3
                          or snapshot.get("allServerChecked") or snapshot.get("selectedWebsites") != 0
                          or not snapshot.get("b2cSelected"))
            if needs_prep and prepare:
                page.evaluate("async () => FC27RepricingDOM.prepareAdminFilter()")
                page.wait_for_timeout(350)
                continue
            page.evaluate("({snapshot,targets}) => FC27RepricingLogic.validateBackendSnapshot(snapshot,targets)",
                          {"snapshot": snapshot, "targets": targets})
            return snapshot
        except ValueError:
            raise
        except Exception:
            page.wait_for_timeout(400)
    raise ValueError("backend_validation_failed")


def same_backend(page, left, right):
    return page.evaluate("({left,right}) => FC27RepricingLogic.sameBackendSnapshot(left,right,['PS','XBOX','PC'])",
                         {"left": left, "right": right})


def revalidate_evidence(page, quote, preview):
    if not fresh(quote["evidence"]["checked_at"], 3600):
        raise ValueError("evidence_expired")
    from pricing_v2 import verify_quote
    verify_quote(quote,load_policy(),list(PLATFORMS),for_execution=True)
    computed = page.evaluate("payload => FC27RepricingLogic.buildPreview(payload,Date.now())",
                             {"evidence": quote["evidence"], "edits": quote.get("edits") or {}, "result": quote["result"]})
    expected = preview["targets"]
    if [x["platform"] for x in computed["targets"]] != list(PLATFORMS):
        raise ValueError("computed_platform_mismatch")
    for new, old in zip(computed["targets"], expected):
        for key in ("platform", "id", "quote", "targetCost", "sourceCost", "effectiveCost"):
            if new[key] != old[key]:
                raise ValueError("preview_evidence_changed")


def expected_state(snapshot, preview, changed):
    before = {row["platform"]: row for row in preview["backend_before"]["rows"]}
    targets = {row["platform"]: row for row in preview["targets"]}
    for row in snapshot["rows"]:
        platform = row["platform"]
        target = targets[platform]
        old = before[platform]
        expected_cost = target["targetCost"] if platform in changed else old["costPrice"]
        if not same_money(row["costPrice"], expected_cost):
            raise ValueError("before_cost_changed:" + platform)
        allowed_b2c = (old["b2c"], target["quote"]) if platform in changed else (old["b2c"],)
        if not any(same_money(row["b2c"], value) for value in allowed_b2c):
            raise ValueError("before_b2c_changed:" + platform)


def mirror_after_order_confirmation(record):
    """A failed ALL login before any dispatch cannot undo confirmed Order prices."""
    policy = load_policy()
    try:
        return mirror_confirmed(record, policy, save_audit, ROOT, load_policy,
                                current_quote=lambda: current_cycle_quote(record['preview_id'], record['selected'],
                                                                          record['automation_policy_revision']))
    except ValueError as error:
        if (str(error) != 'coin_auth_unavailable'
                or (ROOT / 'all-coin-sync' / (record['execution_id'] + '.json')).exists()
                or record.get('sync_confirmed') is not True
                or policy != load_policy()):
            raise
        # Other ALL failures, including any created ledger, retain UNKNOWN protection.
        rows = record.get('after', {}).get('rows', [])
        if len(rows) != 3 or {r.get('platform') for r in rows} != set(PLATFORMS):
            raise ValueError('coin_order_confirmation_incomplete')
        result = {'status':'deferred_before_dispatch','reason':'coin_auth_unavailable',
                  'execution_id':record['execution_id'],'price_post_attempted':False,
                  'success_scope':'order_b2c_and_public_price'}
        record['all_baseline'] = result
        stage(record, 'all_auth_deferred', status='PARTIAL')
        return result


def confirm_sync_recipient(record):
    """A lost DOM receipt may be reconciled by two stable recipient GETs, never replayed."""
    import time
    from p2pah_session_service import SessionManager, read_private_config, allowed_admin_usernames
    from coin_all_sync_job import api, read_row, PRODUCTS
    manager = SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError('sync_recipient_session_unavailable')
    identity = api(manager, '/admin/index/index')
    if not isinstance(identity, dict) or identity.get('adminInfo', {}).get('username') not in allowed_admin_usernames():
        raise ValueError('sync_recipient_identity_invalid')
    previous = None
    rounds = []
    for attempt in range(2):
        current_cycle_quote(record['preview_id'], record['selected'], record['automation_policy_revision'])
        rows = {p: read_row(manager, p, 266) for p in PRODUCTS}
        if any(not same_money(rows[t['platform']]['unit_price'], t['quote']) for t in record['targets']):
            raise ValueError('sync_recipient_price_unconfirmed')
        current = {p: {'unit_price': str(r['unit_price']), 'tier_prices': r['more']['price']} for p, r in rows.items()}
        if previous is not None and current != previous:
            raise ValueError('sync_recipient_unstable')
        rounds.append(current)
        previous = current
        if attempt == 0:
            time.sleep(1)
    return {'basis': 'two_stable_original_admin_recipient_reads', 'rounds': rounds,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'sync_replayed': False}


def execute(preview_id, execution_id, actor, selected, margin_confirmed=None, check_only=False,
            margin_reason="", policy_revision=None, automatic=False):
    preview_id = parse_uuid(preview_id)
    execution_id = parse_uuid(execution_id)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", actor):
        raise ValueError("actor_invalid")
    if not selected or len(selected) != len(set(selected)) or any(x not in PLATFORMS for x in selected):
        raise ValueError("platform_selection_invalid")
    preview, quote = load_authorized(preview_id)
    low_margin = []
    if not check_only:
        policy = load_policy()
        if policy_revision != policy["revision"]:
            raise ValueError("automation_policy_changed")
        low_margin = check_write(policy, quote, selected, automatic=automatic,
                                 confirmed=margin_confirmed or [], reason=margin_reason)
    if not check_only:
        for path in (ROOT / "executions").glob("*.json"):
            state = read_json(path)
            if state.get("status") in {"RUNNING", "UNCERTAIN", "PARTIAL"}:
                raise ValueError("unresolved_execution_exists")
    if not check_only:
        hooks_before_write(load_policy(), selected, automatic,
                           current_quote=lambda: current_cycle_quote(preview_id, selected, policy_revision))
    margin_confirmed = margin_confirmed or []
    record = {"execution_id": execution_id, "preview_id": preview_id,
              "run_id": preview["run_id"], "actor": actor, "selected": selected,
              "status": "CHECK_ONLY" if check_only else "RUNNING", "stage": "preflight",
               "automatic": automatic, "automation_policy_revision": policy_revision,
               "margin_confirmed_platforms": margin_confirmed,
               "low_margin_platforms": low_margin,
               "margin_exception_reason": str(margin_reason).strip()[:200] if low_margin else "",
               "operator_reason": str(margin_reason).strip()[:200],
              "changed": [], "sync_confirmed": False,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "before": preview["backend_before"], "targets": preview["targets"]}
    record['pricing_decision_receipt']=quote['result']['decision_receipt']
    record['hermes_decision']=quote.get('hermes_decision')
    record['pricing_basis']={'evidence':quote['evidence'],'edits':quote.get('edits') or {},'result':quote['result']}
    with sync_playwright() as playwright:
        browser = open_backend(playwright)
        if len(browser.contexts) != 1:
            raise ValueError("browser_context_ambiguous")
        _global_order.apply(browser.contexts[0])
        page = browser.contexts[0].new_page()
        try:
            page.goto(PRICE_URL, wait_until="domcontentloaded", timeout=35000)
            snapshot = read_backend(page, preview["targets"], prepare=True)
            if not same_backend(page, preview["backend_before"], snapshot):
                raise ValueError("backend_before_changed")
            revalidate_evidence(page, quote, preview)
            if check_only:
                return {"status": "CHECK_ONLY", "preview_id": preview_id,
                        "platforms": selected, "backend_same": True}
            # One server collection run may produce multiple previews, but may write only once.
            marker = ROOT / "executions" / f"run-{preview['run_id']}.used"
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
            os.close(fd)
            stage(record, "started")
            targets = {row["platform"]: row for row in preview["targets"]}
            before = {row["platform"]: row for row in preview["backend_before"]["rows"]}
            for platform in selected:
                revalidate_evidence(page, quote, preview)
                current = read_backend(page, preview["targets"])
                expected_state(current, preview, record["changed"])
                old = before[platform]
                target = targets[platform]
                row_before = next(row for row in current["rows"] if row["platform"] == platform)
                if not same_money(row_before["costPrice"], old["costPrice"]):
                    raise ValueError("platform_cost_changed:" + platform)
                hooks_before_write(load_policy(), [platform], automatic,
                                   current_quote=lambda: current_cycle_quote(preview_id, selected, policy_revision))
                stage(record, "saving_" + platform)
                page.evaluate("args => FC27RepricingDOM.setCost(...args)",
                              [platform, target["id"], old["costPrice"],
                               target["targetCost"], old["b2c"]])
                current = read_backend(page, preview["targets"])
                if not same_money(next(row for row in current["rows"] if row["platform"] == platform)["costPrice"], target["targetCost"]):
                    raise ValueError("save_readback_mismatch:" + platform)
                record["changed"].append(platform)
                stage(record, "saved_" + platform)
            revalidate_evidence(page, quote, preview)
            current = read_backend(page, preview["targets"])
            expected_state(current, preview, record["changed"])
            hooks_before_write(load_policy(), selected, automatic,
                               current_quote=lambda: current_cycle_quote(preview_id, selected, policy_revision))
            stage(record, "syncing")
            try:
                feedback = page.evaluate("async () => FC27RepricingDOM.clickSync('mmoexp.com')")
                if not feedback or not feedback.get("success") or not feedback.get("message"):
                    raise ValueError("sync_feedback_unconfirmed")
            except Exception as exc:
                stage(record, 'sync_recipient_check', sync_feedback_error=type(exc).__name__)
                receipt = confirm_sync_recipient(record)
                stage(record, 'sync_recipient_confirmed', sync_confirmed=True,
                      sync_recipient_readback=receipt)
            else:
                stage(record, "sync_feedback", sync_confirmed=True,
                      sync_message=str(feedback["message"])[:120])
            page.reload(wait_until="domcontentloaded", timeout=35000)
            after = read_backend(page, preview["targets"], prepare=True)
            for platform in PLATFORMS:
                actual = next(row for row in after["rows"] if row["platform"] == platform)
                old, target = before[platform], targets[platform]
                cost_expected = target["targetCost"] if platform in selected else old["costPrice"]
                b2c_expected = target["quote"] if platform in selected else old["b2c"]
                if not same_money(actual["costPrice"], cost_expected) or not same_money(actual["b2c"], b2c_expected):
                    raise ValueError("post_sync_readback_mismatch:" + platform)
            stage(record, "all_baseline_pending", status="PARTIAL", after=after)
            baseline = mirror_after_order_confirmation(record)
            if baseline.get("status") not in {"confirmed", "deferred_before_dispatch"}:
                raise ValueError("coin_all_sync_unconfirmed")
            stage(record, "readback_confirmed", status="CONFIRMED", after=after)
            return {"status": "CONFIRMED", "execution_id": execution_id,
                    "platforms": selected, "sync_confirmed": True}
        except Exception as exc:
            if not check_only and (ROOT / "executions" / f"{execution_id}.json").exists():
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                attempted_stage = record["stage"]
                uncertain = attempted_stage in {"syncing", "sync_feedback", "sync_recipient_check", "sync_recipient_confirmed"}
                try:
                    observed = read_backend(page, preview["targets"])
                    for target in preview["targets"]:
                        platform = target["platform"]
                        row = next(x for x in observed["rows"] if x["platform"] == platform)
                        if platform in selected and same_money(row["costPrice"], target["targetCost"]) and platform not in record["changed"]:
                            record["changed"].append(platform)
                except Exception:
                    uncertain = True
                status = "UNCERTAIN" if uncertain else "PARTIAL" if record["changed"] else "FAILED_BEFORE_WRITE"
                stage(record, "stopped", status=status, error=reason[:100])
            raise
        finally:
            close_backend(page)


if __name__ == "__main__":
    try:
        request = json.loads(Path("/run/request.json").read_text(encoding="utf-8"))
        result = execute(request["preview_id"], request["execution_id"], request["actor"],
                         request["platforms"], request.get("margin_confirmed_platforms") or [],
                          request.get("check_only") is True,
                          request.get("margin_exception_reason", ""),
                          request.get("policy_revision"), request.get("automatic") is True)
        print(json.dumps(result))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "FAILED", "reason": reason[:100]}))
        raise SystemExit(1)
