"""Reuse Admin8767 and existing Sales caches; never authenticate independently."""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from channel_effects import Attribution, SITE, TZ, normalize

COLLECTOR = '/opt/sales-dashboard/collector'
SALES = Path('/opt/sales-dashboard/data')
ROOT = Path('/var/lib/fs-channel-effects')


def search(filters):
    result = {}
    for i, (field, operator, value) in enumerate(filters):
        for key, val in (('field', field), ('operator', operator), ('val', value)):
            result['search[%d][%s]' % (i, key)] = val
        if operator == 'RANGE': result['search[%d][render]' % i] = 'datetime'
    return result


def pages(session, path, filters=(), limit=200):
    result, seen, total = [], set(), None
    page = 1
    while True:
        status, payload = session.get_admin(path, page=page, limit=limit, order='id,desc', **search(filters))
        data = payload.get('data') or {}
        rows = data.get('list')
        count = int(data.get('total', -1))
        if status != 200 or payload.get('code') != 1 or not isinstance(rows, list) or not 0 <= count <= 100000:
            raise ValueError('admin_page_failed')
        if total is None: total = count
        if count != total or len(rows) > limit:
            raise ValueError('admin_pagination_changed')
        for row in rows:
            rid = str(row.get('id') or '')
            if not rid or rid in seen: raise ValueError('admin_duplicate_page')
            seen.add(rid); result.append(row)
        if len(result) == total: return result
        if not rows or len(result) > total or page >= 500:
            raise ValueError('admin_incomplete_pages')
        page += 1


def windows(period):
    start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    while start <= end:
        stop = min(start + timedelta(days=27), end)
        yield start.isoformat() + ' 00:00:00', stop.isoformat() + ' 23:59:59'
        start = stop + timedelta(days=1)


def load_costs():
    # The current Sales cache covers Aion2 only. It is never advertised as global.
    path = SALES / 'deliveries.json'
    rows = json.loads(path.read_text('utf-8')) if path.is_file() else []
    info = dict(status='partial' if rows else 'unavailable', source='Sales 现有发货缓存（Aion2）',
                generatedAt=datetime.fromtimestamp(path.stat().st_mtime, TZ).isoformat() if path.is_file() else None,
                limitation='Order 共享源待修复；未关联采购成本保持缺失。匹配行不代表整单已履约或已最终结算。')
    global_path = ROOT / 'order-deliveries.json'
    if global_path.is_file():
        data = json.loads(global_path.read_text('utf-8'))
        if data.get('contract') != 'channel-order-deliveries-v1' or data.get('complete') is not True:
            raise ValueError('invalid_order_cost_cache')
        # Prefer the newer completed capture for identical delivery IDs.
        by_id = {str(r['delivery_id']): r for r in rows}
        by_id.update({str(r['delivery_id']): r for r in data['rows']})
        rows = list(by_id.values())
        info.update(source='Order 逐条订单发货记录 + Sales 已有缓存', generatedAt=data['generatedAt'],
                    period=data['period'], limitation='仅匹配发货记录计算人民币毛利；未匹配不补零，未视作最终结算。')
    return rows, info


def collect(period):
    sys.path.insert(0, COLLECTOR)
    import p2pah_auth as auth
    session = auth.Session()
    token, reason = auth.admin_token_from_service()
    if not token: raise RuntimeError('admin_shared_source_unavailable')
    session.bind_admin_token(token); del token
    orders, logs = [], []
    try:
        for start, end in windows(period):
            batch = pages(session, '/admin/order.Order/index', [('site_id', '=', SITE), ('paytime', 'RANGE', start + ',' + end)], 100)
            if any(str(r.get('site_id')) != str(SITE) or not start <= str(r.get('paytime')) <= end for r in batch):
                raise ValueError('order_scope_not_honored')
            orders.extend(batch)
        discounts = pages(session, '/admin/market.Discount/index')
        templates = pages(session, '/admin/market.Coupon/index')
        order_numbers = [str(r['order_no']) for r in orders]
        for offset in range(0, len(order_numbers), 100):
            selected = order_numbers[offset:offset + 100]
            batch = pages(session, '/admin/user.MemberCouponLog/index', [('site_id', '=', SITE), ('order_no', 'IN', ','.join(selected))])
            if any(str(r.get('site_id')) != str(SITE) or r.get('order_no') not in selected for r in batch):
                raise ValueError('coupon_scope_not_honored')
            logs.extend(batch)
    finally:
        session.close()
    mapping = json.loads((Path(__file__).parent / 'channel_mapping.json').read_text('utf-8'))
    directory_path = SALES / 'promoter_dir.json'
    directory = json.loads(directory_path.read_text('utf-8')) if directory_path.is_file() else {}
    deliveries, cost_info = load_costs()
    return dict(period=period, generatedAt=datetime.now(TZ).isoformat(),
                mapping={k: v for k, v in mapping.items() if k != 'entries'},
                codeCatalog=Attribution(mapping, discounts, directory).catalog(),
                sources=dict(orders=dict(status='complete', source='Admin 销售订单', rows=len(orders), site='MMOEXP', dateBasis='paytime', currency='USD'),
                             coupons=dict(status='complete', source='Admin 优惠券使用日志，按订单号关联', rows=len(logs)),
                             cost=cost_info, attribution=dict(source='Excel 渠道映射 / Sales 推广人目录 / Admin 折扣码配置 / 订单推荐人 UID',
                                                             historical='当前映射回溯应用；未提供历史生效日期')),
                orders=normalize(orders, discounts, logs, templates, deliveries, directory, mapping))
