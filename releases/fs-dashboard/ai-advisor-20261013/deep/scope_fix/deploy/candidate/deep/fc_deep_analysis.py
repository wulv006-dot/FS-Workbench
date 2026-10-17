"""Deterministic FC evidence; only aggregate facts leave the trusted source boundary."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math

CONTRACT = 'fc-evidence-analysis-v1'
SHANGHAI = timezone(timedelta(hours=8))
FIELDS = ('orders', 'revenue_usd', 'unpriced_orders', 'issues', 'unfinished', 'funding', 'completed')
DIMENSIONS = ('platform', 'product', 'bucket')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def dates(lo, hi):
    return [(lo + timedelta(days=i)).isoformat() for i in range((hi-lo).days+1)]


def plan(start, end, at):
    """One shared capture supplies all windows; partial today never enters full-day comparisons."""
    if at.tzinfo is None:
        raise ValueError('timezone_required')
    today = at.astimezone(SHANGHAI).date()
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    if start != lo.isoformat() or end != hi.isoformat() or lo > hi or hi > today or lo < today-timedelta(days=365):
        raise ValueError('invalid_period')
    if (hi-lo).days >= 93:
        raise ValueError('deep_period_limit')
    complete_end = min(hi, today-timedelta(days=1))
    windows = [{'key': 'target', 'start': start, 'end': end, 'kind': 'requested', 'complete_days': hi < today}]
    if complete_end >= lo:
        if hi == today:
            windows.append({'key': 'observed', 'start': start, 'end': complete_end.isoformat(), 'kind': 'complete_portion', 'complete_days': True})
        n = (complete_end-lo).days+1
        windows.append({'key': 'previous', 'start': (lo-timedelta(days=n)).isoformat(), 'end': (lo-timedelta(days=1)).isoformat(), 'kind': 'equal_length', 'complete_days': True})
        if n == 1:
            windows += [
                {'key': 'week_ago', 'start': (lo-timedelta(days=7)).isoformat(), 'end': (lo-timedelta(days=7)).isoformat(), 'kind': 'same_weekday', 'complete_days': True},
                {'key': 'baseline7', 'start': (lo-timedelta(days=7)).isoformat(), 'end': (lo-timedelta(days=1)).isoformat(), 'kind': 'daily_mean', 'complete_days': True},
                {'key': 'baseline30', 'start': (lo-timedelta(days=30)).isoformat(), 'end': (lo-timedelta(days=1)).isoformat(), 'kind': 'daily_mean', 'complete_days': True},
            ]
    floor = (today-timedelta(days=365)).isoformat()
    for w in windows:
        w['within_history'] = w['start'] >= floor
        w['days'] = (date.fromisoformat(w['end'])-date.fromisoformat(w['start'])).days+1
    read_start = min(w['start'] for w in windows if w['within_history'])
    return {'contract': CONTRACT, 'timezone': 'Asia/Shanghai', 'start': start, 'end': end,
            'in_progress': hi == today, 'comparison_target': 'observed' if hi == today else 'target',
            'read_start': read_start, 'read_end': end, 'windows': windows,
            'limits': {'captures': 1, 'order_pages': 3, 'order_samples': 12, 'model_calls': 1}}


def metric_facts(raw):
    out = {}
    for key in FIELDS:
        value = raw.get(key)
        if value is not None and (not number(value) or value < 0 or key != 'revenue_usd' and int(value) != value):
            raise ValueError('invalid_fact')
        out[key] = value
    if out['unpriced_orders'] is None or out['unpriced_orders'] > 0:
        out['revenue_usd'] = None
    n, amount = out['orders'], out['revenue_usd']
    out['average_order_usd'] = rounded(Decimal(str(amount))/n) if n and amount is not None else None
    for key in ('issues', 'unfinished'):
        count = out[key]
        out[key+'_share_pct'] = rounded(Decimal(count)*100/n) if n and count is not None else None
    return out


def backlog_age_bands(rows, observed_at):
    bands = Counter({'under24h': 0, '24to72h': 0, '72to168h': 0, 'over168h': 0, 'unknown': 0})
    for row in rows:
        paid = row.get('paid_at')
        age = (observed_at-datetime.fromisoformat(paid)).total_seconds()/3600 if paid else None
        key = 'unknown' if age is None or age < 0 else 'under24h' if age < 24 else '24to72h' if age < 72 else '72to168h' if age < 168 else 'over168h'
        bands[key] += 1
    return dict(bands)


def age_observation(bands, population):
    labels={'under24h':'不足一天组','24to72h':'一天至不足三天组','72to168h':'三天至不足一周组','over168h':'至少一周组','unknown':'账龄未知组'}
    total=sum(bands.values())
    if not total:return population+'为空'
    maximum=max(bands.values());leaders=[labels[k] for k in labels if bands[k]==maximum]
    text=population+'中，'+'、'.join(leaders)+('并列最多' if len(leaders)>1 else '数量最多')
    if len(leaders)==1:text+='且'+('超过该群体一半' if maximum*2>total else '未超过该群体一半')
    return text


def build_evidence(query_plan, dataset, config, at):
    """Dataset is the existing normalized server cache, never projected wholesale."""
    from fc_detail_model import aggregate, facts, amount_bucket
    coverage = dataset['coverage']
    cp = coverage['period']
    expected_end=(date.fromisoformat(query_plan['read_end'])+timedelta(days=1)).isoformat()+' 00:00'
    if cp['start'] != query_plan['read_start']+' 00:00' or (not query_plan['in_progress'] and cp['end']!=expected_end) or query_plan['in_progress'] and not query_plan['read_end']+' 00:00'<=cp['end']<expected_end:
        raise ValueError('capture_period_mismatch')
    if not dataset['snapshot_id'].startswith('fc-detail-'):
        raise ValueError('capture_identity')
    scope = fingerprint({'contract': 'fc27-detail-analytics-v1', 'site_rule': coverage.get('site_rule'),
                         'distribution': config['distribution_identification'], 'config': config})
    missing_days = set(coverage.get('missing_days', []))
    observed_days = dates(date.fromisoformat(query_plan['read_start']), date.fromisoformat(query_plan['read_end']))
    book, windows = [], []

    def add(ref, kind, value, **extra):
        entry = {'ref': ref, 'kind': kind, 'value': value, 'source': 'Admin FC支付明细',
                 'snapshot_id': dataset['snapshot_id'], 'captured_at': dataset['as_of'], 'scope_fingerprint': scope, **extra}
        book.append(entry)
        return entry

    for w in query_plan['windows']:
        allowed = w['within_history'] and not missing_days.intersection(dates(date.fromisoformat(w['start']), date.fromisoformat(w['end'])))
        allowed = allowed and not coverage.get('missing_payment_time') and not coverage.get('unknown_scope_orders')
        # Absence of an explicit complete/partial-days contract cannot imply zero orders.
        allowed = allowed and (coverage.get('paid_complete') is True or bool(missing_days))
        if not allowed:
            windows.append({**w, 'status': 'missing', 'reason': 'outside_history' if not w['within_history'] else 'incomplete_capture'})
            continue
        q = {'start': w['start'], 'end': w['end'], 'site_group': 'main', 'page': '1'}
        view = aggregate(dataset, q, config, now=at)
        main, satellite = (metric_facts(next(r for r in view['site_groups'] if r['key'] == group)) for group in ('main', 'satellite'))
        dims = {key: [{'key': r['key'], **metric_facts(r)} for r in view['dimensions'][key]] for key in ('platform', 'product')}
        dims['bucket'] = [{'key': r['key'], 'label': r['label'], **metric_facts(r)} for r in view['buckets']]
        item = {**w, 'status': 'available', 'main': main, 'satellite': satellite, 'dimensions': dims}
        windows.append(item)
        add(w['key']+'.main', 'period_facts', main, period={k: w[k] for k in ('start', 'end')}, scope='MMOEXP主站',
            complete_days=w['complete_days'], state_basis='读取时的当前订单状态，不是历史日末状态')
        add(w['key']+'.satellite', 'period_facts', satellite, period={k: w[k] for k in ('start', 'end')}, scope='已配置卫星站汇总')
        if w['key'] in ('target', 'observed', 'previous'):
            for key in DIMENSIONS:
                add(w['key']+'.'+key, 'dimension', dims[key], scope='MMOEXP主站', dimension=key)

    by_key = {w['key']: w for w in windows}
    target = by_key.get(query_plan['comparison_target'])
    comparisons = []
    if target and target['status'] == 'available' and target['complete_days']:
        for baseline in windows:
            if baseline['key'] in ('target', 'observed') or baseline['status'] != 'available':
                continue
            divisor = baseline['days'] if baseline['kind'] == 'daily_mean' else 1
            values = {}
            for field in ('orders', 'revenue_usd', 'average_order_usd'):
                current, before = target['main'][field], baseline['main'][field]
                if current is None or before is None:
                    values[field] = None
                    continue
                # Baseline AOV is total revenue / total orders, not mean of daily AOVs.
                base = Decimal(str(before))/(1 if field == 'average_order_usd' else divisor)
                delta = Decimal(str(current))-base
                values[field] = {'current': current, 'baseline': rounded(base), 'delta': rounded(delta),
                                 'pct': rounded(delta*100/base) if base else None, 'zero_baseline': not bool(base)}
            item = {'target': target['key'], 'baseline': baseline['key'], 'baseline_kind': baseline['kind'], 'values': values}
            comparisons.append(item)
            add('compare.'+baseline['key'], 'comparison', item, scope='MMOEXP主站',
                note='只比较支付订单/销售/客单，不比较不同成熟期订单的当前履约比例')

    contributions = []
    prior = by_key.get('previous')
    if target and prior and target['status'] == prior['status'] == 'available':
        for dim in DIMENSIONS:
            old = {r['key']: r for r in prior['dimensions'][dim]}
            cur = {r['key']: r for r in target['dimensions'][dim]}
            rows = []
            for key in sorted(set(old)|set(cur)):
                a, b = cur.get(key, {}).get('revenue_usd', 0), old.get(key, {}).get('revenue_usd', 0)
                if a is None or b is None:
                    continue
                rows.append({'key': key, 'label': cur.get(key,old.get(key,{})).get('label',key),
                             'current_revenue_usd': a, 'previous_revenue_usd': b,
                             'revenue_delta_usd': rounded(Decimal(str(a))-Decimal(str(b))),
                             'orders_delta': cur.get(key, {}).get('orders', 0)-old.get(key, {}).get('orders', 0)})
            rows.sort(key=lambda r: (-abs(r['revenue_delta_usd']), r['key']))
            contributions.append({'dimension': dim, 'rows': rows})
            add('contribution.'+dim, 'arithmetic_contribution', rows, scope='MMOEXP主站',
                note='金额变化的算术分解，不代表原因或策略效果')

    backlog_rows = [r for r in dataset.get('backlog', []) if r.get('site_group') in ('main', 'satellite') and not r.get('terminal')]
    backlog = None
    if coverage.get('backlog_status') == 'available':
        observed_at=datetime.fromisoformat(dataset['as_of'])
        main_rows = [r for r in backlog_rows if r['site_group'] == 'main']
        age_bands = backlog_age_bands(main_rows, observed_at)
        issue_rows = [r for r in main_rows if r.get('issue')]
        issue_age_bands = backlog_age_bands(issue_rows, observed_at)
        backlog = {'main': metric_facts(facts(main_rows)), 'age_bands': age_bands,
                   'age_bands_scope': 'MMOEXP主站全部当前未终结订单',
                   'issue_age_bands': issue_age_bands,
                   'issue_age_bands_scope': 'MMOEXP主站当前未终结且标记问题的订单子集',
                   'verified_observation': age_observation(age_bands, '全部当前未结订单')+'；'+age_observation(issue_age_bands, '其中的问题单子集')+'。这是跨支付日的当前观察，不等于目标日新增，也不能证明积压增长。',
                   'satellite': metric_facts(facts([r for r in backlog_rows if r['site_group'] == 'satellite'])),
                   'as_of': dataset['as_of'], 'basis': '全部支付日期、当前未终结池；年龄从支付时算'}
        add('backlog.current', 'current_open_pool', backlog, scope='主站与卫星分开', note='当前库存，不能直接归因于所选支付期间；没有历史池快照不能声称积压增长')

    trace = [{'tool': 'existing_fc_detail', 'start': query_plan['read_start'], 'end': query_plan['read_end'],
              'snapshot_id': dataset['snapshot_id'], 'captured_at': dataset['as_of'], 'requested_days': len(observed_days),
              'missing_days': sorted(missing_days), 'status': dataset.get('data_status')}]
    gaps = ['独立分销组缺可靠业务归属字段；当前统计不声称已完整剔除。',
            '新老客标记未验证；不推算新客、复购或跨日去重人数。',
            '缺同口径成本与费用分配，不能用全站优惠或参考利润率推算FC真实利润。',
            '履约状态是当前观察，不是等成熟度快照；不能据此判断历史履约趋势。']
    for w in windows:
        if w['status'] != 'available':
            gaps.append(w['key']+' 对比数据不完整，需要补齐 '+w['start']+' 至 '+w['end']+' 的支付记录。')
    if query_plan['in_progress']:
        gaps.append('含今天的目标期未结束；趋势只比较已经完成的自然日。')
    if backlog is None:
        gaps.append('当前未完成池不完整，不能估计积压总量。')
    result = {'contract': CONTRACT, 'project': 'FC27', 'plan': query_plan, 'generated_at': at.isoformat(),
              'scope_fingerprint': scope, 'currency': 'USD', 'snapshot_id': dataset['snapshot_id'],
              'windows': windows, 'comparisons': comparisons, 'contributions': contributions, 'backlog': backlog,
              'evidence': book, 'trace': trace, 'gaps': gaps, 'diagnostics': {'status': 'not_run'}}
    result['investigations'] = investigations(result)
    return result


def investigations(result):
    jobs = []
    previous = next((x for x in result['comparisons'] if x['baseline'] == 'previous'), None)
    if previous:
        values = previous['values']; r, n, a = (values.get(k) for k in ('revenue_usd', 'orders', 'average_order_usd'))
        if r and abs(r['pct'] or 0) >= 10:
            jobs.append({'kind': 'sales_structure', 'priority': 'P1', 'refs': ['compare.previous', 'contribution.platform', 'contribution.product'],
                         'question': '销售变化主要集中在哪个平台/品类，是订单量还是客单结构变化？', 'status': 'evidence_ready'})
    backlog = result.get('backlog')
    target = next((x for x in result['windows'] if x['key'] == 'target' and x['status'] == 'available'), None)
    if backlog and (backlog['main']['issues'] or sum(backlog['age_bands'][k] for k in ('72to168h', 'over168h'))) or target and target['main']['issues']:
        jobs.append({'kind': 'order_problem_sample', 'priority': 'P1', 'refs': ['backlog.current'] if backlog else ['target.main'],
                     'question': '主站FC当前问题单有哪些可核查日志线索，哪些订单需要人工确认下一步？', 'status': 'needs_readonly_tool',
                     'limits': {'pages': 3, 'samples': 12}, 'scope': 'Order FC27 / www.mmoexp.com / 当前问题单'})
    return jobs


def attach_diagnostics(result, diagnostics):
    result['diagnostics'] = diagnostics
    for item in result['investigations']:
        if item['kind']=='order_problem_sample':
            item['status']='evidence_ready' if diagnostics.get('status') in ('available','partial') else 'unavailable'
    result['trace'].append({'tool': 'order_problem_sample', **{k: diagnostics.get(k) for k in ('status', 'captured_at', 'sampled', 'listed', 'pages', 'coverage')}})
    if diagnostics.get('status') in ('available', 'partial'):
        result['evidence'].append({'ref': 'order.problem_sample', 'kind': 'sample_clues', 'source': 'Order订单只读列表与日志',
                                  'scope': 'FC27 MMOEXP主站当前问题单抽样', 'captured_at': diagnostics['captured_at'],
                                  'value': {k: diagnostics.get(k) for k in ('sampled', 'listed', 'pages', 'categories', 'coverage', 'platform_counts')},
                                  'note': '固定有界样本；不是总体原因比例，不证明根因，也不等于已解决。'})
    else:
        result['gaps'].append('Order问题单日志未完成读取：'+str(diagnostics.get('reason', diagnostics.get('status')))+'；原因判断待核查。')
    return result


def fallback(result):
    """Actionable deterministic output remains if the provider fails; no invented causation."""
    findings = []
    for item in result['investigations']:
        if item['kind'] == 'sales_structure':
            findings.append({'priority': 'P1', 'type': 'fact', 'title': '销售结构值得先排查',
                             'observation': '同口径销售金额出现明显变化，先查看变化贡献最大的主站平台和品类。',
                             'refs': item['refs'], 'hypothesis': '尚不能确认是流量、商品供给、价格还是活动影响。',
                             'action': '项目负责人核对贡献最大的分组，补查该分组流量、可售状态和活动记录，再决定是否调整策略。',
                             'condition': '仅对已完成自然日且来源完整的对比使用。',
                             'risk': '订单结构变化可能抬高或压低客单；未核对利润前不宜扩大优惠。',
                             'verify': {'metric': 'revenue_usd', 'direction': 'review', 'window_days': 3}})
        elif item['kind'] == 'order_problem_sample':
            findings.append({'priority': 'P1', 'type': 'hypothesis', 'title': '先清查可处理的问题单',
                             'observation': '当前问题单或长等待订单需要核查，历史支付日与当前问题池分别展示。',
                             'refs': item['refs']+(['order.problem_sample'] if any(e['ref']=='order.problem_sample' for e in result['evidence']) else []),
                             'hypothesis': '日志分类只是待确认的处理线索，未证明全部订单的共同原因。',
                             'action': '客服负责人从抽样证据入口复核最新状态，先处理能补齐资料或确认交易条件的订单，再复查是否仍卡住。',
                             'condition': '原订单仍为问题状态，且最新记录确认相应障碍仍存在。',
                             'risk': '客户信息变动或旧日志已经失效；不能按旧线索批量操作。',
                             'verify': {'metric': 'backlog_issues', 'direction': 'decrease', 'window_days': 1}})
    if not findings:
        findings.append({'priority': 'P2', 'type': 'fact', 'title': '先建立可复盘的观察基线',
                         'observation': '当前证据尚未支持优先级更高的异常判断。', 'refs': [e['ref'] for e in result['evidence'] if e['ref']=='target.main'],
                         'hypothesis': '缺少流量、同口径利润与策略事件记录，暂不能评价增长质量或活动效果。',
                         'action': '项目负责人补充本期活动与目标，按同口径观察销售与订单结构，再决定是否追加行动。',
                         'condition': '先确认来源覆盖完整。', 'risk': '不得把没有异常证据解释为业务没有问题。',
                         'verify': {'metric': 'revenue_usd', 'direction': 'review', 'window_days': 7}})
    return {'status': 'deterministic', 'findings': findings[:3], 'note': '规则生成的待人工核查建议；模型解读未成功时保留。'}
