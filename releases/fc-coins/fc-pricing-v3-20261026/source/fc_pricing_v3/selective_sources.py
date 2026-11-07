"""Pure source planning/cache projection and stored-snapshot replay. No network or writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .financial import fingerprint, required_history_ratio, fresh, history_period as financial_history_period, HISTORY_WINDOW_CONTRACT
from . import financial as _math

VERSION='fc27-selective-source-v1'
MODES=('daily','revenue_sprint')
RETIRED=('ELD','U4GM','IGGM','U7Buy')
TZ=timezone(timedelta(hours=8))


CATALOG_CONTRACT='fc-coins-catalog-dual20-v1'


def input_ratio(envelope,now):
    """Old promotion evidence is unchanged; V3 catalog makes no worst-offer claim."""
    if not isinstance(envelope,dict) or envelope.get('contract')!=CATALOG_CONTRACT:
        return _math.envelope_ratio(envelope,now)
    if envelope.get('status')!='verified' or envelope.get('site_id')!=266 or envelope.get('game_id')!=1327:
        raise ValueError('pricing_catalog_unverified')
    if envelope.get('worst_status')!='unknown' or 'minimum_retained_ratio' in envelope:
        raise ValueError('pricing_catalog_promotional_claim')
    fresh(envelope.get('checked_at'),now,900)
    if envelope.get('sha256')!=fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')}):
        raise ValueError('pricing_catalog_hash_changed')
    if not isinstance(envelope.get('packages'),dict) or set(envelope['packages'])!={'PS','XBOX','PC'}:
        raise ValueError('pricing_catalog_scope_invalid')
    return None


def _math_ratio(ratio):
    # The frozen dual20 formulas do not use this legacy argument for a hard or
    # historical-average floor. Zero is internal numeric compatibility only;
    # it is never stored/returned as an observed promotion or fresh envelope.
    return 0 if ratio is None else ratio


def input_catalog_floor(cost,fx,ratio,minimum,rules,*,average_ratio=None):
    return _math.catalog_floor(cost,fx,_math_ratio(ratio),minimum,rules,average_ratio=average_ratio)


def input_prove_catalog(unit,cost,fx,ratio,minimum,rules,*,average_ratio=None):
    return _math.prove_catalog(unit,cost,fx,_math_ratio(ratio),minimum,rules,average_ratio=average_ratio)


def input_prove_price(unit,cost_cny,fx,delivered_k,base_k,ratio,minimum=_math.HARD_MARGIN):
    result=_math.prove_price(unit,cost_cny,fx,delivered_k,base_k,_math_ratio(ratio),minimum)
    if ratio is None:
        for key in ('worst_net_usd','promotional_net_usd','promotional_gross_usd','promotional_margin_pct','rounding_reserve_usd'):
            result[key]=None
        result['promotional_status']='unknown'
    return result


def source_plan(active_mode, scope=None, *, known_region_ids=(), interval_minutes=60):
    if active_mode not in MODES and active_mode!='smart':raise ValueError('selective_active_mode_invalid')
    scope=scope or {}
    interval_minutes=scope.get('interval_minutes',interval_minutes)
    if type(interval_minutes) is not int or interval_minutes<=0:raise ValueError('selective_interval_invalid')
    platforms=scope.get('platforms',['PS','XBOX','PC'])
    if not platforms or set(platforms)-{'PS','XBOX','PC'}:raise ValueError('selective_platform_scope_invalid')
    regions=sorted(set(int(value) for value in known_region_ids)|set(int(value) for value in scope.get('region_ids',[])))
    markets=['Lootbar','ItemD2R']
    if 21 in regions and set(platforms)&{'PS','XBOX'} and (active_mode in ('revenue_sprint','smart') or scope.get('compare_saudi') is True):markets.append('ArabUT')
    core_policy=scope.get('competitor_policy')=='lootbar_primary_arabut_secondary_v1'
    if core_policy:markets=['Lootbar','ArabUT']
    return dict(version=VERSION,active_mode=active_mode,platforms=list(platforms),region_ids=regions,
        required_markets=markets,auxiliary_markets=['ItemD2R'] if core_policy else [],
        market_platforms={name:([p for p in platforms if p in ('PS','XBOX')] if name=='ArabUT' and not core_policy else list(platforms)) for name in markets},
        retired_automatic_sources=list(RETIRED),price_interval_minutes=interval_minutes,
        quote_validity_seconds=900,hard_evidence=['current_cost','current_FX','current_catalog' if scope.get('catalog_only') is True else 'current_promotion_envelope','current_public_price','affected_region_contract'],
        history='D_minus_9_through_D_minus_2_eight_closed_days_and_original_hash_cache',
        refresh_monthly_target=active_mode in ('revenue_sprint','smart') and scope.get('catalog_only') is not True,online_observation_job='preserved_separate_incremental_pipeline',
        historical_orders_in_quote=False,long_window_collection=False)


def planned_source_coverage(snapshot,plan,now,*,reference_market=None):
    """Replacement adapter for the retired four-site grid; same-run/price/time rules remain."""
    required=plan['market_platforms']
    expected={(p,s) for s,platforms in required.items() for p in platforms}
    rows=list(snapshot.get('competitors') or [])
    if 'ItemD2R' in required:rows+=list((reference_market or {}).get('offers') or [])
    if 'ArabUT' in required:rows+=list((snapshot.get('arab_ut_status') or {}).get('offers') or [])
    found={};gaps=[];times=[]
    for row in rows:
        key=(row.get('platform'),row.get('source'))
        if key not in expected:continue
        if key in found:raise ValueError('selective_competitor_duplicate')
        if key[1]!='ArabUT' and (row.get('run_id')!=snapshot['run_id'] or row.get('status')!='valid'):
            gaps.append(dict(platform=key[0],source=key[1],reason='same_run_valid_quote_missing'));continue
        captured=row.get('captured_at') or row.get('checked_at')
        try:fresh(captured,now,900)
        except ValueError:gaps.append(dict(platform=key[0],source=key[1],reason='quote_not_fresh'));continue
        try:
            purchase=Decimal(str(row.get('purchase_k',row.get('base_k'))))
            amount=Decimal(str(row.get('gross_usd',row.get('total_usd','0'))))
        except (InvalidOperation,ValueError,TypeError):
            gaps.append(dict(platform=key[0],source=key[1],reason='public_amount_or_quantity_invalid'));continue
        if (row.get('currency')!='USD' or purchase!=100 or row.get('conditional') is True or row.get('comparable') is False):
            gaps.append(dict(platform=key[0],source=key[1],reason='public_no_coupon_100K_scope_invalid'));continue
        if key[1]=='ArabUT' and (row.get('delivery')!=('standard' if key[0]=='PC' else 'normal') or row.get('selection_verified') is not True):
            gaps.append(dict(platform=key[0],source=key[1],reason='platform_delivery_not_verified'));continue
        if not amount.is_finite() or amount<=0:
            gaps.append(dict(platform=key[0],source=key[1],reason='public_amount_invalid'));continue
        found[key]=row
        times.append(datetime.fromisoformat(captured.replace('Z','+00:00')))
    if times and (max(times)-min(times)).total_seconds()>300:raise ValueError('selective_competitor_capture_span')
    missing=expected-set(found)
    for gap in (reference_market or {}).get('missing',[]):
        if (gap.get('platform'),'ItemD2R') in missing:gaps.append(dict(gap,source='ItemD2R'))
    hard_missing=set()
    optional=list(plan['required_markets'])
    return dict(ready=not hard_missing,required_sources=[s for s in plan['required_markets'] if s not in optional],optional_sources=optional,
        pricing_source_policy='current_available_quote_or_100k_margin_floor',
        missing=[dict(platform=p,source=s) for p,s in sorted(hard_missing)],optional_missing=[dict(platform=p,source=s) for p,s in sorted(missing-hard_missing)],gaps=gaps,
        retired_automatic_sources=list(RETIRED),reference_sources={p:[s for s in plan['required_markets'] if s!='Lootbar' and (p,s) in found] for p in plan['platforms']})


def history_period(now):
    return financial_history_period(now)


def seal_history_cache(mix,replay,scenarios,rollups,source_signature,now):
    required_history_ratio(dict(historical_discount_mix=mix),now,require_current=True)
    if replay.get('status')!='verified' or replay.get('basis_lower_bound_sufficient') is not True:
        raise ValueError('selective_region_history_not_verified')
    if replay.get('original_mix_sha256')!=mix['sha256']:
        raise ValueError('selective_history_population_mismatch')
    if sum((Decimal(s['weight_usd']) for s in scenarios),Decimal(0))!=Decimal(mix['undiscounted_order_usd']):
        raise ValueError('selective_history_scenario_weight_mismatch')
    body=dict(version=VERSION,history_window_contract=HISTORY_WINDOW_CONTRACT,period=mix['period'],created_at=now.isoformat(),source_signature=source_signature,
        historical_discount_mix=deepcopy(mix),original_history_replay=deepcopy(replay),
        promotion_scenarios=deepcopy(scenarios),daily_rollups=deepcopy(rollups),
        privacy='anonymous aggregate scenarios only; no raw orders, customer identifiers or historical cost payload')
    return dict(body,cache_sha256=fingerprint(body))


def checked_history_cache(cache,source_signature,now):
    if not isinstance(cache,dict) or cache.get('version')!=VERSION:
        raise ValueError('selective_history_cache_missing')
    if cache.get('cache_sha256')!=fingerprint({k:v for k,v in cache.items() if k!='cache_sha256'}):
        raise ValueError('selective_history_cache_hash_changed')
    if cache.get('source_signature')!=source_signature or cache.get('period')!=history_period(now):
        raise ValueError('selective_history_cache_source_or_window_changed')
    required_history_ratio(dict(historical_discount_mix=cache['historical_discount_mix']),now,require_current=True)
    return cache


def _current_path(scenario,templates):
    if Decimal(scenario['points_credit_usd']):
        return dict(kind='points',credit_usd=scenario['points_credit_usd'],cap_ratio='.10')
    paths=[]
    if Decimal(scenario['code_retained_ratio'])!=1:
        paths.append(dict(kind='ratio',retained_ratio=scenario['code_retained_ratio'],threshold_usd='0',cap_usd=None))
    from .business_source import _coupon_path
    for identity in scenario['coupon_template_ids']:
        template=templates.get(identity)
        if template is None:raise ValueError('selective_current_coupon_template_missing')
        if type(template.get('_current_active')) is not bool:raise ValueError('selective_current_coupon_activity_unverified')
        if template.get('_current_active') is False:continue
        if paths and str(template.get('is_open'))=='0':raise ValueError('selective_current_coupon_exclusivity_conflict')
        paths.append(_coupon_path(template))
    return paths[0] if len(paths)==1 else dict(kind='sequence',paths=paths) if paths else dict(kind='none')


def project_cached_history(cache,templates,now):
    def paths_for(scenarios):
        grouped={}
        for scenario in scenarios:
            path=_current_path(scenario,templates)
            identity=dict(denominator_basis='regional_regular',promotion_path_excludes_region=True,promotion_path=path)
            key=fingerprint(identity)
            item=grouped.setdefault(key,dict(identity,weight_usd='0',orders=0))
            item['weight_usd']=str(Decimal(item['weight_usd'])+Decimal(scenario['weight_usd']))
            item['orders']+=scenario['orders']
        return [grouped[key] for key in sorted(grouped)]
    projected=deepcopy(cache['original_history_replay'])
    template_fields=('mode_type','reduce','attain','max_reduce','is_open','_current_active')
    used={identity for scenario in cache['promotion_scenarios'] for identity in scenario['coupon_template_ids']}
    terms={identity:{key:templates.get(identity,{}).get(key) for key in template_fields} for identity in sorted(used)}
    terms_hash=fingerprint(terms)
    projected['paths']=paths_for(cache['promotion_scenarios'])
    projected['paths_sha256']=fingerprint(projected['paths'])
    projected['projection_checked_at']=now.isoformat()
    projected['current_coupon_terms_sha256']=terms_hash
    projected['source_sha256']=fingerprint([cache['cache_sha256'],terms_hash,'current_terms_projection'])
    for region,layer in projected.get('region_layers',{}).items():
        layer['paths']=paths_for([s for s in cache['promotion_scenarios'] if str(s['region_id'])==str(region)])
        layer['paths_sha256']=fingerprint(layer['paths'])
        layer['source_sha256']=fingerprint([projected['source_sha256'],region])
        layer['projection_checked_at']=now.isoformat()
    return projected


def context_from_cache(cache,plan,templates,now,*,monthly=None,online=None):
    replay=project_cached_history(cache,templates,now)
    result=dict(historical_discount_mix=deepcopy(cache['historical_discount_mix']),history_replay=replay,
        demand_model=deepcopy(cache['daily_rollups'].get('demand_model') or {}),
        historical_ref=dict(kind='d9_d2_eight_closed_day_promotion_cache',history_window_contract=HISTORY_WINDOW_CONTRACT,cache_sha256=cache['cache_sha256'],period=cache['period'],
            original_mix_sha256=cache['historical_discount_mix']['sha256'],source_signature=cache['source_signature'],created_at=cache['created_at']),
        source_plan=deepcopy(plan))
    # These contexts are estimates/observations, never substitutes for current hard evidence.
    result['demand_model'].setdefault('history_observed_at',cache['created_at'])
    result['demand_model'].pop('advertising_context',None)
    if plan['refresh_monthly_target']:result['monthly_target']=monthly or dict(status='gap',mtd=None,amount=None,reason='monthly_target_context_missing')
    if online:result.update(deepcopy(online))
    else:result['learning_coverage']=dict(status='separate_incremental_pipeline_required',automation_disabled=False)
    return result


def validate_current_hard_evidence(evidence,now,*,cost_seconds=3600,market_seconds=900):
    """No cache-hit freshness exemption. Consumer still performs full financial/scope proof."""
    fresh(evidence['fx']['checked_at'],now,cost_seconds)
    if evidence['promotion_envelope'].get('contract')==CATALOG_CONTRACT:
        input_ratio(evidence['promotion_envelope'],now)
    fresh(evidence['promotion_envelope']['checked_at'],now,market_seconds)
    for platform in evidence['source_plan']['platforms']:
        fresh(evidence['costs'][platform]['checked_at'],now,cost_seconds)
        fresh(evidence['storefront']['rows'][platform]['checked_at'],now,cost_seconds)
    return True


def daily_shadow_request(local_date,snapshots,*,interval_minutes=60):
    """Pure request over references already captured that day. Never collects missing sources."""
    selected=[]
    for snapshot in snapshots:
        if snapshot.get('origin')!='live_collector' or snapshot.get('mode')!='production':continue
        as_of=snapshot.get('decision_at') or snapshot.get('created_at') or snapshot['evidence']['checked_at']
        stamp=datetime.fromisoformat(as_of.replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('selective_daily_snapshot_timezone_missing')
        if stamp.astimezone(TZ).date().isoformat()!=local_date:continue
        selected.append(dict(snapshot_id=snapshot['snapshot_id'],checked_at=snapshot['evidence']['checked_at'],
            as_of=as_of,source_status=snapshot.get('status','recorded'),
            evidence_sha256=fingerprint(snapshot['evidence']),historical_ref=snapshot['evidence'].get('historical_ref')))
    selected.sort(key=lambda row:(row['checked_at'],row['snapshot_id']))
    if type(interval_minutes) is not int or interval_minutes<=0:raise ValueError('selective_interval_invalid')
    def slot_for(ref):
        local=datetime.fromisoformat(ref['as_of'].replace('Z','+00:00')).astimezone(TZ)
        return (local.hour*60+local.minute)//interval_minutes
    slots={slot_for(ref) for ref in selected if ref['source_status']!='failed'}
    expected_slots=(1440+interval_minutes-1)//interval_minutes
    day=datetime.fromisoformat(local_date).replace(tzinfo=TZ)
    coverage=dict(configured_interval_minutes=interval_minutes,expected_input_slots=expected_slots,observed_slots=len(slots),stored_snapshots=len(selected),
        full_day_input_slots_covered=len(slots)==expected_slots,
        failed_snapshot_count=sum(ref['source_status']=='failed' for ref in selected),
        missing_slot_starts=[(day+timedelta(minutes=slot*interval_minutes)).isoformat() for slot in range(expected_slots) if slot not in slots],
        scope='stored_decision_inputs_under_supplied_interval_only; changed_intraday_schedule_needs_its_actual_trace; not_continuous_exposure_or_realized_outcome_coverage')
    return dict(kind='daily_two_strategy_stored_snapshot_replay',local_date=local_date,timezone='Asia/Shanghai',
        strategies=list(MODES),snapshot_refs=selected,origin='simulation',mode='shadow',training_eligible=False,
        coverage=coverage,expected_dispatch_at=(day+timedelta(days=1,hours=2,minutes=20)).isoformat(),dedupe_key='daily-shadow:'+local_date,
        external_collection_allowed=False,production_write_allowed=False,missing_inputs='gap_or_explicit_initial_assumption; never_zero',
        request_sha256=fingerprint([local_date,selected,list(MODES)]))


def replay_daily_stored(request,snapshots,pure_evaluator):
    """Evaluator is the owner's pure kernel, never runtime.context/collector/writer."""
    index={s['snapshot_id']:s for s in snapshots}
    records=[]
    for ref in request['snapshot_refs']:
        snapshot=index.get(ref['snapshot_id'])
        if snapshot is None or fingerprint(snapshot['evidence'])!=ref['evidence_sha256']:
            records.append(dict(snapshot_id=ref['snapshot_id'],status='gap',reason='stored_snapshot_missing_or_changed'))
            continue
        if ref['source_status']=='failed':
            records.append(dict(snapshot_id=ref['snapshot_id'],status='gap',reason='original_snapshot_failed'))
            continue
        for mode in request['strategies']:
            try:
                value=pure_evaluator(deepcopy(snapshot),mode,as_of=ref['as_of'])
                if value.get('execution_authorized') is True or value.get('execution_bundle_id'):
                    raise ValueError('selective_shadow_executable_result_forbidden')
                records.append(dict(snapshot_id=ref['snapshot_id'],strategy=mode,status='evaluated',result=value))
            except (KeyError,ValueError) as error:
                records.append(dict(snapshot_id=ref['snapshot_id'],strategy=mode,status='gap',reason=type(error).__name__))
    return dict(request_sha256=request['request_sha256'],records=records,origin='simulation',mode='shadow',
        execution_authorized=False,training_eligible=False,external_collection_performed=False)


def lightweight_snapshot(evidence):
    """Keep decision inputs and the private-history ref; never copy historical order payloads."""
    dropped={'historical_orders','historical_orders_coverage','private_updates','private_history_cache','admin_products'}
    result={key:deepcopy(value) for key,value in evidence.items() if key not in dropped}
    if result.get('historical_ref') is None:raise ValueError('selective_snapshot_history_reference_missing')
    return result


def economic_source_signature(evidence):
    """Source semantics only. The owner's policy thresholds decide whether review is needed."""
    source={}
    source['costs']={p:{key:row.get(key) for key in ('platform','game','product','cny_per_1k')} for p,row in (evidence.get('costs') or {}).items()}
    source['fx']={key:(evidence.get('fx') or {}).get(key) for key in ('cny_per_usd','currency_pair')}
    source['public']={p:{key:row.get(key) for key in ('sku_id','package_usd','base_k','bonus_k','usd_per_k')} for p,row in (evidence.get('storefront',{}).get('rows') or {}).items()}
    source['market']={p:{name:{key:row.get(key) for key in ('usd_price','base_k','bonus_k','conditional','comparable')} for name,row in offers.items()} for p,offers in (evidence.get('offers') or {}).items()}
    source['ItemD2R']=[{key:row.get(key) for key in ('platform','gross_usd','purchase_k','bonus_k','conditional','comparable')} for row in (evidence.get('reference_market') or {}).get('offers',[])]
    source['ArabUT']=[{key:row.get(key) for key in ('platform','total_usd','purchase_k','bonus_k','delivery','currency','price_basis')} for row in evidence.get('arab_ut_quotes',[])]
    envelope=evidence.get('promotion_envelope') or {}
    source['promotions']={key:envelope.get(key) for key in ('contract','minimum_retained_ratio','packages','coupons','vip_contract')}
    mix=evidence.get('historical_discount_mix') or {}
    source['history']={key:mix.get(key) for key in ('period','eligible_orders','net_order_usd','actual_discount_usd','retained_ratio')}
    source['region_rules']=[{key:row.get(key) for key in ('region_id','platforms','factor','price_semantics')} for row in evidence.get('region_rules',[])]
    return fingerprint(source)
