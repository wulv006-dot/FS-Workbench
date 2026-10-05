"""Explicit, single-use ALL alignment; preview is the default and reads only."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid
import coin_all_sync_job as sync


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def preview(manager, reference, policy, reference_hash, execution_id=None):
    steps=sync.plan(manager,reference,policy)
    return {'scope':'fc27_all_alignment_once','execution_id':execution_id or str(uuid.uuid4()),
            'reference_execution_id':reference['execution_id'],'reference_hash':reference_hash,
            'policy_hash':digest(policy),'prepared_at':datetime.now(timezone.utc).isoformat(),
            'product_snapshot_hash':digest([{k:sync.editable(s[k]) for k in ('before','source')} for s in steps]),
            'changes':[{'platform':s['platform'],'all_product_id':s['product_id'],
                        'mmoexp_product_id':s['source_product_id'],'before':s['before']['unit_price'],
                        'after':s['source']['unit_price'],'changed':s['changed'],
                        'tier_prices_before':s['before']['more']['price'],
                        'tier_prices_after':s['source']['more']['price']} for s in steps]}


def apply_once(manager, packet, reference, policy, reference_hash, root, read_policy):
    if packet.get('approved_once') is not True or packet.get('scope')!='fc27_all_alignment_once':
        raise ValueError('single_use_alignment_approval_missing')
    execution_id=str(uuid.UUID(packet['execution_id']))
    if execution_id==reference['execution_id'] or not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}',packet.get('actor','')):
        raise ValueError('new_alignment_identity_invalid')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(packet['prepared_at'])).total_seconds()
    if not 0<=age<=300:raise ValueError('alignment_preview_expired')
    fresh=preview(manager,reference,policy,reference_hash,execution_id)
    for key in ('reference_execution_id','reference_hash','policy_hash','product_snapshot_hash','changes'):
        if fresh[key]!=packet.get(key):raise ValueError('alignment_preview_changed')
    path=root/'executions'/(execution_id+'.json')
    record={'execution_id':execution_id,'kind':'all_baseline_repair','automatic':False,
            'actor':packet['actor'],'created_at':datetime.now(timezone.utc).isoformat(),
            'status':'PARTIAL','stage':'all_baseline_pending','sync_confirmed':True,
            'reference_coin_execution_id':reference['execution_id'],'mmoexp_write_performed':False,
            'automation_policy_revision':policy['revision'],'after':deepcopy(reference['after'])}
    # A new audit exclusively claims this ID; old Coins/Players tasks remain untouched.
    with path.open('x',encoding='utf-8') as stream:
        json.dump(record,stream)
        stream.flush()
        sync.os.fsync(stream.fileno())
    sync.os.chmod(path,0o640)
    def save(value):
        stored=deepcopy(value)
        # Do not present an ALL-only repair as a fresh MMOEXP publication.
        if stored['status']=='CONFIRMED':stored['status']='ALL_ALIGNED'
        sync.atomic(path,stored)
    result=sync.mirror_confirmed(record,policy,save,root,read_policy)
    record.update(status='PARTIAL',stage='all_cache_pending',cache_status='dispatching')
    save(record)
    try:
        sync.api(manager,'/admin/tools.Caches/clear?server=1',{'type':'all','file':''})
    except Exception:
        record['cache_status']='unconfirmed';save(record);raise
    record.update(status='CONFIRMED',stage='all_alignment_complete',cache_status='cleared')
    save(record)
    return {**result,'execution_id':execution_id,'reference_execution_id':reference['execution_id'],
            'mmoexp_write_performed':False,'old_task_replayed':False}


def main():
    sys.path.insert(0,'/usr/local/bin')
    from p2pah_session_service import SessionManager,read_private_config
    root=Path('/run/fc27')
    policy_path=root/'config/automation.json'
    policy=json.loads(policy_path.read_text())
    mode=sys.argv[1] if len(sys.argv)>1 else 'preview'
    if mode not in ('preview','apply'):raise ValueError('mode_invalid')
    packet=json.loads(Path('/run/request.json').read_text()) if mode=='apply' else None
    if packet:
        reference_id=str(uuid.UUID(packet['reference_execution_id']))
        reference_path=root/'executions'/(reference_id+'.json')
    else:
        paths=[p for p in (root/'executions').glob('*.json')
               if json.loads(p.read_text()).get('status')=='CONFIRMED']
        reference_path=max(paths,key=lambda p:json.loads(p.read_text()).get('created_at',''))
    raw=reference_path.read_bytes();reference=json.loads(raw)
    reference_hash=hashlib.sha256(raw).hexdigest()
    manager=SessionManager(read_private_config())
    if not manager.ensure():raise ValueError('coin_auth_unavailable')
    result=(apply_once(manager,packet,reference,policy,reference_hash,root,
                      lambda:json.loads(policy_path.read_text())) if mode=='apply'
            else preview(manager,reference,policy,reference_hash))
    print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'status':'stopped','reason':str(error) if isinstance(error,ValueError) else type(error).__name__}))
        raise SystemExit(2)
