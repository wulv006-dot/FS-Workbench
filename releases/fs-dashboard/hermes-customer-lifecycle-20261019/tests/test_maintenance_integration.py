"""Exercise the stage-maintenance entry points with offline source adapters."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tracemalloc
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / 'source'),
    str(ROOT.parent / 'customer-segments-20261124' / 'source'),
    str(ROOT.parent / 'user-analytics-20261022' / 'source'),
]
from customer_segments import ConfigCommitUnknown, load_config, write_config
from customer_tracking import Store
from maintenance_sources import AdminFacts, Facts, UserProjection
from maintenance_service import Maintenance
from tracking_controller import TrackingController
from user_contract import digest as publication_digest
from user_weekly import CONTRACT as PUBLICATION_CONTRACT, META as PUBLICATION_META
from vip_maintenance import PREFERRED, UK_US, VipMaintenance, record_event
from test_vip_maintenance import FakeSource, buyer, payment


SH = timezone(timedelta(hours=8))
INIT = datetime(2026, 10, 14, 8, tzinfo=SH)
TEMPLATE = dict(id=123, site_id=266, game_id=1327, fetch_scene=4, status=1, time_effect=2, days=7)


def order(ident='a', customer='customer-A', uid=100, address='buyer@example.net', valid=True):
    return dict(customer_id=customer, order_key='admin:266:' + ident, order_no=ident,
                paid_at='2026-10-01T12:00:00+08:00', gid='1327', valid=valid,
                amount_usd='500', pay_status='1', uid=uid, email=address, new_customer_flag='new')


class Source:
    def __init__(self):
        self.current = INIT.replace(hour=0)
        self.revision = '1'
        self.orders = [order()]

    def token(self):
        return 'publication', self.revision

    def coupon_orders(self, numbers, token):
        assert self.token() == token
        return [row for row in self.orders if row['order_no'] in numbers]

    def read(self, now, latest=False):
        receipt = dict(publication_id='publication', cutoff=self.current.isoformat())
        return Facts(receipt, list(self.orders), [
            dict(site='266', state='complete', start='2026-10-01T00:00:00+08:00', end=self.current.isoformat())
        ], self.token())


class Admin:
    def __init__(self):
        self.coupons = []
        self.issues = []

    def logs(self, start, stop):
        return []

    def exceptions(self, orders):
        return list(self.issues)

    def grants(self, uid):
        result = self.coupons.pop(0) if len(self.coupons) > 1 else self.coupons[0] if self.coupons else []
        if isinstance(result, Exception):
            raise result
        return result

    def recent_grant_members(self, at):
        return {str(row['member_id']) for rows in self.coupons if isinstance(rows, list)
                for row in rows if at - timedelta(days=30) < datetime.fromisoformat(row['start_time']) <= at}


class Bridge:
    def __init__(self):
        self.sent = []

    def detail(self, coupon):
        return TEMPLATE.copy()

    def grant(self, coupon, email, batch):
        self.sent.append((coupon, email, batch))
        return dict(state='confirmed', member_coupon_id='345')


class Integration(unittest.TestCase):
    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name) / 'tracking.db'
        self.path.touch(mode=0o600)
        self.store = SimpleNamespace(db=self.db, path=self.path)
        self.vip = VipMaintenance(self.store, clock=lambda: self.now)
        self.source, self.admin, self.bridge, self.now = Source(), Admin(), Bridge(), INIT
        self.service = Maintenance(self.store, source=self.source, admin=self.admin, bridge=self.bridge,
                                   config_path=self.path.with_name('segments.json'), clock=lambda: self.now)

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def tick(self, days=0, run=True):
        self.now += timedelta(days=days)
        self.source.current += timedelta(days=days)
        self.source.revision = str(int(self.source.revision) + 1)
        if run:
            self.service.update()

    def rule(self, owner=None):
        return self.service.save_rule('admin', dict(id='first', expected_version=0, tier='high', stage='silent',
                    customer_type='new', enabled=True, priority=0, daily_quota=1, coupon_id=123, alert=True, owner=owner))

    def create(self, owner=None):
        self.rule(owner=owner)
        self.tick()
        self.assertEqual([], self.service.queue_view('review')['items'])
        self.tick(2, run=False)
        self.service.advance(self.service.facts(), {'version':0, 'stages':{'1327':[14,30,60]}, 'tiers':{}})
        return self.service.ledger.queue(('reviewing',))[0]

    def grant(self, ident):
        return dict(id=ident, member_id=100, site_id=266, status=2, grant_batch_no='manual',
                    start_time=(self.now-timedelta(hours=1)).isoformat())

    def test_stock_recommendations_rank_before_limiting_and_confirm_only_displayed_ids(self):
        self.source.orders = [
            dict(order('late', 'customer-b', 101, 'b@example.net'), amount_usd='900'),
            dict(order('early', 'customer-a', 102, 'a@example.net'), amount_usd='400'),
            dict(order('same', 'customer-a', 102, 'a@example.net'),
                 amount_usd='250', paid_at='2026-10-02T01:00:00+13:00'),
            dict(order('next', 'customer-a', 102, 'a@example.net'),
                 amount_usd='250', paid_at='2026-10-02T01:00:00+08:00'),
        ]
        self.tick(20)
        self.service.save_rule('admin', dict(id='lost', expected_version=0, tier='high', stage='lost',
            customer_type='new', enabled=True, priority=0, daily_quota=50, coupon_id=123, alert=False, owner=None))
        self.service.update()
        result = self.service.recommendations(5)
        band = next(b for b in result['bands'] if (b['tier'], b['stage']) == ('high', 'lost'))
        first, second = band['items']
        self.assertEqual(2, band['pool_count'])
        self.assertEqual(['a@example.net', 'b@example.net'], [first['email'], second['email']])
        self.assertEqual((2, 74.17), (first['purchase_days'], first['score']))
        self.assertEqual(2, result['ready_count'])
        request = dict(ids=[first['id']], decision='confirmed', request_id='one-batch')
        receipt = self.service.decide_entries('admin', request)
        self.assertEqual({'changed': [first['id']], 'skipped': 0}, receipt)
        self.assertEqual(receipt, self.service.decide_entries('admin', request))
        with self.assertRaisesRegex(ValueError, 'maintenance_request_conflict'):
            self.service.decide_entries('admin', dict(request, ids=[second['id']]))
        self.assertEqual([second['id']], [row['id'] for row in self.service.queue_view('ready')['items']])

    def test_stock_respects_rule_quota_and_band_backlog_across_daily_runs(self):
        self.source.orders = [
            dict(order(f'order-{i:02d}', f'c-{i:02d}', 100+i, f'person-{i:02d}@example.net'), amount_usd='750')
            for i in range(18)
        ]
        self.tick(20)
        self.service.save_rule('admin', dict(id='lost', expected_version=0, tier='high', stage='lost',
            customer_type='new', enabled=True, priority=0, daily_quota=6, coupon_id=123, alert=False, owner=None))
        self.service.update()
        first = self.service.queue_view('ready')['items']
        self.assertEqual(6, len(first))
        self.assertEqual([f'person-{i:02d}@example.net' for i in range(5)],
                         [item['email'] for band in self.service.recommendations(5)['bands'] for item in band['items']])
        self.service.update()
        self.assertEqual(6, len(self.service.queue_view('ready')['items']))
        self.tick(1)
        ready = self.service.queue_view('ready')['items']
        self.assertEqual(10, len(ready))
        self.assertTrue({row['id'] for row in first} <= {row['id'] for row in ready})
        removed = next(row['id'] for row in first if row['email'] == 'person-00@example.net')
        self.service.decide_entries('admin', dict(ids=[removed], decision='removed', request_id='remove-stock'))
        self.tick(1)
        ready = self.service.queue_view('ready')['items']
        self.assertEqual([f'person-{i:02d}@example.net' for i in range(1, 11)], sorted(row['email'] for row in ready))

    def test_private_outreach_excludes_recent_coupon_and_contact_but_returns_unentered_stock(self):
        self.source.orders = [
            dict(order(f'order-{i:02d}', f'c-{i:02d}', 100+i, f'person-{i:02d}@example.net'), amount_usd='750')
            for i in range(4)
        ]
        self.tick(20)
        self.service.save_rule('admin', dict(id='lost', expected_version=0, tier='high', stage='lost',
            customer_type='new', enabled=True, priority=0, daily_quota=2, coupon_id=123, alert=False, owner='admin'))
        self.service.update()
        linked = self.service.customer_view('c-00')['case']['case_id']
        with self.db() as db:
            record_event(db, '1'*32, linked, 'admin', dict(event='contacted', contacted_at=self.now.isoformat()),
                         self.now.isoformat())
        self.admin.coupons = [[dict(self.grant('23'), member_id=101)]]
        controller = TrackingController(self.path.parent / 'outreach-auth', lambda user: user == 'admin',
                                        auto_start=False)
        controller.maintenance = self.service
        query = dict(kind='hermes_customer_tracking', action='phase_outreach_export', limit=10)
        with self.assertRaises(PermissionError):
            controller.post('viewer', query)
        with self.assertRaises(ValueError):
            controller.post('admin', dict(query, limit=5))
        response = controller.post('admin', query)[1]
        self.assertEqual('2026-11-02', response['week'])
        self.assertEqual(['person-02@example.net', 'person-03@example.net'],
                         [row['email'] for row in response['items']])
        self.assertTrue(all(row['source'] == 'stock' and row['purchase_days'] == 1
                            and 'owner' in row and 'last_contact_date' in row for row in response['items']))
        view = controller.post('admin', dict(query, action='phase_recommendations', limit=5))[1]
        self.assertEqual(0, view['ready_count'])

    def test_needs_decision_lists_order_and_can_be_exported_for_followup(self):
        self.tick(20)
        self.service.save_rule('admin', dict(id='lost', expected_version=0, tier='high', stage='lost',
            customer_type='new', enabled=True, priority=0, daily_quota=1, coupon_id=123, alert=False, owner=None))
        self.admin.issues = [dict(order_key='admin:266:a', paid_at=self.source.orders[0]['paid_at'],
                                  reason='refund', refund='partial_observed', after_sales='none_observed')]
        self.service.update()
        result = self.service.recommendations(5)
        self.assertEqual((0, 1), (result['ready_count'], result['decision_count']))
        row, = result['decisions']
        self.assertEqual(['admin:266:a'], row['order_keys'])
        self.assertEqual(['exceptions'], row['result']['reasons'])
        exported, = self.service.recommendations(None, export=True)['items']
        self.assertEqual(('decision', 'needs_decision'), (exported['source'], exported['state']))
        self.service.decide_review('admin', dict(id=row['id'], request_id='needs-refund', decision='ready',
            review_digest=row['result']['digest'], reason='核对退款'))
        self.assertEqual(1, self.service.recommendations(5)['ready_count'])

    def test_recent_grant_query_checks_date_scope_and_excludes_automatic_batches(self):
        requests = []
        def read(path, query):
            requests.append((path, query))
            grants = [self.grant('8'), dict(self.grant('9'), member_id=101, grant_batch_no='FCSM_TEST')]
            rows = grants if query['search[1][val]'].endswith('2026-10-14 08:00:00') else []
            return dict(total=len(rows), list=rows)
        self.assertEqual({'100'}, AdminFacts(read).recent_grant_members(self.now))
        self.assertEqual(5, len(requests))
        self.assertTrue(all(path == '/admin/user.MemberCoupon/index' and query['search[0][val]'] == '266'
                            and query['search[1][field]'] == 'start_time' for path, query in requests))
        with self.assertRaisesRegex(ValueError, 'maintenance_grant_scope'):
            AdminFacts(lambda *_: dict(total=1, list=[self.grant('8')])).recent_grant_members(self.now)

    def test_maintenance_dashboard_reads_stored_queue_details_and_counts(self):
        template = dict(TEMPLATE, mode_type=2, reduce='88', max_reduce='50')
        self.bridge.detail = lambda coupon: template.copy()
        entry = self.create()
        groups = self.service.group_view()
        self.assertEqual(dict(reviewing=1), groups['queue_counts'])
        self.assertEqual(0, groups['last_run']['config_version'])

        self.service.update()
        ready, = self.service.queue_view('ready')['items']
        self.assertEqual(entry['id'], ready['id'])
        self.assertEqual('high', ready['tier'])
        self.assertEqual('silent', ready['stage'])
        self.assertEqual('500.00', ready['amount_usd'])
        self.assertEqual(0, ready['unknown_amount_orders'])
        self.assertEqual({'mode_type': 2, 'reduce': '88', 'max_reduce': '50', 'time_effect': 2, 'days': 7},
                         ready['coupon'])
        self.assertNotIn('rule_body', ready)
        self.assertEqual({'ready': 1}, self.service.group_view()['queue_counts'])

    def test_projection_email_conflict_requires_orders_on_site_266(self):
        path = self.path.with_name('customers.sqlite3')
        publication = dict(contract=PUBLICATION_CONTRACT, cadence='daily', cutoff=self.source.current.isoformat(),
                           published_at=self.now.isoformat(), captured_at=self.now.isoformat(),
                           refresh_health={}, coverage_context={}, source_status_rule_versions=[],
                           data_version='1', config=dict(sites=['266']), flag_manifests=[], jobs=[])
        publication['publication_id'] = 'uw_' + publication_digest(publication)[:32]
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO meta VALUES('revision','1');
                CREATE TABLE orders(site TEXT, customer_id TEXT);
                CREATE TABLE identities(customer_id TEXT,email TEXT);
                INSERT INTO orders VALUES('266','customer-A'),('999','customer-B');
                INSERT INTO identities VALUES('customer-A','buyer@example.net'),('customer-B','BUYER@example.net');
            """)
            db.execute('INSERT INTO meta VALUES (?,?)', (PUBLICATION_META, json.dumps(publication)))
        projection = UserProjection(path)
        self.assertFalse(projection.read(self.now).email_conflict('customer-A', 'buyer@example.net'))
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO orders VALUES('266','customer-B')")
        self.assertTrue(projection.read(self.now).email_conflict('customer-A', 'buyer@example.net'))

    def test_true_email_conflict_is_visible_in_the_review_queue(self):
        entry = self.create()
        self.source.orders += [order('other', customer='customer-B', uid=101)]
        self.tick()
        rows = self.service.queue_view('review')['items']
        row = next(row for row in rows if row['id'] == entry['id'])
        self.assertEqual('reviewing', row['state'])
        self.assertEqual('pending_identity', row['identity_status'])
        self.assertEqual('email_conflict', row['identity_reason'])
        self.assertIn('identity_checked_at', row)

    def test_admin_refund_reads_are_batched_by_shanghai_payment_day(self):
        orders = [dict(order(str(i)), paid_at='2026-09-30T16:00:00+00:00') for i in range(51)]
        orders.append(dict(order('previous'), paid_at='2026-09-30T15:59:59+00:00'))
        calls = []
        missing = False

        def read(path, params):
            self.assertEqual(AdminFacts.ROUTES['orders'], path)
            if 'search[2][field]' not in params:
                return dict(total=0, list=[])
            fields = {params[f'search[{i}][field]']: i for i in range(3)}
            window = fields['paytime']
            self.assertEqual('RANGE', params[f'search[{window}][operator]'])
            self.assertEqual('datetime', params[f'search[{window}][render]'])
            day = params[f'search[{window}][val]'][:10]
            self.assertEqual(f'{day} 00:00:00,{day} 23:59:59', params[f'search[{window}][val]'])
            numbers = params[f"search[{fields['order_no']}][val]"].split(',')
            calls.append((day, numbers))
            rows = [dict(id=i, order_no=n, site_id=266, pay_status=1,
                         paytime=f'{day} 12:00:00', amount_usd='500',
                         status_format='已完成') for i, n in enumerate(numbers, 1)]
            if missing:
                rows.pop()
            return dict(total=len(rows), list=rows)

        admin = AdminFacts(read)
        self.assertEqual([], admin.exceptions(orders))
        self.assertEqual([('2026-09-30', 1), ('2026-10-01', 1), ('2026-10-01', 50)],
                         sorted((day, len(numbers)) for day, numbers in calls))
        self.assertEqual(['previous'], next(numbers for day, numbers in calls if day == '2026-09-30'))
        missing = True
        with self.assertRaisesRegex(ValueError, 'maintenance_admin_order_scope'):
            admin.exceptions(orders)

    def test_scopes_order_reads_and_only_a_new_fc27_payment_skips_review(self):
        self.source.orders += [
            dict(order('old-normal'), paid_at='2026-06-01T12:00:00+08:00', amount_usd='1'),
            dict(order('old-flagged', valid=False), paid_at='2026-05-01T12:00:00+08:00'),
        ]
        entry = self.create()
        self.source.orders += [dict(order('non-fc'), paid_at=self.source.current.isoformat(), gid='42')]
        checked = []
        self.admin.exceptions = lambda orders: checked.extend(row['order_no'] for row in orders) or []
        self.tick(1)
        self.assertEqual({'a', 'old-flagged'}, set(checked))
        self.assertEqual('ready', self.service.ledger.entry(entry['id'])['state'])

        self.setUp()
        entry = self.create()
        self.source.orders += [dict(order('new-fc'), paid_at=self.source.current.isoformat())]
        self.tick(1)
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('skipped', row['state'])
        self.assertEqual('paid_after_event', row['result']['reason'])

    def test_manual_review_decision_receipt_and_fresh_dispatch_evidence(self):
        for added in (None, 'refund', 'payment', 'coupon', 'remove'):
            with self.subTest(added=added):
                self.setUp()
                entry = self.create()
                original = dict(order_key='admin:266:a', paid_at=order()['paid_at'], reason='after_sales',
                                refund='partial_observed', after_sales='none_observed', refund_amount='10')
                self.admin.issues = [original]
                self.service.update()
                row = self.service.queue_view('review')['items'][0]
                self.assertEqual('needs_decision', row['state'])
                self.assertIsNone(row['ready_at'])
                self.now += timedelta(days=4)
                self.assertFalse(self.service.ledger.expire(entry['id'], self.now))
                request = dict(kind='hermes_customer_tracking', action='phase_review_decide', id=row['id'],
                               request_id='decision-1', review_digest=row['result']['digest'],
                               decision='removed' if added == 'remove' else 'ready', reason='verified refund')
                controller = TrackingController(self.path.parent / 'auth', lambda user: user == 'admin', auto_start=False)
                controller.maintenance = self.service
                with self.assertRaises(PermissionError):
                    controller.post('viewer', request)
                with self.assertRaisesRegex(ValueError, 'maintenance_review_conflict'):
                    controller.post('admin', dict(request, review_digest='a' * 64))
                self.assertTrue(controller.post('admin', request)[1]['changed'])
                self.assertTrue(controller.post('admin', request)[1]['reused'])
                with self.assertRaisesRegex(ValueError, 'maintenance_request_conflict'):
                    controller.post('admin', dict(request, reason='changed'))
                row = self.service.ledger.entry(entry['id'])
                self.assertEqual(['exceptions'], row['result']['evidence']['reasons'])
                with self.db() as db:
                    actor, details = db.execute("SELECT actor,details FROM maintenance_transitions "
                                                "WHERE entry_id=? AND prior='needs_decision'", (entry['id'],)).fetchone()
                self.assertEqual('admin', actor)
                self.assertEqual(request['reason'], json.loads(details)['reason'])
                if added == 'remove':
                    self.assertEqual('removed', row['state'])
                    continue
                self.assertEqual(self.now, datetime.fromisoformat(row['ready_at']))
                self.service.decide_entries('admin', dict(ids=[entry['id']], decision='confirmed'))
                if added == 'refund':
                    self.admin.issues = [dict(original, refund_amount='20')]
                elif added == 'payment':
                    self.source.orders += [dict(order('new'), paid_at=self.source.current.isoformat())]
                    self.tick(1, run=False)
                elif added == 'coupon':
                    self.admin.coupons = [[self.grant(22)]]
                self.service.dispatch()
                state = self.service.ledger.entry(entry['id'])['state']
                self.assertEqual({None: 'issued', 'refund': 'needs_decision',
                                  'payment': 'skipped', 'coupon': 'deferred'}[added], state)
                self.assertEqual(0 if added else 1, len(self.bridge.sent))

    def test_review_failures_back_off_and_escalate_after_six_attempts(self):
        entry = self.create()
        attempts = []

        def unavailable(orders):
            attempts.append(self.now)
            raise TimeoutError('fixture timeout')

        self.admin.exceptions = unavailable
        with self.assertLogs('maintenance_service', 'WARNING') as log:
            for _ in range(40):
                self.service.update()
                self.now += timedelta(minutes=10)
        self.assertEqual(6, len(attempts))
        self.assertEqual([10, 20, 40, 80, 160],
                         [(b-a)//timedelta(minutes=1) for a, b in zip(attempts, attempts[1:])])
        self.assertEqual(6, len(log.output))
        row = self.service.queue_view('review')['items'][0]
        self.assertEqual(entry['id'], row['id'])
        self.assertEqual('needs_decision', row['state'])
        self.assertEqual('review_retry_exhausted', row['result']['reason'])
        self.assertEqual('TimeoutError', row['result']['error_code'])
        self.assertIsNone(row['ready_at'])

    def test_usage_is_read_once_per_update_and_fresh_during_dispatch(self):
        self.source.orders += [order('b', 'customer-B', 101, 'other@example.net')]
        self.create()
        usage_reads = []
        self.admin.logs = lambda start, stop: usage_reads.append((start, stop)) or []
        self.service.update()
        self.assertEqual(2, len(self.service.queue_view('ready')['items']))
        self.assertEqual(5, len(usage_reads))  # 30 days, 7 days per Admin read.
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.service.dispatch()
        self.assertEqual(15, len(usage_reads))
        self.assertEqual(1, len(self.bridge.sent))  # One per rule per day in this fixture.

    def test_review_coupon_defers_until_next_shanghai_day_and_then_reevaluates(self):
        entry = self.create()
        self.admin.coupons = [[dict(self.grant(22),
                                    start_time=(self.now-timedelta(days=29, hours=23)).isoformat())]]
        self.service.update()
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('reviewing', row['state'])
        self.assertEqual('manual_coupons', row['result']['reason'])
        self.now += timedelta(hours=2)
        self.service.update()
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        self.tick(1)
        self.assertEqual('ready', self.service.ledger.entry(entry['id'])['state'])

    def test_admin_problem_status_blocks_review_and_dispatch(self):
        for status in ('CB(资料)', '调查中', '拒付', '退款中'):
            with self.subTest(status=status):
                for dispatch in (False, True):
                    with self.subTest(dispatch=dispatch):
                        self.setUp()
                        entry = self.create()
                        native_status = '已完成'

                        def read(path, params):
                            if path == AdminFacts.ROUTES['orders']:
                                row = dict(id=1, order_no='a', site_id=266, pay_status=1,
                                           paytime='2026-10-01 12:00:00', amount_usd='500',
                                           status_format=native_status)
                                return dict(total=1, list=[row])
                            return dict(total=0, list=[])

                        self.service.admin = AdminFacts(read)
                        if dispatch:
                            self.service.update()
                            self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
                        native_status = status
                        if dispatch:
                            self.service.dispatch()
                            row = self.service.ledger.entry(entry['id'])
                            self.assertEqual('exceptions', row['result'].get('reason'))
                            self.assertEqual([], self.bridge.sent)
                        else:
                            self.service.update()
                            self.assertEqual('held', self.service.ledger.entry(entry['id'])['state'])
                            review, = self.service.ledger.reviews(entry['id'])
                            self.assertEqual(['exceptions'], review['reasons'])
                            self.assertEqual(status, review['order_exceptions'][0]['order_state'])
                            self.assertEqual('problem', review['order_exceptions'][0]['reason'])
                        finding, = self.service.admin.exceptions(self.source.orders)
                        self.assertEqual(status, finding['order_state'])
                        self.assertEqual('problem', finding['reason'])

    def admin_rows(self, *, usage=lambda: [], grants=lambda: [], status=lambda: '已完成'):
        def read(path, params):
            if path == AdminFacts.ROUTES['orders']:
                rows = [dict(id=i, order_no=number, site_id=266, pay_status=1,
                             paytime='2026-10-01 12:00:00', amount_usd='500', status_format=status())
                        for i, number in enumerate(params['search[1][val]'].split(','), 1)]
            elif path == AdminFacts.ROUTES['grants']:
                rows = grants()
            else:
                rows = usage()
            return dict(total=len(rows), list=rows)

        self.service.admin = AdminFacts(read)

    def coupon_use(self, **changes):
        return dict(dict(id=7, site_id=266, order_no='a', member_id=999, member_coupon_id=22,
                         memberCoupon=dict(id=22, grant_batch_no='manual'),
                         use_time=(self.now-timedelta(hours=1)).isoformat()), **changes)

    def test_usage_failure_with_no_uid_defers_review_and_dispatch(self):
        self.source.orders = [order(uid=None)]
        entry = self.create()
        unavailable = True

        def usage():
            if unavailable:
                raise OSError('fixture unavailable')
            return [self.coupon_use(order_no='not-in-projection')]

        self.admin_rows(usage=usage)
        self.service.update()
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        unavailable = False
        self.now += timedelta(minutes=10)
        self.service.update()
        review, = self.service.ledger.reviews(entry['id'])
        self.assertEqual('pass', review['decision'])
        self.assertEqual(1, review['unattributed_coupon_logs'])
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        unavailable = True
        self.service.dispatch()
        self.assertEqual('confirmed', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual([], self.bridge.sent)

    def test_order_attributed_coupon_blocks_known_uid_and_deduplicates_same_grant(self):
        entry = self.create()
        self.admin_rows(usage=lambda: [self.coupon_use()])
        self.service.update()
        review, = self.service.ledger.reviews(entry['id'])
        self.assertEqual(['manual_coupons'], review['reasons'])
        self.assertEqual(1, review['matches']['manual_coupons'])

    def test_coupon_use_after_publication_cutoff_uses_exact_private_order_owner(self):
        entry = self.create()
        path = self.path.with_name('customer-projection.sqlite3')
        path.touch(mode=0o600)
        cutoff = self.source.current.isoformat()
        projection = UserProjection(path)
        publication = dict(contract=PUBLICATION_CONTRACT, cadence='daily', cutoff=cutoff,
                           published_at=self.now.isoformat(), captured_at=self.now.isoformat(),
                           refresh_health={}, coverage_context={}, source_status_rule_versions=[],
                           data_version='1', config=dict(sites=['266']), flag_manifests=[],
                           jobs=[dict(site='266', state='complete', start='2026-10-01T00:00:00+08:00',
                                      end=cutoff, body='{}')])
        publication['publication_id'] = 'uw_' + publication_digest(publication)[:32]
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO meta VALUES ('revision', '1');
                CREATE TABLE orders(order_key TEXT PRIMARY KEY,site TEXT,gid TEXT,customer_id TEXT,
                                    paid_at TEXT,valid INTEGER,body TEXT,revision INTEGER);
                CREATE TABLE identities(customer_id TEXT,email TEXT);
                INSERT INTO identities VALUES ('customer-A', 'buyer@example.net');
            """)
            db.execute('INSERT INTO meta VALUES (?,?)', (PUBLICATION_META, json.dumps(publication)))
            orders = [('a', order()['paid_at'], 'customer-A'),
                      ('after-cutoff', cutoff, 'customer-A'), ('unverified-order', cutoff, None)]
            for number, paid_at, customer in orders:
                body = json.dumps(dict(order_no=number, uid=100, amount_usd='500', pay_status=1))
                db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',
                           ('admin:266:'+number, '266', '1327', customer, paid_at, 1, body, 1))
        self.service.source = projection
        self.admin_rows(usage=lambda: [self.coupon_use(order_no='after-cutoff'),
                                      self.coupon_use(id=8, order_no='unverified-order', member_id=100)])
        with patch('user_customer_types.read_pinned_flags', return_value=({}, {})):
            self.assertEqual(['a'], [row['order_no'] for row in projection.read(self.now).customer_orders('customer-A')])
            self.service.update()
        review, = self.service.ledger.reviews(entry['id'])
        self.assertEqual(['manual_coupons'], review['reasons'])
        self.assertEqual(1, review['unattributed_coupon_logs'])

    def test_usage_and_grant_for_same_coupon_count_once_and_both_pin_evidence(self):
        entry = self.create()
        self.admin_rows(usage=lambda: [self.coupon_use()], grants=lambda: [self.grant(22)])
        self.service.update()
        review, = self.service.ledger.reviews(entry['id'])
        self.assertEqual(['manual_coupons'], review['reasons'])
        self.assertEqual(1, review['matches']['manual_coupons'])
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual('defer', review['decision'])

    def test_coupon_usage_visible_after_review_still_blocks_dispatch(self):
        entry = self.create()
        visible = False

        def grants():
            nonlocal visible
            visible = True
            return []

        self.admin_rows(usage=lambda: [self.coupon_use()] if visible else [], grants=grants)
        self.service.update()
        self.assertEqual('ready', self.service.ledger.entry(entry['id'])['state'])
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.service.dispatch()
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('deferred', row['state'])
        self.assertEqual('manual_coupons', row['result']['reason'])
        self.assertEqual([], self.bridge.sent)

    def test_admin_grant_visible_after_review_still_blocks_dispatch(self):
        entry = self.create()
        self.admin.coupons = [[], [self.grant(21)]]
        self.service.update()
        self.assertEqual('ready', self.service.ledger.entry(entry['id'])['state'])
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.service.dispatch()
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('deferred', row['state'])
        self.assertEqual('manual_coupons', row['result']['reason'])
        self.assertEqual([], self.bridge.sent)

    def test_grant_read_failure_stays_pending_then_late_grant_blocks_dispatch(self):
        entry = self.create()
        self.admin.coupons = [OSError('fixture unavailable')]
        self.service.update()
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        self.admin.coupons = []
        self.now += timedelta(minutes=10)
        self.service.update()
        self.assertEqual('ready', self.service.ledger.entry(entry['id'])['state'])
        self.service.decide_entries('admin', dict(ids=[entry['id']], decision='confirmed'))
        self.admin.coupons = [[self.grant(22)]]
        self.service.dispatch()
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('manual_coupons', row['result']['reason'])
        self.assertEqual([], self.bridge.sent)

    def test_latest_refund_and_correction_control_dispatch(self):
        entry = self.create()
        self.service.update()
        self.service.decide_entries('admin', dict(ids=[entry['id']], decision='confirmed'))
        self.admin.issues = [dict(order_key='admin:266:a', paid_at=order()['paid_at'],
                                  refund='partial_observed', after_sales='none_observed')]
        self.service.dispatch()
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('exceptions', row['result']['reason'])
        self.assertEqual([], self.bridge.sent)
        self.source.orders = [order(valid=False)]
        self.tick(1)
        timeline = self.service.ledger.entry(entry['id'])
        self.assertEqual('void', timeline['state'])
        self.assertEqual([], self.service.group_view()['items'])

    def test_template_is_read_after_external_evidence_and_checked_at_dispatch_time(self):
        for change in ('snapshot', 'expiry'):
            with self.subTest(change=change):
                self.setUp()
                template = TEMPLATE.copy()
                if change == 'expiry':
                    template.update(time_effect=1, end_time=(self.now+timedelta(days=2, seconds=1)).isoformat())
                self.bridge.detail = lambda coupon: template.copy()
                entry = self.create()
                self.service.update()
                self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))

                def state():
                    if change == 'expiry':
                        self.now += timedelta(seconds=1)
                    else:
                        template['days'] = 21
                    return '已完成'

                self.admin_rows(status=state)
                self.service.dispatch()
                row = self.service.ledger.entry(entry['id'])
                self.assertEqual('template_changed', row['result'].get('reason'))
                self.assertEqual([], self.bridge.sent)

    def test_template_process_failure_does_not_stop_another_coupons_dispatch(self):
        for failure in (subprocess.TimeoutExpired('node', 1), subprocess.CalledProcessError(1, 'node')):
            with self.subTest(failure=type(failure).__name__):
                self.setUp()
                self.bridge.detail = lambda coupon: dict(TEMPLATE, id=coupon)
                self.source.orders.append(dict(order('b', 'customer-B', 101, 'second@example.net'),
                                               amount_usd='1000'))
                self.rule()
                self.service.save_rule('admin', dict(id='second', expected_version=0, tier='ultra', stage='silent',
                    customer_type='new', enabled=True, priority=1, daily_quota=1, coupon_id=456,
                    alert=True, owner=None))
                self.tick()
                self.tick(2)
                self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
                entries = {item['rule_id']: item['id'] for item in self.service.queue_view('delivery')['items']}

                def detail(coupon):
                    if coupon == 123:
                        raise failure
                    return dict(TEMPLATE, id=coupon)

                self.bridge.detail = detail
                self.service.dispatch()
                self.assertEqual('confirmed', self.service.ledger.entry(entries['first'])['state'])
                self.assertEqual('issued', self.service.ledger.entry(entries['second'])['state'])
                self.assertEqual([456], [item[0] for item in self.bridge.sent])

    def test_latest_projection_invalidates_event_before_daily_void_even_if_tier_still_matches(self):
        older = dict(order('older'), paid_at='2026-10-01T10:00:00+08:00')
        self.source.orders = [older, dict(order(), amount_usd='100')]
        entry = self.create()
        self.service.update()
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.source.orders = [older, order(valid=False)]
        self.tick(run=False)
        self.service.dispatch()
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('event_invalid', row['result'].get('reason'))
        self.assertEqual([], self.bridge.sent)

    def test_dispatch_discards_failure_if_source_changes_during_template_read(self):
        for first_order in (order(valid=False), dict(order(), amount_usd='499')):
            with self.subTest(first_order=first_order):
                self.setUp()
                entry = self.create()
                self.service.update()
                self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
                self.source.orders = [first_order]
                self.tick(run=False)

                def detail(coupon):
                    self.source.orders = [order()]
                    self.tick(run=False)
                    return TEMPLATE.copy()

                self.bridge.detail = detail
                self.service.dispatch()
                self.assertEqual('confirmed', self.service.ledger.entry(entry['id'])['state'])
                self.assertEqual([], self.bridge.sent)
                self.bridge.detail = lambda coupon: TEMPLATE.copy()
                self.now += timedelta(minutes=2)
                self.service.dispatch()
                self.assertEqual('issued', self.service.ledger.entry(entry['id'])['state'])

    def test_claim_rechecks_event_status_after_template_read(self):
        entry = self.create()
        self.service.update()
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))

        def detail(coupon):
            with self.db() as db:
                db.execute("UPDATE maintenance_events SET status='void' WHERE id=?", (entry['event_id'],))
            return TEMPLATE.copy()

        self.bridge.detail = detail
        self.service.dispatch()
        self.assertEqual('event_invalid', self.service.ledger.entry(entry['id'])['result']['reason'])
        self.assertEqual([], self.bridge.sent)

    def test_configuration_change_rechecks_old_confirmation(self):
        entry = self.create()
        self.service.update()
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        config = self.service.save_config(dict(expected_version=0, stages=[14,30,60], high='600', ultra='1000'))
        self.assertEqual(1, config['version'])
        self.service.dispatch()
        self.assertEqual('tier_changed', self.service.ledger.entry(entry['id'])['result']['reason'])
        self.assertEqual([], self.bridge.sent)

    def test_config_commit_unknown_reads_back_the_original_version_without_rewriting(self):
        def committed_then_uncertain(path, config, expected):
            write_config(path, config, expected)
            raise ConfigCommitUnknown(config['version'])

        with patch('maintenance_service.write_config', side_effect=committed_then_uncertain) as writer:
            saved = self.service.save_config(dict(expected_version=0, stages=[14, 31, 60], high='500', ultra='1000'))
        self.assertEqual(1, writer.call_count)
        self.assertEqual((14, 31, 60), saved['stages'])
        self.assertEqual(1, saved['version'])

    def insert_case(self, ident, address='buyer@example.net', uid='100'):
        baseline = dict(identity=dict(emails=[address], uids=[uid]))
        with self.db() as db:
            db.execute('INSERT INTO vip_cases(id,week,opened_at,baseline) VALUES(?,?,?,?)',
                       (ident, '2026-10-05', self.now.isoformat(), json.dumps(baseline)))

    def test_review_rechecks_case_binding_with_each_projections_latest_identity(self):
        for move_during_review in (False, True):
            with self.subTest(move_during_review=move_during_review):
                self.setUp()
                entry = self.create()
                self.insert_case('a'*32, 'other@example.net', uid='101')

                def change_identity():
                    self.source.orders = [order(uid=101)]
                    self.tick(run=False)

                def exceptions(orders):
                    if move_during_review and self.source.orders[0]['uid'] == 100:
                        change_identity()
                    return []

                self.admin.exceptions = exceptions
                if not move_during_review:
                    change_identity()
                self.service.update()
                if move_during_review:
                    self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
                    self.assertEqual([], self.service.ledger.reviews(entry['id']))
                    self.now += timedelta(minutes=10)
                    self.service.update()
                self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
                self.assertEqual([], self.service.ledger.reviews(entry['id']))
                controller = TrackingController(self.path.parent / 'auth', lambda user: user == 'operator',
                                                auto_start=False)
                controller.maintenance = self.service
                query = dict(mode=['hermes'], structure=['customer_tracking'], view=['phase_review'])
                status, payload = controller.get('operator', query)
                self.assertEqual(200, status)
                item, = payload['items']
                self.assertEqual('pending_identity', item['identity_status'])
                self.assertEqual('uid_case_conflict', item['identity_reason'])
                self.assertEqual(self.now, datetime.fromisoformat(item['identity_checked_at']))

                self.admin.exceptions = lambda orders: []
                self.source.orders = [order()]
                self.tick()
                self.assertEqual([], controller.get('operator', query)[1]['items'])
                query['view'] = ['phase_ready']
                item, = controller.get('operator', query)[1]['items']
                self.assertEqual(entry['id'], item['id'])
                self.assertNotIn('identity_reason', item)
                self.assertNotIn('identity_checked_at', item)

    def test_ambiguous_cases_keep_review_pending_until_admin_selection(self):
        first, second = 'a'*32, 'b'*32
        self.insert_case(first)
        self.insert_case(second)
        entry = self.create()
        self.service.update()
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        view = self.service.customer_view('customer-A')
        self.assertEqual('pending_identity', view['case']['status'])
        self.assertEqual([first, second], view['matching_cases'])
        self.service.resolve_case('admin', dict(customer_id='customer-A', case_id=second, request_id='selected'))
        self.service.update()
        self.assertEqual('ready', self.service.ledger.entry(entry['id'])['state'])

    def test_new_case_conflict_after_review_prevents_dispatch_until_admin_selection(self):
        entry = self.create()
        self.service.update()
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.insert_case('a'*32)
        self.service.dispatch()
        self.assertEqual('confirmed', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual([], self.bridge.sent)
        self.assertEqual('pending_identity', self.service.customer_view('customer-A')['case']['status'])
        self.service.resolve_case('admin', dict(customer_id='customer-A', case_id='a'*32, request_id='selected'))
        self.now += timedelta(minutes=1)
        self.service.dispatch()
        self.assertEqual('issued', self.service.ledger.entry(entry['id'])['state'])

    def test_dispatch_uses_latest_customer_identity_to_check_case_conflicts(self):
        entry = self.create()
        self.service.update()
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.insert_case('a'*32, 'other@example.net', uid='101')
        self.source.orders = [order(uid=101)]
        self.tick(run=False)
        self.service.dispatch()
        self.assertEqual('confirmed', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual([], self.bridge.sent)

    def weekly_cohort(self, scope):
        source = FakeSource()
        paid_at = datetime.fromisoformat(self.source.orders[0]['paid_at'])
        member = buyer(100, payment(1, paid_at))
        member['email'] = 'BUYER@example.net'
        member['identity']['emails'] = [member['email']]
        source.entries = [member] if scope == UK_US else []
        source.preferred = [dict(member, scope=PREFERRED)] if scope == PREFERRED else []
        self.vip.source = source

    def test_weekly_refresh_reuses_open_stage_case_by_verified_email(self):
        for scope, other in ((UK_US, PREFERRED), (PREFERRED, UK_US)):
            with self.subTest(scope=scope):
                self.setUp()
                entry = self.create(owner='operator')
                stage_case = self.service.customer_view('customer-A')['case']
                self.weekly_cohort(scope)

                self.assertEqual('ready', self.vip.refresh()['scope_status'][scope])

                view = self.service.customer_view('customer-A')
                self.assertEqual([], view['matching_cases'])
                self.assertEqual(stage_case, view['case'])
                weekly_case, = self.vip.queue(scope=scope)['items']
                self.assertEqual(stage_case['case_id'], weekly_case['case_id'])
                self.assertEqual('operator', weekly_case['owner'])
                self.assertEqual([], self.vip.queue(scope=other)['items'])
                self.service.update()
                ready, = self.service.queue_view('ready')['items']
                self.assertEqual(entry['id'], ready['id'])

    def test_stage_maintenance_reuses_open_weekly_case_by_verified_email(self):
        for scope in (UK_US, PREFERRED):
            with self.subTest(scope=scope):
                self.setUp()
                self.weekly_cohort(scope)
                self.assertEqual('ready', self.vip.refresh()['scope_status'][scope])
                weekly_case, = self.vip.queue(scope=scope)['items']

                entry = self.create(owner='operator')
                self.service.update()

                view = self.service.customer_view('customer-A')
                self.assertEqual([], view['matching_cases'])
                self.assertEqual('linked', view['case']['status'])
                self.assertEqual(weekly_case['case_id'], view['case']['case_id'])
                updated, = self.vip.queue(scope=scope)['items']
                self.assertEqual(weekly_case['case_id'], updated['case_id'])
                self.assertEqual('operator', updated['owner'])
                ready, = self.service.queue_view('ready')['items']
                self.assertEqual(entry['id'], ready['id'])

    def test_new_stage_after_closed_case_opens_another_case(self):
        self.vip = VipMaintenance(Store(self.path.parent), clock=lambda: self.now)
        self.create()
        prior = self.service.customer_view('customer-A')['case']['case_id']
        self.vip.feedback('operator', dict(case_id=prior, request_id='1'*32, event='claim'))
        self.vip.feedback('operator', dict(case_id=prior, request_id='2'*32, event='close'))
        self.tick(16)
        current = self.service.customer_view('customer-A')['case']
        self.assertEqual('linked', current['status'])
        self.assertIsNotNone(current['case_id'])
        self.assertNotEqual(prior, current['case_id'])

    def test_two_orders_sharing_uid_do_not_cross_attach_cases(self):
        self.rule(owner='operator')
        with self.db() as db:
            baseline = dict(identity=dict(emails=['other@example.net'], uids=['100']))
            db.execute('INSERT INTO vip_cases(id,week,opened_at,baseline,owner) VALUES(?,?,?,?,?)',
                       ('a'*32, '2026-10-05', self.now.isoformat(), json.dumps(baseline), 'previous'))
        self.tick()
        self.tick(2)
        view = self.service.customer_view('customer-A')
        self.assertEqual('pending_identity', view['case']['status'])
        self.assertIsNone(view['case']['case_id'])
        self.assertEqual([], view['contacts'])
        with self.assertRaises(ValueError):
            self.service.resolve_case('admin', dict(customer_id='customer-A', case_id='a'*32, request_id='fault'))
        resolved = self.service.resolve_case('admin', dict(customer_id='customer-A', case_id=None, request_id='safe'))
        self.assertNotEqual('a'*32, resolved['case_id'])
        self.assertEqual('linked', self.service.customer_view('customer-A')['case']['status'])

    def test_verified_email_case_is_preserved_and_dispatch_uses_lowercase(self):
        self.source.orders = [order(address='Buyer@example.com')]
        self.insert_case('a'*32, 'buyer@example.com')
        entry = self.create()
        self.service.update()
        self.assertEqual('Buyer@example.com', entry['email'])
        view = self.service.customer_view('customer-A')
        self.assertEqual('Buyer@example.com', view['customer']['email'])
        self.assertEqual('a'*32, view['case']['case_id'])
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.service.dispatch()
        self.assertEqual('issued', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual('buyer@example.com', self.bridge.sent[0][1])

    def test_casefold_collision_is_visible_and_neither_identity_can_dispatch(self):
        self.source.orders = [order(address='Buyer@example.com'),
                              order('b', 'customer-B', 101, 'buyer@example.com')]
        self.rule()
        self.tick()
        self.tick(2)
        items = self.service.queue_view('review')['items']
        self.assertEqual({'customer-A', 'customer-B'}, {row['customer_id'] for row in items})
        self.assertEqual({'pending_identity'}, {row['identity_status'] for row in items})
        self.assertEqual({'reviewing'}, {row['state'] for row in items})
        self.assertEqual({'pending_identity'}, {row['case_status'] for row in self.service.group_view()['items']})
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.service.dispatch()
        self.assertEqual([], self.bridge.sent)

    def test_new_casefold_collision_in_latest_identities_defers_existing_confirmation(self):
        self.source.orders = [order(address='Buyer@example.com')]
        entry = self.create()
        self.service.update()
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.source.orders.append(order('b', 'customer-B', 101, 'buyer@example.com'))
        self.tick(run=False)
        self.service.dispatch()
        item, = self.service.queue_view('delivery')['items']
        self.assertEqual('confirmed', item['state'])
        self.assertEqual('pending_identity', item['identity_status'])
        self.assertEqual('email_conflict', item['identity_reason'])
        self.assertEqual([], self.bridge.sent)

        self.source.orders.pop()
        self.tick(run=False)
        self.now += timedelta(minutes=2)
        self.service.dispatch()
        item, = self.service.queue_view('delivery')['items']
        self.assertEqual('issued', item['state'])
        self.assertIsNone(item.get('identity_reason'))
        self.assertEqual(1, len(self.bridge.sent))

    def test_dispatch_reaches_the_101st_item_while_earlier_identities_stay_pending(self):
        self.source.orders = [order(str(i), f'customer-{i}', 1000+i, f'buyer-{i}@example.net')
                              for i in range(101)]
        self.rule()
        self.tick()
        self.tick(2)
        for _ in range(4):
            self.service.update()
        confirmed = self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))
        self.assertEqual(101, len(confirmed['changed']))
        entries = self.service.ledger.queue(('confirmed',), limit=101)
        blocked, last = entries[:100], entries[-1]
        for i, entry in enumerate(blocked):
            self.source.orders.append(order(f'collision-{i}', f'collision-{i}', 2000+i, entry['email']))
        self.tick(run=False)

        with self.assertLogs('maintenance_service', level='WARNING'):
            self.service.dispatch()
        self.assertEqual([], self.bridge.sent)
        self.now += timedelta(minutes=2)
        with self.assertLogs('maintenance_service', level='WARNING'):
            self.service.dispatch()
        self.assertEqual('issued', self.service.ledger.entry(last['id'])['state'])
        self.assertEqual([last['email']], [item[1] for item in self.bridge.sent])
        self.assertTrue(all(self.service.ledger.entry(entry['id'])['state'] == 'confirmed' for entry in blocked))

    def test_dispatch_keeps_rule_priority_while_an_earlier_rule_waits_to_retry(self):
        self.bridge.detail = lambda coupon: dict(TEMPLATE, id=coupon)
        self.rule()
        self.service.save_rule('admin', dict(id='second', expected_version=0, tier='high', stage='silent',
            customer_type='new', enabled=True, priority=1, daily_quota=1, coupon_id=456, alert=True, owner=None))
        self.tick()
        self.tick(2)
        self.service.decide_entries('admin', dict(ids='all', decision='confirmed'))

        def detail(coupon):
            if coupon == 123:
                raise subprocess.TimeoutExpired('node', 1)
            return dict(TEMPLATE, id=coupon)

        self.bridge.detail = detail
        self.service.dispatch()
        self.now += timedelta(seconds=15)
        self.service.dispatch()
        self.assertEqual([], self.bridge.sent)
        self.bridge.detail = lambda coupon: dict(TEMPLATE, id=coupon)
        self.now += timedelta(minutes=1)
        self.service.dispatch()
        self.assertEqual([123], [item[0] for item in self.bridge.sent])
        self.service.dispatch()
        self.assertEqual([123], [item[0] for item in self.bridge.sent])

    def test_assignment_only_fills_empty_and_manual_change_uses_cas(self):
        self.rule(owner='operator')
        self.tick()
        self.tick(2)
        view = self.service.customer_view('customer-A')
        self.assertEqual('operator', view['case']['owner'])
        arguments = dict(request_id='manual-1', customer_id='customer-A', expected=None, value='admin')
        with self.assertRaises(ValueError):
            self.service.modify('admin', 'owner', arguments)
        arguments['expected'] = 'operator'
        self.assertTrue(self.service.modify('admin', 'owner', arguments)['changed'])
        self.assertTrue(self.service.modify('admin', 'owner', arguments)['reused'])
        self.assertEqual('admin', self.service.customer_view('customer-A')['case']['owner'])
        with self.assertRaises(PermissionError):
            self.service.modify(None, 'tier', dict(arguments, value='ultra'))
        self.assertTrue(self.service.modify('admin', 'tier',
            dict(request_id='tier-1', customer_id='customer-A', expected=None, value='ultra'))['changed'])
        self.assertEqual('high', self.service.customer_view('customer-A')['customer']['tier'])
        self.assertEqual(1, len(self.service.ledger.queue(('ready',))))

    def test_group_count_and_last_page_share_the_display_tier_and_identity(self):
        controller = TrackingController(self.path.parent / 'group-auth', lambda user: user == 'operator', auto_start=False)
        controller.maintenance = self.service
        with self.service.ledger.db() as db:
            for index in range(23):
                ident = f'group-{index:02d}'
                body = dict(customer_id=ident, email=f'{ident}@example.net', tier='high',
                            stage='recent', customer_type='old' if index == 22 else 'new',
                            last_order_key=ident)
                db.execute('INSERT INTO maintenance_customers VALUES (?,?)', (ident, json.dumps(body)))
            db.execute('INSERT INTO maintenance_overrides VALUES (?,?)', ('group-00', 'ultra'))
            db.execute('INSERT INTO maintenance_events VALUES (?,?,?,?,?,?,?)',
                       ('alert', 'group-21', 'group-21', self.now.isoformat(), '{}', 'active', 1))
        base = dict(mode=['hermes'], structure=['customer_tracking'], view=['phase_groups'])
        self.assertEqual(0, controller.get('operator', base)[1]['total'])
        query = dict(base, tier=['high'], stage=['recent'], customer_type=['new'])
        with self.assertRaises(PermissionError):
            controller.get('viewer', query)
        with self.assertRaises(ValueError):
            controller.get('operator', dict(query, stage=['invalid']))
        first = controller.get('operator', query)[1]
        last = controller.get('operator', dict(query, offset=['20']))[1]
        group = next(row for row in first['groups']
                     if (row['tier'], row['stage'], row['customer_type']) == ('high', 'recent', 'new'))
        self.assertEqual((21, 21, 20), (group['count'], first['total'], first['next_offset']))
        self.assertEqual(20, len(first['items']))
        self.assertEqual(21, last['total'])
        self.assertIsNone(last['next_offset'])
        self.assertEqual(['group-21@example.net'], [row['email'] for row in last['items']])
        self.assertTrue(last['items'][0]['alert'])

    def test_get_and_post_reject_callers_without_real_admin_session(self):
        controller = TrackingController(self.path.parent / 'auth', lambda user: user == 'operator', auto_start=False)
        controller.maintenance = self.service
        query = dict(mode=['hermes'], structure=['customer_tracking'], view=['phase_groups'])
        for user in (None, 'viewer'):
            with self.assertRaises(PermissionError):
                controller.get(user, query)
            with self.assertRaises(PermissionError):
                controller.post(user, dict(kind='hermes_customer_tracking', action='phase_decide',
                                           ids='all', decision='confirmed'))
        self.assertEqual(200, controller.get('operator', query)[0])

    def test_user_projection_reads_published_timestamp_as_a_shanghai_history_boundary(self):
        config_source = ROOT.parent / 'user-analytics-20261022' / 'source' / 'user_config.json'
        config = json.loads(config_source.read_text('utf-8'))
        cutoff = self.now.replace(hour=0).isoformat()
        path = self.path.with_name('customers.sqlite3')
        start_values = (config['history_backfill_start'], '2025-12-31T16:00:00Z', '2026-01-01')
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO meta VALUES ('revision', '1');
                CREATE TABLE orders(order_key TEXT,site TEXT,gid TEXT,customer_id TEXT,paid_at TEXT,
                                    valid INTEGER,body TEXT,revision INTEGER);
                CREATE TABLE identities(customer_id TEXT,email TEXT);
                INSERT INTO identities VALUES ('customer-A', 'Buyer@example.net');
            """)
            for ident, paid in (('before', '2025-12-31T23:59:59+08:00'),
                                ('first', '2026-01-01T00:00:00+08:00')):
                order_body = json.dumps(dict(order_no=ident, uid=100, amount_usd='500', pay_status=1))
                db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',
                           ('admin:266:'+ident, '266', '1327', 'customer-A', paid, 1, order_body, 1))

        for start in start_values:
            with self.subTest(start=start):
                publication = dict(contract=PUBLICATION_CONTRACT, cadence='daily', cutoff=cutoff,
                                   published_at=self.now.isoformat(), captured_at=self.now.isoformat(),
                                   refresh_health={}, coverage_context={}, source_status_rule_versions=[],
                                   data_version='1', config=dict(config, history_backfill_start=start),
                                   jobs=[], flag_manifests=[])
                publication['publication_id'] = 'uw_' + publication_digest(publication)[:32]
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                               (PUBLICATION_META, json.dumps(publication)))
                projection = UserProjection(path)
                with patch('user_customer_types.read_pinned_flags', return_value=({}, {})):
                    for latest in (False, True):
                        rows = projection.read(self.now, latest=latest).customer_orders('customer-A')
                        self.assertEqual(['first'], [row['order_no'] for row in rows])
                        self.assertEqual('Buyer@example.net', rows[0]['email'])

    def test_stage_refresh_streams_projection_and_keeps_as_of_first_purchase(self):
        path = self.path.with_name('customers.sqlite3')
        cutoff = self.source.current.isoformat()
        publication = dict(contract=PUBLICATION_CONTRACT, cadence='daily', cutoff=cutoff,
                           published_at=self.now.isoformat(), captured_at=self.now.isoformat(),
                           refresh_health={}, coverage_context={}, source_status_rule_versions=[],
                           data_version='1', config=dict(sites=['266']), flag_manifests=[],
                           jobs=[dict(site='266', state='complete', start='2026-01-01T00:00:00+08:00',
                                      end=cutoff, body='{}')])
        publication['publication_id'] = 'uw_' + publication_digest(publication)[:32]
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('''
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO meta VALUES ('revision', '1');
                CREATE TABLE orders(order_key TEXT PRIMARY KEY,site TEXT,gid TEXT,customer_id TEXT,
                                    paid_at TEXT,valid INTEGER,body TEXT,revision INTEGER);
                CREATE TABLE identities(customer_id TEXT,email TEXT);
                INSERT INTO identities VALUES ('customer-A', 'buyer@example.net');
            ''')
            db.execute('INSERT INTO meta VALUES (?,?)', (PUBLICATION_META, json.dumps(publication)))

            def insert(number, customer, gid, paid_at, amount, *, valid=True, padding=''):
                body = json.dumps(dict(order_no=number, uid=100, amount_usd=amount, padding=padding))
                db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',
                           ('admin:266:' + number, '266', gid, customer, paid_at, valid, body, 1))

            date1 = '2026-10-01T12:00:00+08:00'
            insert('first', 'customer-A', '42', '2026-09-01T12:00:00+08:00', '700')
            insert('known', 'customer-A', '1327', date1, '500')
            insert('unknown', 'customer-A', '1327', date1, None)
            insert('invalid', 'customer-A', '1327', date1, '1000', valid=False)
            insert('future', 'customer-A', '1327', cutoff, '1000')
            padding = 'x' * (128 * 1024)
            for index in range(160):
                insert(f'small-{index}', f'small-{index}', '1327', date1, '1', padding=padding)

        self.service.source = UserProjection(path)
        labels = {hashlib.sha256(b'first').hexdigest(): 'old', hashlib.sha256(b'known').hexdigest(): 'new'}
        with patch('user_customer_types.read_pinned_flags', return_value=(labels, {})):
            tracemalloc.start()
            try:
                self.service.update()
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
        customer = self.service.customer_view('customer-A')['customer']
        self.assertEqual(('high', 'old', '500.00', 1, 'admin:266:unknown'),
                         tuple(customer[key] for key in ('tier', 'customer_type', 'amount_usd',
                                                       'unknown_amount_orders', 'last_order_key')))
        self.assertEqual(1, sum(group['count'] for group in self.service.group_view()['groups']))
        self.assertLess(peak, 10 * 1024 * 1024)

        config, _, _ = load_config(self.service.config_path)
        first_pin = self.service.source.read(self.now)
        with closing(sqlite3.connect(path)) as db, db:
            db.row_factory = sqlite3.Row
            previous = dict(db.execute('SELECT * FROM orders WHERE order_key=?', ('admin:266:known',)).fetchone())
            db.execute('CREATE TABLE revisions(id INTEGER PRIMARY KEY,body TEXT)')
            db.execute('INSERT INTO revisions VALUES(?,?)', (2, json.dumps([previous])))
            db.execute("UPDATE meta SET value='2' WHERE key='revision'")
            db.execute("UPDATE orders SET revision=2,valid=0 WHERE order_key=?", (previous['order_key'],))

        with self.assertRaisesRegex(LookupError, 'maintenance_projection_changed'):
            first_pin.stage_cohort(first_pin.day, config)
        with patch('user_customer_types.read_pinned_flags', return_value=(labels, {})):
            pinned = self.service.source.read(self.now)
            self.assertEqual('high', pinned.stage_cohort(pinned.day, config)['customer-A']['tier'])
            latest = self.service.source.read(self.now, latest=True)
            self.assertEqual({}, latest.stage_cohort(latest.day, config))
            import user_version_index
            with closing(sqlite3.connect(path)) as db, db:
                db.row_factory = sqlite3.Row
                self.assertTrue(user_version_index.build_batch(db)['ready'])
            indexed = self.service.source.read(self.now)
            self.assertEqual(pinned.stage_cohort(pinned.day, config), indexed.stage_cohort(indexed.day, config))

    def test_verified_uid_query_has_no_start_time_search(self):
        request = []
        def read(path, params):
            request.append((path, params))
            return dict(total=0, list=[])
        self.assertEqual([], AdminFacts(read).grants('100'))
        self.assertEqual('/admin/user.MemberCoupon/index', request[0][0])
        self.assertEqual('member_id', request[0][1]['search[0][field]'])
        self.assertEqual('100', request[0][1]['search[0][val]'])
        self.assertNotIn('start_time', request[0][1].values())
