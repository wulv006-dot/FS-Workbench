"""Synthetic business fixture only; no production runtime binding."""

import copy,json,unittest,stat

from pathlib import Path

from types import SimpleNamespace

from datetime import datetime,timezone,timedelta

from decimal import Decimal as D

from reconcile import Recovery,validate_round,stable,encode,digest,approved_tiers

from runner import validate_context

class MemoryStore:
    def __init__(self,live):
        self.live=live;self.private={};self.exists=False;self.backup_path='/isolated/private/transaction';self.log=[];self.delays={};self.failure=None;self.on_publish=None;self.delay=lambda s:None
    def read_live(self,k):return self.live[k]
    def tx_exists(self):return self.exists
    def create_tx(self):self.exists=True;self.log.append('create_tx')
    def tx_read(self,n):
        if n not in self.private:raise FileNotFoundError(n)
        return self.private[n]
    def tx_write(self,n,raw):
        self.delay(self.delays.get(n,0))
        if self.failure==n:raise OSError('synthetic fsync failure')
        self.private[n]=raw;self.log.append(('durable',n,json.loads(raw).get('phase') if n=='transaction.json' else None))
    def publish(self,k,raw,allowed,checkpoint):
        if digest(self.live[k]) not in allowed:raise ValueError('publication_cas_changed')
        self.log.append(('stage_fsync',k));self.delay(self.delays.get(k,0));checkpoint()
        if self.on_publish:self.on_publish(k,raw)
        self.live[k]=raw;self.log.append(('rename',k))
        if self.failure==k:raise OSError('synthetic directory fsync failure after rename')
        self.log.append(('directory_fsync',k))
    def sync_visible(self,k):
        if self.failure=='sync_visible':raise OSError('synthetic retry fsync failure')
        self.log.append(('sync_visible',k))

class Fixture:

    def setUp(self):
        self.now=datetime(2030,1,1,tzinfo=timezone.utc);self.calls=0;self.events=[]
        self.scope=json.loads((Path(__file__).parent/'synthetic-binding.json').read_text(encoding='utf-8'));self.scope['sample_model_ids']=list(range(1001,1006));self.scope['sample_product_ids']={}
        pid=self.scope['player_job_id'];cid=self.scope['coin_execution_id'];self.pid=pid;self.cid=cid
        self.policy={'enabled':True,'revision':8};self.audit={'execution_id':cid,'status':'CONFIRMED','automatic':True,'automation_policy_revision':28,'all_baseline':{'status':'confirmed'},'after':{'rows':[{'platform':p,'b2c':'.3' if p=='PC' else '.2'} for p in ['PS','XBOX','PC']]}}
        self.job={'job_id':pid,'kind':'player_sync','status':'failed','error':'player_sync_not_confirmed','error_detail':'player_sample_readback_timeout','created_at':'2030-01-01T00:00:00+00:00','completed_at':'2030-01-01T00:00:01+00:00','request':{'config_revision':8},'sync_result':{'reason':'player_sample_readback_timeout'}}
        self.ledger={'job_id':pid,'coin_execution_id':cid,'status':'needs_reconcile','stage':'stopped','mode':'category_all','error':'player_sample_readback_timeout','sample_count':5,'sample_model_ids':self.scope['sample_model_ids'],'sample_before':{},'sample_readback':{},'sample_verified_count':0,'verified_count':0,'model_count':771,'model_ids_sha256':'b'*64,'created_at':'2030-01-01T00:00:00+00:00'}
        self.proof={'checked_at':self.now.isoformat(),'read_only':True,'business_posts':0,'job_id':pid,'coin_execution_id':cid,'expected_rates':{'PS':'.2','XBOX':'.2','PC':'.3'},'coin_readbacks':[],'samples':[],'coins_public':[],'sample_model_ids':self.scope['sample_model_ids'],'player_policy':self.policy,'source_sha256':self.scope['expected_sources']['/opt/fc27-cloud-browser/player_sync_job.py'],'model_count':771,'model_scope_digest':'b'*64}
        for i,mid in enumerate(self.scope['sample_model_ids']):
            products=[];parts=[]
            for j,p in enumerate(['PS','XBOX','PC']):
                target=str(D(10000)/1000*D(self.proof['expected_rates'][p])*D('1.1'))
                for site in [0,266]:products.append({'id':100000+i*10+j*2+(site==266),'mid':mid,'gid':1327,'cid':9627,'aid':{'PS':21587,'XBOX':21585,'PC':21589}[p],'site_id':site,'status':1,'total':10,'platform':p,'unit_price':target})
                parts.append({'product_id':products[-1]['id'],'platform':p,'our_price_coins':'10000','coefficient':'1.1','target_usd':target,'backend_usd':target,'public_usd':target,'backend_match':True,'public_match':True})
            self.scope['sample_product_ids'][str(mid)]=sorted(x['id'] for x in products)
            self.ledger['sample_before'][str(mid)]=copy.deepcopy(parts);self.ledger['sample_readback'][str(mid)]=copy.deepcopy(parts)
            self.proof['samples'].append({'model_id':mid,'model':{'id':mid,'gid':1327,'cid':9627,'status':1,'title':'Synthetic Model'},'model_inputs':{'PS':'10000','XBOX':'10000','PC':'10000','coefficient':'1.1'},'products':products,'public_readback':parts})
        for p in ['PS','XBOX','PC']:
            for site in [0,266]:
                product_id={'PS':{0:163329309,266:163329311},'XBOX':{0:163329275,266:163329277},'PC':{0:163329343,266:163329345}}[p][site]
                prices=[str(D(g)*D(self.proof['expected_rates'][p])) for g in self.scope['tier_gold']]
                self.proof['coin_readbacks'].append({'platform':p,'site_id':site,'product_id':product_id,'actual_unit_price':self.proof['expected_rates'][p],'http_status':200,'response_code':1,'identity':{'id':product_id,'mid':41217957,'gid':1327,'cid':9623,'aid':{'PS':21587,'XBOX':21585,'PC':21589}[p],'site_id':site,'status':1},'tier_gold':self.scope['tier_gold'],'tier_give':self.scope['tier_give'],'tier_discount':self.scope['tier_discount'],'tier_price':prices})
            self.proof['coins_public'].append({'platform':p,'sku_id':product_id,'tiers':[{'num':g,'give':v,'discount':disc,'price':price,'price_discount':price} for g,v,disc,price in zip(self.scope['tier_gold'],self.scope['tier_give'],self.scope['tier_discount'],prices)]})
        coinjob={'job_id':cid,'kind':'auto_cycle','status':'ready','created_at':'2030-01-01T00:00:00+00:00','result':{'status':'confirmed'},'public_page_readback':{'status':'unconfirmed'},'player_sync':{'status':'queued','job_id':pid},'player_sync_intent':{'enabled':True,'revision':8}}
        self.all_ledger={'status':'confirmed','steps':[]}
        for platform in ['PS','XBOX','PC']:
            row=next(r for r in self.proof['coin_readbacks'] if r['platform']==platform)
            payload={'unit_price':row['actual_unit_price'],'more':{'gold':row['tier_gold'],'give':row['tier_give'],'discount':row['tier_discount'],'price':row['tier_price']}}
            self.all_ledger['steps'].append({'platform':platform,'status':'confirmed','source':copy.deepcopy(payload),'payload':copy.deepcopy(payload)})
        self.gallery={'revision':8,'settings':{'enabled':False,'interval_minutes':600}}
        values={'jobs/'+pid+'.json':self.job,'player-sync/'+pid+'.json':self.ledger,'executions/'+cid+'.json':self.audit,'jobs/'+cid+'.json':coinjob,'all-coin-sync/'+cid+'.json':self.all_ledger,'config/automation.json':{'system_enabled':True,'revision':28,'schedule_revision':28,'interval_minutes':120},'config/player-sync.json':self.policy,'/var/lib/fc27-gallery/settings.json':self.gallery}
        self.store=MemoryStore({k:encode(v) for k,v in values.items()})
        self.scope['expected_files']={k:digest(raw) for k,raw in self.store.live.items()}
        self.proof['ledger_sha256']=self.scope['expected_files']['player-sync/'+pid+'.json']
        self.proof['started_at']=self.now.isoformat();self.proof['provenance']=copy.deepcopy(self.scope['proof_provenance'])
        # Exact real monitor_view top-level contract, intentionally NO gallery.
        self.monitor={key:{} for key in ['storefront','latest_attempt','latest_collection','page_readback','cache_refresh','automation','player_sync','health']}
        self.monitor.update(generated_at=self.now.isoformat(),publication={'execution_id':cid})
        self.proof_mutation=None;self.other_jobs=[];self.other_executions=[];self.queue=[]
        self.store.delay=lambda seconds:self.wait(seconds)

    def context(self,allowed):
        jobs=[json.loads(raw) for k,raw in self.store.live.items() if k.startswith('jobs/')]+self.other_jobs
        executions=[json.loads(raw) for k,raw in self.store.live.items() if k.startswith('executions/')]+self.other_executions
        validate_context(self.scope,self.store.live,self.monitor,self.gallery,jobs,executions,self.queue,self.scope['expected_sources'],allowed)
        if self.store.log and self.store.log[-1]==('stage_fsync',getattr(self,'slow_context_target',None)):
            self.wait(getattr(self,'slow_context_seconds',0));self.monotonic_offset=getattr(self,'slow_context_monotonic',0)

    def probe(self,ledger,raw):
        self.calls+=1;proof=copy.deepcopy(self.proof);proof['started_at']=self.now.isoformat();proof['checked_at']=self.now.isoformat()
        if self.proof_mutation:self.proof_mutation(proof,self.calls)
        return proof

    def wait(self,seconds):self.now+=timedelta(seconds=seconds)

    def recovery(self,event=None):return Recovery(self.store,self.scope,'a'*64,self.context,self.probe,now=lambda:self.now,wait=self.wait,event=event,monotonic=lambda:self.now.timestamp()+getattr(self,'monotonic_offset',0))
