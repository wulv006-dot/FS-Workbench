"""Two objectives over one exact price/financial contract; no legacy selector."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
import itertools

from . import VERSION
from .financial import (number, fingerprint, fresh, instant, common_cost, envelope_ratio,
                        required_history_ratio, catalog_floor, prove_catalog, prove_price,
                        average_margin, MARGIN_BASIS, CENT, HARD_MARGIN, FINANCIAL_CONTRACT_VERSION,
                        LEGACY_FINANCIAL_CONTRACT_VERSION, HISTORY_WINDOW_CONTRACT, package_100k, PRICING_SCOPE)

# Catalog adapters share the current 100K proof and retain legacy-envelope input compatibility.
from .selective_sources import (input_ratio as envelope_ratio, input_catalog_floor as catalog_floor,
                                input_prove_catalog as prove_catalog, input_prove_price as prove_price)

PLATFORMS = ('PS','XBOX','PC')
GROUPS = {'console':('PS','XBOX'), 'pc':('PC',)}
SPRINT_POLICY_VERSION = 'sprint_5_10_lower_quote_floor20_v3'
POLICIES = {
    'daily':dict(offsets=(-8,-4,0,4,8), allocation=(.2,.6,.2)),
    'revenue_sprint':dict(offsets=(-5,-6.25,-7.5,-8.75,-10), allocation=(.1,.7,.2))}


def money(value, rounding=ROUND_DOWN):
    return number(value, zero=True).quantize(CENT, rounding=rounding)


def render(unit, tier, coefficient='1', *, rounding=ROUND_HALF_UP):
    """Exact product amount and public cent display are distinct price layers."""
    base = number(tier['base_k'])
    delivered = base+number(tier.get('bonus_k','0'), zero=True)
    before_region = money(number(unit)*base*number(tier['retained_ratio']),ROUND_HALF_UP)
    exact = before_region*number(coefficient)
    regular = money(exact, rounding)
    return dict(regular_usd=str(regular),exact_regular_usd=str(exact),before_region_usd=str(before_region),
                purchase_k=str(base), delivered_k=str(delivered),
                delivered_unit_100k=str(regular/delivered*100))


def replay_promotion(regular, path):
    """Execute an observed mutually exclusive path, including fixed/threshold/cap rules."""
    regular = number(regular, zero=True)
    kind = path['kind']
    if kind=='sequence':
        paid=regular
        for child in path['paths']:
            paid=replay_promotion(paid,child)
        return paid
    if kind == 'none':
        return regular
    if kind=='points':
        discount=min(number(path['credit_usd'],zero=True),regular*number(path['cap_ratio'],zero=True))
        return max(Decimal(0),regular-money(discount,ROUND_UP))
    if regular < number(path.get('threshold_usd','0'), zero=True):
        return regular
    if kind == 'ratio':
        discount = regular*(1-number(path['retained_ratio'], zero=True))
    elif kind == 'fixed':
        discount = number(path['discount_usd'], zero=True)
    else:
        raise ValueError('pricing_promotion_path_unverified')
    if path.get('cap_usd') is not None:
        discount = min(discount, number(path['cap_usd'], zero=True))
    return max(Decimal(0), regular-money(discount, ROUND_UP))


def replay_history(regular, history, coefficient='1'):
    paths = history.get('replay_paths')
    if not paths:
        raise ValueError('pricing_region_history_paths_missing')
    net, gross = Decimal(0), Decimal(0)
    for sample in paths:
        weight = number(sample['weight_usd'])
        base = money(number(regular)*number(coefficient))
        if sample['denominator_basis'] not in ('global_list','regional_regular'):
            raise ValueError('pricing_historical_price_basis_unknown')
        if sample.get('promotion_path_excludes_region') is not True:
            raise ValueError('pricing_historical_region_decomposition_unknown')
        actual = replay_promotion(base, sample['promotion_path'])
        gross += weight*base
        net += weight*actual
    if not gross:
        raise ValueError('pricing_region_history_empty')
    return net/gross


def mixed_ratio_lower_bound(history):
    def lower(path):
        if path['kind']=='none':return Decimal(1)
        if path['kind']=='ratio':return number(path['retained_ratio'],zero=True)
        if path['kind']=='points':return 1-number(path['cap_ratio'],zero=True)
        if path['kind']=='sequence':
            result=Decimal(1)
            for child in path['paths']:result*=lower(child)
            return result
        raise ValueError('pricing_region_exact_fixed_path_bound_required')
    weights=sum(number(p['weight_usd']) for p in history['replay_paths'])
    return sum(number(p['weight_usd'])*lower(p['promotion_path']) for p in history['replay_paths'])/weights


def market_quote(evidence, platform, source, now, region=None):
    if source == 'Lootbar':
        row = evidence.get('offers',{}).get(platform,{}).get('Lootbar')
        if row:
            row = dict(row, source=source, platform=platform, captured_at=row.get('checked_at'),
                       purchase_k=row.get('base_k'), total_usd=row.get('usd_price'),
                       delivered_k=str(number(row['base_k'])+number(row.get('bonus_k','0'), zero=True)))
    else:
        rows = (evidence.get('reference_market') or {}).get('offers',[]) if source == 'ItemD2R' else evidence.get('arab_ut_quotes',[])
        row = next((r for r in rows if r.get('platform') == platform and (not region or r.get('region_id') in (None,region))), None)
        if row:
            row = dict(row, source=source, captured_at=row.get('captured_at') or row.get('checked_at'),
                       total_usd=row.get('total_usd',row.get('gross_usd',row.get('price_usd'))))
            if 'delivered_k' not in row:
                row['delivered_k'] = str(number(row.get('purchase_k',row.get('base_k','100')))+number(row.get('bonus_k','0'), zero=True))
    if not row:
        raise ValueError('pricing_required_market_missing:'+source+':'+platform)
    fresh(row['captured_at'], now, 900)
    if (row.get('conditional') or row.get('comparable') is False or
            number(row.get('purchase_k',row.get('base_k','100'))) != 100):
        raise ValueError('pricing_market_not_comparable:'+source+':'+platform)
    if source == 'ArabUT' and (row.get('delivery') != 'normal' or row.get('selection_verified') is not True):
        raise ValueError('pricing_arab_normal_not_verified')
    if row.get('currency','USD') != 'USD' and not row.get('fx_version'):
        raise ValueError('pricing_market_currency_unverified')
    row['unit_100k'] = str(number(row['total_usd'])/number(row['delivered_k'])*100)
    row['price_basis'] = row.get('price_basis','public_merchandise')
    return row


def sprint_parameters(plan=None):
    parameters=(plan or {}).get('parameters',{})
    if parameters.get('sprint_policy_version',SPRINT_POLICY_VERSION)!=SPRINT_POLICY_VERSION:
        raise ValueError('pricing_sprint_plan_migration_required')
    preferred=number(parameters.get('preferred_undercut_pct','7.5'))
    if not 5<=preferred<=10:raise ValueError('pricing_competitive_preference_invalid')
    return dict(sprint_policy_version=SPRINT_POLICY_VERSION,financial_contract_version=FINANCIAL_CONTRACT_VERSION,
                min_undercut_pct='5',max_undercut_pct='10',undercut_candidates_pct=['5','6.25','7.5','8.75','10'],preferred_undercut_pct=str(preferred))


def price_basis(evidence,now):
    """Saved-source global catalog bounds for display, never a write authorization."""
    pooled,_=common_cost(evidence)
    fresh(evidence['fx']['checked_at'],now)
    fx=number(evidence['fx']['cny_per_usd'])
    ratio=envelope_ratio(evidence['promotion_envelope'],now)
    average=history_ratio(evidence,now)
    rows={}
    for platform in PLATFORMS:
        fresh(evidence['costs'][platform]['checked_at'],now)
        cost=pooled if platform!='PC' else number(evidence['costs'][platform]['cny_per_1k'])
        rules=evidence['promotion_envelope']['packages'][platform]
        tier=next(t for t in rules['tiers'] if number(t['base_k'])==100)
        delivered=number(tier['base_k'])+number(tier['bonus_k'],zero=True)
        package_cost=delivered*cost/fx
        rows[platform]=dict(cost_cny_per_1k=str(cost),cost_usd_per_1k=str(cost/fx),
            package_cost_usd=str(package_cost),delivered_k=str(delivered),
            regular_floor_usd=str(catalog_floor(cost,fx,ratio,HARD_MARGIN,rules)*100),
            average_floor_usd=str(catalog_floor(cost,fx,ratio,HARD_MARGIN,rules,average_ratio=average)*100),
            cost_checked_at=evidence['costs'][platform]['checked_at'])
    return dict(status='available',rows=rows,as_of=now.isoformat(),scope='global_100k_package_only',pricing_scope=PRICING_SCOPE,
                historical_retained_ratio=str(average),history_window_contract=evidence['historical_discount_mix'].get('history_window_contract'),history_period=evidence['historical_discount_mix']['period'],minimum_margin_pct=str(HARD_MARGIN),execution_authorized=False)


def required_unit_bound(evidence,platform,now,region=None,evaluation_context=None,*,average_minimum=HARD_MARGIN):
    pooled,_=common_cost(evidence)
    cost=pooled if platform!='PC' else number(evidence['costs']['PC']['cny_per_1k'])
    average=history_ratio(evidence,now,evaluation_context)
    rules=evidence['promotion_envelope']['packages'][platform]
    if region:
        history=region.get('history') or {}
        if history.get('replay_paths'):
            number(mixed_ratio_lower_bound(history))
            tier=package_100k(rules)
            required=cost/number(evidence['fx']['cny_per_usd'])*(100+number(tier['bonus_k'],zero=True))/(1-number(average_minimum)/100)
            regular=required.quantize(CENT,rounding=ROUND_UP)
            while regular*replay_history(regular,history)<required:regular+=CENT
            return ((regular-CENT/2)/number(tier['retained_ratio'])).quantize(CENT,rounding=ROUND_UP)/100
        elif history.get('basis')!='pooled_other_promotions_excluding_region_verified':
            raise ValueError('pricing_region_history_basis_unknown:'+str(region['region_id']))
    return catalog_floor(cost,evidence['fx']['cny_per_usd'],envelope_ratio(evidence['promotion_envelope'],now),average_minimum,rules,average_ratio=average)


def required_base_bound(evidence,platform,now,plan=None,evaluation_context=None,*,average_minimum=HARD_MARGIN):
    bound=required_unit_bound(evidence,platform,now,evaluation_context=evaluation_context,average_minimum=average_minimum)
    for region in evidence.get('region_rules',[])+evidence.get('regional_controls',[]):
        if platform not in region['platforms']:continue
        key=str(region['region_id'])+':'+platform
        mutable=any(c['region_id']==region['region_id'] and platform in c['platforms'] for c in evidence.get('regional_controls',[])) and (not plan or plan.get('mode','revenue_sprint')=='revenue_sprint' and 'region:'+key in plan['resources'])
        if region.get('id') is None and number(region['factor'])==1:
            # An uncreated, unchanged default control has no extra regional rounding layer.
            if not mutable:continue
            try:market_quote(evidence,platform,'ArabUT',now,region['region_id'])
            except ValueError:continue
        factor=Decimal(1) if mutable else number(region['factor'])
        tier=package_100k(evidence['promotion_envelope']['packages'][platform])
        regional_floor=required_unit_bound(evidence,platform,now,region,evaluation_context,average_minimum=average_minimum)*100*number(tier['retained_ratio'])
        before=((regional_floor-(CENT/2 if region.get('rounding')=='half_up_cent' else 0))/factor).quantize(CENT,rounding=ROUND_UP)
        base=((before-CENT/2)/number(tier['retained_ratio'])).quantize(CENT,rounding=ROUND_UP)/100
        bound=max(bound,base)
    return (bound*100).quantize(CENT,rounding=ROUND_UP)


def base_limits(public_low,public_high,retained):
    retained=number(retained)
    low=((public_low-CENT/2)/retained).quantize(CENT,rounding=ROUND_UP)
    high=((public_high+CENT/2)/retained).quantize(CENT,rounding=ROUND_UP)-CENT
    return low,high


def resolve_anchor(evidence,platform,quotes,now):
    available=[q for q in quotes if q['source'] in ('Lootbar','ItemD2R') and q['platform']==platform]
    if not available:return dict(source=None,unit_100k=None,reason='BOTH_COMPETITOR_QUOTES_MISSING')
    chosen=min(available,key=lambda q:(number(q['unit_100k']),q['source']!='ItemD2R'))
    return dict(source=chosen['source'],unit_100k=chosen['unit_100k'],reason='SINGLE_VALID_CURRENT_QUOTE' if len(available)==1 else 'ITEMD2R_LOWER_VALID_QUOTE' if chosen['source']=='ItemD2R' else 'LOOTBAR_LOWER_VALID_QUOTE')


def current_market_quotes(evidence,platforms,now,region=None):
    quotes=[];source_gaps=[]
    for p in platforms:
        for source in ('Lootbar','ItemD2R'):
            try:quotes.append(market_quote(evidence,p,source,now,region))
            except (ValueError,KeyError,TypeError) as error:
                reference=evidence.get('reference_market') or {}
                platform_gap=next((gap for gap in reference.get('missing',[]) if gap.get('platform')==p),{}) if source=='ItemD2R' else {}
                source_gaps.append(dict(platform=p,source=source,reason=platform_gap.get('reason') or ((reference.get('reason') or str(error)) if source=='ItemD2R' and not reference.get('offers') else str(error) if isinstance(error,ValueError) else 'pricing_market_contract_invalid')))
    return quotes,source_gaps


def daily_reference(evidence,platforms,now):
    quotes,gaps=current_market_quotes(evidence,platforms,now)
    result={}
    for p in platforms:
        available=[q for q in quotes if q['platform']==p]
        chosen=next((q for q in available if q['source']=='Lootbar'),available[0] if available else None)
        result[p]=dict(source=chosen['source'] if chosen else None,unit_100k=chosen['unit_100k'] if chosen else None,
            captured_at=chosen['captured_at'] if chosen else None,source_gaps=[g for g in gaps if g['platform']==p],
            average_margin_target_pct=None if chosen else '30')
    return result


def daily_item_target(evidence,platforms,references,floor):
    eligible=[p for p in platforms if references[p]['source']=='ItemD2R']
    if not eligible:return None
    driver=min(eligible,key=lambda p:number(references[p]['unit_100k']))
    unit=number(references[driver]['unit_100k'])
    tier=package_100k(evidence['promotion_envelope']['packages'][driver])
    delivered=100+number(tier['bonus_k'],zero=True)
    exact_public=unit*delivered/100
    public=money(exact_public,ROUND_HALF_UP)
    target,high=base_limits(public,public,tier['retained_ratio'])
    previous=(target-CENT)*number(tier['retained_ratio'])
    previous=previous.quantize(CENT,rounding=ROUND_HALF_UP)
    if previous>=public:raise ValueError('pricing_daily_item_target_base_not_minimal')
    chosen=max(number(floor),target)
    positions={}
    for p in platforms:
        shown=render(chosen/100,package_100k(evidence['promotion_envelope']['packages'][p]))
        ref=references[p]
        positions[p]=dict(reference_source=ref['source'],reference_unit_100k=ref['unit_100k'],
            actual_public_usd=shown['regular_usd'],delivered_k=shown['delivered_k'],actual_unit_100k=shown['delivered_unit_100k'],
            difference_pct=str((number(shown['delivered_unit_100k'])/number(ref['unit_100k'])-1)*100) if ref['unit_100k'] is not None else None)
    target_met=number(positions[driver]['actual_public_usd'])==public
    return dict(basis='itemd2r_actual_delivery_target',driver_platform=driver,driver_source='ItemD2R',
        driver_unit_100k=str(unit),driver_captured_at=references[driver]['captured_at'],
        exact_target_public_usd=str(exact_public),target_public_usd=str(public),public_target_rounding='half_up_cent',
        public_target_rounding_difference_usd=str(public-exact_public),
        target_base_total=str(target),target_base_high=str(high),target_public_cent_reachable=target<=high,
        minimum_legal_base_total=str(floor),selected_base_total=str(chosen),
        previous_target_base_cent=str(target-CENT),previous_target_public_usd=str(previous),
        financial_floor_applied=chosen>target,item_target_met=target_met,
        actual_minus_target_public_usd=str(number(positions[driver]['actual_public_usd'])-public),
        unmet_reason=None if target_met else 'financial_floor' if chosen>target else 'public_cent_not_reachable' if target>high else None,
        platforms=positions)


def daily_average_target_proof(evidence,proof,platforms):
    result={}
    for p in platforms:
        cost=number(proof['prices']['global:'+p]['proof']['delivered_cost_usd'])
        scopes={}
        for scope,row in proof['prices'].items():
            if not scope.endswith(':'+p):continue
            regular=number(row['price']['regular_usd'])
            retained=number(row['catalog']['historical_retained_ratio'])
            net=regular*retained
            margin=(net-cost)/net*100
            if margin<30:raise ValueError('pricing_daily_missing_market_average_30')
            scopes[scope]=dict(public_usd=str(regular),delivered_cost_usd=str(cost),retained_ratio=str(retained),estimated_net_usd=str(net),estimated_average_margin_pct=str(margin))
        result[p]=dict(target_pct='30',historical_mix_sha256=evidence['historical_discount_mix']['sha256'],scopes=scopes)
    return result


def competition(evidence, platforms, now, region=None, *, plan=None, resolved_global=None,evaluation_context=None,base_total=None):
    sprint_parameters(plan)
    quotes,source_gaps=current_market_quotes(evidence,platforms,now,region)
    regional_fallbacks={}
    if region==21:
        for p in platforms:
            try:quotes.append(market_quote(evidence,p,'ArabUT',now,region))
            except ValueError as error:regional_fallbacks[p]=dict(mode='follow_global',reason=str(error))
    times = [instant(q['captured_at']) for q in quotes]
    if times and (max(times)-min(times)).total_seconds() > 300:
        raise ValueError('pricing_market_capture_span')
    anchors={p:deepcopy(resolved_global['anchors'][p]) if resolved_global else resolve_anchor(evidence,p,quotes,now) for p in platforms}
    def limits(choices):
      targets={}
      for p in platforms:
        if choices[p].get('unit_100k') is None:continue
        target=number(choices[p]['unit_100k'])
        if region==21:
            arab=next((q for q in quotes if q['source']=='ArabUT' and q['platform']==p),None)
            if arab and number(arab['unit_100k'])<target:
                target=number(arab['unit_100k'])
                choices[p].update(local_source='ArabUT',local_reason='ARABUT_LOWER_NORMAL_QUOTE')
        own = evidence['storefront']['rows'][p]
        delivered = 100+number(own['bonus_k'],zero=True)
        tier=next(t for t in evidence['promotion_envelope']['packages'][p]['tiers'] if number(t['base_k'])==100)
        retained=number(tier['retained_ratio'])
        public_low=(target*Decimal('.90')*delivered/100).quantize(CENT,rounding=ROUND_UP)
        public_high=(target*Decimal('.95')*delivered/100).quantize(CENT,rounding=ROUND_DOWN)
        low,high=base_limits(public_low,public_high,retained)
        targets[p] = dict(anchor_unit_100k=str(target),undiscounted_total=str(target*delivered/100/retained),
                          undiscounted_comparable_public_total=str(target*delivered/100),public_total_low=str(public_low),public_total_high=str(public_high),
                          unit_low=str(target*Decimal('.90')), unit_high=str(target*Decimal('.95')),
                          total_low=str(low),total_high=str(high))
      return targets
    targets=limits(anchors)
    attempts=[];decision_type='regional_follow_global' if region==21 and regional_fallbacks else 'competitive';minimum_base=None;coefficients=['1'] if decision_type=='regional_follow_global' else None
    saudi_floor_follow_global=False
    if region is None:
        floor=max(required_base_bound(evidence,p,now,plan,evaluation_context) for p in platforms)
        minimum_base=str(floor)
        def feasible(values):return bool(values) and max([floor]+[number(t['total_low']) for t in values.values()])<=min(number(t['total_high']) for t in values.values())
        attempts.append(dict(anchors=deepcopy(anchors),targets=deepcopy(targets),financial_interval_feasible=feasible(targets)))
        if not feasible(targets):decision_type='floor_fallback'
    elif base_total is not None:
        p=platforms[0]
        if p in regional_fallbacks:
            coefficients=['1'];decision_type='regional_follow_global'
        elif resolved_global and resolved_global['decision_type']=='floor_fallback':
            coefficients=['1'];decision_type='regional_follow_global';saudi_floor_follow_global=True
        else:
            region_rule=next(r for r in evidence['regional_controls'] if r['region_id']==region and p in r['platforms'])
            floor_factor=(required_unit_bound(evidence,p,now,region_rule,evaluation_context)*100/number(base_total)).quantize(Decimal('.0001'),rounding=ROUND_UP)
            if floor_factor>1:raise ValueError('INFEASIBLE_REGION_FINANCIAL_AND_BASE_PRICE')
            target=targets[p];delivered=100+number(evidence['storefront']['rows'][p]['bonus_k'],zero=True)
            tier=next(t for t in evidence['promotion_envelope']['packages'][p]['tiers'] if number(t['base_k'])==100)
            before_region=render(number(base_total)/100,tier)['before_region_usd']
            coefficients=[str(f) for f in solve_coefficient(before_region,target['unit_low'],target['unit_high'],delivered,minimum_factor=str(max(Decimal('.0001'),floor_factor)))]
            if not coefficients:
                coefficients=['1'];decision_type='regional_follow_global';saudi_floor_follow_global=True
    return dict(quotes=quotes, targets=targets, valid_until=((min(times) if times else instant(evidence['checked_at']))+timedelta(seconds=900)).isoformat(),
                source_gaps=source_gaps,source_policy='current_available_quote_or_100k_margin_floor',
                competition_available={p:anchors[p].get('unit_100k') is not None for p in platforms},
                anchors=anchors,anchor_attempts=attempts,regional_fallbacks=regional_fallbacks,sprint_policy_version=SPRINT_POLICY_VERSION,financial_contract_version=FINANCIAL_CONTRACT_VERSION if evidence['historical_discount_mix'].get('history_window_contract')==HISTORY_WINDOW_CONTRACT else LEGACY_FINANCIAL_CONTRACT_VERSION,
                decision_type=decision_type,reason='SAUDI_MARGIN_FLOOR_FOLLOW_GLOBAL' if saudi_floor_follow_global else 'SAUDI_MISSING_QUOTE_FOLLOW_GLOBAL' if decision_type=='regional_follow_global' else 'BOTH_COMPETITOR_QUOTES_MISSING_USE_MARGIN_FLOOR' if not targets else 'MARGIN_FLOOR_FALLBACK_20' if decision_type=='floor_fallback' else 'VERIFIED_COMPETITIVE_BAND',
                minimum_legal_base_total=minimum_base,legal_coefficients=coefficients,
                pricing_scope=PRICING_SCOPE,scope='100K actual package and gifts; other sizes are outside the hard pricing floor')


def history_ratio(evidence,now,evaluation_context=None):
    if evaluation_context is None:
        if evidence.get('mode')=='shadow' or evidence.get('origin')=='simulation' or (evidence.get('historical_discount_mix') or {}).get('origin')=='simulation':
            raise ValueError('pricing_simulation_execution_forbidden')
        return required_history_ratio(evidence,now)
    if evaluation_context.get('mode')!='shadow' or evaluation_context.get('training_eligible') is not False:
        raise ValueError('pricing_simulation_context_invalid')
    ratio=number(evaluation_context['retained_ratio'])
    if ratio>1:
        raise ValueError('pricing_simulated_history_ratio_invalid')
    return ratio


def financial(evidence, action, now, *, regions=None,evaluation_context=None):
    ratio = envelope_ratio(evidence['promotion_envelope'],now)
    average = history_ratio(evidence,now,evaluation_context)
    cost, pool = common_cost(evidence)
    fx = number(evidence['fx']['cny_per_usd'])
    packages = evidence['promotion_envelope']['packages']
    results = {}
    for p in PLATFORMS:
        fresh(evidence['costs'][p]['checked_at'],now)
        fresh(evidence['storefront']['rows'][p]['checked_at'],now)
        c = cost if p != 'PC' else number(evidence['costs']['PC']['cny_per_1k'])
        unit = number(action['base_prices']['console' if p!='PC' else 'pc'])/100
        proof = prove_catalog(unit,c,fx,ratio,HARD_MARGIN,packages[p],average_ratio=average)
        tier = package_100k(packages[p])
        shown = render(unit,tier)
        base_proof = prove_price(number(shown['regular_usd'])/100,c,fx,shown['delivered_k'],'100',ratio)
        results['global:'+p] = dict(catalog=proof, price=shown, proof=base_proof,
            average=average_margin(shown['regular_usd'],base_proof['delivered_cost_usd'],evidence['historical_discount_mix']))
        for region in regions or []:
            if p not in region['platforms']:
                continue
            coefficient = action.get('region_coefficients',{}).get(str(region['region_id'])+':'+p,region['factor'])
            if region.get('price_semantics') != 'regional_regular_multiplicative' or region.get('verified') is not True:
                raise ValueError('pricing_region_contract_unverified:'+str(region['region_id']))
            if region.get('id') is None and number(coefficient)==1:
                inherited=deepcopy(results['global:'+p])
                inherited['catalog']['extra_region_rounding_bound_per_k']='0'
                inherited.update(coefficient='1',rule_id=None,status='inherited_global',
                    history_basis='global_actual_mix_no_independent_region_rule',application_scope='region_'+str(region['region_id']))
                results[str(region['region_id'])+':'+p]=inherited
                continue
            # The exact replay basis is pinned by the source contract, never inferred from averages.
            history = region.get('history') or {}
            if history.get('basis')=='historical_eligibility_current_terms_projected' and history.get('basis_lower_bound_sufficient') is not True:
                raise ValueError('pricing_region_original_basis_projection_unverified')
            if history.get('replay_paths'):
                history_basis = 'verified_observed_paths_replay'
            elif history.get('basis') == 'pooled_other_promotions_excluding_region_verified':
                regional_average = average
                history_basis = 'global_pooled_actual_mix_regional_projection'
            else:
                raise ValueError('pricing_region_history_basis_unknown:'+str(region['region_id']))
            price = render(unit,tier,coefficient,rounding=ROUND_HALF_UP if region.get('rounding')=='half_up_cent' else ROUND_DOWN)
            regional_average=replay_history(price['regular_usd'],history) if history.get('replay_paths') else regional_average
            regional_catalog=prove_catalog(number(price['regular_usd'])/100/number(tier['retained_ratio']),c,fx,ratio,HARD_MARGIN,packages[p],average_ratio=regional_average)
            regional_catalog['extra_region_rounding_bound_per_k']='0'
            regional_catalog['average_bound_basis']='same_actual_amount_weights_at_100k_package_with_exact_rounding'
            results[str(region['region_id'])+':'+p] = dict(catalog=regional_catalog, price=price,
                 coefficient=str(coefficient), rule_id=region.get('id'), history_basis=history_basis,
                 history_source_sha256=history.get('source_sha256'),original_basis_reconciliation=history.get('original_basis_reconciliation'),
                 status='regional_projection', source_scope=history.get('source_scope','global_pooled_actual_mix'),
                 application_scope='region_'+str(region['region_id']))
    current_window=evidence['historical_discount_mix'].get('history_window_contract')==HISTORY_WINDOW_CONTRACT
    return dict(pass_all=True, margin_basis=MARGIN_BASIS, minimum_pct=str(HARD_MARGIN), financial_contract_version=FINANCIAL_CONTRACT_VERSION if current_window else LEGACY_FINANCIAL_CONTRACT_VERSION, common_console_cost=pool,
                pricing_scope=PRICING_SCOPE,
                proof_kind=('actual_eight_day_lagged_mix' if current_window else 'actual_seven_day_mix') if evaluation_context is None else 'shadow_simulated_projection',
                execution_eligible=evaluation_context is None,
                historical_mix_sha256=evidence['historical_discount_mix']['sha256'], prices=results)


def demand(price, reference, baseline_orders, elasticity='2'):
    ratio = number(price)/number(reference)
    exponent = number(elasticity,zero=True)
    if exponent > 8:
        raise ValueError('pricing_elasticity_domain')
    # Decimal fractional powers preserve monetary inputs; these are predictions, not money guards.
    return number(baseline_orders,zero=True)*(ratio**(-exponent))


def monthly_target(target, mtd, now, plan_end=None,metadata=None):
    local = now.astimezone(timezone(timedelta(hours=8)))
    month_end = (local.replace(day=28)+timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    remaining = Decimal(str(max(0,(month_end-local).total_seconds())))/3600
    end = min(instant(plan_end),month_end) if plan_end else month_end
    plan_hours = Decimal(str(max(0,(end-local).total_seconds())))/3600
    if target is None:
        return dict(target=None,mtd=mtd,gap=None,required_daily=None,status='target_not_configured',
                    month_hours=str(remaining),plan_hours=str(plan_hours))
    if mtd is None:
        return dict(target=str(target),mtd=None,gap=None,required_daily=None,status='mtd_pending',month_hours=str(remaining),plan_hours=str(plan_hours))
    if metadata and metadata.get('mtd_status') not in (None,'complete_through_current_read'):
        lower=metadata.get('mtd_lower_bound')
        upper=metadata.get('mtd_upper_bound')
        return dict(target=str(target),mtd=mtd,mtd_exact=None,mtd_lower_bound=lower,known_period_upper_bound=upper,
                    gap=None,gap_lower_bound='0',gap_upper_bound=str(max(Decimal(0),number(target,zero=True)-number(lower,zero=True))) if lower is not None else None,
                    required_daily=None,status='partial_mtd_interval',through_date=metadata.get('through_date'),month_hours=str(remaining),plan_hours=str(plan_hours))
    gap = max(Decimal(0),number(target,zero=True)-number(mtd,zero=True))
    return dict(target=str(target),mtd=str(mtd),gap=str(gap),
                required_daily=str(gap/remaining*24) if remaining else None,
                month_hours=str(remaining),plan_hours=str(plan_hours),status='settlement' if not remaining else 'available')


def score(mode, action, evidence, financial_proof, anchor, evaluation_context=None,parameters=None):
    model = evidence.get('demand_model') or {}
    rows = {}
    objective = revenue = contribution = Decimal(0)
    absolute = True
    for group in GROUPS:
        price = number(action['base_prices'][group])
        reference = number(anchor['base_prices'][group])
        baseline = (model.get('groups') or {}).get(group,{})
        reference=number(baseline.get('reference_regular_usd') or reference)
        has_baseline = baseline.get('orders_per_block') is not None
        absolute = absolute and has_baseline
        orders = demand(price,reference,baseline['orders_per_block'] if has_baseline else '1',baseline.get('elasticity','2'))
        retention = history_ratio(evidence,instant(evidence['checked_at']),evaluation_context)
        p = 'PS' if group=='console' else 'PC'
        per_cost = number(financial_proof['prices']['global:'+p]['proof']['delivered_cost_usd'])
        if baseline.get('target_revenue_per_order_usd') is not None:
            group_revenue=orders*number(baseline['target_revenue_per_order_usd'])*(price/reference)
            if evaluation_context is not None:
                real_retention=number((evidence.get('historical_discount_mix') or {}).get('retained_ratio') or retention)
                group_revenue*=retention/real_retention
        else:
            group_revenue = orders*price*retention
        if baseline.get('delivered_k_per_order') is not None:
            pooled,_=common_cost(evidence)
            current_cost=pooled if group=='console' else number(evidence['costs']['PC']['cny_per_1k'])
            per_cost=number(baseline['delivered_k_per_order'])*current_cost/number(evidence['fx']['cny_per_usd'])
        group_contribution = group_revenue-orders*per_cost
        group_objective = group_revenue if mode=='revenue_sprint' else group_contribution
        budget_reference=number((evidence.get('budget_reference') or {}).get('base_prices',{}).get(group,anchor['base_prices'][group]))
        concession_per_order=max(Decimal(0),budget_reference-price)
        if baseline.get('target_revenue_per_order_usd') is not None:
            concession_per_order=max(Decimal(0),number(baseline['target_revenue_per_order_usd'])*(budget_reference-price)/reference)
        rows[group] = dict(orders=str(orders),revenue=str(group_revenue),contribution=str(group_contribution),
            concession=str(concession_per_order*orders) if has_baseline else None,
            negative_contribution=str(max(Decimal(0),-group_contribution)) if has_baseline else None,
            prediction_basis='observed_paid_orders_frozen_basket_net_AOV_ratio_projection' if has_baseline else 'relative_100k_anchor_index_not_absolute_forecast',
            order_unit='paid_orders_per_6h' if has_baseline else 'relative_order_index',
            net_revenue_per_order_usd=str(group_revenue/orders) if orders else None,delivered_k_per_order=baseline.get('delivered_k_per_order'),
            new_customers=str(orders*number(baseline['new_customer_ratio'],zero=True)) if baseline.get('new_customer_ratio') is not None else None)
        objective += group_objective
        revenue += group_revenue
        contribution += group_contribution
    regional_predictions=[]
    for segment in model.get('segments',[]):
        key=str(segment['region_id'])+':'+segment['platform']
        price_row=financial_proof['prices'].get(key)
        if not price_row:
            raise ValueError('pricing_demand_segment_price_missing')
        price=number(price_row['price']['regular_usd'])
        orders=demand(price,segment['reference_regular_usd'],segment['orders_per_block'],segment.get('elasticity','2'))
        retention=number(segment['retained_ratio'])
        shadow_adjustment=history_ratio(evidence,instant(evidence['checked_at']),evaluation_context)/number(evidence['historical_discount_mix']['retained_ratio']) if evaluation_context is not None else Decimal(1)
        cost=number(segment['delivered_cost_per_order_usd'])
        if segment.get('target_revenue_per_order_usd') is not None:
            income=orders*number(segment['target_revenue_per_order_usd'])*(price/number(segment['reference_regular_usd']))*shadow_adjustment
        else:
            income=orders*price*retention
            absolute=False
        profit=income-orders*cost
        new_ratio=segment.get('new_customer_ratio')
        objective += income if mode=='revenue_sprint' else profit
        revenue += income
        contribution += profit
        group='pc' if segment['platform']=='PC' else 'console'
        budget_base=number((evidence.get('budget_reference') or {}).get('base_prices',{}).get(group,anchor['base_prices'][group]))
        budget_factor=number((evidence.get('budget_reference') or {}).get('region_coefficients',{}).get(key,'1'))
        concession_per_order=max(Decimal(0),budget_base*budget_factor-price)
        if segment.get('target_revenue_per_order_usd') is not None:
            concession_per_order=max(Decimal(0),number(segment['target_revenue_per_order_usd'])*(budget_base*budget_factor-price)/number(segment['reference_regular_usd']))
        concession=concession_per_order*orders
        if rows[group]['concession'] is not None:rows[group]['concession']=str(Decimal(rows[group]['concession'])+concession)
        if rows[group]['negative_contribution'] is not None:rows[group]['negative_contribution']=str(Decimal(rows[group]['negative_contribution'])+max(Decimal(0),-profit))
        regional_predictions.append(dict(key=key,orders=str(orders),revenue=str(income),contribution=str(profit),
                                         concession=str(concession),negative_contribution=str(max(Decimal(0),-profit))))
    queue_projection=None
    sensitivity = {e:{g:str(demand(action['base_prices'][g],((model.get('groups') or {}).get(g,{}) or {}).get('reference_regular_usd') or anchor['base_prices'][g],
                    ((model.get('groups') or {}).get(g,{}) or {}).get('orders_per_block')
                    if ((model.get('groups') or {}).get(g,{}) or {}).get('orders_per_block') is not None else '1',e)) for g in GROUPS} for e in ('.5','1','2','4')}
    return dict(objective=str(objective),revenue=str(revenue) if absolute else None,
                revenue_index=str(revenue),contribution=str(contribution) if absolute else None,
                contribution_index=str(contribution),groups=rows,
                status=model.get('status','central_prior'), elasticity=model.get('elasticity','2'),
                missing_context=model.get('missing_context',['real_exposure','new_customer_identity','advertising_attribution']),
                contribution_basis='procurement_contribution_ads_and_incremental_fees_pending',
                absolute_forecast_available=absolute,sensitivity=sensitivity,regional_predictions=regional_predictions,queue_projection=queue_projection,
                regional_demand_status='observed_segments' if regional_predictions else 'regional_demand_pending',
                new_customer_objective='available' if all((model.get('groups') or {}).get(g,{}).get('new_customer_ratio') is not None for g in GROUPS) else 'identity_pending_contribution_reference_with_exploration')


def current_action(evidence):
    return dict(base_prices={g:str(max(number(evidence['storefront']['rows'][p]['package_usd']) for p in ps)) for g,ps in GROUPS.items()},
                region_coefficients={str(r['region_id'])+':'+r['platforms'][0]:r['factor'] for r in evidence.get('regional_controls',[])})


def evaluate(evidence, mode, *, plan=None, now=None,evaluation_context=None,explicit_prices=None):
    now = now or datetime.now(timezone.utc)
    if mode not in POLICIES and mode != 'smart':
        raise ValueError('pricing_strategy_unknown')
    if mode == 'smart':
        from .smart import candidate_or_baseline
        sprint_plan = dict(plan, mode='revenue_sprint') if plan else None
        result = evaluate(evidence, 'revenue_sprint', plan=sprint_plan, now=now, evaluation_context=evaluation_context, explicit_prices=explicit_prices)
        if result['selected'] and explicit_prices is None:
            scope = sprint_plan or dict(mode='revenue_sprint', resources=['base:console', 'base:pc'] + [r['resource'] for r in evidence.get('regional_controls', [])], parameters={})
            result['candidates'] = [candidate_or_baseline(evidence, scope, result['current'], result['selected'], label, now) for label in 'ABC']
            result['selected'] = result['candidates'][0]
        result['mode'] = 'smart'
        return result
    fresh(evidence['checked_at'],now)
    fresh(evidence['fx']['checked_at'],now)
    controls=evidence.get('regional_controls',[])
    current = current_action(evidence)
    anchor = deepcopy((plan or {}).get('price_anchor') or current)
    regions = evidence.get('region_rules',[])
    options = {}
    comparisons = {}
    failures = []
    daily_inputs=daily_reference(evidence,PLATFORMS,now) if mode=='daily' else {}
    daily_targets={}
    average30_platforms=[p for group,ps in GROUPS.items() if not plan or 'base:'+group in plan['resources']
                         for p in ps if daily_inputs.get(p,{}).get('average_margin_target_pct')=='30']
    avg = history_ratio(evidence,now,evaluation_context)
    ratio = envelope_ratio(evidence['promotion_envelope'],now)
    pooled,_ = common_cost(evidence)
    for group, platforms in GROUPS.items():
        mutable=not plan or 'base:'+group in plan['resources']
        if not mutable:
            options[group]=[number(current['base_prices'][group])]
            continue
        c = pooled if group=='console' else number(evidence['costs']['PC']['cny_per_1k'])
        bound_plan=plan or dict(mode=mode,resources=[])
        floor = max(required_base_bound(evidence,p,now,bound_plan if mode!='revenue_sprint' else plan,evaluation_context,
                    average_minimum='30' if daily_inputs.get(p,{}).get('average_margin_target_pct')=='30' else HARD_MARGIN) for p in platforms)
        if mode == 'revenue_sprint':
            try:
                market = competition(evidence,platforms,now,plan=plan,evaluation_context=evaluation_context)
                comparisons[group] = market
                low = max([floor]+[number(t['total_low']) for t in market['targets'].values()])
                high = min([number(t['total_high']) for t in market['targets'].values()] or [floor])
                low = max(low,floor)
                if low > high:
                    values={floor}
                else:
                    values = {money(number(t['undiscounted_total'])*(1+Decimal(str(o))/100)) for t in market['targets'].values() for o in POLICIES[mode]['offsets']}
                    values |= {low,high}
                    values = {v for v in values if low<=v<=high}
            except ValueError as exc:
                failures.append(dict(scope=group,code=str(exc)))
                values = {number(current['base_prices'][group])}
                comparisons.pop(group,None)
        else:
            item_target=daily_item_target(evidence,platforms,daily_inputs,floor)
            if item_target:
                daily_targets[group]=item_target
                values={number(item_target['selected_base_total'])}
            elif any(daily_inputs[p]['average_margin_target_pct']=='30' for p in platforms):values={floor}
            else:
                anchor_price = number(anchor['base_prices'][group])
                offsets=(plan or {}).get('parameters',{}).get('offsets_pct',POLICIES[mode]['offsets'])
                values = {money(anchor_price*(1+Decimal(str(o))/100)) for o in offsets}
                values = {v for v in values if v >= floor}
        options[group] = sorted(values)
        if not values:failures.append(dict(scope=group,code='pricing_plan_candidate_range_below_margin_floor'))
        if explicit_prices and group in explicit_prices:
            candidate=number(explicit_prices[group])
            if candidate!=candidate.quantize(CENT):raise ValueError('pricing_package_cents_required')
            if not mutable:raise ValueError('pricing_manual_scope_not_owned')
            if mode=='revenue_sprint':
                if group not in comparisons:raise ValueError('pricing_manual_required_market_missing')
                limits=comparisons[group]['targets'].values()
                if any(not number(t['total_low'])<=candidate<=number(t['total_high']) for t in limits):raise ValueError('pricing_competitive_band')
            elif group in daily_targets:
                if candidate!=number(daily_targets[group]['selected_base_total']):raise ValueError('pricing_daily_item_target_price_changed')
            else:
                offsets=(plan or {}).get('parameters',{}).get('offsets_pct',POLICIES[mode]['offsets'])
                anchor_price=number(anchor['base_prices'][group])
                if not anchor_price*(1+Decimal(str(min(offsets,key=lambda v:Decimal(str(v)))))/100)<=candidate<=anchor_price*(1+Decimal(str(max(offsets,key=lambda v:Decimal(str(v)))))/100):
                    raise ValueError('pricing_manual_outside_plan_range')
            options[group]=[candidate]
    feasible = []
    for console,pc in itertools.product(options['console'],options['pc']):
        bases=dict(console=str(console),pc=str(pc))
        coefficient_options={}
        region_markets={}
        for region in controls:
            p=region['platforms'][0];key=str(region['region_id'])+':'+p
            mutable=(not plan or region['resource'] in plan['resources']) and mode=='revenue_sprint'
            coefficient_options[key]=[number(region['factor'])]
            if mutable:
                try:
                    group='pc' if p=='PC' else 'console'
                    if group not in comparisons:raise ValueError('pricing_region_global_market_unavailable')
                    market=competition(evidence,[p],now,region=21,plan=plan,resolved_global=comparisons[group],evaluation_context=evaluation_context,base_total=bases[group])
                    region_markets[key]=market
                    factors=[number(f) for f in market['legal_coefficients']]
                    if not factors:raise ValueError('INFEASIBLE_REGION_COEFFICIENT_AND_COMPETITIVE_BAND')
                    coefficient_options[key]=factors
                except ValueError as exc:
                    failures.append(dict(scope=key,code=str(exc)))
                    region_markets.pop(key,None)
        keys=list(coefficient_options)
        for combination in itertools.product(*(coefficient_options[k] for k in keys)):
          action=dict(base_prices=bases,region_coefficients=dict(zip(keys,map(str,combination))))
          try:
            affected_regions=proof_regions(evidence,current,action,promised_regions=region_markets,minimum_average_platforms=average30_platforms)
            proof = financial(evidence,action,now,regions=affected_regions,evaluation_context=evaluation_context)
            average30_proof=daily_average_target_proof(evidence,proof,average30_platforms)
            minimum_proofs={}
            for group,ps in GROUPS.items():
                targeted=[p for p in ps if p in average30_platforms]
                if not targeted:continue
                if group in daily_targets and number(bases[group])>number(daily_targets[group]['minimum_legal_base_total']):continue
                lower=deepcopy(action);lower['base_prices'][group]=str(number(bases[group])-CENT)
                try:
                    previous=financial(evidence,lower,now,regions=affected_regions,evaluation_context=evaluation_context)
                    daily_average_target_proof(evidence,previous,targeted)
                except ValueError as exc:
                    if str(exc) not in ('pricing_daily_missing_market_average_30','pricing_hard_margin_floor','pricing_average_catalog_margin_floor'):raise
                    minimum_proofs[group]=dict(previous_cent=lower['base_prices'][group],rejected_by=str(exc),average_margin_target_pct='30')
                else:raise ValueError('pricing_daily_minimum_average_30_not_established')
            for group,target in daily_targets.items():
                if not target['financial_floor_applied'] or group in minimum_proofs:continue
                lower=deepcopy(action);lower['base_prices'][group]=str(number(bases[group])-CENT)
                try:financial(evidence,lower,now,regions=affected_regions,evaluation_context=evaluation_context)
                except ValueError as exc:
                    if str(exc) not in ('pricing_hard_margin_floor','pricing_average_catalog_margin_floor'):raise
                    minimum_proofs[group]=dict(previous_cent=lower['base_prices'][group],rejected_by=str(exc),item_target_below_legal_floor=True)
                else:raise ValueError('pricing_floor_minimality_not_established')
            for group,market in comparisons.items():
                if market['decision_type']!='floor_fallback':continue
                lower=deepcopy(action);lower['base_prices'][group]=str(number(bases[group])-CENT)
                for region in controls:
                    for platform in region['platforms']:
                        key=str(region['region_id'])+':'+platform
                        if platform in GROUPS[group] and (not plan or 'region:'+key in plan['resources']):lower['region_coefficients'][key]='1'
                try:financial(evidence,lower,now,regions=proof_regions(evidence,current,lower),evaluation_context=evaluation_context)
                except ValueError as exc:
                    if str(exc) not in ('pricing_catalog_hard_margin_floor','pricing_average_catalog_margin_floor','pricing_average_margin_floor','pricing_hard_margin_floor','pricing_average_region_tier_margin_floor'):raise
                    minimum_proofs[group]=dict(previous_cent=str(lower['base_prices'][group]),rejected_by=str(exc),all_mutable_region_factors_tested_at_maximum=True)
                else:raise ValueError('pricing_floor_minimality_not_established')
            for key,market in region_markets.items():
                actual=number(proof['prices'][key]['price']['delivered_unit_100k']) if key in proof['prices'] else number(evidence['storefront']['rows'][key.split(':')[1]]['package_usd'])/105*100
                if market['decision_type']=='regional_follow_global':
                    if number(action['region_coefficients'][key])!=1:raise ValueError('pricing_saudi_follow_global_factor_must_be_one')
                elif market['decision_type']!='floor_fallback':
                    target=market['targets'][key.split(':')[1]]
                    if not number(target['unit_low'])<=actual<=number(target['unit_high']):raise ValueError('pricing_regional_competitive_band')
            path=commit_path(current,action,lambda state:financial(evidence,state,now,regions=affected_regions,evaluation_context=evaluation_context),
                             transition=lambda old,new:preserve_competitive_state(evidence,old,new,comparisons,region_markets))
            rating = score(mode,action,evidence,proof,anchor,evaluation_context,(plan or {}).get('parameters'))
            regional_index=Decimal(0)
            for key in region_markets:
                actual=number(proof['prices'][key]['price']['regular_usd']) if key in proof['prices'] else number(bases['pc' if key.endswith(':PC') else 'console'])*number(action['region_coefficients'][key])
                p=key.split(':')[1];ref=number(anchor['base_prices']['pc' if p=='PC' else 'console'])*number(current['region_coefficients'][key])
                regional_index+=demand(actual,ref,'1')*actual/ref
            rating['regional_prior_revenue_index']=str(regional_index)
            preference=number((plan or {}).get('parameters',{}).get('preferred_undercut_pct','7.5'),zero=True)
            preference_distance=sum(abs(number(bases[g])-min(number(t['undiscounted_total']) for t in market['targets'].values())*(1-preference/100)) for g,market in comparisons.items() if market['targets'])
            rating['preferred_undercut_pct']=str(preference)
            rating['preference_distance']=str(preference_distance)
            fallback=any(m['decision_type']=='floor_fallback' or m.get('reason')=='SAUDI_MARGIN_FLOOR_FOLLOW_GLOBAL' for m in list(comparisons.values())+list(region_markets.values()))
            positions={}
            for scope,market in list(comparisons.items())+list(region_markets.items()):
                positions[scope]={}
                for p,target in market['targets'].items():
                    actual=number(proof['prices'][scope if ':' in scope else 'global:'+p]['price']['delivered_unit_100k'])
                    positions[scope][p]=dict(actual_unit_100k=str(actual),anchor=market['anchors'][p],
                        actual_undercut_pct=str((1-actual/number(target['anchor_unit_100k']))*100),
                        difference_pct={q['source']:str((actual/number(q['unit_100k'])-1)*100) for q in market['quotes'] if q['platform']==p},
                        competitive_band_met=number(target['unit_low'])<=actual<=number(target['unit_high']))
                for p,available in market['competition_available'].items():
                    if not available:positions[scope][p]=dict(competition_available=False,competitive_band_met=False,reason='BOTH_COMPETITOR_QUOTES_MISSING')
            feasible.append(dict(action=action,action_sha256=fingerprint(action),steps=path,financial_proof=proof,market_comparison=deepcopy(comparisons),regional_market_comparison=region_markets,score=rating,
                                 daily_reference=deepcopy(daily_inputs),
                                 daily_pricing=deepcopy(daily_targets),
                                 daily_average_target_proof=average30_proof,
                                 minimum_legal_price_proof=minimum_proofs,market_position=positions,
                                 decision_type='floor_fallback' if fallback else 'competitive' if mode=='revenue_sprint' else 'objective',
                                 decision_reason='MARGIN_FLOOR_FALLBACK_20' if fallback else 'DAILY_ITEMD2R_TARGET_BELOW_MARGIN_FLOOR' if any(t['financial_floor_applied'] for t in daily_targets.values()) else 'DAILY_ITEMD2R_PUBLIC_CENT_NOT_REACHABLE' if any(not t['item_target_met'] for t in daily_targets.values()) else 'DAILY_ITEMD2R_ACTUAL_DELIVERY_TARGET' if daily_targets else 'DAILY_MISSING_REFERENCE_AVERAGE_MARGIN_30' if average30_platforms else mode+'_objective',
                                 sprint_policy_version=SPRINT_POLICY_VERSION if mode=='revenue_sprint' else None,financial_contract_version=proof['financial_contract_version'],
                                 control=action==current))
          except ValueError as exc:
            failures.append(dict(scope='joint',code=str(exc)))
    if feasible:
        reference=max(feasible,key=lambda c:Decimal(c['score']['contribution_index']))
        reference_contribution=Decimal(reference['score']['contribution_index'])
        for candidate in feasible:
            candidate['score']['opportunity_cost']=dict(predicted_loss=str(max(Decimal(0),reference_contribution-Decimal(candidate['score']['contribution_index']))),
                reference_action_sha256=reference['action_sha256'],reference_contribution=str(reference_contribution),enforced=False)
    feasible.sort(key=lambda c: (Decimal(c['score']['objective']),Decimal(c['score'].get('regional_prior_revenue_index','0')),Decimal(c['score']['contribution_index']),-Decimal(c['score'].get('preference_distance','0'))),reverse=True)
    valid_until = min([now+timedelta(seconds=900)]+[instant(c['valid_until']) for c in comparisons.values()]+[instant(c['valid_until']) for f in feasible for c in f.get('regional_market_comparison',{}).values()])
    return dict(schema_version=VERSION,pricing_scope=PRICING_SCOPE,mode=mode,status='READY' if feasible else 'INFEASIBLE',
                candidates=feasible,selected=feasible[0] if feasible else None,failures=failures,
                current=current,anchor=anchor,valid_until=valid_until.isoformat(),
                execution_authorized=False,write_performed=False,
                target=monthly_target((evidence.get('monthly_target') or {}).get('amount'),
                    (evidence.get('monthly_target') or {}).get('mtd'),now,(plan or {}).get('ends_at'),metadata=evidence.get('monthly_target')))


def controlled_candidate(evidence,current,control,plan,now,selected=None):
    """Operator price wins; otherwise mark up the freshly selected strategy action once."""
    manual=control['manual_enabled']
    if not manual and not control['uplift_enabled']:return selected
    fresh(evidence['checked_at'],now)
    fresh(evidence['fx']['checked_at'],now)
    original=deepcopy(selected)
    action=deepcopy(current if manual else selected['action'])
    for group in GROUPS:
        if 'base:'+group not in plan['resources']:continue
        target=number(control['manual_prices'][group])*100 if manual else number(action['base_prices'][group])*(1+number(control['uplift_pct'],zero=True)/100)
        action['base_prices'][group]=str(money(target,ROUND_HALF_UP))
    average30=[p for g,ps in GROUPS.items() if 'base:'+g in plan['resources'] for p in ps
               if not manual and selected.get('daily_reference',{}).get(p,{}).get('average_margin_target_pct')=='30']
    regions=proof_regions(evidence,current,action,promised_regions=(selected or {}).get('regional_market_comparison',{}),minimum_average_platforms=average30)
    proof=financial(evidence,action,now,regions=regions)
    average_proof=daily_average_target_proof(evidence,proof,average30)
    steps=commit_path(current,action,lambda state:financial(evidence,state,now,regions=regions))
    result=deepcopy(selected) if selected else dict(market_comparison={},regional_market_comparison={},
        market_position={},daily_reference={},daily_pricing={},minimum_legal_price_proof={},
        score=dict(objective='0',revenue=None,contribution=None,absolute_forecast_available=False,status='manual_intervention'))
    result.update(action=action,action_sha256=fingerprint(action),steps=steps,financial_proof=proof,
        daily_average_target_proof=average_proof,control=action==current,price_control=deepcopy(control),
        strategy_action=original['action'] if original else None,
        decision_type='manual_intervention' if manual else 'temporary_uplift',
        decision_reason='OPERATOR_MANUAL_PRICE' if manual else 'OPERATOR_TEMPORARY_UPLIFT')
    # Strategy minimum/competition proofs describe X, never the operator's final price.
    result['strategy_decision']=original
    result['minimum_legal_price_proof']={}
    if not manual:
        result['score']=score(plan['mode'],action,evidence,proof,plan.get('price_anchor') or current,parameters=plan.get('parameters'))
        for scope,market in list(result['market_comparison'].items())+list(result['regional_market_comparison'].items()):
            for platform,target in market['targets'].items():
                actual=number(proof['prices'][scope if ':' in scope else 'global:'+platform]['price']['delivered_unit_100k'])
                position=result['market_position'][scope][platform]
                position.update(actual_unit_100k=str(actual),actual_undercut_pct=str((1-actual/number(target['anchor_unit_100k']))*100),
                    difference_pct={q['source']:str((actual/number(q['unit_100k'])-1)*100) for q in market['quotes'] if q['platform']==platform},
                    competitive_band_met=number(target['unit_low'])<=actual<=number(target['unit_high']))
    return result


def proof_regions(evidence,before,after,promised_regions=(),minimum_average_platforms=()):
    """Proof also supplies scored hold prices; write leases use impacted_regions only."""
    result=impacted_regions(evidence,before,after,promised_regions)
    for region in evidence.get('region_rules',[])+evidence.get('regional_controls',[]):
        key=(region['region_id'],tuple(region['platforms']))
        if not any((r['region_id'],tuple(r['platforms']))==key for r in result) and set(region['platforms'])&set(minimum_average_platforms):result.append(region)
    for region in evidence.get('region_rules',[]):
        if region not in result and any(seg['region_id']==region['region_id'] and seg['platform'] in region['platforms']
                for seg in (evidence.get('demand_model') or {}).get('segments',[])):
            result.append(region)
    return result


def impacted_regions(evidence,before,after,promised_regions=()):
    selected={}
    for r in evidence.get('region_rules',[])+evidence.get('regional_controls',[]):
        coefficient_changed=any(after.get('region_coefficients',{}).get(str(r['region_id'])+':'+p,r['factor'])!=before.get('region_coefficients',{}).get(str(r['region_id'])+':'+p,r['factor']) for p in r['platforms'])
        promised=any(str(r['region_id'])+':'+p in promised_regions for p in r['platforms'])
        if r in evidence.get('regional_controls',[]) and r.get('id') is None and not coefficient_changed and not promised:
            continue
        changed=any(after['base_prices']['pc' if p=='PC' else 'console']!=before['base_prices']['pc' if p=='PC' else 'console'] or
                    after.get('region_coefficients',{}).get(str(r['region_id'])+':'+p,r['factor'])!=before.get('region_coefficients',{}).get(str(r['region_id'])+':'+p,r['factor']) for p in r['platforms'])
        if changed or promised:
            key=(r['region_id'],tuple(r['platforms']))
            selected[key]=r
    return list(selected.values())


def preserve_competitive_state(evidence,before,after,markets,regional_markets):
    """Final targets satisfy the band; transitions cannot become more expensive than its ceiling."""
    scopes=[(p,None,t) for market in markets.values() if market.get('decision_type')!='floor_fallback' for p,t in market['targets'].items()]
    scopes += [(key.split(':')[1],key,t) for key,market in regional_markets.items() if market.get('decision_type') not in ('floor_fallback','regional_follow_global') for t in market['targets'].values()]
    packages=evidence['promotion_envelope']['packages']
    for platform,region_key,target in scopes:
        group='pc' if platform=='PC' else 'console'
        tier=next(t for t in packages[platform]['tiers'] if number(t['base_k'])==100)
        prices=[]
        for action in (before,after):
            factor=action.get('region_coefficients',{}).get(region_key,'1') if region_key else '1'
            prices.append(number(render(number(action['base_prices'][group])/100,tier,factor)['delivered_unit_100k']))
        low,high=number(target['unit_low']),number(target['unit_high'])
        if prices[0]<=high and prices[1]>high:
            raise ValueError('pricing_intermediate_competitive_commitment_lost')


def solve_coefficient(base_total, target_unit_low, target_unit_high, delivered_k, minimum_factor='0.0001', maximum_factor='1'):
    """Continuous bounds narrowed inward at the real four-decimal input precision."""
    step = Decimal('.0001')
    low = max(number(minimum_factor),number(target_unit_low)*number(delivered_k)/100/number(base_total))
    high = min(number(maximum_factor),number(target_unit_high)*number(delivered_k)/100/number(base_total))
    low = low.quantize(step,rounding=ROUND_UP)
    high = high.quantize(step,rounding=ROUND_DOWN)
    if low > high:
        return []
    return sorted({low,high,((low+high)/2).quantize(step,rounding=ROUND_DOWN)})


def commit_path(before, after, validate,transition=None):
    old_prices={key:number(value) for key,value in before['base_prices'].items()}
    new_prices={key:number(value) for key,value in after['base_prices'].items()}
    changes = [('base_prices','all')] if old_prices!=new_prices else []
    old_factors=before.get('region_coefficients',{})
    changes += [('region_coefficients',key) for key,value in after.get('region_coefficients',{}).items()
                if key not in old_factors or number(old_factors[key])!=number(value)]
    for order in itertools.permutations(changes):
        state = deepcopy(before)
        steps = []
        try:
            for section,key in order:
                prior=deepcopy(state)
                if section=='base_prices':
                    state['base_prices']=deepcopy(after['base_prices'])
                    value=after['base_prices']
                else:
                    state.setdefault(section,{})[key] = after[section][key]
                    value=after[section][key]
                validate(state)
                if transition:transition(prior,state)
                steps.append(dict(step_id=section+':'+key,kind='base' if section=='base_prices' else 'region',
                                  key=key,value=value,state='PREPARED',intermediate=deepcopy(state)))
            return steps
        except ValueError:
            continue
    if changes:
        raise ValueError('NO_SAFE_COMMIT_PATH')
    return []
