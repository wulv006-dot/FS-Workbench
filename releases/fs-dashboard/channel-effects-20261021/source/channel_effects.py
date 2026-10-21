"""MMOEXP channel effects: read-only attribution, covered-cohort money and cache."""
import hashlib
import json
import os
import re
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from threading import RLock

VERSION = 'channel-effects-v1'
SITE = 266
TZ = timezone(timedelta(hours=8))


def money(value):
    if value is None or str(value).strip() in ('', '-', '—'):
        return None
    try:
        result = Decimal(re.sub(r'[$￥¥,\s]', '', str(value)))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def number(value):
    return None if value is None else float(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def positive_id(value):
    text = str(value or '').strip()
    return text if text.isdigit() and int(text) > 0 else ''


def ids(value):
    return {v.strip() for v in str(value or '').split(',') if v.strip() not in ('', '0')}


def clean(value, limit=160):
    return re.sub(r'<[^>]*>', '', str(value or '')).strip()[:limit]


class Attribution:
    def __init__(self, mapping, discounts, directory):
        self.channels = defaultdict(set)
        self.spellings = defaultdict(list)
        for entry in mapping['entries']:
            code, channel = entry['code'], entry['channel']
            self.channels[code.strip().casefold()].add('TikTok' if channel.casefold() in ('tt', 'tiktok') else channel)
            if code not in self.spellings[code.strip().casefold()]: self.spellings[code.strip().casefold()].append(code)
        self.config = defaultdict(list)
        for record in discounts:
            if not ids(record.get('site_id')) or str(SITE) in ids(record.get('site_id')):
                self.config[str(record.get('code') or '').strip().casefold()].append(record)
        self.directory = {k.casefold(): v for k, v in (directory.get('by_code') or {}).items()}
        self.people = directory.get('by_uid') or {}
        self.uid_channels = defaultdict(set)
        for key in set(self.channels) | set(self.config) | set(self.directory):
            channels = self.channels.get(key, set())
            if len(channels) != 1:
                continue
            person = self.directory.get(key)
            candidates = {positive_id(person.get('uid'))} if person else {
                positive_id(r.get('uid')) for r in self.config.get(key, [])}
            candidates.discard('')
            if len(candidates) == 1:
                self.uid_channels[next(iter(candidates))].update(channels)

    def catalog(self):
        result = []
        for key, channels in self.channels.items():
            configs = self.config.get(key, [])
            person = self.directory.get(key) or {}
            result.append(dict(key=key, label=' / '.join(self.spellings[key]), project=next(iter(channels)) if len(channels) == 1 else '待核：映射冲突',
                               promoters=clean(person.get('name')), games=sorted(set().union(*(ids(r.get('gid')) for r in configs))),
                               universal=not configs or any(not ids(r.get('gid')) for r in configs)))
        return result

    def resolve(self, order):
        raw = str(order.get('discount_code') or '').strip()
        key = raw.casefold()
        uid = positive_id(order.get('recommend_uid'))
        name, origin, conflict = '', 'none', False
        if key:
            configs = [r for r in self.config.get(key, []) if not ids(r.get('gid')) or str(order['gid']) in ids(r.get('gid'))]
            # The team directory is the Sales system's explicit owner correction.
            person = self.directory.get(key)
            if person:
                uid, name, origin = positive_id(person.get('uid')), clean(person.get('name')), 'promoter_directory'
            elif configs:
                owners = set()
                for record in configs:
                    owner_uid = positive_id(record.get('uid'))
                    owners.add((owner_uid, '' if owner_uid else clean((record.get('admins') or {}).get('nickname'))))
                if len(owners) == 1:
                    owner_uid, name = next(iter(owners))
                    uid = owner_uid if owner_uid or name else uid
                    origin = 'discount_configuration'
                else:
                    conflict, origin = True, 'configuration_conflict'
            if uid and not name:
                name = clean((self.people.get(uid) or {}).get('name')) or '推广人 ' + uid
            channels = self.channels.get(key, set())
            if len(channels) > 1:
                conflict = True
            project = '待核：映射冲突' if conflict else next(iter(channels)) if len(channels) == 1 else '未归类'
            return dict(code=raw, codeKey=key, project=project, promoter=name or raw,
                        promoterUid=uid, attribution='折扣码', attributionSource=origin, conflict=conflict)
        if uid:
            channels = self.uid_channels.get(uid, set())
            return dict(code='', codeKey='', project=next(iter(channels)) if len(channels) == 1 else '推荐人渠道待核',
                        promoter=clean((self.people.get(uid) or {}).get('name')) or '推广人 ' + uid,
                        promoterUid=uid, attribution='推荐人无码', attributionSource='recommend_uid', conflict=len(channels) > 1)
        return dict(code='', codeKey='', project='无推广归属', promoter='无推广归属', promoterUid='',
                    attribution='无推广归属', attributionSource='none', conflict=False)


def delivery_index(deliveries):
    costs = defaultdict(list)
    seen = set()
    for record in deliveries:
        did = str(record.get('delivery_id') or '')
        if not did or did in seen:
            raise ValueError('duplicate_or_missing_delivery_id')
        seen.add(did)
        if str(record.get('genre')) in ('1', '订单发货') and clean(record.get('source')) == 'www.mmoexp.com':
            costs[str(record.get('sn'))].append(record)
    result = {}
    for sn, records in costs.items():
        sale, cost = [money(r.get('sale_total')) for r in records], [money(r.get('cost_total')) for r in records]
        s = sum(sale, Decimal(0)) if all(v is not None and v >= 0 for v in sale) else None
        c = sum(cost, Decimal(0)) if all(v is not None and v >= 0 for v in cost) else None
        result[sn] = dict(saleCny=number(s), costCny=number(c), profitCny=number(s-c) if s is not None and c is not None else None, deliveryRows=len(records))
    return result


EMPTY_COST = dict(saleCny=None, costCny=None, profitCny=None, deliveryRows=0)


def completed(row):
    return row['status'] == '已完成' and not row['refunded'] and not row.get('testOrder')


def fraud(row):
    return re.sub(r'[·\s]', '', row['status']) == '验证未通过'


def accounting_row(raw, overrides, tests=None, admin_revenue=True):
    row = dict(raw, zeroCost=False, testOrder=False,
               revenueBasis='admin_order_cny' if admin_revenue and 'adminSaleCny' in raw else 'legacy_delivery')
    test = (tests or {}).get(row['orderNo'])
    if test and str(test['gid']) == row['gid'] and money(test['salesUsd']) == money(row['salesUsd']):
        row.update(testOrder=True, saleCny=None, costCny=None, profitCny=None, costStatus='测试单：不计经营指标')
        return row
    if not completed(row):
        row.update(saleCny=None, costCny=None, profitCny=None,
                   costStatus='已退款：不核算' if row['refunded'] else '欺诈单：待退款/申诉' if fraud(row) else '未完成：不核算')
        return row
    rule = overrides.get(row['orderNo'])
    if rule and str(rule['gid']) == row['gid'] and money(rule['salesUsd']) == money(row['salesUsd']):
        sale = money(rule['saleCny'])
        row.update(saleCny=number(sale), costCny=0.0, profitCny=number(sale), zeroCost=True,
                   costStatus='已完成：确认零成本', costBasis=rule['productTitle'])
    else:
        if row['revenueBasis'] == 'admin_order_cny':
            sale, cost = money(row['adminSaleCny']), money(row['costCny'])
            row.update(saleCny=number(sale), profitCny=number(sale-cost) if sale is not None and cost is not None else None)
        row['costStatus'] = '已完成：成本待核' if row['costCny'] is None or row['saleCny'] is None else '已完成：成本已核'
        if row['revenueBasis'] == 'admin_order_cny' and row['saleCny'] is None:
            row['costStatus'] = '已完成：Admin人民币收入待核'
        if row['costStatus'].endswith('成本待核') and (row['game'].replace(' ', '').startswith('NBA2K') or row['game'] == 'ARC Raiders'):
            row['costStatus'] = '已完成：SCM发货，当前源无成本'
    return row


def normalize(orders, discounts, coupon_logs, templates, deliveries, directory, mapping):
    attribution = Attribution(mapping, discounts, directory)
    costs, logs = delivery_index(deliveries), defaultdict(list)
    template_map = {str(t['id']): t for t in templates}
    seen = set()
    for log in coupon_logs:
        lid = str(log.get('id') or '')
        if not lid or lid in seen:
            raise ValueError('duplicate_or_missing_coupon_log_id')
        seen.add(lid)
        if str(log.get('site_id')) != str(SITE) or not log.get('use_time'):
            continue
        template = template_map.get(str(log.get('coupon_id')), {})
        logs[str(log.get('order_no'))].append(dict(
            id=lid, templateId=str(log.get('coupon_id') or 'unknown'),
            title=clean(template.get('title') or log.get('title')) or '未命名优惠券',
            batch=clean((log.get('memberCoupon') or {}).get('grant_batch_no')) or '批次未提供',
            usedAt=clean(log.get('use_time')), status=clean(log.get('status'))))
    result, seen = [], set()
    for order in orders:
        sn = str(order.get('order_no') or '')
        if not sn or sn in seen or str(order.get('site_id')) != str(SITE):
            raise ValueError('invalid_order_identity_or_scope')
        seen.add(sn)
        amount = money(order.get('amount_usd_format'))
        if amount is None:
            raise ValueError('missing_usd_order_amount')
        row = dict(orderNo=sn, gid=str(order.get('gid')), game=clean(order.get('game_format') or (order.get('game') or {}).get('title')) or '游戏未提供',
                   paidAt=clean(order.get('paytime')), day=clean(order.get('paytime'))[:10], salesUsd=number(amount),
                   adminSaleCny=number(money(order.get('amount_rmb_format'))),
                   status=clean(order.get('status_format')) or '状态未提供', payStatus=clean(order.get('pay_status')),
                   refunded=str(order.get('pay_status')) == '2' or clean(order.get('status_format')).startswith('已退款'),
                   country=clean(order.get('country_code') or order.get('country')) or '国家未提供',
                   payment=clean(order.get('paytype_display') or order.get('paytype')) or '支付方式未提供',
                   customerType='新老客未提供',
                   coupons=logs.get(sn, []), **costs.get(sn, EMPTY_COST), **attribution.resolve(order))
        result.append(row)
    return result


def metrics(rows):
    test_count = sum(r.get('testOrder',False) for r in rows)
    rows = [r for r in rows if not r.get('testOrder')]
    fraud_rows = [r for r in rows if fraud(r)]
    rows = [r for r in rows if not fraud(r)]
    covered = [r for r in rows if completed(r) and r['costCny'] is not None and r['saleCny'] is not None]
    total = lambda key, items: sum((Decimal(str(r[key])) for r in items), Decimal(0))
    usd, sale, cost = total('salesUsd', rows), total('saleCny', covered), total('costCny', covered)
    return dict(orders=len(rows), testOrders=test_count, salesUsd=number(usd), coveredOrders=len(covered),
                completedOrders=sum(completed(r) for r in rows), pendingOrders=sum(not completed(r) and not r['refunded'] for r in rows),
                refundedOrders=sum(r['refunded'] for r in rows),
                fraudOrders=len(fraud_rows), excludedFraudUsd=number(total('salesUsd', fraud_rows)),
                legacyRevenueOrders=sum(r.get('revenueBasis') == 'legacy_delivery' for r in covered),
                missingRevenueOrders=sum(completed(r) and r.get('revenueBasis') == 'admin_order_cny' and r['saleCny'] is None for r in rows),
                missingCostOrders=sum(completed(r) and (r['costCny'] is None or r['saleCny'] is None) for r in rows),
                scmOrders=sum('SCM发货' in r.get('costStatus','') for r in rows),
                zeroCostOrders=sum(r.get('zeroCost',False) for r in covered),
                deliveryRows=sum(r['deliveryRows'] for r in covered),
                saleCny=number(sale) if covered else None, costCny=number(cost) if covered else None,
                profitCny=number(sale - cost) if covered else None,
                margin=float((sale - cost) / sale) if sale else None,
                aovUsd=number(usd / len(rows)) if rows else None,
                codedOrders=sum(bool(r['codeKey']) for r in rows),
                referrerOnly=sum(r['attribution'] == '推荐人无码' for r in rows),
                overlapOrders=sum(bool(r['codeKey'] and r['coupons']) for r in rows),
                conflicts=sum(r['conflict'] for r in rows))


def grouped(rows, key, labels=None):
    buckets = defaultdict(list)
    for row in rows:
        buckets[str(row[key])].append(row)
    return sorted([dict(key=k, label=(labels or {}).get(k, k), **metrics(v)) for k, v in buckets.items()],
                  key=lambda r: (-r['salesUsd'], r['key']))


def view(data, query):
    admin_revenue = all('adminSaleCny' in r for r in data['orders'])
    rows = [accounting_row(r, data.get('costOverrides', {}), data.get('testOrders', {}), admin_revenue) for r in data['orders']]
    base = [r for r in rows if (not query.get('gid') or r['gid'] == query['gid'])
            and (query.get('status', 'valid') != 'valid' or not r['refunded'])
            and (query.get('status') != 'refund' or r['refunded'])
            and (not query.get('country') or r['country'] == query['country'])
            and (not query.get('payment') or r['payment'] == query['payment'])]
    coupon = query.get('mode') == 'coupon'
    mode_rows = [r for r in base if r['coupons']] if coupon else [r for r in base if r['codeKey'] or r['promoterUid']]
    templates = {c['templateId']: c['title'] for r in base for c in r['coupons']}
    if coupon:
        left = [dict(key=k, label=title, **metrics([r for r in mode_rows if any(c['templateId'] == k for c in r['coupons'])])) for k, title in templates.items()]
        selected = [r for r in mode_rows if not query.get('project') or any(c['templateId'] == query['project'] for c in r['coupons'])]
        batches = sorted({c['batch'] for r in selected for c in r['coupons'] if not query.get('project') or c['templateId'] == query['project']})
        right = [dict(key=b, label=b, **metrics([r for r in selected if any(c['batch'] == b and (not query.get('project') or c['templateId'] == query['project']) for c in r['coupons'])])) for b in batches]
        selected = [r for r in selected if not query.get('code') or any(c['batch'] == query['code'] and (not query.get('project') or c['templateId'] == query['project']) for c in r['coupons'])]
    else:
        left = grouped(base, 'project')
        selected = [r for r in mode_rows if not query.get('project') or r['project'] == query['project']]
        labels = {r['codeKey']: r['code'] for r in selected if r['codeKey']}
        labels[''] = '推荐人无码'
        right = grouped(selected, 'codeKey', labels)
        for row in right:
            row['promoters'] = ' / '.join(sorted({r['promoter'] for r in selected if r['codeKey'] == row['key']}))[:200]
        existing = {r['key'] for r in right}
        projects = {r['key'] for r in left}
        for code in data.get('codeCatalog', []):
            if query.get('gid') and not code['universal'] and query['gid'] not in code['games']:
                continue
            if code['project'] not in projects:
                left.append(dict(key=code['project'], label=code['project'], **metrics([])))
                projects.add(code['project'])
            if code['key'] not in existing and (not query.get('project') or code['project'] == query['project']):
                right.append(dict(key=code['key'], label=code['label'], promoters=code['promoters'], **metrics([])))
                existing.add(code['key'])
        selected = [r for r in selected if 'code' not in query or r['codeKey'] == query['code']]
    if query.get('q'):
        term = query['q'].casefold()
        selected = [r for r in selected if term in (r['orderNo'] + ' ' + r['code'] + ' ' + r['promoter']).casefold()]
    summary, denominator = metrics(selected), metrics(base)
    summary['shareAllCodes'] = summary['codedOrders'] / denominator['codedOrders'] if denominator['codedOrders'] else None
    summary['shareSite'] = summary['codedOrders'] / denominator['orders'] if denominator['orders'] else None
    summary['couponShareSite'] = summary['orders'] / denominator['orders'] if coupon and denominator['orders'] else None
    days = {r['key']: r for r in grouped(selected, 'day')}
    start, end = date.fromisoformat(data['period']['start']), date.fromisoformat(data['period']['end'])
    trend = [days.get((start + timedelta(days=i)).isoformat(), dict(key=(start + timedelta(days=i)).isoformat(), **metrics([]))) for i in range((end - start).days + 1)]
    sort = query.get('sort', 'paidAt')
    reverse = query.get('direction', 'desc') == 'desc'
    selected.sort(key=lambda r: (r[sort] is not None, r[sort] if r[sort] is not None else 0, r['orderNo']), reverse=reverse)
    page = min(int(query.get('page', '1')), max(1, (len(selected) + 49) // 50))
    return dict(version=VERSION, revenueBasis='admin_order_cny' if admin_revenue else 'legacy_delivery', period=data['period'], generatedAt=data['generatedAt'], sources=data['sources'],
                mapping=data['mapping'], summary=summary, denominator=denominator, trend=trend,
                projects=sorted(left, key=lambda r: -r['salesUsd']), codes=sorted(right, key=lambda r: -r['salesUsd']),
                breakdowns={key: grouped(selected, key) for key in ('game', 'country', 'payment', 'customerType', 'status')},
                options=dict(games=sorted({(r['gid'], r['game']) for r in rows}, key=lambda p: p[1]),
                             countries=sorted({r['country'] for r in rows}), payments=sorted({r['payment'] for r in rows})),
                orders=selected[(page - 1) * 50:page * 50], page=page, pages=max(1, (len(selected) + 49) // 50), total=len(selected))


def parse_query(params):
    allowed = {'start', 'end', 'mode', 'gid', 'project', 'code', 'status', 'country', 'payment', 'q', 'page', 'sort', 'direction', 'refresh'}
    if set(params) - allowed or any(len(v) != 1 or len(v[0]) > 160 for v in params.values()):
        raise ValueError('invalid_parameters')
    q = {k: v[0] for k, v in params.items()}
    start, end = date.fromisoformat(q.get('start', '')), date.fromisoformat(q.get('end', ''))
    if not start <= end <= datetime.now(TZ).date() or (end - start).days > 365:
        raise ValueError('invalid_period')
    for key, values in (('mode', ('code', 'coupon')), ('status', ('valid', 'all', 'refund')),
                        ('sort', ('paidAt', 'salesUsd', 'costCny', 'profitCny', 'orderNo')), ('direction', ('asc', 'desc')), ('refresh', ('1',))):
        if key in q and q[key] not in values:
            raise ValueError('invalid_' + key)
    if 'gid' in q and not q['gid'].isdigit():
        raise ValueError('invalid_game')
    if not re.fullmatch(r'[1-9][0-9]{0,5}', q.get('page', '1')):
        raise ValueError('invalid_page')
    return q


class ChannelService:
    def __init__(self, root, authorizer, source=None):
        self.root, self.authorizer, self.source = Path(root), authorizer, source
        self.pool, self.lock, self.jobs, self.starts = ThreadPoolExecutor(max_workers=2), RLock(), {}, {}

    def publish(self, data, target):
        fd, temp = tempfile.mkstemp(dir=self.root, prefix='channel-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(data, output, ensure_ascii=False, allow_nan=False)
                output.flush(); os.fsync(output.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def capture(self, period, key, target, force=False, cost_only=False):
        cost_phase = False
        try:
            import fcntl
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)
            with (self.root / 'collector.lock').open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if self.source is None:
                    from channel_cache import collect_period, compose
                    source = (lambda p: compose(p, self.root)) if cost_only else (lambda p: collect_period(p, self.root, force=force))
                else:
                    source = self.source
                data = source(period)
                if data.get('period') != period or not isinstance(data.get('orders'), list):
                    raise ValueError('source_contract_failed')
                self.publish(data, target)
                if self.source is None:
                    from channel_cache import store_days
                    store_days(data, self.root)
            if self.source is None:
                from channel_source import enrich
                cost_phase = True
                with self.lock: self.jobs[key] = 'cost_pending'
                data = enrich(data, force=force)
                self.publish(data, target)
                store_days(data, self.root)
            with self.lock: self.jobs[key] = 'available'
        except Exception:
            with self.lock: self.jobs[key] = 'cost_failed' if cost_phase else 'source_failed'

    def get(self, params, user):
        if not self.authorizer(user):
            return 403, {'error': 'admin_required'}
        query = parse_query(params)
        period = {k: query[k] for k in ('start', 'end')}
        key = hashlib.sha256((VERSION + json.dumps(period, sort_keys=True)).encode()).hexdigest()[:24]
        target = self.root / (key + '.json')
        archived = None
        if self.source is None and period['end'] < datetime.now(TZ).date().isoformat():
            from channel_cache import compose
            archived = compose(period, self.root)
        data = archived or (json.loads(target.read_text('utf-8')) if target.is_file() else None)
        with self.lock:
            state = self.jobs.get(key)
            coverage=(data or {}).get('sources',{}).get('cache',{})
            revenue_ready=bool(data is not None and all('adminSaleCny' in r for r in data['orders']))
            fixed=bool(archived and revenue_ready and coverage.get('deliveryDayComplete') and coverage.get('customerDayComplete'))
            stamp = data['sources'].get('cost',{}).get('generatedAt') if fixed else (data or {}).get('generatedAt')
            fresh = bool(revenue_ready and stamp and 0 <= time.time() - datetime.fromisoformat(stamp).timestamp() < 600)
            if (not fresh or query.get('refresh')) and state not in ('pending','cost_pending'):
                if time.monotonic() - self.starts.get(key, -1000) >= 60:
                    if sum(v in ('pending','cost_pending') for v in self.jobs.values()) >= 2:
                        if not data or fresh: return 429, {'status': 'busy', 'retryAfter': 10}
                        state = 'deferred'
                    else:
                        self.starts[key] = time.monotonic(); self.jobs[key] = 'pending'; state = 'pending'
                        self.pool.submit(self.capture, period, key, target, force=bool(query.get('refresh')),
                                         cost_only=bool(fixed and not query.get('refresh')))
            if data:
                if self.source is None:
                    from channel_source import apply_customer_types, apply_cost_overrides
                    from channel_cache import apply_delivery_cache
                    data = apply_delivery_cache(data, self.root)
                    data = apply_cost_overrides(apply_customer_types(data))
                result = view(data, query)
                result.update(status='available', refreshing=state in ('pending','cost_pending','deferred'), costRefreshing=state == 'cost_pending', costError=state == 'cost_failed', stale=not bool(fresh), sourceError=state == 'source_failed')
                return 200, result
            return (503 if state == 'source_failed' else 202), dict(status=state or 'pending', retryAfter=3)
