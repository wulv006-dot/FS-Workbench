"""Read-only V6 candidate diagnostics over existing saved evidence."""
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import permutations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_curve_preview_v6 import SNAPSHOT_ID, handler_post, preview_request
from test_curve_strategy_v6 import fixture
from fc_pricing_v3 import api, business_source, runtime
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.planning_baskets_v6 import HISTORICAL_SCOPE
from fc_pricing_v3.price_curve import read_curve
import fc_shared_admin


NOW = datetime.fromisoformat('2026-11-13T10:10:00+08:00')
SNAPSHOT_AT = NOW - timedelta(minutes=5)
OLDER_ID = '00000000-0000-4000-8000-000000000042'


class PreviewCandidatesV6(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.db = Ledger(folder / 'control.sqlite3')
        self.store_snapshot(OLDER_ID, SNAPSHOT_AT - timedelta(hours=1))
        self.store_snapshot(SNAPSHOT_ID, SNAPSHOT_AT)
        current, _, _ = fixture()
        row = current['native_payload']
        for key, values in (('delivery_time', ['1'] * len(current['tiers'])), ('hot', [0] * len(current['tiers']))):
            row['more'][key] = values
        row['title'] = 'coins'
        self.current = read_curve(row, current['identity'],
                                  {'source': 'Admin Goods edit read only', 'verified_domain': 'native stored tiers only'})
        self.manager = Mock(token=None)
        self.manager.request.return_value = (200, json.dumps(dict(code=1, data=dict(row=row))).encode())
        stack.enter_context(patch.object(api, 'STORE', folder))
        stack.enter_context(patch.object(api, 'clock', return_value=NOW))
        stack.enter_context(patch.object(api, 'ledger', side_effect=AssertionError('writable ledger accessed')))
        stack.enter_context(patch.object(runtime, 'clock', return_value=NOW))
        stack.enter_context(patch.object(fc_shared_admin, 'SessionManager', return_value=self.manager))

    def store_snapshot(self, ident, at):
        value = dict(snapshot_id=ident, origin='live_collector', mode='production',
                     created_at=at.isoformat(), evidence=dict(run_id=ident,
                     storefront={'rows': {'PS': {'sku_id': '163329311'}}}))
        self.db.put('pricing_snapshots', ident, value)

    def store_history(self, name, *, available=SNAPSHOT_AT, paid_window=None, snapshot_id=SNAPSHOT_ID):
        period = business_source.historical_period('7d', now=SNAPSHOT_AT)
        paid_at = datetime.fromisoformat(period['paid_window_start']) + timedelta(hours=1)
        private = dict(order_key='do-not-expose-order-' + name, source_sha256='original-order-revision',
                       available_at=available.isoformat(), paid_at=paid_at.isoformat(), platform='PS',
                       base_k='1000', cost_cny=None)
        coverage = dict(source_sha256=name, population_scope=HISTORICAL_SCOPE,
                        paid_window_start=period['paid_window_start'],
                        paid_window_end_exclusive=period['paid_window_end_exclusive'],
                        population_status='complete', window_complete=True, refund_revision_coverage='unknown')
        attachment = dict(schema_version='fc-pricing-v3-history-input-v1', source_sha256=name,
                          available_at=available.isoformat(), paid_window=paid_window or period['paid_window'],
                          snapshot_ids=[snapshot_id], historical_orders=[private], historical_orders_coverage=coverage)
        self.db.put('historical_inputs', name, attachment)

    def preview(self, **kwargs):
        code, value = handler_post('preview', preview_request(**kwargs))
        self.assertEqual(code, 202)
        self.assertEqual(value['status'], 'PROOF_INCOMPLETE')
        self.assertIsNone(value['decision']['selected'])
        self.assertFalse(value['execution_authorized'])
        return value

    def test_fixed_a_exposes_compiled_diagnostics_and_existing_basket_coverage(self):
        state = self.db.start_curve_episode('PS', 'fixture-rules', 'Trusted approved fixture A',
                                            initial_curve=self.current, readback_ref='original-A')
        self.store_history('same-snapshot-seven-days', available=SNAPSHOT_AT + timedelta(seconds=1))
        self.store_history('future', available=NOW + timedelta(seconds=1))
        self.store_history('wrong-snapshot', snapshot_id=OLDER_ID)
        wrong_period = business_source.historical_period('14d', now=SNAPSHOT_AT)['paid_window']
        self.store_history('wrong-period', paid_window=wrong_period)
        with closing(self.db.connect()) as conn:
            before = list(conn.iterdump())
        result = self.preview(segment='large')
        decision = result['decision']
        self.assertEqual(decision['reference_curve_id'], state['reference']['reference_curve_id'])
        self.assertEqual(decision['selected_segment'], 'large')
        self.assertEqual(decision['historical_evidence_as_of'], NOW.isoformat())
        candidates = {label: item for item in decision['candidates'] for label in item['labels']}
        self.assertEqual(candidates['CURRENT']['curve_key'], result['current_catalogue']['curve_key'])
        self.assertEqual(candidates['CURRENT']['curve_key'], candidates['A']['curve_key'])
        self.assertNotEqual(candidates['B']['curve_key'], candidates['A']['curve_key'])
        self.assertEqual(candidates['B']['catalogue_basis'], 'offline_admin_editor_model')
        self.assertEqual(candidates['B']['financial_proof']['status'], 'PROOF_INCOMPLETE')
        main = candidates['B']['planning_baskets']['main']
        self.assertEqual(main['source_sha256'], 'same-snapshot-seven-days')
        self.assertEqual(main['paid_orders'], 1)
        self.assertIn('paid_source_refund_revisions_unverified', main['coverage_gaps'])
        self.assertIn('current_quote_or_eligibility_unverified', main['coverage_gaps'])
        self.assertNotIn('do-not-expose-order', json.dumps(result))
        with closing(self.db.connect()) as conn:
            self.assertEqual(list(conn.iterdump()), before)

    def test_missing_reference_does_not_promote_current_to_a(self):
        result = self.preview()
        decision = result['decision']
        self.assertIn('adopted_reference_curve_unavailable', decision['gaps'])
        self.assertEqual([item['labels'] for item in decision['candidates']], [['CURRENT']])
        self.assertIsNone(self.db.curve_strategy_state('PS'))

    def test_real_saved_terms_changes_still_block_candidates(self):
        self.db.start_curve_episode('PS', 'fixture-rules', 'Trusted approved fixture A',
                                    initial_curve=self.current, readback_ref='original-A')
        for field, index, changed in (('gold', 0, '51'), ('give', 2, '1'), ('discount', 2, '99')):
            with self.subTest(field=field):
                row = deepcopy(self.current['native_payload'])
                row['more'][field][index] = changed
                self.manager.request.return_value = (200, json.dumps(dict(code=1, data=dict(row=row))).encode())
                decision = self.preview()['decision']
                self.assertEqual([item['labels'] for item in decision['candidates']], [['CURRENT']])
                self.assertEqual(decision['candidate_gaps'],
                                 {label: ['current_reference_catalogue_terms_differ'] for label in 'ABC'})

    def test_only_conflicts_at_final_visible_revision_matter(self):
        rows = [('older-a', SNAPSHOT_AT), ('older-b', SNAPSHOT_AT),
                ('latest', SNAPSHOT_AT + timedelta(seconds=1))]
        for order in permutations(rows):
            with self.subTest(order=order):
                with closing(self.db.connect()) as conn:
                    conn.execute('DELETE FROM historical_inputs')
                    conn.commit()
                for revision, at in order:
                    self.store_history(revision, available=at)
                self.store_history('future', available=NOW + timedelta(seconds=1))
                with closing(self.db.connect()) as conn:
                    history = api._curve_preview_history(conn, {'snapshot_id': SNAPSHOT_ID,
                                                               'created_at': SNAPSHOT_AT.isoformat()}, NOW)
                self.assertEqual(history['source_sha256'], 'latest')

    def test_conflicting_final_visible_revision_is_rejected(self):
        at = SNAPSHOT_AT + timedelta(seconds=1)
        self.store_history('latest-a', available=at)
        self.store_history('latest-b', available=at)
        self.store_history('older', available=SNAPSHOT_AT)
        self.store_history('future', available=NOW + timedelta(seconds=1))
        with closing(self.db.connect()) as conn:
            with self.assertRaisesRegex(ValueError, '^pricing_curve_preview_history_revision_conflict$'):
                api._curve_preview_history(conn, {'snapshot_id': SNAPSHOT_ID,
                                                 'created_at': SNAPSHOT_AT.isoformat()}, NOW)

    def test_old_snapshot_does_not_borrow_today_curve_as_historical_candidate(self):
        result = self.preview(snapshot_id=OLDER_ID)
        self.assertEqual(result['current_catalogue']['captured_at'], NOW.isoformat())
        self.assertEqual(result['decision']['candidates'], [])
        self.assertIn('historical_snapshot_frozen_curve_unavailable', result['decision']['gaps'])

    def test_invalid_segment_does_not_open_database_or_read_admin(self):
        with patch.object(api.sqlite3, 'connect', side_effect=AssertionError('database accessed')):
            self.assertEqual(handler_post('preview', preview_request(segment='middle')),
                             (400, {'error': 'pricing_curve_preview_fields_invalid'}))
        self.manager.request.assert_not_called()
