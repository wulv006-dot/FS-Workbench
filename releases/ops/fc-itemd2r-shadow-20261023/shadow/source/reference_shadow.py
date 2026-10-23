"""Read-only reference-tier research. Never import this into production pricing."""
from decimal import Decimal, InvalidOperation
from datetime import datetime
from urllib.parse import urlsplit

SOURCE_TIERS = {
    "core": ("Lootbar",),
    "second": ("U7Buy", "ItemD2R"),
    "third": ("IGGM", "U4GM"),
}
PLATFORMS = ("PS", "XBOX", "PC")
SITES = tuple(site for sites in SOURCE_TIERS.values() for site in sites)
LEGACY_SITES = tuple(site for site in SITES if site != "ItemD2R")
SOURCE_DOMAINS = {"Lootbar": "lootbar.com", "U7Buy": "u7buy.com", "ItemD2R": "itemd2r.com",
                  "IGGM": "iggm.com", "U4GM": "u4gm.com"}
EXPERIMENTAL_ANCHOR_WEIGHTS = (Decimal("0.6"), Decimal("0.7"), Decimal("0.8"))
EXPERIMENTAL_REFERENCE_SCORES = {"second": Decimal(2), "third": Decimal(1)}


def shadow_reference_sites(available):
    """Prefer the highest available tier; never invent cross-tier percentages."""
    available = set(available)
    for tier in ("second", "third"):
        selected = [site for site in SOURCE_TIERS[tier] if site in available]
        if selected:
            return tier, selected
    return None, []


def _observation(row):
    site = row["source"]
    tier = next(tier for tier, sites in SOURCE_TIERS.items() if site in sites)
    value = {"tier": tier, "comparable": False, "usd_per_k": None}
    if row["status"] != "valid":
        return dict(value, reason="source_missing")
    if row.get("conditional") or row.get("comparable", True) is not True:
        return dict(value, reason="conditional_or_noncomparable")
    if row.get("currency") != "USD":
        return dict(value, reason="currency_not_usd")
    if "url" in row:
        try:
            host = urlsplit(row["url"]).hostname or ""
            if host != SOURCE_DOMAINS[site] and not host.endswith("."+SOURCE_DOMAINS[site]):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            return dict(value, reason="source_url_identity_mismatch")
    try:
        if any(isinstance(row.get(key), bool) for key in ("gross_usd", "purchase_k", "bonus_k")):
            raise ValueError()
        price = Decimal(str(row["gross_usd"]))
        base = Decimal(str(row["purchase_k"]))
        bonus = Decimal(str(row.get("bonus_k", 0)))
        if (not all(number.is_finite() for number in (price, base, bonus))
                or price <= 0 or base != 100 or not 0 <= bonus <= 100
                or price != price.quantize(Decimal("0.01"))):
            raise ValueError()
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return dict(value, reason="invalid_price_or_100k_package")
    return dict(value, comparable=True, usd_per_k=str(price/(base+bonus)),
                delivered_k=str(base+bonus), reason="observed_package_normalized")


def simulate_reference_tiers(rows):
    """Classify one complete 12/15-row observation; produce no sale-price proposal."""
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("shadow_rows_required")
    sites = LEGACY_SITES if len(rows) == 12 else SITES if len(rows) == 15 else ()
    expected = {(platform, site) for platform in PLATFORMS for site in sites}
    if any(not isinstance(row.get("platform"), str) or not isinstance(row.get("source"), str) for row in rows):
        raise ValueError("shadow_competitor_coverage_invalid")
    keys = [(row.get("platform"), row.get("source")) for row in rows]
    if (not expected or len(set(keys)) != len(keys) or set(keys) != expected
            or any(not isinstance(row.get("status"), str) or row["status"] not in {"valid", "missing"} for row in rows)):
        raise ValueError("shadow_competitor_coverage_invalid")
    if not all(isinstance(row.get("run_id"), str) and row["run_id"] for row in rows):
        raise ValueError("shadow_same_original_run_required")
    runs = {row["run_id"] for row in rows}
    if len(runs) != 1:
        raise ValueError("shadow_same_original_run_required")
    if any(row.get("game", "FC27") != "FC27" or row.get("product", "Game Coins") != "Game Coins" for row in rows):
        raise ValueError("shadow_product_identity_invalid")
    observations = {platform: {} for platform in PLATFORMS}
    for row in rows:
        observations[row["platform"]][row["source"]] = _observation(row)
    references, selected_tiers = {}, {}
    for platform, offers in observations.items():
        tier, selected = shadow_reference_sites(site for site, offer in offers.items() if offer["comparable"])
        references[platform], selected_tiers[platform] = selected, tier
    return {
        "schema_version": 1, "simulation_only": True, "business_effect": "none",
        "production_strategy_changed": False, "run_id": next(iter(runs)),
        "input_schema": "legacy_12" if len(rows) == 12 else "five_site_15",
        "source_tiers": {tier: list(sites) for tier, sites in SOURCE_TIERS.items()},
        "selection_rule": "highest_available_reference_tier_only",
        "observations": observations, "reference_sources": references,
        "selected_reference_tiers": selected_tiers,
        "shadow_core_comparable": all(observations[p]["Lootbar"]["comparable"] for p in PLATFORMS),
        "weight_percentages": None,
    }


def _time_problem(stamp, now, maximum_age):
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if observed.utcoffset() is None:
            return "timestamp_timezone_missing"
        age = (now-observed).total_seconds()
        return "timestamp_future" if age < 0 else "timestamp_stale" if age > maximum_age else None
    except (AttributeError, TypeError, ValueError):
        return "timestamp_invalid"


def _storefront_unit(storefront, platform, run_id, now, maximum_age):
    if not isinstance(storefront, dict):
        return None, "storefront_unavailable"
    if (storefront.get("currency") != "USD" or storefront.get("collection_run_id") != run_id
            or storefront.get("status") != "ok"):
        return None, "storefront_identity_unverified"
    rows = storefront.get("rows")
    row = rows.get(platform) if isinstance(rows, dict) else None
    if not isinstance(row, dict) or row.get("platform") != platform or row.get("status") != "ok":
        return None, "storefront_platform_unverified"
    if row.get("conditional") or row.get("comparable", True) is not True or row.get("currency", "USD") != "USD":
        return None, "storefront_noncomparable"
    timing = _time_problem(row.get("checked_at"), now, maximum_age)
    if timing:
        return None, "storefront_"+timing
    try:
        if any(isinstance(row.get(key), bool) for key in ("package_usd", "base_k", "bonus_k")):
            raise ValueError()
        price, base, bonus = (Decimal(str(row.get(key, 0))) for key in ("package_usd", "base_k", "bonus_k"))
        if (not all(n.is_finite() for n in (price, base, bonus)) or price <= 0 or base != 100
                or not 0 <= bonus <= 100 or price != price.quantize(Decimal("0.01"))):
            raise ValueError()
        return price/(base+bonus), None
    except (InvalidOperation, TypeError, ValueError):
        return None, "storefront_package_invalid"


def experimental_scenarios(rows, *, now, storefront=None, maximum_age_seconds=900):
    """Illustrative weight experiments only; neither user-set rules nor sale prices."""
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("shadow_aware_now_required")
    if type(maximum_age_seconds) is not int or not 0 < maximum_age_seconds <= 900:
        raise ValueError("shadow_bounded_freshness_required")
    result = simulate_reference_tiers(rows)
    by_key = {(row["platform"], row["source"]): row for row in rows}
    platforms = {}
    for platform in PLATFORMS:
        observed = result["observations"][platform]
        for site in SITES:
            if site not in observed:
                observed[site] = {"tier": next(tier for tier, sites in SOURCE_TIERS.items() if site in sites),
                                  "comparable": False, "usd_per_k": None, "reason": "source_not_observed"}
            row, value = by_key.get((platform, site)), observed[site]
            if value["comparable"]:
                timing = _time_problem(row.get("captured_at"), now, maximum_age_seconds)
                if timing:
                    value.update(comparable=False, usd_per_k=None, reason=timing)
        available = {site: value for site, value in observed.items() if value["comparable"]}
        selected_tier, selected = shadow_reference_sites(available)
        result["reference_sources"][platform] = selected
        result["selected_reference_tiers"][platform] = selected_tier
        absent = {site: value["reason"] for site, value in observed.items() if not value["comparable"]}
        own, own_problem = _storefront_unit(storefront, platform, result["run_id"], now, maximum_age_seconds)
        anchor = Decimal(available["Lootbar"]["usd_per_k"]) if "Lootbar" in available else None
        scores = {site: EXPERIMENTAL_REFERENCE_SCORES[value["tier"]]
                  for site, value in available.items() if value["tier"] != "core"}
        scenarios = []
        for weight in EXPERIMENTAL_ANCHOR_WEIGHTS:
            candidate, normalized = None, {}
            if anchor is not None and scores:
                total = sum(scores.values())
                normalized = {site: (1-weight)*score/total for site, score in scores.items()}
                candidate = weight*anchor+sum(normalized[site]*Decimal(available[site]["usd_per_k"]) for site in scores)
            scenarios.append({
                "experiment": "illustrative_anchor_"+str(weight), "anchor_weight": str(weight),
                "reference_weights": {site: str(value) for site, value in normalized.items()},
                "weighted_unit": str(candidate) if candidate is not None else None,
                "delta_vs_lootbar_pct": str((candidate/anchor-1)*100) if candidate is not None else None,
                "delta_vs_storefront_pct": str((candidate/own-1)*100) if candidate is not None and own is not None else None,
                "margin_redlines": "not_evaluated_requires_original_prove_catalog",
            })
        platforms[platform] = {
            "status": "partial" if absent or own_problem or anchor is None or not scores else "complete",
            "unavailable_sources": absent, "storefront_problem": own_problem,
            "lootbar_unit": str(anchor) if anchor is not None else None,
            "storefront_unit": str(own) if own is not None else None,
            "reference_quality_scores": {site: str(score) for site, score in scores.items()},
            "scenarios": scenarios,
        }
    result.update(status="partial" if any(p["status"] != "complete" for p in platforms.values()) else "complete",
                  status_basis="observation_comparability_only_not_business_price_approval",
                  price_recommendation=False,
                  experimental_parameters="illustrative_research_only_not_user_selected_or_production_rules",
                  scenario_rule="all_comparable_references_second_score_2_third_score_1_normalized",
                  evaluated_at=now.isoformat(), maximum_age_seconds=maximum_age_seconds,
                  shadow_core_comparable=all(result["observations"][p]["Lootbar"]["comparable"] for p in PLATFORMS),
                  weighted_platforms=platforms)
    return result
