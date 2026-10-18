"""Private customer-care reports through the existing owner-scoped conversation API."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import re
import threading

from customer_tracking import money

IDENT = re.compile(r'[a-f0-9]{32}')
STATUS = {'已支付', '已完成', '待发货', '发货中', '已发货', '问题订单', '已退款',
          '退款中', '已取消', 'paid', 'completed', 'pending', 'processing', 'refunded', 'cancelled'}


def moment(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:
        return None


def anonymous_evidence(detail, days, now=None):
    """Allowlist numerical aggregates; never forward raw rows, IDs or free text."""
    now = now or datetime.now(timezone.utc)
    tracked = moment(detail.get('tracked_at'))
    tracking_id = detail.get('tracking_id')
    if not isinstance(tracking_id, str) or not IDENT.fullmatch(tracking_id) or tracked is None:
        raise ValueError('report_tracking_identity')
    if days not in (0, 7, 14, 30):
        raise ValueError('report_window')
    cutoff = min(now, tracked + timedelta(days=days)) if days else now
    if days and now < tracked + timedelta(days=days):
        raise ValueError('report_window_immature')
    groups = {}
    marked_orders = []
    unknown_time = unpaid = 0
    seen = set()
    for row in detail.get('orders', []):
        number = row.get('order_no')
        if not isinstance(number, str) or number in seen:
            continue
        seen.add(number)
        if row.get('customer_flag') in {'new', 'old', 'unknown'}:
            marked_orders.append({'customer_flag': row['customer_flag'],
                                  'order_usd': str(money(row.get('order_usd'))) if money(row.get('order_usd')) is not None else None,
                                  'discount_usd': str(money(row.get('discount_usd'))) if money(row.get('discount_usd')) is not None else None})
        when = moment(row.get('paid_at'))
        if when is None:
            unknown_time += 1
            continue
        if when > cutoff:
            continue
        if str(row.get('pay_status')) != '1':
            unpaid += 1
            continue
        scope = ('FC27' if row.get('selected_game') is True or str(row.get('gid')) == '1327'
                 else 'other_games' if str(row.get('gid')).isdigit() else 'unknown_game')
        period = 'before_enrollment' if when < tracked else 'after_enrollment'
        local_day = when.astimezone(timezone(timedelta(hours=8))).date()
        if period == 'before_enrollment':
            bucket = local_day.strftime('%Y-%m') if when >= tracked - timedelta(days=90) else 'earlier_history'
        else:
            bucket = 'enrollment_week_' + str((when - tracked).days // 7 + 1)
        key = (scope, period, bucket)
        group = groups.setdefault(key, {'orders': 0, 'known_order_usd': 0, 'order_usd': Decimal(0),
                                       'known_discount_usd': 0, 'discount_usd': Decimal(0), 'statuses': Counter()})
        group['orders'] += 1
        for field in ('order_usd', 'discount_usd'):
            amount = money(row.get(field))
            if amount is not None and amount >= 0:
                group['known_' + field] += 1
                group[field] += amount
        status = row.get('current_status', row.get('status'))
        group['statuses'][status if isinstance(status, str) and status in STATUS else 'unknown'] += 1
    rows = []
    for (scope, period, bucket), group in sorted(groups.items()):
        rows.append({'game_scope': scope, 'period': period, 'bucket': bucket, 'orders': group['orders'],
                     'order_usd': str(group['order_usd']) if group['known_order_usd'] else None,
                     'known_order_usd': group['known_order_usd'],
                     'discount_usd': str(group['discount_usd']) if group['known_discount_usd'] else None,
                     'known_discount_usd': group['known_discount_usd'], 'status_counts': dict(group['statuses'])})
    coverage = detail.get('history_coverage') or {}
    evidence = {'tracking_id': tracking_id, 'profile': 'FC27', 'site_id': 266,
                'tracked_at': tracked.isoformat(), 'node_days': days, 'cutoff': cutoff.isoformat(),
                'generated_at': now.isoformat(), 'currency': 'USD', 'paid_order_groups': rows,
                'es_marked_order_context': marked_orders[:8],
                'history_complete': coverage.get('complete') is True,
                'source_observed_at': moment(detail.get('history_observed_at')).isoformat() if moment(detail.get('history_observed_at')) else None,
                'unknown_payment_time_orders': unknown_time, 'non_paid_orders_excluded': unpaid,
                'rule': '首次建议截至实际生成时刻，可能晚于加入日；7/14/30节点截至加入后相应天数。加入前近90天按自然月汇总，更早历史合并；加入后按连续7日分段，末段可不足7天。付款金额不是扣除退款的净收入；状态为本次观察状态，未知折扣不补零。'}
    return evidence


def report_prompt(detail, days):
    evidence = anonymous_evidence(detail, days)
    return ('请为这名匿名FC27客户生成' + ('首次维护建议' if days == 0 else f'加入观察后第{days}天维护复盘') +
            '。先读取现行报告方法和客户维护业务知识，再独立分析以下冻结证据。'
            '保持经营者视角：判断优先级、主要依据、有理由的假设、可落实的人工维护步骤和复查条件。'
            '高消费低优惠不自动证明忠诚；分清加入前后、同游戏与其他游戏、未付款与退款状态，不把维护后复购直接当因果。'
            '历史覆盖不足时限制相应结论，仍可给出有依据的建议。数据尽量用合适大小图表，文字提炼结论与动作，'
            '布局、配色和交互自主，涨红跌绿。输出完整可离线打开的HTML原稿，必要明细折叠；不要返回JSON报告封套。'
            '客户身份保留在管理员工具页，不索取或输出邮箱、UID、原单号；只引用追踪ID。'
            '这是分析任务，不执行联系、发券、改价、改订单或长期记忆写入。\n'
            '<frozen_customer_evidence>\n' + json.dumps(evidence, ensure_ascii=False, separators=(',', ':')) +
            '\n</frozen_customer_evidence>')


class CustomerReports:
    def __init__(self, conversation_service, store, admin_user=None):
        self.conversation = conversation_service
        self.store = store
        self.admin_user = admin_user
        self.lock = threading.Lock()

    def _bind(self, row, **fields):
        self.store.bind_report(row['tracking_id'], row['days'], expected_state=row['state'], **fields)
        row.update(fields)

    def _original_turn(self, owner, conversation_id, request_id):
        with self.conversation.store.db() as db:
            row = db.execute('SELECT t.id FROM turns t JOIN conversations c ON c.id=t.conversation_id '
                             'WHERE c.id=? AND c.owner=? AND t.request_id=?',
                             (conversation_id, owner, request_id)).fetchone()
        return row['id'] if row else None

    def _poll(self, row, owner):
        cid = row.get('conversation_id')
        if not cid:
            if row.get('state') in {'creating', 'claimed'}:
                self._bind(row, state='needs_review')
            return
        turn_id = row.get('turn_id') or self._original_turn(owner, cid, row['request_id'])
        if not turn_id:
            return  # Unknown dispatch is reconciled, never re-submitted.
        value = self.conversation.detail(owner, cid)
        turn = next((item for item in value.get('turns', []) if item.get('turn_id') == turn_id), None)
        if turn is None:
            return
        state = turn.get('state')
        result = {'conversation_id': cid, 'turn_id': turn_id,
                  'state': 'dispatch_unknown' if state == 'dispatch_unknown' else 'running'}
        if state == 'completed':
            artifact = next((item for item in turn.get('artifacts', []) if item.get('mime') == 'text/html'
                             and IDENT.fullmatch(str(item.get('artifact_id', '')))), None)
            result.update(state='completed' if artifact else 'needs_review', artifact_id=artifact['artifact_id'] if artifact else None)
        elif state in {'failed', 'cancelled', 'interrupted'}:
            result['state'] = state
        self._bind(row, **result)

    def tick(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            processed = set()
            for due in self.store.due_reports():
                tracking_id = due.get('tracking_id', due.get('track_id'))
                if tracking_id in processed:
                    continue
                processed.add(tracking_id)
                detail = self.store.detail(tracking_id)
                observed = moment(detail.get('history_observed_at'))
                due_at = moment(due.get('due_at'))
                if due['state'] == 'scheduled' and (observed is None or due_at is None or observed < due_at):
                    continue
                row = self.store.claim_report(tracking_id, due['days'])
                owner = row.get('owner') or self.admin_user
                if not owner:
                    continue
                try:
                    if not row.get('claimed'):
                        self._poll(row, owner)
                        continue
                    prompt = row.get('prompt') or report_prompt(detail, row['days'])
                    if len(prompt) > 12000:
                        raise ValueError('report_input_size')
                    cid = row.get('conversation_id')
                    if not cid:
                        self._bind(row, state='creating')
                        cid = self.conversation.create(owner)['conversation_id']
                        self._bind(row, conversation_id=cid, state='claimed')
                    self._bind(row, conversation_id=cid, prompt=prompt, state='dispatch_unknown')
                    submitted = self.conversation.submit(owner, cid, prompt, row['request_id'])
                    self._bind(row, conversation_id=cid, turn_id=submitted['turn_id'], state=submitted['state'])
                except Exception:
                    # Durable claim and original request survive network errors and restart.
                    # Do not log exceptions: upstream text may contain private information.
                    if row.get('state') in {'creating', 'claimed'}:
                        self._bind(row, state='needs_review')
                    continue
        finally:
            self.lock.release()
