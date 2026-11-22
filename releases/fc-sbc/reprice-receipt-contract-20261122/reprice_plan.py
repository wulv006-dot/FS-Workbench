"""Offline SBC/Packs price candidates. No reads, writes, or defaults from production."""
from collections import Counter
from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, ROUND_HALF_UP, localcontext
from typing import Iterable, Mapping, Optional, Tuple, Union

Number = Union[Decimal, str, int]
CENT = Decimal("0.01")
HUNDRED = Decimal(100)
PLATFORMS = frozenset({"PS", "XBOX", "PC"})
KINDS = frozenset({"SBC", "Packs"})
TIER_BASIS = "actual_100k_purchase_v1"
REFERENCE_SITE_ID = 266
ROW_RATE_BASIS = "verified_row_override_usd_per_coin"
FORMULA_V1 = "fee_before_markup_floor_after_rounding_v1"


@dataclass(frozen=True)
class TrustedRate:
    """USD for exactly 100K coins, or USD per coin for an explicit row override."""

    platform: str
    basis: str
    usd: Number
    confirmed: bool
    source_site_id: int


@dataclass(frozen=True)
class PricingRule:
    """Caller-confirmed platform/category policy; use floor 0 for no floor."""

    markup: Number
    fee_usd: Number
    floor_usd: Number
    rounding: str
    confirmed: bool
    formula: Optional[str] = None


@dataclass(frozen=True)
class ProductRow:
    goods_id: int
    site_id: int
    platform: str
    kind: str
    live: Optional[bool]
    current_price_usd: Optional[Number]
    current_unit_price_usd: Optional[Number]
    current_discount_pct: Optional[Number]
    current_quantity: Optional[Number]
    coins: Optional[Number] = None
    rate_override: Optional[TrustedRate] = None
    markup_override: Optional[Number] = None
    fee_override_usd: Optional[Number] = None
    confirmed_target_usd: Optional[Number] = None


@dataclass(frozen=True)
class PriceDecision:
    goods_id: int
    site_id: int
    platform: str
    state: str
    reason: str
    target_unit_price_usd: Optional[Decimal] = None
    normalize_discount: bool = False


def _number(raw: Optional[Number], *, allow_zero: bool = False) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (Decimal, str, int)):
        raise ValueError("invalid decimal input")
    value = Decimal(raw)
    if not value.is_finite() or value < 0 or (not allow_zero and value == 0):
        raise ValueError("outside numeric domain")
    # Reject ambiguous loss of precision up front, before arithmetic or quantization.
    if len(value.as_tuple().digits) > 18 or abs(value.as_tuple().exponent) > 18:
        raise ValueError("outside planner precision")
    return value


def _cent_value(raw: Optional[Number], *, allow_zero: bool = False) -> Decimal:
    value = _number(raw, allow_zero=allow_zero)
    if value != value.quantize(CENT):
        raise ValueError("expected exact cents")
    return value.quantize(CENT)


def _round_cent(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _plan_row(
    row: ProductRow,
    rates: Mapping[str, TrustedRate],
    rules: Mapping[Tuple[int, str, str], PricingRule],
) -> PriceDecision:
    def decision(state: str, reason: str) -> PriceDecision:
        return PriceDecision(row.goods_id, row.site_id, row.platform, state, reason)

    if type(row.site_id) is not int or row.site_id <= 0:
        return decision("unconfirmed", "site_scope_missing")
    if row.live is False:
        return decision("skipped", "not_live")
    if row.live is not True:
        return decision("unconfirmed", "live_status_missing")
    if (not isinstance(row.platform, str) or row.platform not in PLATFORMS
            or not isinstance(row.kind, str) or row.kind not in KINDS):
        return decision("unconfirmed", "platform_or_kind_unconfirmed")
    if None in (row.current_price_usd, row.current_unit_price_usd,
                row.current_discount_pct, row.current_quantity):
        return decision("unconfirmed", "current_price_fields_missing")
    try:
        price = _cent_value(row.current_price_usd, allow_zero=True)
        unit = _cent_value(row.current_unit_price_usd)
        discount = _number(row.current_discount_pct, allow_zero=True)
        quantity = _number(row.current_quantity)
    except (ValueError, DecimalException):
        return decision("rejected", "invalid_current_price_fields")
    # Historical candidates write the target into unit_price directly.
    # No evidence here supports dividing/rounding the target for multi-unit rows.
    if quantity != 1:
        return decision("unconfirmed", "non_single_quantity")
    if discount == 0:
        return decision("unconfirmed", "zero_discount_review")
    if price != _round_cent(unit * quantity * discount / HUNDRED):
        return decision("rejected", "inconsistent_current_price_fields")

    rule = rules.get((row.site_id, row.platform, row.kind))
    if rule is None or rule.confirmed is not True:
        return decision("unconfirmed", "pricing_rule_unconfirmed")
    if row.confirmed_target_usd is not None:
        try:
            target = _cent_value(row.confirmed_target_usd)
        except (ValueError, DecimalException):
            return decision("rejected", "invalid_confirmed_target")
    else:
        if rule.formula != FORMULA_V1 or rule.rounding != ROUND_HALF_UP:
            return decision("unconfirmed", "pricing_rule_unconfirmed")
        rate = row.rate_override if row.rate_override is not None else rates.get(row.platform)
        basis = ROW_RATE_BASIS if row.rate_override is not None else TIER_BASIS
        source_site = row.site_id if row.rate_override is not None else REFERENCE_SITE_ID
        if (rate is None or rate.confirmed is not True
                or rate.platform != row.platform or rate.basis != basis
                or type(rate.source_site_id) is not int or rate.source_site_id != source_site):
            return decision("unconfirmed", "coin_rate_unconfirmed")
        if row.coins is None:
            return decision("unconfirmed", "coin_quantity_missing")
        try:
            coins = _number(row.coins)
            if coins != coins.to_integral_value():
                raise ValueError("coin quantity must be integral")
            per_coin = _number(rate.usd)
            if basis == TIER_BASIS:
                per_coin /= 100_000
            markup = _number(rule.markup if row.markup_override is None else row.markup_override)
            if row.kind == "SBC":
                fee_input = rule.fee_usd if row.fee_override_usd is None else row.fee_override_usd
                fee = _number(fee_input, allow_zero=True)
            else:
                # A saved per-product fee may exist, but must not affect Packs.
                fee = _number(rule.fee_usd, allow_zero=True)
                if fee != 0:
                    return decision("rejected", "packs_rule_fee_must_be_zero")
            floor = _cent_value(rule.floor_usd, allow_zero=True)
            target = max(_round_cent((coins * per_coin + fee) * markup), floor)
            if target <= 0 or len(target.as_tuple().digits) > 18:
                raise ValueError("calculated target outside supported price range")
        except (ValueError, DecimalException):
            return decision("rejected", "invalid_pricing_inputs")

    normalize = discount != HUNDRED
    if not normalize and target == price == unit:
        return PriceDecision(row.goods_id, row.site_id, row.platform, "skipped", "price_unchanged", target)
    reason = "discount_and_unit_price" if normalize else "unit_price"
    return PriceDecision(row.goods_id, row.site_id, row.platform, "candidate", reason, target, normalize)


def plan_prices(
    rows: Iterable[ProductRow],
    rates: Mapping[str, TrustedRate],
    rules: Mapping[Tuple[int, str, str], PricingRule],
) -> Tuple[PriceDecision, ...]:
    """Return ordered decisions; never use another platform, a stale rate or guessed rule.

    Rules must be matched by exact (site_id, platform, kind). The actual 100K
    reference from site 266 is independent of the product site or writer route.
    The caller owns identity, verification, freshness and freeze of all inputs;
    `confirmed_target_usd` is an explicitly trusted whole-cent manual target, not
    a raw UI value. A candidate is neither a write nor proof of one.
    """
    rows = tuple(rows)
    multiplicity = Counter(row.goods_id for row in rows if type(row.goods_id) is int)
    with localcontext(Context(prec=80, rounding=ROUND_HALF_UP)):
        return tuple(
            PriceDecision(row.goods_id, row.site_id, row.platform, "rejected", "invalid_goods_id")
            if type(row.goods_id) is not int or row.goods_id <= 0
            else PriceDecision(row.goods_id, row.site_id, row.platform, "rejected", "duplicate_goods_id")
            if multiplicity[row.goods_id] != 1
            else _plan_row(row, rates, rules)
            for row in rows
        )
