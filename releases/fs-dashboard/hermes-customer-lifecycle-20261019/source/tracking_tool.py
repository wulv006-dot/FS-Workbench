"""Authorized customer detail and optional anonymous aggregates for a tracking ID."""
from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from customer_tracking import ID, money, buyer_evidence


def _moment(value):
    if not isinstance(value,str):return None
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:return None


def anonymous_snapshot(detail):
    """Optional identity-free aggregate; callers may also request business detail."""
    tracking_id=detail.get('tracking_id')
    if not isinstance(tracking_id,str) or not ID.fullmatch(tracking_id):raise ValueError('tracking_identity')
    tracked=_moment(detail.get('tracked_at'))
    if tracked is None:raise ValueError('tracking_enrollment_time')
    coverage=detail.get('history_coverage') or {}
    grouped=defaultdict(lambda:{'paid_orders':0,'known_order_usd':0,'order_usd':Decimal(0),
                               'known_discount_usd':0,'discount_usd':Decimal(0)})
    unknown_time=unpaid=0
    for row in detail.get('orders',[]):
        when=_moment(row.get('paid_at'))
        if when is None:
            unknown_time+=1;continue
        if str(row.get('pay_status'))!='1':
            unpaid+=1;continue
        game=('FC27' if row.get('selected_game') is True or str(row.get('gid'))=='1327' else
              'unknown_game' if row.get('gid') is None else 'other_games')
        period='before_enrollment' if when<tracked else 'after_enrollment'
        item=grouped[(game,period)];item['paid_orders']+=1
        for field in ('order_usd','discount_usd'):
            value=money(row.get(field))
            if value is not None and value>=0:
                item['known_'+field]+=1;item[field]+=value
    groups=[]
    for (game,period),item in sorted(grouped.items()):
        groups.append({'game_scope':game,'period':period,'paid_orders':item['paid_orders'],
            'order_usd':str(item['order_usd']) if item['known_order_usd'] else None,
            'known_order_usd':item['known_order_usd'],
            'discount_usd':str(item['discount_usd']) if item['known_discount_usd'] else None,
            'known_discount_usd':item['known_discount_usd']})
    return {'status':'available' if coverage.get('complete') is True else 'partial',
        'tracking_id':tracking_id,'profile':'FC27','site_id':266,'tracked_at':tracked.isoformat(),'first_paid_at':detail.get('first_paid_at'),'lifecycle_day':detail.get('lifecycle_day'),'phase':detail.get('phase'),'report_policy':'manual_pool_only',
        'observed_at':detail.get('history_observed_at'),'source_complete':coverage.get('complete') is True,
        'source_total':coverage.get('source_total'),'source_received':coverage.get('received'),
        'buyer_identity_evidence':buyer_evidence(detail.get('orders',[])),
        'groups':groups,'unknown_payment_time_orders':unknown_time,'non_paid_orders_excluded':unpaid,
        'rule':'客户主键仍按已核邮箱，buyer仅作覆盖与冲突证据，尚未按buyer重算客户或跨邮箱历史；仅站点266匹配订单参与，分FC27与其他游戏、加入前后；首次付款日独立记录为生命周期第1天，加入前后仅为人工观察行为分界，不能当作首付时间；仅pay_status=1计付费单。未知金额不补零，退款状态需人工复核；无联系、发券、改单权限。'}


def customer_snapshot(detail):
    """Original admin/owner authorization permits identifiers and stored order detail."""
    value=anonymous_snapshot(detail)
    for key in ('email','uid','owner','first_paid_status','first_paid_scope','stage_markers',
                'clock_rule','history_coverage','history_observed_at','milestones'):
        if key in detail:value[key]=deepcopy(detail[key])
    value['tracking_status']=detail.get('status')
    fields=('order_no','email','uid','gid','site_id','paid_at','observed_at','pay_status',
        'current_status','order_usd','order_usd_source','admin_order_usd','es_order_usd',
        'selected_game','discount_usd','product_type','product_types','customer_flag',
        'profile','identity_status','identity_reason','identity_source','amount_conflict')
    value['orders']=[]
    for order in detail.get('orders',[]):
        row={key:deepcopy(order[key]) for key in fields if key in order}
        for key,names in (('payment',('amount','currency')),('es_identity',('buyer_id','uid','status','source'))):
            if isinstance(order.get(key),dict):row[key]={name:deepcopy(order[key][name]) for name in names if name in order[key]}
        value['orders'].append(row)
    return value
