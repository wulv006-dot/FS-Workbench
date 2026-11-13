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
from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL, prewrite_refusal
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.ledger import Ledger
from test_curve_writer_v6 import OPERATION, PLATFORM, Transport, setup_bundle, writer
from test_price_curve_v6 import EDITOR_CONTRACT


class CurveRuntime(unittest.TestCase):
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

    def test_proven_keep_opens_and_extends_only_readback_window(self):
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import IDENTITY_FIELDS, curve_key, read_curve
        from test_pricing_proof_v6 import fixture

        self.prepare(large='100')
        now = datetime.now(timezone.utc)
        plan = self.db.get('pricing_plans', 'plan')
        plan.update(mode='daily', write_protocol=CURVE_WRITE_PROTOCOL,
                    starts_at=(now - timedelta(hours=1)).isoformat(), resources=['base:PS'])
        self.db.put('pricing_plans', 'plan', plan)
        row = self.transport.rows[writer.PRODUCTS[PLATFORM][1]]
        curve = read_curve(row, {key: row[key] for key in IDENTITY_FIELDS}, EDITOR_CONTRACT)
        self.db.start_curve_episode(PLATFORM, 'fixture-rules', 'Adopted readback', initial_curve=curve,
                                    readback_ref='fixture-initial')
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
        self.assertEqual(self.db.all('operations'), [])
        self.assertEqual(self.db.all('readback_receipts'), [])
        self.assertEqual(self.transport.posts, [])

    def run_verified_curve_cycle(self, *, cost_repair=False):
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
        self.assertEqual(current_slot, same_slot)
        self.assertEqual((current_slot['source'], current_slot['segment'], current_slot['block']),
                         ('smart_three_hour_block', 'large', 0))
        self.assertIn(current_slot['label'], 'ABC')
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
        def read(_, platform, site, observer):
            self.assertEqual(platform, PLATFORM)
            observer({'response_sha256': 'fixture-' + str(site)})
            return rows[site]

        with patch.object(writer, 'read_row', side_effect=read) as get, \
                patch.object(writer, 'read_curve_routes', return_value={}), \
                patch('fc_shared_admin.SessionManager'):
            found = runtime.collect_curve_catalogues(evidence, [PLATFORM])[PLATFORM]
        self.assertEqual(get.call_count, 2)
        curve = found['primary_curve']
        proof_input = found['primary_inputs'][curve_key(curve)]
        self.assertEqual([p['regular_usd'] for p in proof_input['evidence']['paths']],
                         [tier['native_price_usd'] for tier in curve['tiers']])
        self.assertEqual(runtime._validated_curve(curve, proof_input)['status'], 'PROOF_INCOMPLETE')
        self.assertIn('native_checkout_path_domain_unverified', proof_input['domain']['coverage_gaps'])
        self.assertTrue(found['all_targets'])
        for key, target in found['all_targets'].items():
            self.assertEqual(target['identity']['site_id'], '0')
            self.assertIn(key, found['primary_inputs'])
            self.assertEqual(runtime._validated_curve(target, found['all_inputs'][curve_key(target)])['status'],
                             'PROOF_INCOMPLETE')

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
        proof_input = runtime._catalogue_proof_input(curve, 'PS', source, CUT.isoformat(), AS_OF,
            recent=recent, checkout=checkout, facts=cost_facts, fx=fx())
        path = next(row for row in proof_input['evidence']['paths'] if row['purchase_k'] == purchase)
        self.assertEqual(path.get('cost_status'), 'verified', path)
        self.assertEqual(path['quote_basis'], 'observed_native_cart')
        self.assertAlmostEqual(Decimal(path['stress_cost_usd']), Decimal(total) * Decimal('.39') / 7)
        self.assertEqual(proof_input['baskets']['main']['matched_orders'], 10)
        self.assertEqual(proof_input['baskets']['recent']['selection'], 'main_fallback')
        result = runtime._validated_curve(curve, proof_input)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIn('member_and_discount_allocation_unverified', result['scope']['coverage_gaps'])
        self.assertNotIn('procurement_time_unverified', result['gaps'])


if __name__ == '__main__':
    unittest.main()
