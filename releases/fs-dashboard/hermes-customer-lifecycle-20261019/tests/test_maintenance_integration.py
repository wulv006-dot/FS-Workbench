"""Exercise the stage-maintenance entry points with offline source adapters."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
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
from customer_segments import ConfigCommitUnknown, write_config
from customer_tracking import Store
from maintenance_sources import AdminFacts, Facts, UserProjection
from maintenance_service import Maintenance
from tracking_controller import TrackingController
from user_contract import digest as publication_digest
from user_weekly import CONTRACT as PUBLICATION_CONTRACT, META as PUBLICATION_META
from vip_maintenance import VipMaintenance


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

    def create(self):
        self.rule()
        self.tick()
        self.assertEqual([], self.service.queue_view('review')['items'])
        self.tick(2, run=False)
        self.service.advance(self.service.facts(), {'version':0, 'stages':{'1327':[14,30,60]}, 'tiers':{}})
        return self.service.ledger.queue(('reviewing',))[0]

    def grant(self, ident):
        return dict(id=ident, member_id=100, site_id=266, status=2, grant_batch_no='manual',
                    start_time=(self.now-timedelta(hours=1)).isoformat())

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

    def test_usage_and_grant_for_same_coupon_count_once_and_both_pin_evidence(self):
        entry = self.create()
        self.admin_rows(usage=lambda: [self.coupon_use()], grants=lambda: [self.grant(22)])
        self.service.update()
        review, = self.service.ledger.reviews(entry['id'])
        self.assertEqual(['manual_coupons'], review['reasons'])
        self.assertEqual(1, review['matches']['manual_coupons'])
        self.assertEqual('held', self.service.ledger.entry(entry['id'])['state'])

    def test_changed_coupon_usage_during_review_discards_stale_pass(self):
        entry = self.create()
        visible = False

        def grants():
            nonlocal visible
            visible = True
            return []

        self.admin_rows(usage=lambda: [self.coupon_use()] if visible else [], grants=grants)
        self.service.update()
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual([], self.service.ledger.reviews(entry['id']))
        self.service.update()
        self.assertEqual('held', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual(['manual_coupons'], self.service.ledger.reviews(entry['id'])[0]['reasons'])

    def test_changed_admin_grant_evidence_does_not_write_stale_pass(self):
        entry = self.create()
        self.admin.coupons = [[], [self.grant(21)]]
        self.service.update()
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual([], self.service.ledger.reviews(entry['id']))
        self.service.update()
        self.assertEqual('held', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual(['manual_coupons'], self.service.ledger.reviews(entry['id'])[0]['reasons'])

    def test_grant_read_failure_stays_pending_then_late_grant_blocks_dispatch(self):
        entry = self.create()
        self.admin.coupons = [OSError('fixture unavailable')]
        self.service.update()
        self.assertEqual('reviewing', self.service.ledger.entry(entry['id'])['state'])
        self.admin.coupons = []
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
        self.admin.issues = [dict(order_key='admin:266:a', refund='partial_observed')]
        self.service.dispatch()
        row = self.service.ledger.entry(entry['id'])
        self.assertEqual('exceptions', row['result']['reason'])
        self.assertEqual([], self.bridge.sent)
        self.source.orders = [order(valid=False)]
        self.tick(1)
        timeline = self.service.ledger.entry(entry['id'])
        self.assertEqual('recheck_failed', timeline['state'])
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
        self.assertEqual('confirmed', self.service.ledger.entry(entry['id'])['state'])
        self.assertEqual([], self.bridge.sent)

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
                        rows = projection.read(self.now, latest=latest).orders
                        self.assertEqual(['first'], [row['order_no'] for row in rows])
                        self.assertEqual('Buyer@example.net', rows[0]['email'])

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