"""Bind candidate rows to explicit site configuration before offline pricing."""
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from reprice_plan import PriceDecision, PricingRule, ProductRow, TrustedRate, plan_prices
from site_binding import AdminRow, BindingKey, bind


PLATFORM_IDS = {"PS": 21587, "XBOX": 21585, "PC": 21589}
CATEGORIES = {"SBC": frozenset({9625, 9971, 10203}), "Packs": frozenset({9629, 10255})}
FC27_GAME_ID = 1327


@dataclass(frozen=True)
class ScopedInput:
    key: Optional[BindingKey]
    candidates: Sequence[AdminRow]
    product: ProductRow


def plan_site_reprice(
    inputs: Iterable[ScopedInput],
    rates: Mapping[str, TrustedRate],
    rules: Mapping[Tuple[int, str, str], PricingRule],
) -> Tuple[PriceDecision, ...]:
    """Plan only explicit, unambiguous concrete sites with matching product identities.

    Categories observed in archived Admin data are a minimum compatibility
    allowlist, not discovery of today’s enabled models. Template rows (site 0)
    stay outside this candidate's concrete-site rewrite.
    """
    results = []
    candidates = []
    for item in inputs:
        match = bind(item.key, item.candidates)
        row, product, key = match.row, item.product, item.key
        if row is None:
            reason = match.state
        elif row.site_id == 0:
            reason = "template_not_migrated"
        elif row.goods_id != product.goods_id or row.site_id != product.site_id:
            reason = "price_row_scope_mismatch"
        elif type(product.site_id) is not int or type(product.goods_id) is not int:
            reason = "price_row_scope_mismatch"
        elif key.game_id != FC27_GAME_ID or key.category_id not in CATEGORIES.get(product.kind, ()):
            reason = "unsupported_game_or_category"
        elif row.platform_id != PLATFORM_IDS.get(product.platform):
            reason = "price_row_scope_mismatch"
        else:
            reason = None
        if reason is None:
            candidates.append(product)
            results.append(None)
        else:
            results.append(PriceDecision(product.goods_id, product.site_id, product.platform,
                                         "unconfirmed", reason))
    planned = iter(plan_prices(candidates, rates, rules))
    return tuple(next(planned) if item is None else item for item in results)
