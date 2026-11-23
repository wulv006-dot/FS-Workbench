"""Read operator-supplied IGGM quotes obtained through an authorized source."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json

from .hourly import QuoteUnavailable


@dataclass(frozen=True)
class IggmOffer:
    purchase_k: int
    total_usd: Decimal
    observed_at: str
    reference: str


def _parse_offer(row, hour, now):
    try:
        purchase_k = row["purchase_k"]
        raw_total = row["total_usd"]
        observed = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        reference = row["reference"]
        if type(purchase_k) is not int or purchase_k <= 0 or not isinstance(raw_total, str):
            raise ValueError
        total = Decimal(raw_total)
        if (not total.is_finite() or total <= 0
                or not isinstance(reference, str) or not reference.strip() or len(reference) > 100
                or not hour <= observed <= now):
            raise ValueError
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError, OverflowError):
        raise QuoteUnavailable("iggm_quote_invalid_or_stale") from None
    return IggmOffer(purchase_k, total, observed.isoformat(), reference)


def load_iggm_receipt(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        def unavailable(platform, eldorado):
            raise QuoteUnavailable("iggm_receipt_unreadable")
        return unavailable
    return authorized_iggm_reader(data)


def authorized_iggm_reader(data, *, now=None):
    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    hour = now.replace(minute=0, second=0, microsecond=0)

    def read(platform, eldorado):
        if (not isinstance(data, dict) or data.get("source") != "IGGM"
                or data.get("product") != "MLB26_STUBS" or data.get("currency") != "USD"
                or not isinstance(data.get("offers"), dict)):
            raise QuoteUnavailable("iggm_receipt_scope_invalid")
        rows = data["offers"].get(platform)
        if not isinstance(rows, list) or not rows:
            raise QuoteUnavailable("iggm_platform_missing")

        comparable = []
        for row in rows:
            offer = _parse_offer(row, hour, now)
            if eldorado is None or eldorado.minimum_k <= offer.purchase_k <= eldorado.stock_k:
                comparable.append(offer)
        if not comparable:
            raise QuoteUnavailable("iggm_comparable_quantity_missing")

        selected = min(comparable, key=lambda offer: offer.purchase_k)
        same_tier = {offer.total_usd for offer in comparable if offer.purchase_k == selected.purchase_k}
        if len(same_tier) != 1:
            raise QuoteUnavailable("iggm_conflicting_quotes")
        return selected

    return read
