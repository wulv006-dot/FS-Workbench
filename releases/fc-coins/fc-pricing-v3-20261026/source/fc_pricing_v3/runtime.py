"""One FC coordinator, using the existing collection and mechanical writer adapters."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import uuid

from . import VERSION, PROGRAM_CONTRACT
from .engine import evaluate, financial, competition, commit_path, impacted_regions, proof_regions, GROUPS, PLATFORMS, market_quote, sprint_parameters, SPRINT_POLICY_VERSION
from .financial import fingerprint, number, instant, MARGIN_BASIS, HARD_MARGIN, FINANCIAL_CONTRACT_VERSION
from .ledger import Ledger, clock

ROOT = Path(os.environ.get('FC27_V3_ROOT','/var/lib/fc27-cloud'))
STORE = ROOT/'v3'


def ledger():
    return Ledger(STORE/'control.sqlite3')


def current_history_mix(now):
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
    return checked_history_cache(cache,selective_history_signature(history_period(now)),now)['historical_discount_mix']


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
    return dict(active_mode=(plan or {}).get('mode','revenue_sprint'),scope=dict(
        platforms=list(PLATFORMS),region_ids=regions,interval_minutes=load_policy()['interval_minutes']))


def context(evidence):
    """Source results are attached once to the immutable quote snapshot."""
    from .sources import collect_context
    db=ledger()
    scope=collection_scope(db,evidence['run_id'])
    envelope=collect_context(dict(evidence,price_windows=db.all('actual_price_windows'),
        active_mode=scope['active_mode'],active_scope=scope['scope'],
        history_cache=db.get('metadata','seven_day_history_cache'),online_context=db.get('metadata','daily_online_context')))
    for key,value in envelope['private_updates'].items():
        if key!='history_cache':raise ValueError('pricing_private_source_update_invalid')
        db.put('metadata','seven_day_history_cache',value)
    result=dict(evidence,**envelope['context'])
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


def sprint_anchor_context(db,plan,now):
    """One common saved baseline, plus the original entry basis during a cost response."""
    baseline=None
    for snapshot in sorted(db.all('pricing_snapshots'),key=lambda s:s.get('created_at','')):
        at=instant(snapshot.get('created_at') or snapshot['evidence']['checked_at'])
        if not 0<(now-at).total_seconds()<=21600:continue
        old=snapshot['evidence']
        try:
            from .financial import common_cost
            pooled,_=common_cost(old)
            quotes={p:{s:market_quote(old,p,s,at) for s in ('Lootbar','ItemD2R')} for p in PLATFORMS}
            costs={p:str((pooled if p!='PC' else number(old['costs']['PC']['cny_per_1k']))/number(old['fx']['cny_per_usd'])) for p in PLATFORMS}
        except (ValueError,KeyError):continue
        baseline=dict(snapshot_id=snapshot['snapshot_id'],created_at=at.isoformat(),quotes=quotes,costs=costs,source_sha256=fingerprint(old))
        break
    previous=max((r for r in db.all('market_comparisons') if r.get('plan_id')==(plan or {}).get('plan_id') and r.get('sprint_policy_version')==SPRINT_POLICY_VERSION),key=lambda r:r['created_at'],default={})
    if plan and plan.get('paused_at') and previous and instant(previous['created_at'])<=instant(plan['paused_at']):previous={}
    context={}
    for p in PLATFORMS:
        group='pc' if p=='PC' else 'console'
        prior=((previous.get('groups') or {}).get(group) or {}).get('anchors',{}).get(p)
        base=dict(snapshot_id=baseline['snapshot_id'],created_at=baseline['created_at'],quotes=baseline['quotes'][p],cost_usd_per_k=baseline['costs'][p],source_sha256=baseline['source_sha256']) if baseline else None
        context[p]=dict(baseline=base,previous=prior)
    return context


def calculate(evidence, edits=None, *, selected_action=None,override_reason=None,operation_id=None):
    edits = edits or {}
    if edits.get('costs') or edits.get('offers') or edits.get('quotes'):
        raise ValueError('pricing_legacy_edits_retired_use_v3_evaluate')
    db = ledger()
    job_path=ROOT/'jobs'/(evidence['run_id']+'.json')
    job=json.loads(job_path.read_text()) if job_path.exists() else {}
    plan_id=(job.get('request') or {}).get('v3_plan_id')
    plan = db.get('pricing_plans',plan_id) if plan_id else db.active_plan()
    from .uk_retirement import PURPOSE as UK_RETIREMENT,calculate as calculate_uk_retirement
    if (job.get('request') or {}).get('v3_authorization_purpose')==UK_RETIREMENT:
        return calculate_uk_retirement(evidence,job,db)
    if (job.get('request') or {}).get('v3_authorization_purpose')=='original_unsent_ALL_steps_only':
        return calculate_postwrite(evidence,job,db)
    mode = plan['mode'] if plan else 'revenue_sprint'
    now = clock()
    if plan and plan.get('financial_contract_version')!=FINANCIAL_CONTRACT_VERSION:
        raise ValueError('pricing_financial_plan_migration_required')
    if mode=='revenue_sprint':evidence['sprint_anchor_context']=sprint_anchor_context(db,plan,now)
    evaluations = {mode:evaluate(evidence,mode,plan=plan,now=now)}
    evaluation = evaluations[mode]
    if not evaluation['candidates']:
        result=dict(checked_at=evidence['checked_at'],rows=[],strategy_version=VERSION,status=evaluation['status'],
            execution_authorized=False,decision_receipt=dict(schema_version=VERSION,mode=mode,plan_id=(plan or {}).get('plan_id'),
                financial_contract_version=FINANCIAL_CONTRACT_VERSION,review_contract=PROGRAM_CONTRACT,
                decision_source='program_current_strategy_infeasible',per_cycle_model_required=False,execution_authorized=False,status=evaluation['status']))
        publish_snapshot(db,evidence,result,evaluations,plan,now)
        raise ValueError('pricing_v3_'+evaluation['status'].lower()+':'+','.join(sorted({e['code'] for e in evaluation['failures']}))[:250])
    if selected_action is not None:
        selected=next((c for c in evaluation['candidates'] if c['action']==selected_action),None)
        if selected is None:
            explicit=evaluate(evidence,mode,plan=plan,now=now,explicit_prices=selected_action['base_prices'])
            selected=next((c for c in explicit['candidates'] if c['action']==selected_action),None)
        if selected is None:raise ValueError('pricing_override_not_currently_feasible')
        prior=db.assignment(plan,evaluation['candidates'],now=now) if plan else None
        allocation=db.override_assignment(plan,prior,selected,override_reason) if prior else dict(assignment_id=str(uuid.uuid4()),action=selected_action,ends_at=evaluation['valid_until'],
                        deterministic=True,labels=['explicit_override'],parent_assignment_id=(prior or {}).get('assignment_id'),
                        original_assignment=prior,deviation_reason=override_reason)
        db.put('experiment_assignments',allocation['assignment_id'],allocation)
    elif plan:
        allocation = db.assignment(plan,evaluation['candidates'],now=now)
        selected = next(c for c in evaluation['candidates'] if c['action']==allocation['action'])
    else:
        selected = evaluation['selected']
        allocation = dict(assignment_id=None,action=selected['action'],ends_at=evaluation['valid_until'],
                          deterministic=True,labels=['read_only_unowned'])
    action = selected['action']
    relevant_regions=impacted_regions(evidence,evaluation['current'],action,promised_regions=selected.get('regional_market_comparison',{}))
    steps=deepcopy(selected['steps'])
    for step in steps:
        if step['kind']=='region':
            region=next(r for r in evidence['regional_controls'] if str(r['region_id'])+':'+r['platforms'][0]==step['key'])
            step.update(scope=region['scope'],expected_rule_set_sha256=region['expected_rule_set_sha256'])
    mutable_resources=sorted({'base:'+g for g in GROUPS if action['base_prices'][g]!=evaluation['current']['base_prices'][g]} |
                            {'region:'+key for key,factor in action.get('region_coefficients',{}).items() if factor!=evaluation['current'].get('region_coefficients',{}).get(key,'1')})
    resources = sorted(set(mutable_resources or (plan or {}).get('resources') or ['base:console','base:pc']) |
                       {r.get('resource','region_rule:'+str(r['id'])) for r in relevant_regions} |
                       {'base:'+('pc' if p=='PC' else 'console') for r in relevant_regions for p in r['platforms']
                        if any(key.startswith('region:'+str(r['region_id'])+':') for key in mutable_resources)})
    valid = min(instant(evaluation['valid_until']),instant(allocation['ends_at']))
    bundle = dict(schema_version=VERSION,decision_bundle_id=operation_id or (job.get('request') or {}).get('v3_operation_id') or str(uuid.uuid4()),
        snapshot_id=evidence['run_id'],snapshot_sha256=fingerprint(evidence),mode=mode,
        plan_id=(plan or {}).get('plan_id'),revision=(plan or {}).get('revision'),
        engine_generation=(plan or {}).get('generation'),assignment_id=allocation['assignment_id'],
        action=action,before_action=evaluation['current'],resources=resources,readback_regions=[dict(region_id=r['region_id'],platforms=[p for p in r['platforms'] if 'base:'+('pc' if p=='PC' else 'console') in (mutable_resources or (plan or {}).get('resources',[])) or 'region:'+str(r['region_id'])+':'+p in mutable_resources]) for r in relevant_regions],mutable_resources=mutable_resources or list((plan or {}).get('resources') or []),steps=steps,region_rule_ids=[r['id'] for r in relevant_regions],region_proof_resources=[r.get('resource','region_rule:'+str(r['id'])) for r in relevant_regions],created_at=now.isoformat(),valid_until=valid.isoformat(),
        catalog=evidence['promotion_envelope']['packages'],budget_reference=evidence.get('budget_reference',{}),
        affected_platforms=sorted({p for g,ps in GROUPS.items() if 'base:'+g in (mutable_resources or (plan or {}).get('resources',[])) for p in ps} | {r.split(':')[-1] for r in mutable_resources if r.startswith('region:')}),
        assignment_probability=allocation.get('probabilities',{}).get(fingerprint(action),1),
        randomization_verified=bool(allocation.get('probabilities') and len(allocation['probabilities'])>1 and not allocation.get('effective_choice')),
        financial_proof=selected['financial_proof'],market_comparison=selected['market_comparison'],regional_market_comparison=selected.get('regional_market_comparison',{}),
        financial_contract_version=FINANCIAL_CONTRACT_VERSION,sprint_policy_version=SPRINT_POLICY_VERSION if mode=='revenue_sprint' else None,
        strategy_parameters=sprint_parameters(plan) if mode=='revenue_sprint' else (plan or {}).get('parameters',{}),
        authorized_resources=(plan or {}).get('resources',[]),decision_type=selected.get('decision_type'),decision_reason=selected.get('decision_reason'),
        market_position=selected.get('market_position'),minimum_legal_price_proof=selected.get('minimum_legal_price_proof'),
        strategy_decision=selected['score'],allocation=allocation,
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
        group='pc' if p=='PC' else 'console'
        fp=selected['financial_proof']['prices']['global:'+p]
        cost=evidence['costs'][p]
        own=evidence['storefront']['rows'][p]
        target=number(action['base_prices'][group])
        public_anchor=evidence['offers'][p]['Lootbar']
        offers=[dict(source=s,**value) for s,value in evidence['offers'][p].items()]
        rows.append(dict(platform=p,proposal=format(target/100,'.4f'),auto_proposal=format(target/100,'.4f'),
            raw_cost_cny=cost['cny_per_1k'],cost_cny=cost['cny_per_1k'],raw_cost_record_id=cost['record_id'],
            raw_cost_trade_at=cost['trade_at'],cost_record_id=cost['record_id'],cost_trade_at=cost['trade_at'],
            target_page_usd=str(target),floor_usd_per_1k=fp['catalog']['minimum_unit_usd'],
            offers=offers,missing=[],proof=dict(fp['proof'],catalog=fp['catalog']),
            estimated_average_margin=fp['average'],margin_basis=MARGIN_BASIS,
            minimum_gross_margin_pct=str(HARD_MARGIN),margin_below_minimum=False,auto_blocked_reason=None,
            decision_type=selected.get('decision_type'),financial_contract_version=FINANCIAL_CONTRACT_VERSION,
            gross_margin_pct=fp['proof']['procurement_margin_pct'],pricing_mode=mode,pricing_tier=None,
            requested_discount_pct=None,profit_floor_applied=False,pricing_basis='page_total_100k',
            strategy_version=VERSION,quote_manual=False,own_bonus_k=own['bonus_k'],
            decision_reason=selected.get('decision_reason') or mode+'_objective',ending_reason='v3_exact_no_hidden_adjustment',
            pricing_quantity_basis='both_sides_actual_delivered_quantity',
            lootbar_page_usd=public_anchor['usd_price'],
            lootbar_usd_per_1k=str(number(public_anchor['usd_price'])/(number(public_anchor['base_k'])+number(public_anchor.get('bonus_k','0'),zero=True))),
            change_pct=str((target/number(own['package_usd'])-1)*100),
            warning='双20%红线；单笔合法优惠仍可亏损。预测不是实绩。',status='财务底价兜底 · 未达到竞争降幅' if selected.get('decision_type')=='floor_fallback' else '双模式引擎核算通过 · 待执行'))
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
    if set(actual)!=set(PLATFORMS) or number(actual['PS'])!=number(actual['XBOX']):raise ValueError('pricing_postwrite_actual_scope_invalid')
    base=dict(console=actual['PS'],pc=actual['PC'])
    if any(number(base[g])!=number(op['bundle']['action']['base_prices'][g]) for g in GROUPS):raise ValueError('pricing_postwrite_actual_price_changed')
    base=deepcopy(op['bundle']['action']['base_prices'])
    action=dict(base_prices=base,region_coefficients={str(r['region_id'])+':'+p:r['factor'] for r in evidence.get('region_rules',[])+evidence.get('regional_controls',[]) for p in r['platforms']})
    now=clock();regions=proof_regions(evidence,action,action)
    for region in evidence.get('region_rules',[]):
        if region not in regions:regions.append(region)
    proof=financial(evidence,action,now,regions=regions)
    bundle=dict(schema_version=VERSION,authorization_purpose='original_unsent_ALL_steps_only',decision_bundle_id=operation_id,
        original_operation_id=operation_id,snapshot_id=evidence['run_id'],snapshot_sha256=fingerprint(evidence),mode='postwrite_completion',
        plan_id=plan['plan_id'],revision=plan['revision'],engine_generation=plan['generation'],assignment_id=op['bundle'].get('assignment_id'),
        action=action,before_action=action,resources=op['resources'],mutable_resources=op['bundle'].get('mutable_resources',op['resources']),
        steps=[],created_at=now.isoformat(),valid_until=(now+timedelta(minutes=15)).isoformat(),financial_proof=proof,financial_contract_version=FINANCIAL_CONTRACT_VERSION,
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
    if not selected or set(selected)-set(PLATFORMS) or set(selected)&{'PS','XBOX'} and not {'PS','XBOX'}<=set(selected):
        raise ValueError('pricing_common_console_scope_required')
    if number(policy['minimum_gross_margin_pct'])!=HARD_MARGIN:
        raise ValueError('pricing_margin_contract_changed')
    if receipt.get('financial_contract_version')!=FINANCIAL_CONTRACT_VERSION:
        raise ValueError('pricing_financial_quote_migration_required')
    from .uk_retirement import PURPOSE as UK_RETIREMENT,authority_resources
    maintenance=receipt.get('maintenance_purpose')==UK_RETIREMENT
    regions=quote['evidence'].get('region_rules',[])
    if maintenance:
        authority_resources(receipt)
        regions=regions+quote['evidence'].get('regional_controls',[])
        if financial(quote['evidence'],receipt['before_action'],now,regions=regions)!=receipt['before_financial_proof']:
            raise ValueError('pricing_uk_retirement_before_proof_changed')
    elif purpose!='original_unsent_ALL_steps_only':regions=proof_regions(quote['evidence'],receipt['before_action'],receipt['action'],promised_regions=receipt.get('regional_market_comparison',{}))
    proof=financial(quote['evidence'],receipt['action'],now,regions=regions)
    if proof!=receipt['financial_proof']:
        raise ValueError('pricing_financial_proof_changed')
    for row in quote['result']['rows']:
        group='pc' if row['platform']=='PC' else 'console'
        if number(row['proposal'])*100!=number(receipt['action']['base_prices'][group]):
            raise ValueError('pricing_action_row_changed')
    if receipt['mode']=='revenue_sprint':
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
            group='pc' if platform=='PC' else 'console'
            market=competition(quote['evidence'],[platform],now,region=21,plan=market_plan,resolved_global=markets[group],base_total=receipt['action']['base_prices'][group])
            if market!=prior:raise ValueError('pricing_regional_market_proof_changed')
            price=number(proof['prices'][key]['price']['delivered_unit_100k'])
            limits=market['targets'][platform]
            if market['decision_type']=='floor_fallback':
                if receipt.get('decision_type')!='floor_fallback' or receipt['action']['region_coefficients'][key] not in market['legal_coefficients']:raise ValueError('pricing_regional_fallback_not_minimum_legal_price')
            elif market['decision_type']=='regional_follow_global':
                if number(receipt['action']['region_coefficients'][key])!=1:raise ValueError('pricing_saudi_missing_quote_must_follow_global')
            elif not number(limits['unit_low'])<=price<=number(limits['unit_high']):raise ValueError('pricing_regional_competitive_band')
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


def execute_run(run_id):
    import fc27_cloud_worker as worker
    db=ledger()
    quote=json.loads((ROOT/'quotes'/(run_id+'.json')).read_text())
    from automation_policy import load_policy
    bundle=verify_quote(quote,load_policy(),list(PLATFORMS),for_execution=True)
    plan=db.get('pricing_plans',bundle['plan_id'])
    existing=db.get('operations',bundle['decision_bundle_id'])
    if existing:
        return existing if existing['status'] in ('COMPLETED','NO_CHANGE') else reconcile(existing['operation_id'])
    code,preview=worker.run([str(worker.APP/'preview_backend.sh'),run_id],85)
    if code or preview.get('status')!='review_only':
        raise ValueError('pricing_backend_preview_failed')
    job=json.loads((ROOT/'jobs'/(run_id+'.json')).read_text())
    automatic=not job.get('request',{}).get('manual_requested')
    selected=[p for p in PLATFORMS if number(quote['evidence']['storefront']['rows'][p]['package_usd'])!=number(bundle['action']['base_prices']['pc' if p=='PC' else 'console'])]
    if set(selected)&{'PS','XBOX'}:
        selected=[p for p in PLATFORMS if p in set(selected)|{'PS','XBOX'}]
    operation=db.prepare(plan,bundle,dispatch_context=dict(preview=preview,selected=selected,automatic=automatic,
                         actor=job['actor'] if not automatic else 'system-automation',policy_revision=load_policy()['revision']))
    if not bundle['steps']:
        from .adapters import verify_nochange
        receipt=verify_nochange(operation,preview)
        if receipt['status']!='PUBLIC_CONFIRMED':
            operation.update(status='PUBLIC_PENDING',readback=receipt)
            db.put('operations',operation['operation_id'],operation)
            return operation
        return db.finish(operation['operation_id'],receipt,no_change=True)
    return drive_steps(operation,quote)


def drive_steps(operation,quote):
    from automation_policy import load_policy
    from .adapters import region_step,dispatch_base
    db=ledger()
    operation_id=operation['operation_id']
    for original in operation['steps']:
        current=db.get('operations',operation_id)
        step=next(s for s in current['steps'] if s['step_id']==original['step_id'])
        if step['state']=='CONFIRMED':
            continue
        if step.get('dispatched_at'):
            return reconcile(operation_id)
        verify_quote(quote,load_policy(),list(PLATFORMS),for_execution=True)
        if step['kind']=='region':
            previous=[s for s in current['steps'][:current['steps'].index(step)] if s['kind']=='region' and s['state']=='CONFIRMED']
            if previous:
                step['expected_rule_set_sha256']=previous[-1]['receipt']['rule_set_sha256']
                db.put('operations',operation_id,current)
        claimed=db.claim_dispatch(operation_id,step['step_id'])
        if claimed is None:return reconcile(operation_id)
        result=dispatch_base(db.get('operations',operation_id)) if step['kind']=='base' else region_step(operation_id,step['step_id'],write=True)
        db.step_result(operation_id,step['step_id'],'CONFIRMED' if result.get('status')=='CONFIRMED' else 'UNKNOWN',result)
        if result.get('status')!='CONFIRMED':return db.get('operations',operation_id)
    return reconcile(operation_id)


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
    result=db.finish_known_partial(ident,receipt,actual,reason)
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


def close_on_order_admin(op,audit):
    """用「Order 成功反馈 + Admin 单价核对」收尾已发出的操作。

    只调用现有收尾函数（``finish`` / ``finish_known_partial``），不新增释放路径。
    证据不足时保持 UNKNOWN：不动租约、不新建操作、不重复下发。
    收尾后同步推进执行审计文件，避免只释放账本一侧。
    """
    from .order_close import build_receipt,evaluate_close,order_write_confirmed
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
        result=db.finish(ident,postwrite);receipt=postwrite
    elif not decision['cancelled']:
        receipt=build_receipt(latest,audit,observed,decision,postwrite)
        result=db.finish(ident,receipt)
    else:
        receipt=build_receipt(latest,audit,observed,decision,postwrite)
        actual=deepcopy(latest['bundle']['before_action'])
        for step in latest['steps']:
            if step['state']=='CONFIRMED':actual=deepcopy(step['intermediate'])
        result=db.finish_known_partial(ident,receipt,actual,decision['reason'])
        if result.get('plan_id') and result.get('revision') is not None:
            db.deadline(result['plan_id'],result['revision'])
    audit_close=_close_execution_audit(ident,audit,receipt,result.get('status'))
    if audit_close.get('status')!='written':
        result=dict(result,execution_audit_close=audit_close)
    return result


def unified_close_entry(op,audit):
    """Order+Admin 统一收尾入口。

    不看旧的 ``all_baseline`` / 公开页状态：只要拿到 Order 成功反馈就尝试收尾，
    公开页仅作为回执里的记录。这样「Order 与 ALL 都成功但公开页没确认」也能收尾
    （PR #588 review #2）。
    """
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
    try:
        closed=unified_close_entry(op,audit)
    except Exception:
        closed=None
    if closed is not None and closed.get('status') in TERMINAL_CLOSE_STATUS:
        return closed
    return stop_unissued_and_exit(op,reason)


def reconcile(operation_id):
    """Never repeat a base save or sync; recover only original post-write stages."""
    db=ledger()
    op=db.get('operations',operation_id)
    if not op:
        raise ValueError('pricing_operation_missing')
    if op['status'] in ('COMPLETED','NO_CHANGE','CANCELLED_NOT_SENT','KNOWN_PARTIAL_EXIT_PENDING','KNOWN_PARTIAL_EXITED'):return op
    audit_path=ROOT/'executions'/(operation_id+'.json')
    audit=json.loads(audit_path.read_text()) if audit_path.exists() else None
    if op['status']=='KNOWN_PARTIAL_PUBLIC_PENDING':return exit_or_close(op,audit,op['stop_unissued_reason'])
    if not op['steps'] and op['status']=='PUBLIC_PENDING':
        from .adapters import verify_nochange
        receipt=verify_nochange(op,op.get('readback',{}).get('preview',{}))
        return db.finish(operation_id,receipt,no_change=True) if receipt['status']=='PUBLIC_CONFIRMED' else op
    from .adapters import region_step,dispatch_base,reconcile_base
    for step in op['steps']:
        if step['kind']=='base' and step.get('dispatched_at') and step['state']!='CONFIRMED':
            from .dispatch import proven_not_sent
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
            return db.finish(operation_id,post)
        op=db.get('operations',operation_id)
        op.update(status=post['status'],readback=post,postwrite_receipt=post)
        db.put('operations',operation_id,op)
    elif not any(s['kind']=='base' for s in op['steps']) and all(s['state']=='CONFIRMED' for s in op['steps']):
        from .adapters import reconcile_postwrite
        post=reconcile_postwrite(op,None)
        if post['status']=='PUBLIC_CONFIRMED':return db.finish(operation_id,post)
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
        return drive_steps(op,quote)
    # An uncertain original mechanical request is not converted to a fresh execution.
    return db.get('operations',operation_id)
