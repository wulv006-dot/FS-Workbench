"""Bind read-only MLB26 pricing targets to the existing Order scope."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


_GAME_ID = 922
_AREAS = {"PS": "PS 5", "XBOX": "XBOX", "SWITCH": "Switch"}


def _positive_rate(value):
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("mlb_order_rate_invalid") from None
    if not rate.is_finite() or rate <= 0:
        raise ValueError("mlb_order_rate_invalid")
    return str(rate)


def _timestamp_status(value):
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return "unknown"
    if observed.tzinfo is None or observed.utcoffset() is None:
        return "timezone_unverified"
    age = datetime.now(timezone.utc) - observed
    return "within_hour" if timedelta(0) <= age < timedelta(hours=1) else "outside_hour"


def order_readback_preview(snapshot, targets):
    if isinstance(snapshot, dict) and isinstance(snapshot.get("data"), dict):
        snapshot = snapshot["data"]
    if (not isinstance(snapshot, dict) or snapshot.get("ok") is not True
            or snapshot.get("gid") != _GAME_ID or snapshot.get("b2c_unit") != "USD/1K"
            or not isinstance(snapshot.get("rows"), list)):
        raise ValueError("mlb_order_scope_mismatch")

    rows = {}
    row_ids = set()
    for row in snapshot["rows"]:
        if not isinstance(row, dict) or row.get("gid") != _GAME_ID:
            raise ValueError("mlb_order_scope_mismatch")
        area = row.get("area")
        row_id = row.get("id")
        if (area not in _AREAS.values() or area in rows
                or not isinstance(row_id, str) or not row_id.isascii()
                or not row_id.isdigit() or row_id in row_ids):
            raise ValueError("mlb_order_scope_mismatch")
        rows[area] = row
        row_ids.add(row_id)
    if len(rows) != len(_AREAS):
        raise ValueError("mlb_order_scope_mismatch")

    if set(targets) != set(_AREAS) or targets["SWITCH"] != targets["PS"]:
        raise ValueError("mlb_order_targets_mismatch")
    proposals = {}
    for platform, area in _AREAS.items():
        target = targets[platform]
        target_rate = _positive_rate(target["usd_per_k"]) if target else None
        proposals[platform] = {
            "row_id": rows[area]["id"],
            "area": area,
            "before_usd_per_k": _positive_rate(rows[area].get("b2c")),
            "target_usd_per_k": target_rate,
            "supplier_settlement_usd_per_k": (
                str(Decimal(target_rate) * Decimal("0.75")) if target_rate else None
            ),
        }
    return {
        "status": "preview_only",
        "gid": _GAME_ID,
        "currency_unit": "USD/1K",
        "source_fetched_at": snapshot.get("fetched_at"),
        "source_timestamp_status": _timestamp_status(snapshot.get("fetched_at")),
        "rows": proposals,
    }
