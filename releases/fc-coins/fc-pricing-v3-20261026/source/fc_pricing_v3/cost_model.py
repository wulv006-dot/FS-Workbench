"""V6 same-layer cost arithmetic, without source selection or financial approval.

Callers supply already deduplicated order/batch totals in USD, selected comparable
records and an evidenced upper bound. Selecting 72h/7d cohorts, verifying component
coverage, currency conversion, maturity and freshness remain source responsibilities.
No forecast here is written back as an actual order cost.
"""
from decimal import Decimal, getcontext, localcontext

from .financial import number


BASES = ('PURCHASE_K', 'PROMISED_DELIVERED_K')
LAYER_FIELDS = ('platform', 'quantity_bucket', 'offer_version', 'fulfilment_contract')


def _divide(numerator, denominator):
    # Keep guard digits in repeating per-K rates until the caller projects a
    # money amount. Do not round a 50/1030 rate to cents (or to the caller's
    # final-money precision) before multiplying by the promised quantity.
    with localcontext() as context:
        context.prec = max(56, getcontext().prec * 2)
        return numerator / denominator


def _quantity(row, basis):
    if basis not in BASES:
        raise ValueError('cost_target_basis_invalid')
    purchase = number(row.get('purchase_k'))
    return purchase if basis == 'PURCHASE_K' else purchase + number(row.get('promised_bonus_k'), zero=True)


def normalize_cost(row, target_basis):
    """Convert a known total or explicit per-basis rate without doubling gifts.

    ACTUAL_SHIPPED_K may describe the provenance of a TOTAL, never the future
    model's denominator. A raw cost_unit with that basis must first be reconciled
    into the actual full/partial total by the source adapter.
    """
    quantity = _quantity(row, target_basis)
    amount = number(row.get('cost_usd'), zero=True)
    if row.get('cost_kind') == 'TOTAL':
        total = amount
    elif row.get('cost_kind') == 'PER_BASIS_K':
        if row.get('quantity_basis') not in BASES:
            raise ValueError('cost_source_basis_invalid')
        total = amount * _quantity(row, row['quantity_basis'])
    else:
        raise ValueError('cost_kind_invalid')
    return dict(total_usd=total, basis_k=quantity, unit_usd=_divide(total, quantity))


def estimate_layer(rows, layer, quantity_basis, *, upper=None):
    """Compute expected/safe/stress rates and quantity-weighted missing share.

    Rows are a caller-selected single comparable layer. Unknown quantities stay
    in coverage counts but cannot enter alpha's known-quantity denominator.
    Upper is a comparable rate/total with the same layer; its source evidence is
    retained by the caller. This arithmetic cannot certify that upper is a bound.
    """
    if quantity_basis not in BASES:
        raise ValueError('cost_target_basis_invalid')
    if any(not layer.get(key) for key in LAYER_FIELDS):
        raise ValueError('cost_layer_missing')
    def check_layer(row):
        if any((row.get('layer') or {}).get(key) != layer[key] for key in LAYER_FIELDS):
            raise ValueError('cost_layer_mismatch')
    known_quantity = missing_quantity = complete_quantity = complete_cost = Decimal(0)
    partial_cost = Decimal(0)
    unallocated_known_cost = Decimal(0)
    complete_rates, partial_rates, gaps, seen = [], [], [], set()
    incomplete_count = unknown_quantity_count = 0
    for row in rows:
        check_layer(row)
        key = row.get('order_key')
        if not key or key in seen:
            raise ValueError('cost_order_identity_duplicate_or_missing')
        seen.add(key)
        complete = row.get('cost_complete') is True and row.get('cost_usd') is not None
        incomplete_count += not complete
        if row.get('purchase_k') is None or quantity_basis == 'PROMISED_DELIVERED_K' and row.get('promised_bonus_k') is None:
            unknown_quantity_count += 1
            if row.get('cost_usd') is not None and row.get('cost_kind') == 'TOTAL':
                unallocated_known_cost += number(row['cost_usd'], zero=True)
            continue
        quantity = _quantity(row, quantity_basis)
        known_quantity += quantity
        if not complete:
            missing_quantity += quantity
        if row.get('cost_usd') is not None:
            normalized = normalize_cost(row, quantity_basis)
            if complete:
                complete_quantity += quantity
                complete_cost += normalized['total_usd']
                complete_rates.append(normalized['unit_usd'])
            else:
                partial_cost += normalized['total_usd']
                partial_rates.append(normalized['unit_usd'])
    expected = _divide(complete_cost, complete_quantity) if complete_quantity else None
    alpha = missing_quantity / known_quantity if known_quantity else None
    upper_rate = None
    if upper is not None:
        check_layer(upper)
        upper_rate = normalize_cost(upper, quantity_basis)['unit_usd']
    if unknown_quantity_count:
        gaps.append('unknown_quantity')
    if expected is None:
        gaps.append('complete_cost_sample_missing')
    if missing_quantity and upper_rate is None:
        gaps.append('same_layer_upper_missing')
    if upper_rate is not None and any(rate > upper_rate for rate in partial_rates):
        gaps.append('upper_below_known_partial')
    if expected is not None and upper_rate is not None and upper_rate < expected:
        gaps.append('upper_below_expected')
    safe = None
    if not gaps:
        safe = expected if not missing_quantity else _divide(
            complete_cost + missing_quantity * upper_rate, known_quantity)
    stress_values = complete_rates + ([upper_rate] if upper_rate is not None else [])
    stress = max(stress_values) if stress_values and not gaps else None
    return dict(status='PROOF_INCOMPLETE' if gaps else 'calculated',
                quantity_basis=quantity_basis, layer=dict(layer), orders=len(seen),
                incomplete_cost_orders=incomplete_count, unknown_quantity_orders=unknown_quantity_count,
                known_quantity_k=known_quantity, missing_cost_quantity_k=missing_quantity,
                alpha=alpha, expected_unit_usd=expected, safe_unit_usd=safe,
                stress_unit_usd=stress, known_partial_usd=partial_cost,
                unallocated_known_cost_usd=unallocated_known_cost, gaps=gaps)
