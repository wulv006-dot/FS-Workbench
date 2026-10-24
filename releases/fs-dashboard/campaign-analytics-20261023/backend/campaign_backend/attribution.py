"""Paid-order attribution from actual applied benefits, independent of browser visits."""
from dataclasses import dataclass

from .core import ContractError, Money, identity, same_money, source_identity, timestamp
from .catalog import field, mapped


@dataclass(frozen=True)
class BenefitRef:
    kind: str
    native_id: str
    batch_id: str = None

    def __post_init__(self):
        if self.kind not in ('coupon', 'discount', 'campaign'):
            raise ContractError('BENEFIT_KIND_UNKNOWN')
        identity(self.native_id)
        if self.batch_id is not None:
            identity(self.batch_id)


@dataclass(frozen=True)
class AppliedBenefit:
    ref: BenefitRef
    applied_at: str
    rule_version: str = None

    def __post_init__(self):
        if not isinstance(self.ref, BenefitRef):
            raise ContractError('INVALID_BENEFIT')
        timestamp(self.applied_at)
        if self.rule_version is not None:
            identity(self.rule_version)


@dataclass(frozen=True)
class Binding:
    activity_id: str
    binding_version: str
    rule_version: str
    site_id: str
    ref: BenefitRef
    valid_from: str
    valid_to: str
    page_id: str = None

    def __post_init__(self):
        for value in (self.activity_id, self.binding_version, self.rule_version, self.site_id):
            identity(value)
        if self.page_id is not None:
            identity(self.page_id)
        if not isinstance(self.ref, BenefitRef) or timestamp(self.valid_from) >= timestamp(self.valid_to):
            raise ContractError('INVALID_BINDING')

    def matches(self, site_id, use):
        return (self.site_id == site_id and self.ref.kind == use.ref.kind
                and self.ref.native_id == use.ref.native_id
                and (self.ref.batch_id is None or self.ref.batch_id == use.ref.batch_id)
                and (use.rule_version is None or use.rule_version == self.rule_version)
                and timestamp(self.valid_from) <= timestamp(use.applied_at) < timestamp(self.valid_to))


@dataclass(frozen=True)
class OrderLine:
    line_id: str
    benefits: tuple
    paid: Money = None

    def __post_init__(self):
        identity(self.line_id)
        if (not isinstance(self.benefits, tuple)
                or any(not isinstance(v, AppliedBenefit) for v in self.benefits)
                or (self.paid is not None and not isinstance(self.paid, Money))):
            raise ContractError('INVALID_ORDER_LINE')


@dataclass(frozen=True)
class Order:
    site_id: str
    order_no: str
    payment_state: str
    paid_at: str
    paid: Money
    benefits: tuple
    lines: tuple = ()
    mode: str = 'production'

    def __post_init__(self):
        identity(self.site_id)
        identity(self.order_no)
        if self.payment_state not in ('paid', 'unpaid', 'cancelled'):
            raise ContractError('PAYMENT_STATE_UNKNOWN')
        if self.mode not in ('production', 'integration_test', 'preview'):
            raise ContractError('DATA_MODE_UNKNOWN')
        if not isinstance(self.paid, Money):
            raise ContractError('INVALID_MONEY')
        if self.payment_state == 'paid':
            timestamp(self.paid_at)
        if (not isinstance(self.benefits, tuple) or not isinstance(self.lines, tuple)
                or any(not isinstance(v, AppliedBenefit) for v in self.benefits)
                or any(not isinstance(v, OrderLine) for v in self.lines)
                or len({v.line_id for v in self.lines}) != len(self.lines)):
            raise ContractError('INVALID_ORDER_DETAIL')
        for line in self.lines:
            if line.paid is not None:
                same_money(self.paid, line.paid)
        known = sum(line.paid.minor for line in self.lines if line.paid is not None)
        if known > self.paid.minor:
            raise ContractError('LINE_ALLOCATION_EXCEEDS_PAID')


@dataclass(frozen=True)
class Refund:
    site_id: str
    refund_id: str
    order_no: str
    amount: Money
    line_id: str = None

    def __post_init__(self):
        for value in (self.site_id, self.refund_id, self.order_no):
            identity(value)
        if not isinstance(self.amount, Money):
            raise ContractError('INVALID_MONEY')
        if self.line_id is not None:
            identity(self.line_id)


@dataclass(frozen=True)
class OrderMapping:
    verification_ref: str
    fields: dict
    payment_states: tuple
    currency_scales: dict
    mode: str


def normalize_order(raw, mapping, *, benefits=(), lines=()):
    """No default paid enum, currency, timezone or paid-amount field. Uses must be verified actual use."""
    identity(mapping.verification_ref)
    try:
        get = lambda key: field(raw, mapping.fields[key])
        state = mapped(get('payment_state'), mapping.payment_states)
        return Order(site_id=source_identity(get('site_id')), order_no=source_identity(get('order_no')), payment_state=state,
                     paid_at=get('paid_at'), paid=Money.parse(get('paid'), get('currency'),
                     mapping.currency_scales), benefits=tuple(benefits), lines=tuple(lines), mode=mapping.mode)
    except (KeyError, TypeError, AttributeError):
        raise ContractError('ORDER_MAPPING_REQUIRED') from None


def unique(rows, key):
    result = {}
    for row in rows:
        rid = key(row)
        if rid in result and result[rid] != row:
            raise ContractError('CONFLICTING_DUPLICATE_FACT')
        result[rid] = row
    return result


def attribute(orders, bindings, refunds=(), *, mode='production'):
    """A complete consistent snapshot in; separate linked-order and allocated-line money out."""
    if mode not in ('production', 'integration_test', 'preview'):
        raise ContractError('DATA_MODE_UNKNOWN')
    bindings = tuple(bindings)
    # Overlap on the same native identity cannot assign one shared coupon to several pages.
    for index, left in enumerate(bindings):
        for right in bindings[index + 1:]:
            same_ref = (left.site_id, left.ref.kind, left.ref.native_id) == (right.site_id, right.ref.kind, right.ref.native_id)
            overlapping_batch = (left.ref.batch_id is None or right.ref.batch_id is None
                                 or left.ref.batch_id == right.ref.batch_id)
            overlap = max(timestamp(left.valid_from), timestamp(right.valid_from)) < min(timestamp(left.valid_to), timestamp(right.valid_to))
            if same_ref and overlapping_batch and overlap and left != right:
                raise ContractError('AMBIGUOUS_BINDING_USE_ACTIVITY_GROUP')
    orders = unique(orders, lambda o: (o.site_id, o.order_no))
    refunds = unique(refunds, lambda r: (r.site_id, r.refund_id))
    by_order = {}
    for refund in refunds.values():
        key = (refund.site_id, refund.order_no)
        if key not in orders:
            raise ContractError('REFUND_ORDER_MISSING')
        same_money(orders[key].paid, refund.amount)
        by_order.setdefault(key, []).append(refund)
    rows, global_totals, activity_totals, currency_scales = [], {}, {}, {}

    def total(container, money):
        previous = currency_scales.setdefault(money.currency, money.scale)
        if previous != money.scale:
            raise ContractError('CURRENCY_OR_SCALE_CONFLICT')
        return container.setdefault(money.currency, dict(currency=money.currency, scale=money.scale,
            order_count=0, linked_paid_minor=0, linked_refund_minor=0, linked_net_minor=0,
            allocated_paid_minor=0, allocated_refund_minor=0, allocated_net_minor=0,
            allocation_missing_orders=0, refund_allocation_missing_orders=0))

    for key, order in sorted(orders.items()):
        if order.mode != mode or order.payment_state != 'paid':
            continue
        matches = {}
        for use in order.benefits + tuple(use for line in order.lines for use in line.benefits):
            for binding in bindings:
                if binding.matches(order.site_id, use):
                    matches.setdefault(binding.activity_id, set()).add(binding)
        if not matches:
            continue
        refund_rows = by_order.get(key, [])
        refunded = sum(r.amount.minor for r in refund_rows)
        if refunded > order.paid.minor:
            raise ContractError('REFUND_EXCEEDS_PAID')
        line_ids = {line.line_id for line in order.lines}
        if any(r.line_id is not None and r.line_id not in line_ids for r in refund_rows):
            raise ContractError('REFUND_LINE_MISSING')
        for line in order.lines:
            if line.paid is not None and sum(r.amount.minor for r in refund_rows if r.line_id == line.line_id) > line.paid.minor:
                raise ContractError('REFUND_EXCEEDS_LINE_PAID')
        global_total = total(global_totals, order.paid)
        for item in [global_total]:
            item['order_count'] += 1
            item['linked_paid_minor'] += order.paid.minor
            item['linked_refund_minor'] += refunded
            item['linked_net_minor'] += order.paid.minor - refunded
        all_allocated = set()
        for activity_id, activity_bindings in sorted(matches.items()):
            selected = [line for line in order.lines if any(
                binding.matches(order.site_id, use) for use in line.benefits for binding in activity_bindings)]
            selected_ids = {line.line_id for line in selected}
            missing = not selected or any(line.paid is None for line in selected)
            refund_missing = bool(refund_rows) and (not selected or any(r.line_id is None for r in refund_rows))
            allocated = None if missing else sum(line.paid.minor for line in selected)
            allocated_refund = None if refund_missing else sum(r.amount.minor for r in refund_rows if r.line_id in selected_ids)
            if allocated is not None and allocated_refund is not None and allocated_refund > allocated:
                raise ContractError('REFUND_EXCEEDS_LINE_PAID')
            basket = 'unknown' if not selected else ('all' if len(selected) == len(order.lines) else 'mixed')
            row = dict(site_id=order.site_id, order_no=order.order_no, activity_id=activity_id,
                binding_versions=sorted({b.binding_version for b in activity_bindings}),
                rule_versions=sorted({b.rule_version for b in activity_bindings}),
                page_ids=sorted({b.page_id for b in activity_bindings if b.page_id is not None}),
                attribution_level='page' if all(b.page_id is not None for b in activity_bindings) else 'activity_group',
                currency=order.paid.currency, scale=order.paid.scale, linked_paid_minor=order.paid.minor,
                linked_refund_minor=refunded, linked_net_minor=order.paid.minor - refunded,
                basket_scope=basket, allocation_status='missing' if missing else 'available',
                allocated_paid_minor=allocated, allocated_refund_minor=allocated_refund,
                allocated_net_minor=None if allocated is None or allocated_refund is None else allocated - allocated_refund)
            rows.append(row)
            activity_total = total(activity_totals.setdefault(activity_id, {}), order.paid)
            activity_total['order_count'] += 1
            for name in ('linked_paid_minor', 'linked_refund_minor', 'linked_net_minor'):
                activity_total[name] += row[name]
            activity_total['allocation_missing_orders'] += int(missing)
            activity_total['refund_allocation_missing_orders'] += int(refund_missing)
            for name in ('allocated_paid_minor', 'allocated_refund_minor', 'allocated_net_minor'):
                if row[name] is not None:
                    activity_total[name] += row[name]
            all_allocated.update(selected_ids)
        # Global allocated money counts a line once even if several distinct benefits hit it.
        selected = [line for line in order.lines if line.line_id in all_allocated]
        allocation_missing = not selected or any(line.paid is None for line in selected)
        refund_missing = bool(refund_rows) and (not selected or any(r.line_id is None for r in refund_rows))
        global_total['allocation_missing_orders'] += int(allocation_missing)
        global_total['refund_allocation_missing_orders'] += int(refund_missing)
        allocated = sum(line.paid.minor for line in selected if line.paid is not None)
        allocated_refund = sum(r.amount.minor for r in refund_rows if r.line_id in all_allocated)
        if not allocation_missing:
            global_total['allocated_paid_minor'] += allocated
        if not refund_missing:
            global_total['allocated_refund_minor'] += allocated_refund
        if not allocation_missing and not refund_missing:
            global_total['allocated_net_minor'] += allocated - allocated_refund
    for item in list(global_totals.values()) + [item for values in activity_totals.values() for item in values.values()]:
        for name in ('allocated_paid_minor', 'allocated_refund_minor', 'allocated_net_minor'):
            item['known_' + name] = item[name]
        if item['allocation_missing_orders']:
            item['allocated_paid_minor'] = None
        if item['refund_allocation_missing_orders']:
            item['allocated_refund_minor'] = None
        if item['allocation_missing_orders'] or item['refund_allocation_missing_orders']:
            item['allocated_net_minor'] = None
    return dict(mode=mode, rows=rows, global_totals=list(global_totals.values()),
                activity_totals={key: list(value.values()) for key, value in activity_totals.items()})
