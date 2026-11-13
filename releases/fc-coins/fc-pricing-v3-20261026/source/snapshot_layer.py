"""Normalize one server-only FC27 collection run; never reuse older evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import glob
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from fc27_quote_engine import source_coverage


PLATFORMS = ("PS", "XBOX", "PC")
SITES = ("Lootbar",)
LOOTBAR_URL = "https://www.lootbar.com/game-coins/fc27"
ROOT = Path("/var/lib/fc27-cloud")
COLLECTOR = Path("/opt/fc27-cloud-browser/collect_lootbar.sh")
PUBLIC_COLLECTOR = Path("/opt/fc27-cloud-browser/collect_competitor.sh")
COST_COLLECTOR = Path("/opt/fc27-cloud-browser/collect_p2pah_cost.sh")
FX_COLLECTOR = Path("/opt/fc27-cloud-browser/collect_fx.sh")


def positive(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError("invalid_numeric_field") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("invalid_numeric_field")
    return number


def lootbar_snapshots(run_id: str, events: list[dict]) -> list[dict]:
    last = events[-1] if events else {}
    if last.get('stage') == 'remote_complete':
        if (last.get('read_only') is not True or last.get('node_id') != '183'
                or last.get('run_id') != run_id or last.get('source_receipt_verified') is not True
                or not isinstance(last.get('offers'), list) or not last['offers']):
            raise ValueError('remote_lootbar_receipt_invalid')
        rows = last['offers']
        seen = set()
        for row in rows:
            if (row.get('source') != 'Lootbar' or row.get('run_id') != run_id or row.get('status') != 'valid'
                    or row.get('platform') not in PLATFORMS or row['platform'] in seen
                    or row.get('currency') != 'USD' or row.get('selection_verified') is not True
                    or row.get('coupon_excluded') is not True or row.get('auth_state') not in ('public','logged_in')
                    or not row.get('source_metadata') or not row.get('observation_id')):
                raise ValueError('remote_lootbar_offer_invalid')
            captured = datetime.fromisoformat(row['captured_at'].replace('Z','+00:00'))
            if captured.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-captured).total_seconds() <= 900:
                raise ValueError('stale_capture')
            positive(row['gross_usd']); positive(row['purchase_k'])
            seen.add(row['platform'])
        return rows + [r for r in missing_competitors(run_id, 'remote_platform_quote_missing') if r['platform'] not in seen]
    if (last.get("stage") != "complete" or last.get("read_only") is not True
            or not any(event.get("stage") == "ps_restored" for event in events)):
        raise ValueError("collector_incomplete")
    offers = last.get("offers") or {}
    if set(offers) != set(PLATFORMS):
        raise ValueError("platform_coverage_incomplete")
    captured_at = last.get("checked_at")
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError("invalid_capture_time") from None
    if captured.tzinfo is None or abs((datetime.now(timezone.utc) - captured).total_seconds()) > 3600:
        raise ValueError("stale_capture")
    rows = []
    for platform in PLATFORMS:
        offer = offers[platform]
        if offer.get("platform") != platform:
            raise ValueError("platform_or_coupon_mismatch")
        gross = positive(offer.get("usd_price"))
        coupon_excluded = offer.get('coupon_excluded')
        if type(coupon_excluded) is not bool:
            raise ValueError('platform_or_coupon_mismatch')
        # The legacy bool means whether exclusion was needed, not whether the price is usable.
        if coupon_excluded:
            paid = positive(offer.get('observed_coupon_price'))
            discount = positive(offer.get('excluded_coupon_discount'))
            if gross-paid != discount:
                raise ValueError('coupon_reconstruction_mismatch')
        elif (offer.get('observed_coupon_price') is not None or offer.get('excluded_coupon_discount') is not None
                or offer.get('price_basis') not in (None,'当前无券商品价')):
            raise ValueError('coupon_reconstruction_unverified')
        purchase = positive(offer.get("base_k"))
        if purchase != 100:
            raise ValueError("unexpected_package_size")
        try:
            bonus = Decimal(str(offer.get("bonus_k")))
        except (InvalidOperation, TypeError):
            raise ValueError("invalid_bonus") from None
        if not bonus.is_finite() or bonus < 0:
            raise ValueError("invalid_bonus")
        rows.append({
            "run_id": run_id, "source": "Lootbar", "platform": platform,
            "captured_at": captured_at, "url": LOOTBAR_URL, "currency": "USD",
            "purchase_k": str(purchase), "bonus_k": str(bonus),
            "gross_usd": str(gross),
            "effective_usd_per_k": str(gross / (purchase + bonus)),
            "coupon_excluded": True, "raw_coupon_excluded": coupon_excluded, "auth_state": "logged_in",
            "price_basis": "visible_public_sale_price", "discount_source": "visible_coupon_excluded" if coupon_excluded else "visible_no_coupon",
            "source_metadata": {k:offer[k] for k in ('price_basis','reconstruction','observed_coupon_price','excluded_coupon_discount') if k in offer},
            "status": "valid", "reason": None,
        })
    return rows


def missing_competitors(run_id: str, reason: str) -> list[dict]:
    return [{"run_id": run_id, "source": source, "platform": platform,
             "status": "missing", "reason": reason}
            for source in SITES for platform in PLATFORMS]


def public_snapshots(run_id: str, source: str, payload: dict) -> list[dict]:
    if 'quantity_scope' in payload:
        from fc_pricing_v3.competitor_offers import normalize_offers, quantities
        if source!='U7Buy' or payload.get('source')!=source or payload.get('status')!='valid':
            raise ValueError('quantity_collector_contract')
        scope=quantities(payload['quantity_scope'])
        rows=payload.get('offers')
        if not isinstance(rows,list) or any(r.get('source')!=source or str(r.get('purchase_k')) not in scope for r in rows):
            raise ValueError('quantity_collector_scope')
        return normalize_offers(rows,run_id,datetime.now(timezone.utc))
    if payload.get("source") != source or payload.get("status") != "valid":
        raise ValueError("collector_incomplete")
    rows = payload.get("offers") or []
    if [row.get("platform") for row in rows] != list(PLATFORMS):
        raise ValueError("platform_coverage_incomplete")
    result = []
    for row in rows:
        if (row.get("source") != source or row.get("status") != "valid"
                or row.get("currency") != "USD" or row.get("purchase_k") != "100"):
            raise ValueError("offer_contract_mismatch")
        try:
            captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
            bonus = Decimal(str(row["bonus_k"]))
            effective = Decimal(str(row["effective_usd_per_k"]))
        except (KeyError, InvalidOperation, ValueError, TypeError):
            raise ValueError("offer_value_invalid") from None
        if (captured.tzinfo is None or abs((datetime.now(timezone.utc) - captured).total_seconds()) > 3600
                or not bonus.is_finite() or bonus < 0
                or effective != positive(row.get("gross_usd")) / (Decimal(100) + bonus)):
            raise ValueError("offer_value_invalid")
        result.append({**row, "run_id": run_id})
    return result


def cost_snapshots(run_id: str, payload: dict) -> list[dict]:
    if payload.get("status") != "valid":
        raise ValueError("cost_collector_incomplete")
    rows = payload.get("costs") or []
    if [row.get("platform") for row in rows] != list(PLATFORMS):
        raise ValueError("cost_platform_coverage_incomplete")
    result = []
    for row in rows:
        if row.get("genre") != "1" or row.get("delivery_type") != "\u8ba2\u5355\u53d1\u8d27":
            raise ValueError("cost_delivery_type_unverified")
        if (row.get("status") != "valid" or row.get("game") != "FC27"
                or row.get("product") != "Game Coins" or row.get("unit") != "CNY/K"
                or not str(row.get("record_id", "")).isdigit() or not row.get("trade_at")):
            raise ValueError("cost_contract_mismatch")
        positive(row.get("cny_per_1k"))
        try:
            checked = datetime.fromisoformat(row["checked_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, AttributeError):
            raise ValueError("cost_capture_invalid") from None
        if checked.tzinfo is None or abs((datetime.now(timezone.utc) - checked).total_seconds()) > 3600:
            raise ValueError("cost_capture_stale")
        result.append({**row, "run_id": run_id})
    from fc_pricing_v3.financial import common_cost
    common_cost({'costs': {row['platform']: row for row in result}})
    return result


def newest_evidence(pattern: str, before: set[str]) -> dict:
    after = set(glob.glob(str(ROOT / "evidence" / pattern))) - before
    if len(after) != 1:
        raise ValueError("evidence_file_ambiguous")
    return json.loads(Path(after.pop()).read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: dict):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def collector_failure(pattern, before, source):
    """Read only this invocation's new evidence; never use an older result."""
    try:
        after = set(glob.glob(str(ROOT / "evidence" / pattern))) - before
        if len(after) != 1:
            return "collector_failed"
        path = Path(after.pop())
        if source == "Lootbar":
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            primary = next((x for x in events if x.get("stage") == "primary_failed"), {})
            reason = primary.get("reason_code")
            if reason in ("platform_timeout", "platform_collection_failed"):
                platform = primary.get("platform")
                return reason + (":" + platform if platform in PLATFORMS else "")
            if any(x.get("stage") == "ps_restore_failed" for x in events):
                return "ps_restore_failed"
            payload = events[-1] if events else {}
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
        reason = payload.get("reason")
        if isinstance(reason, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:,.-]{0,119}", reason):
            return reason
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return "collector_failed"


def collect_once(run_id=None, competitor_policy=None):
    from fc_pricing_v3.competitor_offers import POLICY, QUANTITIES, normalize_offers, quantity_coverage
    if competitor_policy not in (None,POLICY):raise ValueError('competitor_policy_unknown')
    run_id = run_id or str(uuid.uuid4())
    if str(uuid.UUID(run_id)) != run_id:
        raise ValueError("invalid_run_id")
    started = datetime.now(timezone.utc).isoformat()
    snapshots = missing_competitors(run_id, "collector_not_connected")
    status, reason = "incomplete", None
    failures = []
    before = {p for p in glob.glob(str(ROOT / "evidence/lootbar-*.jsonl"))}
    try:
        result = subprocess.run([str(COLLECTOR), run_id], capture_output=True, timeout=230)
        if result.returncode:
            failures.append("Lootbar:" + collector_failure("lootbar-*.jsonl", before, "Lootbar"))
        else:
            after = set(glob.glob(str(ROOT / "evidence/lootbar-*.jsonl"))) - before
            if len(after) != 1:
                raise ValueError("evidence_file_ambiguous")
            path = Path(after.pop())
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            valid = lootbar_snapshots(run_id, events)
            snapshots = [row for row in snapshots if row["source"] != "Lootbar"] + valid
            reason = "cost_not_connected"
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        failures.append("Lootbar:" + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
    quantity_offers=[]
    if competitor_policy==POLICY:
        for row in snapshots:
            if row.get('status')!='valid':continue
            try:quantity_offers.extend(normalize_offers([row],run_id,datetime.now(timezone.utc)))
            except ValueError as exc:failures.append('Lootbar:'+str(exc))
        before=set(glob.glob(str(ROOT/'evidence/U7Buy-*.json')))
        try:
            process=subprocess.run([str(PUBLIC_COLLECTOR),'U7Buy',','.join(QUANTITIES)],capture_output=True,timeout=100)
            if process.returncode:raise ValueError(collector_failure('U7Buy-*.json',before,'U7Buy'))
            payload=newest_evidence('U7Buy-*.json',before)
            quantity_offers.extend(public_snapshots(run_id,'U7Buy',payload))
        except (OSError,ValueError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
            failures.append('U7Buy:'+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
    reason = "cost_not_connected" if not failures else ";".join(failures)
    costs = [{"run_id": run_id, "platform": platform, "status": "missing",
              "reason": "cost_collector_failed"} for platform in PLATFORMS]
    before = set(glob.glob(str(ROOT / "evidence/p2pah-cost-*.json")))
    cost_failure = None
    try:
        process = subprocess.run([str(COST_COLLECTOR)], capture_output=True, timeout=185)
        if process.returncode:
            try:
                report = json.loads(process.stdout.splitlines()[-1])
                reported = report.get('reason')
                if (report.get('source') == 'P2PAH' and isinstance(reported, str)
                        and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_:,.-]{0,119}', reported)):
                    cost_failure = {k:report[k] for k in ('reason','diagnostic','evidence_file') if k in report}
            except (ValueError,IndexError,AttributeError,TypeError):
                pass
            raise ValueError(cost_failure['reason'] if cost_failure else "collector_failed")
        costs = cost_snapshots(run_id, newest_evidence("p2pah-cost-*.json", before))
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        failures.append("P2PAH:" + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
    fx = {"status": "missing", "reason": "fx_collector_failed"}
    before = set(glob.glob(str(ROOT / "evidence/fx-*.json")))
    try:
        process = subprocess.run([str(FX_COLLECTOR)], capture_output=True, timeout=55)
        if process.returncode:
            raise ValueError(collector_failure("fx-*.json", before, "BOC"))
        fx = newest_evidence("fx-*.json", before)
        if fx.get("status") != "valid" or not fx.get("checked_at"):
            raise ValueError("fx_contract_mismatch")
        positive(fx.get("cny_per_usd"))
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        failures.append("BOC:" + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
        fx = {"status": "missing", "reason": "fx_collector_failed"}
    valid_count = sum(x["status"] == "valid" for x in snapshots)
    cost_count = sum(x["status"] == "valid" for x in costs)
    coverage = dict(ready=True,required_sources=[],optional_sources=['Lootbar'],
                    pricing_source_policy='current_available_quote_or_100k_margin_floor')
    if competitor_policy==POLICY:coverage=quantity_coverage(quantity_offers)
    source_warnings = [failure for failure in failures
                       if failure.split(":", 1)[0] in ("Lootbar", "IGGM", "U4GM", "U7Buy")]
    for row in snapshots:
        if row["status"] == "missing":
            row["reason"] = next((failure for failure in failures
                                  if failure.startswith(row["source"] + ":")), row["reason"])
    complete = coverage["ready"] and cost_count == 3 and fx["status"] == "valid"
    status = "ready_for_quote" if complete else "incomplete"
    reason = None if complete else ";".join(failures) or "required_evidence_missing"
    payload = {"run_id": run_id, "created_at": started, "status": status,
               "reason": reason, "competitors": snapshots, "costs": costs,
               "fx": fx, "quote_status": "PENDING" if complete else "NO_QUOTE",
               "source_coverage": coverage, "source_warnings": source_warnings}
    if competitor_policy==POLICY:
        payload.update(competitor_policy=POLICY,competitor_offers=quantity_offers,
            legacy_competitor_scope='100k_observed_only')
    if cost_failure is not None:
        payload['cost_failure'] = cost_failure
    run_path = ROOT / "runs" / f"{run_id}.json"
    atomic_json(run_path, payload)
    os.chown(run_path.parent, -1, 11028)
    os.chmod(run_path.parent, 0o750)
    os.chown(run_path, -1, 11028)
    os.chmod(run_path, 0o640)
    summary = {"run_id": run_id, "status": status, "reason": reason,
               "valid_competitors": valid_count, "valid_costs": cost_count,
               "fx_status": fx["status"], "quote_status": payload["quote_status"],
               "source_coverage": coverage, "source_warnings": source_warnings}
    if cost_failure is not None:
        summary['cost_failure'] = cost_failure
    return summary, complete


if __name__ == "__main__":
    import fcntl  # Linux collection lock; keep read-only validation importable on Windows.
    lock_path = ROOT / "state" / "snapshot.lock"
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "busy", "quote_status": "NO_QUOTE"}))
            sys.exit(75)
        summary, success = collect_once(sys.argv[1] if len(sys.argv) > 1 else None,
            sys.argv[2] if len(sys.argv)>2 else None)
        print(json.dumps(summary))
        sys.exit(0 if success else 1)
