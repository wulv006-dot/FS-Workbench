"""账本收尾集成测试：ORDER_ADMIN_CONFIRMED 回执可收尾并释放租约。

验证点（DECOUPLE-DESIGN §6.2）：
    - finish_known_partial 接受 ORDER_ADMIN_CONFIRMED，释放 resource_leases
    - 仍拒绝无法识别的回执状态（不放开任何未知态）
    - 不改变终态白名单：结果仍是 KNOWN_PARTIAL_EXIT_PENDING
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3.ledger import Ledger  # noqa: E402

BUNDLE = {
    'assignment_id': 'assign-1',
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
        'steps': [
            {'step_id': 'base_prices:all', 'kind': 'base', 'state': 'CONFIRMED',
             'intermediate': {'base_prices': dict(BUNDLE['action']['base_prices']),
                              'region_coefficients': dict(BUNDLE['before_action']['region_coefficients'])}},
            {'step_id': 'region_coefficients:21:PS', 'kind': 'region', 'state': 'CANCELLED_NOT_SENT'},
        ],
    }


class FinishKnownPartialTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Ledger(Path(self.tmp.name) / 'control.sqlite3')

    def _seed(self):
        self.db.put('operations', 'op-1', _operation())
        with self.db.transaction() as conn:
            for resource in BUNDLE['mutable_resources']:
                conn.execute('INSERT OR REPLACE INTO resource_leases (resource,operation_id) VALUES (?,?)',
                             (resource, 'op-1'))

    def _leases(self):
        with self.db.connect() as conn:
            return [r[0] for r in conn.execute('SELECT resource FROM resource_leases')]

    def test_accepts_order_admin_confirmed_and_releases_leases(self):
        self._seed()
        receipt = {'status': 'ORDER_ADMIN_CONFIRMED', 'confirmation_scope': 'Order_Admin'}
        actual = dict(BUNDLE['action'])
        op = self.db.finish_known_partial('op-1', receipt, actual, 'order_write_confirmed_admin_price_matched')
        self.assertEqual(op['status'], 'KNOWN_PARTIAL_EXIT_PENDING')
        self.assertEqual(self._leases(), [])
        stored = self.db.get('readback_receipts', 'op-1')
        self.assertEqual(stored['status'], 'ORDER_ADMIN_CONFIRMED')

    def test_still_accepts_public_confirmed(self):
        self._seed()
        op = self.db.finish_known_partial('op-1', {'status': 'PUBLIC_CONFIRMED'},
                                          dict(BUNDLE['action']), 'partial')
        self.assertEqual(op['status'], 'KNOWN_PARTIAL_EXIT_PENDING')

    def test_continue_partial_records_actual_prices_once_without_exit_state(self):
        self._seed()
        actual = _operation()['steps'][0]['intermediate']
        receipt = dict(status='ORDER_ADMIN_CONFIRMED')
        op = self.db.finish_known_partial('op-1',receipt,actual,'confirmed_partial',exit_pending=False)
        self.assertEqual(op['status'], 'COMPLETED')
        self.assertTrue(op['target_not_completed'])
        self.assertEqual(op['actual_action'], actual)
        self.assertEqual(op['completed_at'],op['actual_state_confirmed_at'])
        window = self.db.get('actual_price_windows','op-1')
        self.assertEqual(window['action'], actual)
        self.assertEqual(set(window['resources']), {'base:pc','base:console'})
        self.assertEqual(self._leases(), [])
        self.assertEqual(self.db.finish_known_partial('op-1',receipt,actual,'retry',exit_pending=False),op)
        self.assertEqual(self.db.get('actual_price_windows','op-1'),window)

    def test_rejects_unknown_receipt_status(self):
        self._seed()
        with self.assertRaises(ValueError) as ctx:
            self.db.finish_known_partial('op-1', {'status': 'BACKEND_CONFIRMED'},
                                         dict(BUNDLE['action']), 'partial')
        self.assertIn('pricing_partial_public_unconfirmed', str(ctx.exception))
        # 拒绝时不得释放租约
        self.assertEqual(len(self._leases()), 4)

    def test_rejects_when_steps_unresolved(self):
        self._seed()
        op = _operation()
        op['steps'][1]['state'] = 'UNKNOWN'
        self.db.put('operations', 'op-1', op)
        with self.assertRaises(ValueError) as ctx:
            self.db.finish_known_partial('op-1', {'status': 'ORDER_ADMIN_CONFIRMED'},
                                         dict(BUNDLE['action']), 'partial')
        self.assertIn('pricing_partial_actual_state_unresolved', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
