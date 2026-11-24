"""As-of FC27 stage snapshots and durable stage-entry identities."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from customer_segments import SHANGHAI, stage, tier
from maintenance_review import digest


GID = '1327'
RANK = {'recent': 0, 'silent': 1, 'lost': 2, 'long_lost': 3}
FOLLOW_UP = ('silent', 'lost', 'long_lost')


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