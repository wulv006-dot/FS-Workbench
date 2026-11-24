"""Stages, stock and event identity derived from the closed order projection."""
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'source'), str(ROOT.parent / 'customer-segments-20261124' / 'source')]
from maintenance_stages import cohort, new_event, matches_rule
from maintenance_effects import effects


CONFIG = dict(version=0, stages={'1327': [14, 30, 60]}, tiers={})


def order(key, at, usd, *, customer='c1', gid='1327', valid=True, flag=None):
    return dict(order_key=key, paid_at=at + 'T12:00:00+08:00', customer_id=customer,
                gid=gid, amount_usd=usd, valid=valid, new_customer_flag=flag)


class Stages(unittest.TestCase):
    def get(self, orders, day, config=CONFIG, covered=lambda a, b: True):
        return cohort(orders, date.fromisoformat(day), config, covered).get('c1')

    def test_exact_gate_unknown_amount_and_newness_use_site_first_order(self):
        rows = [order('before', '2026-09-05', '30', gid='5', flag='old'),
                order('fc1', '2026-10-01', '500.00', flag='new'),
                order('fc2', '2026-10-02', None)]
        view = self.get(rows, '2026-10-16')
        self.assertEqual(('high', 'old', 'silent', 1, 'fc2'),
                         (view['tier'], view['customer_type'], view['stage'],
                          view['unknown_amount_orders'], view['last_order_key']))
        rows[1]['amount_usd'] = '499.99'
        self.assertIsNone(self.get(rows, '2026-10-16'))
        config = dict(CONFIG, version=1, tiers={'1327': dict(high='499.99', ultra='1000')})
        self.assertEqual('high', self.get(rows, '2026-10-16', config)['tier'])
        self.assertEqual('unverified', self.get(rows, '2026-10-16', config, lambda a, b: False)['stage'])

    def test_stock_version_backfill_refund_and_missed_day(self):
        rows = [order('b', '2026-10-01', '600', flag='new'),
                order('after', '2026-10-18', '200', flag='old')]
        recent = self.get(rows, '2026-10-14')
        silent = self.get(rows, '2026-10-15')
        self.assertIsNone(new_event(None, recent))
        event = new_event(recent, silent)
        self.assertEqual(('silent', 'b'), (event['stage'], event['last_order_key']))
        self.assertIsNone(new_event(silent, self.get(rows, '2026-10-16')))
        self.assertIsNone(new_event(recent, dict(silent, config_version=1)))
        self.assertIsNone(new_event(recent, dict(silent, last_order_key='correction')))
        self.assertEqual('recent', self.get(rows, '2026-10-18')['stage'])
        rows[0]['valid'] = False
        self.assertIsNone(self.get(rows, '2026-10-15'))
        self.assertFalse(matches_rule(dict(tier='ultra', stage='silent', customer_type=None), silent))

    def test_repurchase_uses_latest_issued_once_and_coupon_use_can_be_unpaid(self):
        entries = [
            dict(id='a', rule_id='r1', state='issued', customer_id='c1', batch='old',
                 event_at='2026-10-01T00:00:00+08:00', dispatch_at='2026-10-01T00:00:00+08:00'),
            dict(id='b', rule_id='r2', state='issued', customer_id='c1', batch='new',
                 event_at='2026-10-02T00:00:00+08:00', dispatch_at='2026-10-03T00:00:00+08:00'),
            dict(id='c', rule_id='r3', state='issued', customer_id='c1', batch='tie',
                 event_at='2026-10-02T00:00:00+08:00', dispatch_at='2026-10-03T00:00:00+08:00'),
        ]
        logs = [dict(id=1, order_no='paid', status=1, memberCoupon={'grant_batch_no': 'new'}),
                dict(id=2, order_no='unpaid', status=0, memberCoupon={'grant_batch_no': 'new'})]
        rows = [order('res', '2026-10-05', '25')]
        result = effects(entries, rows, logs, 7, date(2026, 11, 24), lambda a, b: True)
        self.assertEqual([1, 1, 1], [row['trigger_returned'] for row in result])
        self.assertEqual([0, 1, 0], [row['issued_orders'] for row in result])
        self.assertEqual([0, 2, 0], [row['coupon_uses'] for row in result])
        self.assertEqual([0, 1, 0], [row['coupon_paid_uses'] for row in result])