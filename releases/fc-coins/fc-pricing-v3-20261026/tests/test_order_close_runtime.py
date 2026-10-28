"""runtime.close_on_order_admin 的编排测试（打桩，不连生产）。

验证点：
    - 证据齐 → 走现有收尾函数，租约释放，回执 scope=Order_Admin
    - 证据不足 → 保持 UNKNOWN，租约保留，不产生新请求
    - Admin 读回抛错 → 视为未知，不误判成功
    - 公开页不确认不再阻塞（postwrite 失败也照样收尾）
"""
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3 import adapters, runtime  # noqa: E402
from fc_pricing_v3.ledger import Ledger  # noqa: E402

ADMIN_OK = {'PC': Decimal('0.0746'), 'PS': Decimal('0.0738'), 'XBOX': Decimal('0.0738')}

BUNDLE = {
    'assignment_id': 'assign-1',
    'snapshot_id': 'run-1',
    'action': {'base_prices': {'pc': '7.46', 'console': '7.38'},
               'region_coefficients': {'21:PS': '0.9994', '21:XBOX': '0.9994'}},
    'before_action': {'base_prices': {'pc': '7.99', 'console': '7.99'},
                      'region_coefficients': {'21:PS': '0.9804', '21:XBOX': '1.0000'}},
    'mutable_resources': ['base:pc', 'base:console', 'region:21:PS', 'region:21:XBOX'],
    'affected_platforms': ['PS', 'XBOX', 'PC'],
    'catalog': {},
    'budget_reference': {},
}


def _operation():
    return {
        'operation_id': 'op-1',
        'plan_id': 'plan-1',
        'generation': 1,
        'status': 'UNKNOWN',
        'resources': list(BUNDLE['mutable_resources']),
        'bundle': dict(BUNDLE),
        'dispatch_context': {'selected': ['PS', 'XBOX', 'PC']},
        'steps': [
            {'step_id': 'base_prices:all', 'kind': 'base', 'state': 'UNKNOWN',
             'dispatched_at': '2026-10-28T04:04:54+00:00',
             'receipt': {'status': 'UNKNOWN'},
             'intermediate': {'base_prices': dict(BUNDLE['action']['base_prices']),
                              'region_coefficients': dict(BUNDLE['action']['region_coefficients'])}},
            {'step_id': 'region_coefficients:21:PS', 'kind': 'region', 'state': 'PREPARED'},
            {'step_id': 'region_coefficients:21:XBOX', 'kind': 'region', 'state': 'PREPARED'},
        ],
    }


def _audit():
    return {'status': 'PARTIAL', 'sync_confirmed': True, 'sync_message': '同步成功',
            'all_baseline': {'status': 'deferred_before_dispatch', 'reason': 'coin_auth_unavailable'}}


class CloseOnOrderAdminTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / 'control.sqlite3')
        self.ledger.put('operations', 'op-1', _operation())
        with self.ledger.transaction() as conn:
            for resource in BUNDLE['mutable_resources']:
                conn.execute('INSERT OR REPLACE INTO resource_leases (resource,operation_id) VALUES (?,?)',
                             (resource, 'op-1'))
        self._orig_ledger = runtime.ledger
        self._orig_prices = runtime._admin_observed_prices
        self._orig_postwrite = adapters.reconcile_postwrite
        runtime.ledger = lambda: self.ledger
        adapters.reconcile_postwrite = lambda op, audit: {'status': 'PUBLIC_CONFIRMED'}
        self.addCleanup(self._restore)

    def _restore(self):
        runtime.ledger = self._orig_ledger
        runtime._admin_observed_prices = self._orig_prices
        adapters.reconcile_postwrite = self._orig_postwrite

    def _leases(self):
        with self.ledger.connect() as conn:
            return [r[0] for r in conn.execute('SELECT resource FROM resource_leases')]

    def test_closes_and_releases_when_evidence_complete(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        closed = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(closed['status'], 'KNOWN_PARTIAL_EXIT_PENDING')
        self.assertEqual(self._leases(), [])
        states = {s['step_id']: s['state'] for s in closed['steps']}
        self.assertEqual(states['base_prices:all'], 'CONFIRMED')
        self.assertEqual(states['region_coefficients:21:PS'], 'CANCELLED_NOT_SENT')

    def test_keeps_unknown_and_leases_when_price_mismatch(self):
        runtime._admin_observed_prices = lambda: {'PC': Decimal('0.0799'),
                                                  'PS': Decimal('0.0799'),
                                                  'XBOX': Decimal('0.0799')}
        op = self.ledger.get('operations', 'op-1')
        kept = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(kept['status'], 'UNKNOWN')
        self.assertEqual(kept['order_close']['reason'], 'admin_unit_price_mismatch')
        self.assertEqual(len(self._leases()), 4)
        stored = self.ledger.get('operations', 'op-1')
        self.assertEqual(stored['steps'][0]['state'], 'UNKNOWN')

    def test_admin_readback_error_is_treated_as_unknown(self):
        def boom():
            raise ValueError('admin_page_failed')
        runtime._admin_observed_prices = boom
        op = self.ledger.get('operations', 'op-1')
        kept = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(kept['status'], 'UNKNOWN')
        self.assertIn('admin_readback_unavailable', kept['order_close']['detail'])
        self.assertEqual(len(self._leases()), 4)

    def test_no_order_feedback_means_no_touch_and_no_admin_call(self):
        calls = []
        runtime._admin_observed_prices = lambda: calls.append(1) or ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        kept = runtime.close_on_order_admin(op, {'status': 'PARTIAL'})
        self.assertEqual(kept['status'], 'UNKNOWN')
        self.assertEqual(calls, [])   # 没成功反馈就不去打 Admin
        self.assertEqual(len(self._leases()), 4)

    def test_postwrite_failure_does_not_block_close(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK

        def failing_postwrite(op, audit):
            raise RuntimeError('storefront_down')
        adapters.reconcile_postwrite = failing_postwrite
        op = self.ledger.get('operations', 'op-1')
        closed = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(closed['status'], 'KNOWN_PARTIAL_EXIT_PENDING')
        receipt = self.ledger.get('readback_receipts', 'op-1')
        self.assertEqual(receipt['status'], 'ORDER_ADMIN_CONFIRMED')
        self.assertEqual(receipt['public_verification']['status'], 'postwrite_failed')

    def test_receipt_never_claims_public_confirmation(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        adapters.reconcile_postwrite = lambda op, audit: {'status': 'BACKEND_CONFIRMED'}
        op = self.ledger.get('operations', 'op-1')
        runtime.close_on_order_admin(op, _audit())
        receipt = self.ledger.get('readback_receipts', 'op-1')
        self.assertEqual(receipt['status'], 'ORDER_ADMIN_CONFIRMED')
        self.assertNotEqual(receipt['status'], 'PUBLIC_CONFIRMED')
        self.assertEqual(receipt['confirmation_scope'], 'Order_Admin')


if __name__ == '__main__':
    unittest.main()
