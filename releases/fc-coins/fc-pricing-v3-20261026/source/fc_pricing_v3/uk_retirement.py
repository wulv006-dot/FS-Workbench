"""Retire the one authorized UK rule through the existing operation and region writer."""
from copy import deepcopy
from datetime import timedelta
import json,uuid

from . import VERSION
from .platforms import PLATFORMS, PRICE_SCOPE_CONTRACT, groups_for
from .financial import FINANCIAL_CONTRACT_VERSION,MARGIN_BASIS,fingerprint,number,instant
from .region_source import rule_expectations

PURPOSE='retire_uk_discount_v1'
SCOPE=dict(site_id=266,lang_region_id=39,goods_id=0,gid=1327,top_cid=1,cid=0,sid=7645,aid=0)
RESOURCES=['region:39:'+p for p in ('PS','XBOX','PC')]


def authority_resources(bundle):
    if bundle.get('maintenance_purpose')!=PURPOSE:return bundle['mutable_resources'] if 'mutable_resources' in bundle else bundle['resources']
    steps=bundle.get('steps') or []
    if len(steps)!=1 or bundle.get('mutable_resources')!=RESOURCES:raise ValueError('pricing_uk_retirement_scope_changed')
    step=steps[0]
    if (step.get('kind')!='region' or step.get('scope')!=SCOPE or step.get('intent')!=PURPOSE or
            step.get('rule_id')!=1 or step.get('target_status')!=0 or number(step.get('value'))!=number('.91')):
        raise ValueError('pricing_uk_retirement_scope_changed')
    before=bundle['before_action'];after=bundle['action']
    if before['base_prices']!=after['base_prices']:raise ValueError('pricing_uk_retirement_base_changed')
    expected=deepcopy(before)
    for p in ('PS','XBOX','PC'):
        if number(before['region_coefficients']['39:'+p])!=number('.91'):raise ValueError('pricing_uk_retirement_rule_changed')
        expected['region_coefficients']['39:'+p]='1'
    if expected!=after:raise ValueError('pricing_uk_retirement_action_changed')
    return ['base:'+g for g in groups_for(bundle['action'])]


def calculate(evidence,job,db):
    from .engine import financial
    from .runtime import clock,render_result
    plan=db.get('pricing_plans',job['request']['v3_plan_id']);now=clock()
    if not plan or plan['state']!='ACTIVE' or plan.get('financial_contract_version')!=FINANCIAL_CONTRACT_VERSION:raise ValueError('pricing_uk_retirement_plan_inactive')
    with db.connect() as conn:db.owns(plan,['base:'+p for p in PLATFORMS],conn)
    raw=evidence['region_contract']['rules']
    matches=[r for r in raw if r['id']==1]
    if len(matches)!=1 or any(matches[0][k]!=v for k,v in SCOPE.items()) or matches[0]['status']!=1 or number(matches[0]['factor'])!=number('.91'):
        raise ValueError('pricing_uk_retirement_rule_changed')
    regions=evidence.get('region_rules',[])+evidence.get('regional_controls',[])
    before=dict(base_prices={g:str(evidence['storefront']['rows'][p]['package_usd']) for g,p in ((p,p) for p in PLATFORMS)},
        region_coefficients={str(r['region_id'])+':'+p:str(r['factor']) for r in regions for p in r['platforms']})
    after=deepcopy(before)
    for p in ('PS','XBOX','PC'):after['region_coefficients']['39:'+p]='1'
    prior=financial(evidence,before,now,regions=regions);proof=financial(evidence,after,now,regions=regions)
    expected=deepcopy(raw)
    next(r for r in expected if r['id']==1)['status']=0
    operation=job['request']['v3_operation_id']
    step=dict(step_id=str(uuid.uuid5(uuid.NAMESPACE_URL,operation+':uk-rule-1')),kind='region',key='39:ALL',state='PENDING',
        scope=SCOPE,rule_id=1,value='.9100',target_status=0,intent=PURPOSE,expected_rule_set_sha256=fingerprint(raw),intermediate=after)
    bundle=dict(schema_version=VERSION,maintenance_purpose=PURPOSE,mode='uk_discount_retirement',
        decision_bundle_id=operation,snapshot_id=evidence['run_id'],snapshot_sha256=fingerprint(evidence),
        plan_id=plan['plan_id'],revision=plan['revision'],engine_generation=plan['generation'],assignment_id=None,
        action=after,before_action=before,mutable_resources=RESOURCES,
        resources=['base:'+p for p in PLATFORMS]+['region_rule:1']+RESOURCES,steps=[step],
        created_at=now.isoformat(),valid_until=min(now+timedelta(minutes=15),instant(evidence['checked_at'])+timedelta(minutes=15)).isoformat(),
        financial_proof=proof,before_financial_proof=prior,financial_contract_version=FINANCIAL_CONTRACT_VERSION,price_scope_contract=PRICE_SCOPE_CONTRACT,
        catalog=evidence['promotion_envelope']['packages'],market_comparison={},regional_market_comparison={},
        uk_rule_expectations=rule_expectations(expected),readback_regions=[dict(region_id=r['region_id'],platforms=r['platforms']) for r in regions],
        affected_platforms=['PS','XBOX','PC'],budget_policy='none',execution_authorized=True,
        review_contract=PURPOSE,decision_source='user_authorized_uk_discount_retirement',per_cycle_model_required=False,
        decision_type='regional_rule_retirement',decision_reason='AUTHORIZED_UK_091_RETIREMENT',margin_basis=MARGIN_BASIS)
    authority_resources(bundle);bundle['sha256']=fingerprint(bundle)
    result=render_result(evidence,dict(action=after,financial_proof=proof,decision_type=bundle['decision_type'],decision_reason=bundle['decision_reason']),bundle,'uk_discount_retirement')
    db.put('pricing_snapshots',evidence['run_id'],dict(snapshot_id=evidence['run_id'],authorization_purpose=PURPOSE,
        origin='live_collector',mode='production',evidence=evidence,result=result,created_at=now.isoformat(),policy_version=VERSION))
    return result


def run(body):
    import fc27_cloud_worker as worker
    from .runtime import ROOT,clock,ledger,execute_run,reconcile
    from automation_policy import load_policy
    db=ledger();key=body['_durable_job_id'];operation=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-uk-retirement:'+key))
    existing=db.get('operations',operation)
    if existing:return reconcile(operation)
    plan=db.get('pricing_plans',body['plan_id'])
    if not plan or plan['state']!='ACTIVE' or plan['revision']!=body['revision']:return dict(status='superseded')
    ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-uk-collection:'+key+':'+str(body.get('_attempt',0))))
    job=dict(job_id=ident,kind=PURPOSE,actor=body['actor'],status='running',created_at=clock().isoformat(),
        request=dict(policy_revision=load_policy()['revision'],v3_plan_id=plan['plan_id'],v3_operation_id=operation,
            v3_authorization_purpose=PURPOSE,manual_requested=True,request_id=key),engine_generation=plan['generation'])
    worker.save_job(job)
    try:
        collected=worker.collect_quote(job)
        outcome=execute_run(collected['run_id'])
        job.update(status='ready',result=dict(operation_id=operation,status=outcome['status']),completed_at=clock().isoformat())
        worker.save_job(job);return outcome
    except ValueError as exc:
        job.update(status='failed',error=str(exc),completed_at=clock().isoformat());worker.save_job(job)
        if str(exc).startswith('pricing_uk_retirement_'):return dict(status='REJECTED_PREWRITE',reason=str(exc),operation_id=operation)
        raise
