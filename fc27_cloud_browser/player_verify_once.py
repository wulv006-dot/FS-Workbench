"""One approved FC27 Players category request; never enables the recurring switch."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
import uuid
import coin_all_sync_job as coins
from coin_all_once import digest

TARGET_MODEL=43169073


def prepare(manager, player, alignment, coin_policy, player_policy, job_id=None):
    if alignment.get('status')!='ALL_ALIGNED' or player_policy.get('enabled') is not False:
        raise ValueError('single_validation_preflight_changed')
    context={**alignment,'status':'CONFIRMED'}
    steps=coins.plan(manager,context,coin_policy)
    if any(s['changed'] for s in steps):raise ValueError('all_baselines_not_aligned')
    models=player.list_models(manager)
    samples=player.category_samples(manager,models)
    if TARGET_MODEL not in {s['id'] for s in samples}:
        model=next((r for r in models if int(r['id'])==TARGET_MODEL),None)
        if not model or str(model.get('status'))!='1':raise ValueError('anomaly_model_not_active')
        linked=player.products(manager,TARGET_MODEL)
        if len([r for r in linked if player.active(r)])!=3:raise ValueError('anomaly_products_incomplete')
        samples.append({'id':TARGET_MODEL,'title':str(model['title']).split('/',1)[0].strip(),
                        'product_ids':sorted(int(r['id']) for r in linked)})
    rates={r['platform']:Decimal(str(r['b2c'])) for r in alignment['after']['rows']}
    before={str(s['id']):player.public_formula_status(s,player.products(manager,s['id']),rates) for s in samples}
    return {'scope':'fc27_players_category_validation_once','job_id':job_id or str(uuid.uuid4()),
            'all_alignment_id':alignment['execution_id'],'prepared_at':datetime.now(timezone.utc).isoformat(),
            'coin_policy_hash':digest(coin_policy),'player_policy_hash':digest(player_policy),
            'model_count':len(models),'model_ids_hash':digest(sorted(int(r['id']) for r in models)),
            'rates':{k:str(v) for k,v in rates.items()},'samples':samples,'sample_before':before,
            'random_sample_count':5,'required_anomaly_model_id':TARGET_MODEL,
            'native_request':{'gid':1327,'cid':9627,'id':[]}}


def execute(manager, player, packet, alignment, read_coin_policy, read_player_policy, root):
    if packet.get('approved_once') is not True or packet.get('scope')!='fc27_players_category_validation_once':
        raise ValueError('single_validation_approval_missing')
    if packet.get('native_request')!={'gid':1327,'cid':9627,'id':[]}:
        raise ValueError('single_validation_category_changed')
    job_id=str(uuid.UUID(packet['job_id']))
    if job_id==alignment['execution_id']:raise ValueError('new_validation_id_required')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(packet['prepared_at'])).total_seconds()
    if not 0<=age<=300:raise ValueError('single_validation_preview_expired')
    def guard():
        cp,pp=read_coin_policy(),read_player_policy()
        if (digest(cp)!=packet['coin_policy_hash'] or digest(pp)!=packet['player_policy_hash']
                or pp.get('enabled') is not False or alignment.get('status')!='ALL_ALIGNED'):
            raise ValueError('single_validation_policy_changed')
        if any(s['changed'] for s in coins.plan(manager,{**alignment,'status':'CONFIRMED'},cp)):
            raise ValueError('single_validation_coin_source_changed')
    guard()
    models=player.list_models(manager)
    if digest(sorted(int(r['id']) for r in models))!=packet['model_ids_hash']:
        raise ValueError('single_validation_model_scope_changed')
    path=root/'executions'/(job_id+'.json')
    record={'execution_id':job_id,'kind':'player_validation_once','automatic':False,
            'created_at':datetime.now(timezone.utc).isoformat(),'status':'RUNNING','stage':'preflight',
            'authorization_mode':'approved_single_validation','production_player_switch_enabled':False,
            'all_alignment_id':alignment['execution_id'],'native_request':packet['native_request'],
            'model_count':len(models),'model_ids_hash':packet['model_ids_hash'],
            'samples':packet['samples'],'sample_before':packet['sample_before'],'sample_readback':{},
            'sample_verified_count':0,'cache_status':None}
    with path.open('x',encoding='utf-8') as stream:
        json.dump(record,stream);stream.flush();coins.os.fsync(stream.fileno())
    coins.os.chmod(path,0o640)
    def save():coins.atomic(path,record)
    rates={k:Decimal(v) for k,v in packet['rates'].items()}
    def linked_sample(sample):
        detail=player.api(manager,'/admin/goods.GoodsMould/edit?id='+str(sample['id']))
        row=detail.get('row') if isinstance(detail,dict) else None
        if (not isinstance(row,dict) or int(row.get('id',0))!=sample['id']
                or str(row.get('gid'))!='1327' or str(row.get('cid'))!='9627'
                or str(row.get('status'))!='1'
                or str(row.get('title','')).split('/',1)[0].strip()!=sample['title']):
            raise ValueError('single_validation_sample_model_changed')
        linked=player.products(manager,sample['id'])
        if sorted(int(r['id']) for r in linked)!=sample['product_ids']:
            raise ValueError('single_validation_sample_scope_changed')
        return linked
    try:
        # Guard each recorded sample's exact model/product scope before the one POST.
        for sample in packet['samples']:
            linked_sample(sample)
        guard()
        record['stage']='category_dispatch_intent';save()
        player.recalculate_category(manager)  # Exactly one, never retried.
        record['stage']='cache_dispatch_intent';record['cache_status']='dispatching';save()
        coins.api(manager,'/admin/tools.Caches/clear?server=1',{'type':'all','file':''})
        record['cache_status']='cleared';record['stage']='sample_readback';save()
        deadline=time.monotonic()+180
        verified=set()
        while True:
            guard()
            verified=set()
            for sample in packet['samples']:
                linked=linked_sample(sample)
                parts=player.public_formula_status(sample,linked,rates)
                before={p['platform']:p for p in packet['sample_before'][str(sample['id'])]}
                if any(p['our_price_coins']!=before[p['platform']]['our_price_coins']
                       or p['coefficient']!=before[p['platform']]['coefficient'] for p in parts):
                    raise ValueError('single_validation_formula_inputs_changed')
                record['sample_readback'][str(sample['id'])]=parts
                if all(p['backend_match'] and p['public_match'] for p in parts):verified.add(sample['id'])
            record['sample_verified_count']=len(verified);save()
            if len(verified)==len(packet['samples']):break
            if time.monotonic()>=deadline:raise ValueError('single_validation_readback_timeout')
            time.sleep(10)
        record.update(status='VALIDATED',stage='complete',completed_at=datetime.now(timezone.utc).isoformat())
        save()
        return {'status':'validated','job_id':job_id,'model_count':len(models),
                'sample_verified_count':len(verified),'sample_model_ids':sorted(verified),
                'production_player_switch_enabled':False,'native_post_count':1}
    except Exception as error:
        record.update(status='UNCERTAIN',stage='stopped',
                      error=str(error) if isinstance(error,ValueError) else type(error).__name__)
        save();raise


def main():
    sys.path.insert(0,'/usr/local/bin');sys.path.insert(0,'/opt/fc27-cloud-browser')
    import player_sync_job as player
    manager=player.SessionManager(player.read_private_config())
    if not manager.ensure():raise ValueError('player_auth_unavailable')
    root=Path('/run/fc27')
    read_cp=lambda:json.loads((root/'config/automation.json').read_text())
    read_pp=lambda:json.loads((root/'config/player-sync.json').read_text())
    mode=sys.argv[1] if len(sys.argv)>1 else 'preview'
    if mode not in ('preview','apply'):raise ValueError('mode_invalid')
    packet=json.loads(Path('/run/request.json').read_text()) if mode=='apply' else None
    alignment_id=str(uuid.UUID(packet['all_alignment_id'] if packet else sys.argv[2]))
    alignment=json.loads((root/'executions'/(alignment_id+'.json')).read_text())
    result=(execute(manager,player,packet,alignment,read_cp,read_pp,root) if mode=='apply'
            else prepare(manager,player,alignment,read_cp(),read_pp()))
    print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'status':'stopped','reason':str(error) if isinstance(error,ValueError) else type(error).__name__}))
        raise SystemExit(2)
