"""Exercise original-operation coordination against the synthetic F4 transport."""
from contextlib import ExitStack, closing
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


class CurveRuntime(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        enter = stack.enter_context
        folder = enter(tempfile.TemporaryDirectory())
        self.root = Path(folder)
        for name in ('quotes', 'jobs', 'executions'):
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
        quote = dict(result=dict(decision_receipt=bundle))
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
        with self.assertRaisesRegex(ValueError, 'pricing_curve_execution_verifier_unavailable'):
            runtime.verify_quote(quote, {}, ['PS'], for_execution=True)

    def test_inconsistent_dirty_curve_cannot_use_empty_steps(self):
        self.prepare()
        self.bundle['steps'] = []
        with self.assertRaisesRegex(ValueError, 'pricing_curve_original_dispatch_scope_changed'):
            self.execute()
        self.dispatch.assert_not_called()
        self.worker.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
