"""Continue this proven empty ALL preflight; never replay the Order price writes."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

EXECUTION='d91adb32-a3ac-5d1e-9d1c-0d23e1a0173a'
COIN_SHA='8ea19ed3b6a842745df17235b53d8a3762ad81501ae10dbcf40b3a92e1a565fd'


def empty_auth_failure(audit,record):
    if (audit.get('execution_id')!=EXECUTION or record.get('execution_id')!=EXECUTION
            or audit.get('status')!='PARTIAL' or audit.get('stage')!='stopped'
            or audit.get('error')!='coin_backend_request_rejected' or audit.get('sync_confirmed') is not True
            or set(audit.get('changed',[]))!={'PS','XBOX','PC'}
            or record.get('status')!='needs_reconcile' or record.get('steps')!=[]):
        raise ValueError('original_empty_preflight_scope_changed')
    proof=record.get('source_confirmation',{});observations=[o for r in proof.get('rounds',[]) for o in r.get('observations',[])]
    if (proof.get('status')!='stopped' or proof.get('reason')!='coin_backend_request_rejected'
            or not observations or any(o.get('response_code')!=302 or o.get('http_status')!=200
                or o.get('path')!='/admin/goods.Goods/edit?id=163329311' for o in observations)):
        raise ValueError('original_auth_rejection_not_proven')
    rows={r['platform']:r for r in audit['after']['rows']}
    for target in audit['targets']:
        row=rows[target['platform']]
        from decimal import Decimal
        if Decimal(row['b2c'])!=Decimal(target['quote']) or Decimal(row['costPrice'])!=Decimal(target['targetCost']):
            raise ValueError('original_order_write_not_confirmed')


def main():
    mode=sys.argv[1];assert mode in ('--check','--apply')
    root=Path('/tmp/fc-pricing-v2-20261022');live=Path('/var/lib/fc27-cloud')
    sys.path=[p for p in sys.path if p!=str(Path(__file__).parent)]
    sys.path[:0]=['/opt/fc27-cloud-browser','/opt/fs-order-session','/opt/fs-hermes-fc','/opt/sales-dashboard/collector']
    import coin_all_sync_job as coin
    import fc27_cloud_worker as worker
    from automation_policy import load_policy
    from fc_shared_admin import SessionManager
    from channel_source import pages
    import p2pah_auth as auth
    import pricing_sources,pricing_v2,fc27_quote_engine
    if hashlib.sha256(Path(coin.__file__).read_bytes()).hexdigest()!=COIN_SHA:raise ValueError('original_mirror_source_drift')
    info=json.loads((root/'stage-clarity.json').read_text());stage=Path(info['stage'])
    spec=importlib.util.spec_from_file_location('recovery_locks',stage/'input_clarity.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    base=module.adapter.load_base()
    audit_path=live/'executions'/(EXECUTION+'.json');ledger_path=live/'all-coin-sync'/(EXECUTION+'.json');job_path=live/'jobs'/(EXECUTION+'.json')
    cfg=json.loads(Path('/etc/fc27-cloud/global-admin-principal.json').read_text())
    # Same approved principal file as the original container's read-only bind.
    coin.allowed_admin_usernames=lambda:cfg['P2PAH_ALLOWED_USERNAMES']
    with base.locks(Path('/')):
        base.hermes_quiescent(Path('/'))
        audit=json.loads(audit_path.read_text());record=json.loads(ledger_path.read_text());empty_auth_failure(audit,record)
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (audit_path,ledger_path,job_path)}
        policy=load_policy();quote=json.loads((live/'quotes'/(audit['run_id']+'.json')).read_text())
        if policy['revision']!=audit['automation_policy_revision'] or not policy['system_enabled']:raise ValueError('original_policy_changed')
        if {k:quote[k] for k in ('evidence','edits','result')}!=audit['pricing_basis']:raise ValueError('original_frozen_basis_changed')
        context=deepcopy(audit);context['stage']='all_baseline_pending';coin.validate(context,policy)
        manager=SessionManager(cfg)
        if not manager.ensure():raise ValueError('shared_admin_unavailable')
        identity=coin.api(manager,'/admin/index/index')
        if identity.get('adminInfo',{}).get('username') not in cfg['P2PAH_ALLOWED_USERNAMES']:raise ValueError('original_identity_changed')
        sources={p:coin.read_row(manager,p,266) for p in coin.PRODUCTS}
        def current_proof():
            s=auth.Session();token,reason=auth.admin_token_from_service()
            if not token:raise ValueError('shared_admin_unavailable')
            s.bind_admin_token(token);del token
            try:
                discounts=pages(s,'/admin/market.Discount/index');coupons=pages(s,'/admin/market.Coupon/index')
                goods=pages(s,'/admin/goods.Goods/index',[('id','IN',','.join(str(r['id']) for r in sources.values()))])
            finally:s.close()
            # This is an Admin price/config validation view for an already-written
            # operation, never a substitute for the later public readback.
            backend_view=deepcopy(quote['evidence']['storefront'])
            for p,r in sources.items():backend_view['rows'][p]['package_usd']=str(coin.money(r['unit_price'])*100)
            envelope=pricing_sources.normalize(discounts,coupons,goods,backend_view)
            if envelope['sha256']!=quote['evidence']['promotion_envelope']['sha256']:raise ValueError('pricing_promotions_changed_since_original_write')
            candidate=deepcopy(quote);candidate['evidence']['promotion_envelope']=envelope
            candidate['result']=fc27_quote_engine.calculate(candidate['evidence'],candidate['edits'])
            pricing_v2.verify_quote(candidate,load_policy(),list(coin.PRODUCTS),for_execution=True)
            if any(coin.money(r['proposal'])!=coin.money(sources[r['platform']]['unit_price']) for r in candidate['result']['rows']):raise ValueError('original_target_no_longer_safe')
            if load_policy()!=policy:raise ValueError('original_policy_changed')
            return candidate
        proof=current_proof();result=dict(execution_id=EXECUTION,hashes=hashes,shared_admin='identity_and_six_product_scope',hard_floor='fresh_same_promotion_fingerprint_and_full_catalog_verified',mmoexp_replayed=False,mode=mode)
        if mode=='--check':
            (root/'original-reconcile-check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return
        expected=json.loads((root/'original-reconcile-check.json').read_text())
        if hashes!=expected['hashes']:raise ValueError('original_reconcile_cas_changed')
        backup=root/'original-reconcile-before';backup.mkdir(mode=0o700,exist_ok=False)
        for p in (audit_path,ledger_path,job_path):(backup/p.name.replace('.json','-'+p.parent.name+'.json')).write_bytes(p.read_bytes())
        with (root/'original-reconcile-intent.json').open('x') as f:json.dump(result,f);f.flush();os.fsync(f.fileno())
        save=lambda value:coin.atomic(audit_path,value)
        persist=lambda value:coin.atomic(ledger_path,value)
        record.setdefault('source_confirmation_history',[]).append(deepcopy(record['source_confirmation']))
        confirmed=coin.wait_sources(manager,context,policy,record,persist,load_policy)
        steps=coin.plan(manager,context,policy)
        if any(coin.editable(s['source'])!=confirmed[s['platform']] for s in steps):raise ValueError('source_changed_during_recovery')
        record['steps']=[{k:deepcopy(s[k]) for k in ('platform','product_id','source_product_id','before','source','payload','changed')}|{'status':'pending'} for s in steps]
        record['status']='continued_after_verified_empty_auth_rejection';persist(record)
        audit.setdefault('recovery_history',[]).append(dict(stage=audit['stage'],error=audit['error'],status=audit['status'],continued_at=datetime.now(timezone.utc).isoformat(),mmoexp_replayed=False,original_empty_auth_preflight=True))
        audit['stage']='all_baseline_pending';save(audit)
        original_request=manager.request
        def guarded(path,*,data=None,token=None):
            if data is not None:
                if path not in {'/admin/goods.Goods/edit?id='+str(v[0]) for v in coin.PRODUCTS.values()}:raise ValueError('recovery_write_scope')
                current_proof()
            return original_request(path,data=data,token=token)
        manager.request=guarded
        outcome=coin.drive(manager,audit,policy,steps,record,save,persist,load_policy,current_proof)
        job=json.loads(job_path.read_text());job['reconciliation']=dict(status='confirmed',execution_id=EXECUTION,completed_at=record['completed_at'],original_job_status=job['status'],mmoexp_replayed=False)
        job['cache_refresh']=worker.refresh_backend_cache(job);job['storefront_after']=worker.refresh_storefront(job)
        public=json.loads((live/'monitor/storefront.json').read_text());targets={r['platform']:r['targetPageUsd'] for r in audit['targets']}
        matched=public.get('status')=='ok' and public.get('collection_run_id')==EXECUTION and all(coin.money(public['rows'][p]['package_usd'])==coin.money(targets[p]) for p in coin.PRODUCTS)
        job['reconciliation']['public_readback']='verified' if matched else 'unconfirmed';worker.save_job(job)
        result.update(outcome=outcome,cache=job['cache_refresh'],public_readback=job['reconciliation']['public_readback'],all_post_count=sum(s.get('post_response') is not None for s in record['steps']),original_job_status_preserved=job['status'])
        (root/'original-reconcile-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
