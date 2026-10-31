"""Invented customers, real SQLite Store/Service, no live clients or credentials."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'source'))
try:
    ZoneInfo('Asia/Shanghai')
except ZoneInfoNotFoundError:
    # Only this local 2026 synthetic fixture. Linux CI uses its actual zone database.
    print('A2 fixture: local tzdata absent; importing 2026 fixtures with explicit UTC+08')
    with patch('zoneinfo.ZoneInfo', return_value=timezone(timedelta(hours=8))):
        from a2_query_context import context_factory
        import user_replay_v1  # The existing frozen recipe reader also owns a TZ constant.
else:
    from a2_query_context import context_factory
from user_contract import stamp
from user_query import Service
from user_store import Store

NOW = stamp('2026-10-31T12:00:00+08:00')
SCOPE = {'scope': 'project', 'scope_id': '1327'}


def order(n, day='2026-10-02', person='one', gid='1327', amount='10.25', paid='1'):
    return {'id': n, 'order_no': 'synthetic-' + str(n), 'email': person + '@example.test',
            'uid': 0, 'gid': gid, 'site_id': '266', 'paytime': day, 'pay_status': paid,
            'status': '11', 'amount_usd_format': amount}


class A2Context(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = json.loads((BASE / 'source/user_config.json').read_text(encoding='utf-8'))
        self.config.update(snapshot_storage='recipe-v1', history_origins={'project:1327': '2026-01-01'})
        root = Path(self.temp.name) / 'facts'
        if os.name == 'nt':
            # Windows lacks POSIX mode bits. Emulate them only for this temporary
            # fixture; real filesystem authorization remains a Linux CI obligation.
            original_stat = Path.stat
            def fixture_stat(path, *args, **kwargs):
                result = original_stat(path, *args, **kwargs)
                if path == root or root in path.parents:
                    fields = list(result)
                    fields[0] &= ~0o077
                    return os.stat_result(fields)
                return result
            mode_patch = patch.object(Path, 'stat', fixture_stat)
            mode_patch.start()
            self.addCleanup(mode_patch.stop)
        self.store = Store(root, b's' * 32, self.config)
        self.source_allowed = True
        self.host_allowed = True
        self.authorizer = lambda user, query, private: self.source_allowed and user == 'operator'
        self.original = Service(self.store, self.authorizer, clock=lambda: NOW, weekly_publication=False)
        self.contexts = []
        self.context = self.make()
        self.rows = [order(1), order(2, '2026-10-20'), order(3, person='other'),
                     order(4, '2026-10-29', gid='1329', amount='999999')]
        self.load()

    def tearDown(self):
        for context in self.contexts:
            if context.service and context.service.private_cache_timer:
                context.service.private_cache_timer.cancel()

    def make(self, scope=None, observation=None):
        context = context_factory(self.original, 'operator', SCOPE if scope is None else scope,
                                  lambda user, scope: self.host_allowed and user == 'operator', observation)
        self.contexts.append(context)
        return context

    def load(self, end='2026-10-31'):
        self.store.replace_window('266', '2026-01-01', end, self.rows, NOW.isoformat())

    def summary(self, context=None, end='2026-10-25', **extra):
        return (context or self.context).aggregate({'start': '2026-10-01', 'end_exclusive': end,
                                                   'state_basis': 'period_end', **extra})

    def snapshot(self, value):
        return value['source']['snapshot_id']

    def cid(self, snapshot):
        return self.context.candidates(snapshot)['rows'][0]['opaque_customer_id']

    def test_end_to_end_frozen_investigation_and_minimal_reference(self):
        catalog = self.context.catalog()
        self.assertEqual(set(catalog['projects']), {'1327'})
        self.assertEqual(catalog['scope'], SCOPE)
        value = self.summary()
        snapshot = self.snapshot(value)
        self.assertTrue(snapshot.startswith('us_'))
        self.assertTrue(value['source']['evidence_id'].startswith('ua_'))
        self.assertEqual(value['evidence_ref']['scope'], SCOPE)
        self.assertEqual(value['load']['source_rows_scanned'], 'unknown')
        self.assertFalse(value['data']['requires_global_scope'])
        page = self.context.candidates(snapshot)
        self.assertTrue(page['complete'])
        self.assertEqual(page['total'], 2)
        detail = self.context.timeline(snapshot, page['rows'][0]['opaque_customer_id'])
        self.assertTrue(detail['complete'])
        self.assertEqual(set(detail['events'][0]), {'at', 'kind', 'stage'})
        # No email/order number/free-text/full-order bodies cross the projection boundary.
        exported = json.dumps([page, detail])
        for forbidden in ('@example.test', 'synthetic-', '999999', '"email"', '"orders"', '"uid"'):
            self.assertNotIn(forbidden, exported)
        self.assertEqual(detail['customer']['amount_unit'], 'USD')
        self.assertIn('net_contribution', detail['missing_fields'])

    def test_205_candidates_stable_pages_no_terminal_page_claim_of_whole_group(self):
        self.rows = [order(i + 10, person='person' + str(i)) for i in range(205)]
        self.load()
        snapshot = self.snapshot(self.summary())
        first = self.context.candidates(snapshot, limit=200)
        self.assertEqual((first['total'], first['returned'], first['complete']), (205, 200, False))
        second = self.context.candidates(snapshot, cursor=first['next_cursor'], limit=200)
        self.assertEqual((second['returned'], second['next_cursor'], second['complete']), (5, None, False))
        ids = [row['opaque_customer_id'] for row in first['rows'] + second['rows']]
        self.assertEqual(ids, sorted(set(ids)))
        repeated = self.context.candidates(snapshot, cursor=first['next_cursor'], limit=200)
        self.assertEqual(second['rows'], repeated['rows'])
        other = self.snapshot(self.summary(end='2026-10-26'))
        with self.assertRaisesRegex(ValueError, 'cursor_query'):
            self.context.candidates(other, cursor=first['next_cursor'])
        with self.assertRaisesRegex(ValueError, 'cursor_query'):
            self.context.candidates(snapshot, group='entered_silent', cursor=first['next_cursor'])
        for invalid in (0, 201, True):
            with self.assertRaises(ValueError):
                self.context.candidates(snapshot, limit=invalid)

    def test_timeline_pagination_has_same_projection_and_customer_bound_cursor(self):
        snapshot = self.snapshot(self.summary())
        people = self.context.candidates(snapshot)['rows']
        cid = max(people, key=lambda p: p['purchases']['covered_history_orders'])['opaque_customer_id']
        full = self.context.timeline(snapshot, cid)
        events, cursor = [], None
        while True:
            page = self.context.timeline(snapshot, cid, cursor=cursor, limit=1)
            events += page['events']
            cursor = page['next_cursor']
            if cursor is None:
                break
        self.assertEqual(events, full['events'])
        first = self.context.timeline(snapshot, cid, limit=1)
        other = next(row['opaque_customer_id'] for row in people if row['opaque_customer_id'] != cid)
        with self.assertRaisesRegex(ValueError, 'cursor_query'):
            self.context.timeline(snapshot, other, first['next_cursor'])

    def test_host_and_original_permissions_both_remain_live(self):
        snapshot = self.snapshot(self.summary())
        self.assertIs(self.original.authorizer, self.authorizer)
        self.assertIs(self.context.service.store, self.store)
        self.host_allowed = False
        for fn in (self.context.catalog, lambda: self.context.aggregate(snapshot_id=snapshot),
                   lambda: self.context.candidates(snapshot), lambda: self.context.timeline(snapshot, 'c_'+'a'*32)):
            with self.assertRaises(PermissionError):
                fn()
        self.host_allowed = True
        self.source_allowed = False
        with self.assertRaises(PermissionError):
            self.context.candidates(snapshot)

    def test_no_host_scope_no_source_reads_and_truthy_is_not_permission(self):
        for kwargs in ({}, {'identity': 'operator', 'allowed_scope': {}},
                       {'identity': 'operator', 'allowed_scope': {'scope': 'global', 'scope_id': ''}, 'validate': lambda *a: True}):
            with patch.object(self.store, 'read', side_effect=AssertionError('unexpected read')):
                context = context_factory(self.original, **kwargs)
                self.assertEqual(context.aggregate({})['status'], 'unavailable')
                self.assertEqual(context.catalog()['status'], 'unavailable')
        context = context_factory(self.original, 'operator', SCOPE, lambda *a: 1)
        with self.assertRaises(PermissionError):
            context.catalog()

    def test_old_global_dependent_snapshot_and_other_scope_are_rejected(self):
        query = {'start': '2026-10-01', 'end_exclusive': '2026-10-25', 'state_basis': 'period_end', **SCOPE}
        old = self.original.query(query, 'operator')
        self.assertTrue(old['requires_global_scope'])
        with self.assertRaises(PermissionError):
            self.context.aggregate(snapshot_id=old['snapshot_id'])
        site = self.make({'scope': 'site', 'scope_id': '266'})
        snap = self.snapshot(self.summary(site))
        with self.assertRaises(PermissionError):
            self.context.candidates(snap)
        with self.assertRaises(ValueError):
            self.context.aggregate({**query, 'scope': 'global'})

    def test_period_first_seen_is_never_verified_historical_day_zero(self):
        value = self.context.aggregate({'start': '2026-10-01'})
        rows = self.context.candidates(self.snapshot(value))['rows']
        for row in rows:
            self.assertEqual(row['first_paid'], {'at': None, 'basis': 'unknown', 'complete': False, 'missing': True})
            self.assertEqual(row['observed_first']['basis'], 'selected_period_first_seen')
        historical = self.context.candidates(self.snapshot(self.summary()))['rows']
        self.assertTrue(all(row['first_paid']['complete'] for row in historical))

    def test_missing_sales_are_unknown_and_refunds_costs_not_net_value(self):
        self.rows = [order(1, amount=None)]
        self.load()
        row = self.context.candidates(self.snapshot(self.summary()))['rows'][0]
        self.assertIsNone(row['purchases']['period_sales_usd'])
        self.assertFalse(row['purchases']['period_amount_complete'])
        self.assertEqual(row['refund_review']['status'], 'requires_review')
        self.assertIn('not_net_contribution', row['amount_basis'])

    def plan(self, cid, at='2026-10-29T00:00:00+08:00', due='2026-10-28T00:00:00+08:00'):
        return self.make(observation={'observation_at': at, 'checks': {cid: {'recheck_at': due}}})

    def test_due_without_new_purchase_requires_actual_freshness(self):
        baseline = self.snapshot(self.summary())
        cid = self.cid(baseline)
        context = self.plan(cid)
        refs = [{'opaque_customer_id': cid, 'snapshot_id': baseline}]
        stale = context.changes_due(baseline, baseline, '2026-10-29T00:00:00+08:00', refs)
        self.assertEqual(stale['changes'][0]['status'], 'refresh_required')
        current = self.snapshot(self.summary(end='2026-10-30'))
        due = context.changes_due(baseline, current, '2026-10-29T00:00:00+08:00', refs)
        self.assertEqual(due['changes'][0]['status'], 'due_no_new_purchase_observed')
        self.assertEqual(due['freshness']['status'], 'sufficient')
        with self.assertRaises(PermissionError):
            context.changes_due(baseline, current, '2026-10-30T00:00:00+08:00', refs)
        with self.assertRaises(ValueError):
            context.changes_due(baseline, current, '2026-10-29', refs)

    def test_new_purchase_and_late_correction_preserve_old_snapshot(self):
        baseline = self.snapshot(self.summary())
        people = self.context.candidates(baseline)['rows']
        person = max(people, key=lambda p: p['purchases']['covered_history_orders'])
        cid = person['opaque_customer_id']
        context = self.plan(cid)
        self.rows.append(order(9, '2026-10-28'))
        self.load()
        current = self.snapshot(self.summary(end='2026-10-30'))
        refs = [{'opaque_customer_id': cid, 'snapshot_id': baseline}]
        value = context.changes_due(baseline, current, '2026-10-29T00:00:00+08:00', refs)
        self.assertEqual(value['changes'][0]['status'], 'due_with_new_purchase')
        self.rows[-1] = order(9, '2026-10-28', paid='2')
        self.load()
        corrected = self.snapshot(self.summary(end='2026-10-30'))
        revised = context.changes_due(current, corrected, '2026-10-29T00:00:00+08:00',
                                      [{'opaque_customer_id': cid, 'snapshot_id': current}])
        self.assertIn('purchases', revised['changes'][0]['changed_fields'])
        self.assertEqual(revised['changes'][0]['status'], 'requires_review')
        self.assertTrue(revised['changes'][0]['review_required'])
        again = self.context.candidates(baseline)['rows']
        self.assertEqual(people, again)

    def test_incompatible_policy_or_identity_never_compares(self):
        baseline = self.snapshot(self.summary())
        cid = self.cid(baseline)
        context = self.plan(cid)
        changed = self.snapshot(self.summary(end='2026-10-30', policy_version='common-v1'))
        value = context.changes_due(baseline, changed, '2026-10-29T00:00:00+08:00',
                                    [{'opaque_customer_id': cid, 'snapshot_id': baseline}])
        self.assertEqual(value['status'], 'incomparable')
        self.assertEqual(value['changes'], [])
        self.config['identity_version'] = 'different-synthetic-identity'
        current = self.snapshot(self.summary(end='2026-10-30'))
        self.assertEqual(context.changes_due(baseline, current, '2026-10-29T00:00:00+08:00',
            [{'opaque_customer_id': cid, 'snapshot_id': baseline}])['status'], 'incomparable')

    def test_same_policy_label_different_actual_thresholds_is_incomparable(self):
        baseline = self.snapshot(self.summary())
        cid = self.cid(baseline)
        self.config['policies']['fc-v1'] = [15, 31, 91]
        current = self.snapshot(self.summary(end='2026-10-30'))
        result = self.plan(cid).changes_due(baseline, current, '2026-10-29T00:00:00+08:00',
                                           [{'opaque_customer_id': cid, 'snapshot_id': baseline}])
        self.assertEqual(result['status'], 'incomparable')

    def test_partial_coverage_no_false_due_and_explicit_plan_membership(self):
        baseline = self.snapshot(self.summary())
        cid = self.cid(baseline)
        self.rows.append(dict(order(99, '2026-10-27'), email=''))
        self.load()
        current = self.snapshot(self.summary(end='2026-10-30'))
        context = self.plan(cid)
        value = context.changes_due(baseline, current, '2026-10-29T00:00:00+08:00',
                                    [{'opaque_customer_id': cid, 'snapshot_id': baseline}])
        self.assertEqual(value['changes'][0]['status'], 'refresh_required')
        with self.assertRaises(PermissionError):
            context.changes_due(baseline, current, '2026-10-29T00:00:00+08:00',
                                [{'opaque_customer_id': 'c_'+'f'*32, 'snapshot_id': baseline}])

    def test_failed_refresh_retains_frozen_cutoff_and_never_advances_observation(self):
        baseline = self.snapshot(self.summary())
        cid = self.cid(baseline)
        self.store.failed_window('266', '2026-01-01', '2026-10-31', 'synthetic_failure')
        # Reuse the actual old cutoff, not the requested later observation date.
        old = self.context.aggregate(snapshot_id=baseline)
        self.assertEqual(old['source']['snapshot_id'], baseline)
        context = self.plan(cid)
        result = context.changes_due(baseline, baseline, '2026-10-29T00:00:00+08:00',
                                     [{'opaque_customer_id': cid, 'snapshot_id': baseline}])
        self.assertEqual(result['changes'][0]['status'], 'refresh_required')
        self.assertEqual(stamp(result['freshness']['snapshot_cutoff']), stamp('2026-10-25'))

    def test_not_due_and_host_plan_are_separate_from_data_freshness(self):
        snapshot = self.snapshot(self.summary())
        cid = self.cid(snapshot)
        refs = [{'opaque_customer_id': cid, 'snapshot_id': snapshot}]
        self.assertEqual(self.context.changes_due(snapshot, snapshot, '2026-10-29T00:00:00+08:00', refs)['status'], 'unavailable')
        context = self.plan(cid, due='2026-10-30T00:00:00+08:00')
        result = context.changes_due(snapshot, snapshot, '2026-10-29T00:00:00+08:00', refs)
        self.assertEqual(result['changes'][0]['status'], 'not_due')
        self.assertFalse(result['changes'][0]['checks']['recheck_at']['due'])
        self.assertEqual(result['freshness']['status'], 'insufficient_freshness')
        with self.assertRaises(ValueError):
            context.changes_due(snapshot, snapshot, '2026-10-29T00:00:00+08:00', refs + refs)

    def test_no_history_proof_and_partial_identity_never_supply_verified_day_zero(self):
        self.config['history_origins'] = {}
        snapshot = self.snapshot(self.summary())
        self.assertTrue(all(row['first_paid']['basis'] == 'unknown' for row in self.context.candidates(snapshot)['rows']))
        self.config['history_origins'] = {'project:1327': '2026-01-01'}
        self.rows.append(dict(order(98), email=''))
        self.load()
        partial = self.context.candidates(self.snapshot(self.summary()))
        self.assertEqual(partial['status'], 'partial')
        self.assertTrue(all(not row['first_paid']['complete'] for row in partial['rows']))

    def test_malformed_cursor_and_unknown_customer_do_not_fall_back_to_first_page(self):
        snapshot = self.snapshot(self.summary())
        for bad in ('garbage', 'e30', 'W10', self.context.cursor(snapshot, 'candidates', {'group': 'known_pool'}, None)):
            with self.assertRaises(ValueError):
                self.context.candidates(snapshot, cursor=bad)
        with self.assertRaises(LookupError):
            self.context.timeline(snapshot, 'c_' + 'f'*32)
        with self.assertRaises(ValueError):
            self.context.timeline(snapshot, 'not-an-email')

    def test_missing_weekly_publication_is_unavailable_without_forcing_collection(self):
        self.config['update_cadence'] = 'weekly-v1'
        self.original.weekly_publication = None
        context = self.make()
        self.assertEqual(context.catalog()['weekly_update']['status'], 'initial_publication_pending')
        with patch.object(self.store, 'replace_window', side_effect=AssertionError('unexpected collection')):
            result = context.aggregate({'start': '2026-10-01'})
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'weekly_initial_publication_pending')


if __name__ == '__main__':
    unittest.main()
