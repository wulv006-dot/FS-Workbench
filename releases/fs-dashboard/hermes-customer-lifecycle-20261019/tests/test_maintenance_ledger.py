"""Maintenance ledger state, timeout history, and coupon protections."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from maintenance_ledger import Ledger, ALLOWED, batch_for


NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)
DAY = timedelta(days=1)


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.root = TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / 'test.sqlite3'
        self.ledger = Ledger(self.connection)
        self.rule('r1')
        self.rule('r2')

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            yield db

    def rule(self, rule, quota=1):
        self.ledger.save_rule(rule, 0, dict(enabled=True, priority=1, template={'id': 123},
                                           daily_quota=quota), 'admin', NOW)

    def entry(self, event='e1', customer='c1', rule='r1', ready=NOW):
        entry = self.ledger.enqueue(event, customer, 'example@example.net', rule, NOW)
        self.ledger.commit_review(entry, dict(digest='old', decision='pass'), 'old', ready)
        return entry

    def approved(self, *args, **kwargs):
        entry = self.entry(*args, **kwargs)
        self.assertTrue(self.ledger.decide(entry, 'confirmed', 'admin', NOW))
        return entry

    def test_atomic_state_gate_and_review_dedup(self):
        entry = self.ledger.enqueue('e', 'c', 'example@example.net', 'r1', NOW)
        self.assertEqual(entry, self.ledger.enqueue('e', 'c', 'example@example.net', 'r1', NOW))
        self.assertFalse(self.ledger.decide(entry, 'confirmed', 'admin', NOW))
        review = dict(digest='old', decision='pass')
        self.assertFalse(self.ledger.commit_review(entry, review, 'new', NOW))
        self.assertEqual('reviewing', self.ledger.entry(entry)['state'])
        self.assertTrue(self.ledger.commit_review(entry, review, 'old', NOW))
        self.assertFalse(self.ledger.commit_review(entry, review, 'old', NOW))
        self.assertEqual(1, len(self.ledger.reviews(entry)))
        self.assertTrue(self.ledger.decide(entry, 'removed', 'admin', NOW))
        self.assertFalse(self.ledger.decide(entry, 'confirmed', 'admin', NOW))
        self.assertFalse(self.ledger.expire(entry, NOW + 4 * DAY))
        self.assertNotIn('dispatching', ALLOWED['removed'])

    def test_timeout_uses_history_at_expiration_and_cas(self):
        on = self.entry('on')
        off = self.entry('off', rule='r2')
        self.ledger.set_auto('r1', True, 'before', NOW + 3 * DAY)
        self.ledger.set_auto('r1', False, 'after', NOW + 3 * DAY + timedelta(seconds=1))
        self.ledger.set_auto('r2', True, 'after', NOW + 3 * DAY + timedelta(seconds=1))
        self.assertFalse(self.ledger.expire(on, NOW + 3 * DAY - timedelta(microseconds=1)))
        self.assertTrue(self.ledger.expire(on, NOW + 4 * DAY))
        self.assertTrue(self.ledger.expire(off, NOW + 4 * DAY))
        self.assertEqual('auto_confirmed', self.ledger.entry(on)['state'])
        self.assertEqual('before', self.ledger.entry(on)['result']['enabled_by'])
        self.assertEqual('expired', self.ledger.entry(off)['state'])
        self.assertFalse(self.ledger.decide(on, 'confirmed', 'admin', NOW + 4 * DAY))

    def test_concurrent_claims_observe_customer_and_rule_quotas(self):
        entries = [self.approved('a', 'same', 'r1'), self.approved('b', 'same', 'r2'),
                   self.approved('c', 'other', 'r1'), self.approved('d', 'other', 'r2')]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda item: self.ledger.claim(item, NOW), entries))
        claimed = [self.ledger.entry(i) for i in entries if self.ledger.entry(i)['state'] == 'dispatching']
        self.assertEqual(2, len(claimed))
        self.assertEqual(2, len({item['customer_id'] for item in claimed}))
        self.assertEqual(2, len({item['rule_id'] for item in claimed}))
        self.assertEqual(2, len({item['batch'] for item in claimed}))
        for item in claimed:
            self.assertRegex(item['batch'], r'^FCSM_[A-F0-9]{32}$')
            self.assertIsNone(self.ledger.claim(item['id'], NOW))

    def test_dispatch_priority_is_applied_before_the_queue_page_limit(self):
        self.ledger.save_rule('higher-number', 0, dict(enabled=True, priority=100,
                              template={'id': 123}, daily_quota=100), 'admin', NOW)
        for index in range(100):
            self.approved('lower-'+str(index), 'lower-'+str(index), 'higher-number')
        high = self.entry('higher-8', 'same', 'r1', ready=NOW)
        self.ledger.decide(high, 'confirmed', 'admin', NOW)
        self.assertEqual(high, self.ledger.dispatch_queue(NOW)[0]['id'])

    def test_deferral_rechecks_customer_quota_on_the_next_day(self):
        first = self.approved('a', 'other', 'r1')
        old = self.approved('b', 'same', 'r2')
        self.ledger.claim(old, NOW - 28 * DAY)
        self.ledger.result(old, 'dispatching', dict(state='confirmed', member_coupon_id='12'), NOW)
        self.ledger.claim(first, NOW)
        candidate = self.approved('c', 'same', 'r1')
        self.ledger.claim(candidate, NOW)
        self.assertEqual('deferred', self.ledger.entry(candidate)['state'])
        self.ledger.claim(candidate, NOW + timedelta(hours=1))
        self.assertEqual('deferred', self.ledger.entry(candidate)['state'])
        self.ledger.claim(candidate, NOW + DAY)
        self.assertEqual('recheck_failed', self.ledger.entry(candidate)['state'])
        self.assertEqual('customer_quota', self.ledger.entry(candidate)['result']['reason'])

    def test_bridge_result_states_and_recorded_jobs_never_resubmit(self):
        states = [
            ({'state': 'confirmed', 'member_coupon_id': '1'}, 'issued', None),
            ({'state': 'pending', 'job_id': 'job'}, 'dispatching', 'job'),
            ({'state': 'pending_register', 'job_id': 'job'}, 'pending_register', 'job'),
            ({'state': 'pending_register'}, 'pending_register', None),
            ({'state': 'limit'}, 'limited', None),
            ({'state': 'rejected'}, 'rejected', None),
            ({'state': 'unknown'}, 'unknown', None),
            ({'state': 'confirmed'}, 'unknown', None),
        ]
        self.rule('bulk', 20)
        for index, (receipt, state, job) in enumerate(states):
            with self.subTest(receipt=receipt):
                ident = str(index)
                entry = self.approved(ident, ident, 'bulk')
                self.ledger.claim(entry, NOW)
                self.assertTrue(self.ledger.result(entry, 'dispatching', receipt, NOW))
                row = self.ledger.entry(entry)
                self.assertEqual(state, row['state'])
                self.assertEqual(job, row['job_id'])
                self.assertIsNone(self.ledger.claim(entry, NOW))
        self.assertEqual(3, len(self.ledger.manual_queue()))
        self.assertEqual(2, len(self.ledger.reconcile_queue()))

    def test_claim_timestamp_order_cannot_hide_a_committed_customer_reservation(self):
        first = self.approved('later-clock', 'same', 'r1')
        second = self.approved('earlier-clock', 'same', 'r2')
        self.assertIsNotNone(self.ledger.claim(first, NOW + timedelta(microseconds=1)))
        self.assertIsNone(self.ledger.claim(second, NOW))
        self.assertEqual('customer_quota', self.ledger.entry(second)['result']['reason'])

    def test_pending_register_without_job_releases_at_exactly_30_days(self):
        first = self.approved('a')
        self.ledger.claim(first, NOW)
        self.ledger.result(first, 'dispatching', dict(state='pending_register'), NOW)
        self.assertEqual(1, len(self.ledger.active_customer('c1', NOW + 30 * DAY - timedelta(seconds=1))))
        self.assertEqual([], self.ledger.active_customer('c1', NOW + 30 * DAY))
        second = self.approved('b')
        self.assertIsNotNone(self.ledger.claim(second, NOW + 30 * DAY))

    def test_limits_and_confirmed_rejection_release_both_quotas(self):
        first = self.approved('a')
        self.ledger.claim(first, NOW)
        self.ledger.result(first, 'dispatching', dict(state='limit'), NOW)
        second = self.approved('b')
        self.ledger.claim(second, NOW)
        self.ledger.result(second, 'dispatching', dict(state='rejected'), NOW)
        self.assertIsNotNone(self.ledger.claim(self.approved('c'), NOW))
        self.assertRegex(batch_for('c1', 'r1', 'e1'), r'^FCSM_[A-F0-9]{32}$')