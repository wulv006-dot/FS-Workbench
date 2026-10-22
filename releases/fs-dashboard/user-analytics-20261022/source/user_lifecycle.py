"""As-of lifecycle, interval events, project migration and mature second purchases."""
from collections import defaultdict
from datetime import datetime, timedelta
import json

from user_contract import TZ, STATES, stamp, state


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
    return config.get('history_origins', {}).get(query['scope'] + ':' + query['scope_id'])


def metric(value, status='available', **extra):
    return dict(value=value, status=status, **extra)


def analyze(orders, jobs, query, config):
    start, end = stamp(query['start']), stamp(query['as_of'])
    observation = (end - timedelta(microseconds=1)).date()
    points = config['policies'][query['policy_version']]
    sites = [query['scope_id']] if query['scope'] == 'site' else list(config['sites'])
    groups = {config['sites'][s].get('verified_identity_group') for s in sites}
    identity_complete = len(sites) == 1 or len(groups) == 1 and None not in groups and '' not in groups
    pool = [r for r in orders if r['valid'] and stamp(r['paid_at']) < end and r['site'] in sites]
    selected = [r for r in pool if in_scope(r, query, config)]
    people = defaultdict(list)
    for row in selected:
        if row['customer_id']:
            people[row['customer_id']].append(row)
    period_complete = covered(jobs, sites, start, end)
    missing_identity = sum(start <= stamp(r['paid_at']) < end and not r['customer_id'] for r in selected)
    coverage_status = 'available' if period_complete and not missing_identity else 'partial'
    metrics, members, records, events = {}, defaultdict(list), {}, []
    anchor = origin(query, config)
    anchor = stamp(anchor) if anchor else None
    for cid, rows in people.items():
        rows.sort(key=lambda r: (r['paid_at'], r['order_key']))
        first, last = stamp(rows[0]['paid_at']), stamp(rows[-1]['paid_at'])
        verified = anchor is not None and anchor <= first and covered(jobs, sites, anchor, first + timedelta(microseconds=1))
        reliable_last = covered(jobs, sites, last, end)
        final = state(last, observation, points) if reliable_last else 'unverified'
        bought = [r for r in rows if start <= stamp(r['paid_at']) < end]
        members[final].append(cid)
        members['known_pool'].append(cid)
        if bought:
            members['purchasers'].append(cid)
            category = 'old_purchasers' if first < start else 'first_purchasers' if verified else 'first_unverified'
            members[category].append(cid)
            if len(rows) > 1 and any(start <= stamp(r['paid_at']) < end for r in rows[1:]):
                members['repeat_purchasers'].append(cid)
        records[cid] = dict(customer_id=cid, first_paid_at=first.isoformat() if verified else None,
                            earliest_observed_at=first.isoformat(), first_verified=verified,
                            last_paid_at=last.isoformat(), stage=final,
                            days_since_last=(observation - last.date()).days if reliable_last else None,
                            period_orders=len(bought), project_ids=sorted({r['gid'] for r in rows}))
        for index, row in enumerate(rows):
            paid = stamp(row['paid_at'])
            following = stamp(rows[index + 1]['paid_at']) if index + 1 < len(rows) else end
            for threshold, stage_name in zip(points, STATES[1:]):
                event_at = datetime.combine(paid.date() + timedelta(days=threshold), datetime.min.time(), TZ)
                # Exact-time purchase wins over a threshold; midnight at the exclusive end is excluded.
                if start <= event_at < end and event_at < following and covered(jobs, sites, paid, event_at + timedelta(microseconds=1)):
                    events.append(dict(at=event_at.isoformat(), stage=stage_name, customer_id=cid, kind='enter'))
            if index and start <= paid < end:
                previous = stamp(rows[index - 1]['paid_at'])
                if covered(jobs, sites, previous, paid + timedelta(microseconds=1)):
                    days = (paid.date() - previous.date()).days
                    if paid.time() == datetime.min.time() and days in points:
                        days -= 1
                    before = STATES[sum(days >= p for p in points)]
                    if before != 'recent':
                        kind = 'silent_wakeup' if before == 'silent' else 'lost_return'
                        members[kind].append(cid)
                        events.append(dict(at=paid.isoformat(), stage=before, customer_id=cid, kind=kind))
    names = ('purchasers', 'first_purchasers', 'old_purchasers', 'first_unverified', 'repeat_purchasers',
             'silent_wakeup', 'lost_return', 'known_pool', *STATES, 'unverified')
    for name in names:
        members[name] = sorted(set(members[name]))
        metrics[name] = metric(len(members[name]), coverage_status, observed_population='covered_identified_buyers')
    for name in STATES[1:]:
        entered = [e['customer_id'] for e in events if e['kind'] == 'enter' and e['stage'] == name]
        members['entered_' + name] = sorted(set(entered))
        metrics['entered_' + name] = metric(len(set(entered)), coverage_status, events=len(entered))
    if not anchor or not covered(jobs, sites, anchor, end):
        for name in ('first_purchasers', 'known_pool', *STATES):
            metrics[name]['status'] = 'insufficient_history' if name == 'first_purchasers' else 'partial'
            metrics[name]['reason'] = '仅已覆盖客户池；完整历史尚未核实'
    if not identity_complete:
        for value in metrics.values():
            value.update(value=None, status='unavailable', reason='跨站身份语义尚未验证；请切换单站')
    cohort = second_purchase(people, jobs, sites, start, end, anchor, query['H'])
    if not identity_complete:
        cohort = dict(status='unavailable', rate=None, reason='cross_site_identity_unverified')
    daily_buyers, daily_enters, daily_returns = defaultdict(set), defaultdict(set), defaultdict(set)
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
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        finish = min(cursor + timedelta(days=1), end)
        daily, entered, returned = daily_buyers[cursor.date()], daily_enters[cursor.date()], daily_returns[cursor.date()]
        trend.append(dict(day=cursor.date().isoformat(), purchasers=len(daily) if identity_complete else None,
                          entered_lost=len(entered) if identity_complete else None, lost_return=len(returned) if identity_complete else None,
                          status='available' if identity_complete and covered(jobs, sites, max(start, cursor), finish) else 'partial'))
        cursor += timedelta(days=1)
    return dict(metrics=metrics, observation_date=observation.isoformat(), cohort=cohort, trend=trend,
                coverage=dict(period_complete=period_complete, identity_deduplication_complete=identity_complete,
                              missing_identity_orders=missing_identity, sites=sites, historical_origin=anchor.isoformat() if anchor else None,
                              pool_scope='covered_identified_buyers', refund_correction='only_reenumerated_payment_windows',
                              failed_windows=sum(j['state'] == 'failed' for j in jobs))), dict(members=members, records=records, events=events)


def second_purchase(people, jobs, sites, start, end, anchor, horizon):
    mature = repeated = observing = gap = unknown = 0
    for rows in people.values():
        first = stamp(rows[0]['paid_at'])
        if not start <= first < end:
            continue
        if anchor is None or not covered(jobs, sites, anchor, first + timedelta(microseconds=1)):
            unknown += 1
            continue
        stop = first + timedelta(days=horizon)
        if stop > end:
            observing += 1
        elif not covered(jobs, sites, first, stop):
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
    by_customer = defaultdict(list)
    for row in orders:
        if row['valid'] and stamp(row['paid_at']) < end:
            by_customer[row['customer_id']].append(row)
    gids = sorted({r['gid'] for r in orders if r['valid'] and stamp(r['paid_at']) < end and in_scope(r, query, config)})
    for gid in gids:
        q = dict(query, scope='project', scope_id=gid)
        if query['policy_mode'] == 'per_project':
            q['policy_version'] = config['projects'].get(gid, {}).get('policy', 'fc-v1' if gid == '1327' else 'common-v1')
        if query['scope'] == 'site':
            subset = [r for r in orders if r['site'] == query['scope_id']]
        else:
            subset = orders
        result, private = analyze(subset, jobs, q, config)
        acquired = dict(global_first=0, existing_global=0, global_unknown=0)
        for cid in private['members']['first_purchasers']:
            t0 = stamp(private['records'][cid]['earliest_observed_at'])
            earlier = [r for r in by_customer[cid] if stamp(r['paid_at']) < t0]
            if earlier:
                acquired['existing_global'] += 1
            else:
                global_origin = config.get('history_origins', {}).get('global:')
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
                             destinations=[dict(project_id=g, purchasers=len(ids)) for g, ids in sorted(destinations.items())], destinations_overlap=True))
    return summaries, matrices
