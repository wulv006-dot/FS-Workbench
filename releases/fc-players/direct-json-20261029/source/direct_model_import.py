"""Frozen per-player JSON writes, using the original execution/event ledger."""
from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from openpyxl import load_workbook
from 球员维护工具.admin_adapter import AdminAdapter, build_existing_model_map, extract_futbin_id, extract_model_id
from 球员维护工具.admin_client import _safe_response_code, _safe_response_message
from 球员维护工具.transformer import EN_HEADERS
from .direct_model_payload import build_model_payload, validate_model_readback, missing_platforms, resolve_players_types
from .price_lock import shared_price_lock
from .repository import StateError, canonical, digest, now


def _source_rows(path):
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if len(workbook.worksheets) != 1:
            raise StateError("DIRECT_SOURCE_SHEET_INVALID")
        rows = iter(workbook.worksheets[0].iter_rows(values_only=True))
        if tuple(next(rows, ())) != EN_HEADERS:
            raise StateError("DIRECT_SOURCE_HEADERS_INVALID")
        result = []
        for values in rows:
            if not any(value is not None for value in values):
                continue
            result.append(dict(zip(EN_HEADERS, values)))
        return result
    finally:
        workbook.close()


# Admin accepts a-z, 0-9, "-" and a fixed set of accented Latin letters
# (e.g. "luka-vušković"); it rejects "ı" and silently drops ".".
_SLUG_LETTER_FOLD = {"ı": "i", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "ħ": "h", "ŀ": "l",
                     "þ": "th", "ß": "ss", "æ": "ae", "œ": "oe", "ĸ": "k", "ŋ": "n", "ŧ": "t"}


def product_slug(text):
    """Admin-safe slug; idempotent, so it also repairs slugs frozen by older plans."""
    out = []
    for char in unicodedata.normalize("NFC", str(text).lower()):
        if char.isascii():
            if char.isalnum():
                out.append(char)
            elif char == "-" or char.isspace():
                out.append("-")
            continue  # ASCII punctuation such as "." is dropped, as Admin does.
        if char in _SLUG_LETTER_FOLD:
            out.append(_SLUG_LETTER_FOLD[char])
            continue
        if char.isspace():
            out.append("-")
            continue
        base = "".join(part for part in unicodedata.normalize("NFD", char) if not unicodedata.combining(part))
        if len(base) == 1 and base.isascii() and base.isalpha():
            # Latin-1 / Latin Extended-A accents are stored by Admin as given.
            out.append(char if "À" <= char <= "ſ" else base)
    return "-".join(part for part in "".join(out).split("-") if part)


def prepare_direct_items(artifact_path, candidates, add_form, *, business_defaults, icons=None, context_artifact_path=None):
    """Selected data is frozen; classification uses the same export's full context."""
    artifact = Path(artifact_path)
    context = Path(context_artifact_path) if context_artifact_path is not None else artifact
    source_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    context_sha = hashlib.sha256(context.read_bytes()).hexdigest()
    candidates = {str(row["futbin_id"]): row for row in candidates}
    context_rows = _source_rows(context)
    types = resolve_players_types(context_rows)
    by_id = {str(row["FUTBIN ID"]).strip(): row for row in context_rows}
    result, seen = [], set()
    for source in _source_rows(artifact):
        futbin = str(source["FUTBIN ID"]).strip()
        if futbin not in candidates or futbin in seen or futbin not in by_id:
            raise StateError("DIRECT_SOURCE_SCOPE_CHANGED")
        seen.add(futbin)
        reference = by_id[futbin]
        image = (icons or {}).get(futbin, {"icon": 0, "icon_url": ""})
        payload, error = None, None
        try:
            if (str(reference["name"]).strip(), str(reference["Version"]).strip(), str(reference["IS"]).strip()) != (
                    str(source["name"]).strip(), str(source["Version"]).strip(), str(source["IS"]).strip()):
                raise StateError("DIRECT_CONTEXT_IDENTITY_CHANGED")
            if types.get(futbin) is None:
                raise StateError("DIRECT_PLAYERS_TYPE_UNKNOWN")
            payload = build_model_payload(source, add_form, icon=image["icon"], icon_url=image["icon_url"], tag_ids=[],
                                          business_defaults={**business_defaults, "players_type": types[futbin]})
        except ValueError as exc:
            error = str(exc).split(":", 1)[0]
        slug = product_slug(str(source["name"]) + "-" + futbin)
        result.append({"futbin_id": futbin, "product_slug": slug, "payload": payload, "payload_sha256": digest(payload),
                       "players_type": types.get(futbin), "blocked_error": error, "missing_platforms": missing_platforms(source),
                       "missing_price_policy": business_defaults.get("missing_price_policy", "reject"),
                       "shelves_payload": {"site_ids": [266], "aids": [21587, 21585, 21589],
                                           "status": "0", "min_qty": 1, "num": 1, "total": 0,
                                           "discount": 100, "price": business_defaults["model_price"],
                                           "is_rec": "0", "duration": "0", "open_watermark": "0"},
                       "context_artifact_path": str(context), "context_sha256": context_sha,
                       "source_sha256": source_sha, "form_sha256": digest(add_form),
                       "candidate_sha256": digest(candidates[futbin])})
    if seen != set(candidates):
        raise StateError("DIRECT_SOURCE_SCOPE_CHANGED")
    return result


def _latest(db, execution_id, futbin, phase):
    rows = db.execute("SELECT seq,status,detail_json FROM events WHERE execution_id=? AND step=? ORDER BY seq DESC",
                      (execution_id, "direct_" + phase))
    for row in rows:
        detail = json.loads(row["detail_json"])
        if detail.get("futbin_id") == futbin:
            return {"seq": row["seq"], "state": row["status"], **detail}
    return None


def _receipt(repo, execution_id, item, phase, state, payload_sha, *, previous=None, detail=None):
    with repo.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = _latest(db, execution_id, item["futbin_id"], phase)
        if current and current["payload_sha256"] != payload_sha:
            raise StateError("DIRECT_ACTION_PAYLOAD_CHANGED")
        if previous is not None and (not current or current["seq"] != previous):
            db.commit()
            return current, False
        if state == "intent" and current and current["state"] != "not_started":
            db.commit()
            return current, False
        if state == "intent":
            scope = db.execute("SELECT execution_id FROM active_scope WHERE futbin_id=?", (item["futbin_id"],)).fetchone()
            if not scope or scope["execution_id"] != execution_id:
                raise StateError("DIRECT_SCOPE_OWNER_CHANGED")
        body = {"futbin_id": item["futbin_id"], "payload_sha256": payload_sha,
                "source_sha256": item["source_sha256"], **(detail or {})}
        cursor = db.execute("INSERT INTO events(execution_id,created_at,step,status,detail_json) VALUES (?,?,?,?,?)",
                            (execution_id, now(), "direct_" + phase, state, canonical(body)))
        db.execute("UPDATE executions SET status='running',step=?,updated_at=? WHERE id=?",
                   ("direct_" + phase, now(), execution_id))
        db.commit()
        return {"seq": cursor.lastrowid, "state": state, **body}, True


def _diagnostic(exc):
    value = getattr(exc, "diagnostic", None)
    report = getattr(exc, "report", None)
    if not isinstance(value, Mapping) and isinstance(report, Mapping):
        value = report.get("diagnostic")
    return value if isinstance(value, Mapping) else {}


def _error(exc):
    result = {"error_type": type(exc).__name__}
    if isinstance(exc, StateError):
        code = str(exc)
        if code.startswith(("DIRECT_", "EXISTING_MODEL_")) and code.replace("_", "").isalnum():
            result["error_code"] = code
    diagnostic = _diagnostic(exc)
    if isinstance(diagnostic, Mapping):
        allowed = {key: diagnostic[key] for key in ("method", "endpoint", "http_status")
                   if key in diagnostic and isinstance(diagnostic[key], (str, int, float, bool, type(None)))}
        if "response_code" in diagnostic:
            allowed["response_code"] = _safe_response_code(diagnostic["response_code"])
        message = _safe_response_message({"msg": diagnostic.get("response_msg")})
        if message:
            allowed["response_msg"] = message
        result["diagnostic"] = allowed
    return result


def _action(repo, execution_id, item, phase, payload, dispatch, verify, *, allow_proof=True, should_stop=None):
    if should_stop and should_stop():
        return False
    action_sha = digest(payload)
    receipt, created = _receipt(repo, execution_id, item, phase, "intent", action_sha)
    if receipt["state"] == "rejected":
        return False
    if not created:
        # No new POST after an interrupted intent, even when the target is absent.
        try:
            proof = verify()
        except Exception:
            return False
        if receipt["state"] == "confirmed":
            return True
        if not allow_proof and receipt["state"] not in {"accepted", "confirmed"}:
            return False
        result, _ = _receipt(repo, execution_id, item, phase, "confirmed", action_sha,
                             previous=receipt["seq"], detail={"proof": proof, "reconciled_readonly": True})
        return result["state"] == "confirmed"
    try:
        if should_stop and should_stop():
            _receipt(repo, execution_id, item, phase, "not_started", action_sha,
                     previous=receipt["seq"], detail={"dispatch_started": False})
            return False
        response = dispatch()
        if not isinstance(response, Mapping) or response.get("code") not in (1, "1"):
            raise StateError("DIRECT_WRITE_RESPONSE_INVALID")
        accepted = {"response_code": response["code"], "response_sha256": digest(response)}
        data = response.get("data")
        if phase == "add" and isinstance(data, Mapping):
            row = data.get("row", data)
            if isinstance(row, Mapping) and extract_model_id(row):
                accepted["model_id"] = extract_model_id(row)
        receipt, changed = _receipt(repo, execution_id, item, phase, "accepted", action_sha,
                                    previous=receipt["seq"], detail=accepted)
        if not changed:
            return receipt["state"] == "confirmed"
        proof = verify()
        receipt, _ = _receipt(repo, execution_id, item, phase, "confirmed", action_sha,
                              previous=receipt["seq"], detail={"proof": proof,
                                                             "response_sha256": digest(response)})
        return receipt["state"] == "confirmed"
    except Exception as exc:
        if receipt["state"] == "accepted":
            detail = {key: value for key, value in receipt.items() if key not in {"seq", "state"}}
            detail["last_readback_error"] = _error(exc)
            _receipt(repo, execution_id, item, phase, "accepted", action_sha,
                     previous=receipt["seq"], detail=detail)
            return False
        diagnostic = _diagnostic(exc)
        rejected = diagnostic.get("response_code") in (401, "401", 403, "403")
        _receipt(repo, execution_id, item, phase, "rejected" if rejected else "unknown", action_sha,
                 previous=receipt["seq"], detail={**_error(exc), "retryable": False})
        return False


def _model(adapter, client, item, repo, execution_id):
    with repo.connection() as db:
        receipt = _latest(db, execution_id, item["futbin_id"], "add")
    mid = (receipt or {}).get("model_id") or (receipt or {}).get("proof", {}).get("model_id")
    if not mid:
        mid = build_existing_model_map(adapter.list_all_models()).get(item["futbin_id"])
    if not mid:
        raise StateError("DIRECT_MODEL_READBACK_MISSING")
    actual = client.get_model(mid)
    if extract_model_id(actual) != int(mid) or extract_futbin_id(actual) != item["futbin_id"]:
        raise StateError("DIRECT_MODEL_IDENTITY_CHANGED")
    validate_model_readback(item["payload"], actual)
    return int(mid)


def _products(client, mid, *, expected_slug=None, rows=None):
    model = client.get_model(mid)
    if str(model.get("status")) != "1" or str(model.get("is_put")) != "1":
        raise StateError("DIRECT_SHELVES_MODEL_STATE_INCOMPLETE")
    if rows is None:
        rows = client.get_products(mid)
    ids, scopes = [], []
    for row in rows:
        if str(row.get("gid")) != "1327" or str(row.get("cid")) != "9627" or str(row.get("mid")) != str(mid):
            raise StateError("DIRECT_PRODUCT_SCOPE_CHANGED")
        value = row.get("id")
        if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
            raise StateError("DIRECT_PRODUCT_ID_INVALID")
        if expected_slug is not None and str(row.get("site_id")) == "266" and row.get("slug") != expected_slug:
            raise StateError("DIRECT_PRODUCT_SLUG_MISMATCH")
        ids.append(int(value))
        scopes.append((str(row.get("site_id")), str(row.get("aid", row.get("game_area_id")))))
    if not ids or len(ids) != len(set(ids)):
        raise StateError("DIRECT_PRODUCTS_INCOMPLETE")
    expected = {(site, area) for site in ("0", "266") for area in ("21587", "21585", "21589")}
    if len(scopes) != 6 or set(scopes) != expected:
        raise StateError("DIRECT_PRODUCT_SIX_SCOPES_INCOMPLETE")
    return {"model_id": mid, "product_ids": sorted(ids), "products_sha256": digest(rows)}


def _shelves_readback(client, mid):
    # Shelves returns before its model flag and all six products become visible.
    pending = {"DIRECT_SHELVES_MODEL_STATE_INCOMPLETE", "DIRECT_PRODUCTS_INCOMPLETE",
               "DIRECT_PRODUCT_SIX_SCOPES_INCOMPLETE"}
    for attempt in range(6):
        try:
            return _products(client, mid)
        except StateError as exc:
            if str(exc) not in pending or attempt == 5:
                raise
            time.sleep(2)


def _product_slug(client, mid, pid, aid, *, before_fill=None):
    products = client.get_products(mid)
    rows = [row for row in products if str(row.get("id")) == str(pid)]
    if len(rows) != 1:
        raise StateError("DIRECT_PRODUCT_SCOPE_CHANGED")
    row = rows[0]
    if tuple(str(row.get(k)) for k in ("mid", "gid", "cid", "site_id", "aid")) != (
            str(mid), "1327", "9627", "266", str(aid)):
        raise StateError("DIRECT_PRODUCT_SCOPE_CHANGED")
    if "slug" not in row:
        raise StateError("DIRECT_PRODUCT_SLUG_MISMATCH")
    if before_fill is not None and row["slug"] in (None, ""):
        # Admin may propagate one edit to every product for the model.
        _products(client, mid, rows=products)
        if any("slug" not in product or product["slug"] not in (None, "", before_fill)
               for product in products):
            raise StateError("DIRECT_PRODUCT_SLUG_MISMATCH")
    return row["slug"]


def _product_state(client, mid, product_id, desired):
    _products(client, mid)
    rows = [row for row in client.get_products(mid) if str(row.get("id")) == str(product_id)]
    if len(rows) != 1 or str(rows[0].get("status")) != str(desired):
        raise StateError("DIRECT_PRODUCT_STATUS_INCOMPLETE")
    if desired:
        price = Decimal(str(rows[0].get("unit_price")))
        if not price.is_finite() or price <= 0:
            raise StateError("DIRECT_PRODUCT_PRICE_UNKNOWN")
    return {"model_id": mid, "product_id": product_id, "status": desired,
            "unit_price": rows[0].get("unit_price")}


def _synced_products(client, mid, item, expected_ids):
    proof = _products(client, mid)
    if proof["product_ids"] != expected_ids:
        raise StateError("DIRECT_PRODUCT_SCOPE_CHANGED")
    platforms = {21587: "PlayStation", 21585: "Xbox", 21589: "PC"}
    for row in client.get_products(mid):
        missing = platforms[int(row["aid"])] in item.get("missing_platforms", [])
        for field in ("num", "discount", "price", "unit_price"):
            if field == "unit_price" and missing:
                continue
            number = Decimal(str(row.get(field)))
            if not number.is_finite() or number < 0 or (field == "unit_price" and number <= 0):
                raise StateError("DIRECT_PRODUCT_PRICE_UNKNOWN")
            if field == "unit_price" and number == Decimal("9999"):
                raise StateError("DIRECT_SYNC_KNOWN_PRICE_PENDING")
    return {**proof, "formula_verified": False, "missing_platforms": item.get("missing_platforms", [])}


def _fallback_readback(client, mid, pid):
    _products(client, mid)
    rows = [row for row in client.get_products(mid) if int(row["id"]) == pid]
    if len(rows) != 1 or not _is_fallback_price(rows[0].get("unit_price")):
        raise StateError("DIRECT_FALLBACK_READBACK_INCOMPLETE")
    return {"model_id": mid, "product_id": pid, "unit_price": 9999}


def _is_fallback_price(value):
    try:
        return Decimal(str(value)) == Decimal("9999")
    except (ArithmeticError, ValueError):
        return False


def _bound_plan(repo, execution_id, plan):
    execution = repo.get_execution(execution_id, plan["owner"])
    original = repo.get_plan(execution["plan_id"], plan["owner"])
    if plan.get("plan_id") != execution["plan_id"] or plan.get("import_mode") != "direct_json_v1":
        raise StateError("DIRECT_PLAN_REQUIRED")
    if plan.get("origin_plan_digest"):
        if original["plan_digest"] != plan["origin_plan_digest"]:
            raise StateError("DIRECT_ORIGIN_CHANGED")
        if not any(event["step"] == "direct_plan_migration" and
                   event["detail"].get("root_controlled") is True and
                   isinstance(event["detail"].get("original_request_no_enqueue_evidence"), Mapping) and
                   event["detail"]["original_request_no_enqueue_evidence"] and
                   event["detail"].get("direct_plan_sha256") == digest(plan) and
                   event["detail"].get("direct_plan") == plan for event in execution["events"]):
            raise StateError("DIRECT_MIGRATION_PROOF_REQUIRED")
    elif any(original.get(key) != plan.get(key) for key in
             ("direct_items", "scope_ids", "upload_futbin_ids", "tag_futbin_ids", "recommend_futbin_ids", "selected_tag_ids", "existing_model_map")):
        raise StateError("DIRECT_PLAN_CHANGED")
    items = plan.get("direct_items") or []
    ids = [item["futbin_id"] for item in items]
    if not ids or len(ids) != len(set(ids)) or set(ids) != set(plan["upload_futbin_ids"]):
        raise StateError("DIRECT_SOURCE_SCOPE_CHANGED")
    scope = set(ids) | set(plan.get("existing_model_map", {}))
    if scope != set(plan["scope_ids"]) or any(set(plan.get(key, [])) - scope for key in ("tag_futbin_ids", "recommend_futbin_ids")):
        raise StateError("DIRECT_SOURCE_SCOPE_CHANGED")
    artifact_sha = hashlib.sha256(Path(plan["artifact_path"]).read_bytes()).hexdigest()
    if artifact_sha != plan["artifact_sha256"]:
        raise StateError("ARTIFACT_CHANGED")
    for item in items:
        if item["source_sha256"] != artifact_sha or digest(item["payload"]) != item["payload_sha256"]:
            raise StateError("DIRECT_ITEM_CHANGED")
        context_path = item.get("context_artifact_path")
        context_sha = item.get("context_sha256")
        if (not context_path or not context_sha or
                hashlib.sha256(Path(context_path).read_bytes()).hexdigest() != context_sha or
                context_path != plan.get("context_artifact_path") or context_sha != plan.get("context_sha256")):
            raise StateError("DIRECT_CONTEXT_CHANGED")
    return execution


def _finish_person(repo, execution_id, item, mid, required):
    with repo.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if any(not (row := _latest(db, execution_id, item["futbin_id"], phase)) or row["state"] != "confirmed"
               for phase in required):
            raise StateError("DIRECT_PERSON_NOT_CONFIRMED")
        db.execute("INSERT OR IGNORE INTO execution_items VALUES (?,?,?,?,?,?,?)",
                   (execution_id, mid, "verified", canonical(item), None,
                    canonical({"model_id": mid, "futbin_id": item["futbin_id"]}), now()))
        db.execute("UPDATE execution_items SET status='verified',updated_at=? WHERE execution_id=? AND model_id=?",
                   (now(), execution_id, mid))
        db.execute("DELETE FROM active_scope WHERE execution_id=? AND futbin_id=?", (execution_id, item["futbin_id"]))
        db.commit()


def execute_direct_plan(settings, repo, client, execution_id, plan, should_stop=None, only_futbin_ids=None):
    if not settings.new_card_write_enabled:
        raise StateError("WRITE_DISABLED")
    execution = _bound_plan(repo, execution_id, plan)
    closed = {row["planned"].get("futbin_id"): row["planned"] for row in execution["items"] if row["status"] == "verified"}
    existing = {str(fid): int(mid) for fid, mid in plan.get("existing_model_map", {}).items()}
    for fid, mid in existing.items():
        row = client.get_model(mid)
        if (extract_model_id(row) != mid or extract_futbin_id(row) != fid or
                str(row.get("gid")) != "1327" or str(row.get("cid")) != "9627"):
            raise StateError("EXISTING_MODEL_MAP_CHANGED")
    all_ids = {item["futbin_id"] for item in plan["direct_items"]} | set(existing)
    selected = all_ids if only_futbin_ids is None else {str(value) for value in only_futbin_ids}
    if not selected or selected - all_ids:
        raise StateError("DIRECT_EXECUTION_SUBSET_INVALID")
    adapter = AdminAdapter(client, state_root=settings.data_root / "admin_state/shared", write_enabled=False)
    done, unresolved, waiting = [], [], []
    with adapter.temporary_write_access():
        for item in plan["direct_items"]:
            fid = item["futbin_id"]
            if fid not in selected:
                continue
            if fid in closed and all(closed[fid].get(key) == item.get(key) for key in
                                     ("payload_sha256", "source_sha256", "context_sha256")):
                done.append(fid)
                continue
            if should_stop and should_stop():
                unresolved.extend(row["futbin_id"] for row in plan["direct_items"] if row["futbin_id"] not in done)
                break
            try:
                if item.get("blocked_error"):
                    unresolved.append(fid)
                    repo.set_execution(execution_id, "running", "direct_person_blocked",
                                       {"futbin_id": fid, "error_code": item["blocked_error"], "retryable": False})
                    continue
                with repo.connection() as db:
                    old_add = _latest(db, execution_id, fid, "add")
                if not old_add and fid in build_existing_model_map(adapter.list_all_models()):
                    unresolved.append(fid)
                    repo.set_execution(execution_id, "running", "direct_conflict", {"futbin_id": fid})
                    continue
                if not _action(repo, execution_id, item, "add", item["payload"],
                               lambda: client.add_model(item["payload"]),
                               lambda: {"model_id": _model(adapter, client, item, repo, execution_id)}, should_stop=should_stop):
                    unresolved.append(fid)
                    continue
                mid = _model(adapter, client, item, repo, execution_id)

                def checked_write(write):
                    validate_model_readback(item["payload"], client.get_model(mid))
                    return write()

                shelves = item["shelves_payload"]
                if shelves.get("site_ids") != [266] or shelves.get("aids") != [21587, 21585, 21589] or str(shelves.get("status")) != "0":
                    raise StateError("DIRECT_SHELVES_SCOPE_INVALID")
                if not _action(repo, execution_id, item, "shelves", {"model_id": mid, "payload": shelves},
                               lambda: checked_write(lambda: client.shelves_models([mid], gid=1327, cid=9627, payload=shelves)),
                               lambda: _shelves_readback(client, mid), should_stop=should_stop):
                    unresolved.append(fid)
                    continue
                phases = ["add", "shelves"]
                frozen_slug = item.get("product_slug")
                slug = product_slug(frozen_slug) if frozen_slug else frozen_slug
                # A plan frozen before the Admin charset rule keeps its old receipts;
                # the corrected slug is a new action under its own phase name.
                slug_phase = "product_slug_" if slug == frozen_slug else "product_slug_admin_charset_"
                if slug:
                    products = client.get_products(mid)
                    _products(client, mid, rows=products)
                    slug_complete = True
                    for product in products:
                        if str(product["site_id"]) != "266":
                            continue
                        pid, aid = int(product["id"]), int(product["aid"])
                        current_slug = _product_slug(client, mid, pid, aid, before_fill=slug)
                        if current_slug not in (None, "", slug):
                            raise StateError("DIRECT_PRODUCT_SLUG_MISMATCH")
                        phase = slug_phase + str(pid)
                        if current_slug == slug:
                            with repo.connection() as db:
                                receipt = _latest(db, execution_id, fid, phase)
                            if not receipt or receipt["state"] == "not_started":
                                continue

                        def verify_slug():
                            if _product_slug(client, mid, pid, aid) != slug:
                                raise StateError("DIRECT_PRODUCT_SLUG_MISMATCH")
                            return {"product_id": pid, "slug": slug}

                        def set_slug():
                            if current_slug == slug:
                                return {"code": 1, "no_change": True}
                            return client.set_product_slug(pid, slug)

                        if not _action(repo, execution_id, item, phase,
                                       {"model_id": mid, "product_id": pid, "aid": aid, "slug": slug},
                                       set_slug, verify_slug, should_stop=should_stop):
                            slug_complete = False
                            break
                        phases.append(phase)
                    if not slug_complete:
                        unresolved.append(fid)
                        continue
                if fid in plan["tag_futbin_ids"]:
                    tags = list(plan["selected_tag_ids"])

                    def verify_tags():
                        row = client.get_model(mid)
                        validate_model_readback(item["payload"], row)
                        current = row.get("tid", [])
                        current = current.split(",") if isinstance(current, str) else current
                        if not {str(tag) for tag in tags}.issubset({str(tag) for tag in current}):
                            raise StateError("DIRECT_TAG_READBACK_INCOMPLETE")
                        return {"model_id": mid, "tag_ids": tags}

                    if not _action(repo, execution_id, item, "tags", {"model_id": mid, "tag_ids": tags},
                                   lambda: checked_write(lambda: {"code": 1, "data": adapter.add_tags([mid], tags)}),
                                   verify_tags, should_stop=should_stop):
                        unresolved.append(fid)
                        continue
                    phases.append("tags")
                if fid in plan["recommend_futbin_ids"]:
                    def verify_recommend():
                        if str(client.get_model(mid).get("is_rec")) != "1":
                            raise StateError("DIRECT_RECOMMEND_READBACK_INCOMPLETE")
                        return {"model_id": mid, "is_rec": 1}
                    if not _action(repo, execution_id, item, "recommend", {"model_id": mid, "is_rec": 1},
                                   lambda: checked_write(lambda: {"code": 1, "data": adapter.set_recommendation([mid], True)}),
                                   verify_recommend, should_stop=should_stop):
                        unresolved.append(fid)
                        continue
                    phases.append("recommend")
                with shared_price_lock() as acquired:
                    if not acquired:
                        waiting.append(fid)
                        continue
                    product_ids = _products(client, mid)["product_ids"]
                    fallback = item.get("missing_price_policy") == "fallback_9999"

                    def sync_once():
                        if fallback and item.get("missing_platforms"):
                            return checked_write(lambda: client.recalc_fc27_price(model_ids=[mid], gid=1327, cid=9627))
                        return checked_write(lambda: {"code": 1, "data": adapter.sync_prices([mid])})

                    if not _action(repo, execution_id, item, "sync", {"model_id": mid}, sync_once,
                                   lambda: _synced_products(client, mid, item, product_ids),
                                   allow_proof=False, should_stop=should_stop):
                        unresolved.append(fid)
                        continue
                    phases.append("sync")
                    fallback_complete = True
                    if fallback:
                        platforms = {21587: "PlayStation", 21585: "Xbox", 21589: "PC"}
                        for product in client.get_products(mid):
                            if platforms[int(product["aid"])] not in item.get("missing_platforms", []):
                                continue
                            pid = int(product["id"])
                            scope = (str(product["site_id"]), str(product["aid"]))
                            phase = "fallback_price_" + str(pid)

                            def fallback_once(pid=pid, scope=scope):
                                validate_model_readback(item["payload"], client.get_model(mid))
                                _products(client, mid)
                                current = [row for row in client.get_products(mid) if int(row["id"]) == pid]
                                if len(current) != 1 or (str(current[0]["site_id"]), str(current[0]["aid"])) != scope:
                                    raise StateError("DIRECT_PRODUCT_SCOPE_CHANGED")
                                if _is_fallback_price(current[0].get("unit_price")):
                                    return {"code": 1, "no_change": True}
                                return client.set_product_fallback_price(mid, pid)

                            if not _action(repo, execution_id, item, phase,
                                           {"model_id": mid, "product_id": pid, "site_id": scope[0], "aid": scope[1], "unit_price": 9999},
                                           fallback_once, lambda pid=pid: _fallback_readback(client, mid, pid),
                                           should_stop=should_stop):
                                fallback_complete = False
                                break
                            phases.append(phase)
                    if not fallback_complete:
                        unresolved.append(fid)
                        continue
                product_rows = list(client.get_products(mid))
                _products(client, mid, expected_slug=slug, rows=product_rows)
                platforms = {"21587": "PlayStation", "21585": "Xbox", "21589": "PC"}
                enabled = True
                for product in product_rows:
                    pid = int(product["id"])
                    scope = (str(product["site_id"]), str(product["aid"]))
                    desired = int(item.get("missing_price_policy") == "fallback_9999" or
                                  platforms[str(product["aid"])] not in item.get("missing_platforms", []))
                    phase = "product_status_" + str(pid)

                    def set_status(pid=pid, desired=desired, scope=scope):
                        validate_model_readback(item["payload"], client.get_model(mid))
                        _products(client, mid)
                        current = [row for row in client.get_products(mid) if int(row["id"]) == pid]
                        if len(current) != 1 or (str(current[0]["site_id"]), str(current[0]["aid"])) != scope:
                            raise StateError("DIRECT_PRODUCT_SCOPE_CHANGED")
                        if str(current[0].get("status")) == str(desired):
                            return {"code": 1, "no_change": True}
                        if desired:
                            value = Decimal(str(current[0].get("unit_price")))
                            if not value.is_finite() or value <= 0:
                                raise StateError("DIRECT_PRODUCT_PRICE_UNKNOWN")
                        return client.set_product_status(mid, pid, desired)

                    if not _action(repo, execution_id, item, phase,
                                   {"model_id": mid, "product_id": pid, "site_id": scope[0], "aid": scope[1], "status": desired},
                                   set_status, lambda pid=pid, desired=desired: _product_state(client, mid, pid, desired),
                                   should_stop=should_stop):
                        enabled = False
                        break
                    phases.append(phase)
                if not enabled:
                    unresolved.append(fid)
                    continue
                _model(adapter, client, item, repo, execution_id)
                _products(client, mid, expected_slug=slug)
                _finish_person(repo, execution_id, item, mid, phases)
                done.append(fid)
            except Exception as exc:
                unresolved.append(fid)
                repo.set_execution(execution_id, "running", "direct_person_blocked", {"futbin_id": fid, **_error(exc)})
        for fid, mid in existing.items():
            if fid not in selected:
                continue
            if fid in closed and closed[fid].get("kind") == "existing_actions":
                done.append(fid)
                continue
            if should_stop and should_stop():
                unresolved.append(fid)
                continue
            item = {"futbin_id": fid, "model_id": mid, "kind": "existing_actions",
                    "source_sha256": plan["artifact_sha256"]}
            phases = []
            try:
                for phase, targets in (("extra_tags", plan["tag_futbin_ids"]),
                                       ("extra_recommend", plan["recommend_futbin_ids"])):
                    if fid not in targets:
                        continue
                    tags = list(plan["selected_tag_ids"])

                    def verify_extra(phase=phase):
                        row = client.get_model(mid)
                        if extract_model_id(row) != mid or extract_futbin_id(row) != fid or str(row.get("gid")) != "1327" or str(row.get("cid")) != "9627":
                            raise StateError("EXISTING_MODEL_MAP_CHANGED")
                        if phase == "extra_tags":
                            current = row.get("tid", [])
                            current = current.split(",") if isinstance(current, str) else current
                            if not {str(tag) for tag in tags}.issubset({str(tag) for tag in current}):
                                raise StateError("DIRECT_TAG_READBACK_INCOMPLETE")
                        elif str(row.get("is_rec")) != "1":
                            raise StateError("DIRECT_RECOMMEND_READBACK_INCOMPLETE")
                        return {"model_id": mid, "tag_ids": tags} if phase == "extra_tags" else {"model_id": mid, "is_rec": 1}

                    def write_extra(phase=phase):
                        row = client.get_model(mid)
                        if extract_model_id(row) != mid or extract_futbin_id(row) != fid:
                            raise StateError("EXISTING_MODEL_MAP_CHANGED")
                        result = adapter.add_tags([mid], tags) if phase == "extra_tags" else adapter.set_recommendation([mid], True)
                        return {"code": 1, "data": result}

                    action = {"model_id": mid, "tag_ids": tags} if phase == "extra_tags" else {"model_id": mid, "is_rec": 1}
                    if not _action(repo, execution_id, item, phase, action, write_extra, verify_extra, should_stop=should_stop):
                        unresolved.append(fid)
                        break
                    phases.append(phase)
                else:
                    _finish_person(repo, execution_id, item, mid, phases)
                    done.append(fid)
            except Exception as exc:
                unresolved.append(fid)
                repo.set_execution(execution_id, "running", "direct_person_blocked", {"futbin_id": fid, **_error(exc)})
    current = repo.get_execution(execution_id, plan["owner"])
    previously_closed = {item["planned"].get("futbin_id") for item in current["items"] if item["status"] == "verified"}
    pending = sorted(all_ids - selected - previously_closed)
    status = "waiting_price_lock" if waiting else "needs_reconcile" if unresolved else "partial_readback" if pending else "completed_readback"
    step = "sync_pending" if waiting else "direct_partial" if unresolved else "pilot_complete" if pending else "done"
    result = {"completed_futbin_ids": done, "unresolved_futbin_ids": sorted(set(unresolved)),
              "waiting_futbin_ids": waiting, "pending_futbin_ids": pending, "import_mode": "direct_json_v1"}
    repo.set_execution(execution_id, status, step, result)
    return result
