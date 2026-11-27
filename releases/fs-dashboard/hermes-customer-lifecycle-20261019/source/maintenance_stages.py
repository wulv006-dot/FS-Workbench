"""As-of FC27 stage snapshots and durable stage-entry identities."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from customer_segments import SHANGHAI, stage, tier
from maintenance_review import coupon_time, digest


GID = '1327'
RANK = {'recent': 0, 'silent': 1, 'lost': 2, 'long_lost': 3}
FOLLOW_UP = ('silent', 'lost', 'long_lost')
BANDS = tuple((value, phase) for value in ('ultra', 'high') for phase in ('lost', 'long_lost'))
COUPON_FIELDS = ('mode_type', 'reduce', 'max_reduce', 'time_effect', 'days', 'start_time', 'end_time')


def day_start(day):
    return datetime.combine(day, time.min, tzinfo=SHANGHAI)


def day_end(day):
    return day_start(day + timedelta(days=1))


def payment(row):
    return datetime.fromisoformat(row['paid_at']).astimezone(SHANGHAI)


def cohort(orders, day, config, covered):
    by_customer = defaultdict(list)
    for row in orders:
        if row['valid'] and row.get('customer_id') and payment(row) < day_end(day):
            by_customer[row['customer_id']].append(row)
    result = {}
    for customer, paid in by_customer.items():
        fc = [row for row in paid if str(row['gid']) == GID]
        if not fc:
            continue
        amounts = [Decimal(str(row['amount_usd'])) for row in fc if row['amount_usd'] is not None]
        total = sum(amounts, Decimal(0))
        value = tier(total, GID, config)
        if value is None:
            continue
        first = min(paid, key=lambda row: (payment(row), row['order_key']))
        last = max(fc, key=lambda row: (payment(row), row['order_key']))
        last_paid = payment(last)
        flag = first.get('new_customer_flag')
        result[customer] = dict(customer_id=customer, tier=value, gid=GID,
                                stage=stage(last_paid, day, GID, config, covered(
                                    day_start(last_paid.date() + timedelta(days=1)), day_end(day))),
                                customer_type=flag if flag in ('new', 'old') else 'unverified',
                                email=last.get('email'), uid=last.get('uid'), last_order_key=last['order_key'],
                                last_paid_at=last_paid.isoformat(), amount_usd=f'{total:.2f}',
                                purchase_days=len({payment(row).date() for row in fc}),
                                unknown_amount_orders=len(fc) - len(amounts),
                                observation_date=day.isoformat(), config_version=config['version'])
    return result


def new_event(previous, current):
    if not previous or current['stage'] not in FOLLOW_UP or previous['stage'] not in RANK:
        return None
    if any(previous[field] != current[field] for field in ('last_order_key', 'config_version')):
        return None
    if RANK[previous['stage']] >= RANK[current['stage']]:
        return None
    key = [current[field] for field in ('customer_id', 'gid', 'stage', 'last_order_key', 'config_version')]
    return dict(current, id='me_' + digest(key),
                event_at=day_end(date.fromisoformat(current['observation_date'])).isoformat())


def matches_rule(rule, customer):
    return (customer['tier'] == rule['tier'] and customer['stage'] == rule['stage']
            and (rule['customer_type'] is None or customer['customer_type'] == rule['customer_type']))


def stock_event(customer, at):
    key = [customer[field] for field in ('customer_id', 'stage', 'last_order_key', 'config_version')]
    return dict(customer, id='me_' + digest([*key, 'stock']), event_at=at.isoformat(), origin='stock')


def coupon_terms(rule):
    return {key: value for key, value in (rule.get('template') or {}).items() if key in COUPON_FIELDS}


def rank_customers(customers):
    ranked = {band: [] for band in BANDS}
    for customer in customers:
        band = customer['tier'], customer['stage']
        if band not in ranked:
            continue
        paid = coupon_time(customer['last_paid_at']).astimezone(SHANGHAI)
        overdue = (date.fromisoformat(customer['observation_date']) - paid.date()).days
        total = Decimal(customer['amount_usd'])
        days = customer['purchase_days']
        ceiling = 3000 if customer['tier'] == 'ultra' else 1000
        start, span = (30, 30) if customer['stage'] == 'lost' else (60, 90)
        freshness = max(0, min(span, start + span - overdue))
        score = (min(total / ceiling, 1) * 50 + Decimal(min(days, 10)) * 25 / 10
                 + Decimal(freshness) * 25 / span)
        reason = f"累计 ${total:,.2f}，{days} 个购买日，{('流失' if start == 30 else '长期流失')}第 {overdue} 天"
        key = (-score, -total, overdue, customer['customer_id'])
        ranked[band].append((key, dict(customer, score=float(round(score, 2)),
                                       days_since_last_paid=overdue, reason=reason)))
    return {band: [dict(row, rank=index) for index, (_, row) in enumerate(sorted(rows), 1)]
            for band, rows in ranked.items()}
