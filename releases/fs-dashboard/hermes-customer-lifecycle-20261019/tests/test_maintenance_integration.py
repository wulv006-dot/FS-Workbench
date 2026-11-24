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
sys.path[:0] = [str(ROOT / 'source'), str(ROOT.parent / 'customer-segments-20261124' / 'source')]
from customer_segments import ConfigCommitUnknown, write_config
from maintenance_sources import AdminFacts, Facts
from maintenance_service import Maintenance
from tracking_controller import TrackingController
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