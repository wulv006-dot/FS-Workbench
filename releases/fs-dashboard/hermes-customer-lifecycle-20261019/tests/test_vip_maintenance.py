import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'hermes-customer-lifecycle-20261019' / 'source'))
sys.path.insert(0, str(PROJECT / 'nightly-reschedule-20261025' / 'source'))

from customer_tracking import SHANGHAI, Store
from vip_maintenance import VipMaintenance, vip_weekly_report


def moment(day, hour=0):
    return datetime(2026, 11, day, hour, tzinfo=SHANGHAI)


def payment(index, date, refund='none_observed', amount='350.00'):
    return dict(siteId='266', orderNo=f'order-{index}', paidAtShanghai=date.isoformat(),
                refundStatus=refund, afterSales='none_observed', amountUsd=amount,
                knownSettledRefundUsd=None, payStatus='1')


def buyer(index, *payments):
    last = payments[-1]
    return dict(buyerId=f'buyer-{index}', siteId='266', uid=str(index), email=f'buyer-{index}@example.test',
                identity={'uids': [str(index)], 'emails': [f'buyer-{index}@example.test']},
                country='US', history=list(payments), lastOrder=last, followUpStatus='due',
                paymentCoverage={'complete': False},
                windows={key: {'orders': 1, 'salesUsd': '350.00'} for key in ('month', 'firstHalf', 'secondHalf')})


class FakeSource:
    def __init__(self):
        self.archive_calls = self.live_calls = 0
        self.archive_complete = self.live_complete = True
        self.entries = [buyer(1, payment(1, moment(1))), buyer(2, payment(2, moment(1)))]
        self.updated = {}
        self.requests = []

    def read_cohort(self, *, anchor, now):
        self.archive_calls += 1
        return dict(coverage={'complete': self.archive_complete, 'datesComplete': self.archive_complete},
                    buyers=self.entries)

    def refresh_buyers(self, buyers, *, since, now, recheck_orders):
        self.live_calls += 1
        self.requests.append((since, {order['orderNo'] for order in recheck_orders}))
        through = now.isoformat() if self.live_complete else None
        entries = [dict(record, history=self.updated.get(record['buyerId'], record['history']),
                        paymentCoverage={'complete': self.live_complete, 'observedThrough': through, 'through': through})
                   for record in buyers]
        return dict(coverage={'complete': self.live_complete}, buyers=entries, asOfShanghai=now.isoformat())


class VipWorkflows(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'tracking')
        self.source = FakeSource()
        self.now = moment(16, 7)
        self.report_root = Path(temp.name)
        self.vip = VipMaintenance(self.store, self.source, clock=lambda: self.now, report_root=self.report_root)

    def write(self, case, event, number, actor='operator', **fields):
        return self.vip.feedback(actor, dict(case_id=case['case_id'], request_id=f'{number:032x}', event=event, **fields))

    def test_rollover_preserves_owner_feedback_and_idempotent_receipt(self):
        self.assertEqual(self.vip.refresh()['status'], 'ready')
        case = self.vip.queue(actor='operator')['items'][0]
        self.assertEqual(self.write(case, 'claim', 1)['owner'], 'operator')
        self.assertTrue(self.write(case, 'claim', 1)['reused'])
        self.assertTrue(self.vip.refresh()['reused'])
        with self.assertRaises(PermissionError):
            self.write(case, 'feedback', 2, actor='someone_else', notes='wrong owner')
        with self.assertRaises(ValueError):
            self.write(case, 'feedback', 1, notes='wrong request reuse')
        with self.assertRaises(PermissionError):
            self.vip.lookup_receipt('someone_else', f'{1:032x}')
        self.write(case, 'feedback', 2, reason='no_reply', next_review_day='2026-11-24')
        self.now = moment(23, 8)
        self.vip.refresh()
        next_case = next(item for item in self.vip.queue(actor='operator')['items'] if item['case_id'] == case['case_id'])
        self.assertEqual((next_case['status'], next_case['reason'], next_case['carried_over']), ('assigned', 'no_reply', True))
        self.assertEqual(len(self.vip.queue('2026-11-16')['items']), 2)
        self.assertEqual(self.source.archive_calls, 2)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tracks').fetchone()[0], 0)

    def test_shared_email_with_conflicting_member_id_preserves_separate_owners(self):
        self.source.entries = [buyer(1, payment(1, moment(1)))]
        self.vip.refresh()
        case = self.vip.queue()['items'][0]
        self.write(case, 'claim', 1)
        second = buyer(2, payment(2, moment(7)))
        second.update(email=case['email'], identity={'uids': ['2'], 'emails': [case['email']]})
        self.source.entries = [second]
        self.now = moment(23, 8)
        self.vip.refresh()
        self.assertEqual({item['uid']: item['owner'] for item in self.vip.queue()['items']},
                         {'1': 'operator', '2': None})

    def test_natural_and_contacted_payments_maturity_and_later_full_refund(self):
        self.vip.refresh()
        first, second = sorted(self.vip.queue()['items'], key=lambda row: row['uid'])
        self.write(first, 'claim', 1)
        self.write(second, 'claim', 2)
        first_order, second_order = [entry['history'][0] for entry in self.source.entries]
        self.now = moment(17, 7)
        self.write(first, 'contacted', 3, contacted_at=self.now.isoformat())
        self.write(second, 'contacted', 4, contacted_at=self.now.isoformat())
        self.source.updated.update({
            'buyer-1': [first_order, payment(3, moment(17, 6)), payment(4, moment(18, 6))],
            'buyer-2': [second_order, payment(5, moment(19, 8), amount='410.00')],
        })
        self.now = moment(20, 7)
        self.vip.refresh()
        midweek = self.vip.queue()['summary']
        self.assertEqual((midweek['natural_people'], midweek['post_contact_people'], midweek['immature_people']),
                         (1, 1, 2))
        self.assertEqual((midweek['natural_usd'], midweek['post_contact_usd']), ('350.00', '410.00'))
        self.assertEqual(midweek['mature_contacted_people'], 0)
        self.now = moment(23, 7)
        self.vip.refresh()
        report = vip_weekly_report(self.store.path, '2026-11-16', moment(23))
        self.assertEqual(report['summary']['post_contact_people'], 1)
        self.assertNotIn('@example.test', json.dumps(report))
        self.now = moment(25, 7)
        self.source.updated['buyer-2'][-1]['refundStatus'] = 'full_observed'
        self.vip.refresh()
        self.assertEqual(self.source.requests[-1][0], moment(23, 7))
        self.assertIn('order-5', self.source.requests[-1][1])
        historical = self.vip.queue('2026-11-16')['summary']
        self.assertEqual((historical['natural_people'], historical['post_contact_people'],
                          historical['mature_contacted_people']), (1, 0, 1))

    def test_partial_coverage_preserves_unknown_and_does_not_freeze_early(self):
        self.source.archive_complete = False
        self.assertEqual(self.vip.refresh()['status'], 'partial')
        self.assertIsNone(self.vip.queue()['summary'])
        self.source.archive_complete = True
        self.source.live_complete = False
        self.now += timedelta(minutes=31)
        self.assertEqual(self.vip.refresh()['status'], 'partial')
        self.assertEqual(self.vip.queue()['summary']['unknown_people'], 2)
        report = vip_weekly_report(self.store.path, '2026-11-16', moment(23))
        self.assertFalse(report['payment_complete'])
        self.assertEqual(report['reason'], 'vip_week_partial_coverage')

    def test_guidance_uses_each_buyers_payment_pattern(self):
        multiple = buyer(1, payment(1, moment(1) - timedelta(days=6)), payment(2, moment(1) - timedelta(days=3)),
                         dict(payment(3, moment(1)), platform='PS', purchaseK='600'))
        stocked = buyer(2, dict(payment(4, moment(1)), platform='PC', purchaseK='5000'))
        self.source.entries = [stocked, multiple]
        self.vip.refresh()
        first, second = self.vip.queue()['items']
        self.assertEqual((first['uid'], first['guidance']['median_gap_days']), ('1', 3.0))
        self.assertIn('观察到 3 个购买日', first['guidance']['reason'])
        self.assertIn('PS 600K', first['guidance']['reason'])
        self.assertIn('PC 5000K', second['guidance']['reason'])
        self.assertIn('提前备量', second['guidance']['reason'])

    def test_report_context_consumes_aggregate_only_on_weekly_entry(self):
        fake_source_snapshots = SimpleNamespace(archive_status=lambda query: query)
        fake_nightly = SimpleNamespace(closed_period=lambda day, kind: ('2026-11-16', '2026-11-22'))
        self.vip.refresh()
        with patch.dict(sys.modules, source_snapshots=fake_source_snapshots, nightly=fake_nightly):
            from nightly_data import report_context
            with patch('nightly_data.VIP_REPORT_ROOT', self.report_root):
                weekly = report_context(moment(23, 3), 'weekly')
                self.assertEqual(weekly['vip_maintenance']['summary']['people'], 2)
                self.assertNotIn('vip_maintenance', report_context(moment(23, 3), 'daily'))
                self.assertNotIn('@example.test', json.dumps(weekly))
                archive = self.report_root / 'vip-maintenance-2026-11-16.json'
                archive.write_text(archive.read_text(encoding='utf-8').replace(
                    '2026-11-23T00:00:00', '2026-11-24T00:00:00'), encoding='utf-8')
                self.assertEqual(report_context(moment(23, 3), 'weekly')['vip_maintenance']['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
