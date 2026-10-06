"""Gold cost validity at existing configuration and actual writer precision.

The container writer uses %.6f. This guard validates that representation;
it does not change the calculation, configured rounding, or profit policy.
"""
import math


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def precision(cfg):
    raw = ((cfg or {}).get("金币") or {}).get("采购成本小数位", 6)
    if isinstance(raw, bool):
        return None
    raw = raw or 6  # Existing zero/empty precision means default 6.
    number = finite(raw)
    if number is None:
        return None
    try:
        dec = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return dec if dec == number else None


def write_cost(value, cfg):
    number = finite(value)
    dec = precision(cfg)
    if number is None or number <= 0 or dec is None:
        return None
    try:
        rounded = finite(round(number, dec))
        serialized = finite("%.6f" % number)  # Exact existing container format.
    except (TypeError, ValueError, OverflowError):
        return None
    if rounded is None or rounded <= 0 or serialized is None or serialized <= 0:
        return None
    return number


def validate_ticket(plan, cfg):
    items = plan.get("items") if isinstance(plan, dict) else plan
    if not isinstance(items, list) or not items:
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        value = item.get("采购成本_新")
        if value is None:
            value = item.get("new")
        if write_cost(value, cfg) is None:
            return False
    return True
