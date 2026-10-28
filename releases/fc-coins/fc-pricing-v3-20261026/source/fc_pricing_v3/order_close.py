"""Order 侧成功反馈 + Admin unit_price 读回的收尾判定。

设计依据：docs/planning/fc-pricing-ops-20261028/DECOUPLE-DESIGN.md
    §6.1 严格发送证明
    §6.3 改价成功判定 = Order 操作保存的成功反馈 + 随后 Admin unit_price 核对
    §6.4 在 reconcile 补的唯一入口

本模块只做**纯判定**与**收尾材料构造**，不写库、不发请求；
落库由 runtime 用现有收尾函数（finish / finish_known_partial）完成。

⚠️ 两个状态消费者必须一致（PR #588 review #3）：
    账本（SQLite operations）收尾后，执行审计文件 ``executions/<id>.json``
    仍是 PARTIAL 时，下一轮 ``price_writer.execute`` 的
    ``unresolved_execution_exists`` 扫描会继续拦截。
    本模块提供 ``closed_audit_state()`` 与 ``execution_is_unresolved()``
    让两侧识别同一终态。
"""

from .admin_readback import matches_targets

# §6.3 条件 1：只有 clickSync 真正返回的反馈才算 Order 成功。
# price_writer.py 只在 `feedback['success'] and feedback['message']` 成立时写这个字段。
ORDER_FEEDBACK_FIELD = 'sync_message'

# 不能当作成功证据：这是 confirm_sync_recipient() 用两次 Admin 读价稳定一致推断出来的，
# 判据与 §6.3 条件 2 完全相同。一旦接受它，「价格碰巧已是目标价」就会被误当成 Order 成功。
PRICE_INFERENCE_FIELD = 'sync_recipient_readback'

# 平台 -> bundle['action']['base_prices'] 的键（console 覆盖 PS 与 XBOX）
BASE_PRICE_KEY = {'PC': 'pc', 'PS': 'console', 'XBOX': 'console'}
ALL_PLATFORMS = ('PS', 'XBOX', 'PC')

RECEIPT_STATUS = 'ORDER_ADMIN_CONFIRMED'

# price_writer.execute() 会因这些审计状态拒绝新一轮写入
UNRESOLVED_AUDIT_STATUS = frozenset({'RUNNING', 'UNCERTAIN', 'PARTIAL'})

# 账本侧已收尾的状态：审计文件即便残留 PARTIAL，也不应再阻挡下一轮
TERMINAL_LEDGER_STATUS = frozenset({
    'COMPLETED', 'NO_CHANGE', 'CANCELLED_NOT_SENT',
    'KNOWN_PARTIAL_EXIT_PENDING', 'KNOWN_PARTIAL_EXITED', 'FAILED_BEFORE_WRITE',
})


def order_feedback_state(audit):
    """返回 Order 成功反馈的**证据等级**。

    ``sync_feedback``            真有 clickSync 成功反馈（唯一可作为条件 1 的证据）
    ``price_inference_only``     只有两次读价一致推断（等同条件 2，不得当成功）
    ``missing``                  两者都没有
    """
    if not isinstance(audit, dict):
        return 'missing'
    message = audit.get(ORDER_FEEDBACK_FIELD)
    if isinstance(message, str) and message.strip():
        return 'sync_feedback'
    if audit.get(PRICE_INFERENCE_FIELD):
        return 'price_inference_only'
    return 'missing'


def order_write_confirmed(audit):
    """§6.3 条件 1：**本次 Order 操作**保存的成功反馈。

    只认 ``sync_message``（clickSync 返回 success + message）。
    不认 ``sync_recipient_readback``：那是读价推断，会与条件 2 混为一谈。
    不读 ``status``（要等 ALL 收尾）、不读 ``stage``（每次 stage() 都会覆盖）。
    """
    return order_feedback_state(audit) == 'sync_feedback'


def proven_never_dispatched(step):
    """§6.1 严格发送证明：三条同时满足才算「确定未发出」。

    1. 无 ``dispatched_at``
    2. ``transport_claimed_at`` 为空
    3. ``receipt`` 不存在或 ``receipt.status == 'NOT_SENT'``

    三条是 AND 关系，任一不满足 → 视为「已发出 / 未知」，**不得**当成未发送。

    第 3 条对 ``receipt`` 缺失的落地解释
    ------------------------------------
    §6.1 原文写 ``receipt.status == 'NOT_SENT'``，但**从未派发的步骤根本没有回执**
    （本次事故里两个区域步骤是 ``PREPARED``、``receipt`` 为空）。若要求回执必须存在，
    对这类步骤永远无法成立，卡死会原样复现。

    因此：``dispatched_at`` 与 ``transport_claimed_at`` 同时缺席 ⇒ 从未尝试发送
    ⇒ 不可能有回执，此时 ``receipt is None`` 视为未发出。

    反之，只要有任何一条传输痕迹（已 dispatch，或已 claim），无论回执写什么，
    都必须继续核对，不能用「价格没变」「intermediate 已更新」来推断未发送。
    """
    if not isinstance(step, dict):
        return False
    if step.get('dispatched_at'):
        return False
    if step.get('transport_claimed_at'):
        return False
    status = (step.get('receipt') or {}).get('status')
    return status in (None, 'NOT_SENT')


def target_platforms(operation):
    """本次写价覆盖的平台。

    base step 为 ``base_prices:all`` 时覆盖全部平台；否则取 dispatch 实际选择的平台。
    """
    steps = operation.get('steps') or []
    base_ids = [str(s.get('step_id')) for s in steps if s.get('kind') == 'base']
    if any(step_id.endswith(':all') for step_id in base_ids):
        return list(ALL_PLATFORMS)
    selected = ((operation.get('dispatch_context') or {}).get('selected') or [])
    ordered = [p for p in ALL_PLATFORMS if p in set(selected)]
    return ordered or list(ALL_PLATFORMS)


def admin_targets(operation):
    """把 bundle 目标价整理成 Admin 核对目标（Order 每 100K 口径）。"""
    action = ((operation.get('bundle') or {}).get('action') or {})
    base_prices = action.get('base_prices') or {}
    targets = []
    for platform in target_platforms(operation):
        key = BASE_PRICE_KEY.get(platform)
        if key is None or key not in base_prices:
            continue
        targets.append({'platform': platform, 'quote': str(base_prices[key])})
    return targets


def _keep(operation, reason):
    return dict(action='keep', reason=reason, confirmed=None, cancelled=[],
                targets=admin_targets(operation))


def evaluate_close(operation, audit, observed_prices):
    """纯判定收尾动作。

    action:
        ``keep``          证据不足 → 保持 UNKNOWN，不释放锁、不新建操作
        ``finish``        所有 step 均确认 → 交给 ``finish()``
        ``finish_partial``部分确认 + 其余确定未发出 → 交给 ``finish_known_partial()``
    """
    feedback = order_feedback_state(audit)
    if feedback != 'sync_feedback':
        return _keep(operation, 'order_success_feedback_missing'
                     if feedback == 'missing' else 'order_feedback_is_price_inference_only')

    targets = admin_targets(operation)
    if not targets:
        return _keep(operation, 'admin_targets_unavailable')
    if not matches_targets(observed_prices or {}, targets):
        return _keep(operation, 'admin_unit_price_mismatch')

    steps = list(operation.get('steps') or [])
    unconfirmed = [s for s in steps if s.get('state') != 'CONFIRMED']
    base_unconfirmed = [s for s in unconfirmed if s.get('kind') == 'base']
    if len(base_unconfirmed) > 1:
        return _keep(operation, 'base_step_ambiguous')

    confirm_step = base_unconfirmed[0]['step_id'] if base_unconfirmed else None
    if confirm_step is None and not any(s.get('state') == 'CONFIRMED' for s in steps):
        return _keep(operation, 'no_confirmed_step')

    cancelled = []
    for step in unconfirmed:
        if confirm_step is not None and step['step_id'] == confirm_step:
            continue
        if not proven_never_dispatched(step):
            return _keep(operation, 'step_transport_unresolved:' + str(step.get('step_id')))
        cancelled.append(step['step_id'])

    action = 'finish' if not cancelled else 'finish_partial'
    return dict(action=action, reason='order_write_confirmed_admin_price_matched',
                confirmed=confirm_step, cancelled=cancelled, targets=targets)


def build_receipt(operation, audit, observed_prices, decision, postwrite=None):
    """构造写进账本的回执。

    status 用 ``ORDER_ADMIN_CONFIRMED``，不冒充 ``PUBLIC_CONFIRMED``；
    公开页核对结果放在 ``public_verification`` 里，只作事后补充。
    读价推断字段单独留在 ``price_inference``，表明它**没有**被当作成功证据。
    """
    feedback = {}
    if isinstance(audit, dict) and audit.get(ORDER_FEEDBACK_FIELD):
        feedback[ORDER_FEEDBACK_FIELD] = audit.get(ORDER_FEEDBACK_FIELD)
    inference = None
    if isinstance(audit, dict) and audit.get(PRICE_INFERENCE_FIELD):
        inference = dict(field=PRICE_INFERENCE_FIELD, usable_as_proof=False,
                         basis=(audit.get(PRICE_INFERENCE_FIELD) or {}).get('basis')
                         if isinstance(audit.get(PRICE_INFERENCE_FIELD), dict) else None)
    observed = {}
    for platform, value in sorted((observed_prices or {}).items()):
        observed[platform] = str(value)
    return dict(status=RECEIPT_STATUS, confirmation_scope='Order_Admin',
                operation_id=operation.get('operation_id'),
                order_feedback=feedback, price_inference=inference,
                admin_unit_prices=observed,
                targets=decision.get('targets') or [],
                confirmed_step=decision.get('confirmed'),
                cancelled_steps=decision.get('cancelled') or [],
                public_verification=postwrite or dict(status='not_required'))


def closed_audit_state(audit, receipt, ledger_status, closed_at):
    """把执行审计文件推进到与账本同一个终态（PR #588 review #3）。

    ``price_writer.execute()`` 开跑前会扫 ``executions/*.json``，见到
    ``RUNNING / UNCERTAIN / PARTIAL`` 就抛 ``unresolved_execution_exists``。
    只收尾账本会让下一轮继续被拦，所以两侧必须写同一个终态。
    """
    updated = dict(audit or {})
    updated.update(
        status=receipt.get('status') or RECEIPT_STATUS,
        ledger_status=ledger_status,
        operation_id=receipt.get('operation_id'),
        confirmation_scope='Order_Admin',
        closed_at=closed_at,
        sync_confirmed=True,
        close_receipt=dict(
            status=receipt.get('status'),
            admin_unit_prices=receipt.get('admin_unit_prices') or {},
            targets=receipt.get('targets') or [],
            public_verification=receipt.get('public_verification'),
        ),
    )
    return updated


def execution_is_unresolved(state, ledger_status=None):
    """writer 扫描判据：审计状态未收敛 **且** 账本没有给出终态。

    ``ledger_status`` 为 None（读不到 / 无此操作）时按未收敛处理（fail-closed），
    避免读账本失败被当成「已收尾」而放过双重写入。
    """
    if not isinstance(state, dict):
        return False
    if state.get('status') not in UNRESOLVED_AUDIT_STATUS:
        return False
    return ledger_status not in TERMINAL_LEDGER_STATUS
