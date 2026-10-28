"""order_close 判定测试。

对应 docs/planning/fc-pricing-ops-20261028/DECOUPLE-DESIGN.md §4「测试要求」：
    迟到响应 / 证据不足 / 部分地区生效 / ALL 已发出后失败
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3.order_close import (  # noqa: E402
    RECEIPT_STATUS,
    admin_targets,
    build_receipt,
    evaluate_close,
    order_write_confirmed,
    proven_never_dispatched,
    target_platforms,
)

TARGETS = {'pc': '7.46', 'console': '7.38'}
BEFORE = {'pc': '7.99', 'console': '7.99'}
ADMIN_OK = {'PC': Decimal('0.0746'), 'PS': Decimal('0.0738'), 'XBOX': Decimal('0.0738')}


def _step(step_id, kind, state, *, dispatched=None, claimed=None, receipt=None, intermediate=None):
    step = {'step_id': step_id, 'kind': kind, 'state': state}
    if dispatched:
        step['dispatched_at'] = dispatched
    if claimed:
        step['transport_claimed_at'] = claimed
    if receipt is not None:
        step['receipt'] = receipt
    if intermediate is not None:
        step['intermediate'] = intermediate
    return step


def _operation(steps, *, selected=('PS', 'XBOX', 'PC')):
    return {
        'operation_id': 'op-1',
        'status': 'UNKNOWN',
        'steps': steps,
        'dispatch_context': {'selected': list(selected)},
        'bundle': {
            'action': {'base_prices': dict(TARGETS), 'region_coefficients': {'21:PS': '0.9994'}},
            'before_action': {'base_prices': dict(BEFORE), 'region_coefficients': {'21:PS': '0.9804'}},
        },
    }


def _audit(**extra):
    audit = {'status': 'PARTIAL', 'sync_confirmed': True, 'sync_message': '同步成功',
             'all_baseline': {'status': 'deferred_before_dispatch', 'reason': 'coin_auth_unavailable'}}
    audit.update(extra)
    return audit


class OrderFeedbackTest(unittest.TestCase):
    """§6.3 条件 1：只认 Order 自己的成功反馈字段。"""

    def test_accepts_sync_message(self):
        self.assertTrue(order_write_confirmed(_audit()))

    def test_accepts_fallback_recipient_readback(self):
        audit = _audit(sync_message='', sync_recipient_readback={'status': 'CONFIRMED'})
        self.assertTrue(order_write_confirmed(audit))

    def test_rejects_blank_sync_message(self):
        self.assertFalse(order_write_confirmed(_audit(sync_message='   ')))

    def test_rejects_global_status_only(self):
        # 全局 status=CONFIRMED 不是 Order 侧证据
        audit = {'status': 'CONFIRMED', 'sync_confirmed': True,
                 'all_baseline': {'status': 'confirmed'}}
        self.assertFalse(order_write_confirmed(audit))

    def test_rejects_stage_name_only(self):
        # stage 会被后续 stage() 覆盖，不能当判据
        audit = _audit(stage='sync_feedback')
        audit.pop('sync_message')
        self.assertFalse(order_write_confirmed(audit))

    def test_rejects_none(self):
        self.assertFalse(order_write_confirmed(None))


class SendProofTest(unittest.TestCase):
    """§6.1 严格发送证明：三条同时满足。"""

    def test_never_dispatched_when_no_transport_at_all(self):
        self.assertTrue(proven_never_dispatched(_step('r1', 'region', 'PREPARED')))

    def test_never_dispatched_when_receipt_not_sent(self):
        self.assertTrue(proven_never_dispatched(
            _step('r1', 'region', 'PREPARED', receipt={'status': 'NOT_SENT'})))

    def test_claimed_without_dispatch_is_not_proven(self):
        # 已 claim 但没写 dispatched_at：可能已在路上，禁止当未发出
        self.assertFalse(proven_never_dispatched(
            _step('r1', 'region', 'PREPARED', claimed='2026-10-28T04:04:54+00:00')))

    def test_dispatched_is_not_proven(self):
        self.assertFalse(proven_never_dispatched(
            _step('r1', 'region', 'UNKNOWN', dispatched='2026-10-28T04:04:54+00:00',
                  receipt={'status': 'NOT_SENT'})))

    def test_ambiguous_receipt_is_not_proven(self):
        self.assertFalse(proven_never_dispatched(
            _step('r1', 'region', 'UNKNOWN', receipt={'status': 'UNKNOWN'})))

    def test_price_change_is_not_used_as_send_proof(self):
        # 回执未知时，即便 intermediate 显示价格已变，也不能判未发出
        step = _step('r1', 'region', 'UNKNOWN', receipt={'status': 'UNKNOWN'},
                     intermediate={'base_prices': dict(TARGETS)})
        self.assertFalse(proven_never_dispatched(step))


class LateResponseTest(unittest.TestCase):
    """迟到响应：请求超时后才返回成功 → 不重复下发，用原 ID 核对后收尾。"""

    def test_close_after_late_success_without_new_dispatch(self):
        op = _operation([
            _step('base_prices:all', 'base', 'UNKNOWN', dispatched='2026-10-28T04:04:54+00:00',
                  receipt={'status': 'UNKNOWN'}, intermediate={'base_prices': dict(TARGETS)}),
            _step('region_coefficients:21:PS', 'region', 'PREPARED'),
            _step('region_coefficients:21:XBOX', 'region', 'PREPARED'),
        ])
        decision = evaluate_close(op, _audit(), ADMIN_OK)
        self.assertEqual(decision['action'], 'finish_partial')
        self.assertEqual(decision['confirmed'], 'base_prices:all')
        self.assertEqual(sorted(decision['cancelled']),
                         ['region_coefficients:21:PS', 'region_coefficients:21:XBOX'])
        # 判定不允许产生新请求：不应携带任何 dispatch 指令
        self.assertNotIn('dispatch', decision)
        self.assertNotIn('retry', decision)


class InsufficientEvidenceTest(unittest.TestCase):
    """证据不足 → 保持 UNKNOWN，不放锁。"""

    def test_keep_when_order_feedback_missing(self):
        op = _operation([_step('base_prices:all', 'base', 'UNKNOWN',
                               dispatched='2026-10-28T04:04:54+00:00')])
        self.assertEqual(evaluate_close(op, {'status': 'PARTIAL'}, ADMIN_OK)['action'], 'keep')

    def test_keep_when_admin_price_mismatch(self):
        op = _operation([_step('base_prices:all', 'base', 'UNKNOWN',
                               dispatched='2026-10-28T04:04:54+00:00')])
        stale = {'PC': Decimal('0.0799'), 'PS': Decimal('0.0799'), 'XBOX': Decimal('0.0799')}
        decision = evaluate_close(op, _audit(), stale)
        self.assertEqual(decision['action'], 'keep')
        self.assertEqual(decision['reason'], 'admin_unit_price_mismatch')

    def test_keep_when_admin_platform_missing(self):
        op = _operation([_step('base_prices:all', 'base', 'UNKNOWN',
                               dispatched='2026-10-28T04:04:54+00:00')])
        decision = evaluate_close(op, _audit(), {'PC': Decimal('0.0746')})
        self.assertEqual(decision['action'], 'keep')

    def test_keep_when_admin_readback_unavailable(self):
        op = _operation([_step('base_prices:all', 'base', 'UNKNOWN',
                               dispatched='2026-10-28T04:04:54+00:00')])
        decision = evaluate_close(op, _audit(), {})
        self.assertEqual(decision['action'], 'keep')

    def test_keep_when_region_step_was_dispatched(self):
        op = _operation([
            _step('base_prices:all', 'base', 'UNKNOWN', dispatched='2026-10-28T04:04:54+00:00'),
            _step('region_coefficients:21:PS', 'region', 'UNKNOWN', dispatched='2026-10-28T04:05:10+00:00',
                  receipt={'status': 'UNKNOWN'}),
        ])
        decision = evaluate_close(op, _audit(), ADMIN_OK)
        self.assertEqual(decision['action'], 'keep')
        self.assertEqual(decision['reason'], 'step_transport_unresolved:region_coefficients:21:PS')

    def test_keep_when_base_step_ambiguous(self):
        op = _operation([
            _step('base_prices:pc', 'base', 'UNKNOWN', dispatched='2026-10-28T04:04:54+00:00'),
            _step('base_prices:console', 'base', 'UNKNOWN', dispatched='2026-10-28T04:04:56+00:00'),
        ])
        self.assertEqual(evaluate_close(op, _audit(), ADMIN_OK)['reason'], 'base_step_ambiguous')


class PartialRegionTest(unittest.TestCase):
    """部分地区生效：base 已确认 + 一个区域已确认 + 另一个确定未发出。"""

    def test_partial_close_keeps_confirmed_region(self):
        op = _operation([
            _step('base_prices:all', 'base', 'CONFIRMED',
                  intermediate={'base_prices': dict(TARGETS)}),
            _step('region_coefficients:21:PS', 'region', 'CONFIRMED',
                  intermediate={'base_prices': dict(TARGETS),
                                'region_coefficients': {'21:PS': '0.9994', '21:XBOX': '1.0000'}}),
            _step('region_coefficients:21:XBOX', 'region', 'PREPARED'),
        ])
        decision = evaluate_close(op, _audit(), ADMIN_OK)
        self.assertEqual(decision['action'], 'finish_partial')
        self.assertIsNone(decision['confirmed'])
        self.assertEqual(decision['cancelled'], ['region_coefficients:21:XBOX'])

    def test_full_close_when_every_step_confirmed(self):
        op = _operation([
            _step('base_prices:all', 'base', 'CONFIRMED'),
            _step('region_coefficients:21:PS', 'region', 'CONFIRMED'),
        ])
        self.assertEqual(evaluate_close(op, _audit(), ADMIN_OK)['action'], 'finish')

    def test_keep_when_nothing_confirmed(self):
        op = _operation([_step('region_coefficients:21:PS', 'region', 'PREPARED')])
        self.assertEqual(evaluate_close(op, _audit(), ADMIN_OK)['reason'], 'no_confirmed_step')


class AllPostDispatchFailureTest(unittest.TestCase):
    """ALL 已发出后失败：不能因 Order 成功就丢掉 ALL，但仍按 Order+Admin 记录改价成功。"""

    def test_closes_with_order_admin_scope_when_all_deferred(self):
        op = _operation([_step('base_prices:all', 'base', 'UNKNOWN',
                               dispatched='2026-10-28T04:04:54+00:00')])
        audit = _audit(all_baseline={'status': 'deferred_before_dispatch',
                                     'reason': 'coin_auth_unavailable',
                                     'price_post_attempted': False})
        decision = evaluate_close(op, audit, ADMIN_OK)
        receipt = build_receipt(op, audit, ADMIN_OK, decision)
        self.assertEqual(receipt['status'], RECEIPT_STATUS)
        self.assertEqual(receipt['confirmation_scope'], 'Order_Admin')
        # 不冒充公开页确认
        self.assertNotEqual(receipt['status'], 'PUBLIC_CONFIRMED')
        # ALL 的失败必须留在回执里可追溯
        self.assertEqual(receipt['public_verification']['status'], 'not_required')

    def test_receipt_records_admin_prices_and_targets(self):
        op = _operation([_step('base_prices:all', 'base', 'UNKNOWN',
                               dispatched='2026-10-28T04:04:54+00:00')])
        decision = evaluate_close(op, _audit(), ADMIN_OK)
        receipt = build_receipt(op, _audit(), ADMIN_OK, decision, {'status': 'BACKEND_CONFIRMED'})
        self.assertEqual(receipt['admin_unit_prices']['PC'], '0.0746')
        self.assertEqual(receipt['public_verification']['status'], 'BACKEND_CONFIRMED')
        quotes = {t['platform']: t['quote'] for t in receipt['targets']}
        self.assertEqual(quotes, {'PS': '7.38', 'XBOX': '7.38', 'PC': '7.46'})


class TargetMappingTest(unittest.TestCase):
    """目标价映射：console 覆盖 PS 与 XBOX。"""

    def test_all_step_covers_every_platform(self):
        op = _operation([_step('base_prices:all', 'base', 'PREPARED')])
        self.assertEqual(target_platforms(op), ['PS', 'XBOX', 'PC'])

    def test_selected_subset_respected(self):
        op = _operation([_step('base_prices:pc', 'base', 'PREPARED')], selected=('PC',))
        self.assertEqual(target_platforms(op), ['PC'])

    def test_console_maps_to_both_consoles(self):
        op = _operation([_step('base_prices:all', 'base', 'PREPARED')])
        quotes = {t['platform']: t['quote'] for t in admin_targets(op)}
        self.assertEqual(quotes['PS'], '7.38')
        self.assertEqual(quotes['XBOX'], '7.38')
        self.assertEqual(quotes['PC'], '7.46')


if __name__ == '__main__':
    unittest.main()
