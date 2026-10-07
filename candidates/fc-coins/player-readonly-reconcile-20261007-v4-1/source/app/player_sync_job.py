"""Run one FC27 Players repricing job with the server-owned chenchao identity.

This module runs in an isolated fc27-cloud-session container. A dispatch intent is
durably recorded before every POST; an interrupted or uncertain request is never
replayed automatically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
from random import SystemRandom
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

sys.path.insert(0, "/usr/local/bin")
from p2pah_session_service import HEADERS, SessionManager, read_private_config


ROOT = Path("/run/player-sync")
REQUEST = Path("/run/request.json")
EXECUTION = Path("/run/coin-execution.json")
POLICY = Path("/run/config/player-sync.json")
GID, CID, MMOEXP_SITE = 1327, 9627, 266
TOLERANCE = Decimal("0.001")
PUBLIC_PAGE = "https://www.mmoexp.com/Fc-27/Players.html"
PUBLIC_API = "https://www.mmoexp.com/ajax/goods"
PUBLIC_AREAS = {"PS": 21587, "XBOX": 21585, "PC": 21589}


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def decimal(value, label, *, positive=True):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(label + "_invalid") from None
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(label + "_invalid")
    return result


def atomic(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".player-sync-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def query_pairs(filters, **simple):
    value = dict(simple)
    for index, (field, expected) in enumerate(filters):
        prefix = f"search[{index}]"
        value[prefix + "[field]"] = field
        value[prefix + "[operator]"] = "="
        value[prefix + "[val]"] = str(expected)
    return urlencode(value)


def api(manager, path, *, payload=None):
    for attempt in range(3 if payload is None else 1):
        try:
            status, raw = manager.request(path, data=payload, token=manager.token)
            break
        except OSError:
            if payload is not None or attempt == 2:
                raise
            time.sleep(attempt + 1)
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("backend_response_invalid") from None
    if status != 200 or result.get("code") != 1:
        raise ValueError("backend_request_rejected")
    return result.get("data")


def recalculate_category(manager):
    """Submit the admin page's category action once with a bulk sized timeout."""
    headers = {**HEADERS, "Content-Type": "application/json", "batoken": manager.token}
    body = json.dumps({"gid": GID, "cid": CID, "id": []}).encode("utf-8")
    request = urllib.request.Request(
        manager.config["P2PAH_API_BASE"] + "/admin/goods.GoodsMould/recalcFc27Price",
        data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("backend_response_invalid") from None
    if status != 200 or result.get("code") != 1:
        raise ValueError("backend_request_rejected")
    return result.get("data")


def list_models(manager):
    rows, expected_total = [], None
    for page in range(1, 101):
        data = api(manager, "/admin/goods.GoodsMould/index?" + query_pairs(
            [("gid", GID), ("cid", CID)], page=page, limit=200, order="sort,desc"))
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise ValueError("model_list_invalid")
        total = int(data.get("total", -1))
        if total < 1 or total > 10000 or (expected_total is not None and total != expected_total):
            raise ValueError("model_list_total_changed")
        expected_total = total
        page_rows = data["list"]
        if not page_rows or len(page_rows) > 200:
            raise ValueError("model_list_incomplete")
        rows.extend(page_rows)
        if len(rows) >= total:
            break
    if len(rows) != expected_total:
        raise ValueError("model_list_incomplete")
    ids = [int(row["id"]) for row in rows]
    if len(set(ids)) != len(ids) or any(str(row.get("gid")) != str(GID)
                                    or str(row.get("cid")) != str(CID) for row in rows):
        raise ValueError("model_list_scope_invalid")
    return rows


def products(manager, model_id):
    rows, expected_total = [], None
    for page in range(1, 21):
        data = api(manager, "/admin/goods.Goods/index?" + query_pairs(
            [("gid", GID), ("cid", CID), ("mid", model_id)], page=page, limit=200))
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise ValueError("product_list_invalid")
        total = int(data.get("total", -1))
        if total < 0 or total > 4000 or (expected_total is not None and total != expected_total):
            raise ValueError("product_list_total_changed")
        expected_total = total
        rows.extend(data["list"])
        if len(rows) >= total:
            break
        if not data["list"]:
            raise ValueError("product_list_incomplete")
    if len(rows) != expected_total:
        raise ValueError("product_list_incomplete")
    ids = [int(row["id"]) for row in rows]
    if len(set(ids)) != len(ids) or any(str(row.get("gid")) != str(GID)
                                    or str(row.get("cid")) != str(CID)
                                    or int(row.get("mid") or 0) != model_id for row in rows):
        raise ValueError("product_list_scope_invalid")
    if any(str(row.get("site_id")) not in {"0", str(MMOEXP_SITE)} for row in rows):
        raise ValueError("product_site_scope_unknown")
    return rows


def area(row):
    item = row.get("gameArea")
    name = str(item.get("title") if isinstance(item, dict) else "").lower()
    if "xbox" in name:
        return "XBOX"
    if "playstation" in name or name.startswith("ps"):
        return "PS"
    if "pc" in name:
        return "PC"
    raise ValueError("player_product_platform_unknown")


def model_inputs(row):
    more = row.get("more")
    if not isinstance(more, dict) or not isinstance(more.get("extend"), list):
        raise ValueError("model_price_inputs_missing")
    values = {str(item.get("key")): item.get("value") for item in more["extend"]
              if isinstance(item, dict)}
    return {"PS": decimal(values.get("ps_price"), "player_ps_coins"),
            "XBOX": decimal(values.get("ps_price"), "player_xbox_coins"),
            "PC": decimal(values.get("pc_price"), "player_pc_coins"),
            "coefficient": decimal(values.get("coefficient") or "1.1", "player_coefficient")}


def formula_ok(rows, inputs, rates):
    selling = [row for row in rows if active(row)]
    if not selling:
        return False
    for row in selling:
        platform = area(row)
        expected = inputs[platform] / Decimal(1000) * rates[platform] * inputs["coefficient"]
        actual = decimal(row.get("unit_price"), "player_unit_price")
        if abs(actual - expected) > TOLERANCE:
            return False
    return True


def active(row):
    return (str(row.get("site_id")) == str(MMOEXP_SITE)
            and str(row.get("status")) == "1"
            and int(row.get("total") or 0) > 0)


def recovery_start(ledger, *, job_id, coin_id, count, digest):
    """Only continue the same immutable plan after an operator reconciles its stop."""
    if (ledger.get("job_id") != job_id or ledger.get("coin_execution_id") != coin_id
            or ledger.get("status") != "needs_reconcile"
            or ledger.get("model_count") != count or ledger.get("model_ids_sha256") != digest
            or type(ledger.get("verified_count")) is not int
            or type(ledger.get("next_index")) is not int
            or ledger["verified_count"] != ledger["next_index"]
            or not 0 <= ledger["verified_count"] < count):
        raise ValueError("player_sync_recovery_state_invalid")
    return ledger["verified_count"]


def category_samples(manager, models, size=5):
    """Choose a uniform random sample from active models with MMOEXP stock."""
    candidates = [row for row in models if str(row.get("status")) == "1"]
    SystemRandom().shuffle(candidates)
    selected = []
    for row in candidates:
        model_id = int(row["id"])
        linked = products(manager, model_id)
        selling = [item for item in linked if active(item)]
        if len(selling) != 3 or {area(item) for item in selling} != set(PUBLIC_AREAS):
            continue
        for item in linked:
            area(item)
        selected.append({"id": model_id,
                         "product_ids": sorted(int(item["id"]) for item in linked),
                         "title": str(row.get("title") or "").split("/", 1)[0].strip()})
        if len(selected) == size:
            if any(not item["title"] for item in selected):
                raise ValueError("player_sample_title_missing")
            return selected
    raise ValueError("player_sample_incomplete")


def public_offer(product_id, model_id, platform, player_name):
    """Read the public card feed that renders Our Price; match by exact product ID."""
    if platform not in PUBLIC_AREAS or not player_name or not 0 < len(player_name) < 150:
        raise ValueError("public_player_query_invalid")
    form = {"orderBy": "", "prop_ids": "", "site_id": MMOEXP_SITE,
            "Game_id": GID, "page": 1, "top_cid": 2, "category_id": "",
            "cid": CID, "aid": PUBLIC_AREAS[platform], "keyword": player_name,
            "tid": "", "perpage": 12, "is_search_category": 1}
    expected_total = None
    for page in range(1, 51):
        form["page"] = page
        command = ["curl", "--fail", "--silent", "--show-error", "--location",
                   "--max-time", "18", "--max-filesize", "4000000",
                   "--proto", "=https", "--proto-redir", "=https",
                   "--user-agent", "Mozilla/5.0 (compatible; FC27-player-monitor/1.0)",
                   "--referer", PUBLIC_PAGE, "--header", "Accept: application/json",
                   "--header", "Content-Type: application/x-www-form-urlencoded",
                   "--header", "Cache-Control: no-cache", "--header", "Pragma: no-cache",
                   "--data", urlencode(form), PUBLIC_API]
        try:
            response = subprocess.run(command, capture_output=True, timeout=22)
            if response.returncode or not response.stdout or len(response.stdout) > 4000000:
                raise ValueError("public_player_source_unavailable")
            payload = json.loads(response.stdout)
            listing = payload["goods"]["index"]
            rows = listing["list"]
            total = int(listing["total"])
            if (not isinstance(rows, list) or total < 1 or total > 600
                    or expected_total is not None and total != expected_total
                    or not 0 < len(rows) <= 12):
                raise ValueError("public_player_listing_invalid")
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            raise ValueError("public_player_source_unavailable") from None
        expected_total = total
        matches = [row for row in rows if int(row.get("id") or 0) == product_id]
        if len(matches) > 1:
            raise ValueError("public_player_product_ambiguous")
        if matches:
            row = matches[0]
            if (int(row.get("mid") or 0) != model_id
                    or int(row.get("gid") or 0) != GID
                    or int(row.get("cid") or 0) != CID
                    or int(row.get("site_id") or 0) != MMOEXP_SITE
                    or int(row.get("aid") or 0) != PUBLIC_AREAS[platform]
                    or str(row.get("status")) != "1"
                    or int(row.get("total") or 0) <= 0):
                raise ValueError("public_player_product_mismatch")
            meta = row.get("more_extend_fromat")
            if not isinstance(meta, dict):
                raise ValueError("public_player_coins_missing")
            coin_field = "pc_price" if platform == "PC" else "ps_price"
            return {"product_id": product_id, "model_id": model_id,
                    "platform": platform, "our_price_coins": decimal(meta.get(coin_field),
                                                                         "public_player_coins"),
                    "coefficient": decimal(meta.get("coefficient") or "1.1",
                                           "public_player_coefficient"),
                    "usd": decimal(row.get("unit_price"), "public_player_usd"),
                    "checked_at": now()}
        if page * 12 >= total:
            break
    raise ValueError("public_player_product_missing")


def public_formula_status(sample, linked, rates):
    """Check both backend and public dollars against the public Our Price coins."""
    details = []
    for product in linked:
        if not active(product):
            continue
        platform = area(product)
        offer = public_offer(int(product["id"]), sample["id"], platform, sample["title"])
        expected = offer["our_price_coins"] / Decimal(1000) * rates[platform] * offer["coefficient"]
        backend = decimal(product.get("unit_price"), "player_unit_price")
        details.append({"platform": platform, "product_id": offer["product_id"],
                        "our_price_coins": str(offer["our_price_coins"]),
                        "coefficient": str(offer["coefficient"]),
                        "target_usd": str(expected), "backend_usd": str(backend),
                        "public_usd": str(offer["usd"]), "checked_at": offer["checked_at"],
                        "backend_match": abs(backend - expected) <= TOLERANCE,
                        "public_match": abs(offer["usd"] - expected) <= TOLERANCE})
    if len(details) != 3 or {row["platform"] for row in details} != set(PUBLIC_AREAS):
        raise ValueError("player_sample_platforms_incomplete")
    return details


def bulk_main():
    """Match the admin page's unselected 'all in category' action, then audit five."""
    request, execution, policy = read(REQUEST), read(EXECUTION), read(POLICY)
    job_id, coin_id = request["job_id"], request["coin_execution_id"]
    dry_run = request.get("dry_run") is True
    if ((not policy.get("enabled") and not dry_run)
            or policy.get("revision") != request.get("config_revision")
            or execution.get("execution_id") != coin_id
            or execution.get("status") != "CONFIRMED" or execution.get("automatic") is not True):
        raise ValueError("player_sync_preflight_changed")
    rate_rows = execution.get("after", {}).get("rows") or []
    rates = {row["platform"]: decimal(row.get("b2c"), "coin_sale_price") for row in rate_rows}
    if set(rates) != {"PS", "XBOX", "PC"} or len(rate_rows) != 3:
        raise ValueError("coin_sale_prices_incomplete")
    manager = SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError("chenchao_auth_unavailable")
    identity = api(manager, "/admin/index/index")
    if not isinstance(identity, dict) or identity.get("adminInfo", {}).get("username") != "chenchao":
        raise ValueError("chenchao_identity_invalid")
    models = list_models(manager)
    samples = category_samples(manager, models)
    sample_before = {}
    for item in samples:
        sample_before[str(item["id"])] = public_formula_status(
            item, products(manager, item["id"]), rates)
    scope_digest = hashlib.sha256(json.dumps([int(row["id"]) for row in models],
                                             separators=(",", ":")).encode()).hexdigest()
    if dry_run:
        print(json.dumps({"status": "preflight_ready", "mode": "category_all",
                          "model_count": len(models), "sample_count": len(samples),
                          "sample_model_ids": [row["id"] for row in samples],
                          "model_ids_sha256": scope_digest, "coin_execution_id": coin_id}))
        return
    ledger_path = ROOT / (job_id + ".json")
    if ledger_path.exists():
        raise ValueError("player_sync_job_already_started")
    ledger = {"job_id": job_id, "coin_execution_id": coin_id,
              "created_at": now(), "status": "running", "mode": "category_all",
              "stage": "sample_selected", "model_count": len(models),
              "model_ids_sha256": scope_digest, "sample_count": len(samples),
              "sample_model_ids": [row["id"] for row in samples],
              "sample_source": "MMOEXP Players Our Price by exact product ID",
              "sample_before": sample_before, "sample_readback": {},
              "sample_verified_count": 0, "sample_verified_model_ids": [],
              "verified_count": 0,
              "active_model_id": None}
    atomic(ledger_path, ledger)
    try:
        current_policy = read(POLICY)
        if not current_policy.get("enabled") or current_policy.get("revision") != request["config_revision"]:
            raise ValueError("player_sync_switch_changed")
        ledger.update({"stage": "category_dispatch_intent", "updated_at": now()})
        atomic(ledger_path, ledger)
        # The live admin button submits an empty selection to recalculate gid/cid in one call.
        recalculate_category(manager)
        ledger.update({"stage": "sample_readback", "updated_at": now()})
        atomic(ledger_path, ledger)
        deadline = time.monotonic() + 180
        verified = set()
        while len(verified) < len(samples):
            current_policy = read(POLICY)
            if not current_policy.get("enabled") or current_policy.get("revision") != request["config_revision"]:
                raise ValueError("player_sync_switch_changed")
            for item in samples:
                model_id = item["id"]
                if model_id in verified:
                    continue
                ledger["active_model_id"] = model_id
                detail = api(manager, "/admin/goods.GoodsMould/edit?id=" + str(model_id))
                row = detail.get("row") if isinstance(detail, dict) else None
                if (not isinstance(row, dict) or int(row.get("id") or 0) != model_id
                        or str(row.get("gid")) != str(GID) or str(row.get("cid")) != str(CID)
                        or str(row.get("status")) != "1"):
                    raise ValueError("player_sample_model_changed")
                if str(row.get("title") or "").split("/", 1)[0].strip() != item["title"]:
                    raise ValueError("player_sample_title_changed")
                linked = products(manager, model_id)
                if (sorted(int(product["id"]) for product in linked) != item["product_ids"]
                        or not any(active(product) for product in linked)):
                    raise ValueError("player_sample_products_changed")
                details = public_formula_status(item, linked, rates)
                ledger["sample_readback"][str(model_id)] = details
                ledger["updated_at"] = now()
                atomic(ledger_path, ledger)
                if all(part["backend_match"] and part["public_match"] for part in details):
                    verified.add(model_id)
                    ledger.update({"sample_verified_count": len(verified),
                                   "sample_verified_model_ids": sorted(verified),
                                   "verified_count": len(verified),
                                   "last_verified_model_id": model_id,
                                   "active_model_id": None, "updated_at": now()})
                    atomic(ledger_path, ledger)
            if len(verified) == len(samples):
                break
            if time.monotonic() >= deadline:
                raise ValueError("player_sample_readback_timeout")
            time.sleep(10)
        ledger.update({"status": "confirmed", "stage": "complete", "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "confirmed", "mode": "category_all",
                          "model_count": len(models), "sample_count": len(samples),
                          "sample_verified_count": len(verified),
                          "coin_execution_id": coin_id}))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        ledger.update({"status": "needs_reconcile", "stage": "stopped",
                       "error": reason[:90], "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "needs_reconcile", "reason": reason[:90],
                          "mode": "category_all", "sample_verified_count": len(verified)
                          if "verified" in locals() else 0,
                          "active_model_id": ledger["active_model_id"]}))
        raise SystemExit(2)


def main():
    request, execution, policy = read(REQUEST), read(EXECUTION), read(POLICY)
    job_id, coin_id = request["job_id"], request["coin_execution_id"]
    dry_run = request.get("dry_run") is True
    if ((not policy.get("enabled") and not dry_run)
            or policy.get("revision") != request.get("config_revision")
            or execution.get("execution_id") != coin_id
            or execution.get("status") != "CONFIRMED" or execution.get("automatic") is not True):
        raise ValueError("player_sync_preflight_changed")
    rate_rows = execution.get("after", {}).get("rows") or []
    rates = {row["platform"]: decimal(row.get("b2c"), "coin_sale_price") for row in rate_rows}
    if set(rates) != {"PS", "XBOX", "PC"} or len(rate_rows) != 3:
        raise ValueError("coin_sale_prices_incomplete")
    manager = SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError("chenchao_auth_unavailable")
    identity = api(manager, "/admin/index/index")
    if not isinstance(identity, dict) or identity.get("adminInfo", {}).get("username") != "chenchao":
        raise ValueError("chenchao_identity_invalid")
    models = list_models(manager)
    planned = []
    for row in models:
        if str(row.get("status")) != "1":
            continue
        model_id = int(row["id"])
        linked = products(manager, model_id)
        if not any(active(item) for item in linked):
            continue
        inputs = model_inputs(row)
        for item in linked:
            area(item)
        planned.append({"id": model_id, "product_ids": sorted(int(item["id"]) for item in linked),
                        "inputs": {key: str(value) for key, value in inputs.items()}})
    if not planned:
        raise ValueError("no_active_player_models")
    ids = [item["id"] for item in planned]
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    if dry_run:
        print(json.dumps({"status": "preflight_ready", "model_count": len(planned),
                          "model_ids_sha256": digest, "coin_execution_id": coin_id}))
        return
    ledger_path = ROOT / (job_id + ".json")
    resume = request.get("resume") is True
    if ledger_path.exists():
        if not resume:
            raise ValueError("player_sync_job_already_started")
        ledger = read(ledger_path)
        start_index = recovery_start(ledger, job_id=job_id, coin_id=coin_id,
                                     count=len(planned), digest=digest)
        uncertain_model = ledger.get("active_model_id")
        if uncertain_model is not None and uncertain_model != planned[start_index]["id"]:
            raise ValueError("player_sync_recovery_model_changed")
        ledger.setdefault("recoveries", []).append({
            "at": now(), "previous_error": ledger.get("error"),
            "verified_count": start_index, "uncertain_model_id": uncertain_model})
        ledger.update({"status": "running", "stage": "rechecking_uncertain_model",
                       "error": None, "completed_at": None, "updated_at": now()})
    else:
        if resume:
            raise ValueError("player_sync_recovery_ledger_missing")
        start_index, uncertain_model = 0, None
        ledger = {"job_id": job_id, "coin_execution_id": coin_id,
                  "created_at": now(), "status": "running", "model_count": len(planned),
                  "model_ids_sha256": digest, "verified_count": 0, "next_index": 0,
                  "active_model_id": None, "last_verified_model_id": None}
    atomic(ledger_path, ledger)
    last_auth_check = time.monotonic()
    try:
        for index in range(start_index, len(planned)):
            item = planned[index]
            if time.monotonic() - last_auth_check > 300:
                if not manager.ensure():
                    raise ValueError("chenchao_auth_expired")
                last_auth_check = time.monotonic()
            current_policy = read(POLICY)
            if not current_policy.get("enabled") or current_policy.get("revision") != request["config_revision"]:
                raise ValueError("player_sync_switch_changed")
            model_id = item["id"]
            detail = api(manager, "/admin/goods.GoodsMould/edit?id=" + str(model_id))
            row = detail.get("row") if isinstance(detail, dict) else None
            if (not isinstance(row, dict) or int(row.get("id") or 0) != model_id
                    or str(row.get("gid")) != str(GID) or str(row.get("cid")) != str(CID)
                    or str(row.get("status")) != "1"):
                raise ValueError("player_model_changed")
            inputs = {key: decimal(value, key) for key, value in item["inputs"].items()}
            if model_inputs(row) != inputs:
                raise ValueError("player_formula_inputs_changed")
            before = products(manager, model_id)
            if sorted(int(row["id"]) for row in before) != item["product_ids"] or not any(active(row) for row in before):
                raise ValueError("player_products_changed")
            if resume and index == start_index and uncertain_model == model_id:
                matched = formula_ok(before, inputs, rates)
                ledger["recoveries"][-1]["readback_before_retry_matches"] = matched
                atomic(ledger_path, ledger)
                if matched:
                    ledger.update({"verified_count": index + 1, "next_index": index + 1,
                                   "active_model_id": None, "last_verified_model_id": model_id,
                                   "stage": "verified_after_uncertain_write", "updated_at": now()})
                    atomic(ledger_path, ledger)
                    continue
            ledger.update({"next_index": index, "active_model_id": model_id,
                           "stage": "dispatch_intent", "updated_at": now()})
            atomic(ledger_path, ledger)
            try:
                api(manager, "/admin/goods.GoodsMould/recalcFc27Price",
                    payload={"gid": GID, "cid": CID, "id": [model_id]})
            except OSError:
                ledger.update({"stage": "write_response_unknown_readback", "updated_at": now()})
                atomic(ledger_path, ledger)
            deadline = time.monotonic() + 75
            while True:
                after = products(manager, model_id)
                if (sorted(int(row["id"]) for row in after) != item["product_ids"]
                        or not any(active(row) for row in after)):
                    raise ValueError("player_product_readback_scope_changed")
                if formula_ok(after, inputs, rates):
                    break
                if time.monotonic() >= deadline:
                    raise ValueError("player_formula_readback_timeout")
                time.sleep(2)
            ledger.update({"verified_count": index + 1, "next_index": index + 1,
                           "active_model_id": None, "last_verified_model_id": model_id,
                           "stage": "verified", "updated_at": now()})
            atomic(ledger_path, ledger)
        ledger.update({"status": "confirmed", "stage": "complete", "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "confirmed", "model_count": len(planned),
                          "verified_count": len(planned), "coin_execution_id": coin_id}))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        ledger.update({"status": "needs_reconcile", "stage": "stopped",
                       "error": reason[:90], "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "needs_reconcile", "reason": reason[:90],
                          "verified_count": ledger["verified_count"],
                          "active_model_id": ledger["active_model_id"]}))
        raise SystemExit(2)


def run_selected():
    if read(REQUEST).get("resume") is True:
        raise ValueError("legacy_player_sync_resume_requires_manual_reconciliation")
    bulk_main()


if __name__ == "__main__":
    try:
        run_selected()
    except Exception as exc:
        print(json.dumps({"status": "blocked_before_write", "reason": str(exc)[:90]
                          if isinstance(exc, ValueError) else type(exc).__name__}))
        raise SystemExit(1)
