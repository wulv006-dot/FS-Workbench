"""Pure source planning/cache projection and stored-snapshot replay. No network or writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .financial import fingerprint, required_history_ratio, fresh

VERSION='fc27-selective-source-v1'
MODES=('daily','acquisition','backlog','flash_sale','revenue_sprint')
RETIRED=('ELD','U4GM','IGGM','U7Buy')
TZ=timezone(timedelta(hours=8))


def source_plan(active_mode, scope=None, *, known_region_ids=(), interval_minutes=120):
    if active_mode not in MODES:raise ValueError('selective_active_mode_invalid')
    scope=scope or {}
    interval_minutes=scope.get('interval_minutes',interval_minutes)
    if type(interval_minutes) is not int or interval_minutes<=0:raise ValueError('selective_interval_invalid')
    platforms=scope.get('platforms',['PS','XBOX','PC'])
    if not platforms or set(platforms)-{'PS','XBOX','PC'}:raise ValueError('selective_platform_scope_invalid')
    regions=sorted(set(int(value) for value in known_region_ids)|set(int(value) for value in scope.get('region_ids',[])))
    markets=['Lootbar']
    if active_mode=='revenue_sprint' or scope.get('compare_itemd2r') is True:markets.append('ItemD2R')
    if 21 in regions and set(platforms)&{'PS','XBOX'} and (active_mode=='revenue_sprint' or scope.get('compare_saudi') is True):markets.append('ArabUT')
    return dict(version=VERSION,active_mode=active_mode,platforms=list(platforms),region_ids=regions,
        required_markets=markets,market_platforms={name:([p for p in platforms if p in ('PS','XBOX')] if name=='ArabUT' else list(platforms)) for name in markets},
        retired_automatic_sources=list(RETIRED),price_interval_minutes=interval_minutes,
        quote_validity_seconds=900,hard_evidence=['current_cost','current_FX','current_promotion_envelope','current_public_price','affected_region_contract'],
        history='same_seven_closed_days_and_original_hash_cache',
        refresh_backlog=active_mode=='backlog',refresh_monthly_target=active_mode=='revenue_sprint',
        read_ads_context=active_mode=='acquisition',online_observation_job='preserved_separate_incremental_pipeline',
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
        purchase=row.get('purchase_k',row.get('base_k'))
        if (row.get('currency')!='USD' or Decimal(str(purchase))!=100 or row.get('conditional') is True or row.get('comparable') is False):
            gaps.append(dict(platform=key[0],source=key[1],reason='public_no_coupon_100K_scope_invalid'));continue
        if key[1]=='ArabUT' and (row.get('delivery')!='normal' or row.get('selection_verified') is not True):
            gaps.append(dict(platform=key[0],source=key[1],reason='normal_delivery_not_verified'));continue
        if Decimal(str(row.get('gross_usd',row.get('total_usd','0'))))<=0:
            gaps.append(dict(platform=key[0],source=key[1],reason='public_amount_invalid'));continue
        found[key]=row
        times.append(datetime.fromisoformat(captured.replace('Z','+00:00')))
    if times and (max(times)-min(times)).total_seconds()>300:raise ValueError('selective_competitor_capture_span')
    missing=expected-set(found)
    return dict(ready=not missing,required_sources=plan['required_markets'],
        missing=[dict(platform=p,source=s) for p,s in sorted(missing)],gaps=gaps,
        retired_automatic_sources=list(RETIRED),reference_sources={p:[s for s in plan['required_markets'] if s!='Lootbar' and p in required[s]] for p in plan['platforms']})


def history_period(now):
    today=now.astimezone(TZ).date()
    return dict(start=(today-timedelta(days=7)).isoformat(),end=(today-timedelta(days=1)).isoformat())


def seal_history_cache(mix,replay,scenarios,rollups,source_signature,now):
    required_history_ratio(dict(historical_discount_mix=mix),now)
    if replay.get('status')!='verified' or replay.get('basis_lower_bound_sufficient') is not True:
        raise ValueError('selective_region_history_not_verified')
    if replay.get('original_mix_sha256')!=mix['sha256']:
        raise ValueError('selective_history_population_mismatch')
    if sum((Decimal(s['weight_usd']) for s in scenarios),Decimal(0))!=Decimal(mix['undiscounted_order_usd']):
        raise ValueError('selective_history_scenario_weight_mismatch')
    body=dict(version=VERSION,period=mix['period'],created_at=now.isoformat(),source_signature=source_signature,
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
    required_history_ratio(dict(historical_discount_mix=cache['historical_discount_mix']),now)
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


def context_from_cache(cache,plan,templates,now,*,backlog=None,fulfillment=None,monthly=None,ads=None,online=None):
    replay=project_cached_history(cache,templates,now)
    result=dict(historical_discount_mix=deepcopy(cache['historical_discount_mix']),history_replay=replay,
        demand_model=deepcopy(cache['daily_rollups'].get('demand_model') or {}),
        historical_ref=dict(kind='seven_closed_day_promotion_cache',cache_sha256=cache['cache_sha256'],period=cache['period'],
            original_mix_sha256=cache['historical_discount_mix']['sha256'],source_signature=cache['source_signature'],created_at=cache['created_at']),
        source_plan=deepcopy(plan))
    # These contexts are estimates/observations, never substitutes for current hard evidence.
    result['demand_model']['history_observed_at']=cache['created_at']
    if plan['read_ads_context']:result['demand_model']['advertising_context']=ads or dict(status='gap',reason='same_scope_ads_context_missing')
    else:result['demand_model'].pop('advertising_context',None)
    if plan['refresh_backlog']:
        capacity=fulfillment if fulfillment is not None else cache['daily_rollups'].get('observed_fulfillment') or {}
        result['fulfillment_estimates']=dict(estimated=True,rate_window_hours=6,
            backlog_k=(backlog or {}).get('gross_ordered_delivery_k'),current_backlog_source=backlog or dict(status='gap'),
            capacity_k_per_block=capacity.get('observed_delivered_k_per_block'),observed_capacity_source=capacity,
            capacity_basis='initial_estimate_from_stored_observed_throughput_not_promised_supply')
    if plan['refresh_monthly_target']:result['monthly_target']=monthly or dict(status='gap',mtd=None,amount=None,reason='monthly_target_context_missing')
    if online:result.update(deepcopy(online))
    else:result['learning_coverage']=dict(status='separate_incremental_pipeline_required',automation_disabled=False)
    return result


def validate_current_hard_evidence(evidence,now,*,cost_seconds=3600,market_seconds=900):
    """No cache-hit freshness exemption. Consumer still performs full financial/scope proof."""
    fresh(evidence['fx']['checked_at'],now,cost_seconds)
    fresh(evidence['promotion_envelope']['checked_at'],now,market_seconds)
    for platform in evidence['source_plan']['platforms']:
        fresh(evidence['costs'][platform]['checked_at'],now,cost_seconds)
        fresh(evidence['storefront']['rows'][platform]['checked_at'],now,cost_seconds)
    return True


def daily_shadow_request(local_date,snapshots,*,interval_minutes=120):
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
    return dict(kind='daily_five_strategy_stored_snapshot_replay',local_date=local_date,timezone='Asia/Shanghai',
        strategies=list(MODES),snapshot_refs=selected,origin='simulation',mode='shadow',training_eligible=False,
        coverage=coverage,expected_dispatch_at=(day+timedelta(days=1,minutes=20)).isoformat(),dedupe_key='daily-shadow:'+local_date,
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
