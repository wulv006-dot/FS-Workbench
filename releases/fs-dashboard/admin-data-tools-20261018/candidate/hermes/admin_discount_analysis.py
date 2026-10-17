"""Aggregate the observed ES discount fields; never emit orders or coupon codes."""
from collections import defaultdict
from decimal import Decimal

FIELDS = ('优惠类型', '折扣比例', '折扣金额')
GROUPS = ('discount_new_customer', 'discount_type', 'discount_day')
POLICY_VERSION = 'es-discount-usd-user-confirmed-20261018-v1'


def project(rows, args, base, amount, safe_label):
    groups = {}
    missing = 0
    for row in rows:
        new = row.get('是否新客户', '').strip()
        new = '新客订单' if new == '是' else '老客订单' if new == '否' else '新老客未知'
        state = safe_label(row.get('订单状态'))
        offer = safe_label(row.get('优惠类型'))
        dimension = (offer if args['group_by'] == 'discount_type' else
                     row['付款时间'][:10].replace('/', '-') if args['group_by'] == 'discount_day' else new)
        key = (dimension, new, state)
        bucket = groups.setdefault(key, {'label': dimension, 'new_customer': new,
            'order_status': state, 'orders': 0, 'known_discount_orders': 0,
            'unknown_discount_orders': 0, 'positive_discount_orders': 0,
            'negative_discount_orders': 0, 'with_discount_code_orders': 0,
            'discount_amount_usd': Decimal(0), 'order_amount_usd': Decimal(0),
            'known_order_amount_orders': 0})
        bucket['orders'] += 1
        discount = amount(row.get('折扣金额'))
        if discount is None:
            missing += 1
            bucket['unknown_discount_orders'] += 1
        else:
            bucket['known_discount_orders'] += 1
            bucket['discount_amount_usd'] += discount
            bucket['positive_discount_orders'] += discount > 0
            bucket['negative_discount_orders'] += discount < 0
        usd = amount(row.get('订单金额（美元）'))
        if usd is not None:
            bucket['order_amount_usd'] += usd
            bucket['known_order_amount_orders'] += 1
        bucket['with_discount_code_orders'] += bool(row.get('_has_discount_code', row.get('折扣码')))
    def total(buckets):
        count = sum(b['known_discount_orders'] for b in buckets)
        return {'orders': sum(b['orders'] for b in buckets), 'known_discount_orders': count,
                'unknown_discount_orders': sum(b['unknown_discount_orders'] for b in buckets),
                'discount_amount_usd': str(sum((b['discount_amount_usd'] for b in buckets), Decimal(0))) if count else None}
    values = list(groups.values())
    totals = total(values)
    if not rows and base['status'] == 'available':
        totals['discount_amount_usd'] = '0'
    base['discount_totals'] = totals
    base['new_customer_order_discount_totals'] = total([b for b in values if b['new_customer'] == '新客订单'])
    for b in values:
        b['discount_amount_usd'] = str(b['discount_amount_usd']) if b['known_discount_orders'] else None
        b['order_amount_usd'] = str(b['order_amount_usd']) if b['known_order_amount_orders'] else None
    values.sort(key=lambda b: (b['label'], b['new_customer'], b['order_status']))
    # shortcut: bounded public response; expand the budget only with a caller needing more categories.
    base['groups'] = values[:200]
    base['quality'].update(discount_policy_version=POLICY_VERSION,
        discount_currency='USD', discount_currency_basis='user final correction 2026-10-18: source 折扣金额 is uniformly USD',
        unknown_discount_orders=missing, discount_group_count=len(values), discount_groups_truncated=len(values) > 200,
        top_limit=200, total_group_count=len(values),
        discount_fields={k: sum(k in r for r in rows) for k in FIELDS},
        discount_basis='signed original export amount per deduplicated order; zero retained, missing is unknown',
        status_basis='all original statuses shown separately; not all rows are realized/completed concessions',
        customer_basis='export order flag 是/否; not unique customers or acquisition causality',
        new_customer_exclusive_attribution='unverified; do not equate new-customer orders with exclusive promotion redemption',
        refund_discount_reversal='unknown; original discount is not retained net discount',
        discount_rate=None, eligible_before_discount_base=None,
        raw_coupon_codes_exposed=False, original_paid_currency_policy='separate currencies; never subtract from USD',
        no_repeat_profit_deduction='do not subtract this discount again from revenue already net of it')
    if missing or len(values) > 200:
        base['status'] = 'partial'
    return base
