"""Two-round proof source. Only existing GET readers and public query requests."""
import sys,json,hashlib,tempfile,importlib
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal as D

def main():
    started=datetime.now(timezone.utc).isoformat()
    sys.dont_write_bytecode=True;sys.path[:0]=['/opt/fc27-cloud-browser','/usr/local/bin']
    import player_sync_job as player,coin_all_sync_job as coins,storefront_monitor as sf
    from p2pah_session_service import SessionManager,read_private_config
    scope=json.loads(Path('/run/reconcile-scope.json').read_text('utf-8'))
    root=Path('/var/lib/fc27-cloud');pid=scope['player_job_id'];cid=scope['coin_execution_id']
    ledger=json.loads(Path('/run/reconcile-original-ledger.json').read_text('utf-8'));audit=json.loads((root/'executions'/(cid+'.json')).read_text('utf-8'))
    provenance={'python':sys.version,'executable':sys.executable,'executable_sha256':hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),'modules':{}}
    for name in scope['proof_provenance']['modules']:
        module=importlib.import_module(name);path=Path(module.__file__).resolve();provenance['modules'][name]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    if provenance!=scope['proof_provenance']:raise ValueError('proof_dependency_origin_changed')
    manager=SessionManager(read_private_config())
    if not manager.ensure():raise ValueError('session_unavailable')
    if player.api(manager,'/admin/index/index')['adminInfo']['username']!='chenchao':raise ValueError('identity_invalid')
    rates={r['platform']:D(str(r['b2c'])) for r in audit['after']['rows']};coin_reads=[]
    for platform in coins.PRODUCTS:
        for site in (0,266):
            meta={};row=coins.read_row(manager,platform,site,lambda value:meta.update(value))
            coin_reads.append({**meta,'platform':platform,'product_id':row['id'],'site_id':site,'actual_unit_price':row['unit_price'],
                               'identity':{k:row.get(k) for k in ['id','mid','gid','cid','aid','site_id','status']},
                               'tier_gold':row['more']['gold'],'tier_give':row['more']['give'],'tier_discount':row['more']['discount'],'tier_price':row['more']['price']})
    samples=[]
    for mid in ledger['sample_model_ids']:
        model=player.api(manager,'/admin/goods.GoodsMould/edit?id='+str(mid))['row'];sample={'id':mid,'title':model['title'].split('/',1)[0].strip()}
        linked=player.products(manager,mid);public=player.public_formula_status(sample,linked,rates)
        samples.append({'model_id':mid,'model':{k:model.get(k) for k in ['id','gid','cid','status','title']},
                        'model_inputs':{k:str(v) for k,v in player.model_inputs(model).items()},
                        'products':[{**{k:row.get(k) for k in ['id','mid','gid','cid','aid','site_id','status','total','unit_price']},'platform':player.area(row)} for row in linked],
                        'public_readback':public})
    public_coins=[]
    with tempfile.TemporaryDirectory(prefix='fc27-readonly-reconcile-public-') as folder:
        jar=Path(folder)/'public-cookie.txt';mapping=sf.page_mapping(sf.fetch(sf.PAGE_URL,cookie_jar=jar))
        for key,platform in sf.PLATFORMS.items():
            raw=sf.fetch(sf.GOODS_URL,{'Game_id':'1327','top_cid':'1','aid':mapping['servers'][key],'cid':mapping['cid'],'site_id':mapping['site_id']},100000,jar)
            rows=json.loads(raw)['goods']['index']['list']
            if len(rows)!=1 or rows[0]['unit']!='K':raise ValueError('coin_public_scope_changed')
            row=rows[0];public_coins.append({'platform':platform,'sku_id':row['id'],'tiers':[{k:tier.get(k) for k in ['num','give','price','price_discount','discount']} for tier in row['goods_list'].values()]})
    models=player.list_models(manager);model_ids=[int(row['id']) for row in models]
    proof={'started_at':started,'provenance':provenance,'checked_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'business_posts':0,'job_id':pid,'coin_execution_id':cid,
           'model_count':len(model_ids),'model_scope_digest':hashlib.sha256(json.dumps(model_ids,separators=(',',':')).encode()).hexdigest(),
           'ledger_sha256':hashlib.sha256(Path('/run/reconcile-original-ledger.json').read_bytes()).hexdigest(),
           'expected_rates':{p:str(v) for p,v in rates.items()},'coin_readbacks':coin_reads,'samples':samples,'coins_public':public_coins,
           'sample_model_ids':ledger['sample_model_ids'],'player_policy':json.loads((root/'config/player-sync.json').read_text('utf-8')),
           'source_sha256':hashlib.sha256(Path('/opt/fc27-cloud-browser/player_sync_job.py').read_bytes()).hexdigest()}
    print(json.dumps(proof))

if __name__=='__main__':main()
