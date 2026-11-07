"""Stable randomized three-hour policy blocks, independent of hourly prices."""
from datetime import timedelta
from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import random

from .financial import fingerprint, instant

STRATEGY_VERSION = 'smart-bidirectional-v2'


def strategy_start(plan):
    return instant(plan['smart_started_at'] if plan.get('smart_strategy_version') == STRATEGY_VERSION else plan['starts_at'])


def policy_suffix(plan):
    suffix = plan['plan_id'] + ':' + str(plan['revision'])
    return suffix + ':' + STRATEGY_VERSION if plan.get('smart_strategy_version') == STRATEGY_VERSION else suffix


def observed_blocks(plan, operations, outcomes, windows, now, *, epoch, group=None):
    if plan.get('smart_strategy_version')==STRATEGY_VERSION and group not in ('console','pc'):
        raise ValueError('pricing_smart_platform_required')
    group_filter = group
    windows_by_id = {w['operation_id']: w for w in windows}
    confirmed = sorted((o for o in operations if o.get('status') in ('COMPLETED', 'NO_CHANGE') and o.get('completed_at')),
                       key=lambda o: instant(o['completed_at']))
    blocks = {}
    for index, op in enumerate(confirmed):
        info = (op.get('bundle') or {}).get('smart_assignment') or {}
        effective = (info.get('group_keys') or {}).get(group_filter) if group_filter else info.get('effective_key')
        if (op.get('plan_id') != plan['plan_id'] or epoch is not None and info.get('epoch') != epoch or not effective or
                plan.get('smart_strategy_version') == STRATEGY_VERSION and
                (info.get('strategy_version') != STRATEGY_VERSION or info.get('revision') != plan['revision'])):
            continue
        begin = max(instant(op['completed_at']), instant(info['starts_at']))
        end = min(now, instant(info['ends_at']))
        for later in confirmed[index + 1:]:
            if set(op.get('resources', plan.get('resources', []))) & set(later.get('resources', plan.get('resources', []))):
                end = min(end, instant(later['completed_at']))
                break
        if end <= begin or instant(info['ends_at']) > now:
            continue
        slot = info['slot']
        label = (info.get('group_labels') or {}).get(group_filter, info['label'])
        block = blocks.setdefault((info['epoch'], slot), dict(slot=slot, epoch=info['epoch'], block=info.get('block',slot),
                    starts_at=info['starts_at'], label=label, hours=Decimal(0), orders=0,
                    net=Decimal(0), gross=Decimal(0), uncovered=Decimal(0), new_keys=set(),
                    complete=True, customer_complete=True, prices=set(), intervals=[], events=[], no_space=True, has_no_space=False))
        if info.get('strategy_version') == STRATEGY_VERSION:
            block['pair_id'] = info['group_pair_ids'][group_filter]
        if group_filter:
            block['no_space'] = block['no_space'] and (info.get('no_space_by_group') or {}).get(group_filter) is True
            if label != 'A':
                block['has_no_space'] = block['has_no_space'] or (info.get('merged_with_A_by_group') or {}).get(group_filter) is not False
        block_start=instant(info['starts_at'])
        block['intervals'].append([(begin-block_start).total_seconds(), (end-block_start).total_seconds()])
        block['hours'] += Decimal(str((end - begin).total_seconds())) / Decimal(3600)
        block['prices'].add(effective)
        for row in outcomes:
            if not begin <= instant(row['occurred_at']) < end:
                continue
            window = windows_by_id.get(row.get('price_window_id'))
            group = row['group']
            base = group if group in ('console', 'pc') else 'pc' if group.endswith(':PC') else 'console'
            if group_filter and base != group_filter:
                continue
            actual_action = (window or {}).get('action') or {}
            op_action = op['bundle']['action']
            if (base not in actual_action.get('base_prices', {}) or
                    Decimal(actual_action['base_prices'][base]) != Decimal(op_action['base_prices'][base]) or
                    ':' in group and Decimal(actual_action.get('region_coefficients', {}).get(group, '1')) != Decimal(op_action.get('region_coefficients', {}).get(group, '1'))):
                block['complete'] = False
                continue
            block['orders'] += 1
            block['events'].append(dict(row, offset=(instant(row['occurred_at'])-block_start).total_seconds()))
            if row.get('actual_net_usd') is None:
                block['complete'] = False
                continue
            if row.get('new_customer') is None:
                block['customer_complete'] = False
            net = Decimal(row['actual_net_usd'])
            block['net'] += net
            if row.get('actual_contribution_usd') is None:
                block['uncovered'] += net
            else:
                block['gross'] += Decimal(row['actual_contribution_usd'])
            if row['new_customer']:
                if not row.get('customer_key'):
                    block['customer_complete'] = False
                else:
                    block['new_keys'].add(row['customer_key'])
    result = []
    for block in blocks.values():
        block['complete'] = block['complete'] and (not block['net'] or block['uncovered'] <= block['net'] * Decimal('.10'))
        block['new_customers'] = len(block.pop('new_keys'))
        block['prices'] = sorted(block['prices'])
        for key in ('hours', 'net', 'gross', 'uncovered'):
            block[key] = str(block[key])
        result.append(block)
    return result


def paired_exposure(first, second):
    for a in first:
        for b in second:
            overlaps=[(max(x[0],y[0]),min(x[1],y[1])) for x in a.get('intervals',[]) for y in b.get('intervals',[])
                      if min(x[1],y[1])>max(x[0],y[0])]
            hours=sum(Decimal(str(end-start)) for start,end in overlaps)/3600
            if hours>=2:
                return a,b,overlaps,hours
    return None


def assess(blocks, *, complete):
    if not complete:
        return dict(status='WAITING_MORE_DATA', winner=None, excluded=[], causal_effect_estimated=False)
    # Freeze each pair's first sufficiently exposed attempt independently of sales and cost results.
    by_pair = {}
    for b in sorted(blocks, key=lambda b: (b.get('epoch',0),b.get('block',b['slot']))):
        if Decimal(str(b.get('hours', 0))) < 2:
            continue
        pair_id = b.get('pair_id', str(b.get('epoch',0))+':'+str(b['slot'] % 8))
        by_pair.setdefault(pair_id, {}).setdefault(b['label'], []).append(b)
    scores, excluded = {}, []
    for label in ('B', 'C'):
        pairs = []
        for pair_rows in by_pair.values():
            exposure = paired_exposure(pair_rows.get('A',[]),pair_rows.get(label,[]))
            if exposure is None:
                continue
            a,b,overlaps,hours=exposure
            if not a.get('complete') or not b.get('complete'):
                continue
            if b.get('has_no_space') or set(a['prices']) & set(b['prices']):
                continue
            clipped = []
            for block in (a, b):
                rows=[row for row in block.get('events', []) if any(start <= row['offset'] < end for start,end in overlaps)]
                gap_rows=[row for row in rows if 'gap_usd' in row]
                rows=[row for row in rows if 'gap_usd' not in row]
                if gap_rows or any(row.get('actual_net_usd') is None or row.get('actual_contribution_usd') is None for row in rows):
                    break
                net=sum(Decimal(row['actual_net_usd']) for row in rows)
                gross=sum(Decimal(row['actual_contribution_usd']) for row in rows if row.get('actual_contribution_usd') is not None)
                uncertain=sum(Decimal(row['gap_usd']) for row in gap_rows)
                uncovered=sum(Decimal(row['actual_net_usd']) for row in rows if row.get('actual_contribution_usd') is None) + uncertain
                if uncovered:
                    break
                covered=[abs(Decimal(row['actual_contribution_usd'])) for row in rows if row.get('actual_contribution_usd') is not None]
                if covered and max(covered) > abs(gross) / 2:
                    break
                customer_unknown=len(gap_rows)+sum(row.get('new_customer') is None or row.get('new_customer') and not row.get('customer_key') for row in rows)
                new={row['customer_key'] for row in rows if row.get('new_customer') and row.get('customer_key')}
                clipped.append(dict(hours=hours, orders=len(rows)+len(gap_rows), net=net, gross=gross, uncovered=uncovered, uncertain=uncertain,
                                    new_customers=len(new), customer_unknown=customer_unknown))
            if len(clipped)==2:
                pairs.append(tuple(clipped))
        if len(pairs) < 2 or sum(p[0]['orders'] for p in pairs) < 10:
            continue
        if all(Decimal(str(y['gross'])) / Decimal(str(y['hours'])) < Decimal('.90') * Decimal(str(x['gross'])) / Decimal(str(x['hours'])) for x,y in pairs):
            excluded.append(label)
        if sum(p[1]['orders'] for p in pairs) < 10:
            continue
        rates = []
        for index in (0, 1):
            totals = {k:sum(Decimal(str(pair[index][k])) for pair in pairs) for k in ('hours','net','gross','new_customers')}
            totals['uncovered'] = sum(Decimal(str(pair[index].get('uncovered', 0))) for pair in pairs)
            totals['uncertain'] = sum(Decimal(str(pair[index].get('uncertain', 0))) for pair in pairs)
            totals['customer_unknown'] = sum(Decimal(str(pair[index]['customer_unknown'])) for pair in pairs)
            totals['orders'] = sum(Decimal(str(pair[index]['orders'])) for pair in pairs)
            rates.append({k:totals[k] / totals['hours'] for k in ('net','gross','new_customers')})
            rates[-1]['uncovered'] = totals['uncovered'] / totals['hours']
            rates[-1]['uncertain'] = totals['uncertain'] / totals['hours']
            rates[-1]['customer_unknown'] = totals['customer_unknown'] / totals['hours']
            rates[-1]['customer_coverage'] = 1 - totals['customer_unknown'] / totals['orders']
        a, b = rates
        if min(a['customer_coverage'],b['customer_coverage']) < Decimal('.90') or any(a[k] <= 0 for k in ('net','gross','new_customers')) or b['net'] <= 0:
            continue
        consistent=all(Decimal(str(y['gross'])) > Decimal(str(x['gross'])) for x,y in pairs)
        if (consistent and b['gross'] >= (a['gross']+a['uncovered']) * Decimal('1.08') and b['net'] >= (a['net']+a['uncertain']) * Decimal('.95') and
                b['new_customers'] >= (a['new_customers'] + a['customer_unknown']) * Decimal('.90') and
                abs(b['uncovered'] / (b['net']+b['uncertain']) - a['uncovered'] / (a['net']+a['uncertain'])) <= Decimal('.05') and
                b['gross'] - a['gross'] > max(a['uncovered'], b['uncovered'])):
            scores[label] = b['gross'] / a['gross']
    winner = max(scores, key=scores.get) if scores else None
    return dict(status='OBSERVED_WINNER' if winner else 'WAITING_MORE_DATA', winner=winner,
                excluded=excluded, causal_effect_estimated=False)


def scope_gaps(plan, rows, group, epoch, coverage):
    for row in rows:
        block_start=instant(row['starts_at']) if row.get('starts_at') else strategy_start(plan)+timedelta(hours=3*(epoch*16+row['slot']))
        for gap in coverage['gap_events']:
            gap_group=gap.get('group')
            gap_base=gap_group if gap_group in ('console','pc') else 'pc' if gap_group and gap_group.endswith(':PC') else 'console' if gap_group else None
            offset=(instant(gap['occurred_at'])-block_start).total_seconds()
            if gap_base in (None,group) and any(start <= offset < stop for start,stop in row['intervals']):
                if gap.get('amount_usd') is None:
                    row['complete']=False
                else:
                    row['events'].append(dict(offset=offset, gap_usd=gap['amount_usd']))


def early_correction(db, plan, now, block):
    if plan.get('smart_strategy_version') == STRATEGY_VERSION:
        return bidirectional_correction(db, plan, now, block)
    suffix=plan['plan_id']+':'+str(plan['revision'])
    key='smart-correction:'+suffix
    correction=db.get('metadata',key) or dict(effective_blocks={})
    online=db.get('metadata','daily_online_context') or {}
    coverage=online.get('learning_coverage') or {}
    observed=coverage.get('observed_at')
    if not (coverage.get('query_complete') is True and 'gap_events' in coverage and
            coverage.get('unscoped_time_gaps') is False and observed):
        return correction
    cutoff=min(now,instant(observed))
    operations,windows=db.all('operations'),db.all('actual_price_windows')
    epoch=block//16
    exclusions=set()
    for prior_epoch in ({epoch,epoch-1} if epoch else {0}):
        for group in ('console','pc'):
            rows=observed_blocks(plan,operations,online.get('actual_outcomes',[]),windows,cutoff,epoch=prior_epoch,group=group)
            scope_gaps(plan,rows,group,prior_epoch,coverage)
            exclusions.update(assess(rows,complete=True)['excluded'])
    newly=sorted(exclusions-set(correction['effective_blocks']))
    if newly:
        correction=dict(effective_blocks=dict(correction['effective_blocks'],**{label:block+1 for label in newly}),
                        detected_at=now.isoformat(),source_observed_at=observed)
        event=dict(plan_id=plan['plan_id'],revision=plan['revision'],detected_block=block,
                   effective_from_block=block+1,excluded=newly,source_observed_at=observed,created_at=now.isoformat())
        with db.transaction() as conn:
            db.put('metadata','smart-correction-event:'+fingerprint([suffix,block,newly]),event,conn)
            db.put('metadata',key,correction,conn)
    return correction


def epoch_policy(db, plan, now, epoch):
    if plan.get('smart_strategy_version') == STRATEGY_VERSION:
        return bidirectional_policy(db, plan, now, epoch)
    suffix = plan['plan_id'] + ':' + str(plan['revision'])
    key = 'smart-policy:' + suffix + ':' + str(epoch)
    pending_key = 'smart-pending:' + suffix
    existing = db.get('metadata', key)
    previous = db.get('metadata', 'smart-policy:' + suffix + ':' + str(epoch-1)) or {}
    pending = db.get('metadata', pending_key) or {}
    if epoch:
        online = db.get('metadata', 'daily_online_context') or {}
        coverage = online.get('learning_coverage') or {}
        observed = coverage.get('observed_at')
        end = instant(plan['starts_at']) + timedelta(hours=48 * epoch)
        complete = (coverage.get('query_complete') is True and 'gap_events' in coverage and coverage.get('unscoped_time_gaps') is False
                    and observed is not None and instant(observed) >= end)
        if complete and (pending.get('assessed_epoch',-1) < epoch-1 or pending.get('observed_at') != observed):
            operations, windows = db.all('operations'), db.all('actual_price_windows')
            groups = {g: observed_blocks(plan, operations, online.get('actual_outcomes', []), windows, instant(observed), epoch=epoch-1, group=g)
                      for g in ('console', 'pc')}
            for group, rows in groups.items():
                scope_gaps(plan,rows,group,epoch-1,coverage)
            results = {g: assess(rows, complete=True) for g,rows in groups.items()}
            winners = {r['winner'] for r in results.values() if r['winner']}
            winner = next(iter(winners)) if len(winners)==1 and all(
                results[g]['winner'] in winners or len(rows)==16 and all(row['no_space'] for row in rows)
                for g,rows in groups.items()) else None
            excluded = sorted(set(previous.get('excluded', [])) | set(pending.get('excluded', [])) |
                              {label for result in results.values() for label in result['excluded']})
            if winner in excluded:
                winner = None
            pending = dict(status='OBSERVED_WINNER' if winner else 'WAITING_MORE_DATA', winner=winner,
                           excluded=excluded, assessed_epoch=epoch-1, observed_at=observed, group_results=results,
                           causal_effect_estimated=False,
                           coverage_basis='actual_same_order_cost_complete_in_compared_intervals')
            db.put('metadata', pending_key, pending)
    if existing:
        return existing
    correction = db.get('metadata', 'smart-correction:' + suffix) or {}
    excluded = sorted(set(previous.get('excluded', [])) | set(pending.get('excluded', [])) |
                      {label for label,block in correction.get('effective_blocks', {}).items() if block <= epoch * 16})
    policy = dict(status='WAITING_MORE_DATA', winner=None, excluded=excluded, causal_effect_estimated=False)
    if pending:
        policy.update(pending, excluded=excluded)
    elif previous.get('winner') and previous['winner'] not in excluded:
        policy.update(status='PREVIOUS_OBSERVED_WINNER', winner=previous['winner'])
    db.put('metadata', key, policy)
    return policy


def effective_key(evidence, action, only_group=None):
    from .engine import GROUPS, package_100k, render
    prices = {}
    for group, platforms in GROUPS.items():
        if only_group and group != only_group:
            continue
        for platform in platforms:
            tier = package_100k(evidence['promotion_envelope']['packages'][platform])
            unit = Decimal(action['base_prices'][group]) / 100
            prices['global:' + platform] = render(unit, tier)['delivered_unit_100k']
            for region in evidence.get('regional_controls', []):
                if platform in region['platforms']:
                    key = str(region['region_id']) + ':' + platform
                    factor = action.get('region_coefficients', {}).get(key, region['factor'])
                    prices[key] = render(unit, tier, factor)['delivered_unit_100k']
    return fingerprint(prices)


def candidate_or_baseline(evidence, plan, current, baseline, label, now):
    if plan.get('smart_strategy_version') == STRATEGY_VERSION:
        requested = label if isinstance(label, dict) else {g:label for g in ('console','pc')}
        chosen, reasons = dict(requested), {}
        for group in ('console','pc'):
            group_labels={g:requested.get(g,'A') if g==group else 'A' for g in ('console','pc')}
            try:
                build_candidate(evidence,plan,current,baseline,group_labels,now)
            except ValueError as error:
                if requested.get(group,'A')=='A' or str(error) not in {'NO_SAFE_COMMIT_PATH', 'pricing_hard_margin_floor',
                        'pricing_average_catalog_margin_floor', 'pricing_catalog_hard_margin_floor',
                        'INFEASIBLE_REGION_FINANCIAL_AND_BASE_PRICE', 'INFEASIBLE_REGION_COEFFICIENT_AND_COMPETITIVE_BAND'}:
                    raise
                chosen[group]='A'
                reasons[group]=str(error)
        result=build_candidate(evidence,plan,current,baseline,chosen,now)
        result['smart_reasons_by_group']=reasons
        if reasons:
            result['smart_reason']='PLATFORM_LEGAL_BASELINE_FALLBACK'
        return result
    try:
        return build_candidate(evidence, plan, current, baseline, label, now)
    except ValueError as error:
        if label == 'A' or str(error) not in {'NO_SAFE_COMMIT_PATH', 'pricing_hard_margin_floor',
                              'pricing_average_catalog_margin_floor',
                              'INFEASIBLE_REGION_FINANCIAL_AND_BASE_PRICE',
                              'INFEASIBLE_REGION_COEFFICIENT_AND_COMPETITIVE_BAND'}:
            raise
        result = build_candidate(evidence, plan, current, baseline, 'A', now)
        result['smart_reason'] = str(error)
        return result


def build_candidate(evidence, plan, current, baseline, label, now):
    from . import engine
    action = deepcopy(baseline['action'])
    markets = baseline['market_comparison']
    labels = label if isinstance(label,dict) else {g:label for g in engine.GROUPS}
    for group, platforms in engine.GROUPS.items():
        if 'base:' + group not in plan['resources']:
            continue
        market = markets.get(group, {})
        tiers = {p: engine.package_100k(evidence['promotion_envelope']['packages'][p]) for p in platforms}
        anchors = {p: (market.get('anchors', {}).get(p) or {}).get('unit_100k') for p in platforms}
        action['base_prices'][group] = candidates(action['base_prices'][group], tiers, anchors,
                    version=plan.get('smart_strategy_version','smart-v1'))[labels.get(group,'A')]
        if plan.get('smart_strategy_version')==STRATEGY_VERSION and labels.get(group)=='B':
            floor=max(engine.required_base_bound(evidence,p,now,plan) for p in platforms)
            action['base_prices'][group]=str(min(Decimal(baseline['action']['base_prices'][group]),max(floor,Decimal(action['base_prices'][group]))))
    unchanged = all(Decimal(action['base_prices'][g]) == Decimal(baseline['action']['base_prices'][g]) for g in engine.GROUPS)
    no_uplift = any(v!='A' for v in labels.values()) and unchanged
    regional = {}
    for control in evidence.get('regional_controls', []):
        p = control['platforms'][0]
        key = str(control['region_id']) + ':' + p
        if control['resource'] not in plan['resources']:
            continue
        group = 'pc' if p == 'PC' else 'console'
        market = engine.competition(evidence, [p], now, region=21, plan=plan,
                                    resolved_global=markets[group], base_total=action['base_prices'][group])
        regional[key] = market
        factors = market.get('legal_coefficients') or []
        if not factors:
            raise ValueError('INFEASIBLE_REGION_COEFFICIENT_AND_COMPETITIVE_BAND')
        old = Decimal(action['region_coefficients'].get(key, '1'))
        action['region_coefficients'][key] = min(factors, key=lambda f: abs(Decimal(f) - old))
    regions = engine.proof_regions(evidence, current, action, promised_regions=regional)
    proof = engine.financial(evidence, action, now, regions=regions)
    capped = deepcopy(markets)
    for market in capped.values():
        for platform, target in list(market['targets'].items()):
            group = 'pc' if platform == 'PC' else 'console'
            tier = engine.package_100k(evidence['promotion_envelope']['packages'][platform])
            p0 = Decimal(engine.render(Decimal(baseline['action']['base_prices'][group]) / 100, tier)['delivered_unit_100k'])
            if p0 > Decimal(target['anchor_unit_100k']) * Decimal('1.03'):
                del market['targets'][platform]
                continue
            target['unit_high'] = str(Decimal(target['anchor_unit_100k']) * Decimal('1.03'))
        if market['targets']:
            market['decision_type'] = 'competitive'
    steps = engine.commit_path(current, action, lambda a: engine.financial(evidence, a, now, regions=regions),
        transition=lambda old, new: engine.preserve_competitive_state(evidence, old, new, capped, regional))
    result = deepcopy(baseline)
    positions = {}
    for scope, market in list(markets.items()) + list(regional.items()):
        positions[scope] = {}
        for platform, target in market['targets'].items():
            key = scope if ':' in scope else 'global:' + platform
            actual = Decimal(proof['prices'][key]['price']['delivered_unit_100k'])
            positions[scope][platform] = dict(actual_unit_100k=str(actual), anchor=market['anchors'][platform],
                actual_undercut_pct=str((1 - actual / Decimal(target['anchor_unit_100k'])) * 100),
                difference_pct={q['source']:str((actual / Decimal(q['unit_100k']) - 1) * 100) for q in market['quotes'] if q['platform'] == platform},
                competitive_band_met=Decimal(target['unit_low']) <= actual <= Decimal(target['unit_high']))
        for platform, available in market['competition_available'].items():
            if not available:
                positions[scope][platform] = dict(competition_available=False, competitive_band_met=False, reason='BOTH_COMPETITOR_QUOTES_MISSING')
    result.update(action=action, action_sha256=fingerprint(action), financial_proof=proof, steps=steps,
                  regional_market_comparison=regional, market_position=positions,
                  decision_type=baseline.get('decision_type') if unchanged else 'smart',
                  decision_reason=baseline.get('decision_reason') if unchanged else 'SMART_' + (label if isinstance(label,str) else '_'.join(g+'_'+v for g,v in sorted(labels.items()))), smart_baseline_action=baseline['action'],
                  score=engine.score('revenue_sprint', action, evidence, proof, plan.get('price_anchor') or current,
                                     parameters=plan.get('parameters')))
    if no_uplift:
        result['smart_reason'] = 'NO_PRICE_DIFFERENCE' if plan.get('smart_strategy_version')==STRATEGY_VERSION else 'NO_UPLIFT_SPACE'
    return result


def candidates(p0, tiers, anchors, *, version='smart-v1'):
    from .engine import render
    if not tiers:
        raise ValueError('pricing_smart_platforms_missing')
    base = Decimal(p0)
    def within(value):
        return all(anchors.get(p) is not None and
                   Decimal(render(value / 100, tier)['delivered_unit_100k']) <= Decimal(anchors[p]) * Decimal('1.03')
                   for p, tier in tiers.items())
    result = {'A': str(base)}
    factors = (('B', Decimal('.97')), ('C', Decimal('1.03'))) if version == STRATEGY_VERSION else (('B', Decimal('1.03')), ('C', Decimal('1.06')))
    for label, factor in factors:
        desired = (base * factor).quantize(Decimal('.01'), rounding=ROUND_UP if factor<1 else ROUND_DOWN)
        if factor < 1:
            result[label] = str(desired)
            continue
        if not within(base):
            result[label] = str(base)
            continue
        low, high = int(base * 100), int(desired * 100)
        while low < high:
            mid = (low + high + 1) // 2
            if within(Decimal(mid) / 100):
                low = mid
            else:
                high = mid - 1
        result[label] = str((Decimal(low) / 100).quantize(Decimal('.01')))
    return result


def assignment(plan, now, *, policy=None, correction=None):
    if plan.get('smart_strategy_version') == STRATEGY_VERSION:
        return bidirectional_assignment(plan, now, policy=policy, correction=correction)
    start = instant(plan['starts_at'])
    block = int((now - start).total_seconds() // (3 * 3600))
    if block < 0:
        raise ValueError('pricing_smart_plan_not_started')
    epoch, slot = divmod(block, 16)
    seed = fingerprint([plan['plan_id'], plan['revision'], epoch, 'smart-v1'])
    rng = random.Random(seed)
    policy = policy or {}
    winner, excluded = policy.get('winner'), set(policy.get('excluded') or [])
    if winner in ('B', 'C') and winner not in excluded:
        other = 'C' if winner == 'B' else 'B'
        schedule = [winner] * (13 if other in excluded else 12) + ['A'] * 3 + ([] if other in excluded else [other])
        rng.shuffle(schedule)
    else:
        pairs = [('A', 'B')] * 4 + [('A', 'C')] * 2 + [('B', 'C')] * 2
        rng.shuffle(pairs)
        pairs = [pair if rng.randrange(2) == 0 else pair[::-1] for pair in pairs]
        schedule = [pair[0] for pair in pairs]+[pair[1] for pair in pairs]
        schedule = ['A' if label in excluded else label for label in schedule]
    label = schedule[slot]
    original_label = label
    effective_blocks = (correction or {}).get('effective_blocks') or {name:(correction or {}).get('effective_from_block',block+1) for name in (correction or {}).get('excluded', [])}
    corrected = any(block >= start for start in effective_blocks.values())
    if label in effective_blocks and block >= effective_blocks[label]:
        label = 'A'
    probabilities = ({name:('1' if name == label else '0') for name in 'ABC'} if corrected else
                     {name:str(Decimal(schedule.count(name))/16) for name in 'ABC'})
    return dict(epoch=epoch, block=block, slot=slot, label=label, seed=seed,
                original_label=original_label, randomization_verified=not corrected,
                marginal_probabilities=probabilities,
                schedule=schedule,
                starts_at=(start + timedelta(hours=3 * block)).isoformat(),
                ends_at=(start + timedelta(hours=3 * (block + 1))).isoformat())


def bidirectional_assignment(plan, now, *, policy=None, correction=None):
    policy, correction = policy or {}, correction or {}
    groups = {}
    for group in ('console', 'pc'):
        legacy = dict(plan, starts_at=strategy_start(plan).isoformat(), smart_strategy_version='smart-v1',
                      plan_id=plan['plan_id']+':'+STRATEGY_VERSION+':'+group)
        info = assignment(legacy, now, policy=(policy.get('group_results') or {}).get(group),
                          correction=(correction.get('groups') or {}).get(group))
        repairs = (policy.get('repairs_by_group') or {}).get(group, {})
        schedule = list(info['schedule'])
        for slot, repair in repairs.items():
            schedule[int(slot)] = repair['label']
        repair = repairs.get(str(info['slot']))
        if repair:
            label = repair['label']
            stops = ((correction.get('groups') or {}).get(group) or {}).get('effective_blocks', {})
            if label in stops and info['block'] >= stops[label]:
                label = 'A'
            info.update(label=label, original_label=repair['label'], randomization_verified=False,
                        marginal_probabilities={name:'1' if name==label else '0' for name in 'ABC'})
        info['schedule'] = schedule
        info['pair_id'] = repair['pair_id'] if repair else str(info['epoch'])+':'+str(info['slot']%8)
        groups[group] = info
    result = dict(groups['console'])
    labels = {g:info['label'] for g,info in groups.items()}
    result.update(strategy_version=STRATEGY_VERSION, revision=plan['revision'], group_labels=labels,
                  label=next(iter(set(labels.values()))) if len(set(labels.values()))==1 else 'MIXED',
                  group_pair_ids={g:info['pair_id'] for g,info in groups.items()},
                  group_schedules={g:info['schedule'] for g,info in groups.items()},
                  group_probabilities={g:info['marginal_probabilities'] for g,info in groups.items()},
                  randomization_verified=all(info['randomization_verified'] for info in groups.values()))
    return result


def missing_repeats(db, plan, epoch, rows_by_group, *, excluded_by_group=None):
    """Reserve same-clock retries by execution coverage only, before viewing financial results."""
    repairs = {g:{} for g in ('console','pc')}
    for group, rows in rows_by_group.items():
        expected, seen = {}, {}
        for old_epoch in range(epoch):
            old = db.get('metadata','smart-policy:'+policy_suffix(plan)+':'+str(old_epoch))
            if old is None:
                continue
            for slot in range(16):
                info = assignment(plan,strategy_start(plan)+timedelta(hours=48*old_epoch+3*slot),policy=old)
                pair_id = info['group_pair_ids'][group]
                expected.setdefault(pair_id,dict(clock_slot=slot%8,labels=set()))['labels'].add(info['group_labels'][group])
        for row in sorted(rows,key=lambda r:(r['epoch'],r['slot'])):
            if Decimal(row['hours']) >= 2:
                seen.setdefault(row['pair_id'],{}).setdefault(row['label'],[]).append(row)
        for pair_id, pair in expected.items():
            labels = pair['labels']
            if 'A' not in labels or len(labels)!=2 or labels & set((excluded_by_group or {}).get(group,[])):
                continue
            observed = seen.get(pair_id,{})
            # Same-price execution is disclosed as unavailable exploration, never a price experiment.
            if any(row.get('has_no_space') for attempts in observed.values() for row in attempts):
                continue
            missing = [label for label in sorted(labels) if label not in observed]
            if not missing:
                a,b = [observed[label] for label in sorted(labels)]
                if paired_exposure(a,b) is None:
                    missing=list(sorted(labels))
            for label in missing:
                slot = next((s for s in (pair['clock_slot'],pair['clock_slot']+8) if str(s) not in repairs[group]),None)
                if slot is not None:
                    repairs[group][str(slot)]=dict(label=label,pair_id=pair_id)
    return repairs


def bidirectional_policy(db, plan, now, epoch):
    suffix = policy_suffix(plan)
    key, pending_key = 'smart-policy:'+suffix+':'+str(epoch), 'smart-pending:'+suffix
    existing = db.get('metadata',key)
    previous = db.get('metadata','smart-policy:'+suffix+':'+str(epoch-1)) or {}
    pending = db.get('metadata',pending_key) or {}
    online = db.get('metadata','daily_online_context') or {}
    coverage = online.get('learning_coverage') or {}
    observed = coverage.get('observed_at')
    checkpoint = strategy_start(plan)+timedelta(hours=48*epoch)
    operations,windows = db.all('operations'),db.all('actual_price_windows')
    cutoff=min(now,instant(observed)) if observed else now
    groups={g:observed_blocks(plan,operations,online.get('actual_outcomes',[]),windows,cutoff,epoch=None,group=g)
            for g in ('console','pc')}
    complete=(epoch>0 and coverage.get('query_complete') is True and 'gap_events' in coverage and
              coverage.get('unscoped_time_gaps') is False and observed and instant(observed)>=checkpoint)
    if complete:
        results={}
        for group,rows in groups.items():
            scope_gaps(plan,rows,group,None,coverage)
            result=assess(rows,complete=True)
            prior=(pending.get('group_results') or previous.get('group_results') or {}).get(group,{})
            result['excluded']=sorted(set(result['excluded']) | set(prior.get('excluded',[])))
            if result['winner'] in result['excluded']:
                result.update(winner=None,status='WAITING_MORE_DATA')
            results[group]=result
        pending=dict(group_results=results,assessed_epoch=epoch-1,observed_at=observed,
                     strategy_version=STRATEGY_VERSION,causal_effect_estimated=False)
        db.put('metadata',pending_key,pending)
    if existing:
        return existing
    policy=dict(pending or previous)
    policy.update(strategy_version=STRATEGY_VERSION,causal_effect_estimated=False)
    correction=db.get('metadata','smart-correction:'+suffix) or {}
    policy['group_results']=deepcopy(policy.get('group_results') or {})
    for group in ('console','pc'):
        result=policy['group_results'].setdefault(group,dict(winner=None,excluded=[],status='WAITING_MORE_DATA'))
        stops=((correction.get('groups') or {}).get(group) or {}).get('effective_blocks',{})
        result['excluded']=sorted(set(result['excluded']) | {label for label,block in stops.items() if block<=epoch*16})
        if result['winner'] in result['excluded']:
            result.update(winner=None,status='WAITING_MORE_DATA')
    # Repair eligibility uses wall-clock exposure, including when the sales feed is late.
    execution={g:observed_blocks(plan,operations,[],windows,now,epoch=None,group=g) for g in ('console','pc')}
    policy['repairs_by_group']=missing_repeats(db,plan,epoch,execution,
                    excluded_by_group={g:r['excluded'] for g,r in policy['group_results'].items()})
    db.put('metadata',key,policy)
    return policy


def bidirectional_correction(db, plan, now, block):
    key='smart-correction:'+policy_suffix(plan)
    correction=deepcopy(db.get('metadata',key) or dict(groups={}))
    online=db.get('metadata','daily_online_context') or {}
    coverage=online.get('learning_coverage') or {}
    observed=coverage.get('observed_at')
    if not (coverage.get('query_complete') is True and 'gap_events' in coverage and
            coverage.get('unscoped_time_gaps') is False and observed):
        return correction
    operations,windows=db.all('operations'),db.all('actual_price_windows')
    changed=False
    for group in ('console','pc'):
        rows=observed_blocks(plan,operations,online.get('actual_outcomes',[]),windows,min(now,instant(observed)),epoch=None,group=group)
        scope_gaps(plan,rows,group,None,coverage)
        stops=correction['groups'].setdefault(group,dict(effective_blocks={}))['effective_blocks']
        for label in assess(rows,complete=True)['excluded']:
            if label not in stops:
                stops[label]=block+1
                changed=True
    if changed:
        correction.update(detected_at=now.isoformat(),source_observed_at=observed)
        with db.transaction() as conn:
            db.put('metadata',key+':event:'+str(block),dict(correction,detected_block=block),conn)
            db.put('metadata',key,correction,conn)
    return correction
