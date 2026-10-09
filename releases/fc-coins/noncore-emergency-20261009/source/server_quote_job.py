"""Build a review-only FC27 proposal from one complete server snapshot."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import sys

from snapshot_layer import PLATFORMS, SITES, ROOT, atomic_json
from fc27_quote_engine import (calculate, positive, nonnegative, normalize_discount_rules,
                               discount_rules_sha256, source_coverage)
from automation_policy import load_policy


ENGINE_FILE = Path(__file__).with_name("fc27_quote_engine.py")


def age_ok(value: str, now: datetime) -> bool:
    captured = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return captured.tzinfo is not None and 0 <= (now - captured).total_seconds() <= 3600


def validate_edits(edits):
    if not isinstance(edits, dict) or set(edits) - {"costs", "offers", "quotes", "minimum_gross_margin_pct", "reason"}:
        raise ValueError("edits_invalid")
    clean = {}
    margin = edits.get("minimum_gross_margin_pct", "10")
    if nonnegative(margin, "最低毛利率") >= 100:
        raise ValueError("margin_invalid")
    clean["minimum_gross_margin_pct"] = str(margin)
    for name in ("costs", "quotes"):
        source = edits.get(name) or {}
        if not isinstance(source, dict) or set(source) - set(PLATFORMS):
            raise ValueError("edit_platform_invalid")
        clean[name] = {p: str(positive(v, name)) for p, v in source.items()}
    offers = edits.get("offers") or {}
    if not isinstance(offers, dict) or set(offers) - set(PLATFORMS):
        raise ValueError("offer_edit_invalid")
    clean["offers"] = {}
    for platform, sites in offers.items():
        if not isinstance(sites, dict) or set(sites) - set(SITES):
            raise ValueError("offer_site_invalid")
        clean["offers"][platform] = {}
        for site, values in sites.items():
            if not isinstance(values, dict) or set(values) - {"usd_price", "base_k", "bonus_k", "comparable"}:
                raise ValueError("offer_fields_invalid")
            row = {}
            for key in ("usd_price", "base_k", "bonus_k"):
                if key in values:
                    row[key] = str(nonnegative(values[key], key) if key == "bonus_k" else positive(values[key], key))
            if "comparable" in values:
                if not isinstance(values["comparable"], bool):
                    raise ValueError("comparable_invalid")
                row["comparable"] = values["comparable"]
            clean["offers"][platform][site] = row
    reason = edits.get("reason", "")
    if not isinstance(reason, str) or len(reason.strip()) > 200:
        raise ValueError("reason_invalid")
    if (clean["costs"] or clean["quotes"] or clean["offers"]) and not reason.strip():
        raise ValueError("manual_reason_required")
    clean["reason"] = reason.strip()
    return clean


def _quote_for_run(run_id: str, edits=None, *, draft_rules=None, persist=True, expected_revision=None) -> dict:
    requested_edits = edits or {}
    edits = validate_edits(requested_edits)
    policy = load_policy()
    if not persist:
        if type(expected_revision) is not int or policy["revision"] != expected_revision:
            raise ValueError("automation_revision_changed")
        if Decimal(policy["minimum_gross_margin_pct"]) < 10:
            raise ValueError("automation_discount_margin_floor_invalid")
    rules = normalize_discount_rules(draft_rules if not persist else policy.get("pricing_rules"))
    edits["pricing_rules"] = rules
    if policy["minimum_gross_margin_pct"] is not None:
        if ("minimum_gross_margin_pct" in requested_edits
                and Decimal(edits["minimum_gross_margin_pct"]) != Decimal(policy["minimum_gross_margin_pct"])):
            raise ValueError("automation_margin_configured_centrally")
        edits["minimum_gross_margin_pct"] = policy["minimum_gross_margin_pct"]
    source = ROOT / "runs" / f"{run_id}.json"
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    if snapshot.get("run_id") != run_id or snapshot.get("status") != "ready_for_quote":
        raise ValueError("snapshot_incomplete")
    newest = max((p for p in (ROOT / "runs").glob("*.json")), key=lambda p: p.stat().st_mtime)
    if newest != source:
        raise ValueError("newer_run_exists")
    now = datetime.now(timezone.utc)
    if not age_ok(snapshot["created_at"], now):
        raise ValueError("run_stale")
    costs = {}
    offers = {platform: {} for platform in PLATFORMS}
    for cost in snapshot["costs"]:
        platform = cost.get("platform")
        if platform not in PLATFORMS or platform in costs or cost.get("status") != "valid":
            raise ValueError("cost_invalid")
        if cost.get("run_id") != run_id or not age_ok(cost["checked_at"], now):
            raise ValueError("cost_stale_or_mismatched")
        if (cost.get("game") != "FC27" or cost.get("product") != "Game Coins"
                or cost.get("unit") != "CNY/K" or not str(cost.get("record_id", "")).isdigit()
                or not cost.get("trade_at") or Decimal(str(cost["cny_per_1k"])) <= 0):
            raise ValueError("cost_contract_invalid")
        costs[platform] = cost
    coverage = source_coverage(snapshot["competitors"])
    for offer in snapshot["competitors"]:
        platform, site = offer.get("platform"), offer.get("source")
        if platform not in PLATFORMS or site not in SITES or site in offers[platform]:
            raise ValueError("competitor_invalid")
        if offer.get("run_id") != run_id:
            raise ValueError("competitor_stale_or_mismatched")
        if offer.get("status") == "missing" and site != "Lootbar":
            continue
        if (offer.get("run_id") != run_id or offer.get("status") != "valid"
                or offer.get("currency") != "USD" or not age_ok(offer["captured_at"], now)):
            raise ValueError("competitor_stale_or_mismatched")
        offers[platform][site] = {
            "usd_price": offer["gross_usd"], "base_k": offer["purchase_k"],
            "bonus_k": offer["bonus_k"], "conditional": offer.get("conditional", False),
            "comparable": offer.get("comparable", True), "url": offer["url"],
            "checked_at": offer["captured_at"], "status": "已核对",
        }
    if set(costs) != set(PLATFORMS) or not coverage["ready"]:
        raise ValueError("coverage_incomplete")
    fx = snapshot.get("fx") or {}
    if fx.get("status") != "valid" or not age_ok(fx["checked_at"], now):
        raise ValueError("fx_missing_or_stale")
    storefront = snapshot.get("storefront") or {}
    if (storefront.get("source") != "https://www.mmoexp.com/Fc-27/Coins.html"
            or storefront.get("currency") != "USD"
            or storefront.get("collection_run_id") != run_id
            or storefront.get("status") != "ok"
            or storefront.get("package_k") != 100
            or set(storefront.get("rows") or {}) != set(PLATFORMS)):
        raise ValueError("storefront_contract_invalid")
    for platform in PLATFORMS:
        row = storefront["rows"][platform]
        if (row.get("platform") != platform or row.get("status") != "ok"
                or row.get("base_k") != "100" or not age_ok(row["checked_at"], now)
                or not str(row.get("sku_id", "")).isdigit()):
            raise ValueError("storefront_row_invalid:" + platform)
        total = positive(row.get("package_usd"), "MMOEXP 页面总价")
        bonus = nonnegative(row.get("bonus_k"), "MMOEXP 赠送 K")
        if bonus > 100 or total != total.quantize(Decimal("0.01")):
            raise ValueError("storefront_value_invalid:" + platform)
        expected_unit = (total / (Decimal(100) + bonus)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if Decimal(str(row.get("usd_per_k"))) != expected_unit:
            raise ValueError("storefront_unit_mismatch:" + platform)
    evidence = {"game": "FC27", "product": "Game Coins", "checked_at": snapshot["created_at"],
                "costs": costs, "offers": offers, "fx": fx,
                "storefront": storefront}
    result = calculate(evidence, edits)
    if [row.get("platform") for row in result["rows"]] != list(PLATFORMS):
        raise ValueError("quote_platform_invalid")
    if any(row.get("proposal") is None or row.get("missing") for row in result["rows"]):
        raise ValueError("quote_not_ready")
    review = any(row.get("margin_below_minimum") or row.get("auto_blocked_reason")
                 for row in result["rows"])
    proposal = {"run_id": run_id, "created_at": now.isoformat(),
                "status": "margin_review_required" if review else "ready_for_preview",
                "automation_policy_revision": policy["revision"],
                "pricing_rules_schema_version": 1, "pricing_rules": rules,
                "pricing_rules_sha256": discount_rules_sha256(rules),
                "snapshot_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "quote_engine_sha256": hashlib.sha256(ENGINE_FILE.read_bytes()).hexdigest(),
                "cost_record_ids": {p: costs[p]["record_id"] for p in PLATFORMS},
                "evidence": evidence, "edits": edits, "result": result}
    if not persist:
        if load_policy()["revision"] != expected_revision:
            raise ValueError("automation_revision_changed")
        return proposal
    quote_path = ROOT / "quotes" / f"{run_id}.json"
    atomic_json(quote_path, proposal)
    os.chown(quote_path.parent, -1, 11028)
    os.chmod(quote_path.parent, 0o750)
    os.chown(quote_path, -1, 11028)
    os.chmod(quote_path, 0o640)
    return {"run_id": run_id, "status": proposal["status"], "platforms": list(PLATFORMS),
            "quote_engine_sha256": proposal["quote_engine_sha256"]}


def quote_for_run(run_id: str, edits=None) -> dict:
    return _quote_for_run(run_id, edits)


def preview_discount_rules(rules, expected_revision):
    if rules is None:
        raise ValueError("automation_discount_rules_invalid")
    newest = max((ROOT / "runs").glob("*.json"), key=lambda path: path.stat().st_mtime, default=None)
    if newest is None:
        raise ValueError("automation_discount_snapshot_unavailable")
    try:
        draft = _quote_for_run(newest.stem, draft_rules=rules, persist=False,
                               expected_revision=expected_revision)
    except ValueError as exc:
        if str(exc).startswith("automation_"):
            raise
        raise ValueError("automation_discount_snapshot_unavailable") from None
    policy = load_policy()
    if policy["revision"] != expected_revision:
        raise ValueError("automation_revision_changed")
    current = calculate(draft["evidence"], {"minimum_gross_margin_pct": policy["minimum_gross_margin_pct"],
                                            "pricing_rules": policy["pricing_rules"]})
    return {"draft_only": True, "config_revision": expected_revision,
            "run_id": draft["run_id"], "collected_at": draft["evidence"]["checked_at"],
            "snapshot_sha256": draft["snapshot_sha256"], "quote_engine_sha256": draft["quote_engine_sha256"],
            "current_rules_sha256": discount_rules_sha256(policy["pricing_rules"]),
            "draft_rules_sha256": draft["pricing_rules_sha256"], "pricing_rules": draft["pricing_rules"],
            "original": calculate(draft["evidence"], {"minimum_gross_margin_pct": policy["minimum_gross_margin_pct"]}),
            "current": current, "draft": draft["result"]}


if __name__ == "__main__":
    try:
        print(json.dumps(quote_for_run(sys.argv[1])))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "NO_QUOTE", "reason": reason[:80]}))
        raise SystemExit(1)
