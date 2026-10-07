"""Server-owned FC27 Coins automation settings and price-write gates."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
from fractions import Fraction
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
    minimum = decimal_value(value["minimum_gross_margin_pct"], "minimum_margin", 2)
    if not 0 <= minimum < 100:
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
    if not 0 <= margin < 100:
        raise ValueError("minimum_margin_invalid")
    base = decimal_value(base_k, "base_k", 2)
    delivered = decimal_value(delivered_k, "delivered_k", 2)
    if base <= 0 or delivered < base:
        raise ValueError("automation_package_invalid")
    return (cost / rate * delivered / base / (Decimal(1) - margin / 100)).quantize(
        PRICE_STEP, rounding=ROUND_UP)


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
    if not 0 <= configured < 100:
        raise ValueError("minimum_margin_invalid")
    if Decimal(str(quote["result"]["minimum_gross_margin_pct"])) != configured:
        raise ValueError("automation_policy_changed_since_quote")
    if automatic and any(quote.get("edits", {}).get(name) for name in ("costs", "quotes", "offers")):
        raise ValueError("automation_manual_edits_present")
    rows = {row["platform"]: row for row in quote["result"]["rows"]}
    if len(rows) != len(PLATFORMS):
        raise ValueError("automation_quote_platform_invalid")
    rate = decimal_value(quote["evidence"]["fx"]["cny_per_usd"], "fx", 8)
    if rate <= 0:
        raise ValueError("fx_invalid")
    low_margin = []
    for platform in selected:
        row = rows[platform]
        price = decimal_value(row["proposal"], "proposal", 4)
        cost = decimal_value(row["cost_cny"], "cost", 8)
        if price <= 0 or cost <= 0 or row.get("missing"):
            raise ValueError("automation_quote_invalid")
        if row.get("auto_blocked_reason") and not row.get("quote_manual"):
            raise ValueError(("automatic_tier_unavailable:" if automatic else
                              "manual_quote_required:") + platform)
        if row.get("pricing_basis") == "page_total_100k":
            own = ((quote.get("evidence") or {}).get("storefront") or {}).get("rows", {}).get(platform) or {}
            base = decimal_value(own.get("base_k"), "base_k", 2)
            bonus = decimal_value(own.get("bonus_k"), "bonus_k", 2)
            if base != 100 or not 0 <= bonus <= 100:
                raise ValueError("automation_package_invalid")
            delivered = base + bonus
            floor = sale_floor(cost, rate, configured, base_k=base, delivered_k=delivered)
            page = price * base
            if Decimal(str(row.get("target_page_usd"))) != page:
                raise ValueError("automation_page_target_mismatch")
            follows_ps = (automatic and platform == "XBOX" and
                          quote["evidence"].get("game") == "FC27")
            if follows_ps:
                from fc27_quote_engine import calculate
                expected = calculate(quote["evidence"], {"minimum_gross_margin_pct": str(configured),
                                                         "pricing_rules": rules})
                expected_xbox = next(item for item in expected["rows"] if item["platform"] == "XBOX")
                if not expected_xbox.get("auto_proposal") or expected_xbox.get("auto_blocked_reason"):
                    raise ValueError("automatic_tier_unavailable:" + platform)
                if price != Decimal(expected_xbox["auto_proposal"]):
                    raise ValueError("automatic_tier_rule:" + platform)
            if automatic and price >= floor and not follows_ps:
                offers = quote["evidence"]["offers"][platform]
                lootbar_offer = offers["Lootbar"]
                if Decimal(str(lootbar_offer["base_k"])) != 100:
                    raise ValueError("automation_lootbar_package_invalid")
                lootbar_page = decimal_value(lootbar_offer["usd_price"], "lootbar_page", 4)
                lootbar_bonus = decimal_value(lootbar_offer.get("bonus_k", 0), "lootbar_bonus", 6)
                if not 0 <= lootbar_bonus <= 100:
                    raise ValueError("automation_lootbar_package_invalid")
                lootbar_unit = Fraction(lootbar_page) / Fraction(Decimal(100) + lootbar_bonus)
                before_page = decimal_value(own.get("package_usd"), "before_page", 2)
                before_margin = (Decimal(1) - cost / rate * delivered / before_page) * 100
                if lootbar_page != lootbar_page.quantize(Decimal("0.01")):
                    raise ValueError("automation_competitor_page_invalid")
                if before_margin >= 40:
                    gaps = []
                    for site in ("U4GM", "IGGM"):
                        offer = offers[site]
                        if Decimal(str(offer["base_k"])) != 100:
                            raise ValueError("automation_competitor_package_invalid")
                        other_page = decimal_value(offer["usd_price"], site + "_page", 4)
                        other_bonus = decimal_value(offer.get("bonus_k", 0), site + "_bonus", 6)
                        if not 0 <= other_bonus <= 100:
                            raise ValueError("automation_competitor_package_invalid")
                        if other_page != other_page.quantize(Decimal("0.01")):
                            raise ValueError("automation_competitor_page_invalid")
                        other_unit = Fraction(other_page) / Fraction(Decimal(100) + other_bonus)
                        gaps.append(max(Fraction(0), (lootbar_unit - other_unit) / lootbar_unit))
                    reduction = min(Fraction(1, 10), sum(gaps) / 2)
                elif before_margin >= 30:
                    reduction = Fraction(3, 40)
                elif before_margin >= 20:
                    reduction = Fraction(1, 20)
                else:
                    reduction = Fraction(0)
                tier = ("at_least_40" if before_margin >= 40 else "30_to_40" if before_margin >= 30
                        else "20_to_30" if before_margin >= 20 else "below_20")
                reduction = clamp_discount(reduction, tier, rules)
                preferred = lootbar_unit * (1 - reduction) * Fraction(base) * 100
                target_cents = -(-preferred.numerator // preferred.denominator)
                floor_cents = int((floor * 10000).to_integral_value())
                target_cents = max(target_cents, floor_cents)
                if page != Decimal(target_cents) / 100:
                    raise ValueError("automatic_tier_rule:" + platform)
        else:
            floor = sale_floor(cost, rate, configured)
        if price < floor:
            low_margin.append(platform)
    if low_margin and automatic:
        raise ValueError("automatic_margin_floor:" + ",".join(low_margin))
    if low_margin and (not set(low_margin).issubset(set(confirmed)) or not str(reason).strip()):
        raise ValueError("manual_margin_confirmation_required")
    return low_margin
