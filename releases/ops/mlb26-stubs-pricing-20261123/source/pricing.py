"""Select MLB26 Stubs rates from validated public quotes in USD per 1K."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PlatformQuotes:
    eldorado: Optional[Decimal] = None
    iggm: Optional[Decimal] = None


@dataclass(frozen=True)
class PriceDecision:
    usd_per_k: Decimal
    source: str


def _select_price(quotes: PlatformQuotes) -> Optional[PriceDecision]:
    candidates = []
    if quotes.eldorado is not None:
        candidates.append(PriceDecision(quotes.eldorado, "Eldorado"))
    if quotes.iggm is not None:
        candidates.append(PriceDecision(quotes.iggm * Decimal("0.8"), "IGGM"))
    return min(candidates, key=lambda decision: decision.usd_per_k, default=None)


def plan_prices(
    *, playstation: PlatformQuotes, xbox: PlatformQuotes
) -> dict[str, Optional[PriceDecision]]:
    playstation_decision = _select_price(playstation)
    return {
        "PS": playstation_decision,
        "XBOX": _select_price(xbox),
        "SWITCH": playstation_decision,
    }
