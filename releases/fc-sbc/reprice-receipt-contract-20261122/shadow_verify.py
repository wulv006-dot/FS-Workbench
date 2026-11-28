"""Verify synthetic stage receipts against a frozen SBC/Packs row plan."""
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from typing import Optional


@dataclass(frozen=True)
class RowScope:
    site_id: int
    platform_id: int
    goods_id: int

    def __post_init__(self):
        values = (self.site_id, self.platform_id, self.goods_id)
        if any(type(v) is not int for v in values) or self.site_id < 0 or min(values[1:]) <= 0:
            raise ValueError("explicit site, platform and goods identifiers required")


@dataclass(frozen=True)
class PriceState:
    unit_price: Decimal
    discount: Decimal
    quantity: int
    effective_price: Decimal

    def __post_init__(self):
        amounts = (self.unit_price, self.discount, self.effective_price)
        if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in amounts):
            raise ValueError("invalid price fields")
        if type(self.quantity) is not int or self.quantity < 1:
            raise ValueError("invalid quantity")


@dataclass(frozen=True)
class ShadowPlan:
    operation: str
    scope: RowScope
    before: PriceState
    target_unit: Decimal

    def __post_init__(self):
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("explicit operation required")
        if (
            not isinstance(self.target_unit, Decimal)
            or not self.target_unit.is_finite()
            or self.target_unit <= 0
        ):
            raise ValueError("positive cent-precise target required")
        with localcontext(Context(prec=80, rounding=ROUND_HALF_UP)):
            if self.target_unit.adjusted() > 18 or self.target_unit != self.target_unit.quantize(Decimal("0.01")):
                raise ValueError("positive cent-precise target required")


@dataclass(frozen=True)
class StageReceipt:
    operation: str
    scope: RowScope
    disposition: str  # accepted, rejected, not_attempted, unknown
    observed_before: Optional[PriceState] = None
    observed_after: Optional[PriceState] = None

    def __post_init__(self):
        if self.disposition not in ("accepted", "rejected", "not_attempted", "unknown"):
            raise ValueError("invalid disposition")
        if self.disposition == "not_attempted" and (
            self.observed_before is not None or self.observed_after is not None
        ):
            raise ValueError("unattempted stage cannot carry operation read-back")


@dataclass(frozen=True)
class ShadowVerdict:
    outcome: str
    reason: str


def _effective(unit: Decimal, quantity: int, discount: Decimal) -> Decimal:
    # Synthetic Admin contract; production formula/rounding still need verification.
    with localcontext(Context(prec=80, rounding=ROUND_HALF_UP)):
        return (unit * quantity * discount / 100).quantize(Decimal("0.01"))


def _with_clean_discount(unit: Decimal, quantity: int) -> PriceState:
    discount = Decimal("100")
    return PriceState(unit, discount, quantity, _effective(unit, quantity, discount))


def _bound(plan: ShadowPlan, receipt: StageReceipt) -> bool:
    return (plan.operation, plan.scope) == (receipt.operation, receipt.scope)


def _confirmed(receipt: StageReceipt, before: PriceState, after: PriceState) -> bool:
    return (
        receipt.disposition == "accepted"
        and receipt.observed_before == before
        and receipt.observed_after == after
    )


def _rejected_no_change(receipt: StageReceipt, state: PriceState) -> bool:
    return (
        receipt.disposition == "rejected"
        and receipt.observed_before == state
        and receipt.observed_after == state
    )


def verify_shadow(
    plan: ShadowPlan, discount_stage: Optional[StageReceipt], unit_stage: Optional[StageReceipt]
) -> ShadowVerdict:
    """Interpret stages without mutating data, dispatching or retrying any write.

    Caller must bind independently collected before/after observations to
    the authenticated Admin operation and stage. This function never infers
    their provenance from a coincidentally matching price.
    """
    for stage in (discount_stage, unit_stage):
        if stage is not None and not _bound(plan, stage):
            return ShadowVerdict("unknown", "wrong_operation_or_row")

    before = plan.before
    if before.effective_price != _effective(before.unit_price, before.quantity, before.discount):
        return ShadowVerdict("unknown", "inconsistent_frozen_price_state")
    final = _with_clean_discount(plan.target_unit, before.quantity)
    needs_discount = before.discount != 100
    if not needs_discount and before == final:
        if discount_stage is None and unit_stage is None:
            return ShadowVerdict("unchanged", "no_write_required")
        return ShadowVerdict("unknown", "unexpected_stage_for_noop")

    stage_before = before
    if needs_discount:
        if discount_stage is None:
            return ShadowVerdict("unknown", "discount_stage_unverified")
        if _rejected_no_change(discount_stage, before):
            if unit_stage is None:
                return ShadowVerdict("unknown", "discount_rejected_unit_unverified")
            if unit_stage.disposition == "not_attempted":
                return ShadowVerdict("rejected", "discount_rejected")
            return ShadowVerdict("unknown", "unexpected_unit_stage_after_discount_rejection")
        stage_before = _with_clean_discount(before.unit_price, before.quantity)
        if not _confirmed(discount_stage, before, stage_before):
            return ShadowVerdict("unknown", "discount_stage_unverified")
    elif discount_stage is not None:
        return ShadowVerdict("unknown", "unexpected_discount_stage")

    if unit_stage is None:
        reason = "discount_applied_unit_unverified" if needs_discount else "unit_unverified"
        return ShadowVerdict("unknown", reason)
    if unit_stage.disposition == "not_attempted":
        if needs_discount:
            return ShadowVerdict("partial", "discount_applied_unit_not_attempted")
        return ShadowVerdict("not_attempted", "unit_not_attempted")
    if _confirmed(unit_stage, stage_before, final):
        return ShadowVerdict("changed", "final_price_fields_verified")
    if _rejected_no_change(unit_stage, stage_before):
        if needs_discount:
            return ShadowVerdict("partial", "discount_applied_unit_rejected")
        return ShadowVerdict("rejected", "unit_rejected")
    reason = "discount_applied_unit_unverified" if needs_discount else "unit_unverified"
    return ShadowVerdict("unknown", reason)
