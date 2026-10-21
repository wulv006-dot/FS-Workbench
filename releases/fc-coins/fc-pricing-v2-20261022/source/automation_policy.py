"""Server-owned FC27 Coins automation settings and price-write gates."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
import json
import os
from pathlib import Path
import tempfile

from fc27_quote_engine import (normalize_discount_rules, discount_rules_sha256,
                               default_discount_rules, clamp_discount)


ROOT = Path("/var/lib/fc27-cloud")
POLICY_FILE = Path(os.environ.get("FC27_AUTOMATION_POLICY", str(ROOT / "config" / "automation.json")))
PLATFORMS = ("PS", "XBOX", "PC")
MAX_INTERVAL_MINUTES = 9999
DEFAULT_GROSS_MARGIN_PCT = Decimal("10")
PRICE_STEP = Decimal("0.0001")


def initial_policy():
    return {"revision": 0, "system_enabled": False, "mode": "manual",
            "interval_minutes": 60, "platforms": list(PLATFORMS),
            "minimum_gross_margin_pct": str(DEFAULT_GROSS_MARGIN_PCT),
            "pricing_rules": default_discount_rules(),
            "updated_at": None, "updated_by": None}


def decimal_value(value, name, max_places):
    if isinstance(value, bool) or value is None:
        raise ValueError(name + "_invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(name + "_invalid") from None
    if not number.is_finite() or number.as_tuple().exponent < -max_places:
        raise ValueError(name + "_invalid")
    return number


def normalize_policy(value, *, stored=False):
    if not isinstance(value, dict):
        raise ValueError("automation_policy_invalid")
    expected = {"system_enabled", "mode", "interval_minutes", "platforms",
                "minimum_gross_margin_pct"}
    metadata = {"revision", "updated_at", "updated_by"} if stored else set()
    optional = {"pricing_rules"} | ({"schedule_revision"} if stored else set())
    if not expected | metadata <= set(value) or set(value) - (expected | metadata | optional):
        raise ValueError("automation_policy_fields_invalid")
    if (type(value["system_enabled"]) is not bool or type(value["mode"]) is not str
            or value["mode"] not in {"manual", "auto"}):
        raise ValueError("automation_policy_mode_invalid")
    if (type(value["interval_minutes"]) is not int
            or not 1 <= value["interval_minutes"] <= MAX_INTERVAL_MINUTES):
        raise ValueError("automation_interval_invalid")
    platforms = value["platforms"]
    if (not isinstance(platforms, list) or any(type(p) is not str for p in platforms)
            or len(platforms) != len(set(platforms))
            or any(platform not in PLATFORMS for platform in platforms)):
        raise ValueError("automation_platforms_invalid")
    if bool(set(platforms)&{'PS','XBOX'}) and not {'PS','XBOX'}<=set(platforms):
        raise ValueError('pricing_common_console_scope_required')
    minimum = decimal_value(value["minimum_gross_margin_pct"], "minimum_margin", 2)
    if not DEFAULT_GROSS_MARGIN_PCT <= minimum < 100:
        raise ValueError("minimum_margin_invalid")
    clean = {"system_enabled": value["system_enabled"], "mode": value["mode"],
             "interval_minutes": value["interval_minutes"],
             "platforms": [p for p in PLATFORMS if p in platforms],
             "minimum_gross_margin_pct": str(minimum),
             "pricing_rules": normalize_discount_rules(value.get("pricing_rules"))}
    if stored:
        if type(value["revision"]) is not int or value["revision"] < 0:
            raise ValueError("automation_revision_invalid")
        clean.update({key: value[key] for key in metadata})
        if "schedule_revision" in value:
            if type(value["schedule_revision"]) is not int or not 0 <= value["schedule_revision"] <= value["revision"]:
                raise ValueError("automation_schedule_revision_invalid")
            clean["schedule_revision"] = value["schedule_revision"]
    return clean


def load_policy():
    if not POLICY_FILE.exists():
        return initial_policy()
    return normalize_policy(json.loads(POLICY_FILE.read_text(encoding="utf-8")), stored=True)


def save_policy(value, actor, expected_revision, *, discount_rules=None):
    if not isinstance(actor, str) or not actor or len(actor) > 60:
        raise ValueError("automation_actor_invalid")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("automation_revision_invalid")
    rules_only = discount_rules is not None
    rules = normalize_discount_rules(discount_rules) if rules_only else None
    clean = None if rules_only else normalize_policy(value)
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    import fcntl  # Linux service; imported here so policy validation also runs on Windows.
    lock = POLICY_FILE.with_suffix(".lock")
    with lock.open("a+b") as stream:
        os.chmod(lock, 0o660)
        fcntl.flock(stream, fcntl.LOCK_EX)
        current = load_policy()
        if current["revision"] != expected_revision:
            raise ValueError("automation_revision_changed")
        if rules_only:
            if Decimal(current["minimum_gross_margin_pct"]) < 10:
                raise ValueError("automation_discount_margin_floor_invalid")
            if current["pricing_rules"] == rules:
                return current  # Duplicate default/identical save is a read-only no-op.
            # tick() holds this same policy lock while checking/enqueuing a cycle.
            # Reject a rule change during an active Coins job rather than invalidate it midway.
            for folder in ("queue", "jobs"):
                for path in (ROOT / folder).glob("*.json"):
                    job = json.loads(path.read_text(encoding="utf-8"))
                    if job.get("kind") != "player_sync" and job.get("status") in {"queued", "running"}:
                        raise ValueError("automation_discount_cycle_in_progress")
            clean = {key: current[key] for key in ("system_enabled", "mode", "interval_minutes",
                                                   "platforms", "minimum_gross_margin_pct")}
            clean["pricing_rules"] = rules
        elif "pricing_rules" not in value:
            clean["pricing_rules"] = current["pricing_rules"]
        clean["schedule_revision"] = (current.get("schedule_revision", current["revision"])
                                      if rules_only else expected_revision + 1)
        previous = POLICY_FILE.read_bytes() if POLICY_FILE.exists() else None
        clean.update({"revision": expected_revision + 1,
                      "updated_at": datetime.now(timezone.utc).isoformat(),
                      "updated_by": actor})
        audit_path = POLICY_FILE.parent / "automation-events.jsonl"
        # Open the audit stream before publishing the new policy. A permission
        # error must leave the previous revision in place.
        with audit_path.open("a", encoding="utf-8") as audit:
            audit_start = audit_path.stat().st_size
            published = False
            os.chmod(audit_path, 0o660)
            fd, temp = tempfile.mkstemp(dir=POLICY_FILE.parent, prefix=".automation-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(clean, output, ensure_ascii=False, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temp, 0o640)
                os.replace(temp, POLICY_FILE)
                published = True
                audit.write(json.dumps({"at": clean["updated_at"], "actor": actor,
                                        "revision": clean["revision"], "before": current,
                                        "after": clean}, ensure_ascii=False) + "\n")
                audit.flush()
                os.fsync(audit.fileno())
            except Exception:
                # New range saves restore the prior running policy if audit append fails.
                # This is failure recovery under the same lock, not a two-file ACID claim.
                if rules_only and published:
                    if previous is None:
                        POLICY_FILE.unlink()
                    else:
                        restore_fd, restore_path = tempfile.mkstemp(dir=POLICY_FILE.parent,
                                                                    prefix=".automation-restore-")
                        try:
                            with os.fdopen(restore_fd, "wb") as restore:
                                restore.write(previous)
                                restore.flush()
                                os.fsync(restore.fileno())
                            os.chmod(restore_path, 0o640)
                            os.replace(restore_path, POLICY_FILE)
                        finally:
                            if os.path.exists(restore_path):
                                os.unlink(restore_path)
                    audit.flush()
                    os.truncate(audit_path, audit_start)
                raise
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
    return clean


def save_discount_rules(rules, actor, expected_revision):
    if rules is None:
        raise ValueError("automation_discount_rules_invalid")
    return save_policy(None, actor, expected_revision, discount_rules=rules)


def sale_floor(cost_cny, cny_per_usd, minimum_gross_margin_pct,
               *, base_k=100, delivered_k=100):
    """Minimum backend USD/K; delivered coins include the public page bonus."""
    cost = decimal_value(cost_cny, "cost", 8)
    rate = decimal_value(cny_per_usd, "fx", 8)
    margin = decimal_value(minimum_gross_margin_pct, "minimum_margin", 2)
    if cost <= 0 or rate <= 0:
        raise ValueError("automation_cost_or_fx_invalid")
    if not DEFAULT_GROSS_MARGIN_PCT <= margin < 100:
        raise ValueError("minimum_margin_invalid")
    base = decimal_value(base_k, "base_k", 2)
    delivered = decimal_value(delivered_k, "delivered_k", 2)
    if base <= 0 or delivered < base:
        raise ValueError("automation_package_invalid")
    return (cost / rate * delivered / base / (Decimal(1) - margin / 100)).quantize(
        PRICE_STEP, rounding=ROUND_UP)


def required_offer(offers, site):
    offer = offers.get(site) if isinstance(offers, dict) else None
    if not isinstance(offer, dict) or not offer:
        raise ValueError("automation_source_incomplete:" + site)
    if any(key not in offer for key in ("base_k", "usd_price")):
        raise ValueError("automation_source_incomplete:" + site)
    if not bool(offer.get("comparable", not offer.get("conditional", False))):
        raise ValueError("automation_source_incomplete:" + site)
    return offer


def pricing_reference_sites(offers):
    available = []
    for site in ("U4GM", "IGGM", "U7Buy"):
        try:
            offer = required_offer(offers, site)
            price = decimal_value(offer["usd_price"], "reference_price", 4)
            base = decimal_value(offer["base_k"], "reference_base", 4)
            bonus = decimal_value(offer.get("bonus_k", 0), "reference_bonus", 6)
            if price > 0 and price == price.quantize(Decimal("0.01")) and base == 100 and 0 <= bonus <= 100:
                available.append(site)
        except (ValueError, KeyError, TypeError):
            continue
    primary = [site for site in ("U4GM", "IGGM") if site in available]
    references = primary or (["U7Buy"] if "U7Buy" in available else [])
    return references


def check_write(policy, quote, selected, *, automatic=False, confirmed=(), reason=""):
    """Recompute purchase margin from evidence before any normal price write."""
    if not policy["system_enabled"]:
        raise ValueError("automation_system_off")
    if automatic and policy["mode"] != "auto":
        raise ValueError("automation_mode_changed")
    if quote.get("automation_policy_revision") != policy["revision"]:
        raise ValueError("automation_policy_changed_since_quote")
    rules = normalize_discount_rules(policy.get("pricing_rules"))
    if quote.get("pricing_rules") is not None:
        if (quote.get("pricing_rules_schema_version") != 1
                or normalize_discount_rules(quote["pricing_rules"]) != rules
                or quote.get("pricing_rules_sha256") != discount_rules_sha256(rules)
                or normalize_discount_rules(quote.get("edits", {}).get("pricing_rules")) != rules):
            raise ValueError("automation_policy_changed_since_quote")
    elif rules != default_discount_rules() or quote.get("edits", {}).get("pricing_rules") is not None:
        raise ValueError("automation_policy_changed_since_quote")
    if not selected or any(p not in policy["platforms"] for p in selected):
        raise ValueError("automation_platform_disabled")
    configured = decimal_value(policy["minimum_gross_margin_pct"], "minimum_margin", 2)
    if not DEFAULT_GROSS_MARGIN_PCT <= configured < 100:
        raise ValueError("minimum_margin_invalid")
    if Decimal(str(quote["result"]["minimum_gross_margin_pct"])) != configured:
        raise ValueError("automation_policy_changed_since_quote")
    if automatic and (any(quote.get("edits", {}).get(name) for name in ("costs", "offers")) or
                      quote.get('edits',{}).get('quotes') and not quote.get('hermes_decision')):
        raise ValueError("automation_manual_edits_present")
    if quote['result'].get('decision_receipt'):
        from pricing_v2 import verify_quote, envelope_ratio
        current = json.loads((POLICY_FILE.parent / 'pricing-inputs.json').read_text('utf-8'))
        envelope_ratio(current, datetime.now(timezone.utc))
        if current['sha256'] != quote['evidence']['promotion_envelope']['sha256']:
            raise ValueError('pricing_promotions_changed_since_quote')
        verify_quote(quote,policy,selected,for_execution=True)
        return []
    raise ValueError('pricing_legacy_quote_requires_recollection')

def hooks_before_write(policy, selected, automatic=False, current_quote=None):
    """Read the independent, root-owned control immediately before automatic dispatch."""
    if not automatic:
        return
    import stat
    path = Path('/var/lib/fc-ops-readonly-monitor/gates/control.json')
    try:
        meta = path.lstat()
        parent = path.parent.lstat()
        if (not stat.S_ISREG(meta.st_mode) or stat.S_ISLNK(parent.st_mode)
                or meta.st_size > 32768 or meta.st_nlink != 1
                or (os.name == 'posix' and (meta.st_uid != 0 or parent.st_uid != 0
                    or meta.st_mode & 0o022 or parent.st_mode & 0o022))):
            raise ValueError('hook_control_untrusted')
        control = json.loads(path.read_text(encoding='utf-8'))
        now = datetime.now(timezone.utc)
        observed = datetime.fromisoformat(control['observed_at'])
        expiry = datetime.fromisoformat(control['valid_until'])
        if (control.get('schema_version') != 1 or control.get('module_id') != 'fc-coins'
                or control.get('mode') != 'RULES_ARMED' or control.get('user_intent') != 'ENABLED'
                or not policy.get('system_enabled') or policy.get('mode') != 'auto'
                or control.get('policy_revision') != policy.get('revision')
                or not -60 <= (now-observed).total_seconds() <= 900
                or not 0 < (expiry-now).total_seconds() <= 960):
            raise ValueError('hook_control_stale_or_changed')
        if not selected:
            raise ValueError('hook_scope_paused')
        paused = [control['platforms'][p] for p in selected if control['platforms'][p]['reasons']]
        if paused:
            # Only fresh, authorized cycle evidence may supersede an older collection-age alarm.
            if current_quote is None or control.get('unknown_operations') != []:
                raise ValueError('hook_scope_paused')
            bases = []
            for scope in paused:
                basis = (scope.get('recovery_from') or {}) if scope['reasons'] == ['recovery_confirmation_pending'] else {
                    'reasons':scope['reasons'], 'observed_at':control['observed_at']}
                if scope.get('pause_source') != 'system_fault' or basis.get('reasons') != ['collection_stale_or_clock_invalid']:
                    raise ValueError('hook_scope_paused')
                bases.append(datetime.fromisoformat(basis['observed_at']))
            quote = current_quote()  # Writer reuses immutable preview/run/quote and newest-run checks.
            checked = datetime.fromisoformat(quote['evidence']['checked_at'].replace('Z', '+00:00'))
            if not 0 <= (now-checked).total_seconds() <= 900 or any(checked <= basis for basis in bases):
                raise ValueError('hook_scope_paused')
    except (OSError, KeyError, TypeError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('hook_') else 'hook_control_unavailable'
        raise ValueError(code) from None
