"""FC Coins deterministic decisions and non-overridable purchase-margin checks."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN
from urllib.parse import urlsplit
import hashlib
import json

VERSION = 'fc-coins-decision-v2'
MARGIN_BASIS = 'undiscounted_and_historical_average_v2'
HARD_MARGIN = Decimal('10')
CENT = Decimal('.01')
STEP = Decimal('.0001')
CONSOLE = ('PS', 'XBOX')
ROUNDING_RESERVE = Decimal('.02')
REFERENCE_VERSION = 'fc-reference-weighting-20261024-v2'
REFERENCE_WEIGHTS = {'ItemD2R': Decimal('.15'), 'U7Buy': Decimal('.05')}
REFERENCE_GAP_LIMIT = Decimal('.05')
POSITION_VERSION = 'fc-owner-position-20261026-v1'


def number(value, *, zero=False):
    if value is None or isinstance(value, bool):
        raise ValueError('pricing_number_invalid')
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('pricing_number_invalid') from None
    if not n.is_finite() or n > Decimal('1e12') or n < 0 or not zero and n == 0:
        raise ValueError('pricing_number_invalid')
    return n


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def instant(value):
    text = str(value).strip()
    for pattern in ('%y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('pricing_source_time_invalid') from None
    if parsed.tzinfo is None:
        raise ValueError('pricing_source_timezone_missing')
    return parsed


def fresh(value, now, seconds=3600):
    age = (now - instant(value)).total_seconds()
    if not -5 <= age <= seconds:
        raise ValueError('pricing_source_stale')


def common_cost(evidence):
    """One console pool uses its newest verified delivery, preserving both observations."""
    records = [evidence['costs'][p] for p in CONSOLE]
    for p, row in zip(CONSOLE, records):
        if row.get('platform') != p or row.get('game') != 'FC27' or row.get('product') != 'Game Coins':
            raise ValueError('pricing_console_cost_scope')
        number(row.get('cny_per_1k'))
        if not str(row.get('record_id', '')).isdigit():
            raise ValueError('pricing_console_cost_identity')
    latest = max(records, key=lambda r: instant(r['trade_at']))
    at = instant(latest['trade_at'])
    tied = [r for r in records if instant(r['trade_at']) == at]
    if len({number(r['cny_per_1k']) for r in tied}) != 1:
        raise ValueError('pricing_console_simultaneous_cost_conflict')
    return number(latest['cny_per_1k']), dict(
        basis='newest_verified_delivery_in_user_confirmed_shared_console_pool',
        selected_platform=latest['platform'], record_id=str(latest['record_id']),
        trade_at=latest['trade_at'], cny_per_k=str(number(latest['cny_per_1k'])),
        observations=[{k:r.get(k) for k in ('platform','record_id','trade_at','checked_at','cny_per_1k')} for r in records])


def envelope_ratio(envelope, now):
    if not isinstance(envelope, dict) or envelope.get('contract') != 'fc-coins-promotion-envelope-v1':
        raise ValueError('pricing_promotions_missing')
    if envelope.get('status') != 'verified' or envelope.get('site_id') != 266 or envelope.get('game_id') != 1327:
        raise ValueError('pricing_promotions_unverified')
    fresh(envelope.get('checked_at'), now, 900)
    body = {k:v for k,v in envelope.items() if k not in ('sha256','checked_at')}
    if envelope.get('sha256') != fingerprint(body):
        raise ValueError('pricing_promotions_hash_changed')
    ratio = number(envelope.get('minimum_retained_ratio'), zero=True)
    if ratio > 1:
        raise ValueError('pricing_promotions_ratio_invalid')
    return ratio


def hard_floor(cost_cny, fx, delivered_per_base, retained_ratio, minimum='10'):
    margin = number(minimum, zero=True)
    if margin < HARD_MARGIN or margin >= 100:
        raise ValueError('pricing_hard_margin_minimum_10')
    cost = number(cost_cny) / number(fx) * number(delivered_per_base)
    ratio = number(retained_ratio, zero=True)
    if ratio > 1:
        raise ValueError('pricing_promotions_ratio_invalid')
    return (cost / (1 - margin / 100)).quantize(STEP, rounding=ROUND_CEILING)


def prove_price(unit, cost_cny, fx, delivered_k, base_k, ratio, minimum='10'):
    base, delivered = number(base_k), number(delivered_k)
    if delivered < base:
        raise ValueError('pricing_package_invalid')
    cost = number(cost_cny) / number(fx) * delivered
    gross = (number(unit) * base).quantize(CENT, rounding=ROUND_DOWN)
    ratio = number(ratio, zero=True)
    reserve=ROUNDING_RESERVE if ratio<1 else Decimal(0)
    promotional = max(Decimal(0), (gross * ratio).quantize(CENT, rounding=ROUND_DOWN)-reserve)
    hard_floor(cost_cny, fx, delivered/base, ratio, minimum)
    required = cost / (1 - number(minimum) / 100)
    if gross <= 0 or gross < required:
        raise ValueError('pricing_hard_margin_floor')
    return dict(public_usd=str(gross), undiscounted_net_usd=str(gross), margin_basis=MARGIN_BASIS,
                worst_net_usd=str(promotional), promotional_net_usd=str(promotional),
                promotional_gross_usd=str(promotional-cost),
                promotional_margin_pct=str((promotional-cost)/promotional*100) if promotional else None,
                promotions_exempt_from_margin_floor=True, rounding_reserve_usd=str(reserve), delivered_k=str(delivered),
                delivered_cost_usd=str(cost), procurement_gross_usd=str(gross-cost),
                procurement_margin_pct=str((gross-cost)/gross*100), minimum_margin_pct=str(minimum))


def catalog_floor(cost, fx, ratio, minimum, rules, *, average_ratio=None):
    margin=number(minimum,zero=True)
    hard_floor(cost,fx,1,ratio,minimum)
    qty=number(rules['min_custom_k'])
    retained=number(rules['minimum_package_retained_ratio'])
    delivered=number(rules['max_delivered_ratio'])
    if qty<1 or qty!=qty.to_integral_value() or retained>1 or not 1<=delivered<=2:
        raise ValueError('pricing_catalog_bounds_invalid')
    # At any q >= minimum, two downward cent roundings cost less than this bound.
    settlement=2*CENT/qty
    historical=number(average_ratio) if average_ratio is not None else Decimal(1)
    if historical>1:raise ValueError('pricing_historical_mix_ratio_invalid')
    unit=(number(cost)/number(fx)*delivered/(historical*(1-margin/100))+settlement)/retained
    return unit.quantize(STEP,rounding=ROUND_CEILING)


def prove_catalog(unit,cost,fx,ratio,minimum,rules, *, average_ratio=None):
    if number(unit)<catalog_floor(cost,fx,ratio,minimum,rules):raise ValueError('pricing_catalog_hard_margin_floor')
    floor=catalog_floor(cost,fx,ratio,minimum,rules,average_ratio=average_ratio)
    if number(unit)<floor:
        raise ValueError('pricing_average_catalog_margin_floor' if average_ratio is not None else 'pricing_catalog_hard_margin_floor')
    tiers=[prove_price(number(unit)*number(t['retained_ratio']),cost,fx,
                       number(t['base_k'])+number(t['bonus_k'],zero=True),
                       t['base_k'],ratio,minimum) for t in rules['tiers']]
    average_margins=[(number(t['public_usd'])*number(average_ratio)-number(t['delivered_cost_usd']))/(number(t['public_usd'])*number(average_ratio))*100 for t in tiers] if average_ratio is not None else []
    if average_margins and min(average_margins)<number(minimum):raise ValueError('pricing_average_margin_floor')
    return dict(minimum_unit_usd=str(floor),minimum_custom_k=rules['min_custom_k'],margin_basis=MARGIN_BASIS,
                all_integer_custom_quantities_covered=True,published_packages=len(tiers),
                historical_retained_ratio=str(average_ratio) if average_ratio is not None else None,
                minimum_estimated_average_margin_pct=str(min(average_margins)) if average_margins else None,
                worst_published_margin_pct=str(min(number(t['procurement_margin_pct']) for t in tiers)))


def average_margin(public_usd, delivered_cost_usd, mix):
    """Historical discount scenario; execution separately validates its source and minimum."""
    if not isinstance(mix,dict) or mix.get('status') not in ('available','partial') or mix.get('retained_ratio') is None:
        return dict(status='not_available',reason=mix.get('reason','historical_discount_mix_missing') if isinstance(mix,dict) else 'historical_discount_mix_missing',procurement_margin_pct=None)
    if mix.get('sha256') != fingerprint({k:v for k,v in mix.items() if k!='sha256'}):
        raise ValueError('pricing_historical_mix_hash_changed')
    ratio=number(mix['retained_ratio'],zero=True)
    if ratio>1:raise ValueError('pricing_historical_mix_ratio_invalid')
    net=number(public_usd)*ratio;cost=number(delivered_cost_usd)
    return dict(status=mix['status'],period=mix['period'],observed_orders=mix['observed_orders'],
                eligible_orders=mix['eligible_orders'],retained_ratio=str(ratio),estimated_net_usd=str(net),
                estimated_procurement_gross_usd=str(net-cost),
                procurement_margin_pct=str((net-cost)/net*100) if net else None,
                historical_mix_sha256=mix['sha256'],source_times=mix.get('source_times'),
                scope='100K package; shared all-Coins historical discount distribution, not platform-specific or portfolio forecast',
                assumptions='same historical discount intensity at candidate price; current delivery cost incl gifts; unknown demand, package mix, Ads and refund settlement')


def required_history_ratio(evidence,now):
    mix=evidence.get('historical_discount_mix')
    if not isinstance(mix,dict) or mix.get('status') not in ('available','partial'):
        raise ValueError('pricing_average_history_required')
    if mix.get('sha256')!=fingerprint({k:v for k,v in mix.items() if k!='sha256'}):raise ValueError('pricing_historical_mix_hash_changed')
    today=now.astimezone(timezone(timedelta(hours=8))).date()
    if mix.get('period')!={'start':(today-timedelta(days=7)).isoformat(),'end':(today-timedelta(days=1)).isoformat()}:
        raise ValueError('pricing_average_history_period')
    observed,eligible=mix.get('observed_orders'),mix.get('eligible_orders')
    if type(observed) is not int or type(eligible) is not int or observed<=0 or observed!=eligible:
        raise ValueError('pricing_average_history_coverage')
    net=number(mix.get('net_order_usd'));discount=number(mix.get('actual_discount_usd'),zero=True)
    if number(mix.get('undiscounted_order_usd'))!=net+discount or number(mix.get('retained_ratio'))!=net/(net+discount):
        raise ValueError('pricing_historical_mix_ratio_invalid')
    return net/(net+discount)


def ending(main, checks):
    if main % 1 == Decimal('.99'):
        return main, 'already_99'
    target = main.to_integral_value(rounding=ROUND_DOWN) - CENT
    if target <= 0:
        return main, 'no_positive_99'
    for base, delivered, cost, fx, ratio, margin in checks:
        before = prove_price(main/base, cost, fx, delivered, base, ratio, margin)
        try:
            after = prove_price(target/base, cost, fx, delivered, base, ratio, margin)
        except ValueError:
            return main, 'hard_floor'
        net0, net1 = number(before['undiscounted_net_usd']), number(after['undiscounted_net_usd'])
        loss = net0-net1
        if loss > net0*Decimal('.01') or loss > number(before['procurement_gross_usd'])*Decimal('.05'):
            return main, 'ending_budget'
        if number(before['procurement_margin_pct'])-number(after['procurement_margin_pct']) > 1:
            return main, 'ending_margin_budget'
    return target, 'accepted'


def reference_adjustment(evidence, platform, anchor, delivered, now):
    """Bound optional same-cycle references without reallocating missing-source influence."""
    references = evidence.get('reference_market') or {}
    source_times = [instant(r['checked_at']) for offers in evidence['offers'].values()
                    for r in offers.values() if r.get('checked_at')]
    item_rows = references.get('offers') or []
    item_reason = references.get('reason') or 'itemd2r_reference_unavailable'
    item = None
    if references.get('status') == 'available':
        try:
            if (not evidence.get('run_id') or references.get('run_id') != evidence['run_id']
                    or [r.get('platform') for r in item_rows] != ['PS', 'XBOX', 'PC']):
                raise ValueError('itemd2r_reference_run_or_coverage')
            for r in item_rows:
                if (r.get('source') != 'ItemD2R' or r.get('run_id') != evidence['run_id']
                        or r.get('url') != 'https://www.itemd2r.com/ea-sports-fc/fc-27-coins'
                        or r.get('status') != 'valid' or r.get('currency') != 'USD'
                        or r.get('conditional') is not False or r.get('comparable') is not True
                        or number(r.get('purchase_k')) != 100 or number(r.get('bonus_k'), zero=True) > 100):
                    raise ValueError('itemd2r_reference_contract')
                number(r.get('gross_usd'));fresh(r['captured_at'], now, 900)
            stamps = source_times + [instant(r['captured_at']) for r in item_rows]
            if (max(stamps)-min(stamps)).total_seconds() > 300:
                raise ValueError('itemd2r_reference_capture_span_over_300_seconds')
            item = next(r for r in item_rows if r['platform'] == platform)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            item_reason = str(exc) if isinstance(exc, ValueError) else 'itemd2r_reference_invalid'
    total = Decimal(0);sources = {}
    for site, weight in REFERENCE_WEIGHTS.items():
        row = item if site == 'ItemD2R' else evidence['offers'][platform].get(site)
        observation = {'weight': str(weight), 'status': 'unavailable', 'contribution': '0',
                       'reason': item_reason if site == 'ItemD2R' else 'u7buy_reference_unavailable'}
        if row is not None:
            try:
                price, base, bonus, stamp = ((row['gross_usd'], row['purchase_k'], row['bonus_k'], row['captured_at'])
                                            if site == 'ItemD2R' else (row['usd_price'], row['base_k'], row['bonus_k'], row['checked_at']))
                if (row.get('conditional') is not False or row.get('comparable') is not True
                        or number(base) != 100 or number(bonus, zero=True) > 100
                        or urlsplit(row.get('url') or '').hostname != {'ItemD2R':'www.itemd2r.com','U7Buy':'www.u7buy.com'}[site]):
                    raise ValueError('reference_contract_invalid')
                fresh(stamp, now, 900)
                stamps = source_times + [instant(stamp)]
                if (max(stamps)-min(stamps)).total_seconds() > 300:
                    raise ValueError('reference_capture_span_over_300_seconds')
                normalized = number(price)/(number(base)+number(bonus, zero=True))*delivered
                gap = normalized/anchor-1
                clipped = max(-REFERENCE_GAP_LIMIT, min(REFERENCE_GAP_LIMIT, gap))
                contribution = weight*clipped;total += contribution
                observation.update(status='available', reason=None, page_usd=str(number(price)),
                    base_k=str(number(base)), bonus_k=str(number(bonus, zero=True)), checked_at=stamp,
                    normalized_usd=str(normalized), relative_gap=str(gap), clipped_gap=str(clipped),
                    contribution=str(contribution), url=row['url'])
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                observation['reason'] = str(exc) if isinstance(exc, ValueError) else 'reference_contract_invalid'
        sources[site] = observation
    return dict(version=REFERENCE_VERSION, platform=platform, anchor_usd=str(anchor),
                sources=sources, raw_offset=str(total), raw_weighted_usd=str(anchor*(1+total)),
                missing_weight_reallocated=False, third_tier_direct_weight='0')


def apply_decision(rows, evidence, edits, *, now=None):
    now = now or datetime.now(timezone.utc)
    fresh(evidence['checked_at'], now)
    fresh(evidence['fx']['checked_at'], now)
    ratio = envelope_ratio(evidence.get('promotion_envelope'), now)
    average_ratio=required_history_ratio(evidence,now)
    package_rules=evidence['promotion_envelope'].get('packages') or {}
    if set(package_rules)!={'PS','XBOX','PC'}:
        raise ValueError('pricing_catalog_coverage_missing')
    margin = str(edits.get('minimum_gross_margin_pct', '10'))
    pooled, basis = common_cost(evidence)
    fx = number(evidence['fx']['cny_per_usd'])
    by = {row['platform']:row for row in rows}
    for p in ('PS','XBOX','PC'):
        observed=evidence['costs'][p]
        if observed.get('platform')!=p or observed.get('game')!='FC27' or observed.get('product')!='Game Coins' or not str(observed.get('record_id','')).isdigit():
            raise ValueError('pricing_cost_scope_invalid')
        fresh(observed['checked_at'], now)
        if instant(observed['trade_at']) > now + timedelta(seconds=5):
            raise ValueError('pricing_cost_trade_in_future')
        fresh(evidence['storefront']['rows'][p]['checked_at'], now)
    if edits.get('costs') or edits.get('offers'):
        raise ValueError('pricing_observed_source_edit_forbidden')
    quotes = edits.get('quotes') or {}
    if any(p in quotes for p in CONSOLE) and (set(quotes)&set(CONSOLE) != set(CONSOLE) or number(quotes['PS']) != number(quotes['XBOX'])):
        raise ValueError('pricing_common_console_quote_required')
    decisions = []
    for group in (CONSOLE, ('PC',)):
        cost = pooled if len(group)==2 else number(evidence['costs']['PC']['cny_per_1k'])
        checks, current, anchors, references, ceilings = [], [], [], [], []
        for p in group:
            own = evidence['storefront']['rows'][p]
            base = number(own['base_k']); delivered = base + number(own['bonus_k'], zero=True)
            if base != 100 or delivered > 200:
                raise ValueError('pricing_package_invalid')
            current.append(number(own['package_usd']))
            loot = evidence['offers'][p]['Lootbar']
            fresh(loot['checked_at'], now)
            if loot.get('conditional') or loot.get('comparable') is not True or number(loot['base_k']) != 100:
                raise ValueError('pricing_comparable_anchor_required')
            anchors.append(number(loot['usd_price']) / (number(loot['base_k'])+number(loot.get('bonus_k',0),zero=True))*delivered)
            references.append(reference_adjustment(evidence, p, anchors[-1], delivered, now))
            item=references[-1]['sources']['ItemD2R']
            ceilings.append(min(anchors[-1],number(item['normalized_usd'])) if item['status']=='available' else anchors[-1])
            checks.append((base,delivered,cost,fx,ratio,margin))
        floor = max(hard_floor(c,rate,d/base,r,m)*base for base,d,c,rate,r,m in checks).quantize(CENT,rounding=ROUND_CEILING)
        floor=max(floor,max(catalog_floor(cost,fx,ratio,margin,package_rules[p],average_ratio=average_ratio)*100 for p in group)).quantize(CENT,rounding=ROUND_CEILING)
        anchor = min(anchors).quantize(CENT,rounding=ROUND_CEILING)
        raw_weighted = min(number(r['raw_weighted_usd']) for r in references)
        weighted = raw_weighted.quantize(CENT, rounding=ROUND_CEILING)
        # Current price is a choice, not an upper bound on a fresh market candidate.
        hold = max(current)
        ceiling=min(ceilings).quantize(CENT,rounding=ROUND_DOWN)
        peer_missing=any(r['sources']['ItemD2R']['status']!='available' for r in references)
        position_conflict=floor>ceiling
        main = max(floor, min(weighted,ceiling))
        floor_applied = floor > weighted
        after_floor = max(floor, raw_weighted)
        reason = 'cost_or_promotion_floor' if floor_applied else 'weighted_market_reference' if weighted != anchor else 'public_anchor_parity' if main != hold else 'already_competitive_hold'
        if weighted>ceiling and not position_conflict:reason='owner_position_ceiling'
        if reason=='already_competitive_hold' and len(set(current))>1:reason='unify_common_console_base'
        if group[0] in quotes:
            main = number(quotes[group[0]])*100
            if main != main.quantize(CENT):
                raise ValueError('pricing_package_cents_required')
            if main>ceiling:raise ValueError('pricing_position_ceiling')
            reason = 'operator_or_hermes_candidate'
        while True:
            try:
                for base,d,c,rate,r,m in checks:prove_price(main/base,c,rate,d,base,r,m)
                break
            except ValueError as exc:
                if str(exc) != 'pricing_hard_margin_floor' or group[0] in quotes:
                    raise
                main += CENT
        target, tail = ending(main, checks)
        if any(target/100<catalog_floor(cost,fx,ratio,margin,package_rules[p],average_ratio=average_ratio) for p in group):
            target,tail=main,'catalog_hard_floor'
        if group[0] in quotes:
            target, tail = main, 'explicit_candidate_no_hidden_adjustment'
        if not position_conflict:target=min(target,ceiling)
        for p, (base, delivered, c, rate, r, m), old in zip(group, checks, current):
            row = by[p]
            proof = prove_price(target/base,c,rate,delivered,base,r,m)
            proof['catalog']=prove_catalog(target/base,c,rate,r,m,package_rules[p],average_ratio=average_ratio)
            average=average_margin(proof['public_usd'],proof['delivered_cost_usd'],evidence.get('historical_discount_mix'))
            old_average=average_margin(old,proof['delivered_cost_usd'],evidence.get('historical_discount_mix'))
            old_net = old.quantize(CENT,rounding=ROUND_DOWN)
            old_gp = old_net-number(proof['delivered_cost_usd'])
            new_gp = number(proof['procurement_gross_usd'])
            average_old_gp=Decimal(old_average['estimated_procurement_gross_usd']) if 'estimated_procurement_gross_usd' in old_average else None
            average_new_gp=Decimal(average['estimated_procurement_gross_usd']) if 'estimated_procurement_gross_usd' in average else None
            multiplier=average_old_gp/average_new_gp if average_old_gp is not None and average_old_gp>0 and average_new_gp>0 else None
            public_anchor=evidence['offers'][p]['Lootbar']
            row.update(cost_cny=str(cost), proposal=f'{target/base:.4f}', auto_proposal=f'{target/base:.4f}',
                raw_cost_record_id=evidence['costs'][p]['record_id'],
                raw_cost_trade_at=evidence['costs'][p]['trade_at'],
                cost_record_id=basis['record_id'] if p in CONSOLE else evidence['costs'][p]['record_id'],
                cost_trade_at=basis['trade_at'] if p in CONSOLE else evidence['costs'][p]['trade_at'],
                target_page_usd=f'{target:.2f}', floor_usd_per_1k=f'{floor/base:.4f}',
                gross_margin_pct=f"{Decimal(proof['procurement_margin_pct']):.2f}",
                margin_basis=MARGIN_BASIS,estimated_average_margin=average,
                minimum_gross_margin_pct=str(margin),
                margin_below_minimum=False, auto_blocked_reason='pricing_position_floor_conflict' if position_conflict else 'pricing_position_peer_missing' if peer_missing else None, pricing_mode=VERSION,
                pricing_tier=None, requested_discount_pct=None, profit_floor_applied=reason=='cost_or_promotion_floor',
                pricing_basis='page_total_100k', strategy_version=VERSION, quote_manual=p in quotes,
                own_bonus_k=str(delivered-base), decision_reason=reason, ending_reason=tail,
                pricing_quantity_basis='both_sides_actual_delivered_quantity',
                reference_fallback='bounded_optional_reference_weights_no_reallocation',
                lootbar_page_usd=f"{number(public_anchor['usd_price']):.2f}",
                lootbar_usd_per_1k=str(number(public_anchor['usd_price'])/(number(public_anchor['base_k'])+number(public_anchor.get('bonus_k',0),zero=True))),
                pre_change_margin_pct=str(old_gp/old_net*100) if old_net else None,
                main_page_usd=f'{main:.2f}', anchor_page_usd=f'{anchor:.2f}',
                reference_adjustment=references[group.index(p)],
                position_policy_version=POSITION_VERSION,position_ceiling_usd=str(ceiling),
                margin_review={'basis':'current_100k_cost_with_seven_closed_days_discount_mix_not_actual_cohort_profit',
                    'current_pct':old_average.get('procurement_margin_pct'),'candidate_pct':average.get('procurement_margin_pct'),
                    'level':'urgent' if max(Decimal(v) for v in (old_average.get('procurement_margin_pct'),average.get('procurement_margin_pct')) if v is not None)>=50 else 'warning' if max(Decimal(v) for v in (old_average.get('procurement_margin_pct'),average.get('procurement_margin_pct')) if v is not None)>=40 else 'normal',
                    'automatic_margin_cap':False},
                change_pct=str((target/old-1)*100), break_even_order_multiplier=str(multiplier) if multiplier is not None else None,
                proof=proof, cost_basis=basis if p in CONSOLE else {'basis':'latest_verified_pc_delivery'},
                break_even_order_basis='same historical discount mix and fixed delivered cost; conditional, not demand forecast',
                warning='未用优惠及近七日优惠结构估算平均采购毛利均须≥10%，含全部交付与数量公式；单笔合法优惠可亏损。广告后贡献另核。',
                status='10%硬红线核算通过 · 待执行', benchmark_site='Lootbar public display',
                lootbar_reduction_pct=str((1-target/anchors[group.index(p)])*100))
        candidates={'baseline':str(target)}
        if floor<=hold<=ceiling:
            candidates['hold']=str(hold)
        parity=max(floor,min(anchor,ceiling))
        parity_tail,_=ending(parity,checks)
        if all(parity_tail/100>=catalog_floor(cost,fx,ratio,margin,package_rules[p],average_ratio=average_ratio) for p in group):
            parity=parity_tail
        candidates['parity']=str(min(parity,ceiling)) if not position_conflict else str(parity)
        fallback_main=max(floor,min(weighted,ceiling))
        fallback_reason='current_weighted_program'
        prior=evidence.get('previous_confirmed_decision') or evidence.get('previous_observed_manual_decision') or {}
        old_receipt=prior.get('receipt') or {}
        old_decisions=old_receipt.get('decisions') or []
        old=next((d for d in old_decisions if d.get('platforms')==list(group)),None)
        if (old_receipt.get('reference_version')==REFERENCE_VERSION and old
                and number(old['raw_weighted_usd'])==raw_weighted and len(set(current))==1
                and floor<=hold<=ceiling):
            fallback_main=hold
            fallback_reason='unchanged_market_verified_manual_intent' if prior.get('job_id') else 'unchanged_market_confirmed_price'
        fallback=fallback_main if fallback_reason in ('unchanged_market_confirmed_price','unchanged_market_verified_manual_intent') else ending(fallback_main,checks)[0]
        if any(fallback/100<catalog_floor(cost,fx,ratio,margin,package_rules[p],average_ratio=average_ratio) for p in group):
            fallback=fallback_main
        if not position_conflict:fallback=min(fallback,ceiling)
        decisions.append(dict(position_policy_version=POSITION_VERSION,position_ceiling_usd=str(ceiling),
                              position_status='floor_conflict' if position_conflict else 'missing_itemd2r' if peer_missing else 'qualified',platforms=list(group),reason=reason,current_public_usd=[str(v) for v in current],
                              main_usd=str(main),selected_usd=str(target),floor_usd=str(floor),ending=tail,
                              reference_version=REFERENCE_VERSION,reference_adjustments=references,
                              raw_weighted_usd=str(raw_weighted),after_floor_usd=str(after_floor),
                              rounded_market_usd=str(weighted),after_cent_usd=str(max(floor, weighted)),
                              explicit_candidate=group[0] in quotes,
                              direction='up' if target>hold else 'down' if target<hold else 'hold',
                              model_unavailable_fallback_usd=str(fallback),
                              model_unavailable_fallback_reason=fallback_reason,
                              previous_confirmed_execution_id=prior.get('execution_id'),
                              previous_observed_manual_job_id=prior.get('job_id'),
                              candidates=candidates))
    receipt=dict(strategy_version=VERSION, position_policy_version=POSITION_VERSION, reference_version=REFERENCE_VERSION,
        reference_weights={'Lootbar':'0.80','ItemD2R':'0.15','U7Buy':'0.05'},
        hard_minimum_margin_pct=str(HARD_MARGIN),margin_basis=MARGIN_BASIS,
        promotions_exempt_from_margin_floor=True,
        historical_average_minimum_margin_pct=str(margin),
        historical_discount_mix_sha256=(evidence.get('historical_discount_mix') or {}).get('sha256'),
        minimum_retained_ratio=str(ratio), promotion_envelope_sha256=evidence['promotion_envelope']['sha256'],
        common_console_cost=basis, decisions=decisions, ad_after_profit='unknown_until_same_scope_ads',
        causal_effect='not_established', comparison_scope='current_public_display_delivered_100K',
        code_sha256=hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes()).hexdigest())
    receipt['sha256']=fingerprint(receipt)
    return receipt


def verify_quote(quote, policy, selected, *, now=None, for_execution=False):
    configured=number(policy['minimum_gross_margin_pct'],zero=True)
    if configured < HARD_MARGIN:
        raise ValueError('pricing_hard_margin_minimum_10')
    if for_execution and quote['evidence']['promotion_envelope'].get('coupon_other_benefits_contract') not in {'not_applicable','verified_mutually_exclusive','verified_included_in_envelope'}:
        raise ValueError('pricing_coupon_other_benefits_unverified')
    if number((quote.get('edits') or {}).get('minimum_gross_margin_pct','10'),zero=True)!=configured:
        raise ValueError('pricing_policy_margin_changed')
    if (not isinstance(selected,list) or not selected or len(set(selected))!=len(selected)
            or set(selected)-{'PS','XBOX','PC'}):
        raise ValueError('pricing_platform_selection_invalid')
    if set(selected)&set(CONSOLE) and not set(CONSOLE)<=set(selected):
        raise ValueError('pricing_common_console_scope_required')
    rows=quote['result']['rows']
    if len(rows)!=3 or {r.get('platform') for r in rows}!={'PS','XBOX','PC'}:
        raise ValueError('pricing_platform_rows_invalid')
    expected=deepcopy(quote['result']['rows'])
    receipt=apply_decision(expected,quote['evidence'],quote.get('edits') or {},now=now)
    if quote['result'].get('decision_receipt') != receipt:
        raise ValueError('pricing_decision_receipt_changed')
    actual={r['platform']:r for r in quote['result']['rows']}
    for row in expected:
        if row['platform'] not in selected:continue
        if for_execution and row.get('auto_blocked_reason') in ('pricing_position_floor_conflict','pricing_position_peer_missing'):
            raise ValueError(row['auto_blocked_reason'])
        for key in ('proposal','cost_cny','target_page_usd','proof','strategy_version','decision_reason','estimated_average_margin','margin_basis','reference_adjustment'):
            if row[key]!=actual[row['platform']].get(key):
                raise ValueError('pricing_quote_tampered')
    return receipt
