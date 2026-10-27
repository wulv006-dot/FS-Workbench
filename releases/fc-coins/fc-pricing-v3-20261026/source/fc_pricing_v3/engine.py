"""Five objectives over one exact price/financial contract; no legacy selector."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
import itertools

from . import VERSION
from .financial import (number, fingerprint, fresh, instant, common_cost, envelope_ratio,
                        required_history_ratio, catalog_floor, prove_catalog, prove_price,
                        average_margin, MARGIN_BASIS, CENT, HARD_MARGIN, FINANCIAL_CONTRACT_VERSION)

PLATFORMS = ('PS','XBOX','PC')
GROUPS = {'console':('PS','XBOX'), 'pc':('PC',)}
SPRINT_POLICY_VERSION = 'sprint_5_10_itemd2r_floor20_v2'
POLICIES = {
    'daily':dict(offsets=(-8,-4,0,4,8), allocation=(.2,.6,.2)),
    'acquisition':dict(offsets=(-20,-15,-10,-5,0,5), allocation=(.2,.4,.4)),
    'backlog':dict(offsets=(0,5,10,15,20), allocation=(0,1,0)),
    'flash_sale':dict(offsets=(-25,-20,-15,-10,-5,0), allocation=(.1,.6,.3)),
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
        current=number(evidence['storefront']['rows'][platform]['package_usd'])
        package_cost=delivered*cost/fx
        rows[platform]=dict(cost_cny_per_1k=str(cost),cost_usd_per_1k=str(cost/fx),
            package_cost_usd=str(package_cost),delivered_k=str(delivered),
            current_regular_usd=str(current),current_regular_margin_pct=str((current-package_cost)/current*100),
            current_average_margin_pct=str((current*average-package_cost)/(current*average)*100),
            regular_floor_usd=str(catalog_floor(cost,fx,ratio,HARD_MARGIN,rules)*100),
            average_floor_usd=str(catalog_floor(cost,fx,ratio,HARD_MARGIN,rules,average_ratio=average)*100),
            cost_checked_at=evidence['costs'][platform]['checked_at'])
    return dict(status='available',rows=rows,as_of=now.isoformat(),scope='global_catalog_base_100k',
                historical_retained_ratio=str(average),minimum_margin_pct=str(HARD_MARGIN),execution_authorized=False)


def required_unit_bound(evidence,platform,now,region=None,evaluation_context=None):
    pooled,_=common_cost(evidence)
    cost=pooled if platform!='PC' else number(evidence['costs']['PC']['cny_per_1k'])
    average=history_ratio(evidence,now,evaluation_context)
    if region:
        history=region.get('history') or {}
        if history.get('replay_paths'):average=mixed_ratio_lower_bound(history)
        elif history.get('basis')!='pooled_other_promotions_excluding_region_verified':
            raise ValueError('pricing_region_history_basis_unknown:'+str(region['region_id']))
    rules=evidence['promotion_envelope']['packages'][platform]
    unit=catalog_floor(cost,evidence['fx']['cny_per_usd'],envelope_ratio(evidence['promotion_envelope'],now),HARD_MARGIN,rules,average_ratio=average)
    return unit+(CENT/number(rules['min_custom_k']) if region else 0)


def required_base_bound(evidence,platform,now,plan=None,evaluation_context=None):
    bound=required_unit_bound(evidence,platform,now,evaluation_context=evaluation_context)
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
        bound=max(bound,required_unit_bound(evidence,platform,now,region,evaluation_context)/factor)
    return (bound*100).quantize(CENT,rounding=ROUND_UP)


def quote_identity(row):
    return tuple(row.get(k) for k in ('source','platform','purchase_k','delivered_k','delivery','delivery_method','price_basis','coupon_excluded','conditional'))

def base_limits(public_low,public_high,retained):
    retained=number(retained)
    low=((public_low-CENT/2)/retained).quantize(CENT,rounding=ROUND_UP)
    high=((public_high+CENT/2)/retained).quantize(CENT,rounding=ROUND_UP)-CENT
    return low,high


def resolve_anchor(evidence,platform,quotes,now):
    lootbar,item=(next(q for q in quotes if q['source']==source and q['platform']==platform) for source in ('Lootbar','ItemD2R'))
    chosen=item if number(item['unit_100k'])<=number(lootbar['unit_100k']) else lootbar
    result=dict(source=chosen['source'],unit_100k=chosen['unit_100k'],reason='ITEMD2R_LOWER_VALID_QUOTE' if chosen is item else 'LOOTBAR_LOWER_VALID_QUOTE')
    if chosen is item:return result
    context=(evidence.get('sprint_anchor_context') or {}).get(platform,{})
    previous=context.get('previous') or {}
    continuing=previous.get('reason')=='ITEMD2R_COST_RESPONSE'
    baseline=previous.get('baseline') if continuing else context.get('baseline')
    if not baseline:return result
    old=baseline.get('quotes') or {}
    if set(old)!={'Lootbar','ItemD2R'} or any(quote_identity(old[s])!=quote_identity(q) for s,q in (('Lootbar',lootbar),('ItemD2R',item))):return result
    if instant(baseline['created_at'])>now or not continuing and (now-instant(baseline['created_at'])).total_seconds()>21600:return result
    pooled,_=common_cost(evidence)
    cny=pooled if platform!='PC' else number(evidence['costs']['PC']['cny_per_1k'])
    cost=cny/number(evidence['fx']['cny_per_usd'])
    dc=cost/number(baseline['cost_usd_per_k'])-1
    di=number(item['unit_100k'])/number(old['ItemD2R']['unit_100k'])-1
    dl=number(lootbar['unit_100k'])/number(old['Lootbar']['unit_100k'])-1
    gap=number(item['unit_100k'])/number(lootbar['unit_100k'])-1
    matched=(dc>0 and di>0 and gap>Decimal('.02')) if continuing else dc>=Decimal('.05') and di>=Decimal('.05') and abs(dl)<=Decimal('.02') and gap>=Decimal('.05')
    if matched:result.update(source='ItemD2R',unit_100k=item['unit_100k'],reason='ITEMD2R_COST_RESPONSE',baseline=baseline,
        changes_pct=dict(cost=str(dc*100),itemd2r=str(di*100),lootbar=str(dl*100),gap=str(gap*100)),continuing=continuing,
        cost_components=dict(cny_per_k=str(cny),fx_cny_per_usd=evidence['fx']['cny_per_usd']))
    return result


def competition(evidence, platforms, now, region=None, *, plan=None, resolved_global=None,evaluation_context=None,base_total=None):
    sprint_parameters(plan)
    quotes = [market_quote(evidence,p,s,now,region) for p in platforms for s in ('Lootbar','ItemD2R')]
    regional_fallbacks={}
    if region==21:
        for p in platforms:
            try:quotes.append(market_quote(evidence,p,'ArabUT',now,region))
            except ValueError as error:regional_fallbacks[p]=dict(mode='follow_global',reason=str(error))
    times = [instant(q['captured_at']) for q in quotes]
    if (max(times)-min(times)).total_seconds() > 300:
        raise ValueError('pricing_market_capture_span')
    anchors={p:deepcopy(resolved_global['anchors'][p]) if resolved_global else resolve_anchor(evidence,p,quotes,now) for p in platforms}
    def limits(choices):
      targets={}
      for p in platforms:
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
    if region is None:
        floor=max(required_base_bound(evidence,p,now,plan,evaluation_context) for p in platforms)
        minimum_base=str(floor)
        def feasible(values):return max([floor]+[number(t['total_low']) for t in values.values()])<=min(number(t['total_high']) for t in values.values())
        attempts.append(dict(anchors=deepcopy(anchors),targets=deepcopy(targets),financial_interval_feasible=feasible(targets)))
        if not feasible(targets):
            options=[[anchors[p]]+([dict(source='ItemD2R',unit_100k=next(q['unit_100k'] for q in quotes if q['source']=='ItemD2R' and q['platform']==p),reason='ITEMD2R_CURRENT_COST_CONFLICT')]
                     if anchors[p]['source']=='Lootbar' else []) for p in platforms]
            for choice in itertools.product(*options):
                alternative=dict(zip(platforms,deepcopy(choice)));candidate=limits(alternative)
                if alternative==anchors:continue
                attempts.append(dict(anchors=deepcopy(alternative),targets=deepcopy(candidate),financial_interval_feasible=feasible(candidate)))
                if feasible(candidate):anchors,targets=alternative,candidate;break
        if not feasible(targets):decision_type='floor_fallback'
    elif base_total is not None:
        p=platforms[0]
        if p in regional_fallbacks:
            coefficients=['1'];decision_type='regional_follow_global'
        else:
            region_rule=next(r for r in evidence['regional_controls'] if r['region_id']==region and p in r['platforms'])
            floor_factor=(required_unit_bound(evidence,p,now,region_rule,evaluation_context)*100/number(base_total)).quantize(Decimal('.0001'),rounding=ROUND_UP)
            if floor_factor>1:raise ValueError('INFEASIBLE_REGION_FINANCIAL_AND_BASE_PRICE')
            target=targets[p];delivered=100+number(evidence['storefront']['rows'][p]['bonus_k'],zero=True)
            tier=next(t for t in evidence['promotion_envelope']['packages'][p]['tiers'] if number(t['base_k'])==100)
            before_region=render(number(base_total)/100,tier)['before_region_usd']
            coefficients=[str(f) for f in solve_coefficient(before_region,target['unit_low'],target['unit_high'],delivered,minimum_factor=str(max(Decimal('.0001'),floor_factor)))]
            if not coefficients:
                coefficients=[str(max(Decimal('.0001'),floor_factor))];decision_type='floor_fallback'
    return dict(quotes=quotes, targets=targets, valid_until=(min(times)+timedelta(seconds=900)).isoformat(),
                anchors=anchors,anchor_attempts=attempts,regional_fallbacks=regional_fallbacks,sprint_policy_version=SPRINT_POLICY_VERSION,financial_contract_version=FINANCIAL_CONTRACT_VERSION,
                decision_type=decision_type,reason='SAUDI_MISSING_QUOTE_FOLLOW_GLOBAL' if decision_type=='regional_follow_global' else 'MARGIN_FLOOR_FALLBACK_20' if decision_type=='floor_fallback' else 'VERIFIED_COMPETITIVE_BAND',
                minimum_legal_base_total=minimum_base,legal_coefficients=coefficients,
                scope='100K anchor only; complete financial catalog separately proven')


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
        tier = next(t for t in packages[p]['tiers'] if number(t['base_k'])==100)
        shown = render(unit,tier)
        base_proof = prove_price(unit,c,fx,shown['delivered_k'],'100',ratio)
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
            regional_unit = unit*number(coefficient)
            # The exact replay basis is pinned by the source contract, never inferred from averages.
            history = region.get('history') or {}
            if history.get('basis')=='historical_eligibility_current_terms_projected' and history.get('basis_lower_bound_sufficient') is not True:
                raise ValueError('pricing_region_original_basis_projection_unverified')
            if history.get('replay_paths'):
                regional_average = mixed_ratio_lower_bound(history)
                history_basis = 'verified_observed_paths_replay'
            elif history.get('basis') == 'pooled_other_promotions_excluding_region_verified':
                regional_average = average
                history_basis = 'global_pooled_actual_mix_regional_projection'
            else:
                raise ValueError('pricing_region_history_basis_unknown:'+str(region['region_id']))
            # One extra region rounding can lose at most one cent for any allowed integer-K.
            region_rounding_bound = Decimal(0) if region.get('id') is None and number(coefficient)==1 else CENT/number(packages[p]['min_custom_k'])
            regional_catalog = prove_catalog(regional_unit-region_rounding_bound,c,fx,ratio,HARD_MARGIN,packages[p],average_ratio=regional_average)
            regional_catalog['extra_region_rounding_bound_per_k'] = str(region_rounding_bound)
            for regional_tier in packages[p]['tiers']:
                exact = render(unit,regional_tier,coefficient,rounding=ROUND_HALF_UP if region.get('rounding')=='half_up_cent' else ROUND_DOWN)
                exact_proof = prove_price(number(exact['regular_usd'])/number(exact['purchase_k']),c,fx,
                                          exact['delivered_k'],exact['purchase_k'],ratio)
                tier_average=replay_history(exact['regular_usd'],history) if history.get('replay_paths') else regional_average
                net = number(exact['regular_usd'])*tier_average
                if (net-number(exact_proof['delivered_cost_usd']))/net*100 < HARD_MARGIN:
                    raise ValueError('pricing_average_region_tier_margin_floor')
            regional_catalog['average_bound_basis']='same_actual_amount_weights_per_observed_path; thresholds/caps ignored only for sufficient all_integer_K_bound'
            price = render(unit,tier,coefficient,rounding=ROUND_HALF_UP if region.get('rounding')=='half_up_cent' else ROUND_DOWN)
            results[str(region['region_id'])+':'+p] = dict(catalog=regional_catalog, price=price,
                 coefficient=str(coefficient), rule_id=region.get('id'), history_basis=history_basis,
                 history_source_sha256=history.get('source_sha256'),original_basis_reconciliation=history.get('original_basis_reconciliation'),
                 status='regional_projection', source_scope=history.get('source_scope','global_pooled_actual_mix'),
                 application_scope='region_'+str(region['region_id']))
    return dict(pass_all=True, margin_basis=MARGIN_BASIS, minimum_pct=str(HARD_MARGIN), financial_contract_version=FINANCIAL_CONTRACT_VERSION, common_console_cost=pool,
                proof_kind='actual_seven_day_mix' if evaluation_context is None else 'shadow_simulated_projection',
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
    projected_delivery_k=Decimal(0)
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
        if mode=='backlog':
            capacity = evidence.get('capacity_k_per_block')
            backlog = evidence.get('backlog_k')
            delivered = baseline.get('delivered_k_per_order')
            if capacity is None or backlog is None or delivered is None or not has_baseline:
                raise ValueError('pricing_capacity_data_pending')
            reserve=number((parameters or {}).get('capacity_reserve_ratio','.10'),zero=True)
            projected_delivery_k+=orders*number(delivered)
        group_objective = group_revenue if mode=='revenue_sprint' else orders*number(baseline['new_customer_ratio'],zero=True) if mode=='acquisition' and baseline.get('new_customer_ratio') is not None else group_contribution
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
        objective += income if mode=='revenue_sprint' else orders*number(new_ratio,zero=True) if mode=='acquisition' and new_ratio is not None else profit
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
        if mode=='backlog':
            if segment.get('delivered_k_per_order') is None:raise ValueError('pricing_capacity_segment_quantity_pending')
            projected_delivery_k+=orders*number(segment['delivered_k_per_order'])
    queue_projection=None
    if mode=='backlog':
        reserve=number((parameters or {}).get('capacity_reserve_ratio','.10'),zero=True)
        usable=number(evidence['capacity_k_per_block'],zero=True)*(1-reserve)
        remaining=max(Decimal(0),number(evidence['backlog_k'],zero=True)+projected_delivery_k-usable)
        estimated=evidence.get('capacity_is_estimate') is True
        due=evidence.get('due_committed_backlog_k')
        if not estimated and projected_delivery_k+number(evidence['backlog_k'] if due is None else due,zero=True)>usable:
            raise ValueError('CAPACITY_UNRESOLVED_BY_PRICE')
        if due is not None and projected_delivery_k+number(due,zero=True)>usable and not estimated:
            raise ValueError('CAPACITY_UNRESOLVED_BY_PRICE')
        queue_projection=dict(new_delivery_k=str(projected_delivery_k),usable_capacity_k=str(usable),
            opening_backlog_upper_bound_k=str(evidence['backlog_k']),remaining_backlog_upper_bound_k=str(remaining),
            due_committed_backlog_k=due,status='initial_queue_evolution_estimate_not_SLA_proof' if estimated else 'verified_capacity_constraint')
        if estimated:objective=-remaining
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


def evaluate(evidence, mode, *, plan=None, now=None,evaluation_context=None,explicit_prices=None):
    now = now or datetime.now(timezone.utc)
    if mode not in POLICIES:
        raise ValueError('pricing_strategy_unknown')
    fresh(evidence['checked_at'],now)
    fresh(evidence['fx']['checked_at'],now)
    controls=evidence.get('regional_controls',[])
    current = dict(base_prices={g:str(max(number(evidence['storefront']['rows'][p]['package_usd']) for p in ps)) for g,ps in GROUPS.items()},
                   region_coefficients={str(r['region_id'])+':'+r['platforms'][0]:r['factor'] for r in controls})
    anchor = deepcopy((plan or {}).get('price_anchor') or current)
    regions = evidence.get('region_rules',[])
    options = {}
    comparisons = {}
    failures = []
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
        floor = max(required_base_bound(evidence,p,now,bound_plan if mode!='revenue_sprint' else plan,evaluation_context) for p in platforms)
        if mode == 'revenue_sprint':
            try:
                market = competition(evidence,platforms,now,plan=plan,evaluation_context=evaluation_context)
                comparisons[group] = market
                low = max(number(market['targets'][p]['total_low']) for p in platforms)
                high = min(number(market['targets'][p]['total_high']) for p in platforms)
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
            affected_regions=proof_regions(evidence,current,action,promised_regions=region_markets)
            proof = financial(evidence,action,now,regions=affected_regions,evaluation_context=evaluation_context)
            minimum_proofs={}
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
                target=market['targets'][key.split(':')[1]]
                if market['decision_type']=='regional_follow_global':
                    if number(action['region_coefficients'][key])!=1:raise ValueError('pricing_saudi_missing_quote_must_follow_global')
                elif market['decision_type']!='floor_fallback' and not number(target['unit_low'])<=actual<=number(target['unit_high']):raise ValueError('pricing_regional_competitive_band')
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
            preference_distance=sum(abs(number(bases[g])-min(number(t['undiscounted_total']) for t in market['targets'].values())*(1-preference/100)) for g,market in comparisons.items())
            rating['preferred_undercut_pct']=str(preference)
            rating['preference_distance']=str(preference_distance)
            fallback=any(m['decision_type']=='floor_fallback' for m in list(comparisons.values())+list(region_markets.values()))
            positions={}
            for scope,market in list(comparisons.items())+list(region_markets.items()):
                positions[scope]={}
                for p,target in market['targets'].items():
                    actual=number(proof['prices'][scope if ':' in scope else 'global:'+p]['price']['delivered_unit_100k'])
                    positions[scope][p]=dict(actual_unit_100k=str(actual),anchor=market['anchors'][p],
                        actual_undercut_pct=str((1-actual/number(target['anchor_unit_100k']))*100),
                        difference_pct={q['source']:str((actual/number(q['unit_100k'])-1)*100) for q in market['quotes'] if q['platform']==p},
                        competitive_band_met=number(target['unit_low'])<=actual<=number(target['unit_high']))
            feasible.append(dict(action=action,action_sha256=fingerprint(action),steps=path,financial_proof=proof,market_comparison=deepcopy(comparisons),regional_market_comparison=region_markets,score=rating,
                                 minimum_legal_price_proof=minimum_proofs,market_position=positions,
                                 decision_type='floor_fallback' if fallback else 'competitive' if mode=='revenue_sprint' else 'objective',
                                 decision_reason='MARGIN_FLOOR_FALLBACK_20' if fallback else mode+'_objective',
                                 sprint_policy_version=SPRINT_POLICY_VERSION if mode=='revenue_sprint' else None,financial_contract_version=FINANCIAL_CONTRACT_VERSION,
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
    return dict(schema_version=VERSION,mode=mode,status='READY' if feasible else 'INFEASIBLE',
                candidates=feasible,selected=feasible[0] if feasible else None,failures=failures,
                current=current,anchor=anchor,valid_until=valid_until.isoformat(),
                execution_authorized=False,write_performed=False,
                target=monthly_target((evidence.get('monthly_target') or {}).get('amount'),
                    (evidence.get('monthly_target') or {}).get('mtd'),now,(plan or {}).get('ends_at'),metadata=evidence.get('monthly_target')))


def proof_regions(evidence,before,after,promised_regions=()):
    """Proof also supplies scored hold prices; write leases use impacted_regions only."""
    result=impacted_regions(evidence,before,after,promised_regions)
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
    """A new transition cannot lose an already attained same-source competitive band."""
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
        if low<=prices[0]<=high and not low<=prices[1]<=high:
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
    changes = [('base_prices','all')] if before['base_prices']!=after['base_prices'] else []
    changes += [('region_coefficients',key) for key in after.get('region_coefficients',{}) if before.get('region_coefficients',{}).get(key)!=after['region_coefficients'][key]]
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
        # Narrow coupled price/coefficient changes without crossing either proof boundary.
        state=deepcopy(before);steps=[]
        for _ in range(24):
            if state==after:return steps
            progress=False
            for section,key in changes:
                keys=list(after[section]) if key=='all' else [key]
                for denominator in (1,2,4,8,16,32,64):
                    trial=deepcopy(state)
                    for name in keys:
                        old=number(state[section][name]);target=number(after[section][name])
                        precision=CENT if section=='base_prices' else Decimal('.0001')
                        value=(old+(target-old)/denominator).quantize(precision,rounding=ROUND_HALF_UP)
                        trial[section][name]=after[section][name] if value==target else str(value)
                    if all(number(trial[section][name])==number(state[section][name]) for name in keys):continue
                    try:
                        validate(trial)
                        if transition:transition(state,trial)
                    except ValueError:continue
                    steps.append(dict(step_id=section+':'+key+':'+str(len(steps)),kind='base' if section=='base_prices' else 'region',
                                      key=key,value=deepcopy(trial[section] if key=='all' else trial[section][key]),state='PREPARED',intermediate=deepcopy(trial)))
                    state=trial;progress=True;break
            if not progress:break
        if state==after:return steps
        raise ValueError('NO_SAFE_COMMIT_PATH')
    return []
