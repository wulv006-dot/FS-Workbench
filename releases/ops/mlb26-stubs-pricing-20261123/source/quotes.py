"""Validate the visible Eldorado recommended offer before using its unit price."""

from dataclasses import dataclass
from decimal import Decimal
import re


@dataclass(frozen=True)
class EldoradoOffer:
    seller: str
    usd_per_k: Decimal
    minimum_k: Decimal
    stock_k: Decimal


def parse_eldorado(data: dict, device: str) -> EldoradoOffer:
    if data.get("usd") is not True or data.get("devices") != [device]:
        raise ValueError("eldorado_platform_or_currency_unverified")
    seller = data.get("seller")
    offer = data.get("offer") or ""
    if not seller or "Current offer" not in offer:
        raise ValueError("eldorado_recommended_offer_missing")

    price = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*K\b", offer)
    minimum = re.search(r"Min\. qty\.?\s*([0-9,]+(?:\.[0-9]+)?)\s*K\b", offer)
    inventory = re.search(r"In stock\s*([0-9,]+(?:\.[0-9]+)?)\s*K\b", offer)
    if not all((price, minimum, inventory)):
        raise ValueError("eldorado_offer_values_missing")

    usd_per_k = Decimal(price[1])
    minimum_k = Decimal(minimum[1].replace(",", ""))
    stock_k = Decimal(inventory[1].replace(",", ""))
    if usd_per_k <= 0 or minimum_k <= 0 or stock_k < minimum_k:
        raise ValueError("eldorado_offer_unavailable")
    return EldoradoOffer(seller, usd_per_k, minimum_k, stock_k)
