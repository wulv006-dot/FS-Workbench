import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'hermes-customer-lifecycle-20261019' / 'source'))
sys.path.insert(0, str(PROJECT / 'user-analytics-20261022' / 'source'))
sys.path.insert(0, str(PROJECT / 'nightly-reschedule-20261025' / 'source'))

from customer_tracking import SHANGHAI, Store
from vip_maintenance import VipMaintenance, vip_weekly_report


def moment(day, hour=0):
    return datetime(2026, 11, day, hour, tzinfo=SHANGHAI)


def payment(index, date, refund='none_observed', amount='350.00'):
    return dict(siteId='266', orderNo=f'order-{index}', paidAtShanghai=date.isoformat(),
                refundStatus=refund, afterSales='none_observed', amountUsd=amount, orderState='已完成',
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
        self.preferred = []
        self.preferred_complete = True
        self.requests = []

    def read_cohort(self, *, anchor, now):
        self.archive_calls += 1
        return dict(coverage={'complete': self.archive_complete, 'datesComplete': self.archive_complete},
                    buyers=self.entries)

    def read_preferred_cohort(self, *, anchor, now):
        return dict(coverage={'complete': self.preferred_complete, 'datesComplete': self.preferred_complete},
                    buyers=self.preferred)

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

    def batch(self, *case_ids, number=101, scope='uk_us', week='2026-11-16'):
        return dict(week=week, scope=scope, case_ids=list(case_ids), request_id=f'{number:032x}')

    def test_bulk_claim_keeps_scope_week_eligibility_owner_and_per_item_receipts(self):
        self.source.entries = [
            buyer(1, payment(1, moment(1))),
            buyer(2, payment(2, moment(9))),
            buyer(3, dict(payment(3, moment(9)), afterSales='problem')),
            buyer(4, payment(4, moment(1))),
            buyer(5, payment(5, moment(1))),
            buyer(6, payment(6, moment(1))),
            buyer(7, payment(7, moment(1))),
            buyer(8, payment(8, moment(1))),
        ]
        self.source.preferred = [dict(buyer(9, payment(9, moment(1))), scope='global_preferred')]
        self.vip.refresh()
        self.source.updated['buyer-6'] = [payment(6, moment(1)), payment(10, moment(16, 8))]
        self.now = moment(17, 7)
        self.vip.refresh()
        cases = {int(case['uid']): case for case in self.vip.queue(actor='operator')['items']}
        self.write(cases[4], 'claim', 1, actor='someone_else')
        self.write(cases[5], 'claim', 2)
        self.write(cases[5], 'close', 3)
        self.write(cases[8], 'claim', 4)
        with self.store.db() as db:
            observed = db.execute('SELECT observation FROM vip_cases WHERE id=?', (cases[7]['case_id'],)).fetchone()
            snapshot = json.loads(observed[0])
            snapshot['paymentCoverage']['complete'] = False
            db.execute('UPDATE vip_cases SET observation=? WHERE id=?', (json.dumps(snapshot), cases[7]['case_id']))
        preferred_case = self.vip.queue(scope='global_preferred')['items'][0]
        cases[9] = preferred_case
        queue = self.vip.queue(actor='operator')
        self.assertEqual(queue['viewer'], 'operator')
        self.assertEqual({int(row['uid']) for row in queue['items'] if row['can_bulk_claim']}, {1, 3})
        body = self.batch(*(cases[index]['case_id'] for index in range(1,10)), 'f' * 32)
        receipt = self.vip.bulk_claim('operator', body)
        self.assertEqual((receipt['status'], receipt['claimed'], receipt['skipped'], receipt['reused']), ('recorded', 2, 8, False))
        self.assertEqual([item['reason_code'] for item in receipt['items']], [
            'claimed', 'not_due', 'claimed', 'assigned_to_other', 'closed', 'returned',
            'payment_unverified', 'already_claimed', 'not_member', 'not_member',
        ])
        self.assertNotIn('someone_else', json.dumps(receipt))
        request = self.vip.lookup_receipt('operator', body['request_id'])
        self.assertEqual(request, dict(status='available', action='vip_bulk_claim', result=receipt))
        self.assertEqual(self.vip.bulk_claim('operator', body), dict(receipt, reused=True))
        with self.assertRaisesRegex(ValueError, 'vip_bulk_claim_conflict'):
            self.vip.bulk_claim('operator', dict(body, case_ids=body['case_ids'][:1]))
        for owner_only in (lambda: self.vip.bulk_claim('someone_else', body),
                           lambda: self.vip.lookup_receipt('someone_else', body['request_id'])):
            with self.assertRaises(PermissionError):
                owner_only()
        self.assertEqual(self.store.request(body['request_id'])['result'], {'status':'private_receipt'})
        claimed = next(row for row in self.vip.queue(actor='operator')['items'] if row['case_id'] == cases[1]['case_id'])
        self.assertEqual(claimed['events'][0]['event'], 'claim')
        self.assertFalse(claimed['can_bulk_claim'])
        with self.assertRaisesRegex(ValueError, 'vip_already_assigned'):
            self.write(claimed, 'claim', 7)
        self.assertEqual(self.write(claimed, 'feedback', 8, notes='fixture')['owner'], 'operator')
        self.now = moment(23, 8)
        self.assertTrue(self.vip.bulk_claim('operator', body)['reused'])
        with self.assertRaisesRegex(ValueError, 'vip_bulk_claim_current_week'):
            self.vip.bulk_claim('operator', dict(body, request_id='e' * 32))
        self.assertFalse(any(row['can_bulk_claim'] for row in self.vip.queue('2026-11-16', actor='operator')['items']))

    def test_bulk_claim_race_and_original_authenticated_request_route(self):
        from tracking_controller import TrackingController

        self.vip.refresh()
        case, *_ = self.vip.queue(actor='operator')['items']
        controller = TrackingController(self.store.path.parent, lambda actor: actor in ('operator', 'other'), auto_start=False)
        controller.vip = self.vip
        barrier = Barrier(2)

        def claim(actor, number):
            body = self.batch(case['case_id'], number=number)
            barrier.wait(timeout=5)
            return controller.post(actor, dict(kind='hermes_customer_tracking', action='vip_bulk_claim', **body))

        with ThreadPoolExecutor(max_workers=2) as executor:
            attempts = [executor.submit(claim, actor, number) for actor, number in [('operator', 101), ('other', 102)]]
            outcomes = [(actor, task.result(timeout=10)) for actor, task in zip(('operator', 'other'), attempts)]
        self.assertEqual(sorted(data['claimed'] for _, (_, data) in outcomes), [0, 1])
        for actor, (status, data) in outcomes:
            self.assertEqual(status, 200)
            self.assertEqual(data['items'][0]['reason_code'], 'claimed' if data['claimed'] else 'assigned_to_other')
            params = dict(mode=['hermes'], structure=['customer_tracking'], view=['request'], request_id=[data['request_id']])
            self.assertEqual(controller.get(actor, params)[1]['result'], data)
            with self.assertRaises(PermissionError):
                controller.get('other' if actor == 'operator' else 'operator', params)
        with self.assertRaises(PermissionError):
            controller.post('unauthorized', dict(kind='hermes_customer_tracking', action='vip_bulk_claim',
                                                 **self.batch(case['case_id'])))

    def test_bulk_limit_and_unknown_marked_only_after_authenticated_valid_request(self):
        ids = [f'{number:032x}' for number in range(100)]
        payload = self.batch(*ids)
        wire = dict(kind='hermes_customer_tracking', action='vip_bulk_claim', **payload)
        self.assertLess(len(json.dumps(wire).encode()), 16384)
        self.assertIsNone(self.vip.lookup_receipt('operator', payload['request_id']))
        for invalid in (dict(payload, case_ids=[]), dict(payload, case_ids=[*ids, 'f' * 32]),
                        dict(payload, case_ids=['f' * 32, 'f' * 32]), dict(payload, owner='other')):
            with self.assertRaisesRegex(ValueError, 'vip_bulk_claim_fields'):
                self.vip.bulk_claim('operator', invalid)
            self.assertIsNone(self.vip.lookup_receipt('operator', payload['request_id']))
        result = self.vip.bulk_claim('operator', payload)
        self.assertEqual((result['claimed'], result['skipped']), (0, 100))
        self.assertTrue(all(row['reason_code'] == 'not_member' for row in result['items']))

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

    def test_preferred_scope_shares_claim_preserves_scope_clock_and_includes_watch(self):
        original = self.source.entries[0]
        self.source.entries = [original]
        recent = dict(payment(10, moment(15)), afterSales='problem')
        raw = original['history'][0]
        self.source.preferred = [
            dict(original, scope='global_preferred', history=[raw, recent], lastOrder=raw,
                 lastObservedOrder=recent, checksBeforeContact=['latest_payment_or_after_sales_needs_review'],
                 quality={'effectivePurchaseDays': 2}),
            dict(buyer(3, payment(11, moment(12))), scope='global_preferred', quality={'effectivePurchaseDays': 2})]
        self.vip.refresh()
        british = self.vip.queue(actor='operator')['items'][0]
        preferred = self.vip.queue(actor='operator', scope='global_preferred')
        first, watch = preferred['items']
        self.assertEqual(british['case_id'], first['case_id'])
        self.assertEqual((first['guidance']['band'], watch['cycle']['status']), ('P2', 'normal'))
        self.assertEqual((first['can_update'], watch['can_update']), (True, False))
        with self.assertRaisesRegex(ValueError, 'vip_not_due'):
            self.write(watch, 'claim', 3, scope='global_preferred')
        with self.assertRaisesRegex(ValueError, 'vip_not_due'):
            self.write(watch, 'claim', 4)
        self.write(first, 'claim', 5, scope='global_preferred')
        self.assertEqual(self.vip.queue()['items'][0]['owner'], 'operator')
        self.write(british, 'feedback', 6, reason='no_reply')
        preferred = self.vip.queue(scope='global_preferred')
        self.assertEqual(preferred['items'][0]['reason'], 'no_reply')
        self.assertEqual((preferred['summary']['p2_people'], preferred['summary']['normal_cycle_people']), (1, 1))
        self.vip.refresh()
        aggregate = json.loads((self.report_root/'vip-maintenance-2026-11-16.json').read_bytes())
        self.assertEqual(aggregate['scopes']['global_preferred']['summary']['people'], 2)
        self.assertNotIn('@example.test', json.dumps(aggregate))

    def test_preferred_new_week_carries_only_owned_or_requalified_cases(self):
        self.source.entries = []
        self.source.preferred = [
            dict(buyer(n, payment(n, moment(1))), scope='global_preferred') for n in (1, 2, 3)]
        self.vip.refresh()
        first_week = {item['uid']: item for item in self.vip.queue(scope='global_preferred')['items']}
        self.write(first_week['1'], 'claim', 1, scope='global_preferred')
        retained = self.source.preferred[2]
        new_windows = {key: dict(window, salesUsd='500.00') if key == 'month' else window
                       for key, window in retained['windows'].items()}
        self.source.preferred = [dict(retained, windows=new_windows)]
        self.now = moment(23, 7)
        self.vip.refresh()
        second_week = {item['uid']: item for item in self.vip.queue(scope='global_preferred')['items']}
        self.assertEqual(set(second_week), {'1', '3'})
        self.assertTrue(second_week['1']['carried_over'])
        self.assertFalse(second_week['3']['carried_over'])
        self.assertEqual(second_week['3']['case_id'], first_week['3']['case_id'])
        self.assertEqual(second_week['3']['windows']['month']['salesUsd'], '500.00')
        past = {item['uid']: item for item in self.vip.queue('2026-11-16', scope='global_preferred')['items']}
        self.assertEqual(set(past), {'1', '2', '3'})
        self.assertEqual(past['3']['windows']['month']['salesUsd'], '350.00')

    def test_shared_customer_requalifies_after_repurchase_without_losing_next_cohort(self):
        original, peer = self.source.entries
        self.source.preferred = [dict(record, scope='global_preferred') for record in (original, peer)]
        self.vip.refresh()
        previous = {item['uid']: item for item in self.vip.queue(scope='global_preferred')['items']}
        self.assertIn(previous['1']['case_id'], {item['case_id'] for item in self.vip.queue()['items']})
        self.write(previous['1'], 'claim', 1, scope='global_preferred')

        later = dict(buyer(1, *original['history'], payment(101, moment(20, 8))), followUpStatus='recent')
        self.source.updated[original['buyerId']] = later['history']
        self.now = moment(20, 12)
        refresh_buyers = self.source.refresh_buyers

        def observation_with_last_order(*args, **kwargs):
            result = refresh_buyers(*args, **kwargs)
            for item in result['buyers']:
                item['lastOrder'] = item['history'][-1]
            return result

        with patch.object(self.source, 'refresh_buyers', side_effect=observation_with_last_order):
            self.vip.refresh()
        returned = next(item for item in self.vip.queue()['items'] if item['uid'] == '1')
        self.assertEqual(returned['outcome']['kind'], 'natural')

        self.source.entries = [later, peer]
        self.source.preferred = [dict(record, scope='global_preferred') for record in (later, peer)]
        self.now = moment(23, 7)
        refresh = self.vip.refresh()
        self.assertEqual(refresh['scope_status']['global_preferred'], 'ready')
        next_week = {item['uid']: item for item in self.vip.queue('2026-11-23', scope='global_preferred')['items']}
        self.assertEqual(set(next_week), {'1', '2'})
        self.assertNotEqual(next_week['1']['case_id'], previous['1']['case_id'])
        self.assertEqual((next_week['1']['cycle']['status'], next_week['1']['owner']), ('normal', None))
        self.assertEqual(next_week['2']['case_id'], previous['2']['case_id'])
        history = {item['uid']: item for item in self.vip.queue('2026-11-16', scope='global_preferred')['items']}
        self.assertEqual(history['1']['case_id'], previous['1']['case_id'])
        self.assertEqual((history['1']['outcome']['kind'], history['1']['owner']), ('natural', 'operator'))

    def test_scope_failure_leaves_original_queue_available(self):
        self.source.preferred_complete = False
        result = self.vip.refresh()
        self.assertEqual(result['scope_status'], {'uk_us': 'ready', 'global_preferred': 'partial'})
        self.assertEqual(self.vip.queue()['summary']['people'], 2)
        self.assertIsNone(self.vip.queue(scope='global_preferred')['summary'])

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
