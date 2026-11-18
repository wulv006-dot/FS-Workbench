"""One FC coordinator, using the existing collection and mechanical writer adapters."""
from .platforms import PRICE_SCOPE_CONTRACT, action_key, native_action
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import itertools
from math import prod
import json
import os
from pathlib import Path
import uuid

from . import VERSION, PROGRAM_CONTRACT
from .dispatch import CURVE_REJECTED, CURVE_WRITE_PROTOCOL, proven_not_sent, write_protocol
from .engine import evaluate, financial, competition, commit_path, impacted_regions, proof_regions, GROUPS, PLATFORMS, market_quote, sprint_parameters, SPRINT_POLICY_VERSION
from .financial import fingerprint, number, instant, MARGIN_BASIS, HARD_MARGIN, FINANCIAL_CONTRACT_VERSION, LEGACY_FINANCIAL_CONTRACT_VERSION, HISTORY_WINDOW_CONTRACT, required_history_ratio
from .ledger import Ledger, clock, confirmed_curve_window
from .engine import controlled_candidate, current_action

ROOT = Path(os.environ.get('FC27_V3_ROOT','/var/lib/fc27-cloud'))
STORE = ROOT/'v3'
CURVE_DECISION_POLICY = 'v6_paired_bands'
CURVE_PROTECTION_POLICY = 'v6_temporary_cost_protection'


def ledger():
    return Ledger(STORE/'control.sqlite3')


@contextmanager
def operation_execution(operation_id):
    """One original operation across drive/reconcile; unrelated operations stay free."""
    import errno
    path=ledger().path.parent/'operation-locks'/(fingerprint(operation_id)+'.lock')
    if any(item.is_symlink() for item in (path,*path.parents)):raise ValueError('pricing_operation_lock_symlink')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with path.open('a+b') as lock:
        if os.name=='nt':
            import msvcrt
            if lock.tell()==0:lock.write(b'\0');lock.flush()
            lock.seek(0)
        else:import fcntl
        try:
            if os.name=='nt':msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EACCES,errno.EAGAIN):raise
            raise ValueError('pricing_operation_busy') from None
        try:yield
        finally:
            if os.name=='nt':lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(lock,fcntl.LOCK_UN)


def current_history_cache(now):
    """Use the same reconciled cohort at collection and the last write boundary."""
    from contextlib import closing
    import sqlite3
    import sys
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from .business_source import selective_history_signature
    from .selective_sources import checked_history_cache,history_period
    with closing(sqlite3.connect('file:'+str(STORE/'control.sqlite3')+'?mode=ro',uri=True)) as db:
        row=db.execute("SELECT body FROM metadata WHERE id='seven_day_history_cache'").fetchone()
    cache=json.loads(row[0]) if row else None
    return checked_history_cache(cache,selective_history_signature(history_period(now)),now)


def current_history_mix(now):
    return current_history_cache(now)['historical_discount_mix']


def write_json(path, value):
    from snapshot_layer import atomic_json
    atomic_json(path,value)
    if os.name=='posix':
        os.chown(path,-1,11028)
        os.chmod(path,0o640)


def public_snapshot_summary(snapshot):
    evidence=snapshot['evidence']
    fields={key:evidence.get(key) for key in ('monthly_target','offers','reference_market','arab_ut_quotes','region_contract')}
    for key in ('region_rules','regional_controls'):
        fields[key]=[dict(row,history={k:v for k,v in (row.get('history') or {}).items() if k!='replay_paths'})
                     for row in evidence.get(key,[])]
    return dict(snapshot_id=snapshot['snapshot_id'],created_at=snapshot['created_at'],
                plan_id=(snapshot.get('result',{}).get('decision_receipt') or {}).get('plan_id'),
                source_checked_at=evidence.get('checked_at'),evidence=fields,
                result={'rows':snapshot['result']['rows']})


def collection_scope(db,run_id):
    from .competitor_offers import POLICY as CURVE_COMPETITOR_POLICY

    job_path=ROOT/'jobs'/(run_id+'.json')
    job=json.loads(job_path.read_text()) if job_path.exists() else {}
    request = job.get('request') or {}
    plan_id=request.get('v3_plan_id')
    plan=db.get('pricing_plans',plan_id) if plan_id else db.active_plan()
    resources=(plan or {}).get('resources',[])
    regions=sorted({int(r.split(':')[1]) for r in resources if r.startswith('region:')})
    from automation_policy import load_policy
    parameters=dict((plan or {}).get('parameters',{}))
    if _curve_run_requested(job, plan):
        parameters.update(competitor_policy=CURVE_COMPETITOR_POLICY, region_pricing='global')
    elif (plan or {}).get('write_protocol') == CURVE_WRITE_PROTOCOL:
        # Original scalar recovery/maintenance uses its original market contract.
        from .engine import COMPETITOR_POLICY
        parameters.update(competitor_policy=COMPETITOR_POLICY)
    return dict(active_mode=(plan or {}).get('mode','revenue_sprint'),scope=dict(
        platforms=list(PLATFORMS),region_ids=regions,interval_minutes=load_policy()['interval_minutes'],
        **{k:parameters[k] for k in ('competitor_policy','region_pricing') if k in parameters}))


def _curve_run_requested(job, plan):
    request = job.get('request') or {}
    return (not request.get('v3_authorization_purpose')
            and (job.get('kind') == 'collect' and request.get('write_protocol') == CURVE_WRITE_PROTOCOL
                 or (plan or {}).get('write_protocol') == CURVE_WRITE_PROTOCOL))


def latest_collection(root, *, curve):
    from .competitor_offers import POLICY as CURVE_COMPETITOR_POLICY

    # A diagnostic V6 run cannot supersede an active scalar writer's run.
    for path in sorted((root/'runs').glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True):
        if path.name.startswith('.tmp-'):
            continue
        value = json.loads(path.read_text(encoding='utf-8'))
        policy = value.get('competitor_policy') or (value.get('source_plan') or {}).get('competitor_policy')
        if (policy == CURVE_COMPETITOR_POLICY) == curve:
            return path
    return None


def context(evidence):
    """Source results are attached once to the immutable quote snapshot."""
    from .sources import collect_context
    db=ledger()
    scope=collection_scope(db,evidence['run_id'])
    from .selective_sources import CATALOG_CONTRACT
    if (evidence.get('promotion_envelope') or {}).get('contract')==CATALOG_CONTRACT:
        scope['scope']=dict(scope['scope'],catalog_only=True)
    envelope=collect_context(dict(evidence,price_windows=db.all('actual_price_windows'),
        active_mode=scope['active_mode'],active_scope=scope['scope'],
        history_cache=db.get('metadata','seven_day_history_cache'),online_context=db.get('metadata','daily_online_context')))
    for key,value in envelope['private_updates'].items():
        if key!='history_cache':raise ValueError('pricing_private_source_update_invalid')
        db.put('metadata','seven_day_history_cache',value)
    result=dict(evidence,**envelope['context'])
    result.pop('shared_order_facts',None)  # Private bridge input is never a quote/model payload.
    enrich_segments(result)
    target=db.get('monthly_targets','current')
    if target and 'monthly_target' in result:
        if target['target_scope']!=result['monthly_target']['target_scope'] or target['target_basis']!=result['monthly_target']['target_basis']:
            raise ValueError('pricing_monthly_target_scope_mismatch')
        result['monthly_target']=dict(result['monthly_target'],amount=target['amount'],target_source='user_configured_exact_scope',target_version=target.get('version'))
    reference=db.get('budget_references','rolling_global_price_vector')
    if reference is None:
        reference=dict(base_prices={g:str(max(number(result['storefront']['rows'][p]['package_usd']) for p in ps)) for g,ps in GROUPS.items()},
                       region_coefficients={str(r['region_id'])+':'+p:r['factor'] for r in result.get('region_rules',[]) for p in r['platforms']},created_at=clock().isoformat())
        db.put('budget_references','rolling_global_price_vector',reference)
    result['budget_reference']=reference
    for settlement in result.get('budget_settlements',[]):
        db.settle_order(settlement)
    from .demand_model import fit
    observations=result.get('training_observations',[])
    if observations:
        model=fit(observations)
        db.put('model_versions',model['model_version'],model)
        if model['groups']:
            for group,values in model['groups'].items():
                if group in result['demand_model']['groups']:
                    result['demand_model']['groups'][group]=dict(result['demand_model']['groups'][group],**values)
            result['demand_model']['model_version']=model['model_version']
            result['demand_model']['status']=model['status']
    return result


def enrich_segments(evidence):
    """Disjoint observed regional orders use their actual current public anchor and cost."""
    from .financial import common_cost
    model=evidence.get('demand_model') or {}
    estimates=evidence.get('fulfillment_estimates') or {}
    if estimates.get('estimated') and estimates.get('capacity_k_per_block') is not None and estimates.get('backlog_k') is not None:
        evidence.update(capacity_k_per_block=estimates['capacity_k_per_block'],backlog_k=estimates['backlog_k'],
                        capacity_is_estimate=True,backlog_is_upper_bound=True,due_committed_backlog_k=None)
    segments=[]
    pooled,_=common_cost(evidence)
    for observed in model.get('observed_segments',[]):
        region=next((r for r in evidence.get('region_rules',[]) if r['region_id']==observed['region_id'] and observed['platform'] in r['platforms']),None)
        public=((region or {}).get('public_rule_trace') or {}).get('offers',{}).get(observed['platform'])
        if not region or not region.get('verified') or not public or observed.get('orders_per_block') is None or observed.get('delivered_k_per_order') is None:continue
        cost=number(evidence['costs']['PC']['cny_per_1k']) if observed['platform']=='PC' else pooled
        segments.append(dict(observed,reference_regular_usd=public['regular_usd'],
            delivered_cost_per_order_usd=str(number(observed['delivered_k_per_order'])*cost/number(evidence['fx']['cny_per_usd'])),
            reference_basis='same_snapshot_verified_regional_public_100K; observed_disjoint_order_AOV_and_actual_delivered_K'))
    model['segments']=segments
    model['segment_attachment_coverage']=dict(observed=len(model.get('observed_segments',[])),attached=len(segments))
    return evidence


def smart_choices(evidence,plan,current,baseline,schedule,now):
    """Independent group draws share one physical price/probability proof."""
    from .smart import STRATEGY_VERSION,candidate_or_baseline,effective_key
    bidirectional=plan.get('smart_strategy_version')==STRATEGY_VERSION
    labels={''.join(values):dict(zip(GROUPS,values)) for values in itertools.product('ABC',repeat=len(GROUPS))} if bidirectional else {v:v for v in 'ABC'}
    variants={key:candidate_or_baseline(evidence,plan,current,baseline,label,now) for key,label in labels.items()}
    weights={key:float(prod(Decimal(schedule['group_probabilities'][g][label]) for g,label in zip(GROUPS,key)))
             if bidirectional else float(schedule['marginal_probabilities'][key]) for key in variants}
    effective_probabilities={}
    for key,candidate in variants.items():
        if not weights[key]:continue
        effective=effective_key(evidence,candidate['action'])
        effective_probabilities[effective]=effective_probabilities.get(effective,0)+weights[key]
    probabilities={fingerprint(c['action']):effective_probabilities[effective_key(evidence,c['action'])] for key,c in variants.items() if weights[key]}
    choice=''.join(schedule['group_labels'][g] for g in GROUPS) if bidirectional else schedule['label']
    return variants,effective_probabilities,probabilities,choice


def preview_curve(snapshot, platform, *, requested_snapshot_id=None, strategy_state=None,
                  segment='large', closed_attachment=None, latest_selected=True, evidence_as_of=None,
                  frozen_inputs=None):
    """Read one platform's current saved catalogue without opening a pricing operation."""
    from coin_all_sync_job import PRODUCTS, read_row
    from fc_shared_admin import SessionManager, read_private_config
    from .admin_readback import GID_FC27, MID_FC27_COINS, SITE_MAIN
    from .price_curve import curve_key, quote_native, read_curve
    from .pricing_proof_v6 import CONTRACT, INCOMPLETE
    from .competitor_offers import CURRENT_QUANTITIES, POLICY as CURVE_COMPETITOR_POLICY, quantity_coverage

    gaps = ['customer_checkout_unverified', 'offer_path_unverified', 'necessary_fee_unverified',
            'validation_domain_unverified', 'ordinary_delivery_cost_unverified', 'planning_baskets_unverified']
    decision = dict(financial_contract=CONTRACT, selected=None, gaps=gaps, candidates=[], selected_segment=segment)
    if strategy_state:
        reference = strategy_state['reference']
        episode = strategy_state['episode']
        decision.update(reference_curve_id=reference['reference_curve_id'],
                        comparison_episode_id=episode['comparison_episode_id'],
                        initial_reference_curve_id=episode['initial_reference_curve_id'],
                        reference_tiers=reference['reference_curve']['tiers'])
    else:
        gaps.extend(('adopted_reference_curve_unavailable', 'comparison_episode_unavailable'))
    result = dict(status=INCOMPLETE, write_protocol=CURVE_WRITE_PROTOCOL, platform=platform,
                  snapshot_id=requested_snapshot_id, snapshot_captured_at=None, current_catalogue=None,
                  decision=decision,
                  execution_authorized=False, write_performed=False)
    if not snapshot:
        gaps.append('pricing_snapshot_unavailable')
        return result
    evidence = snapshot.get('evidence') or {}
    if (snapshot.get('origin') != 'live_collector' or snapshot.get('mode') != 'production'
            or snapshot.get('authorization_purpose') or snapshot.get('snapshot_id') != evidence.get('run_id')
            or requested_snapshot_id is not None and snapshot['snapshot_id'] != requested_snapshot_id):
        gaps.append('pricing_snapshot_scope_unverified')
        return result
    result.update(snapshot_id=snapshot['snapshot_id'], snapshot_captured_at=snapshot['created_at'])
    if evidence.get('competitor_policy') == CURVE_COMPETITOR_POLICY:
        offers = [row for row in evidence.get('competitor_offers', [])
                  if row['platform'] == platform and row['purchase_k'] in CURRENT_QUANTITIES]
        decision['competitor_quantity_coverage'] = quantity_coverage(offers, platforms=(platform,),
                                                                     requested=CURRENT_QUANTITIES)
        decision['competitor_offers'] = [{k: row.get(k) for k in (
            'source', 'purchase_k', 'bonus_k', 'currency', 'regular_price', 'eligible_net_price',
            'comparable', 'delivery_method', 'delivery_tier', 'promotion_eligibility', 'captured_at',
        )} for row in offers]
    _, goods_id, aid = PRODUCTS[platform]
    own = (evidence.get('storefront') or {}).get('rows', {}).get(platform) or {}
    if own.get('sku_id') is not None and str(own['sku_id']) != str(goods_id):
        gaps.append('pricing_snapshot_goods_scope_unverified')
        return result
    source = 'Admin Goods edit read only'
    observations = []
    try:
        manager = SessionManager(read_private_config())
        row = read_row(manager, platform, int(SITE_MAIN), observer=observations.append)
        captured_at = clock().isoformat()
        identity = dict(id=goods_id, mid=MID_FC27_COINS, gid=GID_FC27, cid=9623,
                        site_id=SITE_MAIN, aid=aid, unit='K', status=1)
        curve = read_curve(row, identity, dict(source=source, verified_domain='native stored tiers only'))
        quote = quote_native(curve, dict(purchase_k='100', multiplier=1, site_id=SITE_MAIN, currency='USD'))
        key = quote.get('curve_key') or curve_key(curve)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        gaps.append('current_catalogue_identity_mismatch' if str(error) == 'coin_product_scope_changed'
                    else 'current_catalogue_readback_unavailable')
        return result
    result['current_catalogue'] = dict(status='saved_tier', source=source, captured_at=captured_at,
        response_sha256=observations[0]['response_sha256'], identity=curve['identity'], tiers=curve['tiers'],
        curve_key=key, quote_100k=quote)
    if not latest_selected:
        gaps.append('historical_snapshot_frozen_curve_unavailable')
        return result

    evidence_as_of = evidence_as_of or instant(captured_at)
    if instant(snapshot['created_at']) > evidence_as_of:
        gaps.append('pricing_snapshot_clock_invalid')
        return result
    if (frozen_inputs and (not instant(frozen_inputs['captured_at']) <= evidence_as_of < instant(frozen_inputs['valid_until'])
            or curve_key(frozen_inputs['primary_curve']) != key)):
        frozen_inputs = None
    decision.update(_preview_curve_candidates(curve, key, platform, strategy_state, segment, closed_attachment,
                                              snapshot['created_at'], captured_at, evidence_as_of,
                                              (frozen_inputs or {}).get('primary_inputs') or {},
                                              editor=(frozen_inputs or {}).get('editor_contract'),
                                              repair=(frozen_inputs or {}).get('repair')))
    return result


def _preview_curve_candidates(curve, key, platform, strategy_state, segment, closed_attachment,
                              snapshot_at, catalogue_at, evidence_as_of, frozen_candidates, *, editor=None, repair=None):
    from .admin_readback import SITE_MAIN
    from .curve_strategy_v6 import ANCHORS, build_candidates
    from .price_curve import EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, curve_key, quote_native

    candidate_gaps = {}
    boundary_search_status = None
    if strategy_state:
        comparison = build_candidates(curve, strategy_state['reference'], strategy_state['episode'], segment,
            editor_contract=editor or dict(curve['native_contract'], editor_asset_sha256=EDITOR_ASSET_SHA256,
                                 editor_handler_sha256=EDITOR_HANDLER_SHA256),
            check_saved_discount_terms=True)
        candidates, candidate_gaps = comparison['candidates'], comparison['gaps']
        boundary_search_status = comparison['boundary_search_status']
    else:
        candidates = [dict(curve=curve, curve_key=key, labels=['CURRENT'], write_gaps=[])]
    if repair:
        for row in repair['candidates']:
            repaired_key = curve_key(row['curve'])
            candidates.append(dict(curve=row['curve'], curve_key=repaired_key, labels=['COST_REPAIR'], write_gaps=[]))
            frozen_candidates = {**frozen_candidates, repaired_key:row['inputs']}

    output = []
    for candidate in candidates:
        proposed = candidate['curve']
        candidate_key = candidate['curve_key']
        quote = quote_native(proposed, dict(purchase_k=ANCHORS[segment], multiplier=1,
                                             site_id=SITE_MAIN, currency='USD'))
        frozen = frozen_candidates.get(candidate_key)
        if frozen is None:
            frozen = _catalogue_proof_input(proposed, platform, closed_attachment, snapshot_at, evidence_as_of)
        baskets = frozen['baskets']
        proof = _validated_curve(proposed, frozen)
        output.append(dict(curve_key=candidate_key, labels=candidate['labels'],
                           catalogue_basis='offline_admin_editor_model'
                           if quote['catalogue_status'] == 'editor_candidate_tier' else 'saved_catalogue',
                           tiers=proposed['tiers'], quote=quote, write_gaps=candidate['write_gaps'],
                           planning_baskets=baskets, financial_proof=proof))
    return dict(candidates=output, candidate_gaps=candidate_gaps, boundary_search_status=boundary_search_status,
                historical_evidence_as_of=evidence_as_of.isoformat(),
                catalogue_captured_at=catalogue_at)


def _curve_proof_inputs(db, evidence, conn=None):
    """Use only the coordinator's private, same-run frozen evidence."""
    attachment = db.get('metadata', 'curve-proof-inputs:' + evidence['run_id'], conn)
    return _bound_curve_proof_inputs(attachment, evidence)


def _bound_curve_proof_inputs(attachment, evidence):
    if (not attachment or attachment.get('run_id') != evidence.get('run_id')
            or attachment.get('collection_sha256') != _curve_collection_fingerprint(evidence)):
        return {}
    return attachment.get('platforms') or {}


def _curve_collection_fingerprint(evidence):
    return fingerprint({key: value for key, value in evidence.items() if key != 'curve_proof_inputs'})


def ordinary_delivery_archives(scope, shared, *, root=None):
    """Use original closed delivery-day files, superseded by the current cache where it actually covers."""
    from pathlib import Path
    from channel_cache import delivery_bounds
    from order_facts_source import project_order_facts

    root = Path(root or '/var/lib/fs-channel-effects')
    names = {row['order_no'] for row in shared['rows']}
    lo = datetime.fromisoformat(scope['start']).date()
    hi = datetime.fromisoformat(scope['end']).date()
    days = [(lo + timedelta(days=i)).isoformat() for i in range((hi - lo).days + 1)]
    ordered_paths = [root / 'delivery-days' / (day + '.json') for day in days]
    ordered_paths.append(root / 'order-deliveries.json')
    sources = []
    for path in ordered_paths:
        if not path.is_file():
            continue
        if any(item.is_symlink() for item in (path, *path.parents)) or path.stat().st_size > 128*1024*1024:
            raise ValueError('curve_delivery_archive_path')
        payload = path.read_bytes()
        value = json.loads(payload)
        if value.get('contract') != 'channel-order-deliveries-v1' or value.get('complete') is not True:
            raise ValueError('curve_delivery_archive_contract')
        period = value['period']
        if path.parent.name == 'delivery-days' and period != {'start':path.stem, 'end':path.stem}:
            raise ValueError('curve_delivery_archive_day_mismatch')
        lower, upper = delivery_bounds(period)
        generated = instant(value['generatedAt'])
        matched = [row for row in value['rows'] if row.get('source') == 'www.mmoexp.com'
                   and row.get('sn') in names and str(row.get('genre')) == '1'
                   and lower <= str(row.get('trade_at')) <= upper]
        if (any(not str(row.get('delivery_id') or '').isdecimal() for row in matched)
                or len({str(row['delivery_id']) for row in matched}) != len(matched)):
            raise ValueError('curve_delivery_archive_record_conflict')
        sources.append((generated, lower, upper, hashlib.sha256(payload).hexdigest(), matched))
    coverage = dict(shared['coverage'])
    rows = {}
    sources.sort(key=lambda source: source[:4])
    for _, lower, upper, _, matched in sources:
        for row in matched:
            old = rows.get(str(row['delivery_id']))
            if old and old['sn'] != row['sn']:
                raise ValueError('curve_delivery_archive_order_conflict')
        for key, old in list(rows.items()):
            if lower <= old['trade_at'] <= upper:
                del rows[key]
        for row in matched:
            key = str(row['delivery_id'])
            rows[key] = row
    captured = clock()
    coverage['admin_captured_at'] = coverage.get('captured_at')
    coverage['captured_at'] = captured.isoformat()
    windows = [dict(start=lower, end=upper, revision=revision, generated_at=generated.isoformat())
               for generated, lower, upper, revision, _ in sources]
    coverage['cost'] = dict(status='observed_only',
                            source_revision=fingerprint(windows) if windows else None,
                            generated_at=max((row[0] for row in sources), default=None).isoformat() if sources else None,
                            shipment_windows=windows, shipment_window_complete=bool(windows),
                            order_cost_complete=False)
    return project_order_facts(shared['rows'], shared['dataset'], rows.values(), scope=scope,
                               source_coverage=coverage, identity_catalog=shared['identity_catalog'])


def _shared_curve_inputs(paid_cutoff, as_of, *, code_names):
    import sys
    from .average_discount_v6 import average_discount_window
    from .business_source import historical_period, shared_curve_attachment

    sys.path[:0] = ['/opt/fs-exact-range-20261001', '/opt/fs-hermes-fc']
    from shared_es_facts import read

    start, discount_end = average_discount_window(paid_cutoff)
    basket = historical_period('7d', now=instant(paid_cutoff))
    scope = dict(site_id='266', gid='1327', **basket['period'])
    shared = read(scope)
    closed = shared_curve_attachment(shared, scope, as_of=as_of, code_names=code_names)
    publication_id = shared['coverage'].get('publication_id')
    discount_source = None
    if publication_id:
        # The structure basket and discount forecast use different windows of the same publication.
        discount_scope = dict(scope, start=start.date().isoformat(),
                              end=(discount_end.date() - timedelta(days=1)).isoformat())
        try:
            discount_data = read(discount_scope, publication_id=publication_id)
            discount_source = shared_curve_attachment(discount_data, discount_scope, as_of=as_of,
                                                      code_names=code_names)
        except (ImportError, OSError, ValueError, TypeError, KeyError):
            pass
    if closed is None:
        return None, None, discount_source
    try:
        facts = ordinary_delivery_archives(scope, shared)
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        facts = None
    return closed, facts, discount_source


def _average_discount_proof_input(curve, platform, closed, recent, paid_cutoff, now, *,
                                  average, route, facts, fx, current_cost):
    from .average_discount_v6 import MODEL, forecast_quotes, quantity_group
    from .cost_inputs_v6 import SMOOTH_COST_CONTRACT, _fx, estimate_historical_cost
    from .planning_baskets_v6 import build_planning_baskets
    from .price_curve import curve_key

    key = curve_key(curve)
    tiers = {row['purchase_k'] for row in curve['tiers']}
    orders = {row['order_key']: row for source in (closed, recent) if source
              for row in source['historical_orders'] if row.get('platform') == platform}
    quantities, observed_gifts = {}, {}
    for identity, row in orders.items():
        if row.get('base_k') is None or row.get('bonus_k') is None:
            continue
        purchase = number(row['base_k'])
        if purchase == purchase.to_integral_value():
            quantities[identity] = purchase
            bonus = number(row['bonus_k'], zero=True)
            observed_gifts[purchase] = max(bonus, observed_gifts.get(purchase, Decimal(0)))
    quotes = forecast_quotes(curve, quantities.values(), average, observed_gifts=observed_gifts)
    now_text = now.isoformat()
    groups = {name: {} for name in ('small', 'large')}
    repriced = {}
    fulfilment = 'ordinary_native_coins_promised_delivered_k'
    for identity, purchase in quantities.items():
        row = orders[identity]
        path = quotes[format(purchase.normalize(), 'f')]
        ref = fingerprint(dict(order=row['source_sha256'], contract=fulfilment))
        repriced[identity] = _repriced_checkout_order(row, path, dict(fulfilment_ref=ref), now,
                                                       average['revision'])
        # Known quantities stay in the cost coverage denominator. An unallocated
        # mixed or multi-unit order cannot supply a comparable procurement amount.
        layer = dict(platform=platform, quantity_bucket=quantity_group(purchase),
                     offer_version=MODEL, fulfilment_contract=fulfilment)
        groups[layer['quantity_bucket']][identity] = dict(
            layer=layer, available_at=now_text, order_revision=row['source_sha256'], evidence_ref=ref,
            quantity_only=row.get('single_line_unit_purchase') is not True)

    smoothed = (current_cost or {}).get('sample_contract') == SMOOTH_COST_CONTRACT
    rate, fx_source = _fx(fx, now) if smoothed else (None, None)
    estimates = {}
    for group, matches in groups.items():
        if smoothed or not matches or facts is None:
            continue
        layer = next(iter(matches.values()))['layer']
        # Original closed archives stop at midnight. Recent today is basket
        # structure; it is never assigned a cost from a future delivery.
        cost_cutoff = instant(closed['historical_orders_coverage']['paid_window_end_exclusive']) if closed else None
        if cost_cutoff is not None:
            estimates[group] = estimate_historical_cost([closed], layer, 'PROMISED_DELIVERED_K',
                as_of=now, paid_cutoff=cost_cutoff, layer_matches=matches, fact_revisions=[facts], fx=fx,
                ordinary_forecast=True, selected_orders=tuple(matches), current_cost=current_cost)

    paths = []
    valid_records = {str(record['record_id']) for record in
                     ((current_cost or {}).get('sample_records') or [current_cost or {}])
                     if record.get('record_id') and (current_cost or {}).get('status') == 'valid'
                     and (current_cost or {}).get('source_platform', platform) == platform}
    for estimate in estimates.values():
        valid_records.update((estimate.get('sample_insurance') or {}).get('valid_record_ids') or [])
    insufficient_samples = len(valid_records) < 3
    for quantity in sorted(tiers | {format(value.normalize(), 'f') for value in quantities.values()}, key=Decimal):
        path = quotes[quantity]
        estimate = estimates.get(quantity_group(number(quantity)))
        if smoothed and current_cost.get('status') == 'valid' and rate is not None and not insufficient_samples:
            total = number(path['promised_delivered_k']) * number(current_cost['cny_per_1k']) / rate
            path.update(cost_status='verified', quantity_basis='PROMISED_DELIVERED_K',
                        cost_sample_contract=SMOOTH_COST_CONTRACT,
                        cost_ref=fingerprint(dict(cost=current_cost, fx=fx_source)),
                        **{kind + '_cost_usd': str(total) for kind in ('expected', 'safe', 'stress')})
        elif estimate and estimate['status'] == 'calculated' and not insufficient_samples:
            units = estimate['diagnostic_estimate']
            total = number(path['promised_delivered_k'])
            path.update(cost_status='verified', quantity_basis='PROMISED_DELIVERED_K',
                        cost_ref=fingerprint(dict(order_cost_source=estimate['order_cost_source'],
                            attachment_revision=estimate['attachment_revision'], fx=estimate['forecast_fx'],
                            upper_source=estimate['cost_upper_source'], current_source=estimate['current_cost_source'])),
                        **{kind + '_cost_usd': str(total * units[kind + '_unit_usd'])
                           for kind in ('expected', 'safe', 'stress')})
        else:
            path['ordinary_cost_gaps'] = (['curve_cost_sample_outlier'] if insufficient_samples else estimate['gaps'] if estimate else
                                          ['ordinary_delivery_cost_sample_missing'])
        paths.append(path)

    propagation = (route or {}).get('propagation_revision')
    domain_gaps = list(average['gap_counts'])
    if insufficient_samples:
        domain_gaps.append('curve_cost_sample_outlier')
    if current_cost and current_cost.get('reason') == 'curve_cost_sample_outlier':
        domain_gaps.append('curve_cost_sample_outlier')
    if smoothed and rate is None:
        domain_gaps.append('forecast_fx_unavailable_as_of')
    if not propagation:
        domain_gaps.append('curve_native_route_unavailable')
    quantity_revision = fingerprint(dict(model=MODEL, curve_key=key, paths=[p['quote_ref'] for p in paths]))
    return dict(baskets=build_planning_baskets(platform, key, closed, recent, repriced,
                                               paid_cutoff=paid_cutoff, as_of=now),
                evidence=dict(curve_key=key, paths=paths, average_discount=average,
                              smoothed_delivery_cost=current_cost if smoothed else None,
                              cost_sample_insurance={name: row.get('sample_insurance') for name, row in estimates.items()}),
                domain=dict(platform=platform, curve_key=key, version=MODEL,
                            coverage_status='partial' if domain_gaps else 'complete',
                            coverage_gaps=sorted(domain_gaps),
                            source_revisions=dict(quantity=quantity_revision, offers=average['revision'],
                                fulfilment=fingerprint(dict(model=MODEL, quantity_revision=quantity_revision,
                                                           cost_refs=[p.get('cost_ref') for p in paths])),
                                propagation=propagation),
                            site_paths={'266': [path['path_id'] for path in paths]}))


def _catalogue_proof_input(curve, platform, closed, paid_cutoff, now, *, recent=None, checkout=None,
                           facts=None, fx=None, current_cost=None, coupons=None, codes=None):
    from .planning_baskets_v6 import build_planning_baskets
    from .price_curve import curve_key, quote_native

    key = curve_key(curve)
    site = curve['identity']['site_id']
    paths = []
    checkout = checkout if checkout and checkout.get('curve_key') == key and checkout.get('site_id') == '266' else {}
    if checkout and checkout.get('platform') != platform:
        raise ValueError('curve_checkout_platform_mismatch')
    coupons = coupons or {}
    codes = {key: terms for key, terms in (codes or {}).items() if terms['aid'] in ('0', curve['identity']['aid'])}
    code_groups = {}
    for code_ref, terms in codes.items():
        code_groups.setdefault(fingerprint(terms['path']), []).append((code_ref, terms))
    observed = {row['purchase_k']: row for row in checkout.get('lines', [])
                if row.get('proof_status') == 'verified' and row.get('offer_path') == 'anonymous_no_coupon'}
    order_rows = {row['order_key']: row for source in (closed, recent) if source
                  for row in source['historical_orders']}
    repriced = {}
    for tier in curve['tiers']:
        quantity = tier['purchase_k']
        quote = quote_native(curve, dict(purchase_k=quantity, multiplier=1, site_id=site, currency='USD'))
        if quote['regular_usd'] is not None:
            path = dict(quote, path_id='catalogue:' + quantity)
            native = observed.get(quantity)
            if (native and number(native['regular_usd']) == number(quote['regular_usd'])
                    and native.get('promised_delivered_k') == quote['promised_delivered_k']):
                path, matching = _checkout_cost_path(path, native, platform, recent or closed, order_rows,
                                                     paid_cutoff, now, facts, fx, current_cost, observed)
                coupon_paths = {identity: _coupon_quote_path(path, native, identity, terms)
                                for identity, terms in coupons.get('terms', {}).items()}
                code_paths, code_quotes = {}, []
                for group, members in sorted(code_groups.items()):
                    terms = dict(members[0][1], source_revision=fingerprint(sorted(
                        entry['source_revision'] for _, entry in members)))
                    adjusted = _promotion_quote_path(path, native, 'code:' + group, terms,
                                                     'derived_eligible_single_line_discount_code_net_lower_bound')
                    adjusted.update(discount_code_rule=terms['path'], discount_code_terms_revision=terms['source_revision'],
                                    discount_code_eligibility=terms['eligibility'])
                    code_quotes.append(adjusted)
                    code_paths.update((code_ref, adjusted) for code_ref, _ in members)
                repriced.update(matching)
                eligible_coupons = set()
                for identity, row in order_rows.items():
                    promotion = row.get('promotion_path') or {}
                    if (row.get('platform') != platform or row.get('base_k') != quantity
                            or row.get('bonus_k') != native['gift_k'] or row.get('region_id') != 0
                            or row.get('single_line_unit_purchase') is not True):
                        continue
                    if promotion.get('kind') == 'coupon':
                        selected = coupon_paths.get(promotion.get('template_id'))
                        if selected and promotion.get('evidence_ref'):
                            eligible_coupons.add(promotion['template_id'])
                            eligible = fingerprint(dict(redemption=promotion['evidence_ref'],
                                                        current_coupon=selected['coupon_terms_revision']))
                            repriced[identity] = _repriced_checkout_order(row, selected, native, now, eligible)
                    elif promotion.get('kind') == 'code':
                        code_ref = promotion.get('code_ref')
                        selected = code_paths.get(code_ref)
                        if selected:
                            eligible = fingerprint(dict(order=row['source_sha256'], revision=codes[code_ref]['source_revision']))
                            repriced[identity] = _repriced_checkout_order(row, selected, native, now, eligible)
                paths.append(path)
                paths.extend(quote for identity, quote in coupon_paths.items()
                             if identity in eligible_coupons or quote['coupon_eligibility'] != 'directed_fc_event_recipient')
                paths.extend(code_quotes)
            else:
                paths.append(path)
    domain_gaps = [] if checkout else ['native_checkout_path_domain_unverified']
    domain_gaps.extend(checkout.get('coverage_gaps', ()))
    if checkout and {tier['purchase_k'] for tier in curve['tiers']} != set(observed):
        domain_gaps.append('fixed_checkout_quantities_unverified')
    domain_gaps.extend(coupons.get('coverage_gaps', ()))
    return dict(baskets=build_planning_baskets(platform, key, closed, recent, repriced,
                                                paid_cutoff=paid_cutoff, as_of=now),
                evidence=dict(curve_key=key, paths=paths),
                domain=dict(platform=platform, curve_key=key, coverage_status='partial' if domain_gaps else 'complete',
                            coverage_gaps=sorted(set(domain_gaps)),
                            site_paths={'266': [path['path_id'] for path in paths]}))


def _promotion_quote_path(path, native, suffix, terms, basis):
    from .engine import replay_promotion

    rule = terms['path']
    net = replay_promotion(number(path['regular_usd']), rule)
    rounding = 'native_usd_subtotal_cent_and_discount_deduction_upper_cent_v1'
    version = fingerprint(dict(native=native['offer_version'], terms=terms['source_revision']))
    quote_ref = fingerprint(dict(native=native['quote_ref'], offer_version=version, curve=path['curve_key'],
                                 path=suffix, amount=format(net, '.2f'), rounding=rounding))
    return dict(path, path_id=path['path_id'] + ':' + suffix, offer_version=version, quote_ref=quote_ref,
                quote_basis=basis, rounding_contract=rounding, net_receipt_usd=format(net, '.2f'))


def _coupon_quote_path(path, native, identity, terms):
    rule = terms['path']
    eligible_subtotal = number(path['regular_usd']) >= number(rule['threshold_usd'], zero=True)
    adjusted = _promotion_quote_path(path, native, 'coupon:' + identity, terms,
                                     'derived_eligible_single_line_coupon_net_lower_bound')
    return dict(adjusted, coupon_template_id=identity,
                coupon_eligibility=terms['eligibility'], coupon_terms_revision=terms['source_revision'],
                coupon_subtotal_eligible=eligible_subtotal, coupon_rule=rule)


def _repriced_checkout_order(row, path, native, as_of, eligibility):
    return dict(curve_key=path['curve_key'], purchase_k=path['purchase_k'], path_id=path['path_id'],
                quote_ref=path['quote_ref'], eligibility_ref=eligibility,
                fulfilment_ref=native.get('fulfilment_ref') or native['quote_ref'],
                available_at=as_of.isoformat(), order_revision=row['source_sha256'])


def _checkout_cost_path(path, native, platform, population, orders, paid_cutoff, as_of, facts, fx,
                        current_cost, observed):
    from .cost_inputs_v6 import estimate_historical_cost

    path = dict(path, path_id=native['path_id'], site_id='266', proof_status='verified', net_receipt_usd=native['net_goods_usd'],
                quote_ref=native['quote_ref'], offer_version=native['offer_version'],
                fulfilment_contract=native['fulfilment_contract'], native_tier_or_rule=native['native_tier_or_rule'],
                rounding_contract=native['rounding_contract'], quote_basis=native['quote_basis'])
    path['gaps'] = [gap for gap in path['gaps'] if gap not in ('customer_checkout_unverified', 'offer_path_unverified')]
    layer = dict(platform=platform, quantity_bucket='small' if number(path['purchase_k']) < 1000 else 'large',
                 offer_version=native['offer_version'], fulfilment_contract=native['fulfilment_contract'])
    bonus = number(path['promised_bonus_k'], zero=True)
    purchase = number(path['purchase_k'])
    comparable = {quantity: row for quantity, row in observed.items()
                  if row['fulfilment_contract'] == layer['fulfilment_contract']
                  and row['offer_version'] == layer['offer_version']
                  and (number(quantity) < 1000) == (purchase < 1000)
                  and number(row['gift_k'], zero=True) * purchase == bonus * number(quantity)}
    matching, layer_matches = {}, {}
    for identity, row in orders.items():
        source_tier = comparable.get(row.get('base_k'))
        if (row.get('platform') != platform or not source_tier
                or row.get('bonus_k') != source_tier['gift_k']
                or row.get('single_line_unit_purchase') is not True):
            continue
        observed_at = as_of.isoformat()
        if (row['base_k'] == path['purchase_k'] and row.get('region_id') == 0
                and row.get('promotion_path') == {'kind':'none'}):
            matching[identity] = _repriced_checkout_order(row, path, native, as_of, native['eligibility_ref'])
        layer_matches[identity] = dict(layer=layer, available_at=observed_at,
                                       order_revision=row['source_sha256'],
                                       evidence_ref=source_tier.get('fulfilment_ref') or source_tier['quote_ref'])
    if population and facts is not None and layer_matches:
        cost = estimate_historical_cost([population], layer, 'PROMISED_DELIVERED_K', as_of=as_of,
            paid_cutoff=paid_cutoff, layer_matches=layer_matches, fact_revisions=[facts], fx=fx,
            ordinary_forecast=True, selected_orders=tuple(layer_matches), current_cost=current_cost)
        if cost['status'] == 'calculated':
            estimate = cost['diagnostic_estimate']
            total = number(path['promised_delivered_k'])
            path.update(cost_status='verified', quantity_basis='PROMISED_DELIVERED_K',
                        cost_ref=fingerprint(dict(order_cost_source=cost['order_cost_source'],
                                                  attachment_revision=cost['attachment_revision'],
                                                  forecast_fx=cost['forecast_fx'], layer=layer,
                                                  basis=cost['cost_basis'], upper_source=cost['cost_upper_source'],
                                                  current_source=cost['current_cost_source'],
                                                  paid_cutoff=paid_cutoff)),
                        **{name + '_cost_usd': str(total * estimate[name + '_unit_usd'])
                           for name in ('expected', 'safe', 'stress')})
        else:
            path['ordinary_cost_gaps'] = cost['gaps']
    elif facts is None:
        path['ordinary_cost_gaps'] = ['ordinary_delivery_source_unavailable']
    else:
        path['ordinary_cost_gaps'] = ['ordinary_delivery_cost_sample_missing']
    return path, matching


def _all_curve_target(all_before, primary_target):
    from .price_curve import read_curve

    before = all_before['native_payload']
    source = primary_target['native_payload']
    payload = dict(before, unit_price=source['unit_price'],
                   more=dict(before['more'], price=source['more']['price'], discount=source['more']['discount']))
    return read_curve(payload, all_before['identity'], primary_target['native_contract'])


def original_restore_curves(db, operation_id, plan, conn=None):
    """Use the exact ALL before tables from one completed, fully read-back operation."""
    from coin_all_sync_job import editable
    from .price_curve import read_curve

    original = db.get('operations', operation_id, conn)
    if not original:
        raise ValueError('pricing_restore_original_missing')
    bundle = original['bundle']
    if (original['operation_id'] != operation_id or original['status'] != 'COMPLETED'
            or write_protocol(bundle) != CURVE_WRITE_PROTOCOL or bundle['decision_bundle_id'] != operation_id):
        raise ValueError('pricing_restore_original_unconfirmed')
    confirmed_curve_window(original)
    before = bundle['before_action']['curves']
    items = original['readback']['curve_results']
    owned = {p: before[p] for p in bundle['affected_platforms'] if 'base:' + p in plan['resources']}
    if not owned:
        raise ValueError('pricing_manual_scope_not_owned')
    for platform, curve in owned.items():
        item = items[platform]
        # Bind the coordinator's original before to the writer's actual CAS record.
        if (item.get('before') != curve['native_payload']
                or item.get('before_hash') != fingerprint(editable(curve['native_payload']))):
            raise ValueError('pricing_restore_original_before_unbound')
    return {p: read_curve(curve['native_payload'], curve['identity'], curve['native_contract'])
            for p, curve in owned.items()}


def _curve_restore_target(current, original):
    from .price_curve import EDITOR_CATALOGUE_ORIGIN, _more, read_curve

    # Tier order belongs to the native editor. Every retained quantity, gift,
    # discount, and compatibility unit price must match the original table.
    saved = original['native_payload']
    live = current['native_payload']
    spec = ('purchase_k', 'promised_bonus_k', 'native_discount')
    if (current['identity'] != original['identity']
            or current['unit_price_usd_per_k'] != original['unit_price_usd_per_k']
            or live.get('discount') != saved.get('discount')
            or [tuple(row[k] for k in spec) for row in current['tiers']]
            != [tuple(row[k] for k in spec) for row in original['tiers']]):
        raise ValueError('pricing_restore_quantity_or_offer_changed')
    payload = dict(live, more=dict(_more(live), price=_more(saved)['price']))
    contract = dict(current['native_contract'], catalogue_origin=EDITOR_CATALOGUE_ORIGIN)
    return read_curve(payload, current['identity'], contract)


def _curve_restore_intent(db, plan, preview_id, operation_id, now, conn=None):
    intent = db.get('manual_previews', preview_id, conn)
    if (not intent or intent.get('write_protocol') != CURVE_WRITE_PROTOCOL
            or intent['operation_id'] != operation_id or intent['plan_id'] != plan['plan_id']
            or intent['revision'] != plan['revision'] or now >= instant(intent['valid_until'])):
        raise ValueError('pricing_curve_restore_preview_invalid')
    source = original_restore_curves(db, intent['restore_source_execution_id'], plan, conn)
    if fingerprint(source) != intent['restore_before_sha256']:
        raise ValueError('pricing_restore_original_before_unbound')
    return intent, source


def _same_hour_curve_performance(platform, online, now):
    """Use already-bound FC outcomes from two closed equal clock-hour slots."""
    coverage = online.get('learning_coverage') or {}
    if coverage.get('query_complete') is not True or not coverage.get('source_sha256'):
        return {}
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=1)
    previous_start, previous_end = start - timedelta(days=1), end - timedelta(days=1)
    if not coverage.get('observed_at') or instant(coverage['observed_at']) < end or coverage.get('unscoped_time_gaps'):
        return {}
    for gap in coverage.get('gap_events', []):
        stamp = gap.get('occurred_at')
        if (stamp and gap.get('group') in (None, platform, 'global:'+platform)
                and (start <= instant(stamp) < end or previous_start <= instant(stamp) < previous_end)):
            return {}
    buckets = {name: {'current': [], 'previous': []} for name in ('small', 'large')}
    for row in online.get('actual_outcomes', []):
        if row.get('platform') != platform:
            continue
        at = instant(row['occurred_at'])
        window = 'current' if start <= at < end else 'previous' if previous_start <= at < previous_end else None
        if window is None:
            continue
        quantity = row.get('purchase_k')
        if quantity is None:
            return {}
        buckets['small' if number(quantity) < 1000 else 'large'][window].append(row)
    result = {}
    for segment, sample in buckets.items():
        if not sample['current'] or not sample['previous']:
            continue
        population = sample['current'] + sample['previous']
        if any(row.get('actual_net_usd') is None for row in population):
            continue
        margin_known = all(row.get('actual_contribution_usd') is not None
                           and row.get('cost_basis') == 'same_order_Order_shipping_CNY_margin_at_actual_USD_receipt'
                           for row in population)
        totals = {}
        for name, rows in sample.items():
            totals[name] = dict(paid_orders=len(rows),
                                net_paid_usd=str(sum(Decimal(row['actual_net_usd']) for row in rows)))
            if margin_known:
                totals[name]['procurement_gross_usd'] = str(sum(Decimal(row['actual_contribution_usd']) for row in rows))
        result[segment] = dict(totals, coverage_status='comparable',
                               margin_basis='procurement_gross_usd' if margin_known else None,
                               source_sha256=coverage['source_sha256'], current_start=start.isoformat(),
                               current_end=end.isoformat(), previous_start=previous_start.isoformat(),
                               previous_end=previous_end.isoformat())
    return result


def _curve_insurance_context(db, platform, evidence, now):
    from .curve_strategy_v6 import band_anchors, large_market_reference

    cutoff = now - timedelta(hours=24)
    windows = [row for row in db.all('actual_price_windows')
               if row.get('write_protocol') == CURVE_WRITE_PROTOCOL
               and platform in (row.get('action', {}).get('curves') or {})
               and instant(row['opened_at']) <= cutoff
               and (row.get('resource_closed_at', {}).get('base:' + platform) is None
                    or instant(row['resource_closed_at']['base:' + platform]) > cutoff)]
    day = max(windows, key=lambda row: instant(row['opened_at']), default=None)
    reference = None
    with db.connect() as conn:
        for raw, in conn.execute('SELECT body FROM operations ORDER BY rowid DESC'):
            op = json.loads(raw)
            if (op.get('status') not in ('COMPLETED', 'NO_CHANGE')
                    or platform not in (op.get('bundle', {}).get('action', {}).get('curves') or {})):
                continue
            try:
                confirmed_curve_window(op)
            except ValueError:
                continue
            snapshot = db.get('pricing_snapshots', op['bundle']['snapshot_id'], conn) or {}
            cost = (snapshot.get('evidence', {}).get('costs') or {}).get(platform) or {}
            selected = (op['bundle'].get('curve_selection') or {}).get(platform) or {}
            reference = selected.get('confirmed_cost_cny_per_k') or cost.get('cny_per_1k')
            break
        # Old strategy rows contain large forecasts; project only this release's natural rounds.
        decisions = [json.loads(raw) for raw, in conn.execute(
            'SELECT body FROM strategy_decisions WHERE body LIKE ?', ('%"automatic_curve_round": true%',))]
    own = ((evidence.get('storefront') or {}).get('rows') or {}).get(platform) or {}
    market = []
    for source, region in (('Lootbar', '0'), ('U7Buy', '0'), ('ArabUT', '21')):
        offers = [row for row in evidence.get('competitor_offers', []) if row.get('source') == source]
        rows = large_market_reference(platform, offers, now, region_id=region,
            delivery_method=own.get('delivery_method') or 'comfort_trade')
        if len(rows) == 1:
            market.append(rows[0]['usd_per_delivered_100k'])
    rounds = 0
    seen = set()
    decisions.sort(key=lambda row: row.get('created_at', ''), reverse=True)
    for decision in decisions:
        if not decision.get('automatic_curve_round') or decision.get('curve_round_id') in seen:
            continue
        seen.add(decision['curve_round_id'])
        row = next((row for row in decision.get('curve', []) if row['platform'] == platform), None)
        if row is None:
            continue
        below_margin = ((row.get('selection') or {}).get('price_insurance') or {}).get('below_margin')
        if not below_margin and row['status'] not in ('READY', 'KEEP'):
            continue
        if not below_margin:
            break
        rounds += 1
    return dict(day_anchors=band_anchors(day['action']['curves'][platform]) if day else {},
                day_window_id=day['operation_id'] if day else None,
                market_per_100k=market, confirmed_cost_cny_per_k=reference, below_margin_rounds=rounds)


def _curve_plan_binding(plan):
    from .curve_strategy_v6 import MARKET_ANCHOR_VERSION, market_anchor_parameters

    if plan is None:
        return None
    version = plan.get('smart_strategy_version')
    parameter_hash = None
    if version == MARKET_ANCHOR_VERSION:
        parameters = plan.get('parameters') or {}
        anchors = market_anchor_parameters(parameters.get('market_anchor'))
        margin_band = parameters.get('margin_band')
        parameter_hash = fingerprint(dict(market_anchor=anchors, margin_band=margin_band) if margin_band else anchors)
    return dict(plan_id=plan.get('plan_id'), revision=plan.get('revision'), strategy_version=version,
                parameters_sha256=parameter_hash)


def _curve_market_history(db, now, *, exclude_snapshot=None):
    """Project quote evidence only; SQLite 3.7 has no JSON extraction extension."""
    from contextlib import closing

    fields = ('source', 'platform', 'purchase_k', 'currency', 'promotion_eligibility', 'conditional',
              'comparable', 'region_id', 'delivery_method', 'comparability_basis', 'captured_at',
              'regular_price', 'bonus_k', 'observation_id')
    history = []
    with closing(db.connect()) as conn:
        rounds = {}
        for ident, raw in conn.execute('SELECT id,body FROM strategy_decisions WHERE body LIKE ?',
                                       ('%"automatic_curve_round": true%',)):
            row = json.loads(raw)
            if row.get('automatic_curve_round') and row.get('curve_round_id'):
                rounds[ident] = row['curve_round_id']
        # Stream full historical bodies instead of holding order/proof payloads in memory.
        for ident, raw in conn.execute('SELECT id,body FROM pricing_snapshots ORDER BY rowid DESC'):
            if ident == exclude_snapshot:
                continue
            row = json.loads(raw)
            if row.get('origin') != 'live_collector' or row.get('write_protocol') != CURVE_WRITE_PROTOCOL:
                continue
            at = instant(row['created_at'])
            if not now - timedelta(days=7) <= at < now:
                continue
            offers = [{key: offer.get(key) for key in fields} for offer in
                      (row.get('evidence') or {}).get('competitor_offers') or []
                      if offer.get('source') in ('Lootbar', 'U7Buy', 'ArabUT') and offer.get('purchase_k') == '100']
            if offers:
                history.append(dict(snapshot_id=ident, round_id=rounds.get(ident, ident), as_of=at.isoformat(),
                                    automatic=ident in rounds, offers=offers))
    return history


def _margin_band_history(db, plan_id):
    from contextlib import closing

    history = {platform: [] for platform in PLATFORMS}
    with closing(db.connect()) as conn:
        for raw, in conn.execute("SELECT body FROM strategy_decisions WHERE body LIKE ? ORDER BY rowid",
                                 ('%"margin_band_plan_id"%',)):
            row = json.loads(raw)
            if row.get('margin_band_plan_id') != plan_id or not row.get('automatic_curve_round'):
                continue
            for decision in row['curve']:
                selection = (decision.get('selection') or {}).get('margin_band')
                if selection and selection['decision_round']['is_decision_round']:
                    history[decision['platform']].append(dict(selection, status=decision['status']))
    return history


def _margin_band_cycle_context(db, plan, job, now, hours):
    from contextlib import closing
    from .cost_inputs_v6 import BEIJING

    request = job.get('request') or {}
    at = instant(job['created_at']) if job.get('created_at') else now
    automatic = bool(request.get('v3_operation_id') and not request.get('manual_requested'))
    last_hour = at.astimezone(BEIJING).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    failed = False
    if automatic and last_hour.hour in hours:
        start = last_hour.astimezone(timezone.utc)
        stop = start + timedelta(hours=1)
        with closing(db.connect()) as conn:
            jobs = conn.execute("SELECT body FROM durable_jobs WHERE kind='cycle' AND state IN ('failed','done') "
                                "AND due_at>=? AND due_at<?", (start.isoformat(), stop.isoformat()))
            failed = any(not row.get('manual_requested')
                         and (row.get('plan_id'), row.get('revision')) == (plan['plan_id'], plan['revision'])
                         for row in (json.loads(raw) for raw, in jobs))
    return dict(at=at, automatic=automatic, collection_failed=failed)


def collect_curve_catalogues(evidence, platforms):
    """Collect current saved Goods rows for the same run's private proof inputs."""
    from contextlib import closing
    from coin_all_sync_job import PRODUCTS, read_curve_routes, read_row
    from fc_shared_admin import SessionManager, read_private_config
    from .api import _curve_preview_history
    from .average_discount_v6 import MODEL, average_discount
    from .business_source import collect_recent_curve_population
    from .curve_strategy_v6 import ANCHORS, MARKET_ANCHOR_VERSION, build_candidates
    from .pricing_proof_v6 import PROVEN
    from .smart import curve_learning
    from .price_curve import (EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, TWO_BAND_PRICE_EDIT,
                              IDENTITY_FIELDS, curve_key, read_curve)

    try:
        manager = SessionManager(read_private_config())
    except (OSError, ValueError):
        return {}
    try:
        routes = read_curve_routes(manager)
    except (OSError, TypeError, ValueError):
        routes = {}
    db = ledger()
    paid_cutoff = evidence['checked_at']
    job_path = ROOT / 'jobs' / (evidence['run_id'] + '.json')
    job = json.loads(job_path.read_text()) if job_path.exists() else {}
    request = job.get('request') or {}
    plan_id = request.get('v3_plan_id')
    restore_id = request.get('curve_restore_preview_id')
    with closing(db.connect()) as conn:
        plan = db.get('pricing_plans', plan_id, conn) if plan_id and request.get('v3_operation_id') else None
        restore = (_curve_restore_intent(db, plan, restore_id, request['v3_operation_id'], clock(), conn)[1]
                   if restore_id else {})
        online = (db.get('metadata', 'curve-online-context:' + plan_id, conn) if plan_id else None) or {}
        # Live diagnostic uses the latest already archived exact window.
        # Historical preview retains the original attachment/snapshot binding.
        closed = _curve_preview_history(conn, dict(snapshot_id=evidence['run_id'], created_at=paid_cutoff), clock(),
                                        require_snapshot_binding=False)
    collected = {}
    for platform in platforms:
        if restore and platform not in restore:
            continue
        public = (evidence.get('storefront') or {}).get('rows', {}).get(platform) or {}
        if public.get('sku_id') is not None and str(public['sku_id']) != str(PRODUCTS[platform][1]):
            continue
        observed = []
        try:
            primary = read_row(manager, platform, 266, observer=observed.append)
            all_row = read_row(manager, platform, 0, observer=observed.append)
            contract = dict(source='Admin Goods edit read only', verified_domain='native stored tiers only',
                            editor_asset_sha256=EDITOR_ASSET_SHA256, editor_handler_sha256=EDITOR_HANDLER_SHA256,
                            price_edit_policy=TWO_BAND_PRICE_EDIT)
            current, all_before = (read_curve(row, {key: row[key] for key in IDENTITY_FIELDS}, contract)
                                   for row in (primary, all_row))
        except (OSError, TypeError, ValueError):
            continue
        editor = contract
        candidates = {curve_key(current): current}
        state = db.curve_strategy_state(platform) if not restore else None
        if state:
            for segment in ANCHORS:
                comparison = build_candidates(current, state['reference'], state['episode'], segment,
                                              editor_contract=editor, check_saved_discount_terms=True)
                candidates.update({row['curve_key']: row['curve'] for row in comparison['candidates']})
        all_targets = {key: _all_curve_target(all_before, curve) for key, curve in candidates.items()
                       if key != curve_key(current)}
        collected[platform] = dict(primary_curve=current, all_before=all_before, editor_contract=editor,
                                   native_route=routes.get(platform), candidates=candidates, readbacks=observed,
                                   all_targets=all_targets)
        if restore:
            try:
                target = _curve_restore_target(all_before, restore[platform])
            except ValueError:
                # The same exact mismatch will be surfaced by the proof stage.
                continue
            all_targets[curve_key(target)] = target
    if not collected:
        return {}
    try:
        shared_closed, facts, discount_source = _shared_curve_inputs(paid_cutoff, clock(), code_names=None)
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        shared_closed, facts, discount_source = None, None, None
    if shared_closed is not None:
        closed = shared_closed
    try:
        recent = collect_recent_curve_population(manager, closed, paid_cutoff)
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        recent = None
    now = clock()
    valid_until = now + timedelta(minutes=15)

    market_plan = plan and plan.get('smart_strategy_version') == MARKET_ANCHOR_VERSION
    market_history = (_curve_market_history(db, now, exclude_snapshot=evidence['run_id'])
                      if plan and plan['mode'] == 'smart' and not restore else [])
    learning_windows = db.all('actual_price_windows') if plan and online and plan['mode'] == 'smart' and not market_plan else []
    margin_config = (plan.get('parameters') or {}).get('margin_band') if market_plan else None
    decision_history = _margin_band_history(db, plan['plan_id']) if margin_config else {}
    margin_context = (_margin_band_cycle_context(db, plan, job, now, margin_config['schedule_hours'])
                      if margin_config else {})
    for platform, entry in collected.items():
        average = average_discount(discount_source, platform, paid_cutoff)
        from .cost_inputs_v6 import smooth_delivery_cost
        context = _curve_insurance_context(db, platform, evidence, now)
        cost = smooth_delivery_cost((evidence.get('costs') or {}).get(platform), platform, now,
                                    context['confirmed_cost_cny_per_k'])
        entry['price_insurance'] = context
        entry['cost_sample_insurance'] = (cost or {}).get('sample_insurance')
        entry['confirmed_cost_cny_per_k'] = (cost or {}).get('cny_per_1k') if (cost or {}).get('status') == 'valid' else None
        if cost and cost.get('reason') == 'curve_cost_sample_outlier':
            db.incident('curve_cost_sample_outlier', 'cost', [platform])

        def proof(curve):
            return _average_discount_proof_input(curve, platform, closed, recent, paid_cutoff, now,
                average=average, route=entry['native_route'], facts=facts, fx=evidence.get('fx'),
                current_cost=cost)

        entry.update(captured_at=now.isoformat(), valid_until=valid_until.isoformat(), pricing_assumption=MODEL,
                     plan_binding=_curve_plan_binding(plan),
                     primary_inputs={key: proof(curve) for key, curve in entry.pop('candidates').items()},
                     all_inputs={curve_key(curve): proof(curve) for curve in entry['all_targets'].values()},
                     performance=_same_hour_curve_performance(platform, online, now))
        if any('curve_cost_sample_outlier' in item['domain']['coverage_gaps']
               for item in entry['primary_inputs'].values()):
            db.incident('curve_cost_sample_outlier', 'cost', [platform])
        current = entry['primary_curve']
        state = db.curve_strategy_state(platform)
        if learning_windows and state:
            entry['learning'] = curve_learning(plan, platform, state, online, learning_windows, now, current)
        if restore:
            continue
        if (state and editor.get('price_edit_policy') == TWO_BAND_PRICE_EDIT
                and entry['primary_inputs'][curve_key(current)]['evidence'].get('average_discount')):
            previous = db.curve_cost_protection(platform)
            entry['market_history'] = market_history
            if margin_config:
                entry['margin_band_context'] = dict(margin_context,
                    history=decision_history[platform],
                    cost_sample_count=sum(instant(row['trade_at']) >= now - timedelta(hours=3)
                                          for row in (cost or {}).get('sample_records', ())))
            _freeze_cost_protection(platform, entry, proof, state, plan, evidence, now, previous)
            entry.pop('margin_band_context', None)
            if plan and plan['mode'] == 'smart' and not market_plan:
                _freeze_anchor_shadow(platform, entry, proof, state, plan, evidence, now, previous)
            entry.pop('market_history', None)
            continue
        current_proof = _validated_curve(current, entry['primary_inputs'][curve_key(current)])
        if current_proof['status'] == 'HARD_CONSTRAINT_FAILED':
            repair = _average_discount_repair(current, entry['all_before'], entry['editor_contract'],
                                              current_proof, proof)
            if repair:
                entry['repair'] = repair
        elif current_proof['status'] == PROVEN and plan and state:
            _freeze_intermediate_trial(platform, entry, proof, state, plan, evidence, now)
    return collected


def _margin_band_discount_refresh(now):
    from .cost_inputs_v6 import BEIJING

    local = now.astimezone(BEIJING)
    return local.hour == 0 and local.minute < 15


def margin_band_round(now, schedule_hours, history=(), *, automatic=True, collection_failed=False,
                      evaluated_at=None):
    """Identify the Shanghai slot and its single next-hour retry."""
    from .cost_inputs_v6 import BEIJING

    local = now.astimezone(BEIJING)
    hour = local.replace(minute=0, second=0, microsecond=0)
    starts = [hour.replace(hour=value) for value in schedule_hours]
    slot = max((value for value in starts if value <= hour), default=max(starts) - timedelta(days=1))
    slot_start = slot.isoformat()
    if ((local.hour == 0 and (0 not in schedule_hours or local.minute < 15))
            or (evaluated_at is not None and _margin_band_discount_refresh(evaluated_at))):
        return dict(is_decision_round=False, slot_start=slot_start, retry=False)
    attempts = [row for row in history if row['decision_round']['slot_start'] == slot_start
                and row['decision_round']['is_decision_round']]
    retry = (hour == slot + timedelta(hours=1) and (attempts or collection_failed)
             and not any(row['decision_round']['retry'] or row['status'] in ('READY', 'KEEP') for row in attempts))
    initial = hour == slot and not attempts
    return dict(is_decision_round=automatic and (initial or retry), slot_start=slot_start,
                retry=automatic and retry)


def margin_band_selection(proof, position, current, target, decision_round, *, cost_median,
                          cost_sample_count, previous_decision_cost_median):
    """Choose native band anchors before the original safety and insurance checks."""
    from .average_discount_v6 import CENT, band_margin, band_target_price

    lower, upper = target - CENT, target + CENT
    drop = (cost_median is not None and previous_decision_cost_median is not None and cost_sample_count < 6
            and Decimal(cost_median) <= Decimal(previous_decision_cost_median) * Decimal('.92'))
    guarded = proof
    if proof and drop:
        ratio = Decimal(previous_decision_cost_median) / Decimal(cost_median)
        guarded = dict(proof, paths=[
            dict(row, safe_cost_usd=str(Decimal(row['safe_cost_usd']) * ratio))
            if row.get('safe_cost_usd') is not None else row for row in proof['paths']
        ])
    bands = {}
    for band, price in current.items():
        low = position.get('low_anchors', {}).get(band)
        high = position['anchors'].get(band)
        margin = band_margin(proof, band) if proof else None
        desired, action, capped, unconfirmed = Decimal(price) if price is not None else None, 'none', None, False
        if decision_round['is_decision_round'] and margin is not None and low is not None and high is not None:
            lo, hi = Decimal(low), Decimal(high)
            if lo <= hi:
                clamped = min(hi, max(lo, desired))
                unconfirmed = margin > upper and drop
                used = guarded if unconfirmed else proof
                decision_margin = band_margin(used, band) if unconfirmed else margin
                # A cost drop awaiting confirmation may cancel a cut, but cannot call for a raise.
                if margin < lower:
                    action = 'raise'
                    found = band_target_price(used, band, target, lo, hi)
                    desired = hi if found is None else found
                    if found is None:
                        capped = 'capped_by_market'
                elif decision_margin > upper:
                    found = band_target_price(used, band, target, lo, clamped)
                    if found is None:
                        desired, action = clamped, 'hold'
                    else:
                        desired, action = found, 'lower'
                        if found == lo and lo > CENT:
                            below = lo - CENT
                            if band_target_price(used, band, target, below, below) is not None:
                                capped = 'capped_by_corridor'
                else:
                    desired, action = clamped, 'hold'
        bands[band] = dict(margin_at_current=str(margin) if margin is not None else None,
                           action=action, desired=str(desired) if desired is not None else None, low=low, high=high, capped=capped,
                           cost_drop_unconfirmed=unconfirmed)
    return dict(decision_round=decision_round, target=str(target), hold_range=[str(lower), str(upper)],
                cost_median=cost_median, cost_sample_count=cost_sample_count,
                previous_decision_cost_median=previous_decision_cost_median, bands=bands)


def _freeze_cost_protection(platform, entry, inputs_for, state, plan, evidence, now, previous):
    from .average_discount_v6 import minimum_band_price
    from .curve_strategy_v6 import (ANCHORS, band_anchors, build_candidates, large_market_reference,
                                    large_market_comparison, market_anchor_targets, market_direction, segment_changes)
    from .price_curve import coin_quantity_band, compile_curve, curve_key
    from .pricing_proof_v6 import FAILED, PROVEN

    current, editor = entry['primary_curve'], entry['editor_contract']
    preference = _curve_preference(platform, current, evidence, entry, now, plan=plan, state=state)
    reference, episode = state['reference'], state['episode']
    own = ((evidence.get('storefront') or {}).get('rows') or {}).get(platform) or {}
    # MMOEXP's published ordinary Coins fulfillment is Comfort Trade.
    market = large_market_reference(platform, evidence.get('competitor_offers') or [], now,
        region_id=own.get('region_id') or '0', delivery_method=own.get('delivery_method') or 'comfort_trade')
    if (preference['segment'] == 'large' and preference.get('source') == 'smart_three_hour_block'
            and preference['label'] != 'A' and len(market) == 1):
        strategy_curve = reference['reference_curve']
        comparable = large_market_comparison(market, strategy_curve, strategy_curve)
        signal = (market_direction('large', Decimal(comparable[0]['normal_difference_pct']) / 100,
                                   entry.get('performance') or {}) if comparable else None)
        assignment = preference['assignment']
        excluded = set((assignment.get('policy') or {}).get('excluded') or [])
        excluded.update(label for label, block in (assignment.get('correction') or {}).get('effective_blocks', {}).items()
                        if assignment['block'] >= block)
        if signal and signal['label'] not in excluded:
            preference = dict(preference, **signal, source='market_100k_linear_reference')
    base = dict(reference_curve_id=reference['reference_curve_id'],
                comparison_episode_id=episode['comparison_episode_id'], previous=previous, preference=preference)
    entry['temporary_cost_protection'] = frozen = dict(base, status='PROOF_INCOMPLETE', gaps=[])
    segment, label = preference['segment'], preference['label']
    active = previous.get('segments') or {}
    if label == 'CURRENT' and segment in active:
        label = 'A'
        preference = dict(preference, label=label)
        frozen['preference'] = preference
    position, margin_band = None, None
    if preference.get('source') == 'market_anchor':
        position = market_anchor_targets(platform, current, evidence.get('competitor_offers') or [], now,
            parameters=(plan.get('parameters') or {}).get('market_anchor'), history=entry.get('market_history') or [])
        prices = position['anchors']
        configuration = (plan.get('parameters') or {}).get('margin_band')
        if configuration and 'low_anchors' in position:
            context = entry.get('margin_band_context') or {}
            history = context.get('history', ())
            decision = margin_band_round(context.get('at', now), configuration['schedule_hours'], history,
                                         automatic=context.get('automatic', False),
                                         collection_failed=context.get('collection_failed', False), evaluated_at=now)
            prior = next((row for row in reversed(history)
                          if row['decision_round']['slot_start'] < decision['slot_start'] and row['cost_median']), {})
            current_input = entry['primary_inputs'].get(curve_key(current)) or inputs_for(current)
            current_proof = _validated_curve(current, current_input)
            observed = band_anchors(current)
            margin_band = margin_band_selection(
                current_proof if current_proof['status'] in (PROVEN, FAILED) else None,
                position, observed, Decimal(configuration[platform]['target']), decision,
                cost_median=entry.get('confirmed_cost_cny_per_k'), cost_sample_count=context.get('cost_sample_count', 0),
                previous_decision_cost_median=prior.get('cost_median'),
            )
            preference = dict(preference, margin_band=margin_band)
            frozen['preference'] = preference
            prices = {band: row['desired'] for band, row in margin_band['bands'].items()
                      if Decimal(row['desired']) != Decimal(observed[band])}
        if position['floor_only'] and (not margin_band or margin_band['decision_round']['is_decision_round']):
            # Missing quotes do not cancel a previously confirmed protection release.
            observed = band_anchors(current)
            prices = {band: prior['normal'] for band, prior in active.items() if observed[band] == prior['target']}
        normal = (compile_curve(current, dict(anchor_prices_usd={ANCHORS[band]: value
                    for band, value in prices.items()}), editor) if prices else current)
        candidate = dict(curve=normal, labels=['A'], write_gaps=(normal.get('gaps') or ['market_anchor_compile_failed'])
                         if prices and normal.get('compilation_status') != 'EDITOR_CANDIDATE' else [])
        preference = dict(preference, market_anchor=position)
        frozen.update(preference=preference, market_anchor=position)
    else:
        comparison = build_candidates(current, reference, episode, segment, editor_contract=editor,
                                      check_saved_discount_terms=True)
        candidate = next((row for row in comparison['candidates'] if label in row['labels']), None)
    if not candidate or candidate['write_gaps']:
        gaps = candidate['write_gaps'] if candidate else comparison['gaps'].get(label, ['normal_candidate_unavailable'])
        current_key = curve_key(current)
        current_input = entry['primary_inputs'][current_key]
        if _validated_curve(current, current_input)['status'] == PROVEN and not active:
            frozen.update(status=PROVEN, final_key=current_key, labels=[], normal_anchors=band_anchors(current),
                          final_anchors=band_anchors(current), segments={}, normal_curve=current, final_curve=current,
                          gaps=gaps)
        else:
            frozen['gaps'] = gaps
        return
    normal = candidate['curve']
    frozen['market_reference'] = market
    observed = band_anchors(current)
    controls = {ANCHORS[band]: row['normal'] for band, row in active.items()
                if not position and band != segment and (observed.get(band) == row['target'] or previous.get('status') == 'legacy')}
    if controls:
        normal = compile_curve(normal, dict(anchor_prices_usd=controls), editor)
        if normal.get('compilation_status') != 'EDITOR_CANDIDATE':
            frozen['gaps'] = normal['gaps']
            return
    # An A/B/C arm is comparable only when the other band did not move.
    preference = dict(preference, restore_other_band=bool(controls))
    frozen['preference'] = preference
    normal_key = curve_key(normal)
    normal_input = entry['primary_inputs'].get(normal_key) or inputs_for(normal)
    proof = _validated_curve(normal, normal_input)
    all_normal = _all_curve_target(entry['all_before'], normal)
    all_normal_input = entry['all_inputs'].get(curve_key(all_normal)) or inputs_for(all_normal)
    all_proof = _validated_curve(all_normal, all_normal_input)
    incomplete = next((row for row in (proof, all_proof) if row['status'] not in (PROVEN, FAILED)), None)
    if incomplete:
        frozen['gaps'] = incomplete['gaps']
        return
    failed = [row for row in (proof, all_proof) if row['status'] == FAILED]
    final = normal
    if failed:
        affected = {coin_quantity_band(row['purchase_k']) for row in failed for row in row['paths']
                    if row['zero_line_status'] == FAILED}
        base = normal
        # If both bands contain a loss-making path, put each at its own
        # break-even cent before solving the remaining basket constraint.
        if len(affected) > 1:
            prices = band_anchors(base)
            controls = {}
            for band in affected:
                floors = [minimum_band_price(row, band, ANCHORS[band], prices[band], zero_line_only=True,
                          current_anchor=observed[band]) for row in failed]
                if any(floor is None for floor in floors):
                    frozen.update(status=FAILED, gaps=['curve_cost_protection_band_floor_unavailable'])
                    return
                controls[ANCHORS[band]] = str(max(floors))
            base = compile_curve(base, dict(anchor_prices_usd=controls), editor)
            if base.get('compilation_status') == 'EDITOR_CANDIDATE':
                all_base = _all_curve_target(entry['all_before'], base)
                checks = [_validated_curve(curve, inputs_for(curve)) for curve in (base, all_base)]
                if any(row['status'] not in (PROVEN, FAILED) for row in checks):
                    return
                failed = [row for row in checks if row['status'] == FAILED]
        final = base
        if failed and base.get('compilation_status', 'EDITOR_CANDIDATE') == 'EDITOR_CANDIDATE':
            bands = list(dict.fromkeys([*active, *ANCHORS] if position else [*active, segment]))
            if affected:
                bands = [band for band in dict.fromkeys([*bands, *ANCHORS]) if band in affected]
            prices = band_anchors(base)
            for band in bands:
                floors = [minimum_band_price(row, band, ANCHORS[band], prices[band],
                          current_anchor=observed[band]) for row in failed]
                if all(floor is not None for floor in floors):
                    final = compile_curve(base, dict(anchor_prices_usd={ANCHORS[band]: str(max(floors))}), editor)
                    break
        if final is normal or final.get('compilation_status') != 'EDITOR_CANDIDATE':
            frozen.update(status=FAILED, gaps=sorted({gap for row in failed for gap in row['hard_failures']}))
            return
    # Stability only holds a currently proven price; a zero-line or basket
    # failure still goes through the normal protection and insurance path.
    proposed = band_anchors(final)
    financial_bands = {band for band, price in band_anchors(normal).items()
                       if Decimal(proposed[band]) > Decimal(price)}
    protected = set(segment_changes(normal, final)) | set(active)
    if position:
        protected.update(ANCHORS)
    holds, release_rounds = {}, {}
    current_checks = [_validated_curve(curve, inputs_for(curve)) for curve in (current, entry['all_before'])]
    if all(row['status'] == PROVEN for row in current_checks):
        for band in protected:
            old, target = Decimal(observed[band]), Decimal(proposed[band])
            previous_band = active.get(band) or {}
            retreat = target < old and previous_band.get('target') == observed[band]
            count = min(previous_band.get('release_rounds', 0) + 1, 3) if retreat else 0
            if count:
                release_rounds[band] = count
            if target != old and ((retreat and count < 3) or abs(target / old - 1) < Decimal('.015')):
                holds[band] = dict(reason='release_hysteresis' if retreat and count < 3 else 'dead_zone',
                                   requested=str(target), kept=str(old), release_rounds=count)
        if holds:
            final = compile_curve(final, dict(anchor_prices_usd={ANCHORS[band]: observed[band] for band in holds}), editor)
            if final.get('compilation_status') != 'EDITOR_CANDIDATE':
                frozen.update(gaps=final['gaps'])
                return
    frozen['stability'] = holds
    insurance = None
    if 'price_insurance' in entry:
        from coin_all_sync_job import curve_price_insurance
        try:
            insurance = curve_price_insurance(current, final, entry['price_insurance'])
        except ValueError as error:
            frozen.update(status='PROOF_INCOMPLETE', gaps=[str(error)])
            return
        if insurance['clipped']:
            final = compile_curve(final, dict(anchor_prices_usd={ANCHORS[band]: price
                                  for band, price in insurance['anchors'].items()}), editor)
            if final.get('compilation_status') != 'EDITOR_CANDIDATE':
                frozen.update(gaps=final['gaps'])
                return
        frozen['price_insurance'] = insurance
    final_key = curve_key(final)
    entry['primary_inputs'][final_key] = (normal_input if final_key == normal_key else inputs_for(final))
    exception = None
    upward = {band: row for band, row in (insurance or {}).get('clipped', {}).items()
              if Decimal(row['bounded']) > Decimal(observed[band])}
    if upward:
        exception = dict(before_anchors=observed, clipped=upward,
                         round=entry['price_insurance']['below_margin_rounds'] + 1)
        entry['primary_inputs'][final_key]['domain']['price_insurance'] = exception
    checked = _validated_curve(final, entry['primary_inputs'][final_key])
    if insurance:
        insurance.update(below_margin=bool(checked.get('price_insurance', {}).get('below_margin')))
    if checked['status'] != PROVEN:
        frozen.update(status=checked['status'], gaps=checked['gaps'] + checked['hard_failures'])
        if insurance and insurance['below_margin'] and exception['round'] > 2:
            frozen['gaps'].append('pricing_curve_margin_exception_exhausted')
        frozen['preference'] = dict(preference, price_insurance=insurance)
        return
    if final_key != curve_key(current):
        target = _all_curve_target(entry['all_before'], final)
        entry['all_targets'][final_key] = target
        entry['all_inputs'][curve_key(target)] = all_normal_input if final_key == normal_key else inputs_for(target)
        if exception:
            entry['all_inputs'][curve_key(target)]['domain']['price_insurance'] = exception
        all_checked = _validated_curve(target, entry['all_inputs'][curve_key(target)])
        if insurance:
            insurance['below_margin'] |= bool(all_checked.get('price_insurance', {}).get('below_margin'))
        if all_checked['status'] != PROVEN:
            frozen.update(status=all_checked['status'], gaps=all_checked['gaps'] + all_checked['hard_failures'],
                          preference=dict(preference, price_insurance=insurance))
            if insurance and insurance['below_margin'] and exception['round'] > 2:
                frozen['gaps'].append('pricing_curve_margin_exception_exhausted')
            return
    normal_prices, final_prices = band_anchors(normal), band_anchors(final)
    if position:
        arab = position['current_quotes'].get('ArabUT')
        position['observations'] = []
        if arab:
            for band, quantity in ANCHORS.items():
                tier = next(row for row in final['tiers'] if row['purchase_k'] == quantity)
                own_rate = Decimal(final_prices[band]) * 100 / (Decimal(quantity) + Decimal(tier['promised_bonus_k']))
                difference = own_rate / Decimal(arab['usd_per_delivered_100k']) - 1
                if difference > Decimal('.10'):
                    position['observations'].append(dict(code='market_anchor_above_arabut', band=band,
                        difference_ratio=str(difference), observation_id=arab.get('observation_id')))
    if not insurance and any(Decimal(final_prices[band]) < Decimal(price) and band not in holds
                             for band, price in normal_prices.items()):
        frozen.update(status=FAILED, gaps=['curve_cost_protection_below_normal_candidate'])
        return
    segments = {band: dict(normal=normal_prices[band], target=final_prices[band])
                for band in segment_changes(normal, final)
                if not position or (Decimal(final_prices[band]) > Decimal(normal_prices[band])
                                    and (band in financial_bands or band in active))}
    if position and (position['floor_only'] or margin_band and not margin_band['decision_round']['is_decision_round']):
        for band, prior in active.items():
            if final_prices[band] == observed[band] == prior['target']:
                segments.setdefault(band, dict(prior))
    for band, count in release_rounds.items():
        if band in segments:
            segments[band]['release_rounds'] = count
    frozen.update(status=PROVEN, final_key=final_key, labels=candidate['labels'],
                  normal_anchors=normal_prices, final_anchors=final_prices, segments=segments,
                  normal_curve=normal, final_curve=final)


def _freeze_anchor_shadow(platform, entry, inputs_for, state, plan, evidence, now, previous):
    """A shadow owns its copies; its failures never authorize or replace the actual action."""
    from copy import deepcopy
    from .curve_strategy_v6 import MARKET_ANCHOR_VERSION

    record = dict(strategy_version=MARKET_ANCHOR_VERSION, plan_id=plan.get('plan_id'),
                  plan_revision=plan.get('revision'), snapshot_id=evidence.get('run_id'),
                  created_at=now.isoformat(), would_write=False, execution_authorized=False)
    try:
        shadow = deepcopy(entry)
        prospective = dict(plan, smart_strategy_version=MARKET_ANCHOR_VERSION)
        record['plan_binding'] = _curve_plan_binding(prospective)
        _freeze_cost_protection(platform, shadow, inputs_for, state, prospective, evidence, now, previous)
        result = _prove_temporary_curve(platform, shadow, shadow['primary_curve'], state, previous)
        record.update(status=result['status'], gaps=result.get('gaps') or [], selection=result.get('selection'),
                      proof=result.get('proof'), would_write=result['status'] == 'READY',
                      target_curve=result.get('target') if result['status'] == 'READY' else shadow['primary_curve'])
    except ValueError as error:
        record.update(status='PROOF_INCOMPLETE', gaps=[str(error)])
    except Exception as error:
        record.update(status='SHADOW_COMPUTATION_FAILED', gaps=[type(error).__name__])
    entry['anchor_shadow'] = record


def _freeze_intermediate_trial(platform, entry, inputs_for, state, plan, evidence, now):
    """Keep the first valid intermediate step for this round's selected band and direction."""
    from coin_all_sync_job import curve_route_ready, curve_writer_capabilities
    from .curve_strategy_v6 import INTERMEDIATE_TRIAL_STEPS, build_candidates, intermediate_candidates
    from .price_curve import curve_key
    from .pricing_proof_v6 import PROVEN

    current, editor, route = entry['primary_curve'], entry['editor_contract'], entry['native_route']
    if not route:
        return
    capability = curve_writer_capabilities({platform: route}).get(platform) or {}
    if not curve_route_ready(capability):
        return
    preferred = _curve_preference(platform, current, evidence, entry, now, plan=plan, state=state)
    label = preferred['label']
    if label not in ('B', 'C'):
        return
    factors_verified = capability.get('tier_price_factors') is True
    comparison = build_candidates(current, state['reference'], state['episode'], preferred['segment'],
                                  editor_contract=editor, check_saved_discount_terms=True,
                                  tier_price_factors_verified=factors_verified)
    for candidate in comparison['candidates']:
        if label not in candidate['labels']:
            continue
        key = candidate['curve_key']
        frozen = entry['primary_inputs'].get(key)
        if not frozen or _validated_curve(candidate['curve'], frozen)['status'] != PROVEN:
            continue
        if key == comparison['confirmed_current_curve_key']:
            return
        after = entry['all_targets'].get(key)
        all_frozen = entry['all_inputs'].get(curve_key(after)) if after else None
        if _writable_curve_trial(platform, entry, current, candidate, after, all_frozen, capability):
            return

    for candidate in intermediate_candidates(comparison, label, editor, tier_price_factors_verified=factors_verified,
                                             step_sizes=INTERMEDIATE_TRIAL_STEPS):
        key, curve = candidate['curve_key'], candidate['curve']
        if candidate['write_gaps']:
            continue
        frozen = entry['primary_inputs'].get(key) or inputs_for(curve)
        if _validated_curve(curve, frozen)['status'] != PROVEN:
            continue
        after = _all_curve_target(entry['all_before'], curve)
        all_key = curve_key(after)
        all_frozen = entry['all_inputs'].get(all_key) or inputs_for(after)
        if _writable_curve_trial(platform, entry, current, candidate, after, all_frozen, capability):
            entry['primary_inputs'][key] = frozen
            entry['all_targets'][key] = after
            entry['all_inputs'][all_key] = all_frozen
            entry['bounded_intermediate_trial'] = key
            return


def _writable_curve_trial(platform, inputs, current, candidate, after, all_frozen, capability):
    from coin_all_sync_job import curve_catalog_plan, editable
    from .pricing_proof_v6 import PROVEN

    if candidate['write_gaps'] or not after or not all_frozen:
        return False
    before, target = inputs['all_before'], candidate['curve']
    if ((before['tiers'], before['unit_price_usd_per_k']) != (current['tiers'], current['unit_price_usd_per_k'])
            or (after['tiers'], after['unit_price_usd_per_k']) != (target['tiers'], target['unit_price_usd_per_k'])):
        return False
    proof = _validated_curve(after, all_frozen)
    if proof['status'] != PROVEN:
        return False
    before_hash = fingerprint(editable(current['native_payload'])) if inputs.get('native_route') else None
    bundle = dict(before_action={'curves': {platform: before}}, action={'curves': {platform: after}},
                  curve_proofs={platform: proof}, curve_primary_before_hashes={platform: before_hash},
                  curve_price_insurance={platform: inputs.get('price_insurance', {})})
    try:
        curve_catalog_plan(bundle, platform, capability)
    except ValueError:
        return False
    return True


def store_curve_proof_inputs(db, evidence, platforms):
    """Persist one internal evidence attachment without replacing prior proof."""
    from .competitor_offers import POLICY as CURVE_COMPETITOR_POLICY

    if (evidence.get('competitor_policy') != CURVE_COMPETITOR_POLICY
            or not platforms or set(platforms) - set(PLATFORMS)):
        raise ValueError('pricing_curve_proof_input_scope_invalid')
    run_id = str(uuid.UUID(evidence['run_id']))
    key = 'curve-proof-inputs:' + run_id
    attachment = dict(run_id=run_id, collection_sha256=_curve_collection_fingerprint(evidence), platforms=platforms)
    with db.transaction() as conn:
        prior = db.get('metadata', key, conn)
        if prior is not None and prior != attachment:
            raise ValueError('pricing_curve_proof_input_conflict')
        return prior if prior is not None else db.put('metadata', key, attachment, conn)


def _curve_preference(platform, current, evidence, inputs, now, *, plan=None, state=None, paired_bands=True):
    from .curve_strategy_v6 import ANCHORS, MARKET_ANCHOR_VERSION, market_preference
    from .smart import assignment, curve_slot

    performance = inputs.get('performance') or {}
    smart = plan and plan['mode'] == 'smart'
    if smart and plan.get('smart_strategy_version') == MARKET_ANCHOR_VERSION:
        return dict(source='market_anchor', label='A', segment='both')
    if not (paired_bands and smart):
        preference = market_preference(current, platform, evidence.get('competitor_offers') or [], performance, now)
        if preference:
            return preference
    if inputs.get('preferred_label'):
        return dict(label=inputs['preferred_label'], segment=inputs['segment'], source='frozen_business_choice')
    if smart and paired_bands:
        slot = curve_slot(plan, platform, state, now, learning=inputs.get('learning'))
        preference = dict(label=slot['label'], segment=slot['segment'], source='smart_three_hour_block',
                          assignment=slot, block=slot['block'], starts_at=slot['starts_at'], ends_at=slot['ends_at'])
        policy, correction = slot['policy'] or {}, slot['correction'] or {}
        stops = {label for label, block in correction.get('effective_blocks', {}).items() if slot['block'] >= block}
        if slot['label'] != slot['original_label']:
            preference['source'] = 'observed_curve_correction'
        elif policy.get('winner') and policy['winner'] not in stops:
            preference['source'] = 'observed_curve_policy'
        elif slot['segment'] == 'small' and slot['label'] != 'A':
            market = market_preference(current, platform, evidence.get('competitor_offers') or [], performance, now)
            if market and market['label'] not in stops and market['label'] not in policy.get('excluded', []):
                preference.update(market, source='market_100k')
        learned = (inputs.get('learning') or {}).get(slot['segment']) or {}
        if slot['learning_source_sha256']:
            preference['observed_blocks'] = learned['blocks']
        return preference
    segment = max(ANCHORS, key=lambda value: (performance.get(value) or {}).get('current', {}).get('paid_orders', 0))
    if plan and plan['mode'] == 'revenue_sprint':
        return dict(label='B', segment=segment, source='revenue_sprint')
    if smart:
        episode = state['episode']
        starts_at = max(instant(plan['starts_at']), instant(episode['opened_at']))
        scoped = dict(plan, starts_at=starts_at.isoformat(), smart_strategy_version='smart-v1',
                      plan_id=plan['plan_id'] + ':curve-v6:' + platform + ':' + episode['comparison_episode_id'])
        slot = assignment(scoped, now)
        return dict(label=slot['label'], segment=segment, source='smart_three_hour_block',
                    block=slot['block'], starts_at=slot['starts_at'], ends_at=slot['ends_at'])
    return dict(label='CURRENT', segment=segment)


def _curve_assignment_result(preference, primary, key, labels):
    from .curve_strategy_v6 import comparison_background_key
    from .price_curve import curve_key

    if not preference.get('assignment'):
        return preference
    requested = preference['label']
    actual = 'A' if 'A' in labels else requested if requested in labels else 'CURRENT'
    info = dict(preference['assignment'], requested_label=requested, actual_label=actual,
                primary_curve_key=curve_key(primary),
                decision_curve_key=key,
                learning_background_curve_key=preference['assignment']['background_curve_key'],
                background_curve_key=comparison_background_key(primary, preference['segment']))
    return dict(preference, assignment=info)


def _validated_curve(curve, frozen):
    from .pricing_proof_v6 import validate_curve

    return validate_curve(curve, frozen['baskets'], frozen['evidence'], frozen['domain'])


def _average_discount_repair(current, all_before, editor, current_proof, inputs_for):
    from .average_discount_v6 import CENT, quantity_group, repair_controls
    from .curve_strategy_v6 import minimum_repair
    from .price_curve import TWO_BAND_PRICE_EDIT, compile_curve
    from .pricing_proof_v6 import FAILED, PROVEN

    floors, affected = repair_controls(current, current_proof)
    if not floors:
        return None
    source = current['tiers']

    def try_controls(floors, segments, extra_cents):
        # Native forward editing requires explicit restoration of an unaffected tail.
        preserved = {}
        if editor.get('price_edit_policy') != TWO_BAND_PRICE_EDIT:
            preserved = {row['purchase_k']: row['native_price_usd'] for row in source
                         if Decimal(row['purchase_k']) > min(map(Decimal, floors))
                         and quantity_group(Decimal(row['purchase_k'])) not in segments}
        anchors = {key: price + extra_cents * CENT for key, price in floors.items()}
        choices = dict(anchor_prices_usd={**preserved, **{q: str(value) for q, value in anchors.items()}})
        target = compile_curve(current, choices, editor)
        if target['compilation_status'] != 'EDITOR_CANDIDATE':
            return None
        all_target = _all_curve_target(all_before, target)
        frozen, all_frozen = inputs_for(target), inputs_for(all_target)
        if (_validated_curve(target, frozen)['status'] != PROVEN
                or _validated_curve(all_target, all_frozen)['status'] != PROVEN):
            return None
        return dict(curve=target, all_target=all_target, inputs=frozen, all_inputs=all_frozen)

    mandatory = {quantity_group(Decimal(row['purchase_k'])) for row in current_proof['paths']
                 if row['zero_line_status'] == FAILED}
    options = [(floors, affected)]
    if len(affected) > 1 and not mandatory:
        # A weighted shortfall may be repaired in one segment. Evaluate those
        # native alternatives alongside the shared increase under both baskets.
        options.extend(repair_controls(current, current_proof, affected={segment}) for segment in sorted(affected))
    proven = []
    for controls, segments in options:
        # A few adjacent cent amounts cover native and net-receipt rounding.
        for extra in range(4):
            candidate = try_controls(controls, segments, extra)
            if candidate and minimum_repair(current, [candidate], segments):
                proven.append(candidate)
                break
    selected = minimum_repair(current, proven, affected)
    if not selected:
        return None
    source_ref = fingerprint(dict(proof=current_proof['proof_hash'], floors={q:str(v) for q,v in floors.items()}))
    return dict(current_proof_hash=current_proof['proof_hash'], domain_status='complete', domain_ref=source_ref,
                repair_search='average_model_cent_floor_and_native_rounding',
                affected_segments=sorted(affected), candidates=[selected])


def _curve_repair(current, current_proof, repair):
    from .curve_strategy_v6 import minimum_repair
    from .price_curve import curve_key
    from .pricing_proof_v6 import FAILED, PROVEN

    if not repair or repair.get('current_proof_hash') != current_proof['proof_hash']:
        return dict(status='HARD_CONSTRAINT_FAILED', gaps=current_proof['hard_failures'])
    if repair.get('domain_status') != 'complete' or not repair.get('domain_ref'):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_native_repair_domain_incomplete'])
    affected = repair.get('affected_segments') or []
    if not affected or set(affected) - {'small','large'}:
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_repair_affected_segment_unverified'])
    proven = []
    for row in repair['candidates']:
        proof = _validated_curve(row['curve'], row['inputs'])
        if proof['status'] not in (PROVEN, FAILED):
            return dict(status='PROOF_INCOMPLETE', gaps=['curve_repair_candidate_proof_incomplete'])
        if proof['status'] == FAILED:
            continue
        all_curve, all_input = row.get('all_target'), row.get('all_inputs')
        if (not all_curve or not all_input or all_input['evidence'].get('curve_key') != curve_key(all_curve)
                or (all_curve['tiers'], all_curve['unit_price_usd_per_k']) !=
                   (row['curve']['tiers'], row['curve']['unit_price_usd_per_k'])):
            return dict(status='PROOF_INCOMPLETE', gaps=['curve_repair_candidate_all_proof_unavailable'])
        all_proof = _validated_curve(all_curve, all_input)
        if all_proof['status'] not in (PROVEN, FAILED):
            return dict(status='PROOF_INCOMPLETE', gaps=['curve_repair_candidate_all_proof_incomplete'])
        if all_proof['status'] == PROVEN:
            proven.append(dict(row, proof=all_proof))
    target = minimum_repair(current, proven, affected)
    if not target:
        return dict(status='NO_FEASIBLE_CURVE', gaps=current_proof['hard_failures'])
    return dict(status='COST_REPAIR', candidate=target)


def _prove_curve_inputs(platform, inputs, db, now, conn=None, *, evidence=None, plan=None, decision_at=None,
                        paired_bands=True, temporary_protection=True):
    from coin_all_sync_job import curve_catalog_plan, curve_route_ready, curve_writer_capabilities, editable
    from .curve_strategy_v6 import (INTERMEDIATE_TRIAL_STEPS, MARKET_ANCHOR_VERSION, build_candidates, choose_action,
                                    intermediate_candidates, primary_reference_curve)
    from .price_curve import curve_key
    from .pricing_proof_v6 import FAILED, PROVEN

    state = db.curve_strategy_state(platform, conn)
    if not inputs or not instant(inputs['captured_at']) <= now < instant(inputs['valid_until']):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_reference_or_fresh_execution_inputs_unavailable'])
    if (plan and (inputs.get('plan_binding') or plan.get('smart_strategy_version') == MARKET_ANCHOR_VERSION)
            and inputs.get('plan_binding') != _curve_plan_binding(plan)):
        return dict(status='PROOF_INCOMPLETE', gaps=['pricing_curve_strategy_revision_changed'])
    if temporary_protection and _margin_band_discount_refresh(now):
        preference = (inputs.get('temporary_cost_protection') or {}).get('preference') or {}
        audit = preference.get('margin_band') or {}
        if (audit.get('decision_round') or {}).get('is_decision_round'):
            return dict(status='PROOF_INCOMPLETE', gaps=['curve_margin_band_discount_refresh'])
    if not state:
        from .average_discount_v6 import MODEL
        if inputs.get('pricing_assumption') == MODEL:
            current = inputs['primary_curve']
            key = curve_key(current)
            frozen = (inputs.get('primary_inputs') or {}).get(key)
            if frozen:
                proof = _validated_curve(current, frozen)
                return dict(status='KEEP' if proof['status'] == PROVEN else proof['status'],
                            current_key=key, proof=proof, gaps=proof['gaps'] + proof['hard_failures'])
        return dict(status='PROOF_INCOMPLETE', gaps=['adopted_reference_curve_unavailable'])
    current = primary_reference_curve(inputs['primary_curve'], platform)
    if temporary_protection and 'temporary_cost_protection' in inputs:
        return _prove_temporary_curve(platform, inputs, current, state, db.curve_cost_protection(platform, conn))
    preference = _curve_preference(platform, current, evidence or {}, inputs, decision_at or now,
                                   plan=plan, state=state, paired_bands=paired_bands)
    route = inputs.get('native_route')
    capability = (curve_writer_capabilities({platform: route}) if route else curve_writer_capabilities()).get(platform) or {}
    factors_verified = curve_route_ready(capability) and capability.get('tier_price_factors') is True
    comparison = build_candidates(current, state['reference'], state['episode'], preference['segment'],
                                  editor_contract=inputs.get('editor_contract'), check_saved_discount_terms=True,
                                  tier_price_factors_verified=factors_verified)
    proofs = {}
    for row in comparison['candidates']:
        key = row['curve_key']
        frozen = inputs.get('primary_inputs', {}).get(key)
        if frozen:
            proofs[key] = _validated_curve(row['curve'], frozen)
    current_proof = proofs.get(comparison['confirmed_current_curve_key']) or {}
    if current_proof.get('status') not in (PROVEN, FAILED):
        return dict(status='PROOF_INCOMPLETE', gaps=current_proof.get('gaps') or ['curve_current_proof_unavailable'],
                    selection=preference)
    repair = current_proof.get('status') == FAILED
    repair_target = None
    if repair:
        solution = _curve_repair(current, current_proof, inputs.get('repair'))
        if solution['status'] != 'COST_REPAIR':
            return solution
        repair_target = solution['candidate']
        target = dict(curve=repair_target['curve'], curve_key=curve_key(repair_target['curve']))
        gaps = []
    else:
        decision = choose_action(comparison, proofs, preferred_label=preference['label'])
        target, gaps = decision['selected'], decision['gaps']
        outer_keys = {row['curve_key'] for row in comparison['candidates']}
        available_steps = set(inputs.get('all_targets') or {}) - outer_keys
        bounded = inputs.get('bounded_intermediate_trial')
        search_intermediate = not target
        if bounded and target and target['curve_key'] != comparison['confirmed_current_curve_key']:
            outer = (inputs.get('all_targets') or {}).get(target['curve_key'])
            outer_proof = (inputs.get('all_inputs') or {}).get(curve_key(outer)) if outer else None
            search_intermediate = not _writable_curve_trial(platform, inputs, current, target, outer,
                                                            outer_proof, capability)
        if search_intermediate and preference['label'] in ('B', 'C') and available_steps:
            step_sizes = INTERMEDIATE_TRIAL_STEPS if bounded else None
            for candidate in intermediate_candidates(comparison, preference['label'],
                                                      inputs.get('editor_contract') or current['native_contract'],
                                                      tier_price_factors_verified=factors_verified, step_sizes=step_sizes):
                key = candidate['curve_key']
                if key not in available_steps:
                    continue
                frozen = inputs['primary_inputs'].get(key)
                after = (inputs.get('all_targets') or {}).get(key)
                all_frozen = (inputs.get('all_inputs') or {}).get(curve_key(after)) if after else None
                if (frozen and all_frozen and _validated_curve(candidate['curve'], frozen)['status'] == PROVEN
                        and _validated_curve(after, all_frozen)['status'] == PROVEN):
                    target, gaps = candidate, candidate['write_gaps']
                    preference = dict(preference, price_step='bounded_intermediate')
                    break
        if not target and preference['label'] in ('A', 'B', 'C') and current_proof.get('status') == PROVEN:
            preference = _curve_assignment_result(preference, current, comparison['confirmed_current_curve_key'], [])
            return dict(status='KEEP', current_key=comparison['confirmed_current_curve_key'], proof=current_proof,
                        selection=preference, gaps=gaps)
        if not target:
            return dict(status=decision['status'], gaps=gaps)
    if target['curve_key'] == comparison['confirmed_current_curve_key']:
        preference = _curve_assignment_result(preference, current, target['curve_key'], target['labels'])
        return dict(status='KEEP', current_key=target['curve_key'], proof=proofs[target['curve_key']], selection=preference)
    if not curve_route_ready(capability):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_native_writer_capability_unverified'])
    if gaps:
        return dict(status='PROOF_INCOMPLETE', gaps=gaps)
    before = inputs.get('all_before')
    after = repair_target.get('all_target') if repair else (inputs.get('all_targets') or {}).get(target['curve_key'])
    if not before or not after:
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_target_all_readback_unavailable'])
    if (before['tiers'], before['unit_price_usd_per_k']) != (current['tiers'], current['unit_price_usd_per_k']):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_current_all_primary_mismatch'])
    if (after['tiers'], after['unit_price_usd_per_k']) != (target['curve']['tiers'], target['curve']['unit_price_usd_per_k']):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_target_all_primary_mismatch'])
    if repair:
        proof = repair_target['proof']
    else:
        frozen = (inputs.get('all_inputs') or {}).get(curve_key(after))
        if not frozen:
            return dict(status='PROOF_INCOMPLETE', gaps=['curve_target_all_proof_unavailable'])
        proof = _validated_curve(after, frozen)
    if proof['status'] != PROVEN:
        return dict(status=proof['status'], gaps=proof['gaps'] + proof['hard_failures'])
    before_hash = fingerprint(editable(current['native_payload'])) if route else None
    bundle = dict(before_action={'curves': {platform: before}}, action={'curves': {platform: after}},
                  curve_proofs={platform: proof}, curve_primary_before_hashes={platform: before_hash},
                  curve_price_insurance={platform: inputs.get('price_insurance', {})})
    try:
        curve_catalog_plan(bundle, platform, capability)
    except ValueError as error:
        return dict(status='PROOF_INCOMPLETE', gaps=[str(error)])
    if repair:
        preference = dict({} if paired_bands else preference,
                          label='COST_REPAIR', failed_proof_hash=current_proof['proof_hash'],
                          repair_domain_ref=inputs['repair']['domain_ref'],
                          reference_curve_id=state['reference']['reference_curve_id'],
                          comparison_episode_id=state['episode']['comparison_episode_id'])
    else:
        preference = _curve_assignment_result(preference, target['curve'], curve_key(after), target['labels'])
    return dict(status='READY', before=before, target=after, proof=proof,
                selection=preference, native_route=route, primary_before_hash=before_hash)


def _prove_temporary_curve(platform, inputs, current, state, previous):
    from coin_all_sync_job import curve_catalog_plan, curve_route_ready, curve_writer_capabilities, editable
    from .curve_strategy_v6 import band_anchors, large_market_comparison, segment_terms
    from .price_curve import curve_key
    from .pricing_proof_v6 import PROVEN

    frozen = inputs['temporary_cost_protection']
    if (frozen['reference_curve_id'] != state['reference']['reference_curve_id']
            or frozen['comparison_episode_id'] != state['episode']['comparison_episode_id']
            or frozen['previous'] != previous):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_cost_protection_state_changed'])
    if frozen['status'] != PROVEN:
        return dict(status=frozen['status'], gaps=frozen['gaps'], selection=frozen['preference'])
    key = frozen['final_key']
    normal, final = frozen['normal_curve'], frozen['final_curve']
    normal_anchors, final_anchors = frozen['normal_anchors'], frozen['final_anchors']
    active = frozen['segments']
    protection = dict(segments=active, status='active' if active else 'released' if previous.get('segments') else 'none')
    selection = dict(frozen['preference'], reference_curve_id=frozen['reference_curve_id'],
                     comparison_episode_id=frozen['comparison_episode_id'],
                     reference_anchors=band_anchors(state['reference']['reference_curve']),
                     normal_anchors=normal_anchors, final_anchors=final_anchors,
                     cost_protection=protection,
                     cost_stability=frozen.get('stability', {}),
                     large_market_reference=large_market_comparison(frozen.get('market_reference', []), normal, final))
    if 'price_insurance' in inputs:
        selection.update(price_insurance=frozen.get('price_insurance'),
                         cost_sample_insurance=inputs.get('cost_sample_insurance'),
                         confirmed_cost_cny_per_k=inputs.get('confirmed_cost_cny_per_k'))
    # The pairing code checks the other band's exact confirmed tiers for both arms.
    small_unchanged = (selection['segment'] == 'small' and active.keys() == {'large'}
                       and segment_terms(normal, 'small') == segment_terms(final, 'small'))
    labels = frozen['labels'] if small_unchanged or not (active or selection.get('restore_other_band')) else []
    if key == curve_key(current):
        return dict(status='KEEP', current_key=key, proof=_validated_curve(current, inputs['primary_inputs'][key]),
                    selection=_curve_assignment_result(selection, current, key, labels), gaps=frozen['gaps'])
    route = inputs.get('native_route')
    capability = (curve_writer_capabilities({platform: route}) if route else curve_writer_capabilities()).get(platform) or {}
    if not curve_route_ready(capability):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_native_writer_capability_unverified'], selection=selection)
    before, after = inputs['all_before'], inputs['all_targets'][key]
    if (before['tiers'], before['unit_price_usd_per_k']) != (current['tiers'], current['unit_price_usd_per_k']):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_current_all_primary_mismatch'], selection=selection)
    if (after['tiers'], after['unit_price_usd_per_k']) != (final['tiers'], final['unit_price_usd_per_k']):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_target_all_primary_mismatch'], selection=selection)
    proof = _validated_curve(after, inputs['all_inputs'][curve_key(after)])
    if proof['status'] != PROVEN:
        return dict(status=proof['status'], gaps=proof['gaps'] + proof['hard_failures'], selection=selection)
    before_hash = fingerprint(editable(current['native_payload'])) if route else None
    try:
        curve_catalog_plan(dict(before_action={'curves': {platform: before}}, action={'curves': {platform: after}},
                                curve_proofs={platform: proof}, curve_primary_before_hashes={platform: before_hash},
                                curve_price_insurance={platform: inputs.get('price_insurance', {})}),
                           platform, capability)
    except ValueError as error:
        return dict(status='PROOF_INCOMPLETE', gaps=[str(error)], selection=selection)
    selection = _curve_assignment_result(selection, final, curve_key(after), labels)
    return dict(status='READY', before=before, target=after, proof=proof, selection=selection,
                native_route=route, primary_before_hash=before_hash)


def _automatic_curve_adoption(db, platform, inputs, decision, operation_id, *, conn=None):
    from .curve_strategy_v6 import primary_reference_curve, propose_adoption
    from .price_curve import curve_key

    selection = decision.get('selection') or {}
    assignment = selection.get('assignment') or {}
    protection = selection.get('cost_protection') or {}
    segment, label = selection.get('segment'), selection.get('label')
    learned = (inputs.get('learning') or {}).get(segment) or {}
    evidence = learned.get('adoption')
    if (not evidence or label not in ('B', 'C') or assignment.get('actual_label') != label
            or (assignment.get('policy') or {}).get('winner') != label or protection.get('segments')
            or not operation_id):
        return None
    state = db.curve_strategy_state(platform, conn)
    current = inputs['primary_curve']
    target = primary_reference_curve(current, platform)
    key = curve_key(target)
    if decision['status'] == 'KEEP':
        original = db.get('operations', operation_id, conn)
        original_selection = ((original or {}).get('bundle', {}).get('curve_selection') or {}).get(platform, {})
        if (not original or original_selection.get('label') == 'COST_REPAIR'
                or (original_selection.get('cost_protection') or {}).get('segments')):
            return None
        proof = (inputs.get('primary_inputs') or {}).get(key)
        if not proof:
            return None
        proof = _validated_curve(current, proof)
    else:
        primary = inputs['temporary_cost_protection']['final_curve']
        target, key = primary, curve_key(primary)
        proof = _validated_curve(primary, inputs['primary_inputs'][key])
    if key != evidence.get('winning_curve_key'):
        return None
    candidate = dict(curve=target, curve_key=key)
    reference = state['reference']
    comparison = dict(state['episode'], candidates=[candidate], selected_segment=segment)
    choice = dict(status='KEEP', selected=candidate, proof_hash=proof['proof_hash'],
                  reference_curve_id=reference['reference_curve_id'],
                  comparison_episode_id=comparison['comparison_episode_id'])
    try:
        proposal = propose_adoption(reference, comparison, choice, evidence, operation_id=operation_id)
    except ValueError:
        return None
    return dict(platform=platform, proposal=proposal, proof=proof)


def _prove_curve_restore(platform, inputs, original, source_id, now):
    from coin_all_sync_job import curve_catalog_plan, curve_writer_capabilities, editable
    from .price_curve import curve_key
    from .pricing_proof_v6 import PROVEN

    if not inputs or not instant(inputs['captured_at']) <= now < instant(inputs['valid_until']):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_restore_fresh_inputs_unavailable'])
    current, before = inputs['primary_curve'], inputs['all_before']
    if (before['tiers'], before['unit_price_usd_per_k']) != (current['tiers'], current['unit_price_usd_per_k']):
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_current_all_primary_mismatch'])
    try:
        after = _curve_restore_target(before, original)
    except ValueError as error:
        return dict(status='PROOF_INCOMPLETE', gaps=[str(error)])
    key = curve_key(after)
    frozen = inputs['all_inputs'].get(key)
    if not frozen:
        return dict(status='PROOF_INCOMPLETE', gaps=['curve_target_all_proof_unavailable'])
    proof = _validated_curve(after, frozen)
    if proof['status'] != PROVEN:
        return dict(status=proof['status'], gaps=proof['gaps'] + proof['hard_failures'])
    if key == curve_key(before):
        return dict(status='KEEP')
    route = inputs.get('native_route')
    capability = (curve_writer_capabilities({platform: route}) if route else curve_writer_capabilities()).get(platform)
    before_hash = fingerprint(editable(current['native_payload'])) if route else None
    selection = dict(label='RESTORE')
    bundle = dict(before_action={'curves': {platform: before}}, action={'curves': {platform: after}},
                  curve_proofs={platform: proof}, curve_primary_before_hashes={platform: before_hash},
                  curve_price_insurance={platform: inputs.get('price_insurance', {})},
                  restore_source_execution_id=source_id)
    try:
        curve_catalog_plan(bundle, platform, capability)
    except ValueError as error:
        return dict(status='PROOF_INCOMPLETE', gaps=[str(error)])
    return dict(status='READY', before=before, target=after, proof=proof,
                selection=selection, native_route=route, primary_before_hash=before_hash)


def revise_curve_strategy(db, ident, expected_revision, actor, snapshot_id, strategy_version, parameters, **changes):
    """Revise bounded plan parameters; initial adoption requires a matching live shadow."""
    from .competitor_offers import POLICY
    from .curve_strategy_v6 import MARKET_ANCHOR_VERSION, margin_band_parameters, market_anchor_parameters
    from .price_curve import curve_key

    parameters = market_anchor_parameters(parameters)
    if 'margin_band' in changes:
        changes['margin_band'] = margin_band_parameters(changes['margin_band'], parameters)
    revision = dict(strategy_version=strategy_version, market_anchor=parameters, **changes)

    def check(conn, plan, now):
        prospective_parameters = dict(plan.get('parameters') or {}, market_anchor=parameters, **changes)
        prospective = dict(plan, smart_strategy_version=strategy_version, parameters=prospective_parameters)
        binding = _curve_plan_binding(prospective)
        proofs = {}
        if strategy_version == MARKET_ANCHOR_VERSION and plan.get('smart_strategy_version') != MARKET_ANCHOR_VERSION:
            snapshot = db.get('pricing_snapshots', snapshot_id, conn) or {}
            evidence = snapshot.get('evidence') or {}
            if (snapshot.get('write_protocol') != CURVE_WRITE_PROTOCOL or snapshot.get('origin') != 'live_collector'
                    or snapshot.get('mode') != 'production' or evidence.get('run_id') != snapshot_id
                    or evidence.get('competitor_policy') != POLICY
                    or not now - timedelta(minutes=15) <= instant(snapshot.get('created_at')) <= now):
                raise ValueError('pricing_curve_market_anchor_shadow_unverified')
            inputs = _curve_proof_inputs(db, evidence, conn)
            platforms = [p for p in PLATFORMS if 'base:' + p in plan['resources']]
            control = db.price_control(conn)
            if not platforms or control['manual_enabled'] or control['uplift_enabled']:
                raise ValueError('pricing_curve_market_anchor_shadow_unverified')
            for platform in platforms:
                data = inputs.get(platform) or {}
                shadow = data.get('anchor_shadow') or {}
                proof = shadow.get('proof') or {}
                target = shadow.get('target_curve')
                if (data.get('plan_binding') != _curve_plan_binding(plan) or shadow.get('plan_binding') != binding
                        or (shadow.get('plan_id'), shadow.get('plan_revision'), shadow.get('snapshot_id')) !=
                           (ident, expected_revision, snapshot_id)
                        or shadow.get('status') not in ('READY', 'KEEP') or shadow.get('execution_authorized') is not False
                        or proof.get('status') != 'PROVEN' or not proof.get('paths') or not target
                        or proof.get('curve_key') != curve_key(target)
                        or proof.get('proof_hash') != fingerprint({k:v for k,v in proof.items() if k != 'proof_hash'})
                        or any(row.get('zero_line_status') != 'PROVEN' for row in proof['paths'])):
                    raise ValueError('pricing_curve_market_anchor_shadow_unverified')
                proofs[platform] = proof['proof_hash']
        return dict(strategy_version=strategy_version, parameters_sha256=binding['parameters_sha256'], shadow_proofs=proofs)
    return db.activate_curve_plan(ident, expected_revision, actor, snapshot_id, check, strategy_revision=revision)


def activate_curve_plan(db, ident, expected_revision, actor, snapshot_id):
    from coin_all_sync_job import curve_route_ready, curve_writer_capabilities
    from .competitor_offers import POLICY as CURVE_COMPETITOR_POLICY
    from .pricing_proof_v6 import CONTRACT

    def check(conn, plan, now):
        snapshot = db.get('pricing_snapshots', snapshot_id, conn) or {}
        evidence = snapshot.get('evidence') or {}
        if (snapshot.get('write_protocol') != CURVE_WRITE_PROTOCOL or snapshot.get('origin') != 'live_collector'
                or snapshot.get('mode') != 'production' or evidence.get('run_id') != snapshot_id
                or evidence.get('competitor_policy') != CURVE_COMPETITOR_POLICY
                or not now - timedelta(minutes=15) <= instant(snapshot['created_at']) <= now):
            raise ValueError('pricing_curve_activation_snapshot_unverified')
        inputs = _curve_proof_inputs(db, evidence, conn)
        platforms = [p for p in PLATFORMS if 'base:' + p in plan['resources']]
        if not platforms:
            raise ValueError('pricing_curve_activation_scope_invalid')
        routes = {p: inputs[p]['native_route'] for p in platforms if (inputs.get(p) or {}).get('native_route')}
        capabilities = curve_writer_capabilities(routes) if routes else curve_writer_capabilities()
        if any(not curve_route_ready(capabilities.get(p) or {}) for p in platforms):
            raise ValueError('pricing_curve_activation_proof_incomplete')
        control = db.price_control(conn)
        if control['manual_enabled'] or control['uplift_enabled']:
            raise ValueError('pricing_curve_activation_price_control_conflict')
        for platform in platforms:
            data = inputs.get(platform) or {}
            readbacks = data.get('readbacks') or []
            if not db.curve_strategy_state(platform, conn) and data.get('primary_curve') and readbacks:
                if data.get('preferred_label', 'CURRENT') != 'CURRENT':
                    raise ValueError('pricing_curve_initial_reference_requires_current')
                db.start_curve_episode(platform, CONTRACT, 'Initial adopted curve from current Admin Goods readback',
                                       initial_curve=data['primary_curve'],
                                       readback_ref='curve-proof-inputs:' + snapshot_id + ':' + fingerprint(readbacks),
                                       db=conn)
        proof = {p: _prove_curve_inputs(p, inputs.get(p), db, now, conn, evidence=evidence) for p in platforms}
        if any(value['status'] not in ('KEEP', 'READY') for value in proof.values()):
            raise ValueError('pricing_curve_activation_proof_incomplete')
        return {p: value['proof']['proof_hash'] for p, value in proof.items()}

    return db.activate_curve_plan(ident, expected_revision, actor, snapshot_id, check)


def calculate_curve_cycle(db, evidence, plan, request, now):
    from .pricing_proof_v6 import CONTRACT, FAILED

    active = bool(request.get('v3_operation_id') and plan and plan.get('write_protocol') == CURVE_WRITE_PROTOCOL
                  and plan['state'] == 'ACTIVE')
    platforms = ([p for p in PLATFORMS if 'base:' + p in plan['resources']] if active else list(PLATFORMS))
    control = db.price_control()
    frozen = {} if control['manual_enabled'] or control['uplift_enabled'] else _curve_proof_inputs(db, evidence)
    restore_id = request.get('curve_restore_preview_id')
    if restore_id:
        if not active or not request.get('manual_requested'):
            raise ValueError('pricing_curve_restore_preview_invalid')
        restore_intent, restore = _curve_restore_intent(db, plan, restore_id, request['v3_operation_id'], now)
        platforms = list(restore)
        decisions = {p: _prove_curve_restore(p, frozen.get(p), restore[p],
                                             restore_intent['restore_source_execution_id'], now) for p in platforms}
    else:
        decisions = {p: _prove_curve_inputs(p, frozen.get(p), db, now, evidence=evidence,
                                           plan=plan if active else None) for p in platforms}
    configuration = (plan.get('parameters') or {}).get('margin_band') if active and not restore_id else None
    if configuration:
        from .curve_strategy_v6 import ANCHORS

        missing = {}
        for platform in platforms:
            selected = decisions[platform].get('selection') or {}
            audit = selected.get('margin_band')
            if not audit:
                data = frozen.get(platform) or {}
                audit = (((data.get('temporary_cost_protection') or {}).get('preference') or {}).get('margin_band'))
                if 'curve_margin_band_discount_refresh' in decisions[platform].get('gaps', ()):
                    audit = None
            if audit:
                decisions[platform]['selection'] = dict(selected, margin_band=audit)
            else:
                missing[platform] = selected
        if missing:
            history = _margin_band_history(db, plan['plan_id'])
            path = ROOT / 'jobs' / (evidence['run_id'] + '.json')
            job = json.loads(path.read_text()) if path.exists() else dict(request=request)
            cycle = _margin_band_cycle_context(db, plan, job, now, configuration['schedule_hours'])
            at = cycle.pop('at')
            for platform, selected in missing.items():
                decision = margin_band_round(at, configuration['schedule_hours'], history[platform],
                                             evaluated_at=now, **cycle)
                audit = margin_band_selection(None, {'anchors': {}}, dict.fromkeys(ANCHORS),
                    Decimal(configuration[platform]['target']), decision, cost_median=None, cost_sample_count=None,
                    previous_decision_cost_median=None)
                decisions[platform]['selection'] = dict(selected, margin_band=audit)
    ready = [p for p in platforms if decisions[p]['status'] == 'READY']
    if restore_id and any(decisions[p]['status'] not in ('READY', 'KEEP') for p in platforms):
        ready = []
    rows = [dict(platform=p, status=decisions[p]['status'], gaps=decisions[p].get('gaps', []),
                 selection=decisions[p].get('selection')) for p in platforms]
    if active:
        for row in rows:
            for code in row['gaps']:
                if code in ('pricing_curve_daily_move_exceeded', 'pricing_curve_out_of_market_range',
                            'pricing_curve_margin_exception_exhausted', 'curve_cost_sample_outlier'):
                    db.incident(code, 'curve_price_insurance', [row['platform']])
    status = ('READY' if active and ready else 'NO_PRICE_CHANGE'
              if all(decisions[p]['status'] == 'KEEP' for p in platforms) else 'PROOF_INCOMPLETE')
    if not ready and any(decisions[p]['status'] == FAILED for p in platforms):
        status = FAILED
    if not active and all(decisions[p]['status'] in ('KEEP', 'READY') for p in platforms):
        status = 'CURVE_CANDIDATE_PROVEN'
    result = dict(status=status, rows=rows, strategy_version=VERSION,
                  financial_contract_version=CONTRACT, execution_authorized=status == 'READY',
                  anchor_shadow={p: frozen[p]['anchor_shadow'] for p in platforms
                                 if frozen.get(p) and frozen[p].get('anchor_shadow')})
    if configuration:
        result['curve_selection'] = {row['platform']: row['selection'] for row in rows}
    if active and status != 'READY':
        states = {decisions[p]['status'] for p in platforms}
        if states & {'PREFERRED_HARD_CONSTRAINT_FAILED', 'HARD_CONSTRAINT_FAILED'}:
            result['status'] = 'HARD_CONSTRAINT_FAILED'
        elif 'NO_FEASIBLE_CURVE' in states:
            result['status'] = 'NO_FEASIBLE_CURVE'
    if status == 'READY':
        resources = ['base:' + p for p in ready]
        deadline = [instant(plan['ends_at'])] if plan.get('ends_at') else []
        if restore_id:
            deadline.append(instant(restore_intent['valid_until']))
        valid_until = min([now + timedelta(minutes=15)] + [instant(frozen[p]['valid_until']) for p in ready] + deadline)
        receipt = dict(schema_version=VERSION, write_protocol=CURVE_WRITE_PROTOCOL,
            decision_bundle_id=request['v3_operation_id'], snapshot_id=evidence['run_id'],
            snapshot_sha256=fingerprint(evidence), created_at=now.isoformat(), valid_until=valid_until.isoformat(),
            plan_id=plan['plan_id'], revision=plan['revision'], engine_generation=plan['generation'],
            activation_revision=plan['activation_revision'], financial_contract_version=CONTRACT,
            assignment_id=request['v3_operation_id'], randomization_verified=False,
            curve_decision_policy=CURVE_PROTECTION_POLICY if any('temporary_cost_protection' in frozen[p] for p in ready)
            else CURVE_DECISION_POLICY,
            resources=resources, mutable_resources=resources, affected_platforms=ready,
            steps=[dict(step_id='base:all', kind='base', state='PENDING')],
            before_action=dict(curves={p: decisions[p]['before'] for p in ready}),
            action=dict(curves={p: decisions[p]['target'] for p in ready}),
            curve_proofs={p: decisions[p]['proof'] for p in ready}, price_control=control,
            curve_price_insurance={p: frozen[p].get('price_insurance', {}) for p in ready},
            curve_selection={p: decisions[p]['selection'] for p in ready},
            curve_native_routes={p: decisions[p]['native_route'] for p in ready if decisions[p]['native_route']},
            curve_primary_before_hashes={p: decisions[p]['primary_before_hash'] for p in ready
                                         if decisions[p]['primary_before_hash']},
            execution_authorized=True)
        if not restore_id and not request.get('manual_requested') and receipt['curve_decision_policy'] == CURVE_PROTECTION_POLICY:
            adoption = next((value for p in ready if 'temporary_cost_protection' in frozen[p]
                             if (value := _automatic_curve_adoption(db, p, frozen[p], decisions[p], request['v3_operation_id']))), None)
            if adoption:
                receipt['curve_adoption'] = adoption
        if restore_id:
            receipt.update(curve_restore_preview_id=restore_id,
                           restore_source_execution_id=restore_intent['restore_source_execution_id'],
                           curve_decision_policy='v6_restore_original_price_table')
        receipt['sha256'] = fingerprint(receipt)
        result['decision_receipt'] = receipt
    snapshot = dict(snapshot_id=evidence['run_id'], origin='live_collector', mode='production',
                    plan_id=plan['plan_id'] if active else None, plan_revision=plan['revision'] if active else None,
                    write_protocol=CURVE_WRITE_PROTOCOL, created_at=now.isoformat(), evidence=evidence, result=result)
    if restore_id:
        snapshot['curve_restore_preview_id'] = restore_id
    with db.transaction() as conn:
        db.put('pricing_snapshots', evidence['run_id'], snapshot, conn)
        decision_record = dict(curve=rows, created_at=now.isoformat(), anchor_shadow=result['anchor_shadow'],
            automatic_curve_round=bool(active and not restore_id and not request.get('manual_requested')),
            curve_round_id=request.get('v3_operation_id'))
        if configuration:
            decision_record.update(margin_band_plan_id=plan['plan_id'], curve_selection=result['curve_selection'])
        db.put('strategy_decisions', evidence['run_id'], decision_record, conn)
        if active and not restore_id:
            for platform, decision in decisions.items():
                if decision['status'] != 'KEEP':
                    continue
                data = frozen[platform]
                observed = data.get('readbacks') or []
                curve = data['primary_curve']
                goods_path = '/admin/goods.Goods/edit?id=' + curve['identity']['id']
                primary_readback = next((row for row in observed if row.get('path') == goods_path
                                         and row.get('http_status') == 200 and row.get('response_code') == 1
                                         and row.get('response_sha256')), None)
                if primary_readback:
                    db.observe_curve_keep(plan, evidence['run_id'], platform, curve,
                                          primary_readback.get('received_at') or data['captured_at'],
                                          'curve-proof-inputs:' + evidence['run_id'] + ':' + fingerprint(observed), conn,
                                          selection=decision.get('selection'))
            db.put('metadata', 'latest_snapshot:' + plan['plan_id'],
                   dict(snapshot_id=evidence['run_id'], plan_id=plan['plan_id']), conn)
    if active and not restore_id and not request.get('manual_requested'):
        for platform in platforms:
            decision = decisions[platform]
            data = frozen.get(platform) or {}
            if decision['status'] != 'KEEP' or 'temporary_cost_protection' not in data:
                continue
            curve = data['primary_curve']
            original = db.current_curve_operation(platform, plan, decision['current_key'])
            adoption = _automatic_curve_adoption(db, platform, data, decision, original)
            if adoption:
                try:
                    db.adopt_confirmed_curve(adoption, current_curve=curve)
                except ValueError as error:
                    if str(error) not in ('strategy_adoption_original_window_not_current', 'strategy_adoption_current_curve_changed'):
                        raise
    return result


def calculate(evidence, edits=None, *, selected_action=None,override_reason=None,operation_id=None):
    edits = edits or {}
    if edits.get('costs') or edits.get('offers') or edits.get('quotes'):
        raise ValueError('pricing_legacy_edits_retired_use_v3_evaluate')
    db = ledger()
    job_path=ROOT/'jobs'/(evidence['run_id']+'.json')
    job=json.loads(job_path.read_text()) if job_path.exists() else {}
    request = job.get('request') or {}
    plan_id=request.get('v3_plan_id')
    plan = db.get('pricing_plans',plan_id) if plan_id else db.active_plan()
    now = clock()
    if (job.get('request') or {}).get('v3_authorization_purpose')=='original_unsent_ALL_steps_only':
        [required_history_ratio(evidence,now,platform=p,require_current=True) for p in PLATFORMS]
        return calculate_postwrite(evidence,job,db)
    if _curve_run_requested(job, plan):
        from .competitor_offers import POLICY as CURVE_COMPETITOR_POLICY
        if (evidence.get('competitor_policy') != CURVE_COMPETITOR_POLICY
                or selected_action is not None or edits.get('quotes')):
            raise ValueError('pricing_curve_collection_scope_changed')
        return calculate_curve_cycle(db, evidence, plan, request, now)
    if plan and plan.get('financial_contract_version')!=FINANCIAL_CONTRACT_VERSION:
        raise ValueError('pricing_financial_plan_migration_required')
    [required_history_ratio(evidence,now,platform=p,require_current=True) for p in PLATFORMS]
    from .uk_retirement import PURPOSE as UK_RETIREMENT,calculate as calculate_uk_retirement
    if (job.get('request') or {}).get('v3_authorization_purpose')==UK_RETIREMENT:
        return calculate_uk_retirement(evidence,job,db)
    mode = plan['mode'] if plan else 'revenue_sprint'
    base_plan = plan['baseline_plan'] if mode=='smart' else plan
    smart_plan = dict(plan, mode='revenue_sprint', parameters=base_plan['parameters'], price_anchor=base_plan['price_anchor']) if mode=='smart' else None
    control=db.price_control()
    if (control['manual_enabled'] or control['uplift_enabled']) and not plan:raise ValueError('pricing_plan_required')
    if selected_action is not None and (control['manual_enabled'] or control['uplift_enabled']):
        raise ValueError('pricing_price_control_conflicts_with_manual_preview')
    if control['manual_enabled']:
        before=current_action(evidence)
        candidate=controlled_candidate(evidence,before,control,plan,now)
        evaluations={mode:dict(mode=mode,status='READY',current=before,anchor=plan['price_anchor'],
            candidates=[candidate],selected=candidate,failures=[],valid_until=(now+timedelta(seconds=900)).isoformat())}
    else:
        evaluations = {mode:evaluate(evidence,'revenue_sprint' if mode=='smart' else mode,plan=base_plan,now=now)}
    evaluation = evaluations[mode]
    if not evaluation['candidates']:
        result=dict(checked_at=evidence['checked_at'],rows=[],strategy_version=VERSION,status=evaluation['status'],
            execution_authorized=False,decision_receipt=dict(schema_version=VERSION,mode=mode,plan_id=(plan or {}).get('plan_id'),
                financial_contract_version=FINANCIAL_CONTRACT_VERSION,price_scope_contract=PRICE_SCOPE_CONTRACT,review_contract=PROGRAM_CONTRACT,
                decision_source='program_current_strategy_infeasible',per_cycle_model_required=False,execution_authorized=False,status=evaluation['status']))
        publish_snapshot(db,evidence,result,evaluations,plan,now)
        raise ValueError('pricing_v3_'+evaluation['status'].lower()+':'+','.join(sorted({e['code'] for e in evaluation['failures']}))[:250])
    if selected_action is not None:
        selected=next((c for c in evaluation['candidates'] if c['action']==selected_action),None)
        if selected is None:
            explicit=evaluate(evidence,mode,plan=plan,now=now,explicit_prices=selected_action['base_prices'])
            selected=next((c for c in explicit['candidates'] if c['action']==selected_action),None)
        if selected is None:raise ValueError('pricing_override_not_currently_feasible')
        prior=db.assignment(base_plan,evaluation['candidates'],now=now,lifecycle_plan=plan if mode=='smart' else None) if plan else None
        allocation=db.override_assignment(base_plan,prior,selected,override_reason) if prior else dict(assignment_id=str(uuid.uuid4()),action=selected_action,ends_at=evaluation['valid_until'],
                        deterministic=True,labels=['explicit_override'],parent_assignment_id=(prior or {}).get('assignment_id'),
                        original_assignment=prior,deviation_reason=override_reason)
        db.put('experiment_assignments',allocation['assignment_id'],allocation)
    elif plan and not control['manual_enabled']:
        allocation = db.assignment(base_plan,evaluation['candidates'],now=now,lifecycle_plan=plan if mode=='smart' else None)
        selected = next(c for c in evaluation['candidates'] if c['action']==allocation['action'])
    else:
        selected = evaluation['selected']
        allocation = dict(assignment_id=None,action=selected['action'],ends_at=evaluation['valid_until'],
                          deterministic=True,labels=['read_only_unowned'])
    if not control['manual_enabled'] and control['uplift_enabled']:
        selected=controlled_candidate(evidence,evaluation['current'],control,base_plan,now,selected)
        evaluation['selected']=selected
    smart_assignment = None
    if mode=='smart' and plan and not control['manual_enabled'] and selected_action is None:
        from .smart import STRATEGY_VERSION,assignment as smart_schedule, effective_key, epoch_policy, early_correction,strategy_start,policy_suffix,observe_display
        bidirectional=plan.get('smart_strategy_version')==STRATEGY_VERSION
        epoch=int((now-strategy_start(plan)).total_seconds()//(48*3600))
        display=observe_display(db,plan,evidence,now)
        policy=epoch_policy(db,plan,now,epoch,display=display)
        block=int((now-strategy_start(plan)).total_seconds()//(3*3600))
        correction=early_correction(db,plan,now,block,display=display)
        schedule = smart_schedule(plan, now, policy=policy, correction=correction)
        baseline = selected
        variants,effective_probabilities,probabilities,choice=smart_choices(evidence,smart_plan,evaluation['current'],baseline,schedule,now)
        selected=variants[choice]
        schedule_id=fingerprint([policy_suffix(plan),'smart_schedule',schedule['epoch']]) if bidirectional else fingerprint([plan['plan_id'],plan['revision'],'smart_schedule',schedule['epoch']])
        if not db.get('metadata',schedule_id):
            db.put('metadata',schedule_id,dict(plan_id=plan['plan_id'],revision=plan['revision'],seed=schedule['seed'],schedule=schedule['schedule']))
        ident=fingerprint([policy_suffix(plan),'smart',schedule['block'],evidence['run_id']]) if bidirectional else fingerprint([plan['plan_id'],plan['revision'],'smart',schedule['block'],evidence['run_id']])
        smart_assignment=dict(schedule,assignment_id=ident,plan_id=plan['plan_id'],revision=plan['revision'],plan_starts_at=plan['starts_at'],policy=policy,correction=correction,
            baseline_plan=base_plan,baseline_assignment=allocation,baseline_candidate=baseline,probabilities=probabilities,
            variants={label:dict(action=c['action'],reason=c.get('smart_reason'),**(dict(reasons_by_group=c.get('smart_reasons_by_group')) if bidirectional else {})) for label,c in variants.items()},
            effective_action=selected['action'],effective_key=effective_key(evidence,selected['action']),
            group_keys={g:effective_key(evidence,selected['action'],g) for g in GROUPS},
            no_space_by_group={g:len({effective_key(evidence,c['action'],g) for c in variants.values()})==1 for g in GROUPS},
            merged_with_A_by_group={g:effective_key(evidence,selected['action'],g)==effective_key(evidence,variants['A'*len(GROUPS) if bidirectional else 'A']['action'],g) for g in GROUPS},
            effective_probabilities=effective_probabilities,no_uplift_space=len({effective_key(evidence,c['action']) for c in variants.values()})==1)
        if bidirectional:smart_assignment['smart_started_at']=plan['smart_started_at']
        db.put('experiment_assignments',ident,smart_assignment)
        allocation=dict(assignment_id=ident,action=selected['action'],ends_at=min(instant(schedule['ends_at']),instant(allocation['ends_at'])).isoformat(),
                        probabilities=probabilities,labels=[schedule['label']],smart=schedule)
        evaluation['mode']='smart'
        evaluation['selected']=selected
        evaluation['smart_assignment']=smart_assignment
    if selected.get('price_control') and (mode!='smart' or control['manual_enabled']):
        allocation=dict(allocation,strategy_action=allocation['action'],action=selected['action'],
            effective_choice='operator_price_control')
    action = selected['action']
    relevant_regions=impacted_regions(evidence,evaluation['current'],action,promised_regions=selected.get('regional_market_comparison',{}))
    steps=deepcopy(selected['steps'])
    for step in steps:
        if step['kind']=='region':
            region=next(r for r in evidence['regional_controls'] if str(r['region_id'])+':'+r['platforms'][0]==step['key'])
            step.update(scope=region['scope'],expected_rule_set_sha256=region['expected_rule_set_sha256'])
    mutable_resources=sorted({'base:'+g for g in GROUPS if action['base_prices'][g]!=evaluation['current']['base_prices'][g]} |
                            {'region:'+key for key,factor in action.get('region_coefficients',{}).items() if factor!=evaluation['current'].get('region_coefficients',{}).get(key,'1')})
    resources = sorted(set(mutable_resources or (plan or {}).get('resources') or ['base:'+p for p in PLATFORMS]) |
                       {r.get('resource','region_rule:'+str(r['id'])) for r in relevant_regions} |
                       {'base:'+p for r in relevant_regions for p in r['platforms']
                        if any(key.startswith('region:'+str(r['region_id'])+':') for key in mutable_resources)})
    valid = min(instant(evaluation['valid_until']),instant(allocation['ends_at']))
    bundle = dict(schema_version=VERSION,decision_bundle_id=operation_id or (job.get('request') or {}).get('v3_operation_id') or str(uuid.uuid4()),
        snapshot_id=evidence['run_id'],snapshot_sha256=fingerprint(evidence),mode=mode,
        plan_id=(plan or {}).get('plan_id'),revision=(plan or {}).get('revision'),
        engine_generation=(plan or {}).get('generation'),assignment_id=allocation['assignment_id'],
        action=action,before_action=evaluation['current'],resources=resources,readback_regions=[dict(region_id=r['region_id'],platforms=[p for p in r['platforms'] if 'base:'+p in (mutable_resources or (plan or {}).get('resources',[])) or 'region:'+str(r['region_id'])+':'+p in mutable_resources]) for r in relevant_regions],mutable_resources=mutable_resources or list((plan or {}).get('resources') or []),steps=steps,region_rule_ids=[r['id'] for r in relevant_regions],region_proof_resources=[r.get('resource','region_rule:'+str(r['id'])) for r in relevant_regions],created_at=now.isoformat(),valid_until=valid.isoformat(),
        catalog=evidence['promotion_envelope']['packages'],budget_reference=evidence.get('budget_reference',{}),
        affected_platforms=sorted({p for g,ps in GROUPS.items() if 'base:'+g in (mutable_resources or (plan or {}).get('resources',[])) for p in ps} | {r.split(':')[-1] for r in mutable_resources if r.startswith('region:')}),
        assignment_probability=allocation.get('probabilities',{}).get(fingerprint(action),1),
        randomization_verified=bool(allocation.get('probabilities') and (not smart_assignment or smart_assignment['randomization_verified'] and len(smart_assignment['effective_probabilities'])>1) and len(allocation['probabilities'])>1 and not allocation.get('effective_choice')),
        financial_proof=selected['financial_proof'],market_comparison=selected['market_comparison'],regional_market_comparison=selected.get('regional_market_comparison',{}),
        daily_reference=selected.get('daily_reference',{}),
        daily_pricing=selected.get('daily_pricing',{}),
        daily_average_target_proof=selected.get('daily_average_target_proof',{}),
        financial_contract_version=FINANCIAL_CONTRACT_VERSION,price_scope_contract=PRICE_SCOPE_CONTRACT,history_window_contract=HISTORY_WINDOW_CONTRACT,sprint_policy_version=SPRINT_POLICY_VERSION if mode in ('revenue_sprint','smart') else None,
        strategy_parameters=dict((plan or {}).get('parameters',{}),**sprint_parameters(plan)) if mode in ('revenue_sprint','smart') else (plan or {}).get('parameters',{}),
        authorized_resources=(plan or {}).get('resources',[]),decision_type=selected.get('decision_type'),decision_reason=selected.get('decision_reason'),
        market_position=selected.get('market_position'),minimum_legal_price_proof=selected.get('minimum_legal_price_proof'),
        strategy_decision=selected['score'],allocation=allocation,price_control=control,smart_assignment=smart_assignment,
        strategy_action=selected.get('strategy_action'),strategy_anchor=evaluation['anchor'],
        base_strategy_decision=selected.get('strategy_decision'),
        budget_policy='none',
        execution_authorized=bool(plan and plan.get('state')=='ACTIVE'),review_contract=PROGRAM_CONTRACT,
        decision_source='program_current_strategy',per_cycle_model_required=False,
        hermes_role='daily_effect_review_and_strategy_suggestions',
        legacy_policy_execution=False,margin_basis=MARGIN_BASIS)
    from .region_source import rule_expectations
    bundle['uk_rule_expectations']=rule_expectations((evidence.get('region_contract') or {}).get('rules',[]))
    bundle['sha256'] = fingerprint(bundle)
    result=render_result(evidence,selected,bundle,mode)
    publish_snapshot(db,evidence,result,evaluations,plan,now,selected)
    return result


def publish_snapshot(db,evidence,result,evaluations,plan,now,selected=None):
    """Keep every current-strategy calculation for the page, audit and daily read-only replay."""
    mode=next(iter(evaluations))
    snapshot=dict(snapshot_id=evidence['run_id'],origin='live_collector',mode='production',evidence=evidence,result=result,
                  policy_version=VERSION,created_at=now.isoformat())
    with db.transaction() as conn:
        db.put('pricing_snapshots',evidence['run_id'],snapshot,conn)
        db.put('metadata','latest_snapshot_summary',public_snapshot_summary(snapshot),conn)
        if plan:
            db.put('metadata','latest_snapshot:'+plan['plan_id'],dict(snapshot_id=evidence['run_id'],plan_id=plan['plan_id']),conn)
        db.put('strategy_decisions',evidence['run_id'],evaluations,conn)
        if mode=='revenue_sprint' and selected:db.put('market_comparisons',evidence['run_id'],dict(created_at=now.isoformat(),plan_id=(plan or {}).get('plan_id'),sprint_policy_version=SPRINT_POLICY_VERSION,groups=selected['market_comparison'],regions=selected.get('regional_market_comparison',{})),conn)
        conn.execute('INSERT OR IGNORE INTO event_outbox(event_key,kind,body) VALUES (?,?,?)',
                     ('snapshot:'+evidence['run_id'],'snapshot_ready',json.dumps(dict(snapshot_id=evidence['run_id']))))


def render_result(evidence,selected,bundle,mode):
    action=selected['action']
    rows=[]
    for p in PLATFORMS:
        group=p
        fp=selected['financial_proof']['prices']['global:'+p]
        cost=evidence['costs'][p]
        own=evidence['storefront']['rows'][p]
        target=number(action['base_prices'][group])
        public_anchor=evidence['offers'][p].get('Lootbar')
        try:market_quote(evidence,p,'Lootbar',instant(evidence['checked_at']))
        except (ValueError,KeyError,TypeError):public_anchor=None
        market=selected.get('market_comparison',{}).get(group,{})
        daily_reference=selected.get('daily_reference',{}).get(p)
        daily_pricing=selected.get('daily_pricing',{}).get(group)
        daily_source=(daily_pricing or {}).get('driver_source','ItemD2R')
        offers=[dict(source=s,**value) for s,value in evidence['offers'][p].items()]
        rows.append(dict(platform=p,proposal=format(target/100,'.4f'),auto_proposal=format(target/100,'.4f'),
            raw_cost_cny=cost['cny_per_1k'],cost_cny=cost['cny_per_1k'],raw_cost_record_id=cost['record_id'],
            raw_cost_trade_at=cost['trade_at'],cost_record_id=cost['record_id'],cost_trade_at=cost['trade_at'],
            target_page_usd=str(target),floor_usd_per_1k=fp['catalog']['minimum_unit_usd'],
            offers=offers,missing=[],proof=dict(fp['proof'],catalog=fp['catalog']),
            estimated_average_margin=fp['average'],margin_basis=MARGIN_BASIS,
            minimum_gross_margin_pct=str(HARD_MARGIN),margin_below_minimum=False,auto_blocked_reason=None,
            decision_type=selected.get('decision_type'),financial_contract_version=FINANCIAL_CONTRACT_VERSION,price_scope_contract=PRICE_SCOPE_CONTRACT,
            gross_margin_pct=fp['proof']['procurement_margin_pct'],pricing_mode=mode,pricing_tier=None,
            requested_discount_pct=None,profit_floor_applied=False,pricing_basis='page_total_100k',
            strategy_version=VERSION,quote_manual=selected.get('decision_type')=='manual_intervention',own_bonus_k=own['bonus_k'],
            decision_reason=selected.get('decision_reason') or mode+'_objective',ending_reason='v3_exact_no_hidden_adjustment',
            pricing_quantity_basis='both_sides_actual_delivered_quantity',
            lootbar_page_usd=public_anchor['usd_price'] if public_anchor else None,
            lootbar_usd_per_1k=str(number(public_anchor['usd_price'])/(number(public_anchor['base_k'])+number(public_anchor.get('bonus_k','0'),zero=True))) if public_anchor else None,
            competition_available=bool(daily_reference.get('source')) if daily_reference is not None else market.get('competition_available',{}).get(p),
            source_gaps=daily_reference['source_gaps'] if daily_reference is not None else [gap for gap in market.get('source_gaps',[]) if gap['platform']==p],
            daily_reference=daily_reference,daily_pricing=daily_pricing,
            change_pct=str((target/number(own['package_usd'])-1)*100),
            warning='双20%红线；单笔合法优惠仍可亏损。预测不是实绩。',status='舍入导致目标未命中 · 未达到'+daily_source+'目标' if daily_pricing and daily_pricing['unmet_reason']=='public_cent_not_reachable' else '财务底价抬高 · 未达到'+daily_source+'目标' if daily_pricing and not daily_pricing['item_target_met'] else '按'+daily_source+'实际交付价定价 · 待执行' if daily_pricing else '财务底价兜底 · 未达到竞争降幅' if selected.get('decision_type')=='floor_fallback' else '双模式引擎核算通过 · 待执行'))
    result=dict(checked_at=evidence['checked_at'],fx=evidence['fx'],minimum_gross_margin_pct=str(HARD_MARGIN),
                rows=rows,decision_receipt=bundle,strategy_version=VERSION)
    return result


def postwrite_owner(db,operation):
    resources=operation['bundle'].get('mutable_resources',operation['resources'])
    current=(db.generation() or {}).get('id')
    if operation['generation']!=current:raise ValueError('pricing_postwrite_old_generation_read_only')
    with db.connect() as conn:
        rows=[conn.execute('SELECT plan_id,revision,generation FROM plan_ownership WHERE resource=?',(resource,)).fetchone() for resource in resources]
    if not rows or any(row is None for row in rows) or len({(r[0],r[1],r[2]) for r in rows})!=1:
        raise ValueError('pricing_postwrite_joint_owner_required')
    plan=db.get('pricing_plans',rows[0][0])
    if not plan or plan['state'] not in ('ACTIVE','ENDING') or plan['generation']!=current:
        raise ValueError('pricing_postwrite_owner_inactive')
    ancestor=plan;seen=set()
    while ancestor['plan_id']!=operation['plan_id']:
        if ancestor['plan_id'] in seen or not ancestor.get('parent_plan_id'):
            raise ValueError('pricing_postwrite_owner_lineage_changed')
        seen.add(ancestor['plan_id']);ancestor=db.get('pricing_plans',ancestor['parent_plan_id'])
        if not ancestor:raise ValueError('pricing_postwrite_owner_lineage_missing')
    return plan


def calculate_postwrite(evidence,job,db):
    """Reprove the saved merchant price solely for original, unsent ALL steps."""
    operation_id=job['request']['v3_operation_id'];op=db.get('operations',operation_id)
    if not op:raise ValueError('pricing_postwrite_original_operation_required')
    plan=postwrite_owner(db,op)
    reservation=db.get('reservations',operation_id)
    if op['bundle'].get('budget_policy')!='none' and (not reservation or reservation.get('state')!='RESERVED' or reservation.get('operation_id')!=operation_id or reservation.get('plan_id')!=op['plan_id']):
        raise ValueError('pricing_postwrite_original_reservation_required')
    audit=json.loads((ROOT/'executions'/(operation_id+'.json')).read_text())
    if audit.get('execution_id')!=operation_id or audit.get('sync_confirmed') is not True:
        raise ValueError('pricing_postwrite_merchant_unconfirmed')
    actual={row['platform']:str(number(row['b2c'])*100) for row in audit.get('after',{}).get('rows',[])}
    if set(actual)!=set(PLATFORMS):raise ValueError('pricing_postwrite_actual_scope_invalid')
    base={p:actual[p] for p in PLATFORMS}
    if any(number(base[g])!=number(op['bundle']['action']['base_prices'][action_key(op['bundle']['action'],g)]) for g in GROUPS):raise ValueError('pricing_postwrite_actual_price_changed')
    base=native_action(op['bundle']['action'])['base_prices']
    action=dict(base_prices=base,region_coefficients={str(r['region_id'])+':'+p:r['factor'] for r in evidence.get('region_rules',[])+evidence.get('regional_controls',[]) for p in r['platforms']})
    now=clock();regions=proof_regions(evidence,action,action)
    for region in evidence.get('region_rules',[]):
        if region not in regions:regions.append(region)
    proof=financial(evidence,action,now,regions=regions)
    bundle=dict(schema_version=VERSION,authorization_purpose='original_unsent_ALL_steps_only',decision_bundle_id=operation_id,
        original_operation_id=operation_id,snapshot_id=evidence['run_id'],snapshot_sha256=fingerprint(evidence),mode='postwrite_completion',
        plan_id=plan['plan_id'],revision=plan['revision'],engine_generation=plan['generation'],assignment_id=op['bundle'].get('assignment_id'),
        action=action,before_action=action,resources=op['resources'],mutable_resources=op['bundle'].get('mutable_resources',op['resources']),
        steps=[],created_at=now.isoformat(),valid_until=(now+timedelta(minutes=15)).isoformat(),financial_proof=proof,financial_contract_version=FINANCIAL_CONTRACT_VERSION,price_scope_contract=PRICE_SCOPE_CONTRACT,
        market_comparison={},regional_market_comparison={},catalog=evidence['promotion_envelope']['packages'],
        budget_policy=op['bundle'].get('budget_policy','historical_reservation'),
        budget_reservation=op['bundle'].get('budget_reservation',{}),budget_kind='original_reservation_no_new_price_or_concession',
        execution_authorized=True,review_contract=op['bundle']['review_contract'],review_receipt=op['bundle'].get('review_receipt'),
        review_approved=False,decision_source='original_business_decision_fresh_financial_revalidation_for_ALL_only',
        margin_basis=MARGIN_BASIS,legacy_policy_execution=False)
    bundle['sha256']=fingerprint(bundle)
    result=render_result(evidence,dict(action=action,financial_proof=proof),bundle,'postwrite_completion')
    snapshot=dict(snapshot_id=evidence['run_id'],origin='live_collector',mode='production',evidence=evidence,result=result,
                  policy_version=VERSION,authorization_purpose=bundle['authorization_purpose'],created_at=now.isoformat())
    db.put('pricing_snapshots',evidence['run_id'],snapshot)
    return result


def override_quote(evidence,explicit_prices,reason,restore_source_execution_id=None,plan=None):
    if not isinstance(reason,str) or len(reason.strip())<4:
        raise ValueError('pricing_manual_reason_required')
    plan=plan or ledger().active_plan()
    if not plan:raise ValueError('pricing_plan_required')
    result=evaluate(evidence,plan['mode'],plan=plan,explicit_prices=explicit_prices)
    if not result['selected']:
        raise ValueError('pricing_manual_infeasible:'+','.join(sorted({r['code'] for r in result['failures']})))
    return dict(selected=result['selected'],current=result['current'],valid_until=result['valid_until'],
                plan_id=plan['plan_id'],revision=plan['revision'],explicit_prices=explicit_prices,reason=reason,
                restore_source_execution_id=restore_source_execution_id,execution_authorized=False)


def verify_quote(quote, policy, selected, *, now=None, for_execution=False,purpose=None):
    now=now or clock()
    receipt=quote['result'].get('decision_receipt') or {}
    if write_protocol(receipt) == CURVE_WRITE_PROTOCOL:
        return verify_curve_quote(quote, receipt, policy, selected, now, for_execution, purpose)
    if receipt.get('authorization_purpose')!=purpose:
        raise ValueError('pricing_authorization_purpose_mismatch')
    if quote['evidence'].get('mode')=='shadow' or quote['evidence'].get('simulation_kind') or receipt.get('financial_proof',{}).get('execution_eligible') is not True:
        raise ValueError('pricing_simulation_execution_forbidden')
    if receipt.get('schema_version')!=VERSION or quote['result'].get('strategy_version')!=VERSION:
        raise ValueError('pricing_legacy_quote_retired')
    if receipt.get('sha256')!=fingerprint({k:v for k,v in receipt.items() if k!='sha256'}):
        raise ValueError('pricing_decision_bundle_changed')
    if receipt['snapshot_sha256']!=fingerprint(quote['evidence']):
        raise ValueError('pricing_snapshot_changed')
    if not selected or set(selected)-set(PLATFORMS) :
        raise ValueError('pricing_platform_scope_required')
    if number(policy['minimum_gross_margin_pct'])!=HARD_MARGIN:
        raise ValueError('pricing_margin_contract_changed')
    if receipt.get('price_scope_contract')!=PRICE_SCOPE_CONTRACT or set(receipt['action']['base_prices'])!=set(PLATFORMS):
        raise ValueError('pricing_platform_quote_migration_required')
    version=receipt.get('financial_contract_version')
    if version==FINANCIAL_CONTRACT_VERSION:
        [required_history_ratio(quote['evidence'],now,platform=p,require_current=True) for p in PLATFORMS]
    elif not for_execution and version==LEGACY_FINANCIAL_CONTRACT_VERSION and quote['evidence']['historical_discount_mix'].get('history_window_contract') is None:
        [required_history_ratio(quote['evidence'],now,platform=p) for p in PLATFORMS]
    else:
        raise ValueError('pricing_financial_quote_migration_required')
    from .uk_retirement import PURPOSE as UK_RETIREMENT,authority_resources
    maintenance=receipt.get('maintenance_purpose')==UK_RETIREMENT
    controlled=bool(receipt.get('price_control',{}).get('manual_enabled') or receipt.get('price_control',{}).get('uplift_enabled'))
    if not maintenance and purpose!='original_unsent_ALL_steps_only':
        if for_execution:
            actual_control=ledger().price_control()
            if receipt.get('price_control',{}).get('revision',0)!=actual_control['revision'] or receipt.get('price_control') is not None and receipt['price_control']!=actual_control:
                raise ValueError('pricing_price_control_revision_changed')
        if controlled and (receipt['mode']!='smart' or receipt['price_control']['manual_enabled']):
            plan=dict(mode=receipt['mode'],resources=receipt['authorized_resources'],parameters=receipt['strategy_parameters'],price_anchor=receipt['strategy_anchor'])
            raw=None
            if not receipt['price_control']['manual_enabled']:
                original=evaluate(quote['evidence'],receipt['mode'],plan=plan,now=now)
                raw=next((c for c in original['candidates'] if c['action']==receipt['strategy_action']),None)
                if raw is None:raise ValueError('pricing_price_control_strategy_changed')
            checked=controlled_candidate(quote['evidence'],receipt['before_action'],receipt['price_control'],plan,now,raw)
            if checked['action']!=receipt['action'] or checked['financial_proof']!=receipt['financial_proof']:
                raise ValueError('pricing_price_control_proof_changed')
        smart_override=receipt['mode']=='smart' and (receipt.get('allocation') or {}).get('effective_choice')=='explicit_business_decision_not_new_random_draw'
        if receipt['mode']=='smart' and not receipt['price_control']['manual_enabled'] and not smart_override:
            from .smart import STRATEGY_VERSION,assignment as smart_schedule,effective_key,policy_suffix,policy_key
            saved=receipt.get('smart_assignment') or {}
            bidirectional=saved.get('strategy_version')==STRATEGY_VERSION
            plan=dict(plan_id=receipt['plan_id'],revision=receipt['revision'],starts_at=saved.get('plan_starts_at'),
                      mode='revenue_sprint',resources=receipt['authorized_resources'],parameters=receipt['strategy_parameters'],price_anchor=receipt['strategy_anchor'])
            if bidirectional:plan.update(smart_strategy_version=STRATEGY_VERSION,smart_started_at=saved.get('smart_started_at'))
            base_plan=saved.get('baseline_plan') or {}
            if base_plan.get('mode')!='revenue_sprint' or base_plan.get('price_anchor')!=receipt['strategy_anchor']:
                raise ValueError('pricing_smart_baseline_plan_changed')
            schedule=smart_schedule(plan,instant(receipt['created_at']),policy=saved.get('policy'),correction=saved.get('correction'))
            fields=('epoch','block','slot','label','original_label','randomization_verified','seed','schedule','marginal_probabilities','starts_at','ends_at')
            if bidirectional:fields+=('strategy_version','revision','group_labels','group_pair_ids','group_schedules','group_probabilities')
            if any(saved.get(k)!=schedule[k] for k in fields):
                raise ValueError('pricing_smart_assignment_changed')
            if for_execution:
                actual=ledger().get('experiment_assignments',saved.get('assignment_id'))
                if actual!=saved or saved.get('assignment_id')!=receipt.get('assignment_id'):
                    raise ValueError('pricing_smart_assignment_not_persisted')
                stored_policy_key=policy_key(plan,schedule['epoch'],saved.get('policy'))
                if ledger().get('metadata',stored_policy_key)!=saved.get('policy'):
                    raise ValueError('pricing_smart_policy_changed')
                live_plan=ledger().get('pricing_plans',plan['plan_id'])
                if not live_plan or live_plan.get('baseline_plan')!=base_plan:
                    raise ValueError('pricing_smart_baseline_plan_changed')
                if bidirectional and (live_plan.get('smart_strategy_version')!=STRATEGY_VERSION or live_plan.get('smart_started_at')!=plan['smart_started_at']):
                    raise ValueError('pricing_smart_strategy_version_changed')
                baseline_key=fingerprint([base_plan['plan_id'],base_plan['revision'],int(instant(receipt['created_at']).timestamp())//(6*3600)])
                baseline_key=fingerprint([baseline_key,'smart_lifecycle',plan['plan_id'],plan['revision']])
                if ledger().get('experiment_assignments',baseline_key)!=(saved.get('baseline_assignment') or {}):
                    raise ValueError('pricing_smart_baseline_assignment_changed')
            evaluation=evaluate(quote['evidence'],'revenue_sprint',plan=base_plan,now=now)
            raw_action=(saved.get('baseline_assignment') or {}).get('action')
            raw=next((c for c in evaluation['candidates'] if c['action']==raw_action),None)
            if raw is None:raise ValueError('pricing_smart_baseline_changed')
            base=controlled_candidate(quote['evidence'],evaluation['current'],receipt['price_control'],base_plan,now,raw) if receipt['price_control']['uplift_enabled'] else raw
            variants,effective_probabilities,probabilities,choice=smart_choices(quote['evidence'],plan,evaluation['current'],base,schedule,now)
            expected_variants={label:dict(action=c['action'],reason=c.get('smart_reason'),**(dict(reasons_by_group=c.get('smart_reasons_by_group')) if bidirectional else {})) for label,c in variants.items()}
            if expected_variants!=saved.get('variants'):raise ValueError('pricing_smart_candidates_changed')
            if effective_probabilities!=saved.get('effective_probabilities'):
                raise ValueError('pricing_smart_probability_changed')
            checked=variants[choice]
            if bidirectional:
                expected=dict(probabilities=probabilities,effective_action=checked['action'],effective_key=effective_key(quote['evidence'],checked['action']),
                    group_keys={g:effective_key(quote['evidence'],checked['action'],g) for g in GROUPS},
                    no_space_by_group={g:len({effective_key(quote['evidence'],c['action'],g) for c in variants.values()})==1 for g in GROUPS},
                    merged_with_A_by_group={g:effective_key(quote['evidence'],checked['action'],g)==effective_key(quote['evidence'],variants['A'*len(GROUPS)]['action'],g) for g in GROUPS},
                    no_uplift_space=len({effective_key(quote['evidence'],c['action']) for c in variants.values()})==1)
                if any(saved.get(k)!=v for k,v in expected.items()):raise ValueError('pricing_smart_group_proof_changed')
                if receipt['allocation'].get('probabilities')!=probabilities or receipt['assignment_probability']!=probabilities.get(fingerprint(checked['action'])):
                    raise ValueError('pricing_smart_probability_changed')
            if checked['action']!=receipt['action'] or checked['financial_proof']!=receipt['financial_proof']:
                raise ValueError('pricing_smart_proof_changed')
            if [s['intermediate'] for s in checked['steps']]!=[s['intermediate'] for s in receipt['steps']]:
                raise ValueError('pricing_smart_commit_path_changed')
    regions=quote['evidence'].get('region_rules',[])
    if maintenance:
        authority_resources(receipt)
        regions=regions+quote['evidence'].get('regional_controls',[])
        if financial(quote['evidence'],receipt['before_action'],now,regions=regions)!=receipt['before_financial_proof']:
            raise ValueError('pricing_uk_retirement_before_proof_changed')
    elif purpose!='original_unsent_ALL_steps_only':
        targeted=[p for g,ps in GROUPS.items() if not receipt.get('plan_id') or 'base:'+g in receipt['authorized_resources'] for p in ps
                  if receipt.get('mode')=='daily' and receipt.get('daily_reference',{}).get(p,{}).get('average_margin_target_pct')=='30']
        regions=proof_regions(quote['evidence'],receipt['before_action'],receipt['action'],promised_regions=receipt.get('regional_market_comparison',{}),minimum_average_platforms=targeted)
    proof=financial(quote['evidence'],receipt['action'],now,regions=regions)
    if proof!=receipt['financial_proof']:
        raise ValueError('pricing_financial_proof_changed')
    for row in quote['result']['rows']:
        group=row['platform']
        if number(row['proposal'])*100!=number(receipt['action']['base_prices'][group]):
            raise ValueError('pricing_action_row_changed')
    if receipt['mode']=='daily' and not controlled and not maintenance and purpose!='original_unsent_ALL_steps_only':
        from .engine import daily_reference,required_base_bound,daily_average_target_proof,daily_competitor_target
        daily_plan=dict(mode='daily',resources=receipt['authorized_resources'],parameters=receipt['strategy_parameters'])
        references=daily_reference(quote['evidence'],PLATFORMS,now,plan=daily_plan)
        if references!=receipt.get('daily_reference'):raise ValueError('pricing_daily_reference_changed')
        targets=[p for g,ps in GROUPS.items() if not receipt.get('plan_id') or 'base:'+g in receipt['authorized_resources'] for p in ps if references[p]['average_margin_target_pct']=='30']
        if daily_average_target_proof(quote['evidence'],proof,targets)!=receipt.get('daily_average_target_proof'):raise ValueError('pricing_daily_average_target_proof_changed')
        pricing={}
        for group,platforms in GROUPS.items():
            if receipt.get('plan_id') and 'base:'+group not in receipt['authorized_resources']:continue
            floor=max(required_base_bound(quote['evidence'],p,now,daily_plan,average_minimum='30' if references[p]['average_margin_target_pct']=='30' else HARD_MARGIN) for p in platforms)
            item_target=daily_competitor_target(quote['evidence'],platforms,references,floor,plan=daily_plan)
            if item_target:
                pricing[group]=item_target
                if number(receipt['action']['base_prices'][group])!=number(item_target['selected_base_total']):raise ValueError('pricing_daily_item_target_price_changed')
            elif any(references[p]['average_margin_target_pct']=='30' for p in platforms):
                if number(receipt['action']['base_prices'][group])!=floor:raise ValueError('pricing_daily_missing_market_not_minimum_average_30')
        if pricing!=receipt.get('daily_pricing',{}):raise ValueError('pricing_daily_item_target_proof_changed')
    if (receipt['mode']=='revenue_sprint' or receipt['mode']=='smart' and (receipt.get('allocation') or {}).get('effective_choice')=='explicit_business_decision_not_new_random_draw') and not controlled:
        market_plan=dict(mode='revenue_sprint',resources=receipt['authorized_resources'],parameters=receipt['strategy_parameters']) if receipt.get('plan_id') else None
        markets={}
        for group in receipt['market_comparison']:
            ps=GROUPS[group]
            market=competition(quote['evidence'],ps,now,plan=market_plan)
            markets[group]=market
            if market!=receipt['market_comparison'][group]:
                raise ValueError('pricing_market_proof_changed')
            target=number(receipt['action']['base_prices'][group])
            if market['decision_type']=='floor_fallback':
                if receipt.get('decision_type')!='floor_fallback' or target!=number(market['minimum_legal_base_total']):raise ValueError('pricing_fallback_not_minimum_legal_price')
            elif any(not number(t['total_low'])<=target<=number(t['total_high']) for t in market['targets'].values()):
                raise ValueError('pricing_competitive_band')
        for key,prior in receipt.get('regional_market_comparison',{}).items():
            platform=key.split(':')[1]
            group=platform
            market=competition(quote['evidence'],[platform],now,region=21,plan=market_plan,resolved_global=markets[group],base_total=receipt['action']['base_prices'][group])
            if market!=prior:raise ValueError('pricing_regional_market_proof_changed')
            price=number(proof['prices'][key]['price']['delivered_unit_100k'])
            if market['decision_type']=='floor_fallback':
                if receipt.get('decision_type')!='floor_fallback' or receipt['action']['region_coefficients'][key] not in market['legal_coefficients']:raise ValueError('pricing_regional_fallback_not_minimum_legal_price')
            elif market['decision_type']=='regional_follow_global':
                if number(receipt['action']['region_coefficients'][key])!=1:raise ValueError('pricing_saudi_follow_global_factor_must_be_one')
            else:
                limits=market['targets'][platform]
                if not number(limits['unit_low'])<=price<=number(limits['unit_high']):raise ValueError('pricing_regional_competitive_band')
    if for_execution:
        if now>=instant(receipt['valid_until']) or not receipt['execution_authorized']:
            raise ValueError('pricing_authorization_expired_or_unowned')
        control=json.loads((ROOT/'config/v3-control.json').read_text())
        if control['generation']!=receipt['engine_generation'] or not control.get('enabled'):
            raise ValueError('pricing_generation_retired')
        if purpose=='original_unsent_ALL_steps_only':
            if receipt.get('review_contract') not in (PROGRAM_CONTRACT,'inherited_hermes_review_with_explicit_v3_deterministic_path'):
                raise ValueError('pricing_original_contract_unknown')
            if receipt['review_contract']!=PROGRAM_CONTRACT and receipt.get('review_receipt') is None:
                raise ValueError('pricing_original_review_receipt_missing')
        elif maintenance:
            if receipt.get('review_contract')!=UK_RETIREMENT or receipt.get('decision_source')!='user_authorized_uk_discount_retirement':raise ValueError('pricing_uk_retirement_contract_changed')
        elif receipt.get('review_contract')==PROGRAM_CONTRACT:
            if receipt.get('per_cycle_model_required') is not False or receipt.get('decision_source')!='program_current_strategy':
                raise ValueError('pricing_program_contract_changed')
        else:
            raise ValueError('pricing_review_contract_retired')
    return receipt


def verify_curve_quote(quote, receipt, policy, selected, now, for_execution, purpose):
    from .competitor_offers import POLICY as CURVE_COMPETITOR_POLICY
    from .pricing_proof_v6 import CONTRACT

    evidence = quote.get('evidence') or {}
    if (purpose is not None or receipt.get('schema_version') != VERSION
            or bool(receipt.get('curve_restore_preview_id')) != bool(receipt.get('restore_source_execution_id'))
            or quote['result'].get('strategy_version') != VERSION
            or receipt.get('financial_contract_version') != CONTRACT
            or evidence.get('competitor_policy') != CURVE_COMPETITOR_POLICY
            or receipt.get('snapshot_id') != evidence.get('run_id')
            or receipt.get('snapshot_sha256') != fingerprint(evidence)
            or receipt.get('sha256') != fingerprint({k: v for k, v in receipt.items() if k != 'sha256'})):
        raise ValueError('pricing_curve_quote_identity_invalid')
    if quote.get('run_id', receipt['snapshot_id']) != receipt['snapshot_id']:
        raise ValueError('pricing_curve_quote_identity_invalid')
    changed = curve_dispatch_platforms(receipt)
    if (not changed or not set(changed) <= set(selected) or receipt['resources'] != receipt['mutable_resources']
            or set(receipt['curve_proofs']) != set(changed)):
        raise ValueError('pricing_curve_original_dispatch_scope_changed')
    if not for_execution:
        return receipt
    if (not policy.get('system_enabled') or not set(changed) <= set(policy['platforms'])
            or quote.get('automation_policy_revision') != policy['revision']
            or not receipt.get('execution_authorized')
            or not instant(receipt['created_at']) <= now < instant(receipt['valid_until'])):
        raise ValueError('pricing_authorization_expired_or_unowned')
    db = ledger()
    control = json.loads((ROOT/'config/v3-control.json').read_text())
    if control.get('enabled') is not True or control['generation'] != receipt['engine_generation']:
        raise ValueError('pricing_generation_retired')
    with db.connect() as conn:
        conn.execute('BEGIN')
        plan = db.get('pricing_plans', receipt['plan_id'], conn)
        if (not plan or plan['state'] != 'ACTIVE' or plan.get('write_protocol') != CURVE_WRITE_PROTOCOL
                or plan.get('activation_revision') != receipt['activation_revision']
                or plan['revision'] != receipt['revision'] or plan['generation'] != receipt['engine_generation']):
            raise ValueError('pricing_curve_plan_revision_changed')
        db.owns(plan, receipt['resources'], conn)
        price_control = db.price_control(conn)
        if price_control != receipt['price_control'] or price_control['manual_enabled'] or price_control['uplift_enabled']:
            raise ValueError('pricing_price_control_revision_changed')
        frozen = _curve_proof_inputs(db, evidence, conn)
        restore_id = receipt.get('curve_restore_preview_id')
        if restore_id:
            intent, restore = _curve_restore_intent(db, plan, restore_id, receipt['decision_bundle_id'], now, conn)
            source_id = intent['restore_source_execution_id']
            if receipt.get('restore_source_execution_id') != source_id:
                raise ValueError('pricing_curve_restore_preview_invalid')
            restored = {p: _prove_curve_restore(p, frozen.get(p), before, source_id, now)
                        for p, before in restore.items()}
            if (set(changed) != {p for p in restored if restored[p]['status'] == 'READY'}
                    or any(row['status'] not in ('READY', 'KEEP') for row in restored.values())):
                raise ValueError('pricing_curve_execution_proof_unverified')
        for platform in changed:
            if restore_id:
                proof = restored[platform]
            else:
                proof = _prove_curve_inputs(platform, frozen.get(platform), db, now, conn, evidence=evidence,
                                            plan=plan, decision_at=instant(receipt['created_at']),
                                            paired_bands=receipt.get('curve_decision_policy') in (CURVE_DECISION_POLICY, CURVE_PROTECTION_POLICY),
                                            temporary_protection=receipt.get('curve_decision_policy') == CURVE_PROTECTION_POLICY)
            if (proof['status'] != 'READY' or proof['before'] != receipt['before_action']['curves'][platform]
                    or proof['target'] != receipt['action']['curves'][platform]
                    or proof['proof'] != receipt['curve_proofs'][platform]
                    or proof['native_route'] != (receipt.get('curve_native_routes') or {}).get(platform)
                    or proof['primary_before_hash'] != (receipt.get('curve_primary_before_hashes') or {}).get(platform)
                    or proof['selection'] != receipt['curve_selection'][platform]):
                raise ValueError('pricing_curve_execution_proof_unverified')
            adoption = receipt.get('curve_adoption') or {}
            if (adoption.get('platform') == platform and receipt.get('curve_decision_policy') == CURVE_PROTECTION_POLICY
                    and adoption != _automatic_curve_adoption(db, platform, frozen[platform], proof,
                                                             receipt['decision_bundle_id'], conn=conn)):
                raise ValueError('pricing_curve_adoption_evidence_changed')
    return receipt


def attach_review(run_id,review):
    path=ROOT/'quotes'/(run_id+'.json')
    quote=json.loads(path.read_text())
    bundle=quote['result']['decision_receipt']
    bundle['review_receipt']={k:review.get(k) for k in ('phase','conversation_id','turn_id','reason','applied')}
    recommended=review.get('recommendation')
    bundle['decision_source']='v3_reviewed_assignment' if recommended and recommended.get('action_vector')==bundle['action'] else 'v3_explicit_deterministic_feasible_assignment'
    bundle['review_approved']=bool(recommended and recommended.get('action_vector')==bundle['action'] and review.get('phase')=='completed')
    bundle['review_basis_quote_sha256']=(recommended or {}).get('quote_sha256')
    bundle['sha256']=fingerprint({k:v for k,v in bundle.items() if k!='sha256'})
    write_json(path,quote)
    db=ledger()
    snapshot=db.get('pricing_snapshots',run_id)
    snapshot['result']=quote['result']
    db.put('pricing_snapshots',run_id,snapshot)
    return quote


def curve_dispatch_platforms(bundle):
    from .price_curve import curve_key

    before = bundle['before_action'].get('curves') or {}
    target = bundle['action'].get('curves') or {}
    if not before or set(before) != set(target) or set(before) - set(PLATFORMS):
        raise ValueError('pricing_curve_scope_missing')
    selected = [p for p in PLATFORMS if p in target and curve_key(before[p]) != curve_key(target[p])]
    if selected:
        if ([s['kind'] for s in bundle['steps']] != ['base']
                or set(bundle['mutable_resources']) != {'base:' + p for p in selected}
                or set(bundle['affected_platforms']) != set(selected)):
            raise ValueError('pricing_curve_original_dispatch_scope_changed')
    elif bundle['steps']:
        raise ValueError('pricing_curve_original_dispatch_scope_changed')
    return selected


def execute_run(run_id):
    import fc27_cloud_worker as worker
    db=ledger()
    quote=json.loads((ROOT/'quotes'/(run_id+'.json')).read_text())
    from automation_policy import load_policy
    candidate = quote['result'].get('decision_receipt') or {}
    if write_protocol(candidate) == CURVE_WRITE_PROTOCOL:
        existing = db.get('operations', candidate['decision_bundle_id'])
        if existing:
            if existing['bundle'] != candidate or candidate['snapshot_id'] != run_id:
                raise ValueError('pricing_operation_payload_conflict')
            return complete_player_followup(existing) if existing['status'] in ('COMPLETED','NO_CHANGE') else reconcile(existing['operation_id'])
    bundle=verify_quote(quote,load_policy(),list(PLATFORMS),for_execution=True)
    plan=db.get('pricing_plans',bundle['plan_id'])
    existing=db.get('operations',bundle['decision_bundle_id'])
    if existing:
        return complete_player_followup(existing) if existing['status'] in ('COMPLETED','NO_CHANGE') else reconcile(existing['operation_id'])
    if write_protocol(bundle) == CURVE_WRITE_PROTOCOL:
        selected = curve_dispatch_platforms(bundle)
    else:
        selected=[p for p in PLATFORMS if number(quote['evidence']['storefront']['rows'][p]['package_usd'])!=number(bundle['action']['base_prices'][p])]
        if set(selected)&{'PS','XBOX'}:
            selected=[p for p in PLATFORMS if p in set(selected)|{'PS','XBOX'}]
    if write_protocol(bundle) == CURVE_WRITE_PROTOCOL:
        if bundle.get('curve_adoption') is not None:
            with db.connect() as conn:
                db._curve_adoption_input(bundle['curve_adoption'], bundle['decision_bundle_id'], bundle, conn)
        preview = _curve_writer_preview(run_id, quote, bundle)
    else:
        code,preview=worker.run([str(worker.APP/'preview_backend.sh'),run_id],85)
        if code or preview.get('status')!='review_only':
            raise ValueError('pricing_backend_preview_failed')
    job=json.loads((ROOT/'jobs'/(run_id+'.json')).read_text())
    automatic=not job.get('request',{}).get('manual_requested')
    operation=db.prepare(plan,bundle,dispatch_context=dict(preview=preview,selected=selected,automatic=automatic,
                         actor=job['actor'] if not automatic else 'system-automation',policy_revision=load_policy()['revision']))
    if not bundle['steps']:
        with operation_execution(operation['operation_id']):
            return _verify_nochange(operation,preview)
    return drive_steps(operation,quote)


def _curve_writer_preview(run_id, quote, bundle):
    preview = dict(preview_id=bundle['decision_bundle_id'], run_id=run_id, status='review_only',
        created_at=bundle['created_at'], expires_at=bundle['valid_until'],
        quote_sha256=hashlib.sha256((ROOT/'quotes'/(run_id+'.json')).read_bytes()).hexdigest(),
        snapshot_sha256=quote['snapshot_sha256'], quote_engine_sha256=quote['quote_engine_sha256'])
    path = ROOT/'previews'/(preview['preview_id']+'.json')
    if path.exists():
        if json.loads(path.read_text()) != preview:
            raise ValueError('pricing_curve_original_preview_changed')
    else:
        write_json(path, preview)
    return preview


def _verify_nochange(operation,preview):
    from .adapters import verify_nochange
    db=ledger();operation=db.get('operations',operation['operation_id'])
    if operation['status'] in TERMINAL_CLOSE_STATUS:return complete_player_followup(operation)
    if write_protocol(operation.get('bundle') or {}) == CURVE_WRITE_PROTOCOL:
        curve_dispatch_platforms(operation['bundle'])
        receipt = dict(status='PUBLIC_PENDING', write_protocol=CURVE_WRITE_PROTOCOL,
                       execution_id=operation['operation_id'], preview=preview,
                       reason='pricing_curve_current_full_readback_unavailable', write_performed=False)
    else:
        receipt=verify_nochange(operation,preview)
    if receipt['status']!='PUBLIC_CONFIRMED':
        operation.update(status='PUBLIC_PENDING',readback=receipt)
        db.put('operations',operation['operation_id'],operation)
        return operation
    return db.finish(operation['operation_id'],receipt,no_change=True)


def drive_steps(operation,quote):
    with operation_execution(operation['operation_id']):
        return _drive_steps(operation,quote)


def _drive_steps(operation,quote):
    from automation_policy import load_policy
    from .adapters import region_step,dispatch_base
    db=ledger()
    operation_id=operation['operation_id']
    if db.get('operations',operation_id)['status'] in TERMINAL_CLOSE_STATUS:
        return _reconcile(operation_id)
    curve = write_protocol(operation['bundle']) == CURVE_WRITE_PROTOCOL
    if curve and curve_dispatch_platforms(operation['bundle']) != operation['dispatch_context']['selected']:
        raise ValueError('pricing_curve_original_dispatch_scope_changed')
    for original in operation['steps']:
        current=db.get('operations',operation_id)
        step=next(s for s in current['steps'] if s['step_id']==original['step_id'])
        if step['state']=='CONFIRMED':
            continue
        if step.get('dispatched_at'):
            return _reconcile(operation_id)
        checked = verify_quote(quote,load_policy(),list(PLATFORMS),for_execution=True)
        if curve and checked != current['bundle']:
            raise ValueError('pricing_curve_original_dispatch_invalid')
        if step['kind']=='region':
            previous=[s for s in current['steps'][:current['steps'].index(step)] if s['kind']=='region' and s['state']=='CONFIRMED']
            if previous:
                step['expected_rule_set_sha256']=previous[-1]['receipt']['rule_set_sha256']
                db.put('operations',operation_id,current)
        claimed=db.claim_dispatch(operation_id,step['step_id'])
        if claimed is None:return _reconcile(operation_id)
        result=dispatch_base(db.get('operations',operation_id)) if step['kind']=='base' else region_step(operation_id,step['step_id'],write=True)
        if curve:
            op = db.step_result(operation_id, step['step_id'], 'UNKNOWN', result)
            return _reconcile_curve(op, retry_readback=False)
        db.step_result(operation_id,step['step_id'],'CONFIRMED' if result.get('status')=='CONFIRMED' else 'UNKNOWN',result)
        if result.get('status')!='CONFIRMED':return db.get('operations',operation_id)
    return _reconcile(operation_id)


def stop_unissued_and_exit(op,reason):
    """Retain unknown transports; cancel only unsent stages and confirm the actual partial state."""
    db=ledger();ident=op['operation_id']
    for step in op['steps']:
        if step['state']=='CONFIRMED':continue
        if step.get('dispatched_at') and (step.get('receipt',{}).get('status')!='NOT_SENT' or step.get('transport_claimed_at')):
            return op
    if not any(s['state']=='CONFIRMED' for s in op['steps']):return db.cancel_not_sent(ident,reason)
    with db.transaction() as conn:
        latest=db.get('operations',ident,conn)
        for step in latest['steps']:
            if step['state']=='CONFIRMED':continue
            step.setdefault('receipt_history',[]).append(dict(state=step.get('state'),receipt=step.get('receipt'),recorded_at=clock().isoformat()))
            step.update(state='CANCELLED_NOT_SENT',cancellation_reason=reason)
        latest.update(status='KNOWN_PARTIAL_PUBLIC_PENDING',stop_unissued_reason=reason)
        db.put('operations',ident,latest,conn)
    actual=deepcopy(latest['bundle']['before_action'])
    for step in latest['steps']:
        if step['state']=='CONFIRMED':actual=deepcopy(step['intermediate'])
    from .adapters import verify_known_partial
    receipt=verify_known_partial(latest,actual)
    if receipt['status']!='PUBLIC_CONFIRMED':
        latest['partial_readback']=receipt;db.put('operations',ident,latest);return latest
    plan=db.get('pricing_plans',latest['plan_id'])
    continuing=bool(plan and plan.get('state')=='ACTIVE' and
                    (not plan.get('ends_at') or clock()<instant(plan['ends_at'])))
    result=db.finish_known_partial(ident,receipt,actual,reason,exit_pending=not continuing)
    if not continuing:
        db.deadline(result['plan_id'],result['revision'])
        with db.transaction() as conn:
            conn.execute("UPDATE durable_jobs SET due_at=? WHERE id=? AND state='queued'",(clock().isoformat(),'exit:'+result['plan_id']+':'+str(result['revision'])))
    return result


def _admin_observed_prices():
    """§6.3 条件 2 的取数：Admin 各平台 unit_price（每 K）。异常由调用方视为未知。

    ⚠️ 必须与 ``daily.collect_outcomes`` / ``sources.shared_context`` 走**同一条**
    共享 Admin 通道：``channel_source`` 与 ``p2pah_auth`` 都不在本仓库目录下，
    要先挂 ``/opt/fs-hermes-fc``，再挂 ``COLLECTOR``，并用服务端 token 绑定会话。

    缺任一步的后果（2026-10-28 上线实测）：``from channel_source import ...``
    直接 ``ModuleNotFoundError`` → 观测值恒为空 → 条件 2 永远
    ``admin_unit_price_mismatch`` → 已写成功、``sync_message`` 齐全的操作
    被反复判 ``keep``，租约不释放，后续改价全部排队。
    """
    import sys
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages as admin_pages,COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    from .admin_readback import read_admin_unit_prices
    session=auth.Session()
    token,_=auth.admin_token_from_service()
    if not token:
        session.close()
        raise ValueError('pricing_admin_readback_token_unavailable')
    session.bind_admin_token(token);del token
    try:
        return read_admin_unit_prices(session,pages=admin_pages)
    finally:
        session.close()


def _close_execution_audit(operation_id,audit,receipt,ledger_status):
    """把 executions/<id>.json 推到与账本同一终态（PR #588 review #3）。

    只收尾账本会让 price_writer 的 `unresolved_execution_exists` 扫描继续拦截下一轮。
    """
    from .order_close import closed_audit_state
    path=ROOT/'executions'/(operation_id+'.json')
    try:
        state=json.loads(path.read_text()) if path.exists() else dict(audit or {})
        write_json(path,closed_audit_state(state,receipt,ledger_status,clock().isoformat()))
        return dict(status='written',ledger_status=ledger_status)
    except Exception as exc:
        return dict(status='audit_write_failed',error=type(exc).__name__)


def complete_player_followup(operation,job=None):
    """Reuse the original V3 parent and deterministic Players follow-up after any completion path."""
    bundle=operation.get('bundle') or {}
    if operation.get('status')!='COMPLETED' or bundle.get('schema_version')!=VERSION or bundle.get('maintenance_purpose'):return operation
    if operation.get('target_not_completed') and not any(s.get('kind')=='base' and s.get('state')=='CONFIRMED' for s in operation.get('steps',[])):return operation
    try:
        original=ledger().get('operations',operation['operation_id'])
        if not original or original.get('status')!='COMPLETED':raise ValueError('player_sync_coin_not_confirmed')
        parent_id=original['bundle']['snapshot_id']
        if job is None:job=json.loads((ROOT/'jobs'/(parent_id+'.json')).read_text())
        if (job.get('job_id')!=parent_id or job.get('kind')!='v3_cycle' or
                (job.get('request') or {}).get('v3_operation_id')!=original['operation_id']):raise ValueError('player_sync_parent_mismatch')
        import fc27_cloud_worker as worker
        config=worker.load_player_sync_policy()
        receipt = original.get('readback') or {}
        platforms = (list(receipt['curve_results']) if receipt.get('write_protocol') == CURVE_WRITE_PROTOCOL
                     else receipt.get('public', {}).get('platforms', []))
        job.update(status='ready',v3_outcome=original,result=dict(status='confirmed',execution_id=original['operation_id'],
                   platforms=platforms))
        job.setdefault('completed_at',clock().isoformat())
        intent=job.setdefault('player_sync_intent',dict(enabled=config['enabled'],revision=config['revision']))
        worker.save_job(job)
        if intent.get('enabled') and config['enabled'] and intent.get('revision')==config['revision']:
            try:job['player_sync']=worker.enqueue_player_sync(job,config)
            except (OSError,ValueError) as exc:
                job['player_sync']=dict(status='pending',reason=type(exc).__name__,original_coin_execution_id=original['operation_id'])
            worker.save_job(job)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        # Coins has already completed; a Players persistence error must not invoke the old cancellation path.
        return dict(operation,player_sync_followup=dict(status='pending',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
    return operation


def close_on_order_admin(op,audit):
    """用「Order 成功反馈 + Admin 单价核对」收尾已发出的操作。

    只调用现有收尾函数（``finish`` / ``finish_known_partial``），不新增释放路径。
    证据不足时保持 UNKNOWN：不动租约、不新建操作、不重复下发。
    收尾后同步推进执行审计文件，避免只释放账本一侧。
    """
    from .order_close import build_receipt,evaluate_close,order_write_confirmed
    if write_protocol(op.get('bundle') or {}) == CURVE_WRITE_PROTOCOL or (audit or {}).get('write_protocol') == CURVE_WRITE_PROTOCOL:
        return op
    db=ledger();ident=op['operation_id']
    if not order_write_confirmed(audit):return op
    note=None
    try:
        observed=_admin_observed_prices()
    except Exception as exc:
        observed={};note='admin_readback_unavailable:'+type(exc).__name__
    decision=evaluate_close(op,audit,observed)
    if decision['action']=='keep':
        op['order_close']=dict(decision,detail=note)
        db.put('operations',ident,op)
        return op
    with db.transaction() as conn:
        latest=db.get('operations',ident,conn)
        for step in latest['steps']:
            if step['step_id']==decision['confirmed']:
                step.setdefault('receipt_history',[]).append(dict(state=step.get('state'),receipt=step.get('receipt'),recorded_at=clock().isoformat()))
                step.update(state='CONFIRMED',receipt=dict(execution_id=ident,status='CONFIRMED',confirmation_scope='Order_Admin'))
            elif step['step_id'] in decision['cancelled']:
                step.setdefault('receipt_history',[]).append(dict(state=step.get('state'),receipt=step.get('receipt'),recorded_at=clock().isoformat()))
                step.update(state='CANCELLED_NOT_SENT',cancellation_reason=decision['reason'])
        latest['order_close']=dict(decision,detail=note)
        db.put('operations',ident,latest,conn)
    latest=db.get('operations',ident)
    # 公开页/缓存刷新只做尽力而为：已有的结果直接复用，不重复调用
    postwrite=latest.get('postwrite_receipt')
    if not postwrite:
        try:
            from .adapters import reconcile_postwrite
            postwrite=reconcile_postwrite(latest,audit)
        except Exception as exc:
            postwrite=dict(status='postwrite_failed',error=type(exc).__name__)
    if (postwrite or {}).get('status')=='PUBLIC_CONFIRMED' and not decision['cancelled']:
        receipt=dict(postwrite,**{k:v for k,v in build_receipt(latest,audit,observed,decision,postwrite).items() if k!='status'})
        result=db.finish(ident,receipt)
    elif not decision['cancelled']:
        receipt=build_receipt(latest,audit,observed,decision,postwrite)
        result=db.finish(ident,receipt)
    else:
        receipt=build_receipt(latest,audit,observed,decision,postwrite)
        actual=deepcopy(latest['bundle']['before_action'])
        for step in latest['steps']:
            if step['state']=='CONFIRMED':actual=deepcopy(step['intermediate'])
        result=db.finish_known_partial(ident,receipt,actual,decision['reason'],exit_pending=False)
    audit_close=_close_execution_audit(ident,audit,receipt,result.get('status'))
    if audit_close.get('status')!='written':
        result=dict(result,execution_audit_close=audit_close)
    return complete_player_followup(result) if audit_close.get('status')=='written' else result


def _original_curve_audit(op, audit):
    return bool(isinstance(audit, dict) and audit.get('execution_id') == op['operation_id']
                and audit.get('write_protocol') == CURVE_WRITE_PROTOCOL
                and audit.get('pricing_decision_receipt') == op['bundle']
                and audit.get('selected') == op['dispatch_context']['selected'])


def unified_close_entry(op,audit):
    """Use the original operation's write protocol to close confirmed work.

    V6 uses the original F4 catalog, propagation and projection receipt.
    Scalar operations retain the Order+Admin proof from PR #588.
    """
    if write_protocol(op.get('bundle') or {}) == CURVE_WRITE_PROTOCOL:
        if op['status'] in TERMINAL_CLOSE_STATUS:
            return complete_player_followup(op)
        if _original_curve_audit(op, audit) and audit.get('status') == CURVE_REJECTED:
            ident = op['operation_id']
            receipt = dict(status=CURVE_REJECTED, operation_id=ident, execution_id=ident,
                           write_protocol=CURVE_WRITE_PROTOCOL, curve_results=audit['curve_results'])
            return ledger().finish_curve_rejection(ident, receipt)
        if not _original_curve_audit(op, audit) or audit.get('status') != 'CONFIRMED':
            return None
        step, = op['steps']
        if not step.get('dispatched_at'):
            return None
        ident = op['operation_id']
        results = audit.get('curve_results') or {}
        if set(results) != set(op['bundle']['affected_platforms']) or set(results) != set(audit['selected']):
            raise ValueError('pricing_curve_original_readback_scope_changed')
        receipt = dict(status='CONFIRMED', operation_id=ident, execution_id=ident,
                       write_protocol=CURVE_WRITE_PROTOCOL, confirmation_scope=CURVE_WRITE_PROTOCOL,
                       curve_results=results)
        confirmed_curve_window(dict(op, readback=receipt))
        db = ledger()
        if step['state'] != 'CONFIRMED' or step.get('receipt') != receipt:
            db.step_result(ident, step['step_id'], 'CONFIRMED', receipt)
        return db.finish(ident, receipt)
    from .order_close import order_write_confirmed
    if not audit or not order_write_confirmed(audit):
        return None
    return close_on_order_admin(op,audit)


TERMINAL_CLOSE_STATUS = ('COMPLETED','NO_CHANGE','CANCELLED_NOT_SENT',
                         'KNOWN_PARTIAL_EXIT_PENDING','KNOWN_PARTIAL_EXITED',CURVE_REJECTED)


def exit_or_close(op,audit,reason):
    """退出前先尝试 Order+Admin 收尾。

    授权过期（``pricing_authorization_expired``）、复算失败、公开页异常这类
    「事后才发现的坏消息」都不应该让**已经写成功**的操作走取消路径：
    先按 Order 反馈 + Admin 单价核对收尾，收不了才退回原有退出流程。
    收尾只记录既成事实，不授权任何新的写入。
    """
    if write_protocol(op.get('bundle') or {}) == CURVE_WRITE_PROTOCOL:
        return _reconcile_curve(op, retry_readback=False)
    try:
        closed=unified_close_entry(op,audit)
    except Exception:
        closed=None
    if closed is not None and closed.get('status') in TERMINAL_CLOSE_STATUS:
        return closed
    return stop_unissued_and_exit(op,reason)


def reconcile(operation_id):
    with operation_execution(operation_id):
        return _reconcile(operation_id)


def _reconcile_curve(op, *, retry_readback=True):
    """Recover claimed work from the original F4 audit and read-only transport."""
    from .adapters import reconcile_base

    db = ledger()
    ident = op['operation_id']
    if not op['steps']:
        return _verify_nochange(op, op['dispatch_context']['preview'])
    step, = op['steps']
    if not step.get('dispatched_at'):
        if retry_readback:
            quote = json.loads((ROOT/'quotes'/(op['bundle']['snapshot_id']+'.json')).read_text())
            return _drive_steps(op, quote)
        return op
    path = ROOT/'executions'/(ident+'.json')
    recovered = None
    audit = None
    try:
        audit = json.loads(path.read_text()) if path.exists() else None
        if (retry_readback and _original_curve_audit(op, audit)
                and audit.get('status') in ('RUNNING', 'UNCERTAIN', 'PARTIAL')):
            recovered = reconcile_base(op)
            updated = json.loads(path.read_text())
            if _original_curve_audit(op, updated):
                audit = updated
            else:
                recovered = dict(status='UNKNOWN', reason='pricing_curve_original_audit_changed')
    except (OSError, ValueError) as exc:
        recovered = dict(status='UNKNOWN', reason='pricing_curve_original_audit_unavailable',
                         error=type(exc).__name__)

    prior = step.get('receipt') or {}
    original = _original_curve_audit(op, audit)
    results = audit.get('curve_results') if original else None
    audited_not_sent = (original and proven_not_sent(audit) and isinstance(results, dict)
                        and set(results) == set(audit['selected']) and all(
        isinstance(row, dict) and row.get('operation_id') == ident and row.get('platform') == platform
        and isinstance(row.get('catalog'), dict) and isinstance(row.get('projection'), dict)
        and ('send_intent' not in row['catalog'] or row['catalog'].get('status') == 'not_sent')
        and 'post_response' not in row['catalog'] and 'send_intent' not in row['projection']
        for platform, row in results.items()))
    refused_before_send = (audit is None and recovered is None and prior.get('status') == 'NOT_SENT'
                           and prior.get('write_protocol') == CURVE_WRITE_PROTOCOL
                           and prior.get('execution_id', ident) == ident
                           and (prior.get('business_dispatch_started') is False or prior.get('exit_code') == 75))
    if (audited_not_sent or refused_before_send) and not step.get('transport_claimed_at'):
        receipt = dict(prior, status='NOT_SENT', write_protocol=CURVE_WRITE_PROTOCOL, execution_id=ident,
                       business_dispatch_started=False)
        db.step_result(ident, step['step_id'], 'UNKNOWN', receipt)
        return db.cancel_not_sent(ident, prior.get('reason') or 'pricing_curve_original_not_sent')

    receipt = dict(status='UNKNOWN', write_protocol=CURVE_WRITE_PROTOCOL, execution_id=ident,
                   reason='pricing_curve_original_audit_unconfirmed')
    if original:
        try:
            closed = unified_close_entry(op, audit)
        except (KeyError, TypeError, ValueError) as exc:
            receipt['reason'] = str(exc) if isinstance(exc, ValueError) else 'pricing_curve_original_receipt_invalid'
        else:
            if closed is not None:
                return complete_player_followup(closed)
        receipt['curve_results'] = results or {}
        if audit.get('status') == 'PARTIAL':
            receipt.update(status='PARTIAL', reason='pricing_curve_original_partial')
    elif prior.get('status') == 'PARTIAL':
        receipt.update(status='PARTIAL', curve_results=prior.get('curve_results') or {})
    if recovered is not None:
        receipt['recovery'] = recovered
    state = 'PARTIALLY_APPLIED' if receipt['status'] == 'PARTIAL' else 'UNKNOWN'
    if step['state'] == state and prior == receipt:
        return op
    return db.step_result(ident, step['step_id'], state, receipt)


def _reconcile(operation_id):
    """Never repeat a base save or sync; recover only original post-write stages."""
    db=ledger()
    op=db.get('operations',operation_id)
    if not op:
        raise ValueError('pricing_operation_missing')
    if op['status'] in TERMINAL_CLOSE_STATUS:return complete_player_followup(op)
    if write_protocol(op.get('bundle') or {}) == CURVE_WRITE_PROTOCOL:
        return _reconcile_curve(op)
    audit_path=ROOT/'executions'/(operation_id+'.json')
    audit=json.loads(audit_path.read_text()) if audit_path.exists() else None
    if op['status']=='KNOWN_PARTIAL_PUBLIC_PENDING':return exit_or_close(op,audit,op['stop_unissued_reason'])
    if not op['steps']:
        return _verify_nochange(op,op.get('readback',{}).get('preview') or op.get('dispatch_context',{}).get('preview',{}))
    from .adapters import region_step,dispatch_base,reconcile_base
    for step in op['steps']:
        if step['kind']=='base' and step.get('dispatched_at') and step['state']!='CONFIRMED':
            if step.get('receipt',{}).get('status')=='NOT_SENT' or proven_not_sent(audit):
                path=ROOT/'quotes'/(op['bundle']['snapshot_id']+'.json')
                from automation_policy import load_policy
                try:verify_quote(json.loads(path.read_text()),load_policy(),list(PLATFORMS),for_execution=True)
                except ValueError as exc:
                    return exit_or_close(op,audit,str(exc))
                result=dispatch_base(op)
                db.step_result(operation_id,step['step_id'],'CONFIRMED' if result.get('status')=='CONFIRMED' else 'UNKNOWN',result)
    op=db.get('operations',operation_id)
    if audit_path.exists():
        audit=json.loads(audit_path.read_text())
        if audit.get('status')!='CONFIRMED' or audit.get('sync_confirmed') is not True or audit.get('all_baseline',{}).get('status')!='confirmed':
            recovered=reconcile_base(op)
            if audit_path.exists():audit=json.loads(audit_path.read_text())
            if recovered.get('status') not in ('CONFIRMED','confirmed'):
                op['recovery_status']=recovered
                db.put('operations',operation_id,op)
                if recovered.get('reason')=='requires_fresh_postwrite_authorization' and not op.get('auto_postwrite_stopped'):
                    with db.connect() as conn:
                        pending=any(json.loads(r[0]).get('operation_id')==operation_id for r in conn.execute("SELECT body FROM durable_jobs WHERE kind='postwrite_refresh' AND state IN ('queued','running')"))
                    if not pending:db.enqueue('postwrite_refresh','postwrite-refresh:'+operation_id+':'+str(int(clock().timestamp())//300),clock(),dict(operation_id=operation_id))
    for step in op['steps']:
        if step['kind']=='region' and step.get('dispatched_at') and step['state']!='CONFIRMED':
            result=region_step(operation_id,step['step_id'])
            if result.get('status')!='CONFIRMED' and step.get('receipt',{}).get('status')=='NOT_SENT' and not step.get('transport_claimed_at'):
                from automation_policy import load_policy
                try:verify_quote(json.loads((ROOT/'quotes'/(op['bundle']['snapshot_id']+'.json')).read_text()),load_policy(),list(PLATFORMS),for_execution=True)
                except ValueError as exc:
                    return exit_or_close(op,audit,str(exc))
                result=region_step(operation_id,step['step_id'],write=True)
            if result.get('status')=='CONFIRMED':
                db.step_result(operation_id,step['step_id'],'CONFIRMED',result)
    op=db.get('operations',operation_id)
    if any(s['state']!='CONFIRMED' for s in op['steps']) and any(s['state']=='CONFIRMED' for s in op['steps']):
        if clock()>=instant(op['bundle']['valid_until']):return exit_or_close(op,audit,'pricing_authorization_expired')
    if audit and audit.get('status')=='CONFIRMED' and audit.get('sync_confirmed') is True and audit.get('all_baseline',{}).get('status')=='confirmed':
        for step in op['steps']:
            if step['kind']=='base':
                db.step_result(operation_id,step['step_id'],'CONFIRMED',dict(execution_id=operation_id,status='CONFIRMED',confirmation_scope='Order_Admin_ALL'))
        from .adapters import reconcile_postwrite
        # 公开页/缓存异常不应中断收尾：记下来交给后面的统一收尾判据
        try:
            post=reconcile_postwrite(op,audit)
        except Exception as exc:
            post=dict(status='postwrite_failed',error=type(exc).__name__)
        if post['status']=='PUBLIC_CONFIRMED':
            return complete_player_followup(db.finish(operation_id,post))
        op=db.get('operations',operation_id)
        op.update(status=post['status'],readback=post,postwrite_receipt=post)
        db.put('operations',operation_id,op)
    elif not any(s['kind']=='base' for s in op['steps']) and all(s['state']=='CONFIRMED' for s in op['steps']):
        from .adapters import reconcile_postwrite
        post=reconcile_postwrite(op,None)
        if post['status']=='PUBLIC_CONFIRMED':return complete_player_followup(db.finish(operation_id,post))
        op.update(status=post['status'],readback=post)
        db.put('operations',operation_id,op)
    # 2026-10-28: Order+Admin 统一收尾入口（DECOUPLE-DESIGN §6.4）。
    # 不再排除旧的「audit 全绿」路径：Order 与 ALL 都成功、只有公开页没确认时也要能收尾。
    op=db.get('operations',operation_id)
    closed=unified_close_entry(op,audit)
    if closed is not None:
        if closed.get('status') in TERMINAL_CLOSE_STATUS:
            return closed
        op=closed
    op=db.get('operations',operation_id)
    if any(not s.get('dispatched_at') for s in op['steps']) and all(s['state']=='CONFIRMED' for s in op['steps'] if s.get('dispatched_at')):
        path=ROOT/'quotes'/(op['bundle']['snapshot_id']+'.json')
        quote=json.loads(path.read_text())
        from automation_policy import load_policy
        try:verify_quote(quote,load_policy(),list(PLATFORMS),for_execution=True)
        except ValueError as exc:
            return exit_or_close(op,audit,str(exc))
        return _drive_steps(op,quote)
    # An uncertain original mechanical request is not converted to a fresh execution.
    return db.get('operations',operation_id)
