"""Durable fixed reference and adoption on the original operation ID."""
from contextlib import closing
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_curve_runtime_v6 as runtime_fixture
from test_curve_runtime_v6 import OPERATION, PLATFORM, writer
from test_curve_writer_v6 import saved
from test_curve_strategy_v6 import evidence, proof
from test_curve_preview_v6 import SNAPSHOT_ID, SNAPSHOT_TIME, handler_post, preview_request
from fc_pricing_v3 import api, runtime
from fc_pricing_v3.curve_strategy_v6 import build_candidates, choose_action, confirm_adoption, propose_adoption
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.price_curve import EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, curve_key, read_curve
from fc_pricing_v3.pricing_proof_v6 import validate_curve
from test_pricing_proof_v6 import basket, quote


class AdoptionLedger(unittest.TestCase):
    def setUp(self):
        # Reuse the original runtime/F4 transport fixture without inheriting its tests.
        self.run = runtime_fixture.CurveRuntime()
        self.run.setUp()
        self.addCleanup(self.run.doCleanups)
        self.run.prepare(propagate=False)
        self.db = self.run.db
        self.baseline = saved(self.run.transport.rows[writer.PRODUCTS[PLATFORM][1]])
        self.target = deepcopy(self.baseline['native_payload'])
        self.target['more']['price'][1] = '103'
        self.target = saved(self.target)

    def start(self):
        return self.db.start_curve_episode(PLATFORM, 'same-rules-v1', 'Approved initial A',
                                           initial_curve=self.baseline, readback_ref='trusted-initial-capture')

    def proposal(self, state):
        reference, episode = state['reference'], state['episode']
        comparison = build_candidates(self.target, reference, episode, 'large')
        financial = proof(self.target)
        decision = choose_action(comparison, {curve_key(self.target): financial})
        values = evidence()
        values['cumulative']['initial_reference_curve_id'] = episode['initial_reference_curve_id']
        proposal = propose_adoption(reference, comparison, decision, values, operation_id=OPERATION)
        return dict(platform=PLATFORM, proposal=proposal, proof=financial)

    def attach(self, adoption):
        bundle = self.run.bundle
        bundle.pop('sha256')
        bundle['curve_adoption'] = adoption
        bundle['sha256'] = fingerprint(bundle)
        (self.run.root / 'quotes' / 'run.json').write_text(json.dumps(dict(result=dict(decision_receipt=bundle))))

    def test_reference_survives_reopen_and_episode_rotation_inherits_a(self):
        start = self.start()
        self.assertEqual(self.start(), start)
        reopened = Ledger(self.db.path)
        first_id = start['episode']['comparison_episode_id']
        next_state = reopened.start_curve_episode(PLATFORM, 'new-offer-domain', 'Offer domain changed',
                                                  expected_episode_id=first_id)
        self.assertNotEqual(next_state['episode']['comparison_episode_id'], first_id)
        self.assertEqual(next_state['reference'], start['reference'])
        self.assertEqual(next_state['episode']['initial_reference_curve'], self.baseline)
        self.assertEqual(reopened.curve_strategy_state(PLATFORM), next_state)
        self.assertIsNone(reopened.curve_strategy_state('PC'))

    def test_original_reconcile_promotes_once_after_complete_curve_readback(self):
        state = self.start()
        self.attach(self.proposal(state))
        partial = self.run.execute()
        self.assertEqual(partial['status'], 'PARTIALLY_APPLIED')
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), state)
        self.run.transport.apply_recipient()
        recovered = runtime.reconcile(OPERATION)
        adopted = self.db.curve_strategy_state(PLATFORM)
        self.assertEqual(recovered['status'], 'COMPLETED')
        self.assertEqual(recovered['curve_adoption_result']['status'], 'ADOPTED')
        self.assertEqual(adopted['episode'], state['episode'])
        self.assertEqual(adopted['reference']['reference_curve'], self.target)
        self.assertEqual(adopted['reference']['confirmed_operation_id'], OPERATION)
        self.assertEqual(runtime.reconcile(OPERATION), recovered)
        self.assertEqual(len(self.run.transport.posts), 1)

    def test_already_confirmed_original_can_be_adopted_without_another_dispatch(self):
        state = self.start()
        self.run.execute()
        self.run.transport.apply_recipient()
        original = runtime.reconcile(OPERATION)
        self.assertEqual(original['status'], 'COMPLETED')
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), state)
        request = self.proposal(state)
        result = self.db.adopt_confirmed_curve(request, current_curve=self.target)
        self.assertEqual(result['status'], 'ADOPTED')
        self.assertEqual(self.db.adopt_confirmed_curve(request, current_curve=self.target), result)
        self.assertEqual(self.db.get('operations', OPERATION), original)
        self.assertEqual(len(self.run.transport.posts), 1)

    def test_preview_after_original_writer_adopts_editor_provenance_curve(self):
        metadata = dict(source='Admin Goods edit read only', verified_domain='native stored tiers only',
                        editor_asset_sha256=EDITOR_ASSET_SHA256, editor_handler_sha256=EDITOR_HANDLER_SHA256)
        bundle = self.run.bundle
        target = bundle['action']['curves'][PLATFORM]
        target = read_curve(target['native_payload'], target['identity'],
                            dict(metadata, catalogue_origin=target['native_contract']['catalogue_origin']))
        target_key = curve_key(target)
        domain = dict(bundle['curve_proofs'][PLATFORM]['scope'], curve_key=target_key,
                      coverage_status='complete', coverage_gaps=[])
        baskets = dict(main=basket('closed_bjt_7d', [('ordinary', '50')]),
                       recent=basket('latest_24h', [('ordinary', '30')]))
        path = quote('ordinary', target_key, regular_usd='103', net_receipt_usd='103')
        bundle['curve_proofs'][PLATFORM] = validate_curve(target, baskets, dict(curve_key=target_key, paths=[path]), domain)
        bundle['action']['curves'][PLATFORM] = target
        bundle['sha256'] = fingerprint({k: v for k, v in bundle.items() if k != 'sha256'})
        self.target = read_curve(self.target['native_payload'], self.target['identity'], metadata)
        self.baseline = read_curve(self.baseline['native_payload'], self.baseline['identity'], metadata)
        state = self.start()
        self.attach(self.proposal(state))
        self.assertEqual(self.run.execute()['status'], 'PARTIALLY_APPLIED')
        self.run.transport.apply_recipient()
        completed = runtime.reconcile(OPERATION)
        self.assertEqual(completed['curve_adoption_result']['status'], 'ADOPTED')
        adopted = self.db.curve_strategy_state(PLATFORM)['reference']
        self.assertEqual(adopted['confirmed_operation_id'], OPERATION)
        self.assertEqual(adopted['reference_curve']['native_contract']['editor_asset_sha256'], EDITOR_ASSET_SHA256)
        self.assertEqual(adopted['reference_curve']['native_contract']['editor_handler_sha256'], EDITOR_HANDLER_SHA256)
        self.assertEqual(adopted['reference_curve']['native_payload'], self.run.transport.rows[writer.PRODUCTS[PLATFORM][1]])
        snapshot = dict(snapshot_id=SNAPSHOT_ID, origin='live_collector', mode='production',
                        created_at=SNAPSHOT_TIME, evidence={'run_id': SNAPSHOT_ID,
                        'storefront': {'rows': {PLATFORM: {'sku_id': str(writer.PRODUCTS[PLATFORM][1])}}}})
        self.db.put('pricing_snapshots', SNAPSHOT_ID, snapshot)
        with closing(self.db.connect()) as conn:
            before = list(conn.iterdump())
        with patch.object(api, 'STORE', self.db.path.parent), patch('fc_shared_admin.SessionManager', return_value=self.run.transport):
            status, result = handler_post('preview', preview_request())
        self.assertEqual(status, 202)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIsNone(result['decision']['selected'])
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(result['decision']['reference_curve_id'], adopted['reference_curve_id'])
        self.assertIn('A', {label for row in result['decision']['candidates'] for label in row['labels']})
        self.assertNotIn('current_reference_catalogue_terms_differ', json.dumps(result['decision']['candidate_gaps']))
        self.assertEqual(len(self.run.transport.posts), 1)
        with closing(self.db.connect()) as conn:
            self.assertEqual(list(conn.iterdump()), before)

    def test_previous_original_requires_fresh_current_curve_and_unclosed_window(self):
        state = self.start()
        self.run.execute()
        self.run.transport.apply_recipient()
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'COMPLETED')
        request = self.proposal(state)
        with self.assertRaisesRegex(ValueError, 'strategy_adoption_current_curve_changed'):
            self.db.adopt_confirmed_curve(request, current_curve=self.baseline)
        window = self.db.get('actual_price_windows', OPERATION)
        window['resource_closed_at'] = {'base:PS': SNAPSHOT_TIME}
        self.db.put('actual_price_windows', OPERATION, window)
        with self.assertRaisesRegex(ValueError, 'strategy_adoption_original_window_not_current'):
            self.db.adopt_confirmed_curve(request, current_curve=self.target)
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), state)
        self.assertEqual(len(self.run.transport.posts), 1)

    def test_cross_platform_and_unproven_input_are_rejected_before_dispatch(self):
        state = self.start()
        request = self.proposal(state)
        for bad in (dict(request, platform='XBOX'), dict(request, proof=dict(request['proof'], status='PROOF_INCOMPLETE'))):
            with self.subTest(bad=bad['platform']):
                self.attach(bad)
                with self.assertRaisesRegex(ValueError, 'strategy_adoption'):
                    self.run.execute()
        self.assertIsNone(self.db.get('operations', OPERATION))
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), state)
        self.assertEqual(self.run.transport.posts, [])

    def test_stale_episode_keeps_a_without_losing_original_confirmation(self):
        state = self.start()
        self.attach(self.proposal(state))
        self.run.execute()
        successor = self.db.start_curve_episode(PLATFORM, 'new-contract', 'Offers changed',
            expected_episode_id=state['episode']['comparison_episode_id'])
        self.run.transport.apply_recipient()
        original = runtime.reconcile(OPERATION)
        self.assertEqual(original['status'], 'COMPLETED')
        self.assertEqual(original['curve_adoption_result']['status'], 'NOT_ADOPTED')
        self.assertEqual(original['curve_adoption_result']['reason'], 'strategy_adoption_reference_or_episode_changed')
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), successor)

    def test_receipt_for_different_full_target_does_not_adopt(self):
        state = self.start()
        self.attach(self.proposal(state))
        self.run.execute()
        self.run.transport.apply_recipient()
        def swapped_receipt(operation):
            result = self.run.read_original(operation)
            audit = json.loads(self.run.audit_path.read_text())
            audit['curve_results'][PLATFORM]['propagation']['curve_mapping']['target_curve_key'] = 'another-curve'
            self.run.save_audit(audit)
            return result
        self.run.reconcile.side_effect = swapped_receipt
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), state)
        self.assertEqual(len(self.run.transport.posts), 1)

    def test_self_consistent_mapping_cannot_adopt_different_high_tier(self):
        state = self.start()
        self.attach(self.proposal(state))
        self.run.execute()
        self.run.transport.apply_recipient()
        def false_mapping(operation):
            result = self.run.read_original(operation)
            audit = json.loads(self.run.audit_path.read_text())
            row = audit['curve_results'][PLATFORM]
            altered = deepcopy(row['actual_site266_curve']['native_payload'])
            altered['more']['price'][1] = '104'
            altered = saved(altered)
            altered_key = curve_key(altered)
            row.update(actual_site266_curve=altered, actual_site266_curve_key=altered_key)
            row['propagation']['curve_mapping']['actual_site266_curve_key'] = altered_key
            self.run.save_audit(audit)
            return result
        self.run.reconcile.side_effect = false_mapping
        operation = runtime.reconcile(OPERATION)
        self.assertEqual(operation['status'], 'UNKNOWN')
        self.assertEqual(operation['steps'][0]['receipt']['reason'], 'curve_window_primary_mapping_unconfirmed')
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), state)
        self.assertEqual(len(self.run.transport.posts), 1)

    def test_finish_transaction_does_not_publish_half_adoption(self):
        state = self.start()
        self.attach(self.proposal(state))
        self.run.execute()
        self.run.transport.apply_recipient()
        put = self.db.put
        def fail_operation(table, key, body, db=None):
            if table == 'operations' and body.get('status') == 'COMPLETED':
                raise OSError('simulated ledger write failure')
            return put(table, key, body, db)
        with patch.object(self.db, 'put', side_effect=fail_operation):
            with self.assertRaisesRegex(OSError, 'simulated ledger write failure'):
                runtime.reconcile(OPERATION)
        self.assertEqual(self.db.curve_strategy_state(PLATFORM), state)
        self.assertIsNone(self.db.get('readback_receipts', OPERATION))
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))
        self.assertEqual(runtime.reconcile(OPERATION)['curve_adoption_result']['status'], 'ADOPTED')
        self.assertEqual(len(self.run.transport.posts), 1)

    def test_preview_reads_fixed_reference_without_authorizing_a_decision(self):
        state = self.start()
        snapshot = dict(snapshot_id=SNAPSHOT_ID, origin='live_collector', mode='production',
                        created_at=SNAPSHOT_TIME, evidence={'run_id': SNAPSHOT_ID,
                        'storefront': {'rows': {PLATFORM: {'sku_id': str(writer.PRODUCTS[PLATFORM][1])}}}})
        self.db.put('pricing_snapshots', SNAPSHOT_ID, snapshot)
        with patch.object(api, 'STORE', self.db.path.parent), patch('fc_shared_admin.SessionManager', return_value=self.run.transport):
            status, result = handler_post('preview', preview_request())
        self.assertEqual(status, 202)
        self.assertEqual(result['decision']['reference_curve_id'], state['reference']['reference_curve_id'])
        self.assertEqual(result['decision']['comparison_episode_id'], state['episode']['comparison_episode_id'])
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIsNone(result['decision']['selected'])
        self.assertFalse(result['execution_authorized'])
        with closing(self.db.connect()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM operations').fetchone()[0], 0)

    def test_mixing_previous_revisions_does_not_reuse_old_evidence(self):
        state = self.start()
        latest = self.proposal(state)['proposal']
        reference = state['reference']
        target_key = latest['target_curve_key']
        reference['adoption_evidence'] = dict(
            order_revisions={'anon-order-1': 'semantic-cost-v2', 'other-order': 'same'},
            used_order_revisions={'anon-order-1': ['semantic-cost-v1', 'semantic-cost-v2'], 'other-order': ['same']})
        comparison = build_candidates(self.target, reference, state['episode'], 'large')
        decision = choose_action(comparison, {target_key: proof(self.target)})
        mixed = evidence()
        mixed['cumulative']['initial_reference_curve_id'] = state['episode']['initial_reference_curve_id']
        mixed['order_revisions']['other-order'] = 'same'
        with self.assertRaisesRegex(ValueError, 'strategy_adoption_has_no_new_evidence'):
            propose_adoption(reference, comparison, decision, mixed, operation_id=OPERATION)
        mixed['order_revisions']['new-order'] = 'new'
        proposal = propose_adoption(reference, comparison, decision, mixed, operation_id=OPERATION)
        self.assertEqual(set(proposal['evidence_delta']), {'new-order'})
        receipt = dict(operation_id=OPERATION, status='COMPLETED', complete_curve_readback=True,
                       curve_key=target_key, readback_ref='original')
        adopted = confirm_adoption(reference, proposal, self.target, receipt)
        self.assertEqual(adopted['adoption_evidence']['order_revisions']['anon-order-1'], 'semantic-cost-v2')
