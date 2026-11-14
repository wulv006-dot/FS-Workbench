"""Stable randomized three-hour policy blocks, independent of hourly prices."""
from datetime import timedelta
from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import random

from .financial import fingerprint, instant

from .platforms import SMART_VERSION, SMART_VERSIONS, groups_for, action_key, native_resources

STRATEGY_VERSION = SMART_VERSION


def strategy_start(plan):
    return instant(plan['smart_started_at'] if plan.get('smart_strategy_version') in SMART_VERSIONS else plan['starts_at'])


def policy_suffix(plan):
    suffix = plan['plan_id'] + ':' + str(plan['revision'])
    return suffix + ':' + plan['smart_strategy_version'] if plan.get('smart_strategy_version') in SMART_VERSIONS else suffix


def observe_display(db, plan, evidence, now):
    """Record observed display transitions, never a guessed launch or a financial discount."""
    if plan.get('smart_strategy_version') not in SMART_VERSIONS:
        return None
    metadata_key='smart-display:'+policy_suffix(plan)
    saved=db.get('metadata',metadata_key)
    rows=(evidence.get('storefront') or {}).get('rows') or {}
    if saved is None and not any('display_status' in row for row in rows.values()):
        return None  # Original fixtures and uninstrumented historical replay retain their contract.
    context=deepcopy(saved or dict(groups={},historical_status='historical_unobserved'))
    def known_time(row):
        if not (row.get('status')=='ok' and row.get('display_status')=='verified' and
                isinstance(row.get('display_regime_key'),str) and len(row['display_regime_key'])==64):return None
        try:
            observed=instant(row['display_observed_at'])
            return observed if observed==instant(row['checked_at']) and observed<=now else None
        except (KeyError,TypeError,ValueError):
            return None  # Invalid display evidence does not invalidate the regular price.
    for group, platforms in groups_for(plan).items():
        selected=[rows.get(p,{}) for p in platforms]
        stamps=[known_time(row) for row in selected]
        known=all(stamps)
        # Failed refreshes retain old row timestamps. Date unknown evidence by this
        # frozen collection, while known terms start only at their real page observation.
        at=max(stamps) if known else instant(evidence['checked_at']) if evidence.get('checked_at') else now
        key=fingerprint({p:row['display_regime_key'] for p,row in zip(platforms,selected)}) if known else None
        if known and plan.get('smart_strategy_version')==STRATEGY_VERSION:
            specifications={}
            for platform in platforms:
                tiers=((evidence.get('promotion_envelope') or {}).get('packages',{}).get(platform) or {}).get('tiers',[])
                tier=next((t for t in tiers if Decimal(str(t.get('base_k',0)))==100),None)
                specifications[platform]={field:format(Decimal(str(tier[field])).normalize(),'f') for field in ('base_k','bonus_k')} if tier else None
            key=fingerprint(dict(display_terms_key=key,package_specifications=specifications))
        state=context['groups'].setdefault(group,dict(key=None,segments=[]))
        segments=state['segments']
        if segments and at<=instant(segments[-1]['last_seen']):
            continue  # An older frozen quote cannot rewrite a newer observed boundary.
        if segments and key==state['key']:
            segments[-1]['last_seen']=at.isoformat()
        else:
            if segments:segments[-1]['end']=segments[-1]['last_seen']
            segments.append(dict(key=key,start=at.isoformat(),last_seen=at.isoformat()))
        state['key']=key
    if context!=saved:db.put('metadata',metadata_key,context)
    return context


def display_intervals(display, group, begin, end):
    if display is None:return [(begin,end)]
    state=display['groups'][group]
    if state['key'] is None:return []
    return [(max(begin,instant(segment['start'])),min(end,instant(segment['end']) if segment.get('end') else end))
            for segment in state['segments'] if segment['key']==state['key'] and
            min(end,instant(segment['end']) if segment.get('end') else end)>max(begin,instant(segment['start']))]


def display_suffix(plan, display, group):
    return policy_suffix(plan)+':display:'+group+':'+(display['groups'][group]['key'] or 'unknown')


def policy_key(plan, epoch, policy=None):
    keys=(policy or {}).get('display_group_keys')
    suffix=policy_suffix(plan)+(':display:'+fingerprint(keys) if keys is not None else '')
    return 'smart-policy:'+suffix+':'+str(epoch)


def observed_blocks(plan, operations, outcomes, windows, now, *, epoch, group=None, display=None):
    if plan.get('smart_strategy_version') in SMART_VERSIONS and group not in groups_for(plan):
        raise ValueError('pricing_smart_platform_required')
    group_filter = group
    windows_by_id = {w['operation_id']: w for w in windows}
    confirmed = sorted((o for o in operations if o.get('status') in ('COMPLETED', 'NO_CHANGE') and o.get('completed_at')),
                       key=lambda o: instant(o['completed_at']))
    if plan.get('smart_strategy_version')==STRATEGY_VERSION:
        # A write to another platform neither confirms nor terminates this exposure.
        def confirms(op):
            resources=native_resources((op.get('bundle') or {}).get('mutable_resources',op.get('resources',[])))
            return 'base:'+group in resources or any(r.startswith('region:') and r.endswith(':'+group) for r in resources)
        confirmed=[op for op in confirmed if confirms(op)]
    blocks = {}
    for index, op in enumerate(confirmed):
        info = (op.get('bundle') or {}).get('smart_assignment') or {}
        effective = (info.get('group_keys') or {}).get(group_filter) if group_filter else info.get('effective_key')
        if (op.get('plan_id') != plan['plan_id'] or epoch is not None and info.get('epoch') != epoch or not effective or
                plan.get('smart_strategy_version') in SMART_VERSIONS and
                (info.get('strategy_version') != plan.get('smart_strategy_version') or info.get('revision') != plan['revision'])):
            continue
        begin = max(instant(op['completed_at']), instant(info['starts_at']))
        end = min(now, instant(info['ends_at']))
        for later in confirmed[index + 1:]:
            if set(native_resources(op.get('resources', plan.get('resources', [])))) & set(native_resources(later.get('resources', plan.get('resources', [])))):
                end = min(end, instant(later['completed_at']))
                break
        if end <= begin or instant(info['ends_at']) > now:
            continue
        intervals=display_intervals(display,group_filter,begin,end)
        if not intervals:continue
        slot = info['slot']
        label = (info.get('group_labels') or {}).get(group_filter, info['label'])
        block = blocks.setdefault((info['epoch'], slot), dict(slot=slot, epoch=info['epoch'], block=info.get('block',slot),
                    starts_at=info['starts_at'], label=label, hours=Decimal(0), orders=0,
                    net=Decimal(0), gross=Decimal(0), uncovered=Decimal(0), new_keys=set(),
                    complete=True, customer_complete=True, prices=set(), intervals=[], events=[], no_space=True, has_no_space=False))
        if info.get('strategy_version') in SMART_VERSIONS:
            block['pair_id'] = info['group_pair_ids'][group_filter]
        if display is not None:block['display_regime_key']=display['groups'][group_filter]['key']
        if group_filter:
            block['no_space'] = block['no_space'] and (info.get('no_space_by_group') or {}).get(group_filter) is True
            if label != 'A':
                block['has_no_space'] = block['has_no_space'] or (info.get('merged_with_A_by_group') or {}).get(group_filter) is not False
        block_start=instant(info['starts_at'])
        block['intervals'].extend([[(start-block_start).total_seconds(), (stop-block_start).total_seconds()] for start,stop in intervals])
        block['hours'] += sum(Decimal(str((stop-start).total_seconds()))/3600 for start,stop in intervals)
        block['prices'].add(effective)
        for row in outcomes:
            if not any(start <= instant(row['occurred_at']) < stop for start,stop in intervals):
                continue
            window = windows_by_id.get(row.get('price_window_id'))
            group = row.get('price_group') or row['group']
            base = row.get('platform') if plan.get('smart_strategy_version')==STRATEGY_VERSION and row.get('platform') in groups_for(plan) else group if group in groups_for(plan) else group.rsplit(':',1)[-1] if plan.get('smart_strategy_version')==STRATEGY_VERSION else 'pc' if group.endswith(':PC') else 'console'
            if group_filter and base != group_filter:
                continue
            actual_action = (window or {}).get('action') or {}
            op_action = op['bundle']['action']
            actual_key=action_key(actual_action,base) if base in ('PS','XBOX','PC') else base
            if (actual_key not in actual_action.get('base_prices', {}) or
                    Decimal(actual_action['base_prices'][actual_key]) != Decimal(op_action['base_prices'][base]) or
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


def observed_curve_blocks(plan, platform, state, online, windows, now):
    """Slice confirmed V6 exposure at assignment and actual price boundaries."""
    from .business_source import OBSERVED_PRICE_WINDOWS, _window_decision_key, _window_end
    from .curve_strategy_v6 import ANCHORS, comparison_background_key, segment_reference_id
    from .platforms import native_resources
    from .price_curve import curve_key

    coverage = online.get('learning_coverage') or {}
    if (online.get('smart_plan_id') != plan['plan_id'] or online.get('smart_revision') != plan['revision']
            or coverage.get('query_complete') is not True or coverage.get('unscoped_time_gaps') is not False
            or 'gap_events' not in coverage or not coverage.get('observed_at') or not coverage.get('source_sha256')):
        return []
    cutoff = min(now, instant(coverage['observed_at']))
    resource = 'base:' + platform
    scoped = [window for window in windows if resource in native_resources(window.get('mutable_resources', []))]
    outcomes = {}
    for row in online.get('actual_outcomes', []):
        if row.get('platform') == platform:
            outcomes.setdefault(row.get('price_window_id'), []).append(row)
    gaps = [gap for gap in coverage['gap_events'] if gap.get('group') is None or
            gap['group'].rsplit(':', 1)[-1] == platform]
    blocks = {}
    for window in scoped:
        curve = (window['action'].get('curves') or {}).get(platform)
        if (window.get('write_protocol') != 'fc27_curve_v6' or not curve or
                window.get('mode') != 'production' or window.get('origin') not in OBSERVED_PRICE_WINDOWS):
            continue
        opened = instant(window['opened_at'])
        entries = [(opened, (window.get('curve_selection') or {}).get(platform))]
        entries.extend((instant(row['at']), (row.get('curve_selection') or {}).get(platform))
                       for row in window.get('continuations', []) if resource in row['resources'])
        entries.sort(key=lambda entry: entry[0])
        if not any(selection and selection.get('assignment') for _, selection in entries):
            continue
        closed = _window_end(window, platform, scoped, cutoff, platform=platform)
        actual_key = curve_key(curve)
        decision_key = _window_decision_key(window, platform, actual_key)
        for index, (at, selection) in enumerate(entries):
            info = (selection or {}).get('assignment') or {}
            segment = info.get('segment')
            if (segment not in ANCHORS or info.get('plan_id') != plan['plan_id']
                    or info.get('revision') != plan['revision'] or info.get('platform') != platform
                    or info.get('comparison_episode_id') != state['episode']['comparison_episode_id']
                    or info.get('reference_curve_id') != segment_reference_id(state['reference'], segment)):
                continue
            start = instant(info['starts_at'])
            end = instant(info['ends_at'])
            if end > cutoff:
                continue
            begin = max(opened, at, start)
            stop = min(closed, end, entries[index + 1][0]) if index + 1 < len(entries) else min(closed, end)
            if stop <= begin:
                continue
            label = info['actual_label']
            background = comparison_background_key(curve, segment)
            block = blocks.setdefault((segment, info['block']), dict(segment=segment, block=info['block'],
                epoch=info['epoch'], slot=info['slot'], pair_id=info['pair_id'], starts_at=info['starts_at'],
                ends_at=info['ends_at'], label=label, display_regime_key=info['background_curve_key'],
                hours=Decimal(0), intervals=[], prices=set(), events={}, complete=True, window_ids=set()))
            if (block['label'] != label or block['display_regime_key'] != info['background_curve_key']
                    or info['background_curve_key'] != background
                    or info['primary_curve_key'] != actual_key
                    or info['decision_curve_key'] not in (actual_key, decision_key)):
                block['complete'] = False
            block['intervals'].append([(begin-start).total_seconds(), (stop-start).total_seconds()])
            block['hours'] += Decimal(str((stop-begin).total_seconds())) / 3600
            block['prices'].add(actual_key)
            block['window_ids'].add(window['operation_id'])
            if any(begin <= instant(gap['occurred_at']) < stop for gap in gaps):
                block['complete'] = False
            for row in outcomes.get(window['operation_id'], ()):
                occurred = instant(row['occurred_at'])
                if not begin <= occurred < stop:
                    continue
                if row.get('curve_key') != actual_key or row.get('decision_curve_key') != decision_key:
                    block['complete'] = False
                    continue
                event = dict(row, offset=(occurred-start).total_seconds())
                identity = row['order_key']
                if identity in block['events'] and block['events'][identity] != event:
                    block['complete'] = False
                block['events'][identity] = event
    for block in blocks.values():
        block['complete'] = block['complete'] and len(block['prices']) == 1
        block['prices'] = sorted(block['prices'])
        block['window_ids'] = sorted(block['window_ids'])
        block['events'] = list(block['events'].values())
    return list(blocks.values())


def _curve_block_summary(block):
    from .price_curve import coin_quantity_band

    def summarize(rows):
        cost_basis = 'same_order_Order_shipping_CNY_margin_at_actual_USD_receipt'
        cost_rows = [r for r in rows if r.get('cost_basis') == cost_basis
                     and r.get('actual_contribution_usd') is not None and r.get('actual_net_usd') is not None]
        totals = {}
        for field in ('actual_net_usd', 'purchase_k', 'promised_bonus_k', 'promised_delivered_k'):
            totals[field] = (str(sum(Decimal(r[field]) for r in rows))
                             if block['complete'] and all(r.get(field) is not None for r in rows) else None)
        net = totals['actual_net_usd']
        gross = sum(Decimal(r['actual_contribution_usd']) for r in cost_rows)
        totals.update(orders=len(rows) if block['complete'] else None, cost_covered_orders=len(cost_rows),
                      procurement_gross_usd=str(gross) if net is not None and len(cost_rows) == len(rows) else None,
                      procurement_margin=str(gross / Decimal(net)) if net and Decimal(net) > 0
                      and len(cost_rows) == len(rows) else None)
        return totals

    rows = block['events']
    summary = {key: value for key, value in block.items() if key not in ('events', 'intervals', 'hours')}
    summary.update(hours=str(block['hours']), platform=summarize(rows),
                   segments={segment: summarize([row for row in rows if row.get('purchase_k') is not None
                                                 and coin_quantity_band(row['purchase_k']) == segment])
                             for segment in ('small', 'large')})
    return summary


def curve_learning(plan, platform, state, online, windows, now, current):
    """Reuse the existing paired assessor, keeping procurement coverage explicit."""
    from .curve_strategy_v6 import ANCHORS, comparison_background_key, segment_reference_id

    blocks = observed_curve_blocks(plan, platform, state, online, windows, now)
    source = online.get('learning_coverage') or {}
    result = {}
    current_epoch = curve_slot(plan, platform, state, now)['epoch']
    for segment in ANCHORS:
        rows = sorted((row for row in blocks if row['segment'] == segment), key=lambda row: row['block'])
        if not rows:
            continue
        background = comparison_background_key(current, segment)
        eligible = []
        for row in rows:
            if row['label'] not in ('A', 'B', 'C') or row['display_regime_key'] != background:
                continue
            events = [dict(event, actual_contribution_usd=None) if
                      event.get('cost_basis') != 'same_order_Order_shipping_CNY_margin_at_actual_USD_receipt'
                      else event for event in row['events']]
            eligible.append(dict(row, events=events))
        assessed = [row for row in eligible if row['epoch'] < current_epoch]
        policy = assess_strata(assessed, complete=True)
        recent = assess(eligible, complete=True)
        correction = dict(effective_blocks={label: eligible[-1]['block'] + 1 for label in recent['excluded']})
        result[segment] = dict(policy=policy, correction=correction, background_curve_key=background,
            reference_curve_id=segment_reference_id(state['reference'], segment),
            comparison_episode_id=state['episode']['comparison_episode_id'],
            assessed_epoch=current_epoch - 1,
            observed_at=source['observed_at'], source_sha256=source['source_sha256'],
            blocks=[_curve_block_summary(row) for row in rows[-2:]])
        winner = policy.get('winner')
        if winner in ('B', 'C'):
            result[segment]['adoption'] = curve_adoption_evidence(assessed, winner, state)
    return result


def curve_adoption_evidence(blocks, winner, state):
    """Use the same fixed-clock exposures used by the approved assessor."""
    by_pair = {}
    for block in blocks:
        if block['hours'] >= 2:
            by_pair.setdefault(block['pair_id'], {}).setdefault(block['label'], []).append(block)
    windows, revisions, winning_curves, cohorts, limits = set(), {}, set(), [[], []], []
    for pair in by_pair.values():
        exposure = paired_exposure(pair.get('A', []), pair.get(winner, []))
        if exposure is None:
            continue
        a, b, overlaps, _ = exposure
        if not a['complete'] or not b['complete'] or set(a['prices']) & set(b['prices']):
            continue
        winning_curves.update(b['prices'])
        for cohort, block in zip(cohorts, (a, b)):
            limits.extend((block['starts_at'], block['ends_at']))
            windows.update(block['window_ids'])
            for row in block['events']:
                if not any(start <= row['offset'] < end for start, end in overlaps):
                    continue
                fields = ('actual_net_usd', 'actual_contribution_usd', 'new_customer', 'cost_basis')
                revisions[row['order_key']] = fingerprint([row.get(key) for key in fields])
                cohort.append(row)
    if len(winning_curves) != 1 or not revisions or any(row.get('new_customer') is None or row.get('actual_contribution_usd') is None
                            for rows in cohorts for row in rows):
        return None
    def totals(rows):
        return (sum(Decimal(row['actual_net_usd']) for row in rows),
                sum(Decimal(row['actual_contribution_usd']) for row in rows),
                len({row['customer_key'] for row in rows if row['new_customer'] and row.get('customer_key')}))

    initial = state['episode']['initial_reference_curve_id']
    previous = (state['reference'].get('adoption') or {}).get('cumulative') or {}
    if previous.get('initial_reference_curve_id') != initial:
        previous = {}
    fields = ('revenue_delta_usd', 'procurement_gross_delta_usd', 'new_customer_delta')
    cumulative = {key: str(Decimal(previous.get(key, '0')) + candidate - baseline)
                  for key, baseline, candidate in zip(fields, totals(cohorts[0]), totals(cohorts[1]))}
    cumulative.update(initial_reference_curve_id=initial, evidence_ref=fingerprint([sorted(windows), revisions]))
    return dict(order_revisions=revisions, window_ids=sorted(windows), window_start=min(limits), window_end=max(limits),
                winning_curve_key=next(iter(winning_curves)),
                cost_revision=fingerprint(revisions), maturity='OBSERVED_WINNER',
                reason='matched_original_order_revenue_cost_and_customer_outcomes',
                changed_judgment='paired_observed_winner_' + winner, cumulative=cumulative)


def paired_exposure(first, second):
    for a in first:
        for b in second:
            if a.get('display_regime_key')!=b.get('display_regime_key'):continue
            overlaps=[(max(x[0],y[0]),min(x[1],y[1])) for x in a.get('intervals',[]) for y in b.get('intervals',[])
                      if min(x[1],y[1])>max(x[0],y[0])]
            hours=sum(Decimal(str(end-start)) for start,end in overlaps)/3600
            if hours>=2:
                return a,b,overlaps,hours
    return None


def assess(blocks, *, complete, minimum_both=False):
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
        if len(pairs) < 2 or sum(p[0]['orders'] for p in pairs) < 10 or minimum_both and sum(p[1]['orders'] for p in pairs)<10:
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
            gap_base=gap_group if gap_group in groups_for(plan) else gap_group.rsplit(':',1)[-1] if gap_group and plan.get('smart_strategy_version')==STRATEGY_VERSION else 'pc' if gap_group and gap_group.endswith(':PC') else 'console' if gap_group else None
            offset=(instant(gap['occurred_at'])-block_start).total_seconds()
            if gap_base in (None,group) and any(start <= offset < stop for start,stop in row['intervals']):
                if gap.get('amount_usd') is None:
                    row['complete']=False
                else:
                    row['events'].append(dict(offset=offset, gap_usd=gap['amount_usd']))


def early_correction(db, plan, now, block, *, display=None):
    if plan.get('smart_strategy_version') in SMART_VERSIONS:
        return bidirectional_correction(db, plan, now, block, display=display)
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
        for group in groups_for(plan):
            rows=observed_blocks(plan,operations,online.get('actual_outcomes',[]),windows,cutoff,epoch=prior_epoch,group=group)
            scope_gaps(plan,rows,group,prior_epoch,coverage)
            exclusions.update(assess_for(plan,rows,complete=True)['excluded'])
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


def epoch_policy(db, plan, now, epoch, *, display=None):
    if plan.get('smart_strategy_version') in SMART_VERSIONS:
        return bidirectional_policy(db, plan, now, epoch, display=display)
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
                      for g in groups_for(plan)}
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
    from .engine import package_100k, render
    if 'console' in action.get('base_prices',{}):
        from .legacy_simulation.platform_v2_financial import package_100k
        from .legacy_simulation.platform_v2_engine import render
    prices = {}
    for group, platforms in groups_for(action).items():
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
    if plan.get('smart_strategy_version') in SMART_VERSIONS:
        requested = label if isinstance(label, dict) else {g:label for g in groups_for(plan)}
        chosen, reasons = dict(requested), {}
        for group in groups_for(plan):
            group_labels={g:requested.get(g,'A') if g==group else 'A' for g in groups_for(plan)}
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
        if plan.get('smart_strategy_version') in SMART_VERSIONS and labels.get(group)=='B':
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
        group = action_key(action, p)
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
            group = action_key(action, platform)
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
        result['smart_reason'] = 'NO_PRICE_DIFFERENCE' if plan.get('smart_strategy_version') in SMART_VERSIONS else 'NO_UPLIFT_SPACE'
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
    factors = (('B', Decimal('.97')), ('C', Decimal('1.03'))) if version in SMART_VERSIONS else (('B', Decimal('1.03')), ('C', Decimal('1.06')))
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
    if plan.get('smart_strategy_version') in SMART_VERSIONS:
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


def curve_slot(plan, platform, state, now, *, learning=None):
    """Give both same-clock halves to the same band before considering sales."""
    from .curve_strategy_v6 import segment_reference_id

    episode = state['episode']
    start = max(instant(plan['starts_at']), instant(episode['opened_at']))
    block = int((now - start).total_seconds() // (3 * 3600))
    epoch, slot = divmod(block, 16)
    pair = slot % 8
    scope = [plan['plan_id'], plan['revision'], platform, episode['comparison_episode_id']]
    segment = ('small', 'large')[(int(fingerprint(scope)[-1], 16) + pair) % 2]
    reference_id = segment_reference_id(state['reference'], segment)
    learned = (learning or {}).get(segment) or {}
    if (learned.get('reference_curve_id') != reference_id
            or learned.get('comparison_episode_id') != episode['comparison_episode_id']
            or learned.get('assessed_epoch', epoch - 1) >= epoch):
        learned = {}
    policy, correction = learned.get('policy'), learned.get('correction')
    scoped = dict(plan, starts_at=start.isoformat(), smart_strategy_version='smart-v1',
                  plan_id='curve-v6:' + fingerprint([*scope, segment]))
    assigned = assignment(scoped, now, policy=policy, correction=correction)
    return dict(assigned, plan_id=plan['plan_id'], revision=plan['revision'], platform=platform,
                segment=segment, pair_id=str(epoch) + ':' + str(pair),
                comparison_episode_id=episode['comparison_episode_id'], reference_curve_id=reference_id,
                policy=policy, correction=correction, learning_source_sha256=learned.get('source_sha256'),
                learning_observed_at=learned.get('observed_at'), decision_at=now.isoformat(),
                background_curve_key=learned.get('background_curve_key'))


def bidirectional_assignment(plan, now, *, policy=None, correction=None):
    policy, correction = policy or {}, correction or {}
    groups = {}
    for group in groups_for(plan):
        legacy = dict(plan, starts_at=strategy_start(plan).isoformat(), smart_strategy_version='smart-v1',
                      plan_id=plan['plan_id']+':'+plan['smart_strategy_version']+':'+group)
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
    result = dict(next(iter(groups.values())))
    labels = {g:info['label'] for g,info in groups.items()}
    result.update(strategy_version=plan['smart_strategy_version'], revision=plan['revision'], group_labels=labels,
                  label=next(iter(set(labels.values()))) if len(set(labels.values()))==1 else 'MIXED',
                  group_pair_ids={g:info['pair_id'] for g,info in groups.items()},
                  group_schedules={g:info['schedule'] for g,info in groups.items()},
                  group_probabilities={g:info['marginal_probabilities'] for g,info in groups.items()},
                  randomization_verified=all(info['randomization_verified'] for info in groups.values()))
    return result


def missing_repeats(db, plan, epoch, rows_by_group, *, excluded_by_group=None, cache_suffix=None):
    """Reserve same-clock retries by execution coverage only, before viewing financial results."""
    repairs = {g:{} for g in groups_for(plan)}
    for group, rows in rows_by_group.items():
        expected, seen = {}, {}
        for old_epoch in range(epoch):
            old = db.get('metadata','smart-policy:'+(cache_suffix or policy_suffix(plan))+':'+str(old_epoch))
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


def bidirectional_policy(db, plan, now, epoch, *, display=None, only_group=None):
    if display is not None and only_group is None:
        parts={g:bidirectional_policy(db,plan,now,epoch,display=display,only_group=g) for g in groups_for(plan)}
        result=dict(strategy_version=plan['smart_strategy_version'],causal_effect_estimated=False,
            group_results={g:parts[g]['group_results'][g] for g in parts},
            repairs_by_group={g:parts[g]['repairs_by_group'][g] for g in parts},
            display_group_keys={g:display['groups'][g]['key'] for g in parts},
            display_policy_keys={g:'smart-policy:'+display_suffix(plan,display,g)+':'+str(epoch) for g in parts})
        db.put('metadata',policy_key(plan,epoch,result),result)
        return result
    suffix = display_suffix(plan,display,only_group) if display is not None else policy_suffix(plan)
    selected_groups=(only_group,) if only_group else tuple(groups_for(plan))
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
    groups={g:observed_blocks(plan,operations,online.get('actual_outcomes',[]),windows,cutoff,epoch=None,group=g,display=display)
            for g in selected_groups}
    complete=(epoch>0 and coverage.get('query_complete') is True and 'gap_events' in coverage and
              coverage.get('unscoped_time_gaps') is False and observed and instant(observed)>=checkpoint)
    if complete:
        results={}
        for group,rows in groups.items():
            scope_gaps(plan,rows,group,None,coverage)
            result=assess_for(plan,rows,complete=True)
            prior=(pending.get('group_results') or previous.get('group_results') or {}).get(group,{})
            result['excluded']=sorted(set(result['excluded']) | set(prior.get('excluded',[])))
            if result['winner'] in result['excluded']:
                result.update(winner=None,status='WAITING_MORE_DATA')
            results[group]=result
        pending=dict(group_results=results,assessed_epoch=epoch-1,observed_at=observed,
                     strategy_version=plan['smart_strategy_version'],causal_effect_estimated=False)
        db.put('metadata',pending_key,pending)
    if existing:
        return existing
    policy=dict(pending or previous)
    policy.update(strategy_version=plan['smart_strategy_version'],causal_effect_estimated=False)
    correction=db.get('metadata','smart-correction:'+suffix) or {}
    policy['group_results']=deepcopy(policy.get('group_results') or {})
    for group in selected_groups:
        result=policy['group_results'].setdefault(group,dict(winner=None,excluded=[],status='WAITING_MORE_DATA'))
        stops=((correction.get('groups') or {}).get(group) or {}).get('effective_blocks',{})
        result['excluded']=sorted(set(result['excluded']) | {label for label,block in stops.items() if block<=epoch*16})
        if result['winner'] in result['excluded']:
            result.update(winner=None,status='WAITING_MORE_DATA')
    # Repair eligibility uses wall-clock exposure, including when the sales feed is late.
    execution={g:observed_blocks(plan,operations,[],windows,now,epoch=None,group=g,display=display) for g in selected_groups}
    if display is not None and display['groups'][only_group]['key'] is None:
        policy['repairs_by_group']={g:{} for g in selected_groups}
    else:
        policy['repairs_by_group']=missing_repeats(db,plan,epoch,execution,
                        excluded_by_group={g:r['excluded'] for g,r in policy['group_results'].items()},cache_suffix=suffix)
    db.put('metadata',key,policy)
    return policy


def bidirectional_correction(db, plan, now, block, *, display=None, only_group=None):
    if display is not None and only_group is None:
        parts={g:bidirectional_correction(db,plan,now,block,display=display,only_group=g) for g in groups_for(plan)}
        return dict(groups={g:parts[g].get('groups',{}).get(g,dict(effective_blocks={})) for g in parts},
                    display_group_keys={g:display['groups'][g]['key'] for g in parts})
    key='smart-correction:'+(display_suffix(plan,display,only_group) if display is not None else policy_suffix(plan))
    correction=deepcopy(db.get('metadata',key) or dict(groups={}))
    online=db.get('metadata','daily_online_context') or {}
    coverage=online.get('learning_coverage') or {}
    observed=coverage.get('observed_at')
    if not (coverage.get('query_complete') is True and 'gap_events' in coverage and
            coverage.get('unscoped_time_gaps') is False and observed):
        return correction
    operations,windows=db.all('operations'),db.all('actual_price_windows')
    changed=False
    for group in ((only_group,) if only_group else tuple(groups_for(plan))):
        rows=observed_blocks(plan,operations,online.get('actual_outcomes',[]),windows,min(now,instant(observed)),epoch=None,group=group,display=display)
        scope_gaps(plan,rows,group,None,coverage)
        stops=correction['groups'].setdefault(group,dict(effective_blocks={}))['effective_blocks']
        for label in assess_for(plan,rows,complete=True)['excluded']:
            if label not in stops:
                stops[label]=block+1
                changed=True
    if changed:
        correction.update(detected_at=now.isoformat(),source_observed_at=observed)
        with db.transaction() as conn:
            db.put('metadata',key+':event:'+str(block),dict(correction,detected_block=block),conn)
            db.put('metadata',key,correction,conn)
    return correction

def assess_strata(blocks, *, complete):
    """Accumulate frozen execution pairs within fixed clock strata for low-volume platforms.

    Pair choice precedes any financial inspection. Unknown cost stays in its stratum,
    so a later profitable attempt cannot replace the original covered exposure.
    """
    by_pair = {}
    for block in sorted(blocks, key=lambda b: (b.get('epoch', 0), b.get('block', b['slot']))):
        if Decimal(str(block.get('hours', 0))) >= 2:
            pair_id = block.get('pair_id', str(block.get('epoch', 0))+':'+str(block['slot'] % 8))
            by_pair.setdefault(pair_id, {}).setdefault(block['label'], []).append(block)
    accumulated = {}
    for label in ('B', 'C'):
        for attempts in by_pair.values():
            exposure = paired_exposure(attempts.get('A', []), attempts.get(label, []))
            if exposure is None:
                continue
            a, b, overlaps, hours = exposure
            if b.get('has_no_space') or set(a['prices']) & set(b['prices']):
                continue
            slot = a['slot'] % 8
            pair = accumulated.setdefault((label, slot), [dict(events=[], hours=Decimal(0), complete=True) for _ in range(2)])
            for state, block in zip(pair, (a, b)):
                shift = float(state['hours'] * 3600)
                cursor = shift
                for start, end in overlaps:
                    for event in block.get('events', []):
                        if start <= event['offset'] < end:
                            state['events'].append(dict(event, offset=cursor + event['offset'] - start))
                    cursor += end-start
                state['hours'] += Decimal(str(hours))
                state['complete'] = state['complete'] and bool(block.get('complete'))
    synthetic = []
    incomplete={label for (label,_),pair in accumulated.items() if any(not state['complete'] or any('gap_usd' in event or event.get('actual_net_usd') is None or event.get('actual_contribution_usd') is None for event in state['events']) for state in pair)}
    for (label, slot), pair in accumulated.items():
        if label in incomplete:continue
        for arm, state in zip(('A', label), pair):
            synthetic.append(dict(state, label=arm, slot=slot, epoch=0, pair_id=label+':'+str(slot),
                                  prices=[arm], intervals=[[0, float(state['hours']*3600)]]))
    result = assess(synthetic, complete=complete, minimum_both=True)
    result['assessment_unit'] = 'fixed_clock_cumulative_stratum'
    result['clock_strata'] = {label: sum(key[0] == label for key in accumulated) for label in ('B', 'C')}
    return result


def assess_for(plan, blocks, *, complete):
    return (assess_strata if plan.get('smart_strategy_version') == STRATEGY_VERSION else assess)(blocks, complete=complete)
