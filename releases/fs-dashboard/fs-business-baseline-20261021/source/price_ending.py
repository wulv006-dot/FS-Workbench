"""User-approved .99 preference for package-total previews; never writes prices."""
from decimal import Decimal, ROUND_FLOOR


def package_ending(price, delivered_cost_usd, minimum_margin_pct):
    price, cost, floor = map(lambda x: Decimal(str(x)), (price, delivered_cost_usd, minimum_margin_pct))
    if not all(v.is_finite() for v in (price, cost, floor)) or price <= 0 or cost <= 0 or not 0 <= floor < 100:
        raise ValueError('price_ending_inputs')
    integer = price.to_integral_value(rounding=ROUND_FLOOR)
    target = price if price%1==Decimal('0.99') else integer - Decimal('0.01')
    # A near-integer preference has a bounded business cost, not a fixed dollar window.
    margin = 1 - cost / price
    limits = {'revenue_one_percent':price * Decimal('0.01'),
              'gross_profit_five_percent':max(Decimal(0),price-cost) * Decimal('0.05'),
              'margin_one_percentage_point':price-cost/(cost/price+Decimal('0.01')),
              'existing_margin_floor':price-cost/(1-floor/100)}
    budget = max(Decimal(0),min(limits.values()))
    eligible = integer >= 1 and target > 0
    allowed = eligible and price-target <= budget
    result = target if allowed else price
    return {'original_package_usd': str(price), 'package_usd': str(result), 'delivered_cost_usd': str(cost),
            'reduction_usd': str(price - result), 'margin_pct': str((1 - cost / result) * 100),
            'allowed_reduction_usd':str(budget), 'reduction_limits_usd':{k:str(v) for k,v in limits.items()},
            'margin_decrease_pp':str((margin-(1-cost/result))*100),
            'reason': 'already_99' if price%1==Decimal('0.99') else 'applied' if allowed else 'margin_floor' if eligible and price-target>limits['existing_margin_floor'] else 'adaptive_budget_exceeded' if eligible else 'no_positive_ending',
            'rule': 'adaptive-package-ending-20261021-v1', 'control_basis':'implementation: <=1% revenue, <=5% gross profit, <=1pp margin, original margin floor',
            'price_writes': False}
