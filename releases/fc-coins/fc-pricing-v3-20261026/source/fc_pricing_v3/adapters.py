"""Only mechanical execution and readback; policy selection stays in the coordinator."""
import json
import subprocess
from pathlib import Path

from .financial import number,fingerprint


def region_step(operation_id,step_id,*,write=False):
    done=subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.region_adapter'],
                        input=json.dumps(dict(operation_id=operation_id,step_id=step_id,mode='write' if write else 'read')),
                        capture_output=True,text=True,timeout=60,cwd='/opt/fc27-cloud-browser')
    try:return json.loads(done.stdout)
    except ValueError:return dict(status='UNKNOWN',reason='original_region_transport_reply_unavailable',exit_code=done.returncode)


def base_execution_id(operation,step):
    import uuid
    return str(uuid.uuid5(uuid.UUID(operation['operation_id']),step['step_id'])) if sum(s['kind']=='base' for s in operation['steps'])>1 else operation['operation_id']


def base_step_context(operation,step):
    from copy import deepcopy
    from decimal import Decimal
    import uuid
    from .runtime import ROOT,write_json,project_base_step
    context=deepcopy(operation['dispatch_context'])
    reference=dict(operation_id=operation['operation_id'],step_id=step['step_id'])
    quote=json.loads((ROOT/'quotes'/(operation['bundle']['snapshot_id']+'.json')).read_text())
    projected=project_base_step(quote,reference)
    preview=deepcopy(context['preview'])
    preview['preview_id']=str(uuid.uuid5(uuid.UUID(operation['operation_id']),'preview:'+step['step_id']))
    preview['v3_execution_step']=reference
    previous=[s for s in operation['steps'][:operation['steps'].index(step)] if s['kind']=='base']
    if previous:
        audit=json.loads((ROOT/'executions'/(base_execution_id(operation,previous[-1])+'.json')).read_text())
        if audit.get('status')!='CONFIRMED' or audit.get('all_baseline',{}).get('status')!='confirmed':raise ValueError('pricing_previous_base_unconfirmed')
        preview['backend_before']=audit['after']
    by={r['platform']:r for r in projected['result']['rows']}
    for target in preview['targets']:
        row=by[target['platform']]
        target.update(quote=row['proposal'],targetCost=format(Decimal(row['proposal'])*Decimal('5.32'),'.6f'),
                      targetPageUsd=row['target_page_usd'],actualGrossMargin=row['gross_margin_pct'])
    path=ROOT/'previews'/(preview['preview_id']+'.json')
    if path.exists():
        if json.loads(path.read_text())!=preview:raise ValueError('pricing_base_step_preview_changed')
    else:write_json(path,preview)
    context['preview']=preview
    return context,reference


def dispatch_base(operation):
    from .runtime import ROOT,STORE,write_json
    import fc27_cloud_worker as worker
    context=operation['dispatch_context'];reference=None;execution_id=operation['operation_id']
    if sum(s['kind']=='base' for s in operation['steps'])>1:
        step=next(s for s in operation['steps'] if s['kind']=='base' and s['state']!='CONFIRMED')
        try:context,reference=base_step_context(operation,step)
        except (OSError,ValueError,KeyError) as exc:return dict(status='NOT_SENT',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        execution_id=base_execution_id(operation,step)
    request=dict(preview_id=context['preview']['preview_id'],execution_id=execution_id,
                 actor=context['actor'],platforms=context['selected'],margin_confirmed_platforms=[],
                 margin_exception_reason='',policy_revision=context['policy_revision'],automatic=context['automatic'],
                 v3_operation_id=operation['operation_id'],engine_generation=operation['generation'])
    request_path=ROOT/'requests'/(execution_id+'.json')
    if request_path.exists():
        if json.loads(request_path.read_text())!=request:raise ValueError('pricing_operation_payload_conflict')
    else:write_json(request_path,request)
    auth=STORE/'authorizations'/(execution_id+'.json')
    auth.parent.mkdir(parents=True,exist_ok=True)
    authorization=dict(operation_id=execution_id,bundle_sha256=operation['bundle']['sha256'],
                        generation=operation['generation'],run_id=operation['bundle']['snapshot_id'],selected=context['selected'])
    if reference:authorization['v3_execution_step']=reference
    audit_path=ROOT/'executions'/(execution_id+'.json')
    if audit_path.exists():
        from .dispatch import proven_not_sent
        previous=json.loads(audit_path.read_text())
        if not proven_not_sent(previous):return dict(status='UNKNOWN',reason='original_base_dispatch_already_recorded')
        authorization['not_sent_audit_sha256']=fingerprint(previous)
    write_json(auth,authorization)
    try:
        code,result=worker.run([str(worker.APP/'execute_price.sh'),str(request_path)],180)
    except Exception as exc:
        return dict(status='UNKNOWN',error=type(exc).__name__)
    audit=json.loads(audit_path.read_text()) if audit_path.exists() else {}
    fully_confirmed=(not code and result.get('status')=='CONFIRMED' and audit.get('sync_confirmed') is True and audit.get('all_baseline',{}).get('status')=='confirmed')
    status='NOT_SENT' if result.get('status') in ('NOT_SENT','busy') else 'CONFIRMED' if fully_confirmed else 'UNKNOWN'
    return dict(result,status=status,exit_code=code)


def reconcile_base(operation):
    from .runtime import ROOT
    import fc27_cloud_worker as worker
    request=ROOT/'requests'/(operation['operation_id']+'.json')
    if not request.exists():return dict(status='UNKNOWN',reason='original_request_missing')
    try:
        code,result=worker.run([str(worker.APP/'reconcile_price.sh'),str(request)],180)
        return dict(result,exit_code=code)
    except Exception as exc:return dict(status='UNKNOWN',reason=type(exc).__name__,original_operation_id=operation['operation_id'])


def verify_nochange(operation,preview):
    import fc27_cloud_worker as worker
    from .runtime import ROOT
    run_id=operation['bundle']['snapshot_id']
    job=json.loads((ROOT/'jobs'/(run_id+'.json')).read_text())
    job['result']=dict(platforms=['PS','XBOX','PC'])
    job['storefront_after']=worker.refresh_storefront(job)
    public=worker.verify_public_page(job)
    if public.get('status')!='verified':
        return dict(status='PUBLIC_PENDING',public=public,preview=preview)
    regional=verify_regions(operation)
    if regional['status']!='verified':return dict(status='PUBLIC_PENDING',public=public,regions=regional,preview=preview)
    return dict(status='PUBLIC_CONFIRMED',public=public,regions=regional['regions'],no_change=True,write_performed=False)


def reconcile_postwrite(operation,audit):
    from .runtime import ROOT,STORE,ledger,write_json
    import fc27_cloud_worker as worker
    db=ledger()
    operation_id=operation['operation_id']
    run_id=operation['bundle']['snapshot_id']
    saved=db.get('operations',operation_id)
    if saved.get('cache_receipt',{}).get('status')!='cleared':
        if audit is None:
            auth=STORE/'cache-authorizations'/(operation_id+'.json')
            auth.parent.mkdir(parents=True,exist_ok=True)
            write_json(auth,dict(schema_version='fc-pricing-v3-20261026',operation_id=operation_id,
                                backend_steps=saved['steps']))
        cache=worker.refresh_backend_cache(dict(job_id=operation_id))
        saved['cache_receipt']=cache
        saved['status']='CACHE_CONFIRMED' if cache.get('status')=='cleared' else 'BACKEND_CONFIRMED'
        db.put('operations',operation_id,saved)
        if cache.get('status')!='cleared':
            return dict(status='BACKEND_CONFIRMED',cache=cache,execution_id=operation_id)
    job=json.loads((ROOT/'jobs'/(run_id+'.json')).read_text())
    job['result']=dict(platforms=audit['selected'] if audit else ['PS','XBOX','PC'])
    job['storefront_after']=worker.refresh_storefront(job)
    worker.save_job(job)
    public=worker.verify_public_page(job)
    if public.get('status')!='verified':
        return dict(status='CACHE_CONFIRMED',public=public,cache=saved['cache_receipt'],execution_id=operation_id)
    regional=verify_regions(operation)
    if regional['status']!='verified':return dict(status='CACHE_CONFIRMED',public=public,regions=regional,execution_id=operation_id)
    return dict(status='PUBLIC_CONFIRMED',public=public,regions=regional['regions'],cache=saved['cache_receipt'],
                execution_id=operation_id,uk_rule_verified=True,uk_discount_retired=regional.get('uk_discount_retired',False))


def verify_known_partial(operation,actual_action):
    """Read back the actual prefix, without claiming the abandoned joint target succeeded."""
    from copy import deepcopy
    from .runtime import ROOT,STORE,ledger,write_json
    from .engine import render
    import fc27_cloud_worker as worker
    db=ledger();ident=operation['operation_id']
    saved=db.get('operations',ident)
    if saved.get('cache_receipt',{}).get('status')!='cleared':
        confirmed=[s for s in operation['steps'] if s['state']=='CONFIRMED']
        auth=STORE/'cache-authorizations'/(ident+'.json');auth.parent.mkdir(parents=True,exist_ok=True)
        write_json(auth,dict(schema_version='fc-pricing-v3-20261026',operation_id=ident,backend_steps=confirmed))
        cache=worker.refresh_backend_cache(dict(job_id=ident))
        saved['cache_receipt']=cache;db.put('operations',ident,saved)
        if cache.get('status')!='cleared':return dict(status='PUBLIC_PENDING',cache=cache)
    job=json.loads((ROOT/'jobs'/(operation['bundle']['snapshot_id']+'.json')).read_text())
    refresh=worker.refresh_storefront(job)
    if refresh.get('status')!='ok':return dict(status='PUBLIC_PENDING',public=refresh)
    public=json.loads((ROOT/'monitor/storefront.json').read_text())
    platforms=set()
    for step in operation['steps']:
        if step['state']!='CONFIRMED':continue
        if step['kind']=='base':platforms.update(operation['dispatch_context']['selected'])
        else:platforms.add(step['key'].split(':')[-1])
    if platforms & {'PS','XBOX'}:platforms.update(('PS','XBOX'))
    for platform in platforms:
        row=public.get('rows',{}).get(platform) or {}
        expected=actual_action['base_prices']['pc' if platform=='PC' else 'console']
        if row.get('status')!='ok' or number(row['package_usd'])!=number(expected):
            return dict(status='PUBLIC_PENDING',reason='actual_partial_global_price_unconfirmed',platform=platform)
    clone=deepcopy(operation);proof=clone['bundle']['financial_proof']['prices']
    for key,row in proof.items():
        if key.startswith('global:'):continue
        platform=key.split(':')[1]
        factor=actual_action.get('region_coefficients',{}).get(key,row['coefficient'])
        tier=next(t for t in operation['bundle']['catalog'][platform]['tiers'] if number(t['base_k'])==100)
        row.update(price=render(number(actual_action['base_prices']['pc' if platform=='PC' else 'console'])/100,tier,factor),coefficient=factor)
    regional=verify_regions(clone)
    if regional['status']!='verified':return dict(status='PUBLIC_PENDING',regions=regional)
    return dict(status='PUBLIC_CONFIRMED',actual_action=actual_action,global_public={p:public['rows'][p] for p in platforms},
                regions=regional['regions'],cache=saved['cache_receipt'],original_joint_target_completed=False)


def verify_regions(operation):
    """The same real regional readback applies to changed and unchanged price exposure."""
    operation_id=operation['operation_id']
    try:
        rules=region_step(operation_id,None)
        from .region_source import rule_expectations
        expected_uk=operation['bundle'].get('uk_rule_expectations')
        if expected_uk is None:
            from .runtime import ROOT
            quote=json.loads((ROOT/'quotes'/(operation['bundle']['snapshot_id']+'.json')).read_text())
            expected_uk=rule_expectations(quote['evidence']['region_contract']['rules'])
        if rule_expectations(rules.get('rules',[]))!=expected_uk:
            raise ValueError('pricing_uk_rule_changed')
        from .regional_public import collect
        regions={};proof=operation['bundle']['financial_proof']['prices']
        for region_id,code in ((39,'uk'),(21,'ar')):
            allowed=None if 'readback_regions' not in operation['bundle'] else {p for scope in operation['bundle']['readback_regions'] if scope['region_id']==region_id for p in scope['platforms']}
            expected={key.split(':')[1]:value for key,value in proof.items() if key.startswith(str(region_id)+':') and (allowed is None or key.split(':')[1] in allowed)}
            if not expected:continue
            observed=collect(code,region_id)
            for platform,value in expected.items():
                actual=observed['offers'][platform]
                if number(actual['regular_usd'])!=number(value['price']['regular_usd']) or number(actual['coefficient'])!=number(value['coefficient']):
                    raise ValueError('pricing_regional_public_price_mismatch')
            regions[str(region_id)]=observed
        return dict(status='verified',regions=regions,uk_rule_verified=True,
                    uk_discount_retired=any(r['id']==1 and r['status']==0 for r in expected_uk))
    except Exception as exc:
        return dict(status='pending',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__,original_operation_id=operation_id)
