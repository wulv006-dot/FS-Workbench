"""As-of lifecycle, interval events, project migration and mature second purchases."""
from collections import defaultdict
from datetime import datetime, timedelta
from bisect import bisect_left, bisect_right
from decimal import Decimal
import json

from user_contract import TZ, STATES, stamp, state, OBSERVATION_POLICIES


def covered(jobs, sites, start, end):
    if start >= end:
        return True
    for site in sites:
        cursor = start
        for job in sorted((j for j in jobs if j['site'] == site and j['state'] == 'complete'), key=lambda j: j['start']):
            a, b = stamp(job['start']), stamp(job['end'])
            if a <= cursor < b:
                cursor = b
            if cursor >= end:
                break
        if cursor < end:
            return False
    return True


def in_scope(row, query, config):
    scope, ident = query['scope'], query['scope_id']
    return (scope == 'global' or scope == 'site' and row['site'] == ident
            or scope == 'project' and row['gid'] == ident
            or scope == 'series' and config['projects'].get(row['gid'], {}).get('series') == ident)


def origin(query, config):
    return config.get('history_origins', {}).get(query['scope'] + ':' + query['scope_id']) or config.get('available_history_origin')


def metric(value, status='available', **extra):
    return dict(value=value, status=status, unit='customers', **extra)


def coverage_runs(jobs, sites):
    result = {}
    for site in sites:
        merged = []
        for job in sorted((j for j in jobs if j['site'] == site and j['state'] == 'complete'), key=lambda j: j['start']):
            a, b = stamp(job['start']), stamp(job['end'])
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        result[site] = merged
    return result


PATH_LABELS = {'no_purchase': '期间一直未再购买', 'purchased_then_inactive': '期间买过，随后沉睡或流失',
               'returned_then_inactive': '期间唤醒或回流过，随后再次沉睡或流失',
               'returned_active': '期间唤醒或回流，目前仍近期购买',
               'purchased_active': '期间买过，目前仍近期购买', 'observed_after_period': '期间无购买，之后才观察到购买', 'unverified': '变化待核'}


def daily_stocks(people, runs, start, end, points, period_cohort=False):
    """Sweep purchase/threshold boundaries instead of rescanning the full pool for every day."""
    days = []
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        days.append((cursor, min(cursor + timedelta(days=1), end)))
        cursor += timedelta(days=1)
    finishes = [b for _, b in days]
    changes = {key: [0] * (len(days) + 1) for key in (*STATES, 'unverified')}
    if period_cohort:
        changes['waiting'] = [0] * (len(days) + 1)
    def add(key, lo, hi):
        if lo < hi:
            changes[key][lo] += 1; changes[key][hi] -= 1
    for rows in people.values():
        times = [stamp(r['paid_at']) for r in rows]
        for index in range(max(0,bisect_right(times,start)-1),len(times)):
            last = times[index]
            lo = bisect_right(finishes, last)
            hi = bisect_right(finishes, times[index + 1]) if index + 1 < len(times) else len(days)
            if lo >= hi:
                continue
            coverage_end = min((next((b for a, b in intervals if a <= last < b), last) for intervals in runs.values()), default=last)
            reliable = min(hi, bisect_right(finishes, coverage_end))
            boundaries = [lo, *[max(lo, min(reliable, bisect_right(finishes, datetime.combine(last.date() + timedelta(days=p), datetime.min.time(), TZ)))) for p in points], reliable]
            for key, a, b in zip(STATES, boundaries, boundaries[1:]):
                add('waiting' if period_cohort and not index and key == 'recent' else key, a, b)
            add('unverified', max(lo, reliable), hi)
    stock, result = {key: 0 for key in changes}, {}
    for index, (day, _) in enumerate(days):
        for key in stock:
            stock[key] += changes[key][index]
        result[day.date()] = dict(stock)
    return result


def analyze(orders, jobs, query, config, details=True):
    start, cutoff = stamp(query['start']), stamp(query['as_of'])
    end = min(stamp(query['end_exclusive']), cutoff)
    current = query.get('state_basis') == 'current'
    period_cohort = query.get('state_basis') == 'period_cohort'
    observation = (cutoff if current else cutoff - timedelta(microseconds=1)).date()
    points = config['policies'][query['policy_version']]
    sites = [query['scope_id']] if query['scope'] == 'site' else list(config['sites'])
    runs = coverage_runs(jobs, sites)
    def covers(a, b):
        return a >= b or all(any(lo <= a and b <= hi for lo, hi in intervals) for intervals in runs.values())
    groups = {config['sites'][s].get('verified_identity_group') for s in sites}
    identity_complete = len(sites) == 1 or len(groups) == 1 and None not in groups and '' not in groups
    data_through = min((max((b for a, b in intervals), default=cutoff) for intervals in runs.values()), default=cutoff)
    state_through = min(cutoff, data_through) if current else cutoff
    pool = [r for r in orders if r['valid'] and stamp(r['paid_at']) < cutoff and (not period_cohort or stamp(r['paid_at']) >= start) and r['site'] in sites]
    selected = [r for r in pool if in_scope(r, query, config)]
    people = defaultdict(list)
    for row in selected:
        if row['customer_id']:
            people[row['customer_id']].append(row)
    period_complete = covers(start, end)
    missing_identity = sum(start <= stamp(r['paid_at']) < end and not r['customer_id'] for r in selected)
    coverage_status = 'available' if period_complete and not missing_identity else 'partial'
    metrics, members, records, events = {}, defaultdict(list), {}, []
    anchor = None if period_cohort else origin(query, config)
    anchor = stamp(anchor) if anchor else None
    for cid, rows in people.items():
        rows.sort(key=lambda r: (r['paid_at'], int(r.get('source_id') or 0) if period_cohort else 0, r['order_key']))
        times = [stamp(r['paid_at']) for r in rows]
        first, last = times[0], times[-1]
        verified = anchor is not None and anchor <= first and covers(anchor, first + timedelta(microseconds=1))
        reliable_last = covers(last, state_through)
        final = state(last, observation, points) if reliable_last else 'unverified'
        left, right = bisect_left(times,start), bisect_left(times,end)
        bought = rows[left:right]
        if period_cohort and final == 'recent' and len(bought) == 1:
            final = 'waiting'
        members[final].append(cid)
        members['known_pool'].append(cid)
        if bought:
            members['purchasers'].append(cid)
            category = 'old_purchasers' if first < start else 'first_purchasers' if verified else 'first_unverified'
            members[category].append(cid)
            repeated = len(bought) >= 2 if period_cohort else right > max(1,left)
            if repeated:
                members['repeat_purchasers'].append(cid)
        records[cid] = dict(customer_id=cid, first_paid_at=first.isoformat() if verified else None,
                            earliest_observed_at=first.isoformat(), first_verified=verified,
                            last_paid_at=last.isoformat(), stage=final,
                            days_since_last=(observation - last.date()).days if reliable_last else None,
                            period_orders=len(bought), covered_history_orders=len(rows), project_ids=sorted({r['gid'] for r in rows}))
        records[cid].update(period_start_stage=state(times[left-1], start.date(), points) if left and covers(times[left-1], start) else 'unverified',
                            period_end_stage=state(times[right-1], (end-timedelta(microseconds=1)).date(), points) if right and covers(times[right-1], end) else 'unverified')
        if period_cohort:
            flag = config.get('period_customer_types', {}).get(json.loads(rows[0]['body']).get('order_no_hash'), 'unknown')
            if flag not in ('new','old','unknown','conflict'):
                raise ValueError('invalid_order_time_customer_type')
            records[cid].update(period_first_paid_at=first.isoformat(), period_entry_customer_type=flag, period_repeated=len(bought)>=2)
            members['new_purchasers' if flag == 'new' else 'old_flag_purchasers' if flag == 'old' else 'customer_type_unknown'].append(cid)
            if len(bought) == 1:
                members['period_without_repeat'].append(cid)
        for name, group in (('period', bought), ('covered_history', rows)):
            amounts = [json.loads(r['body']).get('amount_usd') for r in group]
            records[cid][name + '_sales_usd'] = str(sum((Decimal(a) for a in amounts if a is not None), Decimal(0))) if amounts else '0'
            records[cid][name + '_amount_orders'] = sum(a is not None for a in amounts)
            records[cid][name + '_amount_complete'] = all(a is not None for a in amounts)
        for index in range(max(0,left-1),right):
            paid = times[index]
            following = times[index+1] if index+1 < len(times) else end
            for threshold, stage_name in zip(points, STATES[1:]):
                event_at = datetime.combine(paid.date() + timedelta(days=threshold), datetime.min.time(), TZ)
                # Exact-time purchase wins over a threshold; midnight at the exclusive end is excluded.
                if start <= event_at < end and event_at < following and covers(paid, event_at + timedelta(microseconds=1)):
                    events.append(dict(at=event_at.isoformat(), stage=stage_name, customer_id=cid, kind='enter'))
            if index and start <= paid < end:
                previous = times[index-1]
                if covers(previous, paid + timedelta(microseconds=1)):
                    days = (paid.date() - previous.date()).days
                    if paid.time() == datetime.min.time() and days in points:
                        days -= 1
                    before = STATES[sum(days >= p for p in points)]
                    if before != 'recent':
                        kind = 'silent_wakeup' if before == 'silent' else 'lost_return'
                        members[kind].append(cid)
                        events.append(dict(at=paid.isoformat(), stage=before, customer_id=cid, kind=kind))
    returns = set(members['silent_wakeup']) | set(members['lost_return'])
    paths = defaultdict(int)
    for cid, record in records.items():
        if not period_complete or record['stage'] == 'unverified':
            path = 'unverified'
        elif stamp(record['earliest_observed_at']) >= end:
            path = 'observed_after_period'
        elif not record['period_orders']:
            path = 'no_purchase'
        else:
            path = ('returned' if cid in returns else 'purchased') + ('_active' if record['stage'] in ('recent','waiting') else '_then_inactive')
        record.update(period_path=path, period_path_label=PATH_LABELS[path])
        group = record['stage'] + '__' + path
        members[group].append(cid); paths[(record['stage'], path)] += 1
    names = ('purchasers', 'first_purchasers', 'old_purchasers', 'first_unverified', 'repeat_purchasers',
             'silent_wakeup', 'lost_return', 'known_pool', *STATES, 'unverified')
    if period_cohort:
        names += ('waiting','new_purchasers','old_flag_purchasers','customer_type_unknown','period_without_repeat')
    for name in names:
        members[name] = sorted(set(members[name]))
        metrics[name] = metric(len(members[name]), coverage_status, observed_population='covered_identified_buyers')
    for name in STATES[1:]:
        entered = [e['customer_id'] for e in events if e['kind'] == 'enter' and e['stage'] == name]
        members['entered_' + name] = sorted(set(entered))
        metrics['entered_' + name] = metric(len(set(entered)), coverage_status, events=len(entered))
    if not period_cohort and (not anchor or not covers(anchor, state_through)):
        for name in ('first_purchasers', 'known_pool', *STATES):
            metrics[name]['status'] = 'insufficient_history' if name == 'first_purchasers' else 'partial'
            metrics[name]['reason'] = '仅已覆盖客户池；完整历史尚未核实'
    if not identity_complete:
        for value in metrics.values():
            value.update(value=None, status='unavailable', reason='跨站身份语义尚未验证；请切换单站')
    cohort = second_purchase(people, jobs, sites, start, end, start if period_cohort else anchor, query['H'], covers=covers)
    if period_cohort:
        cohort['basis'] = 'first_valid_purchase_in_selected_period; includes ES-new and ES-old customers'
    cohort_weeks = []
    entries = defaultdict(dict)
    if details:
        for cid, rows in people.items():
            first = stamp(rows[0]['paid_at'])
            monday = first.date() - timedelta(days=first.weekday())
            entries[monday][cid] = rows
    week = start.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=start.weekday())
    while details and week < end:
        entry_start, entry_end = max(start, week), min(end, week + timedelta(days=7))
        cohort_weeks.append(dict(start=entry_start.isoformat(), end_exclusive=entry_end.isoformat(),
                                 **second_purchase(entries[week.date()], jobs, sites, entry_start, end, start if period_cohort else anchor, query['H'], entry_end, covers)))
        week += timedelta(days=7)
    if not identity_complete:
        cohort = dict(status='unavailable', rate=None, reason='cross_site_identity_unverified')
        cohort_weeks = [dict(start=w['start'], end_exclusive=w['end_exclusive'], status='unavailable', rate=None, denominator=None, numerator=None, observing=None, first_unverified=None, coverage_gap=None) for w in cohort_weeks]
    daily_buyers, daily_enters, daily_returns, daily_first, daily_entries = defaultdict(set), defaultdict(set), defaultdict(set), defaultdict(int), defaultdict(int)
    for rec in records.values():
        if rec['first_verified']:
            daily_first[stamp(rec['first_paid_at']).date()] += 1
        if period_cohort:
            daily_entries[stamp(rec['period_first_paid_at']).date()] += 1
    for row in selected:
        paid = stamp(row['paid_at'])
        if row['customer_id'] and start <= paid < end:
            daily_buyers[paid.date()].add(row['customer_id'])
    for event in events:
        bucket = stamp(event['at']).date()
        if event['kind'] == 'enter' and event['stage'] == 'lost':
            daily_enters[bucket].add(event['customer_id'])
        if event['kind'] == 'lost_return':
            daily_returns[bucket].add(event['customer_id'])
    trend = []
    stocks_by_day = daily_stocks(people, runs, start, end, points, period_cohort) if details else {}
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while details and cursor < end:
        finish = min(cursor + timedelta(days=1), end)
        daily, entered, returned = daily_buyers[cursor.date()], daily_enters[cursor.date()], daily_returns[cursor.date()]
        stocks = stocks_by_day[cursor.date()]
        trend.append(dict(day=cursor.date().isoformat(), purchasers=len(daily) if identity_complete else None,
                          entered_lost=len(entered) if identity_complete else None, lost_return=len(returned) if identity_complete else None,
                          first_purchasers=daily_first[cursor.date()] if anchor and identity_complete else None,
                          stock=stocks if identity_complete else None,
                          status='available' if identity_complete and covers(max(start, cursor), finish) else 'partial'))
        if period_cohort:
            trend[-1]['period_entries'] = daily_entries[cursor.date()] if identity_complete else None
        cursor += timedelta(days=1)
    amounts = sorted(Decimal(r['covered_history_sales_usd']) for r in records.values() if r['covered_history_amount_complete'] and Decimal(r['covered_history_sales_usd']) > 0)
    threshold = amounts[int((len(amounts) - 1) * .75)] if amounts else None
    members['high_value_entered_silent'] = sorted(cid for cid in members['entered_silent'] if threshold is not None and records[cid]['covered_history_amount_complete'] and Decimal(records[cid]['covered_history_sales_usd']) >= threshold)
    members['first_without_repeat'] = sorted(cid for cid in members['first_purchasers'] if len(people[cid]) == 1)
    for key in ('high_value_entered_silent', 'first_without_repeat'):
        metrics[key] = metric(len(members[key]) if identity_complete else None, coverage_status if identity_complete else 'unavailable')
    if not any(lo < end and start < hi for intervals in runs.values() for lo, hi in intervals):
        for key, value in metrics.items():
            if key not in ('known_pool', *STATES, 'unverified'):
                value.update(value=None, status='pending', reason='该区间尚无完整采集片，等待回补')
    result = dict(metrics=metrics, observation_date=observation.isoformat(), cohort=cohort, cohort_weeks=cohort_weeks, trend=trend,
                trajectories=[dict(stage=stage, pattern=path, label=PATH_LABELS[path], count=count, group=stage+'__'+path) for (stage,path),count in sorted(paths.items())],
                value_segment=dict(basis='covered_purchase_history_usd', percentile=75, threshold_usd=str(threshold) if threshold is not None else None),
                coverage=dict(period_complete=period_complete, identity_deduplication_complete=identity_complete,
                              missing_identity_orders=missing_identity, sites=sites, historical_origin=anchor.isoformat() if anchor else None,
                              pool_scope='selected_period_identified_buyers' if period_cohort else 'all_covered_history_identified_buyers', state_data_through=state_through.isoformat(), state_basis=query.get('state_basis','period_end'),
                              covered_history_start=min((a for intervals in runs.values() for a,b in intervals),default=start).isoformat(),
                              refund_correction='only_reenumerated_payment_windows',
                              failed_windows=sum(j['state'] == 'failed' for j in jobs)))
    if period_cohort:
        if identity_complete:
            metrics['first_purchasers'].update(status='insufficient_history',reason='后台订单标记另列；本视图不证明终身真实首购')
        count = len(members['purchasers']); repeated = len(members['repeat_purchasers'])
        result['repeat_rate'] = dict(numerator=repeated,denominator=count,rate=repeated/count if count else None,
                                     status=coverage_status if count else 'not_mature',basis='at_least_two_distinct_valid_orders_within_selected_period')
        result['repeat_states'] = [dict(stage=stage,repeated=sum(rec['stage']==stage and rec['period_repeated'] for rec in records.values()),
                                        not_repeated=sum(rec['stage']==stage and not rec['period_repeated'] for rec in records.values())) for stage in ('waiting',*STATES,'unverified')]
        result['value_segment']['basis'] = 'selected_period_purchase_usd'
        if not identity_complete:
            result['repeat_rate'].update(numerator=None,denominator=None,rate=None,status='unavailable')
            result['repeat_states'] = []
        elif metrics['purchasers']['value'] is None:
            for key in ('known_pool','waiting',*STATES,'unverified'):
                metrics[key].update(value=None,status='pending',reason='所选期间尚无完整订单片')
            result['repeat_rate'].update(numerator=None,denominator=None,rate=None,status='pending')
            result['repeat_states'] = []
    return result, dict(members=members, records=records, events=events)


def customer_orders(orders, cutoff):
    people = defaultdict(list)
    for row in orders:
        if row['site'] != '266' or not row['valid'] or not row['customer_id']:
            continue
        paid = stamp(row['paid_at'])
        if paid < cutoff:
            people[row['customer_id']].append((paid, row['order_key'], row['gid'], json.loads(row['body'])))
    for purchases in people.values():
        purchases.sort(key=lambda order: order[:2])
    return people


def complete_coverage(jobs):
    intervals = coverage_runs(jobs, ['266'])['266']
    return lambda start, end: start >= end or any(lo <= start and end <= hi for lo, hi in intervals)


def amount_summary(purchases):
    known = [Decimal(order[3]['amount_usd']) for order in purchases if order[3].get('amount_usd') is not None]
    return dict(known_usd=format(sum(known, Decimal(0)), 'f') if known or not purchases else None,
                unknown_orders=len(purchases) - len(known))


COHORT_SEGMENTS = ('new', 'old', 'all')


def cohort_groups(batches, people, covered, query, cutoff, flags, segment='new'):
    from customer_segments import is_repeat

    windows = query['windows']
    min_return, max_return = (timedelta(days=query[key]) for key in ('return_after', 'return_within'))
    durations = [timedelta(days=days) for days in windows]
    members = defaultdict(dict)
    for cid, purchases in people.items():
        first = purchases[0]
        month = first[0].strftime('%Y-%m')
        if month not in batches or query['game'] not in ('all', first[2]):
            continue
        batch = batches[month]
        flag = flags.get(first[3]['order_no_hash'])
        if flag not in ('new', 'old'):
            # ES flag missing or conflicting: counted as pending, kept only in the everyone view.
            batch['pending_classification'] += 1
            if segment != 'all':
                continue
        elif segment != 'all' and flag != segment:
            continue
        repeats = [order for order in purchases[1:] if query['game'] in ('all', order[2])
                   and is_repeat(first[0], order[0])]
        first_repeat = repeats[0][0] if repeats else cutoff
        for window, duration in zip(batch['windows'], durations):
            end = first[0] + duration
            if end > cutoff:
                status = 'observing'
            elif not covered(first[0], end):
                status = 'coverage_gap'
            else:
                status = 'denominator'
            in_numerator = status == 'denominator' and first_repeat < end
            members[window['group']][cid] = dict(window_status=status, in_numerator=in_numerator)
            window[status] += 1
            if status == 'denominator':
                if in_numerator:
                    window['numerator'] += 1
                    window['amount_orders'].extend(order for order in repeats if order[0] < end)
                if duration == durations[-1]:
                    bucket = next((i for i, d in enumerate(durations) if first_repeat < first[0] + d), len(windows))
                    batch['first_repeat']['counts'][bucket] += 1

        end = first[0] + max_return
        if end <= cutoff and covered(first[0], end) and first_repeat >= first[0] + min_return:
            returned = batch['silent_return']
            returned['denominator'] += 1
            if first_repeat < end:
                returned['numerator'] += 1
                returned['amount_orders'].extend(order for order in repeats if order[0] < end)
    return members


def analyze_cohorts(orders, jobs, query, cutoff, flags, *, people=None, segment='new'):
    """Build cohort window statistics and the matching frozen membership.

    segment: 'new' (ES new-customer first orders), 'old' (ES old-customer first orders,
    batched by their first purchase in the covered history) or 'all' (everyone).
    """
    if segment not in COHORT_SEGMENTS:
        raise ValueError('cohort_segment')
    prefix = 'cohort:' if segment == 'new' else 'cohort:' + segment + ':'
    windows = query['windows']
    year, month = map(int, query['cohort_start'].split('-'))
    batches = {}
    while (key := f'{year:04d}-{month:02d}') <= query['cohort_end']:
        batches[key] = dict(month=key, pending_classification=0,
                            windows=[dict(days=days, group=f'{prefix}{key}:{days}', numerator=0,
                                          denominator=0, observing=0, coverage_gap=0, amount_orders=[])
                                     for days in windows],
                            first_repeat=dict(boundaries=windows, counts=[0] * (len(windows) + 1)),
                            silent_return=dict(after_days=query['return_after'], within_days=query['return_within'],
                                               numerator=0, denominator=0, amount_orders=[]))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    members = cohort_groups(batches, people if people is not None else customer_orders(orders, cutoff),
                            complete_coverage(jobs), query, cutoff, flags, segment)
    for batch in batches.values():
        for window in batch['windows']:
            members[window['group']]
            window['repeat_amount'] = amount_summary(window.pop('amount_orders'))
            amount = window['repeat_amount']
            known = amount['known_usd']
            window['repeat_per_customer_usd'] = (
                format(Decimal(known) / window['numerator'], '.2f')
                if known is not None and window['numerator'] and not amount['unknown_orders'] else None)
            window['rate'] = window['numerator'] / window['denominator'] if window['denominator'] else None
        returned = batch['silent_return']
        returned['return_amount'] = amount_summary(returned.pop('amount_orders'))
        returned['rate'] = returned['numerator'] / returned['denominator'] if returned['denominator'] else None
    return dict(batches=list(batches.values())), members


def stage_events(purchases, start, end, game, config, covered):
    from customer_segments import stage, thresholds

    points = thresholds(game, config)
    for index, (paid, *_order) in enumerate(purchases):
        if paid >= end:
            break
        if index and paid >= start:
            previous = purchases[index - 1][0]
            if covered(previous, paid + timedelta(microseconds=1)):
                # A purchase at the same midnight as a threshold wins the tie.
                date_before = paid.date() - timedelta(days=1) if paid.time() == datetime.min.time() else paid.date()
                before = stage(previous, max(date_before, previous.date()), game, config, True)
                if before != 'recent':
                    yield dict(kind='silent_wakeup' if before == 'silent' else 'lost_return',
                               stage=before, at=paid.isoformat())
        following = purchases[index + 1][0] if index + 1 < len(purchases) else end
        for threshold, name in zip(points, STATES[1:]):
            at = datetime.combine(paid.date() + timedelta(days=threshold), datetime.min.time(), TZ)
            if start <= at < min(following, end) and covered(paid, at + timedelta(microseconds=1)):
                yield dict(kind='enter', stage=name, at=at.isoformat())


def analyze_stages(orders, jobs, query, cutoff, flags, config, *, people=None):
    """Use one filtered population for interval events, stock, and cross-game flow."""
    from customer_segments import is_repeat, stage

    start, end = (stamp(query[key]) for key in ('start', 'end_exclusive'))
    observation = (cutoff - timedelta(microseconds=1)).date()
    covered = complete_coverage(jobs)
    game = query['game']
    members = defaultdict(set, {f'stage:{key}': set() for key in (*STATES, 'unverified')})
    for name in STATES[1:]:
        members[f'entered:{name}']
    for name in ('silent_wakeup', 'lost_return', 'any'):
        members[f'return:{name}']
    daily = defaultdict(set)
    records = {}
    if people is None:
        people = customer_orders(orders, cutoff)

    def observed(paid, gid):
        return stage(paid, observation, gid, config, covered(paid, cutoff))

    for cid, all_purchases in people.items():
        first = all_purchases[0]
        purchases = all_purchases if game == 'all' else [purchase for purchase in all_purchases if purchase[2] == game]
        interval = [purchase for purchase in purchases if start <= purchase[0] < end]
        flag = flags.get(first[3]['order_no_hash'])
        customer_type = flag if flag in ('new', 'old') else 'unknown'
        if not interval or query['customer_type'] not in ('all', customer_type):
            continue
        repeated = any(key != first[1] and is_repeat(first[0], paid) for paid, key, *_ in purchases)
        if query['repeat_status'] not in ('all', 'repeated' if repeated else 'not_repeated'):
            continue
        last = purchases[-1][0]
        state = observed(last, game)
        records[cid] = dict(customer_id=cid, stage=state, customer_type=customer_type, repeated=repeated,
                            first_paid_at=first[0].isoformat(), last_paid_at=last.isoformat(),
                            period_orders=len(interval))
        members[f'stage:{state}'].add(cid)
        for event in stage_events(purchases, start, end, game, config, covered):
            kind = event['kind']
            if kind == 'enter':
                members[f"entered:{event['stage']}"].add(cid)
            else:
                day = event['at'][:10]
                daily[(day, kind)].add(cid)
                members[f'return:{kind}'].add(cid)
                members['return:any'].add(cid)
        if game == 'all':
            by_game = {purchase[2]: purchase[0] for purchase in all_purchases}
            statuses = {gid: observed(paid, gid) for gid, paid in by_game.items()}
            recent_games = [gid for gid, status in statuses.items() if status == 'recent']
            for source, status in statuses.items():
                if status in ('lost', 'long_lost'):
                    for destination in recent_games:
                        members[f'flow:{source}:{destination}'].add(cid)

    def counts(prefix, labels):
        return [dict(kind=label, group=f'{prefix}:{label}', count=len(members[f'{prefix}:{label}']))
                for label in labels]

    daily_returns = []
    day = start
    while day < end:
        until = day + timedelta(days=1)
        key = day.date().isoformat()
        observed_day = covered(day, until)
        daily_returns.append(dict(date=key,
                                  silent_wakeup=len(daily[(key, 'silent_wakeup')]) if observed_day else None,
                                  lost_return=len(daily[(key, 'lost_return')]) if observed_day else None))
        day = until
    flow = []
    for group in sorted(members):
        if group.startswith('flow:'):
            _, source, destination = group.split(':')
            flow.append(dict(source=source, destination=destination, count=len(members[group]), group=group))
    result = dict(stages=counts('stage', (*STATES, 'unverified')), inflow=counts('entered', STATES[1:]),
                  returns=counts('return', ('silent_wakeup', 'lost_return', 'any')), daily_returns=daily_returns)
    if game == 'all':
        result['cross_game_flow'] = flow
    return result, members, records


def period_repeat(orders, site, game, start, end):
    """Count scoped buyers with a distinct order at least 24 hours after period entry."""
    from customer_segments import is_repeat

    people = defaultdict(list)
    missing_identity = 0
    for row in orders:
        if not row['valid'] or row['site'] != site or game != 'all' and row['gid'] != game:
            continue
        paid = stamp(row['paid_at'])
        if not start <= paid < end:
            continue
        if row['customer_id']:
            people[row['customer_id']].append((paid, row['order_key']))
        else:
            missing_identity += 1
    repeated = 0
    for purchases in people.values():
        first_at, first_key = min(purchases)
        repeated += any(key != first_key and is_repeat(first_at, paid) for paid, key in purchases)
    count = len(people)
    rate = dict(numerator=repeated, denominator=count, rate=repeated / count if count else None,
                status='available' if count else 'not_mature',
                basis='period_first_plus_24h_within_selected_period')
    return rate, missing_identity


def second_purchase(people, jobs, sites, start, end, anchor, horizon, entry_end=None, covers=None):
    mature = repeated = observing = gap = unknown = 0
    covers = covers or (lambda a,b: covered(jobs, sites, a,b))
    for rows in people.values():
        first = stamp(rows[0]['paid_at'])
        if not start <= first < (entry_end or end):
            continue
        if anchor is None or not covers(anchor, first + timedelta(microseconds=1)):
            unknown += 1
            continue
        stop = first + timedelta(days=horizon)
        if stop > end:
            observing += 1
        elif not covers(first, stop):
            gap += 1
        else:
            mature += 1
            repeated += any(stamp(r['paid_at']) < stop for r in rows[1:])
    return dict(H=horizon, numerator=repeated, denominator=mature, observing=observing, coverage_gap=gap,
                first_unverified=unknown, rate=repeated / mature if mature else None,
                status='available' if mature else 'insufficient_history' if unknown or gap else 'not_mature')


def project_analysis(orders, jobs, query, config, global_result, global_members):
    summaries, matrices = [], []
    end, start = stamp(query['as_of']), stamp(query['start'])
    orders = [r for r in orders if r['site'] in config['sites']]
    by_customer, by_project = defaultdict(list), defaultdict(list)
    for row in orders:
        if row['valid'] and stamp(row['paid_at']) < end:
            by_customer[row['customer_id']].append(row)
            by_project[row['gid']].append(row)
    gids = sorted({r['gid'] for r in orders if r['valid'] and stamp(r['paid_at']) < end and in_scope(r, query, config)})
    for gid in gids:
        q = dict(query, scope='project', scope_id=gid)
        if query['policy_mode'] == 'per_project' and query['policy_version'] not in OBSERVATION_POLICIES:
            q['policy_version'] = config['projects'].get(gid, {}).get('policy', 'fc-v1' if config['projects'].get(gid, {}).get('series') == 'FC' else 'common-v1')
        subset = by_project[gid]
        result, private = analyze(subset, jobs, q, config, details=False)
        acquired = dict(global_first=0, existing_global=0, global_unknown=0)
        for cid in private['members']['first_purchasers']:
            t0 = stamp(private['records'][cid]['earliest_observed_at'])
            earlier = [r for r in by_customer[cid] if stamp(r['paid_at']) < t0]
            if earlier:
                acquired['existing_global'] += 1
            else:
                global_origin = config.get('history_origins', {}).get('global:') or config.get('available_history_origin')
                if global_origin and covered(jobs, list(config['sites']), stamp(global_origin), t0 + timedelta(microseconds=1)):
                    acquired['global_first'] += 1
                else:
                    acquired['global_unknown'] += 1
        cross = defaultdict(int)
        destinations = defaultdict(set)
        for cid, rec in private['records'].items():
            whole = global_members['records'].get(cid)
            if not whole:
                continue
            cross[(rec['stage'], whole['stage'])] += 1
            if rec['stage'] in ('lost', 'long_lost') and whole['stage'] == 'recent':
                for row in by_customer[cid]:
                    if row['gid'] != gid and start <= stamp(row['paid_at']) < end:
                        destinations[row['gid']].add(cid)
        if not result['coverage']['identity_deduplication_complete']:
            acquired = {k: None for k in acquired}
            cross, destinations = {}, {}
        summaries.append(dict(project_id=gid, label=config['projects'].get(gid, {}).get('label', '游戏ID ' + gid),
                              policy_version=q['policy_version'], metrics=result['metrics'], acquisition=acquired, cohort=result['cohort']))
        matrices.append(dict(project_id=gid, states=[dict(project_stage=a, global_stage=b, count=n) for (a, b), n in sorted(cross.items())],
                             destinations=[dict(project_id=g, purchasers=len(ids), same_series=bool(config['projects'].get(gid, {}).get('series') and config['projects'].get(gid, {}).get('series') == config['projects'].get(g, {}).get('series'))) for g, ids in sorted(destinations.items())], destinations_overlap=True))
    return summaries, matrices
