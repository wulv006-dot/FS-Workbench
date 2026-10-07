"""Synthetic data only; real monitor keys and separate Gallery settings contract.
MemoryStore simulates ordering/failures; it does NOT certify native fsync/locks.
"""
import copy,json,unittest,stat
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from reconcile import Recovery,validate_round,stable,encode,digest,approved_tiers
from runner import validate_context
from secure_fs import validate_stat

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

class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2030,1,1,tzinfo=timezone.utc);self.calls=0;self.events=[]
        self.scope=json.loads((Path(__file__).parent/'scope.json').read_text());self.scope['sample_model_ids']=list(range(1001,1006));self.scope['sample_product_ids']={}
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
    def guard(self):return validate_round(self.scope,self.ledger,self.job,self.audit,self.policy,self.proof,self.now,approved_tiers(self.all_ledger,self.audit,self.scope))
    def bad(self,change,message):change();self.assertRaisesRegex(ValueError,message,self.guard)
    def test_positive_exact_synthetic_proof(self):self.assertTrue(self.guard())
    def test_old_public_price(self):self.bad(lambda:self.proof['samples'][0]['public_readback'][0].update(public_usd='1'),'price_mismatch')
    def test_wrong_all_baseline(self):self.bad(lambda:self.proof['coin_readbacks'][0].update(actual_unit_price='.21'),'baseline_changed')
    def test_changed_coin_inputs(self):self.bad(lambda:self.proof['samples'][0]['public_readback'][0].update(our_price_coins='10001'),'inputs_changed')
    def test_changed_public_product(self):self.bad(lambda:self.proof['samples'][0]['public_readback'][0].update(product_id=999),'product_scope_changed')
    def test_expired_proof(self):self.now+=timedelta(seconds=61);self.assertRaisesRegex(ValueError,'expired',self.guard)
    def test_future_proof(self):self.proof['checked_at']=(self.now+timedelta(seconds=1)).isoformat();self.assertRaisesRegex(ValueError,'expired',self.guard)
    def test_player_revision(self):self.policy['revision']=9;self.assertRaisesRegex(ValueError,'state_changed',self.guard)
    def test_uncertain_post(self):self.ledger['error']='backend_request_rejected';self.assertRaisesRegex(ValueError,'state_changed',self.guard)
    def test_stability_mismatch(self):other=copy.deepcopy(self.proof);other['samples'][0]['public_readback'][0]['public_usd']='2.2001';self.assertNotEqual(stable(self.proof),stable(other))
    def test_wrong_coin_product_identity(self):self.bad(lambda:self.proof['coin_readbacks'][0].update(product_id=999),'product_identity_changed')
    def test_wrong_coin_game(self):self.bad(lambda:self.proof['coin_readbacks'][0]['identity'].update(gid=999),'backend_identity_changed')
    def test_gift_change(self):self.proof=copy.deepcopy(self.proof);self.bad(lambda:self.proof['coin_readbacks'][0].update(tier_give=[0]*15),'quantity_vector_changed')
    def test_public_coin_stale(self):self.bad(lambda:self.proof['coins_public'][0]['tiers'][0].update(price='99'),'price_or_quantity_mismatch')
    def test_public_coin_discount_changed(self):self.bad(lambda:self.proof['coins_public'][0]['tiers'][0].update(discount=99),'price_or_quantity_mismatch')
    def test_public_coin_duplicate_platform(self):self.bad(lambda:self.proof['coins_public'][2].update(platform='PS'),'identity_changed|platforms_changed')
    def test_missing_public_coin_platform(self):self.bad(lambda:self.proof['coins_public'].pop(),'scope_incomplete')
    def test_unexpected_business_post(self):self.bad(lambda:self.proof.update(business_posts=1),'business_write_forbidden')
    def test_missing_readonly_flag(self):self.bad(lambda:self.proof.update(read_only=False),'business_write_forbidden')
    def test_original_ledger_digest(self):self.bad(lambda:self.proof.update(ledger_sha256='0'*64),'ledger_changed')
    def test_player_source_digest(self):self.bad(lambda:self.proof.update(source_sha256='0'*64),'source_changed')
    def test_full_model_scope_digest(self):self.bad(lambda:self.proof.update(model_scope_digest='0'*64),'model_scope_changed')
    def test_full_model_count(self):self.bad(lambda:self.proof.update(model_count=772),'model_scope_changed')
    def test_sample_order(self):self.bad(lambda:self.proof.update(sample_model_ids=list(reversed(self.scope['sample_model_ids']))),'identity_changed')
    def test_missing_all_player_link(self):self.bad(lambda:self.proof['samples'][0]['products'].pop(0),'linked_scope_incomplete')
    def test_changed_all_player_id(self):self.bad(lambda:self.proof['samples'][0]['products'][0].update(id=999),'product_ids_changed')
    def test_wrong_player_area(self):self.bad(lambda:self.proof['samples'][0]['products'][0].update(aid=999),'area_identity_changed')
    def test_backend_price_mismatch(self):self.bad(lambda:self.proof['samples'][0]['products'][0].update(unit_price='1'),'linked_price_mismatch')
    def test_false_match_flag(self):self.bad(lambda:self.proof['samples'][0]['public_readback'][0].update(public_match=False),'match_flags_false')
    def test_real_monitor_without_gallery_passes(self):
        self.assertNotIn('gallery',self.monitor);self.context({})
    def test_bound_directory_contract_covers_all_runtime_inputs(self):
        frozen=json.loads((Path(__file__).parent/'scope.json').read_text())
        for name in ['jobs','executions','queue']:
            self.assertIn('/var/lib/fc27-cloud/'+name,frozen['trusted_directories'])
        for path in frozen['trusted_directories']:
            if path!='/':self.assertIn(path.rsplit('/',1)[0] or '/',frozen['trusted_directories'])
        self.assertEqual(frozen['trusted_directories']['/var/lib/fc27-cloud/queue']['mode'],'0o2770')
    def test_gallery_separate_source_fails_on_change(self):
        self.gallery['settings']['enabled']=True;self.assertRaisesRegex(ValueError,'gallery_intent',self.context,{})
    def test_earliest_observation105s_end55s_rejected(self):
        self.proof['started_at']=(self.now-timedelta(seconds=105)).isoformat();self.proof['checked_at']=(self.now-timedelta(seconds=55)).isoformat()
        self.assertRaisesRegex(ValueError,'earliest_observation_expired',self.guard)
    def test_provenance_image_or_helper_change_rejected(self):
        self.proof['provenance']['python']='unexpected';self.assertRaisesRegex(ValueError,'dependency_origin',self.guard)
    def test_site_and_public_agree_wrong_target_rejected(self):
        self.proof['coin_readbacks'][1]['tier_price']=list(self.proof['coin_readbacks'][1]['tier_price']);self.proof['coin_readbacks'][1]['tier_price'][0]='99'
        self.proof['coins_public'][0]['tiers'][0].update(price='99',price_discount='99')
        self.assertRaisesRegex(ValueError,'approved_tier_target',self.guard)
    def test_all_only_wrong_target_rejected(self):
        self.proof['coin_readbacks'][0]['tier_price']=list(self.proof['coin_readbacks'][0]['tier_price']);self.proof['coin_readbacks'][0]['tier_price'][0]='99'
        self.assertRaisesRegex(ValueError,'approved_tier_target',self.guard)
    def test_immutable_approved_source_payload_disagree_rejected(self):
        self.all_ledger['steps'][0]['payload']['more']['price'][0]='99';self.assertRaisesRegex(ValueError,'target_disagreement',self.guard)
    def test_preflight_has_zero_storage_writes(self):
        result=self.recovery().run();self.assertEqual(result['status'],'reconcile_preflight_ready');self.assertFalse(self.store.exists);self.assertEqual(self.store.log,[]);self.assertEqual(self.calls,2)
    def test_apply_preserves_errors_and_unrelated_bytes(self):
        before=copy.deepcopy(self.store.live);result=self.recovery().run(True);self.assertEqual(result['status'],'confirmed_by_independent_reconciliation')
        ledger=json.loads(self.store.live[self.scope['allowed_metadata_targets'][0]]);job=json.loads(self.store.live[self.scope['allowed_metadata_targets'][1]])
        self.assertEqual(ledger['recoveries'][0]['original'],self.ledger);self.assertEqual(job['recovery_history'][0]['original'],self.job)
        for k,raw in before.items():
            if k not in self.scope['allowed_metadata_targets']:self.assertEqual(raw,self.store.live[k])
    def test_receipt_evidence_durable_before_consumer_ready(self):
        ledger,job=self.scope['allowed_metadata_targets']
        def consumer(k,raw):
            if k==job:
                self.assertEqual(json.loads(raw)['status'],'ready');self.assertEqual(json.loads(self.store.live[ledger])['status'],'confirmed')
                receipt=json.loads(self.store.private['transaction.json']);self.assertEqual(receipt['phase'],'evidence_committed')
                self.assertTrue(receipt['proof_history']);self.assertIn('after-job.json',self.store.private)
        self.store.on_publish=consumer;self.recovery().run(True)
        rename=next(i for i,item in enumerate(self.store.log) if item==('rename',job))
        self.assertFalse(any(isinstance(x,tuple) and x[0]=='durable' for x in self.store.log[rename+1:]))
    def test_backup_fsync_delay_expires_before_metadata(self):
        self.store.delays['before-0.json']=61;self.assertRaisesRegex(ValueError,'expired',self.recovery().run,True)
        self.assertFalse(any(isinstance(x,tuple) and x[0]=='rename' for x in self.store.log))
    def test_job_stage_fsync_delay_rejects_before_job_rename(self):
        ledger,job=self.scope['allowed_metadata_targets'];self.store.delays[job]=61
        self.assertEqual(self.recovery().run(True)['status'],'metadata_may_be_committed_needs_readback');self.assertEqual(json.loads(self.store.live[job])['status'],'failed')
    def test_160s_budget_includes_backup(self):
        self.store.delays['before-0.json']=161;self.assertRaisesRegex(ValueError,'expired|total_budget',self.recovery().run,True)
    def test_slow_context_crosses60s_before_final_job_rename(self):
        job=self.scope['allowed_metadata_targets'][1];self.store.delays[job]=54
        self.slow_context_target=job;self.slow_context_seconds=2
        self.assertEqual(self.recovery().run(True)['status'],'metadata_may_be_committed_needs_readback')
        self.assertEqual(json.loads(self.store.live[job])['status'],'failed');self.assertNotIn(('rename',job),self.store.log)
    def test_slow_context_crosses160s_before_final_job_rename(self):
        job=self.scope['allowed_metadata_targets'][1];self.slow_context_target=job;self.slow_context_monotonic=161
        result=self.recovery().run(True);self.assertEqual(result['status'],'metadata_may_be_committed_needs_readback');self.assertEqual(result['reason'],'reconcile_total_budget_exceeded')
        self.assertEqual(json.loads(self.store.live[job])['status'],'failed');self.assertNotIn(('rename',job),self.store.log)
    def test_slow_context_before_ledger_keeps_both_originals(self):
        ledger,job=self.scope['allowed_metadata_targets'];before=copy.deepcopy(self.store.live)
        self.store.delays[ledger]=54;self.slow_context_target=ledger;self.slow_context_seconds=2
        self.assertRaisesRegex(ValueError,'expired',self.recovery().run,True)
        self.assertEqual(self.store.live[ledger],before[ledger]);self.assertEqual(self.store.live[job],before[job])
    def test_partial_ledger_rename_retry_synchronizes_before_job(self):
        ledger,job=self.scope['allowed_metadata_targets'];self.store.failure=ledger
        self.assertRaises(OSError,self.recovery().run,True);self.assertEqual(json.loads(self.store.live[job])['status'],'failed')
        self.store.failure=None;self.recovery().run(True)
        self.assertLess(self.store.log.index(('sync_visible',ledger)),self.store.log.index(('rename',job)))
    def test_partial_ledger_retry_sync_failure_keeps_job_failed(self):
        ledger,job=self.scope['allowed_metadata_targets'];self.store.failure=ledger
        self.assertRaises(OSError,self.recovery().run,True);self.store.failure='sync_visible'
        self.assertRaises(OSError,self.recovery().run,True);self.assertEqual(json.loads(self.store.live[job])['status'],'failed')
    def interrupt(self,stage):
        def event(actual):
            if actual==stage:raise RuntimeError('synthetic interruption')
        self.assertRaisesRegex(RuntimeError,'interruption',self.recovery(event).run,True)
        return self.recovery()
    def test_interrupt_prepared_retry_reads_fresh_proof(self):
        r=self.interrupt('prepared');calls=self.calls;self.assertEqual(r.run(True)['status'],'confirmed_by_independent_reconciliation');self.assertEqual(self.calls,calls+2)
    def test_interrupt_ledger_installed_gate_failed(self):
        r=self.interrupt('ledger_installed');self.assertEqual(json.loads(self.store.live[self.scope['allowed_metadata_targets'][1]])['status'],'failed');self.assertEqual(r.run(True)['status'],'confirmed_by_independent_reconciliation')
    def test_interrupt_evidence_committed_gate_failed(self):
        r=self.interrupt('evidence_committed');self.assertEqual(json.loads(self.store.live[self.scope['allowed_metadata_targets'][1]])['status'],'failed');self.assertEqual(r.run(True)['status'],'confirmed_by_independent_reconciliation')
    def test_job_dir_fsync_uncertainty_report_and_exact_retry(self):
        job=self.scope['allowed_metadata_targets'][1];self.store.failure=job
        self.assertEqual(self.recovery().run(True)['status'],'metadata_may_be_committed_needs_readback');calls=self.calls
        self.store.failure=None;self.assertEqual(self.recovery().run(True)['status'],'already_reconciled_exact_publication');self.assertEqual(self.calls,calls)
    def test_retry_fsync_failure_reports_visible_uncertainty(self):
        self.recovery().run(True);self.store.failure='sync_visible';self.assertEqual(self.recovery().run(True)['status'],'metadata_may_be_committed_needs_readback')
    def test_evidence_receipt_fsync_failure_keeps_gate_failed(self):
        def event(stage):
            if stage=='ledger_installed':self.store.failure='transaction.json'
        self.assertRaises(OSError,self.recovery(event).run,True);self.assertEqual(json.loads(self.store.live[self.scope['allowed_metadata_targets'][1]])['status'],'failed')
    def test_queue_between_ledger_job_keeps_gate_failed(self):
        def event(stage):
            if stage=='ledger_installed':self.queue.append({})
        self.assertRaisesRegex(ValueError,'conflict',self.recovery(event).run,True);self.assertEqual(json.loads(self.store.live[self.scope['allowed_metadata_targets'][1]])['status'],'failed')
    def test_queued_running_newer_and_uncertain_contexts(self):
        for collection,row,expected in [(self.queue,{},'conflict'),(self.other_jobs,{'status':'running'},'conflict'),(self.other_jobs,{'kind':'player_sync','status':'ready','job_id':'new','created_at':'2031'},'newer_player'),(self.other_executions,{'status':'UNCERTAIN'},'unconfirmed_execution')]:
            collection.append(row)
            with self.assertRaisesRegex(ValueError,expected):self.context({})
            collection.pop()
    def test_raw_cas_before_probe(self):
        self.store.live['jobs/'+self.pid+'.json']=b'{}';self.assertRaisesRegex(ValueError,'cas_changed',self.recovery().run,True);self.assertEqual(self.calls,0)
    def test_source_digest_drift(self):
        bad=copy.deepcopy(self.scope['expected_sources']);bad[next(iter(bad))]='0'*64
        with self.assertRaisesRegex(ValueError,'dependency_changed'):validate_context(self.scope,self.store.live,self.monitor,self.gallery,[],[],[],bad,{})
    def test_backup_proof_tamper_and_path_escape(self):
        self.interrupt('prepared');self.store.private['proofs-0.json']=b'{}';self.assertRaisesRegex(ValueError,'backup_proof_changed',self.recovery().run,True)
    def test_transaction_proof_record_escape_rejected(self):
        self.interrupt('prepared');state=json.loads(self.store.private['transaction.json']);state['proof_history'][0]['name']='../escape';self.store.private['transaction.json']=encode(state)
        self.assertRaisesRegex(ValueError,'proof_record_path',self.recovery().run,True)
    def test_recomputed_intended_hash_not_proof_driven(self):
        self.interrupt('prepared');state=json.loads(self.store.private['transaction.json']);ledger=self.scope['allowed_metadata_targets'][0]
        value=json.loads(self.store.private['after-ledger.json']);value['verified_count']=771;raw=encode(value);self.store.private['after-ledger.json']=raw;state['after_sha256'][ledger]=digest(raw);self.store.private['transaction.json']=encode(state)
        self.assertRaisesRegex(ValueError,'not_proof_driven',self.recovery().run,True)
    def test_partial_resume_public_regression_blocks(self):
        r=self.interrupt('ledger_installed');self.proof_mutation=lambda p,n:p['samples'][0]['public_readback'][0].update(public_usd='1')
        self.assertRaisesRegex(ValueError,'price_mismatch',r.run,True);self.assertEqual(json.loads(self.store.live[self.scope['allowed_metadata_targets'][1]])['status'],'failed')
    def test_stat_rejects_hardlink_untrusted_owner_and_mode(self):
        expected={'uid':0,'gid':0,'mode':'0o600'};good=dict(st_mode=stat.S_IFREG|0o600,st_nlink=1,st_uid=0,st_gid=0,st_dev=1,st_ino=1)
        validate_stat(SimpleNamespace(**good),expected,'file',True)
        for key,value in [('st_nlink',2),('st_uid',1234),('st_mode',stat.S_IFREG|0o666),('st_mode',stat.S_IFLNK|0o600)]:
            changed={**good,key:value}
            with self.assertRaises(ValueError):validate_stat(SimpleNamespace(**changed),expected,'file',True)

if __name__=='__main__':unittest.main(verbosity=2)
