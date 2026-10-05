"""Explicit continuation of the known partial ALL task; never re-post PS."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib,json,sys
from pathlib import Path
import coin_all_sync_job as sync
from coin_all_once import digest

JOB_ID='d6c6fed5-f757-42a0-a6ab-dfb93a9b4d5e'

def prepare(manager, root, policy):
    ap=root/'executions'/(JOB_ID+'.json'); lp=root/'all-coin-sync'/(JOB_ID+'.json')
    ar,lr=ap.read_bytes(),lp.read_bytes(); audit=json.loads(ar);ledger=json.loads(lr)
    sync.validate(audit,policy)
    if audit.get('kind')!='all_baseline_repair' or ledger.get('status')!='needs_reconcile':
        raise ValueError('resume_state_changed')
    snapshot=[]
    for platform in sync.PRODUCTS:
        snapshot.append({'platform':platform,'all':sync.editable(sync.read_row(manager,platform,0)),
                         'source':sync.editable(sync.read_row(manager,platform,266))})
    if [x.get('status') for x in ledger['steps']]!=['dispatching','pending','pending']:
        raise ValueError('resume_steps_changed')
    for p in (root/'executions').glob('*.json'):
        if p!=ap and json.loads(p.read_text()).get('status') in ('RUNNING','PARTIAL','UNCERTAIN'):
            raise ValueError('other_unresolved_execution')
    return {'scope':'fc27_all_resume_known_keyword_once','execution_id':JOB_ID,
            'prepared_at':datetime.now(timezone.utc).isoformat(),
            'audit_hash':hashlib.sha256(ar).hexdigest(),'ledger_hash':hashlib.sha256(lr).hexdigest(),
            'policy_hash':digest(policy),'snapshot_hash':digest(snapshot),
            'no_repeat_product_id':163329309,'pending_product_ids':[163329275,163329343],
            'accepted_default_keywords':sync.DEFAULT_KEYWORDS}

def apply(manager,packet,root,read_policy):
    if packet.get('approved_once') is not True or packet.get('scope')!='fc27_all_resume_known_keyword_once':
        raise ValueError('resume_approval_missing')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(packet['prepared_at'])).total_seconds()
    if not 0<=age<=300:raise ValueError('resume_preview_expired')
    policy=read_policy();fresh=prepare(manager,root,policy)
    for key in fresh:
        if key!='prepared_at' and fresh[key]!=packet.get(key):raise ValueError('resume_preview_changed')
    ap=root/'executions'/(JOB_ID+'.json');lp=root/'all-coin-sync'/(JOB_ID+'.json')
    audit=json.loads(ap.read_text());ledger=json.loads(lp.read_text())
    if audit.get('cache_status') is not None:raise ValueError('resume_cache_already_dispatched')
    sync.plan(manager,audit,policy)  # Recheck authorized admin identity and tier basis.
    def save(value):
        stored=deepcopy(value)
        if stored['status']=='CONFIRMED':stored['status']='ALL_ALIGNED'
        sync.atomic(ap,stored)
    result=sync.resume_synchronize(manager,audit,policy,ledger,save,lambda x:sync.atomic(lp,x),read_policy)
    audit.update(status='PARTIAL',stage='all_cache_pending',cache_status='dispatching');save(audit)
    try:sync.api(manager,'/admin/tools.Caches/clear?server=1',{'type':'all','file':''})
    except Exception:
        audit['cache_status']='unconfirmed';save(audit);raise
    audit.update(status='CONFIRMED',stage='all_alignment_complete',cache_status='cleared');save(audit)
    return {**result,'execution_id':JOB_ID,'ps_reconciled_read_only':True,
            'new_business_post_product_ids':[163329275,163329343],'cache_status':'cleared'}

def main():
    sys.path.insert(0,'/usr/local/bin')
    from p2pah_session_service import SessionManager,read_private_config
    root=Path('/run/fc27');read_policy=lambda:json.loads((root/'config/automation.json').read_text())
    manager=SessionManager(read_private_config())
    if not manager.ensure():raise ValueError('auth_unavailable')
    mode=sys.argv[1]
    if mode=='preview':result=prepare(manager,root,read_policy())
    elif mode=='apply':result=apply(manager,json.loads(Path('/run/request.json').read_text()),root,read_policy)
    else:raise ValueError('mode_invalid')
    print(json.dumps(result))

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'status':'stopped','reason':str(error) if isinstance(error,ValueError) else type(error).__name__}))
        raise SystemExit(2)
