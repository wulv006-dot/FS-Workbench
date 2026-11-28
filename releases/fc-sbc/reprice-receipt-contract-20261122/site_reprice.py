"""Offline contract: configure ALL; read and verify only MMOEXP."""
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from reprice_plan import PricingRule, ProductRow, TrustedRate, plan_prices
from shadow_verify import PriceState
from site_binding import AdminRow, BindingKey, bind


ALL_SITE_ID = 0
MMOEXP_SITE_ID = 266
PLATFORM_IDS = {"PS": 21587, "XBOX": 21585, "PC": 21589}
CATEGORIES = {"SBC": frozenset({9625, 9971, 10203}), "Packs": frozenset({9629, 10255})}
FC27_GAME_ID = 1327


@dataclass(frozen=True)
class ScopedInput:
    config_scope: BindingKey
    mmoexp_rows: Sequence[AdminRow]
    product: ProductRow


@dataclass(frozen=True)
class ConfigProposal:
    config_scope: BindingKey
    state: str
    reason: str
    unit_price_usd: Optional[Decimal] = None
    normalize_discount: bool = False


def plan_all_config(
    inputs: Iterable[ScopedInput],
    rates: Mapping[str, TrustedRate],
    rules: Mapping[Tuple[int, str, str], PricingRule],
) -> Tuple[ConfigProposal, ...]:
    """Plan a template configuration; never return a concrete goods write target.

    Historic categories are a minimum recognized set, not today's model discovery.
    Inputs are validated MMOEXP snapshots, not a query to ALL or other sites.
    The template policy is explicit; a matching MMOEXP price does not prove the
    template itself already has that value.
    """
    inputs = tuple(inputs)
    occurrences = Counter(item.config_scope for item in inputs)
    results = []
    candidates = []
    for item in inputs:
        scope, product = item.config_scope, item.product
        if scope.site_id != ALL_SITE_ID:
            reason = "config_must_target_all"
        elif occurrences[scope] != 1:
            reason = "duplicate_config_scope"
        elif scope.game_id != FC27_GAME_ID or scope.category_id not in CATEGORIES.get(product.kind, ()):
            reason = "unsupported_game_or_category"
        elif scope.platform_id != PLATFORM_IDS.get(product.platform):
            reason = "platform_scope_mismatch"
        else:
            match = bind(replace(scope, site_id=MMOEXP_SITE_ID), item.mmoexp_rows)
            row = match.row
            if row is None:
                reason = match.state
            elif (
                type(product.site_id) is not int or product.site_id != MMOEXP_SITE_ID
                or type(product.goods_id) is not int or product.goods_id != row.goods_id
            ):
                reason = "mmoexp_snapshot_scope_mismatch"
            else:
                reason = None
        if reason is None:
            candidates.append(product)
            results.append(None)
        else:
            results.append(ConfigProposal(scope, "unconfirmed", reason))

    # Pricing inputs reference observed main-site rows; only the ALL policy
    # is admitted. A site-specific policy cannot silently change ALL.
    price_rules = {
        (MMOEXP_SITE_ID, platform, kind): rule
        for (site_id, platform, kind), rule in rules.items()
        if type(site_id) is int and site_id == ALL_SITE_ID
    }
    planned = iter(plan_prices(candidates, rates, price_rules))
    for index, (item, result) in enumerate(zip(inputs, results)):
        if result is not None:
            continue
        decision = next(planned)
        state, reason = decision.state, decision.reason
        if reason == "price_unchanged":
            state, reason = "unconfirmed", "mmoexp_matches_all_config_unverified"
        results[index] = ConfigProposal(
            item.config_scope, state, reason, decision.target_unit_price_usd, decision.normalize_discount
        )
    return tuple(results)


@dataclass(frozen=True)
class ConfigReceipt:
    operation: str
    scope: BindingKey
    accepted: bool


@dataclass(frozen=True)
class MmoexpReadback:
    operation: str
    scope: BindingKey
    price: PriceState


def verify_mmoexp(
    proposal: ConfigProposal, receipt: ConfigReceipt, readback: Optional[MmoexpReadback]
) -> str:
    """Assess caller-authenticated evidence; never imply all satellites verified.

    The caller must establish that the read-back belongs to this very operation,
    not just supply a coincidentally matching price or reuse an operation ID.
    """
    target = proposal.unit_price_usd
    if (
        proposal.state != "candidate" or proposal.config_scope.site_id != ALL_SITE_ID
        or not isinstance(target, Decimal) or not target.is_finite() or target <= 0
        or receipt.accepted is not True or receipt.scope != proposal.config_scope
        or not isinstance(receipt.operation, str) or not receipt.operation.strip()
    ):
        return "unconfirmed_config"
    if (
        readback is None or readback.operation != receipt.operation
        or readback.scope != replace(receipt.scope, site_id=MMOEXP_SITE_ID)
        or not isinstance(readback.price, PriceState)
    ):
        return "unconfirmed_mmoexp"
    price = readback.price
    expected = PriceState(target, Decimal("100"), 1, target)
    return "verified_mmoexp" if price == expected else "mmoexp_price_mismatch"
