"""Rule-level outcomes and single attribution for issued-coupon returns."""
from collections import defaultdict
from datetime import datetime, timedelta

from maintenance_stages import GID, day_end, payment
from maintenance_review import coupon_time


def effects(entries, orders, logs, days, observation, covered, baseline=None):
    horizon = timedelta(days=days)
    end = day_end(observation)
    by_customer = defaultdict(list)
    by_batch = {}
    main_orders = {}
    coupon_numbers = {log['order_no'] for log in logs or () if log.get('order_no')}
    customers = {entry['customer_id'] for entry in entries}
    summaries = {}
    for row in orders:
        if row.get('order_no') in coupon_numbers:
            main_orders[row['order_no']] = row
        if row['valid'] and str(row['gid']) == GID and row.get('customer_id') in customers:
            by_customer[row['customer_id']].append(row)
    attributed = {}
    for entry in entries:
        rule = entry['rule_id']
        summary = summaries.setdefault(rule, dict(rule_id=rule, trigger_events=0, trigger_returned=0,
                                                   issued_events=0, issued_returned=0, issued_orders=0,
                                                   coupon_uses=0 if logs is not None else None,
                                                   coupon_paid_uses=0 if logs is not None else None,
                                                   unknown=0, deferred=0))
        summary['unknown'] += entry['state'] == 'unknown'
        summary['deferred'] += entry['state'] == 'deferred'
        begins = datetime.fromisoformat(entry['event_at'])
        until = begins + horizon
        if until > end or not covered(begins, until):
            continue
        summary['trigger_events'] += 1
        returned = [row for row in by_customer.get(entry['customer_id'], ()) if begins <= payment(row) < until]
        summary['trigger_returned'] += bool(returned)
        if entry['state'] != 'issued':
            continue
        summary['issued_events'] += 1
        dispatch = datetime.fromisoformat(entry['dispatch_at'])
        by_batch[entry['batch']] = (entry, begins, until)
        for row in returned:
            if payment(row) <= dispatch:
                continue
            existing = attributed.get(row['order_key'])
            if existing is None or (dispatch > existing[0]
                                    or dispatch == existing[0] and entry['id'] < existing[1]['id']):
                attributed[row['order_key']] = (dispatch, entry)
    returned_by_rule = defaultdict(set)
    for _, entry in attributed.values():
        summaries[entry['rule_id']]['issued_orders'] += 1
        returned_by_rule[entry['rule_id']].add(entry['id'])
    seen = set()
    for log in logs or ():
        batch = (log.get('memberCoupon') or {}).get('grant_batch_no')
        if batch not in by_batch:
            continue
        entry, begins, until = by_batch[batch]
        if 'use_time' in log and not begins <= coupon_time(log['use_time']) < until:
            continue
        identity = (batch, log.get('order_no') or log.get('id'))
        if identity in seen:
            continue
        seen.add(identity)
        summary = summaries[entry['rule_id']]
        summary['coupon_uses'] += 1
        order = main_orders.get(log.get('order_no'))
        pay_status = str(order.get('pay_status')) if order else str(log.get('status'))
        summary['coupon_paid_uses'] += pay_status in ('1', '2') if order else pay_status == '1'
    result = []
    for rule, summary in sorted(summaries.items()):
        summary['issued_returned'] = len(returned_by_rule[rule])
        for prefix in ('trigger', 'issued'):
            n = summary[prefix + '_events']
            summary[prefix + '_rate'] = summary[prefix + '_returned'] / n if n else None
        summary['baseline'] = (baseline or {}).get(rule)
        result.append(summary)
    return result