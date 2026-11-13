"""Authorized aggregate-only D2 reads, using the existing channel worker budget."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import csv
import gzip
import hashlib
import io
import json
import math
import re
import time
from urllib.parse import urlsplit

from channel_effects import base_order_matches, keyword_order_matches, promotion_order_matches
from order_facts import summarize

VERSION = 'order-facts-api-20261113-v1'
CHANNELS = ('all', 'SEO', 'Direct', 'PPC', 'Referral', 'Campaign', 'pending_classification', 'unknown')
CHANNEL_LABELS = {'SEO':'SEO（自然搜索）','Direct':'Direct（直接访问）','PPC':'PPC（谷歌广告）',
                  'Referral':'Referral（引荐）','Campaign':'Campaign（营销活动）','pending_classification':'待归类','unknown':'未知'}
UNCLASSIFIED = ('unknown','pending_classification')
ACTIVE = ('pending', 'cost_pending')
FILTERS = ('status','country','payment','project','code','coupon_template','coupon_batch','q')
DETAIL_COLUMNS = (('paidAt','付款时间'),('orderNo','订单号'),('game','游戏'),('channel','归因渠道'),
    ('source','来源明细'),('project','推广项目'),('promoter','推广人'),('code','折扣码'),('coupons','优惠券'),
    ('country','国家'),('payment','支付方式'),('salesUsd','订单金额 USD'),('saleCny','订单金额 CNY'),
    ('costCny','已读采购 CNY'),('profitCny','已核同单毛利 CNY'),('status','订单状态'))


def matches_tracking_filters(effective, q):
    row = effective.get('filter_row') or {}
    if not any(k in q for k in FILTERS):return True
    if not row:return None
    missing = any(q.get(k) and row.get(k) is None for k in ('country','payment','project'))
    missing |= 'code' in q and row.get('codeKey') is None
    if not base_order_matches(row,{'status':q.get('status','all'),**{k:q[k] for k in ('country','payment') if row.get(k) is not None and k in q}}):
        return False
    promotion_query = {k:q[k] for k in ('project','code') if k in q and row.get('project' if k=='project' else 'codeKey') is not None}
    if not promotion_order_matches(row,promotion_query,coupon=False):return False
    if 'coupon_template' in q or 'coupon_batch' in q:
        if row.get('coupons') is None:
            missing = True
        elif not promotion_order_matches(row,{'project':q.get('coupon_template'),'code':q.get('coupon_batch')},coupon=True):
            return False
    if not keyword_order_matches(row,q.get('q')):
        if row.get('code') is not None and row.get('promoter') is not None:return False
        missing = True
    return None if missing else True


def safe_detail(raw):
    if not isinstance(raw,str) or not (label := raw.strip()) or len(label)>512:
        return None
    has_scheme = label.lower().startswith(('https://','http://','//'))
    if has_scheme or re.match(r'^[\w.-]+\.[a-zA-Z]{2,}(?:[/?#]|$)',label):
        try:
            url = urlsplit(label if has_scheme else '//'+label)
            host = url.hostname
            if (not url.username and not url.password and host and re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+',host)
                    and re.search(r'\.[a-z]{2,}$',host) and not re.search(r'\d{7,}',host)):
                return host
        except ValueError:
            pass
        return None
    if (len(label)<=80 and re.fullmatch(r'[^\W\d_][\w .-]*',label)
            and not re.search(r'(?:\d[ .-]*){7,}',label)):
        return label
    return None


def private_label(raw):
    if isinstance(raw,str) and len(raw)<=160 and not re.search(r'[@?&=\r\n]|(?:\+?\d[ ().-]*){7,}',raw):
        return raw
    return None


def detail_csv(rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(label for _,label in DETAIL_COLUMNS)
    for row in rows:
        cells = []
        for key,_ in DETAIL_COLUMNS:
            value = row[key]
            if isinstance(value,list):value = '；'.join(value)
            if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) and key not in ('salesUsd','saleCny','costCny','profitCny'):
                value = "'"+value
            cells.append(value)
        writer.writerow(cells)
    return '\ufeff'+output.getvalue()


def breakdown_rows(grouped, denominator, dimension, status):
    results = []
    for label, rows in sorted(grouped.items(),key=lambda item:(-len(item[1]),item[0] or '')):
        summary = summarize(rows)
        evidence = [r['effective_attribution'] for r in rows]
        associations = {}
        for key in ('discount_code','promoter','coupon'):
            associations[key] = dict(known_orders=sum(r.get(key) is True for r in evidence),
                                     unknown_orders=sum(r.get(key) is None for r in evidence))
        associations['coupon_templates'] = association_labels(evidence,'coupon_templates')
        associations['promotion_projects'] = association_labels(evidence,'promotion_project')
        associations['order_sources'] = association_labels(evidence,'order_source')
        summary.update(label=label if label is not None else '未提供',status=status,
            order_share=len(rows)/denominator if denominator else None,associations=associations,
            conflict_orders=sum(r.get('conflict') is True for r in evidence))
        if dimension=='channel':summary.update(channel=label,label=CHANNEL_LABELS[label])
        results.append(summary)
    return results


def association_labels(evidence, key):
    groups = defaultdict(int)
    for record in evidence:
        labels = record.get(key) or []
        if isinstance(labels,str):labels = [labels]
        for label in {safe_detail(value) for value in labels} - {None}:
            groups[label] += 1
    return [dict(label=label,orders=orders) for label,orders in sorted(groups.items(),key=lambda item:(-item[1],item[0]))]


def aggregate_csv(result):
    output = io.StringIO()
    writer = csv.writer(output)
    scope = result['effective_scope']
    writer.writerow(('开始日期','结束日期','站点ID','游戏ID','渠道筛选','时区','时间口径',
                     '快照版本','事实定义','归因定义','来源修订','同单核算口径','未分配到日的订单','占比分母订单',
                     '其他筛选','筛选字段未核订单'))
    writer.writerow((scope['start'],scope['end'],scope['site_id'],scope['gid'],scope['channel'],
                     result['source_timezone'],result['time_basis'],result['snapshot_id'],result['facts_version'],
                     result['attribution_version'],json.dumps(result['revisions'],sort_keys=True),
                     result['totals']['accounting_basis'],result['trend_unallocated_orders'],result['breakdown']['denominator_orders'],
                     json.dumps({**{k:scope[k] for k in FILTERS if k in scope},
                                 **{k:True for k in ('keyword_applied','discount_code_applied','coupon_batch_applied') if result.get(k)}},ensure_ascii=False),
                     result['coverage']['unverified_filter_orders']))
    writer.writerow(('维度','项目','范围状态','已知订单数','已知美元金额','缺美元金额订单数',
                     '已读采购人民币','已核同单毛利人民币','完整成本订单数','订单占比',
                     '有折扣码／未核','有推广人／未核','有优惠券／未核','关联优惠券模板','关联推广项目','关联订单来源'))
    dimension = '来源明细' if result['breakdown']['dimension']=='source_detail' else '渠道'
    for kind, key, rows in ((dimension,'label',result['breakdown']['rows']),('日期','day',result['trend'])):
        for row in rows:
            usd = row['admin_paid_usd'] if row['orders'] != row['missing_admin_usd_orders'] or not row['orders'] else None
            cost = row['observed_cost_cny'] if kind == '日期' or row['cost_records'] else None
            assoc = row.get('associations',{})
            known = [f"{assoc[k]['known_orders']} / {assoc[k]['unknown_orders']}" if k in assoc else None
                     for k in ('discount_code','promoter','coupon')]
            details = ['、'.join(f"{item['label']} ({item['orders']})" for item in assoc.get(k,()))
                       for k in ('coupon_templates','promotion_projects','order_sources')]
            writer.writerow((kind,row[key],row.get('status',result['status']),row['orders'],usd,
                             row['missing_admin_usd_orders'],cost,
                             row['procurement_gross_cny'],row['cost_covered_orders'],row.get('order_share'),*known,*details))
    return '\ufeff' + output.getvalue()


def selection(params):
    allowed = {'mode', 'start', 'end', 'site_id', 'gid', 'channel', 'refresh', *FILTERS}
    if set(params) - allowed or any(not isinstance(v, list) or len(v) != 1 or
            not isinstance(v[0], str) or len(v[0]) > (160 if k in FILTERS else 80) for k,v in params.items()):
        raise ValueError('order_facts_parameters')
    q = {k: v[0] for k, v in params.items()}
    if q.pop('mode', None) != 'order-facts':raise ValueError('order_facts_mode')
    if 'refresh' in q and q['refresh'] != '1':raise ValueError('order_facts_refresh')
    start, end = (date.fromisoformat(q.get(k, '')) for k in ('start', 'end'))
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if (start.isoformat() != q['start'] or end.isoformat() != q['end'] or
            not 0 <= (end-start).days < 28 or end > today or start < today-timedelta(days=365)):
        raise ValueError('order_facts_period')
    for key in ('site_id', 'gid'):
        q.setdefault(key, 'all')
        if q[key] != 'all' and not re.fullmatch(r'[1-9][0-9]{0,9}', q[key]):
            raise ValueError('order_facts_dimension')
    q.setdefault('channel', 'all')
    if q['channel'] not in CHANNELS:raise ValueError('order_facts_channel')
    if q.get('status','all') not in ('all','valid','refund'):raise ValueError('order_facts_status')
    if any(q.get(k) and safe_detail(q[k])!=q[k] for k in ('country','payment','project')):
        raise ValueError('order_facts_filter_label')
    if 'coupon_template' in q and not re.fullmatch(r'[0-9]{1,12}',q['coupon_template']):
        raise ValueError('order_facts_coupon_template')
    if 'code' in q:q['code'] = q['code'].strip().casefold()
    return q


def public(data, q, games=(), *, detail_rows=None, snapshot_binding=None):
    """Never copy raw inputs, original order keys, or arbitrary source metadata."""
    scope = {k: q[k] for k in ('start', 'end', 'site_id', 'gid')}
    if any(data.get('input_scope', {}).get(k) != v for k, v in scope.items()):
        raise ValueError('order_facts_source_scope')
    rows = data['orders']
    selected = []
    groups, details, daily = defaultdict(list), defaultdict(list), defaultdict(list)
    unknown_days = set()
    unallocated = unverified_filters = 0
    filter_options = defaultdict(set)
    specific_channel = q['channel'] not in ('all',*UNCLASSIFIED)
    for row in rows:
        effective = row.get('effective_attribution')
        if effective is None:
            detail = row['marketing_attribution'].get('source_raw') if row['channel']!='unknown' else None
            effective = dict(channel=row['channel'],detail=detail)
        channel = effective['channel']
        row = dict(row,channel=channel,effective_attribution=effective)
        observed = effective.get('filter_row') or {}
        for key in ('country','payment','project'):
            if (label := safe_detail(observed.get(key))) and label==observed[key]:filter_options[key].add(label)
        for coupon in observed.get('coupons') or ():
            if re.fullmatch(r'[0-9]{1,12}',str(coupon.get('templateId',''))) and (title := safe_detail(coupon.get('title'))):
                filter_options['coupon_templates'].add((coupon['templateId'],title))
        matching = matches_tracking_filters(effective,q)
        if matching is not True:
            if matching is None and (q['channel'] in ('all',channel) or specific_channel and channel in UNCLASSIFIED):
                unverified_filters += 1
            continue
        match = q['channel'] == 'all' or channel == q['channel']
        if not match and not (specific_channel and channel in UNCLASSIFIED):
            continue
        try:
            paid_at = datetime.strptime(row['paid_at'], '%Y-%m-%d %H:%M:%S')
            day = paid_at.date().isoformat()
            if not q['start'] <= day <= q['end']:
                day = None
        except (TypeError, ValueError):
            day = None
        if match:
            selected.append(row)
            if detail_rows is not None:
                raw = effective.get('filter_row') or {}
                detail_rows.append(dict(paidAt=row['paid_at'],orderNo=row['order_no'],gid=row['gid'],game=row['game'],
                    channel=CHANNEL_LABELS[channel],source=safe_detail(effective.get('detail')),project=safe_detail(effective.get('promotion_project')),
                    code=private_label(raw.get('code')),promoter=private_label(raw.get('promoter')),
                    coupons=None if raw.get('coupons') is None else [(safe_detail(c.get('title')) or '券名称未提供') for c in raw['coupons']],
                    country=safe_detail(raw.get('country')),payment=safe_detail(raw.get('payment')),
                    salesUsd=row['admin_paid_usd'],saleCny=row['admin_paid_cny'],
                    costCny=row['observed_cost_cny'] if row['cost_records'] else None,profitCny=row['procurement_gross_cny'],status=row['status']))
            groups[channel].append(row)
            if q['channel']!='all':details[safe_detail(effective.get('detail'))].append(row)
            if day:
                daily[day].append(row)
            else:
                unallocated += 1
        if channel in UNCLASSIFIED:
            unknown_days.add(day)
    # Coverage counts describe the source cohort; totals describe the selection.
    coverage = {k: v for k, v in data.get('coverage', {}).items()
                if k in ('linked_orders', 'unlinked_admin_rows', 'unlinked_attribution_rows',
                         'unlinked_cost_records', 'duplicate_admin_rows', 'duplicate_cost_rows')
                and type(v) is int and v >= 0}
    source = data.get('source_coverage', {})
    revisions = {k: source[k] for k in ('source_revision', 'data_revision', 'publication_id')
                 if type(source.get(k)) in (str, int)}
    cost = source.get('cost', {})
    revisions['cost'] = {k:cost[k] for k in ('source_revision','generated_at','status')
                         if isinstance(cost.get(k),str)}
    revisions['cost']['period'] = {k:v for k,v in (cost.get('period') or {}).items()
                                    if k in ('start','end','until') and isinstance(v,str)}
    revisions['cost']['order_cost_complete'] = cost.get('order_cost_complete') is True
    revisions['cost']['shipment_window_complete'] = cost.get('shipment_window_complete') is True
    attribution = source.get('attribution', {})
    revisions['attribution'] = {k: attribution[k] for k in
        ('source_revision', 'data_revision', 'publication_id', 'identity_revision', 'available_at')
        if type(attribution.get(k)) in (str, int)}
    if 'effective_attribution' in source:
        proof = source['effective_attribution']
        revisions['effective_attribution'] = {k:proof[k] for k in ('rule','mapping_revision') if isinstance(proof.get(k),str)}
        revisions['effective_attribution']['day_revisions'] = {day:digest for day,digest in proof.get('day_revisions',{}).items()
            if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',day) and re.fullmatch(r'[a-f0-9]{64}',digest)}
    bridge = {k: v for k, v in attribution.get('bridge_counts', {}).items()
              if k in ('linked', 'identity_coverage_unverified', 'cross_site_ambiguous',
                       'identity_unmatched', 'site_label_unverified', 'order_status_revision_mismatch') and type(v) is int and v >= 0}
    coverage['attribution'] = dict(
        status=attribution.get('status') if attribution.get('status') in
            ('available', 'partial', 'unavailable') else 'unavailable',
        identity_status='complete' if attribution.get('identity_status') == 'complete' else 'unverified',
        bridge_counts=bridge)
    coverage['unverified_filter_orders'] = unverified_filters
    admin_complete = source.get('admin_complete') is True and data['status'] == 'available' and not unverified_filters
    trend = []
    day = date.fromisoformat(q['start'])
    end = date.fromisoformat(q['end'])
    while day <= end:
        key = day.isoformat()
        summary = summarize(daily[key])
        orders = summary['orders']
        complete = admin_complete and not unallocated and not (specific_channel and (key in unknown_days or None in unknown_days))
        missing_usd = summary['missing_admin_usd_orders']
        missing_cny = summary['missing_admin_cny_orders']
        # Zero means a known empty day or known zero amounts. Missing data stays blank.
        usd_known = orders > missing_usd if orders else complete
        cny_known = orders > missing_cny if orders else complete
        trend.append(dict(day=key, orders=orders,
            status='available' if complete and not (missing_usd or missing_cny) else 'partial',
            admin_paid_usd=summary['admin_paid_usd'] if usd_known else None,
            admin_paid_cny=summary['admin_paid_cny'] if cny_known else None,
            missing_admin_usd_orders=missing_usd, missing_admin_cny_orders=missing_cny,
            observed_cost_cny=summary['observed_cost_cny'] if summary['cost_records'] else None,
            procurement_gross_cny=summary['procurement_gross_cny'],
            cost_covered_orders=summary['cost_covered_orders'],
            gross_covered_orders=summary['gross_covered_orders']))
        day += timedelta(days=1)
    status = data['status']
    if status == 'available' and any(row['status'] == 'partial' for row in trend):status = 'partial'
    channel_rows = breakdown_rows(groups,len(selected),'channel',status)
    breakdown = dict(dimension='channel' if q['channel']=='all' else 'source_detail',denominator_orders=len(selected),
                     rows=channel_rows if q['channel']=='all' else breakdown_rows(details,len(selected),'source_detail',status))
    result = dict(version=VERSION, facts_version=data['version'],
                attribution_version=data['attribution_version'], status=status,
                requested_scope={k:v for k,v in q.items() if k not in ('q','code','coupon_batch')},
                effective_scope={**scope,'channel':q['channel'],**{k:q[k] for k in FILTERS if k in q and k not in ('q','code','coupon_batch')}},
                channel_filter='derived_order_facts', coverage_scope=scope,
                totals=summarize(selected),
                channels=channel_rows,breakdown=breakdown,
                trend=trend, trend_unallocated_orders=unallocated, coverage=coverage, revisions=revisions,
                source_timezone='Asia/Shanghai', time_basis='Admin paytime',
                captured_at=source.get('captured_at'), options={'games':deepcopy(list(games)),
                    **{k:sorted(values) for k,values in filter_options.items()}},
                admin_complete=source.get('admin_complete') is True and not unverified_filters,
                readonly=True, private=True)
    for key, flag in (('q','keyword_applied'),('code','discount_code_applied'),('coupon_batch','coupon_batch_applied')):
        if key in q:result[flag]=True
    if source.get('admin_snapshot') is True:
        result['source_snapshot'] = True
        coverage['missing_days'] = [day for day in source.get('missing_days',())
            if isinstance(day,str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',day)]
    revision_input = {k: v for k, v in result.items() if k not in ('options','captured_at')}
    if snapshot_binding:
        revision_input['authorization_and_scope'] = snapshot_binding
        revision_input['detail_revision'] = hashlib.sha256(json.dumps(detail_rows,sort_keys=True).encode()).hexdigest()
    result['snapshot_id'] = 'order-facts-' + hashlib.sha256(
        json.dumps(revision_input, sort_keys=True).encode()).hexdigest()[:24]
    result['aggregate_csv'] = aggregate_csv(result)
    return result


class OrderFactsService:
    def __init__(self, channels, source, clock=time.monotonic, *, games=()):
        self.channels, self.source, self.clock = channels, source, clock
        self.games = deepcopy(list(games))
        self.entries = {}

    def capture(self, key, q):
        detail_rows = []
        details = None
        try:
            with self.channels.admission():
                value = public(self.source({k: q[k] for k in ('start', 'end', 'site_id', 'gid')}), q, self.games,
                               detail_rows=detail_rows,snapshot_binding=key)
            detail_rows.sort(key=lambda row:(row['paidAt'] or '',row['orderNo']),reverse=True)
            details = gzip.compress(json.dumps(detail_rows,ensure_ascii=False).encode(),compresslevel=1)
            state = 'available'
        except PermissionError:
            value, state = None, 'denied'
        except BlockingIOError:
            value, state = None, 'deferred'
        except Exception:
            # Exception messages may contain upstream original order identifiers.
            value, state = None, 'source_failed'
        with self.channels.lock:
            self.entries[key].update(state=state, value=value, finished=self.clock(),
                                     details=details)
            self.channels.jobs.pop(key, None)

    def detail(self, key, snapshot_id, page, export):
        with self.channels.lock:
            entry = self.entries.get(key)
            if (not entry or entry['state']!='available' or not 0 <= self.clock()-entry['finished'] < 600
                    or entry['value']['snapshot_id']!=snapshot_id):
                return 409, {'status':'snapshot_expired','error':'order_facts_snapshot_expired'}
            payload = entry['details']
        rows = json.loads(gzip.decompress(payload))
        if export:
            return 200, dict(version=VERSION,snapshot_id=snapshot_id,total=len(rows),detail_csv=detail_csv(rows))
        pages = max(1,(len(rows)+49)//50)
        page = min(page,pages)
        return 200, dict(version=VERSION,snapshot_id=snapshot_id,page=page,pages=pages,
                         total=len(rows),orders=rows[(page-1)*50:page*50])

    def get(self, params, user):
        if not user or not self.channels.authorizer(user):
            return 403, {'status': 'denied', 'error': 'admin_required'}
        if any(k in params for k in ('detail_page','detail_export','snapshot_id')):
            detail_page = params.get('detail_page',['1'])
            snapshot_id = params.get('snapshot_id')
            detail_export = params.get('detail_export') == ['1']
            if (not isinstance(detail_page,list) or len(detail_page)!=1 or not isinstance(detail_page[0],str)
                    or not re.fullmatch(r'[1-9][0-9]{0,5}',detail_page[0])
                    or not isinstance(snapshot_id,list) or len(snapshot_id)!=1 or not isinstance(snapshot_id[0],str)
                    or not re.fullmatch(r'order-facts-[a-f0-9]{24}',snapshot_id[0]) or 'refresh' in params
                    or ('detail_export' in params and (not detail_export or 'detail_page' in params))
                    or not (detail_export or 'detail_page' in params)):
                raise ValueError('order_facts_detail_parameters')
            q = selection({k:v for k,v in params.items() if k not in ('detail_page','detail_export','snapshot_id')})
        else:
            q = selection(params)
            detail_page = None
        force = q.pop('refresh', None) == '1'
        key = 'order-facts:' + hashlib.sha256(json.dumps([user, q], sort_keys=True).encode()).hexdigest()
        if detail_page:
            return self.detail(key,snapshot_id[0],int(detail_page[0]),detail_export)
        with self.channels.lock:
            now = self.clock()
            entry = self.entries.get(key)
            if entry and entry['state'] == 'pending':return 202, {'status': 'pending', 'retryAfter': 3}
            if entry and entry['state'] == 'available' and 0 <= now-entry['finished'] < 600:
                if not force:return 200, deepcopy(entry['value'])
                if now-entry['finished'] < 60:
                    return 200, dict(deepcopy(entry['value']), refresh_deferred=True,
                        refresh_reason='recent_capture', retryAfter=math.ceil(60-(now-entry['finished'])))
            if entry and entry['state'] != 'available' and 0 <= now-entry['finished'] < 60:
                code = 403 if entry['state'] == 'denied' else 503
                return code, {'status': entry['state'], 'retryAfter': math.ceil(60-(now-entry['finished']))}
            active = sum(v in ACTIVE for v in self.channels.jobs.values()) + sum(
                v in ACTIVE for v in getattr(self.channels, 'actual_jobs', {}).values())
            if active >= 2:
                if force and entry and entry['state'] == 'available':
                    return 200, dict(deepcopy(entry['value']), refresh_deferred=True,
                        refresh_reason='shared_workers_busy', retryAfter=10)
                return 429, {'status': 'busy', 'retryAfter': 10}
            if key not in self.entries and len(self.entries) >= 32:
                victim = next((k for k, v in self.entries.items() if v['state'] != 'pending'), None)
                if victim is None:return 429, {'status': 'busy', 'retryAfter': 10}
                self.entries.pop(victim)
            try:
                with self.channels.admission():
                    self.entries[key] = dict(state='pending', started=now)
                    self.channels.jobs[key] = 'pending'
                    self.channels.pool.submit(self.capture, key, deepcopy(q))
            except Exception as error:
                self.channels.jobs.pop(key, None)
                state = 'deferred' if isinstance(error, BlockingIOError) else 'source_failed'
                self.entries[key] = dict(state=state, started=now, finished=now, value=None)
                return 503, {'status': state, 'retryAfter': 60}
        return 202, {'status': 'pending', 'retryAfter': 3}
