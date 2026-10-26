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
from fc27_quote_engine import calculate,positive,nonnegative,source_coverage
from automation_policy import load_policy


ENGINE_FILE = Path(__file__).with_name("fc27_quote_engine.py")


def previous_confirmed_decision(run_id, storefront):
    """Reuse a decision only when its original public confirmation matches this run."""
    confirmed=[]
    for path in (ROOT/'executions').glob('*.json'):
        audit=json.loads(path.read_text('utf-8'))
        if audit.get('run_id')!=run_id and audit.get('status')=='CONFIRMED' and audit.get('sync_confirmed'):
            confirmed.append(audit)
    if not confirmed:return None
    audit=max(confirmed,key=lambda row:row['created_at'])
    job_path=ROOT/'jobs'/(audit['execution_id']+'.json')
    if not job_path.is_file():return None
    job=json.loads(job_path.read_text('utf-8'))
    if (job.get('public_page_readback') or {}).get('status')!='verified':return None
    prior_path=ROOT/'quotes'/(audit['run_id']+'.json')
    if not prior_path.is_file():return None
    prior=json.loads(prior_path.read_text('utf-8'))
    rows={row['platform']:row for row in prior['result']['rows']}
    if set(rows)!=set(PLATFORMS):return None
    if any(positive(rows[p]['target_page_usd'],'previous_price')!=positive(storefront['rows'][p]['package_usd'],'public_price')
           or positive(prior['evidence']['storefront']['rows'][p]['base_k'],'previous_quantity')!=positive(storefront['rows'][p]['base_k'],'public_quantity')
           or nonnegative(prior['evidence']['storefront']['rows'][p]['bonus_k'],'previous_bonus')!=nonnegative(storefront['rows'][p]['bonus_k'],'public_bonus') for p in PLATFORMS):return None
    return dict(execution_id=audit['execution_id'],receipt=prior['result']['decision_receipt'])


def observed_manual_decision(run_id, storefront):
    """A candidate plus independent backend/public observations is not a writer receipt."""
    jobs=sorted((ROOT/'jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:120]
    values=[json.loads(p.read_text('utf-8')) for p in jobs]
    manual=next((j for j in values if j.get('kind')=='recalculate' and j.get('status')=='ready' and j.get('actor') in {'wulv','chenchao','DY'}),None)
    if not manual:return None
    prior_run=manual['request'].get('run_id')
    if not prior_run or prior_run==run_id:return None
    path=ROOT/'quotes'/(prior_run+'.json')
    if not path.is_file():return None
    raw=path.read_bytes();prior=json.loads(raw);quotes=(prior.get('edits') or {}).get('quotes') or {}
    if set(quotes)!=set(PLATFORMS) or not prior.get('edits',{}).get('reason'):return None
    if any(positive(quotes[p],'manual_price')*100!=positive(storefront['rows'][p]['package_usd'],'public_price') or
           positive(prior['evidence']['storefront']['rows'][p]['base_k'],'prior_base')!=positive(storefront['rows'][p]['base_k'],'base') or
           nonnegative(prior['evidence']['storefront']['rows'][p]['bonus_k'],'prior_bonus')!=nonnegative(storefront['rows'][p]['bonus_k'],'bonus') for p in PLATFORMS):return None
    for job in values:
        if job.get('kind')!='preview' or job.get('status')!='ready' or job.get('actor')!=manual['actor'] or job.get('request',{}).get('run_id')!=prior_run:continue
        ident=(job.get('result') or {}).get('preview_id')
        if not ident:continue
        saved=ROOT/'previews'/(ident+'.json')
        if not saved.is_file():continue
        view=json.loads(saved.read_text('utf-8'));rows={r['platform']:r for r in view.get('backend_before',{}).get('rows',[])}
        if view.get('quote_sha256')!=hashlib.sha256(raw).hexdigest() or set(rows)!=set(PLATFORMS):continue
        if all(positive(rows[p]['b2c'],'backend_price')==positive(quotes[p],'candidate_price') for p in PLATFORMS):
            return dict(job_id=manual['job_id'],owner=manual['actor'],preview_id=ident,receipt=prior['result']['decision_receipt'],
                        source='candidate_and_independent_backend_public_observation',write_performed=False)
    return None


def age_ok(value: str, now: datetime) -> bool:
    captured = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return captured.tzinfo is not None and 0 <= (now - captured).total_seconds() <= 3600


def validate_edits(edits):
    if not isinstance(edits, dict) or set(edits) - {"costs", "offers", "quotes", "minimum_gross_margin_pct", "reason"}:
        raise ValueError("edits_invalid")
    clean = {}
    margin = edits.get("minimum_gross_margin_pct", "20")
    if not 20 <= nonnegative(margin, "最低毛利率") < 100:
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


def reference_context(snapshot, now):
    """Optional same-run ItemD2R evidence; no stale or mixed-cycle price fallback."""
    from pricing_v2 import fresh, instant, number
    raw = snapshot.get('reference_competitors') or {}
    missing = dict(status='unavailable',offers=[],reason='itemd2r_not_captured_before_decision')
    if not isinstance(raw,dict):
        return dict(missing,reason='itemd2r_reference_invalid')
    if raw.get('status') != 'captured':
        return dict(missing,reason=raw.get('reason') or missing['reason'])
    try:
        offers = raw['offers']
        if raw.get('run_id') != snapshot['run_id'] or [r.get('platform') for r in offers] != list(PLATFORMS):
            raise ValueError('itemd2r_reference_run_or_coverage')
        for row in offers:
            if (row.get('source')!='ItemD2R' or row.get('run_id')!=snapshot['run_id']
                    or row.get('url')!='https://www.itemd2r.com/ea-sports-fc/fc-27-coins'
                    or row.get('status')!='valid' or row.get('currency')!='USD'
                    or row.get('conditional') is not False or row.get('comparable') is not True
                    or number(row.get('purchase_k'))!=100 or number(row.get('bonus_k'),zero=True)>100):
                raise ValueError('itemd2r_reference_contract')
            number(row.get('gross_usd'))
            fresh(row['captured_at'],now,900)
        stamps=[instant(r['captured_at']) for r in snapshot['competitors']+offers if r.get('status')=='valid']
        if (max(stamps)-min(stamps)).total_seconds()>300:
            raise ValueError('itemd2r_reference_capture_span_over_300_seconds')
        return dict(status='available',run_id=snapshot['run_id'],offers=offers,
                    capture_span_seconds=(max(stamps)-min(stamps)).total_seconds(),
                    authority='fc-pricing-v3-20261026-observation')
    except (KeyError,TypeError,ValueError,AttributeError) as exc:
        return dict(missing,reason=str(exc) if isinstance(exc,ValueError) else 'itemd2r_reference_invalid')


def _quote_for_run(run_id: str, edits=None, *, draft_rules=None, persist=True, expected_revision=None, hermes_decision=None) -> dict:
    requested_edits = edits or {}
    edits = validate_edits(requested_edits)
    policy = load_policy()
    if not persist:
        if type(expected_revision) is not int or policy["revision"] != expected_revision:
            raise ValueError("automation_revision_changed")
        if Decimal(policy["minimum_gross_margin_pct"]) < 20:
            raise ValueError("automation_discount_margin_floor_invalid")
    if draft_rules is not None:raise ValueError('pricing_legacy_bands_retired_use_v3_parameters')
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
    from fc_pricing_v3.runtime import collection_scope,ledger
    from fc_pricing_v3.selective_sources import source_plan,planned_source_coverage
    selection=collection_scope(ledger(),run_id)
    planned=source_plan(selection['active_mode'],selection['scope'])
    for offer in snapshot["competitors"]:
        if offer.get("source") not in planned["required_markets"]:continue
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
    if set(costs) != set(PLATFORMS):
        raise ValueError("coverage_incomplete")
    reference_market = reference_context(snapshot, now) if 'ItemD2R' in planned['required_markets'] else dict(status='not_required',offers=[])
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
    evidence = {"game": "FC27", "product": "Game Coins", "run_id": run_id, "checked_at": snapshot["created_at"],
                "costs": costs, "offers": offers, "fx": fx,
                "storefront": storefront, "reference_market": reference_market,
                "arab_ut_status": snapshot.get('arab_ut_status')}
    from pricing_sources import collect as collect_pricing_constraints
    evidence['promotion_envelope']=collect_pricing_constraints(storefront,persist=persist)
    from fc_pricing_v3.runtime import context
    evidence=context(evidence)
    coverage=planned_source_coverage(dict(snapshot,arab_ut_status=evidence['arab_ut_status']),evidence['source_plan'],datetime.now(timezone.utc),reference_market=reference_market)
    if not coverage['ready']:raise ValueError('coverage_incomplete')
    evidence['source_coverage']=coverage
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
                "snapshot_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "quote_engine_sha256": hashlib.sha256(ENGINE_FILE.read_bytes()).hexdigest(),
                "cost_record_ids": {p: costs[p]["record_id"] for p in PLATFORMS},
                "evidence": evidence, "edits": edits, "result": result}
    if hermes_decision is not None:
        proposal['hermes_decision']=hermes_decision
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


def preview_discount_rules(*args,**kwargs):
    raise ValueError('pricing_legacy_bands_retired_use_v3_parameters')


if __name__ == "__main__":
    try:
        print(json.dumps(quote_for_run(sys.argv[1])))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "NO_QUOTE", "reason": reason[:80]}))
        raise SystemExit(1)
