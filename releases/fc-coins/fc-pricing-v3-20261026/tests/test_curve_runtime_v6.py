"""Exercise original-operation coordination against the synthetic F4 transport."""
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3 import adapters, runtime
from fc_pricing_v3.dispatch import CURVE_REJECTED, CURVE_WRITE_PROTOCOL, prewrite_refusal
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.ledger import Ledger
from test_curve_writer_v6 import OPERATION, PLATFORM, Transport, setup_bundle, writer
from test_price_curve_v6 import EDITOR_CONTRACT


class CurveRuntime(unittest.TestCase):
    def test_large_band_smart_trial_uses_own_orders_without_competitor_quotes(self):
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        now = datetime.fromisoformat('2026-11-13T12:00:00+00:00')
        plan = dict(plan_id='plan', mode='smart', revision=1, starts_at='2026-11-13T09:00:00+00:00')
        state = dict(reference=reference, episode=dict(episode, opened_at=plan['starts_at']))
        performance = {'small': {'current': {'paid_orders': 8}}, 'large': {'current': {'paid_orders': 30}}}
        stale_large_offer = dict(source='Lootbar', platform='PS', purchase_k='1000', regular_price='10',
                                delivered_k='1000', captured_at=now.isoformat(), currency='USD',
                                promotion_eligibility='all_customers', comparable=True, conditional=False)
        no_market = runtime._curve_preference('PS', current, {}, {'performance': performance},
                                              now, plan=plan, state=state)
        old_market = runtime._curve_preference('PS', current, {'competitor_offers':[stale_large_offer]},
                                               {'performance': performance}, now, plan=plan, state=state)
        self.assertEqual(old_market, no_market)
        self.assertEqual((no_market['segment'], no_market['source']), ('large', 'smart_three_hour_block'))
        self.assertIn(no_market['label'], 'ABC')

    def test_v6_learning_uses_confirmed_full_curves_and_changes_later_assignments(self):
        from copy import deepcopy
        from fc_pricing_v3.curve_strategy_v6 import comparison_background_key
        from fc_pricing_v3.price_curve import curve_key, read_curve
        from fc_pricing_v3.smart import curve_learning, curve_slot, observed_curve_blocks
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        start = datetime.fromisoformat('2026-11-13T00:00:00+00:00')
        now = start + timedelta(hours=49)
        plan = dict(plan_id='plan', revision=1, mode='smart', starts_at=start.isoformat())
        state = dict(reference=reference, episode=dict(episode, opened_at=start.isoformat()))
        row = deepcopy(current['native_payload'])
        row['more']['price'][4] = '97.85'
        higher = read_curve(row, current['identity'], current['native_contract'])
        self.assertEqual(current['tiers'][2], higher['tiers'][2])
        self.assertNotEqual(curve_key(current), curve_key(higher))
        slots = [curve_slot(plan, PLATFORM, state, start + timedelta(hours=3 * block)) for block in range(16)]
        pairs = [slot['slot'] for slot in slots[:8] if slot['segment'] == 'large'][:2]
        windows, outcomes = [], []
        for first in pairs:
            for label, slot, curve in (('A', slots[first], current), ('C', slots[first + 8], higher)):
                opened = datetime.fromisoformat(slot['starts_at'])
                ident = 'window-' + str(slot['block'])
                key = curve_key(curve)
                decision_key = 'all-' + key
                info = dict(slot, actual_label=label, decision_curve_key=decision_key, primary_curve_key=key,
                            background_curve_key=comparison_background_key(curve, 'large'))
                windows.append(dict(operation_id=ident, action={'curves': {PLATFORM: curve}},
                    origin='confirmed_public_price_window', mode='production', write_protocol=CURVE_WRITE_PROTOCOL,
                    opened_at=slot['starts_at'], resource_closed_at={'base:PS': slot['ends_at']},
                    mutable_resources=['base:PS'], curve_selection={PLATFORM: {'assignment': info}},
                    decision_curve_keys={PLATFORM: decision_key}, curve_confirmations={PLATFORM: dict(
                        operation_id=ident, target_curve_key=decision_key, actual_site266_curve_key=key,
                        basis='full_prices_and_tier_specs_readback')},
                    continuations=[dict(resources=['base:PS'], at=(opened + timedelta(hours=1)).isoformat(),
                                        curve_selection={PLATFORM: {'assignment': info}})]))
                for index in range(5):
                    outcomes.append(dict(order_key=f'{ident}:{index}', platform=PLATFORM, price_window_id=ident,
                        occurred_at=(opened + timedelta(minutes=25 + 30 * index)).isoformat(),
                        curve_key=key, decision_curve_key=decision_key, actual_net_usd='100',
                        actual_contribution_usd='22' if label == 'C' else '20',
                        cost_basis='same_order_Order_shipping_CNY_margin_at_actual_USD_receipt',
                        purchase_k='1000', promised_bonus_k='20', promised_delivered_k='1020',
                        new_customer=True, customer_key=f'{ident}:{index}'))
        coverage = dict(query_complete=True, unscoped_time_gaps=False, gap_events=[],
                        source_sha256='test-source', observed_at=now.isoformat())
        online = dict(smart_plan_id='plan', smart_revision=1, learning_coverage=coverage, actual_outcomes=outcomes)
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertEqual(learned['large']['policy']['winner'], 'C')
        self.assertFalse(learned['large']['policy']['causal_effect_estimated'])
        blocks = observed_curve_blocks(plan, PLATFORM, state, online, windows, now)
        self.assertEqual([(block['hours'], len(block['events'])) for block in blocks], [(3, 5)] * 4)
        self.assertEqual(len({key for block in blocks for key in block['prices']}), 2)
        scheduled_at = [now + timedelta(hours=3 * i) for i in range(16)]
        def choices(evidence):
            selected = [runtime._curve_preference(PLATFORM, current, {}, {'learning': evidence}, at,
                                                  plan=plan, state=state) for at in scheduled_at]
            return [row for row in selected if row['segment'] == 'large']
        self.assertNotEqual([row['label'] for row in choices(learned)], [row['label'] for row in choices({})])
        self.assertTrue(all(row['source'] == 'observed_curve_policy' for row in choices(learned)))
        # A later same-order cost revision updates the original exposures and corrects C.
        for order in outcomes:
            if order['curve_key'] == curve_key(higher):
                order['actual_contribution_usd'] = '16'
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertIsNone(learned['large']['policy']['winner'])
        self.assertIn('C', learned['large']['correction']['effective_blocks'])
        self.assertNotIn('C', {row['label'] for row in choices(learned)})
        # A separate small-band change is a different background for large.
        mixed = deepcopy(current['native_payload'])
        mixed['more']['price'][2] = '10.02'
        mixed = read_curve(mixed, current['identity'], current['native_contract'])
        other_background = curve_learning(plan, PLATFORM, state, online, windows, now, mixed)
        self.assertEqual(other_background['large']['correction']['effective_blocks'], {})
        # Complete paid coverage can report zero. Incomplete membership is unavailable.
        online['actual_outcomes'] = []
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertEqual(learned['large']['blocks'][-1]['platform']['orders'], 0)
        self.assertEqual(learned['large']['blocks'][-1]['platform']['procurement_gross_usd'], '0')
        self.assertIsNone(learned['large']['blocks'][-1]['platform']['procurement_margin'])
        coverage['gap_events'] = [dict(occurred_at=windows[-1]['opened_at'], group=PLATFORM)]
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertIsNone(learned['large']['blocks'][-1]['platform']['orders'])
        coverage['query_complete'] = False
        self.assertEqual(curve_learning(plan, PLATFORM, state, online, windows, now, current), {})

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        enter = stack.enter_context
        folder = enter(tempfile.TemporaryDirectory())
        self.root = Path(folder)
        for name in ('quotes', 'jobs', 'executions', 'previews'):
            (self.root / name).mkdir()
        self.db = Ledger(self.root / 'v3' / 'control.sqlite3')
        enter(patch.object(runtime, 'ROOT', self.root))
        enter(patch.object(runtime, 'ledger', return_value=self.db))
        enter(patch('automation_policy.load_policy', return_value={'revision': 7}))
        self.legacy_nochange = enter(patch.object(adapters, 'verify_nochange'))
        self.legacy_postwrite = enter(patch.object(adapters, 'reconcile_postwrite'))
        self.legacy_close = enter(patch.object(runtime, 'close_on_order_admin'))
        self.preview = dict(status='review_only', preview_id='fixture-preview')
        self.worker = SimpleNamespace(APP=self.root, run=Mock(return_value=(0, self.preview)))
        enter(patch.dict(sys.modules, {'fc27_cloud_worker': self.worker}))
        self.dispatch = enter(patch.object(adapters, 'dispatch_base'))
        self.reconcile = enter(patch.object(adapters, 'reconcile_base'))

    def tearDown(self):
        self.legacy_nochange.assert_not_called()
        self.legacy_postwrite.assert_not_called()
        self.legacy_close.assert_not_called()

    def prepare(self, *, small='10', large='103', propagate=True):
        bundle, capability, before, recipient = setup_bundle(small, large)
        bundle.update(assignment_id='fixture-assignment', resources=['base:PS'])
        bundle['steps'] = [dict(step_id='base:all', kind='base', state='PENDING')]
        bundle['created_at'] = datetime.now(timezone.utc).isoformat()
        if small == '10' and large == '100':
            bundle['steps'] = []
        for action, total in ((bundle['before_action'], '10'), (bundle['action'], small)):
            action['base_prices'] = {'PS': total}
        bundle.pop('sha256')
        bundle['sha256'] = fingerprint(bundle)
        self.bundle = bundle
        plan = dict(plan_id='plan', generation='generation', revision=4, state='ACTIVE', ends_at=None)
        self.db.put('metadata', 'generation', {'id': 'generation'})
        self.db.put('pricing_plans', 'plan', plan)
        with self.db.transaction() as conn:
            conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)', ('base:PS', 'plan', 4, 'generation'))
        quote = dict(result=dict(decision_receipt=bundle), snapshot_sha256='fixture-run',
                     quote_engine_sha256='fixture-engine')
        (self.root / 'quotes' / 'run.json').write_text(json.dumps(quote))
        (self.root / 'jobs' / 'run.json').write_text(json.dumps(dict(request={})))
        self.transport = Transport(before, recipient, propagate=propagate)
        capability['order_projection'] = self.transport.projection()
        self.capabilities = {PLATFORM: capability}
        self.capability = capability
        self.reconcile.side_effect = self.read_original
        self.dispatch.side_effect = self.send_original

    @property
    def audit_path(self):
        return self.root / 'executions' / (OPERATION + '.json')

    def save_audit(self, audit):
        self.audit_path.write_text(json.dumps(audit))

    def send_original(self, operation, before_send=lambda _: None):
        item = writer.curve_catalog_plan(self.bundle, PLATFORM, self.capability)
        audit = dict(execution_id=OPERATION, write_protocol=CURVE_WRITE_PROTOCOL,
                     pricing_decision_receipt=self.bundle, selected=operation['dispatch_context']['selected'],
                     curve_results={PLATFORM: dict(item, operation_id=OPERATION)}, status='RUNNING',
                     sync_confirmed=False, changed=[], business_dispatch_started=False)
        return writer.drive_curve_catalog(self.transport, audit, self.save_audit,
                                          before_send, self.capabilities)

    def read_original(self, operation):
        self.assertEqual(operation['operation_id'], OPERATION)
        return writer.reconcile_curve_catalog(self.transport, json.loads(self.audit_path.read_text()),
                                              self.save_audit, self.capabilities)

    def execute(self):
        with patch.object(runtime, 'verify_quote', return_value=self.bundle):
            return runtime.execute_run('run')

    def leased(self):
        with closing(self.db.connect()) as conn:
            return conn.execute('SELECT operation_id FROM resource_leases').fetchall() != []

    def test_high_tier_only_dispatches_exact_platform_and_freezes_full_readback(self):
        self.prepare()
        result = self.execute()
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['dispatch_context']['selected'], ['PS'])
        self.assertEqual(result['readback']['execution_id'], OPERATION)
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.transport.projection_writes, [])
        window = self.db.get('actual_price_windows', OPERATION)
        actual = window['action']['curves']['PS']
        self.assertEqual(actual['identity']['site_id'], '266')
        self.assertEqual(actual['tiers'][1]['native_price_usd'], '103')
        self.assertEqual(json.loads(self.audit_path.read_text())['status'], 'CONFIRMED')
        self.assertFalse(self.leased())
        self.reconcile.assert_not_called()

    def test_partial_original_confirms_after_propagation_without_reposting(self):
        self.prepare(propagate=False)
        first = self.execute()
        self.assertEqual(first['status'], 'PARTIALLY_APPLIED')
        self.assertTrue(self.leased())
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))
        self.transport.apply_recipient()
        recovered = runtime.reconcile(OPERATION)
        self.assertEqual(recovered['status'], 'COMPLETED')
        self.assertEqual(recovered['readback']['execution_id'], OPERATION)
        self.assertFalse(self.leased())
        self.assertEqual(runtime.reconcile(OPERATION), recovered)
        self.assertEqual(len(self.transport.posts), 1)
        self.reconcile.assert_called_once()
        self.dispatch.assert_called_once()

    def test_original_admin_rejection_closes_only_after_exact_no_change_readback(self):
        self.prepare()
        self.transport.rejection_code = 0
        original_request = self.transport.request
        recipient_id = writer.PRODUCTS[PLATFORM][1]

        def drift_after_send(path, *, data, token):
            if data is None and self.transport.posts and path.endswith('=' + str(recipient_id)):
                raise TimeoutError
            return original_request(path, data=data, token=token)

        with patch.object(self.transport, 'request', side_effect=drift_after_send):
            self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertTrue(self.leased())
        original = json.loads(self.audit_path.read_text())['curve_results'][PLATFORM]['catalog']['post_response']
        closed = runtime.reconcile(OPERATION)
        self.assertEqual(closed['status'], CURVE_REJECTED)
        self.assertEqual(closed['readback']['curve_results'][PLATFORM]['catalog']['post_response'], original)
        self.assertEqual(closed['steps'][0]['receipt_history'][-1]['state'], 'UNKNOWN')
        self.assertFalse(self.leased())
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))
        self.assertEqual(runtime.reconcile(OPERATION), closed)
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.transport.projection_writes, [])
        self.reconcile.assert_called_once()

    def test_undocumented_reply_and_unchanged_prices_stay_unknown(self):
        self.prepare()
        self.transport.rejection_code = '0'
        self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.assertTrue(self.leased())
        self.assertEqual(len(self.transport.posts), 1)

    def test_unknown_with_matching_current_prices_is_only_read_on_original_id(self):
        self.prepare()
        self.transport.response_lost = True
        first = self.execute()
        self.assertEqual(first['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.assertEqual(len(self.transport.posts), 1)
        self.dispatch.assert_called_once()
        self.reconcile.assert_called_once()
        self.assertTrue(self.leased())
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))

    def test_mismatched_audit_cannot_close_or_trigger_readback(self):
        self.prepare()
        def mismatched(operation):
            result = self.send_original(operation)
            audit = json.loads(self.audit_path.read_text())
            audit.update(execution_id='different', sync_confirmed=True, sync_message='legacy success')
            self.save_audit(audit)
            return result
        self.dispatch.side_effect = mismatched
        self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.reconcile.assert_not_called()
        self.assertTrue(self.leased())

    def test_nochange_needs_complete_current_readback_and_does_not_write(self):
        self.prepare(large='100')
        first = self.execute()
        self.assertEqual(first['dispatch_context']['selected'], [])
        self.assertEqual(first['status'], 'PUBLIC_PENDING')
        self.assertEqual(first['readback']['reason'], 'pricing_curve_current_full_readback_unavailable')
        self.assertFalse(first['readback']['write_performed'])
        self.assertEqual(runtime.reconcile(OPERATION), first)
        self.dispatch.assert_not_called()
        self.reconcile.assert_not_called()
        self.assertTrue(self.leased())

    def test_proven_prewrite_refusal_cancels_original_without_retry(self):
        self.prepare()
        self.dispatch.side_effect = None
        self.dispatch.return_value = dict(prewrite_refusal('{}'), write_protocol=CURVE_WRITE_PROTOCOL)
        result = self.execute()
        self.assertEqual(result['status'], 'CANCELLED_NOT_SENT')
        self.assertFalse(self.leased())
        self.assertEqual(runtime.reconcile(OPERATION), result)
        self.dispatch.assert_called_once()

    def test_original_writer_lock_busy_is_proven_zero_dispatch(self):
        self.prepare()
        self.dispatch.side_effect = None
        self.dispatch.return_value = dict(status='NOT_SENT', write_protocol=CURVE_WRITE_PROTOCOL, exit_code=75)
        self.assertEqual(self.execute()['status'], 'CANCELLED_NOT_SENT')
        self.assertFalse(self.leased())
        self.dispatch.assert_called_once()

    def test_original_f4_audit_proves_send_intent_was_not_dispatched(self):
        self.prepare()
        def refuse(_):
            raise ValueError('pricing_curve_resource_fence_changed')
        self.dispatch.side_effect = lambda op: self.send_original(op, before_send=refuse)
        self.assertEqual(self.execute()['status'], 'CANCELLED_NOT_SENT')
        self.assertEqual(json.loads(self.audit_path.read_text())['status'], 'FAILED_BEFORE_WRITE')
        self.assertEqual(self.transport.posts, [])
        self.assertFalse(self.leased())

    def test_readback_failure_cannot_erase_confirmed_catalog_or_release_lease(self):
        self.prepare(propagate=False)
        self.assertEqual(self.execute()['status'], 'PARTIALLY_APPLIED')
        self.reconcile.side_effect = OSError('readback transport failed')
        recovered = runtime.reconcile(OPERATION)
        self.assertEqual(recovered['status'], 'PARTIALLY_APPLIED')
        receipt = recovered['steps'][0]['receipt']
        self.assertEqual(receipt['curve_results']['PS']['catalog']['status'], 'confirmed')
        self.assertEqual(receipt['recovery']['reason'], 'pricing_curve_original_audit_unavailable')
        self.assertTrue(self.leased())
        self.dispatch.assert_called_once()

    def test_bare_not_sent_without_original_transport_evidence_stays_unknown(self):
        self.prepare()
        self.dispatch.side_effect = None
        self.dispatch.return_value = dict(status='NOT_SENT', write_protocol=CURVE_WRITE_PROTOCOL)
        self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.dispatch.assert_called_once()
        self.reconcile.assert_not_called()
        self.assertTrue(self.leased())

    def test_existing_legacy_financial_verifier_does_not_authorize_v6(self):
        self.prepare()
        quote = json.loads((self.root / 'quotes' / 'run.json').read_text())
        with self.assertRaisesRegex(ValueError, 'pricing_curve_quote_identity_invalid'):
            runtime.verify_quote(quote, {}, ['PS'], for_execution=True)

    def test_inconsistent_dirty_curve_cannot_use_empty_steps(self):
        self.prepare()
        self.bundle['steps'] = []
        with self.assertRaisesRegex(ValueError, 'pricing_curve_original_dispatch_scope_changed'):
            self.execute()
        self.dispatch.assert_not_called()
        self.worker.run.assert_not_called()

    def test_monitor_uses_curve_contract_and_keeps_optional_sources_optional(self):
        from fc_pricing_v3.monitoring import source_coverage

        now = datetime.now(timezone.utc)
        plan = dict(plan_id='curve-plan', revision=2, write_protocol=CURVE_WRITE_PROTOCOL)
        snapshot = dict(plan_id='curve-plan', plan_revision=2, write_protocol=CURVE_WRITE_PROTOCOL,
                        snapshot_id='fixture-run', created_at=now.isoformat(),
                        evidence=dict(checked_at=now.isoformat(),
                                      source_coverage=dict(optional_missing=['Lootbar','U7Buy','ArabUT'])),
                        result=dict(status='PROOF_INCOMPLETE',
                                    rows=[dict(platform='PS', status='PROOF_INCOMPLETE')]))
        coverage = source_coverage([snapshot], [plan], now)
        self.assertEqual(coverage['issues'], [])
        self.assertEqual(coverage['plans'][0]['curve_proof_status'], 'PROOF_INCOMPLETE')
        snapshot['result']['rows'][0]['status'] = 'HARD_CONSTRAINT_FAILED'
        self.assertEqual(source_coverage([snapshot], [plan], now)['issues'],
                         [dict(level='critical', code='coin_v3_curve_hard_constraint_failed:PS')])

    def test_newer_diagnostic_collection_does_not_supersede_legacy_run(self):
        from fc_pricing_v3.competitor_offers import POLICY

        folder = self.root / 'runs'
        folder.mkdir()
        legacy = folder / 'legacy.json'
        candidate = folder / 'candidate.json'
        legacy.write_text('{}')
        candidate.write_text(json.dumps(dict(competitor_policy=POLICY)))
        self.assertEqual(runtime.latest_collection(self.root, curve=False), legacy)
        self.assertEqual(runtime.latest_collection(self.root, curve=True), candidate)

    def test_native_candidate_activation_and_execution_use_actual_verifier(self):
        self.run_verified_curve_cycle()

    def test_cost_repair_advances_reference_only_after_original_writer_confirmation(self):
        self.run_verified_curve_cycle(cost_repair=True)

    def test_initial_activation_adopts_current_and_authorizes_verified_repair(self):
        self.run_verified_curve_cycle(cost_repair=True, initial_activation=True)

    def test_proven_keep_opens_and_extends_only_readback_window(self):
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import IDENTITY_FIELDS, curve_key, read_curve
        from test_pricing_proof_v6 import fixture

        self.prepare(large='100')
        now = datetime.now(timezone.utc)
        plan = self.db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol=CURVE_WRITE_PROTOCOL,
                    starts_at=(now - timedelta(hours=1)).isoformat(), resources=['base:PS'])
        self.db.put('pricing_plans', 'plan', plan)
        row = self.transport.rows[writer.PRODUCTS[PLATFORM][1]]
        curve = read_curve(row, {key: row[key] for key in IDENTITY_FIELDS}, EDITOR_CONTRACT)
        self.db.start_curve_episode(PLATFORM, 'fixture-rules', 'Adopted readback', initial_curve=curve,
                                    readback_ref='fixture-initial')
        now = datetime.now(timezone.utc)
        _, baskets, evidence, domain = fixture()
        key = curve_key(curve)
        domain['curve_key'] = evidence['curve_key'] = evidence['paths'][0]['curve_key'] = key
        proof = dict(baskets=baskets, evidence=evidence, domain=domain)
        first = '00000000-0000-4000-8000-000000000092'
        second = '00000000-0000-4000-8000-000000000093'
        for run, at in ((first, now), (second, now + timedelta(hours=1))):
            source = dict(run_id=run, competitor_policy=POLICY)
            observed = dict(captured_at=at.isoformat(), valid_until=(at + timedelta(minutes=10)).isoformat(),
                            primary_curve=curve, primary_inputs={key: proof},
                            readbacks=[dict(path='/admin/goods.Goods/edit?id=' + curve['identity']['id'],
                                            http_status=200, response_code=1, response_sha256='fixture-site266')])
            runtime.store_curve_proof_inputs(self.db, source, {PLATFORM: observed})
            for _ in range(2):
                result = runtime.calculate_curve_cycle(self.db, source, plan, {'v3_operation_id': OPERATION}, at)
                self.assertEqual(result['status'], 'NO_PRICE_CHANGE')
                self.assertNotIn('decision_receipt', result)
        windows = self.db.all('actual_price_windows')
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual(window['origin'], 'observed_native_curve_window')
        self.assertFalse(window['write_performed'])
        self.assertFalse(window['randomization_verified'])
        self.assertEqual(window['opened_at'], now.isoformat())
        self.assertEqual(curve_key(window['action']['curves'][PLATFORM]), key)
        self.assertEqual(len(window['continuations']), 1)
        self.assertFalse(window['continuations'][0]['write_performed'])
        self.assertIn('assignment', window['curve_selection'][PLATFORM])
        self.assertIn('assignment', window['continuations'][0]['curve_selection'][PLATFORM])
        self.assertNotIn('B', (window['curve_selection'][PLATFORM]['assignment']['actual_label'],
                              window['continuations'][0]['curve_selection'][PLATFORM]['assignment']['actual_label']))
        self.assertEqual(self.db.all('operations'), [])
        self.assertEqual(self.db.all('readback_receipts'), [])
        self.assertEqual(self.transport.posts, [])

    def run_verified_curve_cycle(self, *, cost_repair=False, initial_activation=False):
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import IDENTITY_FIELDS, curve_key, read_curve
        from fc_pricing_v3.pricing_proof_v6 import FAILED
        from test_pricing_proof_v6 import basket, quote

        self.prepare()
        now = datetime.now(timezone.utc)
        old = self.db.get('pricing_plans', 'plan')
        old.update(mode='daily', starts_at=(now - timedelta(minutes=30)).isoformat(), resources=['base:PS'],
                   parameters={'competitor_policy': 'lootbar_primary_arabut_secondary_v1'})
        self.db.put('pricing_plans', 'plan', old)
        next_slot = datetime.fromisoformat(old['starts_at']) + timedelta(hours=1)
        cycle_key = 'cycle:plan:' + str(int(next_slot.timestamp())) + ':r0'
        self.db.enqueue('cycle', cycle_key, next_slot, dict(plan_id='plan', revision=4,
                                                           scheduled_at=next_slot.isoformat()))
        current_row = self.transport.rows[writer.PRODUCTS[PLATFORM][1]]
        current = read_curve(current_row, {k: current_row[k] for k in IDENTITY_FIELDS}, EDITOR_CONTRACT)
        target_row = dict(current['native_payload'], more=dict(current['native_payload']['more'], price=['10', '103']))
        target = read_curve(target_row, current['identity'], EDITOR_CONTRACT)
        if not initial_activation:
            self.db.start_curve_episode(PLATFORM, 'fixture-current-rules', 'Previously adopted A',
                                        initial_curve=current if cost_repair else target,
                                        readback_ref='fixture-site266-readback')
        reference_before = self.db.curve_strategy_state(PLATFORM)
        all_before = self.bundle['before_action']['curves'][PLATFORM]
        all_target = self.bundle['action']['curves'][PLATFORM]
        def inputs(curve, *, total='103', safe_cost='76'):
            key = curve_key(curve)
            domain = dict(self.bundle['curve_proofs'][PLATFORM]['scope'], curve_key=key,
                          coverage_status='complete', coverage_gaps=[])
            path = quote('ordinary', key, regular_usd=total, net_receipt_usd=total, safe_cost_usd=safe_cost,
                         expected_cost_usd='75', stress_cost_usd='84')
            return dict(baskets=dict(main=basket('closed_bjt_7d', [('ordinary', '50')]),
                                     recent=basket('latest_24h', [('ordinary', '30')])),
                        evidence=dict(curve_key=key, paths=[path]), domain=domain)
        platform_inputs = dict(captured_at=now.isoformat(), valid_until=(now + timedelta(minutes=10)).isoformat(),
                               primary_curve=current, segment='large', preferred_label='A',
                               primary_inputs={curve_key(target): inputs(target),
                                               curve_key(current): inputs(current, total='100')},
                               all_before=all_before, all_targets={curve_key(target): all_target},
                               all_inputs={curve_key(all_target): inputs(all_target)})
        if initial_activation:
            self.assertIsNone(reference_before)
            platform_inputs.update(preferred_label='CURRENT',
                readbacks=[dict(path='/admin/goods.Goods/edit?id=' + current['identity']['id'],
                                http_status=200, response_code=1, response_sha256='fixture-site266-readback')])
        if cost_repair:
            failed_input = inputs(current, total='100', safe_cost='83')
            failed = runtime._validated_curve(current, failed_input)
            self.assertEqual(failed['status'], FAILED)
            repair = dict(current_proof_hash=failed['proof_hash'], domain_status='complete',
                          domain_ref='fixture-native-domain', affected_segments=['large'],
                          candidates=[dict(curve=target, inputs=inputs(target, safe_cost='83'),
                                           all_target=all_target, all_inputs=inputs(all_target, safe_cost='83'))])
            platform_inputs['primary_inputs'][curve_key(current)] = failed_input
            platform_inputs['repair'] = repair
        candidate_id = '00000000-0000-4000-8000-000000000090'
        run_id = '00000000-0000-4000-8000-000000000091'
        collection = dict(kind='collect', request=dict(write_protocol=CURVE_WRITE_PROTOCOL))
        (self.root/'jobs'/(candidate_id+'.json')).write_text(json.dumps(collection))
        evidence = dict(run_id=candidate_id, competitor_policy=POLICY)
        policy = dict(revision=7, interval_minutes=60, system_enabled=True, mode='auto', platforms=['PS'])
        with patch('automation_policy.load_policy', return_value=policy), \
                patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
            self.assertEqual(runtime.collection_scope(self.db, candidate_id)['scope']['competitor_policy'], POLICY)
            self.assertEqual(runtime.calculate(evidence)['status'], 'PROOF_INCOMPLETE')
            with closing(self.db.connect()) as conn:
                from fc_pricing_v3.api import _latest_snapshot
                self.assertIsNone(_latest_snapshot(conn))
                self.assertEqual(_latest_snapshot(conn, curve=True)['snapshot_id'], candidate_id)
            with self.assertRaisesRegex(ValueError, 'pricing_curve_activation_proof_incomplete'):
                runtime.activate_curve_plan(self.db, 'plan', 4, 'wulv', candidate_id)
            self.assertEqual(self.db.get('pricing_plans', 'plan'), old)
            runtime.store_curve_proof_inputs(self.db, evidence, {'PS': platform_inputs})
            activated = runtime.activate_curve_plan(self.db, 'plan', 4, 'wulv', candidate_id)
            self.assertEqual(activated['revision'], 5)
            self.assertEqual(runtime.activate_curve_plan(self.db, 'plan', 4, 'wulv', candidate_id), activated)
            self.assertEqual(activated['parameters']['competitor_policy'], POLICY)
            if initial_activation:
                reference_before = self.db.curve_strategy_state(PLATFORM)
                self.assertEqual(curve_key(reference_before['reference']['reference_curve']),curve_key(current))
                self.assertEqual(self.transport.posts, [])
            with closing(self.db.connect()) as conn:
                cycle = conn.execute('SELECT body FROM durable_jobs WHERE id=?', (cycle_key,)).fetchone()
                self.assertEqual(json.loads(cycle[0]), dict(plan_id='plan', revision=5,
                                                          scheduled_at=next_slot.isoformat()))
            request = dict(v3_plan_id='plan', v3_operation_id=OPERATION)
            (self.root/'jobs'/(run_id+'.json')).write_text(json.dumps(dict(actor='system-automation', request=request)))
            self.assertEqual(runtime.collection_scope(self.db, run_id)['scope']['competitor_policy'], POLICY)
            evidence = dict(run_id=run_id, competitor_policy=POLICY)
            runtime.store_curve_proof_inputs(self.db, evidence, {'PS': platform_inputs})
            result = runtime.calculate(evidence)
            self.assertEqual(result['status'], 'READY')
            self.bundle = result['decision_receipt']
            self.assertEqual(self.db.curve_strategy_state(PLATFORM), reference_before)
            if cost_repair:
                self.assertEqual(self.bundle['curve_selection'][PLATFORM]['label'], 'COST_REPAIR')
            for folder in ('config',):
                (self.root/folder).mkdir()
            (self.root/'config/v3-control.json').write_text(json.dumps(dict(generation='generation', enabled=True)))
            quote = dict(result=result, evidence=evidence, automation_policy_revision=7,
                         snapshot_sha256='original-run-hash', quote_engine_sha256='original-engine-hash')
            (self.root/'quotes'/(run_id+'.json')).write_text(json.dumps(quote))
            self.assertEqual(runtime.verify_quote(quote, policy, ['PS'], for_execution=True), self.bundle)
            self.assertEqual(self.transport.posts, [])
            tampered = dict(self.bundle, curve_proofs={'PS': dict(self.bundle['curve_proofs']['PS'], status='PROOF_INCOMPLETE')})
            tampered['sha256'] = fingerprint({k: v for k, v in tampered.items() if k != 'sha256'})
            with self.assertRaisesRegex(ValueError, 'pricing_curve_execution_proof_unverified'):
                runtime.verify_quote(dict(quote, result=dict(result, decision_receipt=tampered)),
                                     policy, ['PS'], for_execution=True)
            completed = runtime.execute_run(run_id)
            self.assertEqual(completed['status'], 'COMPLETED', completed['steps'])
            self.assertEqual(completed['readback']['execution_id'], OPERATION)
            self.assertEqual(len(self.transport.posts), 1)
            self.assertEqual(runtime.execute_run(run_id)['status'], 'COMPLETED')
            self.assertEqual(len(self.transport.posts), 1)
            after = self.db.curve_strategy_state(PLATFORM)
            if cost_repair:
                self.assertEqual(after['reference']['confirmed_operation_id'], OPERATION)
                self.assertEqual(after['reference']['event_type'], 'COST_REPAIR')
                self.assertEqual(after['reference']['reference_curve']['tiers'][1]['native_price_usd'], '103')
                self.assertEqual(after['episode']['prior_comparison_episode_id'],
                                 reference_before['episode']['comparison_episode_id'])
            else:
                self.assertEqual(after, reference_before)

    def test_closed_clock_hour_source_and_existing_three_hour_schedule_select_native_segment(self):
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        now = datetime(2026, 11, 13, 6, 7, tzinfo=timezone.utc)
        closed = now.replace(minute=0)
        available = dict(query_complete=True, observed_at=now.isoformat(), source_sha256='fixture-outcomes')

        def order(at, quantity, net):
            return dict(platform='PS', occurred_at=at.isoformat(), purchase_k=quantity, actual_net_usd=net,
                        actual_contribution_usd='8',
                        cost_basis='same_order_Order_shipping_CNY_margin_at_actual_USD_receipt')

        rows = [order(closed - timedelta(minutes=30), '1000', '91'),
                order(closed - timedelta(days=1, minutes=30), '1000', '95'),
                order(closed + timedelta(minutes=2), '100', '10')]
        performance = runtime._same_hour_curve_performance(
            'PS', dict(actual_outcomes=rows, learning_coverage=available), now)
        self.assertEqual(list(performance), ['large'])
        self.assertEqual(performance['large']['current']['net_paid_usd'], '91')
        self.assertEqual(performance['large']['previous']['net_paid_usd'], '95')
        self.assertEqual(runtime._same_hour_curve_performance(
            'PS', dict(actual_outcomes=rows, learning_coverage=dict(available, query_complete=False)), now), {})
        start = (closed - timedelta(hours=2)).isoformat()
        plan = dict(plan_id='plan', mode='smart', starts_at=start, revision=5)
        state = dict(reference=reference, episode=dict(episode, opened_at=start))
        inputs = dict(performance=performance)
        current_slot = runtime._curve_preference('PS', current, {}, inputs, now, plan=plan, state=state)
        same_slot = runtime._curve_preference(
            'PS', current, {}, inputs, now + timedelta(minutes=15), plan=plan, state=state)
        self.assertEqual((current_slot['label'], current_slot['segment'], current_slot['block']),
                         (same_slot['label'], same_slot['segment'], same_slot['block']))
        self.assertEqual(current_slot['source'], 'smart_three_hour_block')
        self.assertIn(current_slot['label'], 'ABC')
        slots = [runtime._curve_preference('PS', current, {}, {}, now + timedelta(hours=3 * block),
                                         plan=plan, state=state)['assignment'] for block in range(16)]
        self.assertEqual([slot['segment'] for slot in slots[:8]], [slot['segment'] for slot in slots[8:]])
        self.assertEqual([slot['pair_id'] for slot in slots[:8]], [slot['pair_id'] for slot in slots[8:]])
        self.assertTrue(all(a['segment'] != b['segment'] for a, b in zip(slots[:7], slots[1:8])))
        self.assertEqual(runtime._curve_preference('PS', current, {}, inputs, now,
                         plan=dict(plan, mode='revenue_sprint'), state=state)['label'], 'B')

    def test_bounded_trial_falls_back_to_independently_proven_intermediate_price(self):
        from fc_pricing_v3.curve_strategy_v6 import build_candidates, intermediate_candidates
        from fc_pricing_v3.price_curve import curve_key, read_curve
        from test_curve_strategy_v6 import candidate, fixture
        from test_pricing_proof_v6 import fixture as proof_fixture

        self.prepare()
        now = datetime.now(timezone.utc)
        current, _, _ = fixture()
        all_id = writer.PRODUCTS[PLATFORM][0]
        before = read_curve(dict(current['native_payload'], id=all_id, site_id=0),
                            dict(current['identity'], id=all_id, site_id=0), EDITOR_CONTRACT)
        state = self.db.start_curve_episode(PLATFORM, 'test', 'A', initial_curve=current, readback_ref='fixture')
        comparison = build_candidates(current, state['reference'], state['episode'], 'large')
        outer = candidate(comparison, 'B')['curve']
        points = intermediate_candidates(comparison, 'B', EDITOR_CONTRACT)
        skipped, eligible = (next(points)['curve'] for _ in range(2))
        all_target = runtime._all_curve_target(before, eligible)
        refs = self.capability['source_revisions']
        self.capability['tier_price_factors'] = True

        def proof_input(curve, *, safe):
            _, baskets, evidence, domain = proof_fixture()
            key = curve_key(curve)
            total = next(row['native_price_usd'] for row in curve['tiers'] if row['purchase_k'] == '1000')
            domain.update(curve_key=key, source_revisions=refs, version=self.capability['domain_version'])
            evidence['curve_key'] = key
            evidence['paths'][0].update(curve_key=key, regular_usd=total, net_receipt_usd=total,
                                         expected_cost_usd='74', safe_cost_usd=safe)
            return dict(baskets=baskets, evidence=evidence, domain=domain)

        data = dict(primary_curve=current, editor_contract=EDITOR_CONTRACT, preferred_label='B', segment='large',
                    captured_at=now.isoformat(), valid_until=(now + timedelta(minutes=10)).isoformat(),
                    all_before=before, all_targets={curve_key(eligible): all_target},
                    primary_inputs={curve_key(current): proof_input(current, safe='76'),
                                    curve_key(outer): proof_input(outer, safe='76'),
                                    curve_key(skipped): proof_input(skipped, safe='74'),
                                    curve_key(eligible): proof_input(eligible, safe='74')},
                    all_inputs={curve_key(all_target): proof_input(all_target, safe='74')})
        with patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
            result = runtime._prove_curve_inputs(PLATFORM, data, self.db, now)
        self.assertEqual(result['status'], 'READY', result)
        self.assertEqual(result['selection']['price_step'], 'bounded_intermediate')
        self.assertEqual(curve_key(result['target']), curve_key(all_target))
        self.assertEqual(self.transport.posts, [])

    def test_native_catalogue_collection_produces_real_tiers_without_fabricating_checkout(self):
        from fc_pricing_v3.price_curve import curve_key, read_curve
        from test_curve_strategy_v6 import fixture

        self.prepare()
        now = datetime.now(timezone.utc)
        all_id, primary_id, _ = writer.PRODUCTS[PLATFORM]
        catalogue, _, _ = fixture()
        primary_row = catalogue['native_payload']
        rows = {0: dict(primary_row, id=all_id, site_id=0),
                266: dict(primary_row, id=primary_id, site_id=266)}
        adopted = read_curve(primary_row, catalogue['identity'], dict(source='fixture saved readback'))
        self.db.start_curve_episode(PLATFORM, 'test-rules', 'Adopted readback', initial_curve=adopted,
                                    readback_ref='fixture-same-platform')
        evidence = dict(run_id='run', checked_at=(now - timedelta(seconds=5)).isoformat(),
                        storefront={'rows': {PLATFORM: {'sku_id': primary_id}}})
        plan = dict(self.db.get('pricing_plans', 'plan'), mode='smart')
        self.db.put('pricing_plans', 'plan', plan)
        self.db.put('metadata', 'curve-online-context:plan', {'smart_plan_id': 'plan'})
        self.db.put('actual_price_windows', 'window', {'operation_id': 'window'})
        job = runtime.ROOT / 'jobs' / 'run.json'
        job.parent.mkdir(parents=True, exist_ok=True)
        job.write_text(json.dumps({'request': {'v3_plan_id': 'plan', 'v3_operation_id': 'op'}}))
        def read(_, platform, site, observer):
            self.assertEqual(platform, PLATFORM)
            observer({'response_sha256': 'fixture-' + str(site)})
            return rows[site]

        with patch.object(writer, 'read_row', side_effect=read) as get, \
                patch.object(writer, 'read_curve_routes', return_value={}), \
                patch('fc_pricing_v3.smart.curve_learning', return_value={'large': {'blocks': []}}) as learning, \
                patch('fc_shared_admin.SessionManager'):
            found = runtime.collect_curve_catalogues(evidence, [PLATFORM])[PLATFORM]
        learning.assert_called_once()
        self.assertEqual(learning.call_args.args[0], plan)
        self.assertEqual(found['learning'], {'large': {'blocks': []}})
        self.assertEqual(get.call_count, 2)
        curve = found['primary_curve']
        proof_input = found['primary_inputs'][curve_key(curve)]
        self.assertEqual([p['regular_usd'] for p in proof_input['evidence']['paths']],
                         [tier['native_price_usd'] for tier in curve['tiers']])
        self.assertEqual(runtime._validated_curve(curve, proof_input)['status'], 'PROOF_INCOMPLETE')
        self.assertIn('average_discount_window_unavailable', proof_input['domain']['coverage_gaps'])
        self.assertIn('curve_native_route_unavailable', proof_input['domain']['coverage_gaps'])
        self.assertTrue(found['all_targets'])
        for key, target in found['all_targets'].items():
            self.assertEqual(target['identity']['site_id'], '0')
            self.assertIn(key, found['primary_inputs'])
            self.assertEqual(runtime._validated_curve(target, found['all_inputs'][curve_key(target)])['status'],
                             'PROOF_INCOMPLETE')

    def test_d8_d2_weighted_amount_and_custom_quantity_drive_current_proof(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import MODEL, average_discount
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        current, _, _ = fixture()
        small = list(rows_for([48] * 10, quantity='123K Coins + 0K Free x1 = $100'))
        large = [(key + '-large', paid, quantity) for key, paid, quantity in
                 rows_for([72] * 10, quantity='1500K Coins + 30K Free x1 = $100')]
        included = small + large
        source = attachment(included)
        coverage = source['historical_orders_coverage']
        coverage.update(shared_publication_id='fixed-pin',shared_source_revision='fixed-source',
                        paid_window_start=(CUT - timedelta(days=8)).isoformat())
        for row in source['historical_orders']:
            gross, off = ('20','4') if row['base_k']=='123' else ('100','4')
            row.update(merchandise_before_discount_usd=gross, actual_es_discount_usd=off,
                       single_line_unit_purchase=True, promotion_path=None)
        source['historical_orders'].append(dict(source['historical_orders'][0], order_key='d1-excluded',
            paid_at=(CUT - timedelta(hours=12)).isoformat(), merchandise_before_discount_usd='999',
            actual_es_discount_usd='999'))
        average = average_discount(source,'PS',CUT)
        self.assertEqual((average['matched_orders'],average['actual_discount_usd'],
                          average['merchandise_before_discount_usd']), (20,'80','1200'))
        self.assertEqual(average['retained_ratio'], str(Decimal(1120) / Decimal(1200)))
        self.assertEqual(average['start'], (CUT - timedelta(days=8)).isoformat())
        self.assertEqual(average['end_exclusive'], (CUT - timedelta(days=1)).isoformat())

        small_facts = facts(small, cost='4.92', delivery_fields={'qty':'123','gift':'0','cost_unit':'.04'})
        large_facts = facts(large, cost='61.20', delivery_fields={'qty':'1530','gift':'0','cost_unit':'.04'})
        combined = dict(small_facts, orders=small_facts['orders'] + large_facts['orders'])
        # The paid population excludes unresolved quantity only from modelling.
        source['historical_orders'].pop()
        quote = runtime._average_discount_proof_input(current,'PS',source,source,CUT.isoformat(),AS_OF,
            average=average,route={'propagation_revision':'native-directory'},facts=combined,fx=fx(),current_cost=None)
        path = next(row for row in quote['evidence']['paths'] if row['purchase_k']=='123')
        self.assertEqual((path['regular_usd'],path['net_receipt_usd'],path['quote_basis']),('12.30','11.47',MODEL))
        self.assertEqual(path['receipt_status'],'forecast_under_average_discount')
        proof = runtime._validated_curve(current,quote)
        self.assertEqual(proof['status'],'PROVEN',proof['gaps'])
        self.assertEqual(proof['average_discount']['revision'],average['revision'])
        self.assertEqual(proof['baskets']['main']['selection'],'closed_bjt_7d')

        # Reuse actual verifier and old writer-compatible native factor, even
        # when an unchanged small catalogue needs a higher global unit.
        from fc_pricing_v3.price_curve import FORWARD_TIER_EDIT, curve_key, read_curve
        from test_price_curve_v6 import EDITOR_CONTRACT
        editor = dict(EDITOR_CONTRACT, price_edit_policy=FORWARD_TIER_EDIT)
        all_row = dict(current['native_payload'],id=writer.PRODUCTS['PS'][0],site_id=0)
        all_before = read_curve(all_row,dict(current['identity'],id=all_row['id'],site_id=0),editor)
        higher = facts(large, cost='1025.10', delivery_fields={'qty':'1530','gift':'0','cost_unit':'.67'})
        combined = dict(small_facts,orders=small_facts['orders'] + higher['orders'])
        def proof_for(curve):
            return runtime._average_discount_proof_input(curve,'PS',source,source,CUT.isoformat(),AS_OF,
                average=average,route={'propagation_revision':'native-directory'},facts=combined,fx=fx(),current_cost=None)
        current_proof = runtime._validated_curve(current,proof_for(current))
        self.assertEqual(current_proof['status'],'HARD_CONSTRAINT_FAILED')
        repair = runtime._average_discount_repair(current,all_before,editor,current_proof,proof_for)
        self.assertIsNotNone(repair)
        answer = runtime._curve_repair(current,current_proof,repair)
        self.assertEqual(answer['status'],'COST_REPAIR',answer)
        candidate = answer['candidate']['curve']
        self.assertEqual([p['native_price_usd'] for p in candidate['tiers'] if int(p['purchase_k'])<1000],
                         [p['native_price_usd'] for p in current['tiers'] if int(p['purchase_k'])<1000])
        preview = runtime._preview_curve_candidates(current, curve_key(current), 'PS', None, 'large', source,
            CUT.isoformat(), AS_OF.isoformat(), AS_OF, {curve_key(current):proof_for(current)},
            editor=editor, repair=repair)
        self.assertEqual([(item['labels'], item['financial_proof']['status']) for item in preview['candidates']],
                         [(['CURRENT'], 'HARD_CONSTRAINT_FAILED'), (['COST_REPAIR'], 'PROVEN')])
        self.assertEqual(preview['candidates'][1]['curve_key'], curve_key(candidate))

        source['historical_orders'][0]['actual_es_discount_usd'] = None
        incomplete = average_discount(source,'PS',CUT)
        self.assertIsNone(incomplete['retained_ratio'])
        self.assertEqual(incomplete['gap_counts'],{'average_discount_amount_unknown':1})

    def test_combined_basket_margin_repair_when_every_quantity_breaks_even(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import average_discount
        from fc_pricing_v3.price_curve import FORWARD_TIER_EDIT, read_curve
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture
        from test_price_curve_v6 import EDITOR_CONTRACT

        original, _, _ = fixture()
        editor = dict(EDITOR_CONTRACT, price_edit_policy=FORWARD_TIER_EDIT)
        native = original['native_payload']
        quantities = native['more']['gold']
        rates = dict(native['more'], discount=[100] * len(quantities),
                     price=[str((Decimal(q)*Decimal('.0816')).quantize(Decimal('.01'))) for q in quantities])
        current = read_curve(dict(native,unit_price='.0816',more=rates),original['identity'],editor)
        all_id = writer.PRODUCTS['PS'][0]
        all_before = read_curve(dict(current['native_payload'],id=all_id,site_id=0),
                                dict(current['identity'],id=all_id,site_id=0),editor)
        large = list(rows_for([48] * 20, quantity='1000K Coins + 30K Free x1 = $81.60'))
        small = [(key+'-small', paid, quantity) for key, paid, quantity in
                 rows_for([48] * 10, quantity='100K Coins + 0K Free x1 = $8.16')]
        source = attachment(large + small)
        source['historical_orders_coverage'].update(shared_publication_id='fixed-pin',
            shared_source_revision='fixed-source', paid_window_start=(CUT-timedelta(days=8)).isoformat())
        for row in source['historical_orders']:
            row.update(single_line_unit_purchase=True, merchandise_before_discount_usd='100', actual_es_discount_usd='9')
        large_facts = facts(large, cost='427.45', delivery_fields=dict(qty='1030', gift='0', cost_unit='.415'))
        small_facts = facts(small, cost='41.50', delivery_fields=dict(qty='100', gift='0', cost_unit='.415'))
        combined = dict(large_facts, orders=large_facts['orders'] + small_facts['orders'])
        average = average_discount(source,'PS',CUT)

        def inputs_for(curve):
            return runtime._average_discount_proof_input(curve,'PS',source,source,CUT.isoformat(),AS_OF,
                average=average,route={'propagation_revision':'native-directory'},facts=combined,fx=fx(),current_cost=None)

        before = runtime._validated_curve(current,inputs_for(current))
        self.assertEqual(before['status'], 'HARD_CONSTRAINT_FAILED')
        self.assertTrue(all(path['zero_line_status']=='PROVEN' for path in before['paths']))
        self.assertEqual(before['hard_failures'], ['platform_margin:main', 'platform_margin:recent'])
        repair = runtime._average_discount_repair(current,all_before,editor,before,inputs_for)
        selected = runtime._curve_repair(current,before,repair)
        self.assertEqual(selected['status'], 'COST_REPAIR')
        candidate = selected['candidate']
        self.assertEqual(runtime._validated_curve(candidate['curve'],candidate['inputs'])['status'],'PROVEN')
        self.assertEqual(runtime._validated_curve(candidate['all_target'],candidate['all_inputs'])['status'],'PROVEN')
        self.assertTrue(all(Decimal(old['native_price_usd'])<=Decimal(new['native_price_usd'])
                            for old,new in zip(current['tiers'],candidate['curve']['tiers'])))

    def test_unallocated_multi_unit_cost_increases_missing_quantity_share(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import average_discount
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        current, _, _ = fixture()
        large = list(rows_for([48] * 11, quantity='1000K Coins + 30K Free x1 = $100'))
        small = [(key+'-small', paid, quantity) for key, paid, quantity in
                 rows_for([48] * 10, quantity='100K Coins + 0K Free x1 = $10')]
        source = attachment(large + small)
        source['historical_orders_coverage'].update(shared_publication_id='fixed-pin',
            shared_source_revision='fixed-source', paid_window_start=(CUT-timedelta(days=8)).isoformat())
        for index, row in enumerate(source['historical_orders']):
            allocated = index < 2 or index >= len(large)
            row.update(single_line_unit_purchase=allocated, merchandise_before_discount_usd='100',
                       actual_es_discount_usd='0', cost_cny=None if allocated else '100000')
        lower = facts(large[:1], cost='350', delivery_fields=dict(qty='1030', gift='0', cost_unit=str(Decimal(350)/1030)))
        higher = facts(large[1:2], cost='630', delivery_fields=dict(qty='1030', gift='0', cost_unit=str(Decimal(630)/1030)))
        small_facts = facts(small, cost='3.50', delivery_fields=dict(qty='100', gift='0', cost_unit='.035'))
        facts_value = dict(lower, orders=lower['orders'] + higher['orders'] + small_facts['orders'])
        result = runtime._average_discount_proof_input(current,'PS',source,source,CUT.isoformat(),AS_OF,
            average=average_discount(source,'PS',CUT),route={'propagation_revision':'native-directory'},
            facts=facts_value,fx=fx(),current_cost=None)
        path = next(row for row in result['evidence']['paths'] if row['purchase_k']=='1000')
        self.assertEqual(path['cost_status'], 'verified')
        self.assertAlmostEqual(Decimal(path['expected_cost_usd']), Decimal(70))
        self.assertAlmostEqual(Decimal(path['safe_cost_usd']), Decimal(950)/11)
        self.assertAlmostEqual(Decimal(path['stress_cost_usd']), Decimal(90))
        self.assertEqual(next(row['weight'] for row in result['baskets']['main']['members'] if row['path_id']=='average:1000'),'11')
        self.assertEqual(runtime._validated_curve(current,result)['baskets']['main']['status'],'HARD_CONSTRAINT_FAILED')

    def test_same_round_native_path_preserves_checkout_scope_and_ordinary_cost(self):
        from decimal import Decimal
        from fc_pricing_v3.price_curve import curve_key
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        curve, _, _ = fixture()
        self.assertEqual(curve['identity']['aid'], '21587')
        tier = next(row for row in curve['tiers'] if row['purchase_k'] == '1000')
        purchase = tier['purchase_k']
        bonus = tier['promised_bonus_k']
        total = str(Decimal(purchase) + Decimal(bonus))
        ordinary_orders = list(rows_for([48] * 10, quantity=f'{purchase}K Coins + {bonus}K Free x1 = $100'))
        source = attachment(ordinary_orders)
        for row in source['historical_orders']:
            row['region_id'] = 0
        source['historical_orders'][0]['promotion_path'] = dict(kind='coupon', template_id='1327',
            evidence_ref='same-order-redemption', historical_regular_usd='10.22', historical_discount_usd='5.00')
        source['historical_orders'][1]['promotion_path'] = dict(kind='code', code_ref='code-one-ref')
        source['historical_orders'][2]['promotion_path'] = dict(kind='code', code_ref='code-two-ref')
        recent = dict(source, historical_orders_coverage=dict(source['historical_orders_coverage'],
                                                              paid_window_end_exclusive=CUT.isoformat()))
        cost_facts = facts(ordinary_orders, cost=str(Decimal(total) * Decimal('.39')),
                           delivery_fields={'qty':total, 'gift':'0', 'cost_unit':'.39'})
        checkout = dict(curve_key=curve_key(curve), platform='PS', site_id='266',
                        coverage_gaps=['member_and_discount_allocation_unverified'], lines=[
            dict(purchase_k=purchase, gift_k=bonus, promised_delivered_k=total, regular_usd=tier['native_price_usd'],
                 proof_status='verified', offer_path='anonymous_no_coupon', quote_basis='observed_native_cart',
                 net_goods_usd=tier['native_price_usd'], quote_ref='checkout-ref', eligibility_ref='eligibility-ref',
                 offer_version='current-guest-offer', fulfilment_contract='native-guest-cart',
                 native_tier_or_rule='native-1000', rounding_contract='native-cent', path_id='catalogue:1000')])
        def terms(identity, rule):
            return dict(path=rule, eligibility='eligible-member', source_revision='template-' + identity)

        coupons = dict(terms={
            '1327': terms('1327', dict(kind='fixed', threshold_usd='10', discount_usd='5', cap_usd=None)),
            '1323': terms('1323', dict(kind='ratio', threshold_usd='0', retained_ratio='.8', cap_usd='50')),
            '1331': terms('1331', dict(kind='fixed', threshold_usd='999', discount_usd='20', cap_usd=None)),
        })
        code_rule = dict(kind='ratio', threshold_usd='0', retained_ratio='.92', cap_usd=None)
        codes = {ref: dict(terms(ref, code_rule), aid='0') for ref in ('code-one-ref', 'code-two-ref')}
        proof_input = runtime._catalogue_proof_input(curve, 'PS', source, CUT.isoformat(), AS_OF,
            recent=recent, checkout=checkout, facts=cost_facts, fx=fx(), coupons=coupons, codes=codes)
        path = next(row for row in proof_input['evidence']['paths'] if row['purchase_k'] == purchase)
        self.assertEqual(path.get('cost_status'), 'verified', path)
        self.assertEqual(path['quote_basis'], 'observed_native_cart')
        self.assertAlmostEqual(Decimal(path['stress_cost_usd']), Decimal(total) * Decimal('.39') / 7)
        self.assertEqual(proof_input['baskets']['main']['matched_orders'], 10, proof_input['baskets']['main'])
        self.assertEqual(proof_input['baskets']['recent']['selection'], 'main_fallback')
        result = runtime._validated_curve(curve, proof_input)
        receipt_paths = {row.get('coupon_template_id'): row for row in result['paths'] if row.get('coupon_template_id')}
        self.assertEqual(set(receipt_paths), {'1327', '1323', '1331'})
        fixed = receipt_paths['1327']
        self.assertEqual(Decimal(fixed['net_receipt_usd']), Decimal(path['regular_usd']) - 5)
        self.assertEqual(fixed['cost_ref'], path['cost_ref'])
        self.assertEqual(fixed['quote_basis'], 'derived_eligible_single_line_coupon_net_lower_bound')
        self.assertEqual(receipt_paths['1331']['net_receipt_usd'], str(Decimal(path['regular_usd']).normalize()))
        self.assertFalse(receipt_paths['1331']['coupon_subtotal_eligible'])
        code_paths = [row for row in result['paths'] if row.get('discount_code_terms_revision')]
        self.assertEqual(len(code_paths), 1)
        self.assertEqual(code_paths[0]['discount_code_rule'], code_rule)
        weights = {row['path_id']: row['weight'] for row in proof_input['baskets']['main']['members']}
        self.assertEqual(weights, {'catalogue:1000': '7', 'catalogue:1000:coupon:1327': '1', code_paths[0]['path_id']: '2'})
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIn('member_and_discount_allocation_unverified', result['scope']['coverage_gaps'])
        self.assertNotIn('procurement_time_unverified', result['gaps'])

    def test_candidate_coupon_money_bounds_use_each_rule_and_candidate_subtotal(self):
        path = dict(path_id='catalogue:100', curve_key='candidate', regular_usd='9.99')
        native = dict(quote_ref='guest-quote', offer_version='guest-version')
        terms = dict(source_revision='current-template', eligibility='eligible-voucher',
                     path=dict(kind='fixed', threshold_usd='10', discount_usd='5', cap_usd=None))
        below = runtime._coupon_quote_path(path, native, '1327', terms)
        reached = runtime._coupon_quote_path(dict(path, regular_usd='10.00'), native, '1327', terms)
        self.assertEqual((below['net_receipt_usd'], below['coupon_subtotal_eligible']), ('9.99', False))
        self.assertEqual((reached['net_receipt_usd'], reached['coupon_subtotal_eligible']), ('5.00', True))
        self.assertNotEqual(below['quote_ref'], reached['quote_ref'])
        share = dict(terms, path=dict(kind='ratio', threshold_usd='0', retained_ratio='.8', cap_usd='50'))
        cap = runtime._coupon_quote_path(dict(path, regular_usd='300.01'), native, '1323', share)
        rounded = runtime._coupon_quote_path(dict(path, regular_usd='10.01'), native, '1323', share)
        self.assertEqual((cap['net_receipt_usd'], rounded['net_receipt_usd']), ('250.01', '8.00'))


if __name__ == '__main__':
    unittest.main()
