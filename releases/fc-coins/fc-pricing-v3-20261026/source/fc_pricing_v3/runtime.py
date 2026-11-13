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
from .dispatch import CURVE_WRITE_PROTOCOL, proven_not_sent, write_protocol
from .engine import evaluate, financial, competition, commit_path, impacted_regions, proof_regions, GROUPS, PLATFORMS, market_quote, sprint_parameters, SPRINT_POLICY_VERSION
from .financial import fingerprint, number, instant, MARGIN_BASIS, HARD_MARGIN, FINANCIAL_CONTRACT_VERSION, LEGACY_FINANCIAL_CONTRACT_VERSION, HISTORY_WINDOW_CONTRACT, required_history_ratio
from .ledger import Ledger, clock, confirmed_curve_window
from .engine import controlled_candidate, current_action

ROOT = Path(os.environ.get('FC27_V3_ROOT','/var/lib/fc27-cloud'))
STORE = ROOT/'v3'


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
    job_path=ROOT/'jobs'/(run_id+'.json')
    job=json.loads(job_path.read_text()) if job_path.exists() else {}
    plan_id=(job.get('request') or {}).get('v3_plan_id')
    plan=db.get('pricing_plans',plan_id) if plan_id else db.active_plan()
    resources=(plan or {}).get('resources',[])
    regions=sorted({int(r.split(':')[1]) for r in resources if r.startswith('region:')})
    from automation_policy import load_policy
    parameters=(plan or {}).get('parameters',{})
    return dict(active_mode=(plan or {}).get('mode','revenue_sprint'),scope=dict(
        platforms=list(PLATFORMS),region_ids=regions,interval_minutes=load_policy()['interval_minutes'],
        **{k:parameters[k] for k in ('competitor_policy','region_pricing') if k in parameters}))


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


def preview_curve(snapshot, platform, *, requested_snapshot_id=None, strategy_state=None):
    """Read one platform's current saved catalogue without opening a pricing operation."""
    from coin_all_sync_job import PRODUCTS, read_row
    from fc_shared_admin import SessionManager, read_private_config
    from .admin_readback import GID_FC27, MID_FC27_COINS, SITE_MAIN
    from .price_curve import curve_key, quote_native, read_curve
    from .pricing_proof_v6 import CONTRACT, INCOMPLETE

    gaps = ['customer_checkout_unverified', 'offer_path_unverified', 'necessary_fee_unverified',
            'validation_domain_unverified', 'procurement_time_unverified', 'planning_baskets_unverified']
    decision = dict(financial_contract=CONTRACT, selected=None, gaps=gaps)
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
    _, goods_id, aid = PRODUCTS[platform]
    own = (evidence.get('storefront') or {}).get('rows', {}).get(platform) or {}
    if str(own.get('sku_id')) != str(goods_id):
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
    return result


def calculate(evidence, edits=None, *, selected_action=None,override_reason=None,operation_id=None):
    edits = edits or {}
    if edits.get('costs') or edits.get('offers') or edits.get('quotes'):
        raise ValueError('pricing_legacy_edits_retired_use_v3_evaluate')
    db = ledger()
    job_path=ROOT/'jobs'/(evidence['run_id']+'.json')
    job=json.loads(job_path.read_text()) if job_path.exists() else {}
    plan_id=(job.get('request') or {}).get('v3_plan_id')
    plan = db.get('pricing_plans',plan_id) if plan_id else db.active_plan()
    now = clock()
    if (job.get('request') or {}).get('v3_authorization_purpose')=='original_unsent_ALL_steps_only':
        [required_history_ratio(evidence,now,platform=p,require_current=True) for p in PLATFORMS]
        return calculate_postwrite(evidence,job,db)
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
    if for_execution and write_protocol(receipt) == CURVE_WRITE_PROTOCOL:
        raise ValueError('pricing_curve_execution_verifier_unavailable')
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
                         'KNOWN_PARTIAL_EXIT_PENDING','KNOWN_PARTIAL_EXITED')


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
    if op['status'] in ('COMPLETED','NO_CHANGE','CANCELLED_NOT_SENT','KNOWN_PARTIAL_EXIT_PENDING','KNOWN_PARTIAL_EXITED'):return complete_player_followup(op)
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
