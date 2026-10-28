"""runtime.close_on_order_admin / unified_close_entry 的编排测试（打桩，不连生产）。

覆盖 PR #588 review 的三个实质问题：
    1. Order 超时（只有读价推断）不能算成功
    2. Order 成功但公开页失败 → 仍按 Admin 核对收尾
    3. 收尾后执行审计文件同步推进，下一轮 writer 不被拦
"""
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3 import adapters, runtime  # noqa: E402
from fc_pricing_v3.ledger import Ledger  # noqa: E402
from fc_pricing_v3.order_close import RECEIPT_STATUS, execution_is_unresolved  # noqa: E402

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
                              'region_coefficients': dict(BUNDLE['before_action']['region_coefficients'])}},
            {'step_id': 'region_coefficients:21:PS', 'kind': 'region', 'state': 'PREPARED'},
            {'step_id': 'region_coefficients:21:XBOX', 'kind': 'region', 'state': 'PREPARED'},
        ],
    }


def _audit(**extra):
    audit = {'status': 'PARTIAL', 'sync_confirmed': True, 'sync_message': '同步成功',
             'all_baseline': {'status': 'deferred_before_dispatch', 'reason': 'coin_auth_unavailable'}}
    audit.update(extra)
    return audit


class CloseOnOrderAdminTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'executions').mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.root / 'v3' / 'control.sqlite3')
        self.ledger.put('operations', 'op-1', _operation())
        with self.ledger.transaction() as conn:
            for resource in BUNDLE['mutable_resources']:
                conn.execute('INSERT OR REPLACE INTO resource_leases (resource,operation_id) VALUES (?,?)',
                             (resource, 'op-1'))
        self._orig = (runtime.ledger, runtime._admin_observed_prices, runtime.ROOT, runtime.write_json)
        runtime.ledger = lambda: self.ledger
        runtime.ROOT = self.root
        runtime.write_json = lambda path, value: Path(path).write_text(
            json.dumps(value, ensure_ascii=False), encoding='utf-8')
        adapters.reconcile_postwrite = lambda op, audit: {'status': 'PUBLIC_CONFIRMED'}
        self.postwrite_calls = []
        self.addCleanup(self._restore)

    def _restore(self):
        runtime.ledger, runtime._admin_observed_prices, runtime.ROOT, runtime.write_json = self._orig
        runtime._admin_observed_prices = self._orig[1]

    def _write_audit(self, state):
        path = self.root / 'executions' / 'op-1.json'
        path.write_text(json.dumps(state), encoding='utf-8')
        return path

    def _read_audit(self):
        return json.loads((self.root / 'executions' / 'op-1.json').read_text(encoding='utf-8'))

    def _leases(self):
        with self.ledger.connect() as conn:
            return [r[0] for r in conn.execute('SELECT resource FROM resource_leases')]

    # ---- 基本路径 ----

    def test_closes_and_releases_when_evidence_complete(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        closed = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(closed['status'], 'COMPLETED')
        self.assertEqual(self._leases(), [])
        states = {s['step_id']: s['state'] for s in closed['steps']}
        self.assertEqual(states['base_prices:all'], 'CONFIRMED')
        self.assertEqual(states['region_coefficients:21:PS'], 'CANCELLED_NOT_SENT')

    def test_partial_close_keeps_active_plan_and_actual_region_prices(self):
        from fc_pricing_v3.scheduler import next_cycle_at
        from fc_pricing_v3.financial import instant
        from datetime import timedelta
        runtime._admin_observed_prices = lambda: ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        op['revision'] = 1
        self.ledger.put('operations', 'op-1', op)
        plan = dict(plan_id='plan-1', revision=1, state='ACTIVE', ends_at=None,
                    starts_at='2026-10-28T00:00:00+00:00', resources=list(BUNDLE['mutable_resources']))
        self.ledger.put('pricing_plans', 'plan-1', plan)
        with self.ledger.transaction() as conn:
            for resource in plan['resources']:
                conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)', (resource,'plan-1',1,'1'))
        closed = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(closed['status'], 'COMPLETED')
        self.assertTrue(closed['target_not_completed'])
        self.assertEqual(self.ledger.get('pricing_plans', 'plan-1'), plan)
        self.assertEqual(closed['actual_action']['region_coefficients'], BUNDLE['before_action']['region_coefficients'])
        window = self.ledger.get('actual_price_windows', 'op-1')
        self.assertEqual(window['action'], closed['actual_action'])
        self.assertEqual(set(window['resources']), {'base:pc','base:console'})
        with self.ledger.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='exit'").fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM plan_ownership').fetchone()[0], 4)
            self.assertEqual(next_cycle_at(conn,plan,dict(interval_minutes=60)), instant(closed['completed_at'])+timedelta(minutes=60))
        self.assertEqual(self._leases(), [])

    def test_explicit_partial_exit_still_ends_plan_and_enqueues_exit(self):
        op = self.ledger.get('operations', 'op-1')
        op.update(revision=1)
        op['steps'][0]['state'] = 'CONFIRMED'
        self.ledger.put('operations', 'op-1', op)
        self.ledger.put('pricing_plans', 'plan-1', dict(plan_id='plan-1',revision=1,state='ENDING',ends_at='2026-10-28T00:00:00+00:00'))
        with self.ledger.transaction() as conn:
            conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)', ('base:pc','plan-1',1,'1'))
        with patch.object(adapters,'verify_known_partial',return_value=dict(status='PUBLIC_CONFIRMED')):
            closed = runtime.stop_unissued_and_exit(op, 'plan_deadline')
        self.assertEqual(closed['status'], 'KNOWN_PARTIAL_EXIT_PENDING')
        self.assertEqual(self.ledger.get('pricing_plans','plan-1')['state'], 'ENDING')
        with self.ledger.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='exit'").fetchone()[0], 1)

    def test_keeps_unknown_and_leases_when_price_mismatch(self):
        runtime._admin_observed_prices = lambda: {'PC': Decimal('0.0799'),
                                                  'PS': Decimal('0.0799'),
                                                  'XBOX': Decimal('0.0799')}
        op = self.ledger.get('operations', 'op-1')
        kept = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(kept['status'], 'UNKNOWN')
        self.assertEqual(kept['order_close']['reason'], 'admin_unit_price_mismatch')
        self.assertEqual(len(self._leases()), 4)
        self.assertEqual(self.ledger.get('operations', 'op-1')['steps'][0]['state'], 'UNKNOWN')

    def test_admin_readback_error_is_treated_as_unknown(self):
        def boom():
            raise ValueError('admin_page_failed')
        runtime._admin_observed_prices = boom
        op = self.ledger.get('operations', 'op-1')
        kept = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(kept['status'], 'UNKNOWN')
        self.assertIn('admin_readback_unavailable', kept['order_close']['detail'])
        self.assertEqual(len(self._leases()), 4)

    def test_no_order_feedback_means_no_admin_call(self):
        calls = []
        runtime._admin_observed_prices = lambda: calls.append(1) or ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        kept = runtime.close_on_order_admin(op, {'status': 'PARTIAL'})
        self.assertEqual(kept['status'], 'UNKNOWN')
        self.assertEqual(calls, [])
        self.assertEqual(len(self._leases()), 4)

    def test_postwrite_failure_does_not_block_close(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK

        def failing(op, audit):
            raise RuntimeError('storefront_down')
        adapters.reconcile_postwrite = failing
        op = self.ledger.get('operations', 'op-1')
        closed = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(closed['status'], 'COMPLETED')
        receipt = self.ledger.get('readback_receipts', 'op-1')
        self.assertEqual(receipt['status'], RECEIPT_STATUS)
        self.assertEqual(receipt['public_verification']['status'], 'postwrite_failed')

    def test_receipt_never_claims_public_confirmation(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        adapters.reconcile_postwrite = lambda op, audit: {'status': 'BACKEND_CONFIRMED'}
        op = self.ledger.get('operations', 'op-1')
        runtime.close_on_order_admin(op, _audit())
        receipt = self.ledger.get('readback_receipts', 'op-1')
        self.assertEqual(receipt['status'], RECEIPT_STATUS)
        self.assertNotEqual(receipt['status'], 'PUBLIC_CONFIRMED')
        self.assertEqual(receipt['confirmation_scope'], 'Order_Admin')

    def test_public_receipt_reuses_order_admin_evidence_without_extra_read(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        op['steps'] = op['steps'][:1]
        self.ledger.put('operations', 'op-1', op)
        with patch.object(runtime, '_admin_observed_prices', return_value=ADMIN_OK) as readback, \
                patch.object(adapters, 'reconcile_postwrite', return_value={'status': 'PUBLIC_CONFIRMED', 'public': {'platforms': ['PS','XBOX','PC']}}) as public:
            closed = runtime.close_on_order_admin(op, _audit())
        self.assertEqual(closed['status'], 'COMPLETED')
        receipt = self.ledger.get('readback_receipts', 'op-1')
        self.assertEqual(receipt['status'], 'PUBLIC_CONFIRMED')
        self.assertEqual(receipt['confirmation_scope'], 'Order_Admin')
        self.assertEqual(receipt['operation_id'], 'op-1')
        self.assertEqual(receipt['order_feedback']['sync_message'], '同步成功')
        self.assertEqual(set(receipt['admin_unit_prices']), {'PS','XBOX','PC'})
        self.assertEqual(set(r['platform'] for r in receipt['targets']), {'PS','XBOX','PC'})
        self.assertEqual(self._read_audit()['close_receipt'], {k: receipt[k] for k in ('status','admin_unit_prices','targets','public_verification')})
        readback.assert_called_once_with();public.assert_called_once()

    # ---- review #1：读价推断不能当成功 ----

    def test_price_inference_only_cannot_close(self):
        """Order 超时、只有两次读价一致，且 Admin 本来就是目标价 → 不得算成功。"""
        runtime._admin_observed_prices = lambda: ADMIN_OK
        self._write_audit({'status': 'PARTIAL', 'sync_confirmed': True,
                           'sync_recipient_readback': {
                               'basis': 'two_stable_original_admin_recipient_reads'}})
        op = self.ledger.get('operations', 'op-1')
        # 入口层就应该拦掉，不打 Admin
        self.assertIsNone(runtime.unified_close_entry(op, {'status': 'PARTIAL', 'sync_confirmed': True,
                                                           'sync_recipient_readback': {'basis': 'x'}}))
        kept = runtime.close_on_order_admin(op, {'status': 'PARTIAL', 'sync_recipient_readback': {'basis': 'x'}})
        self.assertEqual(kept['status'], 'UNKNOWN')
        self.assertEqual(len(self._leases()), 4)
        # 审计文件保持未收敛，writer 仍会拦（证明没有假装收尾）
        self.assertTrue(execution_is_unresolved(self._read_audit(), None))

    # ---- review #2：公开页失败不阻挡 ----

    def test_closes_when_public_page_unconfirmed(self):
        """Order 与 ALL 都成功、公开页只到 CACHE_CONFIRMED → 仍按 Admin 核对收尾。"""
        runtime._admin_observed_prices = lambda: ADMIN_OK
        self._write_audit({'status': 'CONFIRMED', 'sync_confirmed': True, 'sync_message': '同步成功',
                           'all_baseline': {'status': 'confirmed'}})
        op = self.ledger.get('operations', 'op-1')
        op['postwrite_receipt'] = {'status': 'CACHE_CONFIRMED'}
        op['status'] = 'CACHE_CONFIRMED'
        self.ledger.put('operations', 'op-1', op)

        def counting(op, audit):
            self.postwrite_calls.append(1)
            return {'status': 'BACKEND_CONFIRMED'}
        adapters.reconcile_postwrite = counting

        closed = runtime.close_on_order_admin(self.ledger.get('operations', 'op-1'),
                                              self._read_audit())
        self.assertEqual(closed['status'], 'COMPLETED')
        receipt = self.ledger.get('readback_receipts', 'op-1')
        self.assertEqual(receipt['status'], RECEIPT_STATUS)
        self.assertEqual(receipt['public_verification']['status'], 'CACHE_CONFIRMED')
        # 已算过的 postwrite 不重复调用
        self.assertEqual(self.postwrite_calls, [])

    def test_unified_entry_accepts_green_audit(self):
        """旧路径的全绿审计也走同一入口，不再被排除。"""
        runtime._admin_observed_prices = lambda: ADMIN_OK
        audit = {'status': 'CONFIRMED', 'sync_confirmed': True, 'sync_message': '同步成功',
                 'all_baseline': {'status': 'confirmed'}}
        closed = runtime.unified_close_entry(self.ledger.get('operations', 'op-1'), audit)
        self.assertIsNotNone(closed)
        self.assertEqual(closed['status'], 'COMPLETED')

    # ---- review #3：下一轮不被拦 ----

    def test_execution_audit_closed_so_next_round_can_run(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        adapters.reconcile_postwrite = lambda op, audit: {'status': 'BACKEND_CONFIRMED'}
        self._write_audit({'status': 'PARTIAL', 'changed': ['PC'], 'stage': 'all_baseline_pending'})
        op = self.ledger.get('operations', 'op-1')
        runtime.close_on_order_admin(op, _audit())

        state = self._read_audit()
        self.assertEqual(state['status'], RECEIPT_STATUS)
        self.assertEqual(state['ledger_status'], 'COMPLETED')
        self.assertEqual(state['changed'], ['PC'])          # 原有审计内容保留
        self.assertFalse(execution_is_unresolved(state, None))
        self.assertFalse(execution_is_unresolved(state, 'COMPLETED'))

    def test_audit_write_failure_is_reported_not_hidden(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK

        def boom(path, value):
            raise OSError('disk_full')
        runtime.write_json = boom
        op = self.ledger.get('operations', 'op-1')
        closed = runtime.close_on_order_admin(op, _audit())
        # 账本仍已收尾（不能回滚），但失败要显式可见
        self.assertEqual(closed['status'], 'COMPLETED')
        self.assertEqual(closed['execution_audit_close']['status'], 'audit_write_failed')


class ExitOrCloseTest(unittest.TestCase):
    """review #4：授权过期 / 公开页异常不得让已成功的操作走取消路径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'executions').mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.root / 'v3' / 'control.sqlite3')
        self.ledger.put('operations', 'op-1', _operation())
        with self.ledger.transaction() as conn:
            for resource in BUNDLE['mutable_resources']:
                conn.execute('INSERT OR REPLACE INTO resource_leases (resource,operation_id) VALUES (?,?)',
                             (resource, 'op-1'))
        self._orig = (runtime.ledger, runtime._admin_observed_prices, runtime.ROOT,
                      runtime.write_json, runtime.stop_unissued_and_exit)
        runtime.ledger = lambda: self.ledger
        runtime.ROOT = self.root
        runtime.write_json = lambda path, value: Path(path).write_text(
            json.dumps(value, ensure_ascii=False), encoding='utf-8')
        runtime.stop_unissued_and_exit = lambda op, reason: {'status': 'CANCELLED_NOT_SENT',
                                                             'cancel_reason': reason, 'sentinel': True}
        adapters.reconcile_postwrite = lambda op, audit: {'status': 'BACKEND_CONFIRMED'}
        self.addCleanup(self._restore)

    def _restore(self):
        runtime.ledger, runtime._admin_observed_prices, runtime.ROOT, \
            runtime.write_json, runtime.stop_unissued_and_exit = self._orig

    def _leases(self):
        with self.ledger.connect() as conn:
            return [r[0] for r in conn.execute('SELECT resource FROM resource_leases')]

    def test_expired_authorization_does_not_block_verified_close(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        op['bundle']['valid_until'] = '2026-10-28T04:16:39+00:00'   # 早已过期
        self.ledger.put('operations', 'op-1', op)

        result = runtime.exit_or_close(op, _audit(), 'pricing_authorization_expired')
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertNotIn('sentinel', result)      # 没走取消路径
        self.assertEqual(self._leases(), [])

    def test_public_page_exception_still_closes(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK

        def boom(op, audit):
            raise RuntimeError('storefront_down')
        adapters.reconcile_postwrite = boom

        op = self.ledger.get('operations', 'op-1')
        result = runtime.exit_or_close(op, _audit(), 'pricing_authorization_expired')
        self.assertEqual(result['status'], 'COMPLETED')
        receipt = self.ledger.get('readback_receipts', 'op-1')
        self.assertEqual(receipt['public_verification']['status'], 'postwrite_failed')

    def test_falls_back_to_cancel_when_no_order_evidence(self):
        runtime._admin_observed_prices = lambda: ADMIN_OK
        op = self.ledger.get('operations', 'op-1')
        result = runtime.exit_or_close(op, {'status': 'PARTIAL'}, 'pricing_authorization_expired')
        self.assertTrue(result.get('sentinel'))
        self.assertEqual(result['status'], 'CANCELLED_NOT_SENT')
        self.assertEqual(len(self._leases()), 4)

    def test_falls_back_to_cancel_when_admin_mismatch(self):
        runtime._admin_observed_prices = lambda: {'PC': Decimal('0.0799'),
                                                  'PS': Decimal('0.0799'),
                                                  'XBOX': Decimal('0.0799')}
        op = self.ledger.get('operations', 'op-1')
        result = runtime.exit_or_close(op, _audit(), 'pricing_authorization_expired')
        self.assertTrue(result.get('sentinel'))
        self.assertEqual(len(self._leases()), 4)

    def test_close_error_does_not_lose_the_exit_path(self):
        def boom():
            raise ValueError('admin_unreachable')
        runtime._admin_observed_prices = boom
        op = self.ledger.get('operations', 'op-1')
        result = runtime.exit_or_close(op, _audit(), 'pricing_authorization_expired')
        self.assertTrue(result.get('sentinel'))
        self.assertEqual(len(self._leases()), 4)


if __name__ == '__main__':
    unittest.main()
