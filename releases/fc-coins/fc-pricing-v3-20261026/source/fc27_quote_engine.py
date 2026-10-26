"""Collection-shape compatibility; current decisions use the FC Pricing V3 coordinator."""
from decimal import Decimal,InvalidOperation
PLATFORMS=("PS","XBOX","PC")
SITES=("Lootbar","U4GM","IGGM","U7Buy")

def reference_sites(available):
    available = set(available)
    primary = [site for site in ("U4GM", "IGGM") if site in available]
    return primary or (["U7Buy"] if "U7Buy" in available else [])


def source_coverage(rows):
    expected = {(platform, site) for platform in PLATFORMS for site in SITES}
    keys = [(row.get("platform"), row.get("source")) for row in rows]
    if (len(keys) != len(expected) or set(keys) != expected
            or any(row.get("status") not in {"valid", "missing"} for row in rows)):
        raise ValueError("competitor_coverage_invalid")
    available = {p: [row["source"] for row in rows
                     if row["platform"] == p and row["status"] == "valid"] for p in PLATFORMS}
    return {"ready": all("Lootbar" in available[p] for p in PLATFORMS),
            "unavailable_sources": [site for site in SITES if site != "Lootbar"
                                    and any(site not in available[p] for p in PLATFORMS)],
            "reference_sources": {p: reference_sites(available[p]) for p in PLATFORMS}}


def positive(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{label} 不是有效数字") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{label} 必须大于 0")
    return number


def nonnegative(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{label} 不是有效数字") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label} 不得小于 0")
    return number


def calculate(evidence, edits=None):
    from fc_pricing_v3.runtime import calculate as calculate_v3
    return calculate_v3(evidence, edits)

