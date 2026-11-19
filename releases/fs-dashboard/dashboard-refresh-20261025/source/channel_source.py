"""Reuse Admin8767 and existing Sales caches; never authenticate independently."""
import json
import sys
import os
import tempfile
import hashlib
import time
from functools import lru_cache
from datetime import date, datetime, timedelta
from pathlib import Path

from channel_effects import Attribution, EMPTY_COST, SITE, TZ, delivery_index, normalize, money, number

COLLECTOR = '/opt/sales-dashboard/collector'
SALES = Path('/opt/sales-dashboard/data')
ROOT = Path('/var/lib/fs-channel-effects')
ES_ARCHIVE = Path('/var/lib/fc27-es-exports')


def apply_cost_overrides(data):
    path = ROOT / 'accounting-overrides.json'
    rules, tests = {}, {}
    info = dict(status='available', source='用户确认的历史零成本商品与测试单', orders=0, testOrders=0)
    try:
        if path.exists():
            if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size > 128*1024: raise ValueError('unsafe_accounting_overrides')
            raw = path.read_text('utf-8'); config = json.loads(raw)
            info['sourceVersion'] = hashlib.sha256(raw.encode()).hexdigest()
            rules = config['orders']
            tests = config.get('testOrders', {})
            if config.get('contract') != 'channel-zero-cost-v1' or not isinstance(rules,dict) or len(rules)>200:
                raise ValueError('invalid_accounting_overrides')
            for sn, rule in rules.items():
                if not isinstance(sn,str) or not 1 <= len(sn) <= 160 or not str(rule['gid']).isdigit() or not rule.get('productTitle'):
                    raise ValueError('invalid_zero_cost_identity')
                if money(rule.get('costCny')) != 0 or money(rule.get('salesUsd')) is None or money(rule.get('salesUsd')) < 0 or money(rule.get('saleCny')) is None or money(rule.get('saleCny')) < 0:
                    raise ValueError('invalid_zero_cost_amount')
            if not isinstance(tests,dict) or len(tests)>200: raise ValueError('invalid_test_orders')
            for sn, rule in tests.items():
                if not isinstance(sn,str) or not 1 <= len(sn) <= 160 or not str(rule['gid']).isdigit() or money(rule.get('salesUsd')) is None or money(rule['salesUsd']) < 0:
                    raise ValueError('invalid_test_order_identity')
            info['orders'] = len(rules)
            info['testOrders'] = len(tests)
    except (OSError,ValueError,KeyError,TypeError):
        rules, tests = {}, {}; info.update(status='unavailable', limitation='核算注释暂不可用，未匹配完成单保持待核，不推定为零或测试单。')
    data['costOverrides'] = rules
    data['testOrders'] = tests
    data['sources']['accounting'] = info
    return data


@lru_cache(maxsize=8)
def customer_types(start, end, manifests, archive):
    """Reuse immutable ES files, including complete sets covering a wider period."""
    import es_order_structure as es
    root = Path(archive)
    candidates = [json.loads((root / name).read_text('utf-8')) for name in manifests]
    cursor, selected = start, []
    while cursor <= end:
        options = [v for v in candidates if v['query']['start'] <= cursor <= v['query']['end']]
        if not options: break
        value = max(options, key=lambda v: (v['query']['end'], v.get('captured_at') or ''))
        selected.append(value)
        cursor = (date.fromisoformat(value['query']['end']) + timedelta(days=1)).isoformat()
    flags, hashes, captures, complete = {}, set(), [], cursor > end
    order_sources = {}
    for value in selected:
        dataset = es.archived_dataset(value['query'], root=root)
        if not dataset: complete = False; continue
        complete &= dataset['parse_failures'] == 0 and dataset['failed_files'] == 0 and dataset['declared_files'] == len(dataset['hashes'])
        hashes.update(dataset['hashes']); captures.append(dataset['captured_at'])
        for row in dataset['rows']:
            paid = str(row.get('付款时间') or '').replace('/', '-')[:10]
            if start <= paid <= end and row.get('订单号'):
                flags.setdefault(row['订单号'], set()).add(str(row.get('是否新客户') or '').strip())
                order_sources.setdefault(row['订单号'], set()).add((row.get('订单来源'), str(row.get('游戏') or '').strip()))
    index = {key: {'是': '新客', '否': '老客'}.get(next(iter(values)), '新老客未提供') if len(values) == 1 else '待核：新老客冲突' for key, values in flags.items()}
    return index, dict(status='complete' if complete else 'partial', source='Admin ES订单：下单时是否新客户',
                       generatedAt=max((v for v in captures if v), default=None),
                       sourceVersion=hashlib.sha256(''.join(sorted(hashes)).encode()).hexdigest(),
                       files=len(hashes), orderSources={key:dict(sourceRaw=next(iter(values))[0], sourceGame=next(iter(values))[1], sourceStatus='available' if next(iter(values))[0] is not None else 'unavailable') if len(values)==1 else dict(sourceRaw=None, sourceGame='', sourceStatus='conflict') for key,values in order_sources.items()}, limitation='按该笔订单的ES字段判断；缺失、未匹配和冲突不按老客推断，不使用当前会员状态或Admin isNew。')


def apply_current_mapping(data):
    raw = Path(__file__).with_name('channel_mapping.json').read_bytes()
    attribution = Attribution(json.loads(raw), [], {})
    def project(key, previous):
        channels = attribution.channels.get(str(key).strip().casefold(), set())
        return next(iter(channels)) if len(channels) == 1 else previous
    data['orders'] = [dict(row, project=project(row.get('codeKey'), row['project'])
                           if row.get('codeKey') and not row.get('conflict') else row['project']) for row in data['orders']]
    data['codeCatalog'] = [dict(row, project=project(row['key'], row['project'])) for row in data.get('codeCatalog', [])]
    data['sources']['attribution'] = dict(data['sources'].get('attribution', {}),
        mappingVersion=hashlib.sha256(raw).hexdigest(),
        projection='当前渠道映射回溯应用于有码订单；保留原采集时间、推广人、冲突和订单站点。')
    return data


def apply_customer_types(data, request=False):
    """Correct old normalized caches too; never retain the mistaken Admin flag."""
    sys.path.insert(0, '/opt/fs-hermes-fc')
    start, end = data['period']['start'], data['period']['end']
    def read():
        names = tuple(sorted(p.name for p in ES_ARCHIVE.glob('*.json')))
        return customer_types(start, end, names, str(ES_ARCHIVE))
    try:
        index, info = read()
        if request and info['status'] != 'complete':
            import es_order_structure as es
            query = dict(profile='ALL', start=start, end=end, group_by='new_customer', status='all')
            deadline = time.monotonic() + 160
            while time.monotonic() < deadline:
                # The existing durable attempt ledger prevents a duplicate export.
                result = es.server_bundle(query)
                if result.get('status') != 'pending' and not result.get('refresh_pending'): break
                time.sleep(3)
            index, info = read()
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        index, info = {}, dict(status='unavailable', source='Admin ES订单：下单时是否新客户', limitation='ES字段暂未取得，保持未知，不按老客推断。')
    info = dict(info)
    sources = info.pop('orderSources', {})
    for row in data['orders']:
        row.update(sources.get(hashlib.sha256(row['orderNo'].encode()).hexdigest(), dict(sourceRaw=None, sourceGame='', sourceStatus='unavailable')))
        row['customerType'] = index.get(hashlib.sha256(row['orderNo'].encode()).hexdigest(), '新老客未提供')
    data['sources']['orderSource'] = dict(status=info.get('status','unavailable'), source='Admin ES订单来源与实际游戏', generatedAt=info.get('generatedAt'), sourceVersion=info.get('sourceVersion'), matchedOrders=sum(r.get('sourceStatus')=='available' for r in data['orders']), limitation='按同订单身份关联；来源缺失/冲突保持未知，不当自然。广告优先视图与码/推荐人协助视图独立。')
    data['sources']['customer'] = dict(info, matchedOrders=sum(r['customerType'] in ('新客', '老客') for r in data['orders']))
    return apply_current_mapping(data)


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
                limitation='当前仅使用可关联的发货缓存；未匹配采购成本保持缺失，不代表整单已履约或已最终结算。')
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
                    period=data['period'], limitation='仅关联实际发货采购成本；收入使用Admin单笔原人民币金额，缺失不补零，不视作财务最终结算。')
    return rows, info


def enrich(data, force=False):
    """Publish orders first, then fill costs through the same shared Order source."""
    from urllib.request import urlopen
    try:
        with urlopen('http://127.0.0.1:8768/health', timeout=5) as response:
            ready = json.load(response).get('ready') is True
    except OSError:
        ready = False
    if not ready:
        data['sources']['cost']['status'] = 'unavailable'
        data['sources']['cost']['limitation'] = 'Order 共享源暂不可用；保留已有发货覆盖，不将缺失成本补零。'
        return data
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = ROOT / 'order-deliveries.json'
    from channel_cache import delivery_bounds
    from order_delivery_index import MAIN_SITE, capture_time, covered_through, read_orders, sync_after_publish, trade_second
    import fcntl
    with (ROOT / 'order-deliveries.lock').open('a+b') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            data['sources']['cost']['limitation'] = '另一项全局成本读取进行中；保留现有覆盖，完成后可刷新。'
            return data
        previous = json.loads(path.read_text('utf-8')) if path.is_file() else None
        if previous and (previous.get('contract') != 'channel-order-deliveries-v1' or previous.get('complete') is not True):
            raise ValueError('invalid_order_cost_cache')
        now = datetime.now(TZ)
        # Exclude the open minute so newly created rows do not shift offset pages.
        cutoff = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
        requested = data['period']['start']+' 00:00:00'
        stop = cutoff.strftime('%Y-%m-%d %H:%M:59')
        if requested > stop:
            return data
        proof = read_orders((),root=ROOT)
        if proof['status'] != 'available' and previous and sync_after_publish(ROOT):
            proof = read_orders((),root=ROOT)
        covered = covered_through(proof['windows'],MAIN_SITE,requested,as_of=now) if not force else None
        # The JSON fallback must keep the entire prefix it used to return.
        retained_through = None
        reusable = None
        age = None
        if previous and not force:
            observed = capture_time(previous['generatedAt'])
            age = (now-observed).total_seconds()
            legacy_start, legacy_stop = delivery_bounds(previous['period'])
            retained_from = previous.get('retainedFrom',legacy_start)
            trade_second(retained_from)
            if retained_from <= legacy_start and retained_from <= requested <= legacy_stop and covered:
                retained_through = min(covered,legacy_stop)
            if (legacy_start <= requested <= legacy_stop
                    and datetime.fromisoformat(legacy_stop).replace(tzinfo=TZ) <= observed <= now):
                reusable = legacy_stop
            reusable = max(reusable or '',retained_through or '')
        if reusable and (reusable>=stop or reusable[:10]==now.date().isoformat() and age is not None and 0<=age<600):
            data['sources']['cost']['limitation'] = '复用固定发货截止 ' + reusable + '；未匹配不补零，匹配不等于最终结算。'
            if data.get('include_cost_delivery_rows') is True:
                data['cost_delivery_rows'], _ = load_costs()
            return data
        begin = requested
        if retained_through:
            overlap = datetime.fromisoformat(retained_through)-timedelta(minutes=5)+timedelta(seconds=1)
            begin = max(requested,overlap.strftime('%Y-%m-%d %H:%M:%S'))
        window = dict(start=begin[:10],end=cutoff.date().isoformat(),until=cutoff.strftime('%Y-%m-%d %H:%M'))
        if begin != requested:
            window['since'] = begin
        from channel_cost_source import collect as cost_collect
        sys.path.insert(0, COLLECTOR); import p2pah_auth as auth
        session = auth.Session()
        try:
            fresh = cost_collect(session,window['start'],window['end'],until=window['until'],
                                 **({'since':begin} if 'since' in window else {}))
        finally: session.close()
        # A complete window replaces its membership, including records no longer returned.
        by_id = {str(r['delivery_id']): r for r in (previous or {}).get('rows', [])
                 if not begin <= r['trade_at'] <= stop}
        by_id.update({str(r['delivery_id']): r for r in fresh})
        cache = dict(contract='channel-order-deliveries-v1', complete=True, generatedAt=datetime.now(TZ).isoformat(),
                     period=window, rows=list(by_id.values()), retainedFrom=requested)
        fd, temp = tempfile.mkstemp(dir=ROOT)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(cache, output); output.flush(); os.fsync(output.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        deliveries, cost_info = load_costs()
        index = delivery_index(deliveries)
        for row in data['orders']: row.update(index.get(row['orderNo'], EMPTY_COST))
        cost_info['limitation'] = '已按固定发货截止 ' + cutoff.strftime('%Y-%m-%d %H:%M') + ' 完整分页读取；未匹配不补零，匹配不等于全部履约或最终结算。'
        data['sources']['cost'] = cost_info
        if data.get('include_cost_delivery_rows') is True:
            data['cost_delivery_rows'] = deliveries
    sync_after_publish(ROOT)
    return data


def shared_view(period, gid=None, *, read=None):
    """Adapt one existing scoped ES publication to the original channel views."""
    from order_facts_api import safe_detail
    if read is None:
        from order_facts_runtime import collect_dashboard as read
    scope = dict(period,site_id=str(SITE),gid=gid or 'all')
    result = read(scope)
    coverage = result['source_coverage']
    if result['status']=='unavailable':return None, coverage
    deliveries, cost = load_costs()
    costs = delivery_index(deliveries)
    orders = []
    for fact in result['orders']:
        effective = fact['effective_attribution']
        observed = effective['filter_row']
        code, uid = observed.get('code') or '', effective.get('promoter_uid') or ''
        project = observed.get('project') or '未归类'
        flags = fact.get('pinned_customer_flag')
        source = safe_detail(effective['order_source'])
        orders.append(dict(orderNo=fact['order_no'], gid=fact['gid'], game=fact['game'] or '游戏未提供',
            paidAt=fact['paid_at'], day=fact['paid_at'][:10], salesUsd=number(money(fact['admin_paid_usd'])),
            adminSaleCny=number(money(fact['admin_paid_cny'])), status=fact['status'], payStatus=fact['pay_status'],
            refunded=observed['refunded'], country=observed.get('country') or '国家未提供', payment=observed.get('payment') or '支付方式未提供',
            customerType={'是':'新客','否':'老客'}.get(flags, effective.get('historical_customer_type') or '新老客未提供'),
            sourceRaw=source, sourceStatus='available' if source and not effective.get('source_conflict') else 'unavailable',
            code=code,codeKey=code.casefold(),project=project,promoter=observed.get('promoter') or '推广人未提供',promoterUid=uid,
            attribution='折扣码' if code else '推荐人无码' if uid else '无推广归属', attributionSource=effective.get('promoter_basis'),
            conflict=effective['conflict'],coupons=observed.get('coupons') or [],couponUnknown=observed.get('coupons') is None,
            **costs.get(fact['order_no'],EMPTY_COST)))
    unknown_coupons = sum(r['couponUnknown'] for r in orders)
    mapping_path=Path(__file__).with_name('channel_mapping.json')
    mapping=json.loads(mapping_path.read_bytes())
    directory_path=SALES/'promoter_dir.json'
    directory=json.loads(directory_path.read_bytes()) if directory_path.is_file() else {}
    data=dict(period=period, generatedAt=coverage['captured_at'], orders=orders,
        mapping={key:value for key,value in mapping.items() if key!='entries'},
        codeCatalog=Attribution(mapping,[],directory).catalog(),
        sources=dict(orders=dict(status='complete' if coverage['admin_complete'] else 'partial', source='共享ES订单库',
                rows=len(orders), site='MMOEXP', dateBasis='paytime', currency='USD',
                publication_id=coverage.get('publication_id'),missing_days=coverage.get('missing_days',[])),
            coupons=dict(status='partial' if unknown_coupons else 'complete',source='共享ES订单库 · Admin用券记录',
                         unknownOrders=unknown_coupons),cost=cost,
            customer=dict(limitation='复用同单固定ES新老客字段；缺失保留未知'),
            attribution=dict(source='共享ES订单库 + 现有推广映射',historical='当前映射回溯应用；未提供历史生效日期')))
    return apply_cost_overrides(data), coverage


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
    return apply_cost_overrides(apply_customer_types(dict(period=period, generatedAt=datetime.now(TZ).isoformat(),
                mapping={k: v for k, v in mapping.items() if k != 'entries'},
                codeCatalog=Attribution(mapping, discounts, directory).catalog(),
                sources=dict(orders=dict(status='complete', source='Admin 销售订单', rows=len(orders), site='MMOEXP', dateBasis='paytime', currency='USD'),
                             coupons=dict(status='complete', source='Admin 优惠券使用日志，按订单号关联', rows=len(logs)),
                             cost=cost_info, attribution=dict(source='Excel 渠道映射 / Sales 推广人目录 / Admin 折扣码配置 / 订单推荐人 UID',
                                                             historical='当前映射回溯应用；未提供历史生效日期')),
                orders=normalize(orders, discounts, logs, templates, deliveries, directory, mapping)), request=True))
