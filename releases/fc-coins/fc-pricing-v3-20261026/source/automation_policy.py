"""Server-owned FC27 Coins automation settings and price-write gates."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
import json
import os
from pathlib import Path
import tempfile



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
             "minimum_gross_margin_pct": str(minimum)}
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
    if discount_rules is not None:raise ValueError('pricing_legacy_bands_retired_use_v3_parameters')
    clean=normalize_policy(value)
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    import fcntl  # Linux service; imported here so policy validation also runs on Windows.
    lock = POLICY_FILE.with_suffix(".lock")
    with lock.open("a+b") as stream:
        os.chmod(lock, 0o660)
        fcntl.flock(stream, fcntl.LOCK_EX)
        current = load_policy()
        if current["revision"] != expected_revision:
            raise ValueError("automation_revision_changed")
        clean['schedule_revision']=expected_revision+1
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
                if published:
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


def save_discount_rules(*args,**kwargs):
    raise ValueError('pricing_legacy_bands_retired_use_v3_parameters')


def check_write(policy, quote, selected, *, automatic=False, confirmed=(), reason=""):
    """Recompute purchase margin from evidence before any normal price write."""
    if not policy["system_enabled"]:
        raise ValueError("automation_system_off")
    if automatic and policy["mode"] != "auto":
        raise ValueError("automation_mode_changed")
    if quote.get("automation_policy_revision") != policy["revision"]:
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

def hooks_before_write(policy,selected,automatic=False,current_quote=None):
    if current_quote is None:
        raise ValueError('pricing_v3_current_quote_required')
    from fc_pricing_v3.runtime import verify_quote
    scope=['PS','XBOX'] if set(selected)&{'PS','XBOX'} and set(selected)<={'PS','XBOX'} else selected
    quote=current_quote()
    verify_quote(quote,policy,scope,for_execution=True,purpose=(quote['result'].get('decision_receipt') or {}).get('authorization_purpose'))


