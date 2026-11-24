"""Dispatch with fixture adapters. No process or Admin request is invoked."""
import sys
from pathlib import Path
import unittest
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'customer-segments-20261124' / 'source'))
import test_maintenance_ledger as ledger_test

NOW = ledger_test.NOW
from maintenance_dispatch import Dispatcher, checked_template
from maintenance_reconcile import reconcile


TEMPLATE = {'id': 123, 'site_id': 266, 'game_id': 1327, 'status': 1,
            'fetch_scene': 4, 'time_effect': 2, 'days': 7}


class Bridge:
    def __init__(self):
        self.grants = []
        self.template = dict(TEMPLATE)

    def detail(self, coupon):
        return self.template

    def grant(self, coupon, email, batch):
        self.grants.append((coupon, email, batch))
        raise TimeoutError('fixture disconnected after send')


class DispatchTest(unittest.TestCase):
    setUp = ledger_test.LedgerTest.setUp
    connection = ledger_test.LedgerTest.connection
    entry = ledger_test.LedgerTest.entry
    approved = ledger_test.LedgerTest.approved

    def rule(self, rule, quota=1):
        self.ledger.save_rule(rule, 0, dict(enabled=True, priority=1, template=TEMPLATE,
                                           daily_quota=quota), 'admin', NOW)

    def test_fresh_evidence_rejects_coupon_refund_and_current_tier_change(self):
        bridge = Bridge()
        for index, reason in enumerate(('manual_coupons', 'exceptions', 'tier_changed')):
            entry = self.approved(str(index))
            checker = lambda row, at: lambda db, fresh: reason
            Dispatcher(self.ledger, bridge, checker, lambda: NOW).once(entry)
            self.assertEqual('recheck_failed', self.ledger.entry(entry)['state'])
            self.assertEqual(reason, self.ledger.entry(entry)['result']['reason'])
        self.assertEqual([], bridge.grants)

    def test_disconnected_write_is_unknown_and_never_reissued(self):
        bridge = Bridge()
        entry = self.approved()
        runner = Dispatcher(self.ledger, bridge, lambda row, at: lambda db, fresh: None, lambda: NOW)
        runner.once(entry)
        runner.once(entry)
        self.assertEqual(1, len(bridge.grants))
        self.assertEqual('unknown', self.ledger.entry(entry)['state'])
        self.assertEqual('unknown', self.ledger.manual_queue()[0]['state'])

    def test_template_changed_after_rule_approval(self):
        bridge = Bridge()
        bridge.template['days'] = 21
        entry = self.approved()
        Dispatcher(self.ledger, bridge, lambda row, at: lambda db, fresh: None, lambda: NOW).once(entry)
        self.assertEqual('template_changed', self.ledger.entry(entry)['result']['reason'])
        self.assertEqual([], bridge.grants)

    def test_template_rejects_global_or_expired_coupon(self):
        for invalid in (dict(TEMPLATE, site_id=0), dict(TEMPLATE, game_id=77),
                        dict(TEMPLATE, time_effect=1, end_time='2026-10-01 00:00:00')):
            with self.assertRaises(ValueError):
                checked_template(invalid, 123, NOW)

    def test_reconciler_rotates_past_a_full_page_of_long_pending_jobs(self):
        self.rule('many', quota=101)
        entries = []
        for i in range(101):
            ident = self.approved(str(i), str(i), 'many')
            self.ledger.claim(ident, NOW)
            entries.append(ident)
        entries.sort()
        for index, ident in enumerate(entries):
            self.ledger.result(ident, 'dispatching', dict(state='pending', job_id=f'j{index}'), NOW)

        def lookup(job, email, batch):
            if job == 'j100':
                return dict(state='confirmed', member_coupon_id='23')
            return dict(state='pending', job_id=job)

        reconcile(self.ledger, lambda: NOW, lookup)
        self.assertEqual('dispatching', self.ledger.entry(entries[-1])['state'])
        reconcile(self.ledger, lambda: NOW, lookup)
        self.assertEqual('issued', self.ledger.entry(entries[-1])['state'])

    def test_reconciler_addresses_only_original_job_and_batch_and_recovers_missing_job(self):
        first = self.approved('known-job', 'c1', 'r1')
        second = self.approved('interrupted', 'c2', 'r2')
        pending = self.ledger.claim(first, NOW)
        self.ledger.claim(second, NOW)
        self.ledger.result(first, 'dispatching', dict(state='pending', job_id='o1'), NOW)
        looked_up = []
        def lookup(job, email, batch):
            looked_up.append((job, email, batch))
            return dict(state='confirmed', member_coupon_id='23')
        reconcile(self.ledger, lambda: NOW + timedelta(minutes=4), lookup)
        self.assertEqual([('o1', pending['email'], pending['batch'])], looked_up)
        self.assertEqual('issued', self.ledger.entry(first)['state'])
        self.assertEqual('unknown', self.ledger.entry(second)['state'])
