"""Targeted new-diff tests. Historical 57/76 suites are not executed here."""
import copy,hashlib,importlib,json,os,sys,types,unittest,uuid
import tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
import test_v4 as fixtures
from fixture import Fixture,MemoryStore
from reconcile import encode,digest
from supersede import Supersession,validate_supersession_round
import launch

class SupersessionTests(Fixture,unittest.TestCase):
    def setUp(self):
        Fixture.setUp(self)
        old=self.cid;self.old=old;self.cid='00000000-0000-4000-8000-000000000009'
        self.scope['coin_execution_id']=self.cid
        self.scope['supersession']={'mode':'later_confirmed_coin','old_coin_execution_id':old}
        self.scope['player_revision']=8
        self.audit['created_at']='2029-12-31T23:59:00+00:00'
        self.store.live['executions/'+old+'.json']=encode(self.audit)
        audit=copy.deepcopy(self.audit);audit.update(execution_id=self.cid,automatic=False,sync_confirmed=True,created_at='2030-01-01T00:00:00+00:00')
        for r in audit['after']['rows']:
            if r['platform']!='PC':r['b2c']='.1'
        ledger=copy.deepcopy(self.all_ledger)
        for step in ledger['steps']:
            rate='.3' if step['platform']=='PC' else '.1'
            for name in ['source','payload']:
                step[name]['unit_price']=rate;step[name]['more']['price']=[str(Decimal(g)*Decimal(rate)) for g in self.scope['tier_gold']]
        self.store.live['executions/'+self.cid+'.json']=encode(audit)
        self.store.live['all-coin-sync/'+self.cid+'.json']=encode(ledger)
        self.store.live['jobs/'+self.cid+'.json']=encode({'job_id':self.cid,'kind':'execute','status':'ready','created_at':audit['created_at'],'result':{'status':'CONFIRMED'}})
        self.scope['expected_files']={k:digest(v) for k,v in self.store.live.items()}
        self.monitor['publication']['execution_id']=self.cid
        self.proof['coin_execution_id']=self.cid;self.proof['expected_rates']={'PS':'.1','XBOX':'.1','PC':'.3'}
        for r in self.proof['coin_readbacks']:
            rate=self.proof['expected_rates'][r['platform']];r['actual_unit_price']=rate;r['tier_price']=[str(Decimal(g)*Decimal(rate)) for g in self.scope['tier_gold']]
        for r in self.proof['coins_public']:
            for i,t in enumerate(r['tiers']):t['price']=t['price_discount']=str(Decimal(self.scope['tier_gold'][i])*Decimal(self.proof['expected_rates'][r['platform']]))
        for sample in self.proof['samples']:
            for part in sample['public_readback']:
                part['target_usd']=str(Decimal(part['our_price_coins'])/1000*Decimal(self.proof['expected_rates'][part['platform']])*Decimal(part['coefficient']))
                part['backend_match']=part['public_match']=part['platform']=='PC'
    def operation(self,event=None):
        return Supersession(self.store,self.scope,'a'*64,self.context,self.probe,now=lambda:self.now,wait=self.wait,event=event,monotonic=lambda:self.now.timestamp())
    def test_success_preserves_original_error_completion_and_prices(self):
        originals=copy.deepcopy(self.store.live);result=self.operation().run(True)
        self.assertEqual(result['status'],'historical_failure_superseded_current_coin_readback')
        for key in self.scope['allowed_metadata_targets']:
            after=json.loads(self.store.live[key]);before=json.loads(originals[key])
            self.assertEqual(after['status'],'superseded')
            for field in ['error','error_detail','completed_at','result','stage','sync_result']:
                self.assertEqual(after.get(field),before.get(field))
        for key in originals:
            if key not in self.scope['allowed_metadata_targets']:self.assertEqual(self.store.live[key],originals[key])
        self.assertEqual(result['business_posts'],0)
    def test_private_receipt_is_durable_before_gate_readable_job(self):
        self.operation().run(True);log=self.store.log
        receipt=next(i for i,e in enumerate(log) if isinstance(e,tuple) and e[:2]==('durable','supersession-receipt.json'))
        job=next(i for i,e in enumerate(log) if isinstance(e,tuple) and e[:2]==('rename','jobs/'+self.pid+'.json'))
        self.assertLess(receipt,job);self.assertFalse(any(e[0]=='durable' for e in log[job+1:] if isinstance(e,tuple)))
    def test_preflight_does_not_mutate_metadata(self):
        before=copy.deepcopy(self.store.live);self.assertEqual(self.operation().run()['status'],'supersession_preflight_ready');self.assertEqual(before,self.store.live);self.assertFalse(self.store.exists)
    def test_partial_ledger_publication_resumes_exact_original_intent(self):
        def stop(stage):
            if stage=='ledger_installed':raise ValueError('isolated stop')
        with self.assertRaisesRegex(ValueError,'isolated stop'):self.operation(stop).run(True)
        self.assertEqual(json.loads(self.store.live['jobs/'+self.pid+'.json'])['status'],'failed')
        self.assertEqual(self.operation().run(True)['status'],'historical_failure_superseded_current_coin_readback')
    def test_final_commit_unknown_is_not_claimed_as_success_then_exact_resume(self):
        self.store.failure='jobs/'+self.pid+'.json'
        self.assertEqual(self.operation().run(True)['status'],'metadata_may_be_committed_needs_readback')
        self.store.failure=None;calls=self.calls
        self.assertEqual(self.operation().run(True)['status'],'already_superseded_exact_publication');self.assertEqual(calls,self.calls)
    def test_receipt_fsync_failure_leaves_failed_gate_job(self):
        self.store.failure='supersession-receipt.json'
        with self.assertRaises(OSError):self.operation().run(True)
        self.assertEqual(json.loads(self.store.live['jobs/'+self.pid+'.json'])['status'],'failed')
    def test_corrupt_private_receipt_refuses_resume(self):
        self.operation().run(True);r=json.loads(self.store.private['supersession-receipt.json']);r['marker']['superseding_coin_execution_id']=self.old;self.store.private['supersession-receipt.json']=encode(r)
        with self.assertRaisesRegex(ValueError,'supersession_receipt_changed'):self.operation().run(True)
    def test_coin_http_price_public_tier_and_origin_negative_proofs(self):
        mutators=[lambda p:p['coin_readbacks'][0].update(http_status=500),lambda p:p['coin_readbacks'][0].update(actual_unit_price='.9'),lambda p:p['coins_public'][0]['tiers'][0].update(price='.9'),lambda p:p.update(business_posts=1),lambda p:p['provenance'].update(loader='unsealed'),lambda p:p['samples'][0]['products'][0].update(site_id=88),lambda p:p['samples'][0]['public_readback'][0].update(backend_match=True)]
        for mutate in mutators:
            with self.subTest(mutation=mutate):
                self.proof_mutation=lambda p,n:mutate(p)
                with self.assertRaises(ValueError):self.operation().run(True)
                self.assertFalse(self.store.exists)
    def test_new_coin_cas_and_policy_revision_change_refused(self):
        for key in ['executions/'+self.cid+'.json','config/player-sync.json']:
            with self.subTest(key=key):
                before=self.store.live[key];self.store.live[key]=before+b' '
                with self.assertRaisesRegex(ValueError,'scope_file_cas_changed'):self.operation().run(True)
                self.store.live[key]=before

class FollowupIncrementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.QueueTests.setUpClass.__func__(cls)
        ocr=types.ModuleType('ddddocr')
        def forbidden_ocr(*args,**kwargs):raise AssertionError('OCR is outside targeted test scope')
        ocr.DdddOcr=forbidden_ocr
        with patch.dict(sys.modules,{'ddddocr':ocr}):cls.player=importlib.import_module('player_sync_job')
    @classmethod
    def tearDownClass(cls):fixtures.QueueTests.tearDownClass.__func__(cls)
    add=fixtures.QueueTests.add
    def setUp(self):
        fixtures.QueueTests.setUp(self)
        self.cid='00000000-0000-4000-8000-000000000009';self.old='00000000-0000-4000-8000-000000000001';self.parent_id='00000000-0000-4000-8000-000000000005'
        self.at=datetime.now(timezone.utc)
        self.basis={'old_player_job_id':self.old,'coin_execution_id':self.cid,'coin_execution_sha256':'a'*64,'supersession_proof_sha256':'b'*64,'all_ledger_sha256':'c'*64,'source_sha256':{},'preview_id':self.parent_id,'coin_revision':28,'player_revision':8}
        self.parent={'job_id':self.parent_id,'kind':'auto_cycle','actor':'system-automation','status':'ready','run_id':self.parent_id,'request':{'policy_revision':28},'result':{'status':'no_price_change'},'completed_at':self.at.isoformat(),'player_sync_basis':self.basis,'player_sync_intent':{'enabled':True,'revision':8}}
        self.config={'enabled':True,'revision':8}
        self.add(patch.object(self.tick,'load_player_sync_policy',lambda:self.config))
        self.valid={'parent_id':self.parent_id,'parent_fields_sha256':self.worker.parent_fields_hash(self.parent),'basis':self.basis}
    def tearDown(self):fixtures.QueueTests.tearDown(self)
    def test_same_current_coin_basis_deduplicates_two_different_cycle_parents(self):
        with patch.object(self.worker,'validate_nochange_parent',return_value=self.valid) as validate:
            first=self.worker.enqueue_player_sync(self.parent,self.config)
            other=copy.deepcopy(self.parent);other['job_id']='00000000-0000-4000-8000-000000000006'
            second=self.worker.enqueue_player_sync(other,self.config)
        self.assertEqual(first['status'],'queued');self.assertEqual(second,{'status':'already_queued','job_id':first['job_id']});self.assertEqual(validate.call_count,1)
        self.assertEqual(first['job_id'],str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+self.cid)))
    def test_claimed_failed_interrupted_and_unknown_jobs_never_replay(self):
        jid=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+self.cid))
        for status in ['running','failed','interrupted','ready']:
            with self.subTest(status=status),patch.object(self.worker,'validate_nochange_parent') as validate:
                (self.root/'jobs'/(jid+'.json')).write_text(json.dumps({'status':status}),encoding='utf-8')
                self.assertEqual(self.worker.enqueue_player_sync(self.parent,self.config)['status'],'already_queued');validate.assert_not_called()
                self.assertFalse((self.root/'queue'/(jid+'.json')).exists())
    def test_off_and_invalid_ordinary_parent_do_not_queue(self):
        self.assertEqual(self.worker.enqueue_player_sync(self.parent,{'enabled':False,'revision':8})['status'],'disabled')
        bad=copy.deepcopy(self.parent);bad.pop('player_sync_basis')
        with self.assertRaisesRegex(ValueError,'player_sync_coin_not_confirmed'):self.worker.enqueue_player_sync(bad,self.config)
    def test_ordinary_confirmed_auto_path_identity_unchanged(self):
        ordinary={'job_id':self.parent_id,'kind':'auto_cycle','result':{'status':'confirmed'}}
        with patch.object(self.worker,'validate_nochange_parent') as validate:
            result=self.worker.enqueue_player_sync(ordinary,self.config);validate.assert_not_called()
        self.assertEqual(result['job_id'],str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+self.parent_id)))
    def test_nochange_pending_intent_blocks_later_cycle_until_queue_durable(self):
        (self.root/'jobs'/(self.parent_id+'.json')).write_text(json.dumps(self.parent),encoding='utf-8')
        self.assertEqual(self.tick.player_sync_gate(),'needs_reconcile')
    def test_parent_hash_excludes_followup_link_but_includes_price_basis(self):
        before=self.worker.parent_fields_hash(self.parent);self.parent['player_sync']={'status':'queued'}
        self.assertEqual(before,self.worker.parent_fields_hash(self.parent));self.parent['player_sync_basis']['coin_revision']=29
        self.assertNotEqual(before,self.worker.parent_fields_hash(self.parent))
    def capsule(self):
        audit={'execution_id':self.cid,'status':'CONFIRMED','sync_confirmed':True,'automatic':False,'all_baseline':{'status':'confirmed'}}
        eraw=encode(audit);lraw=encode({'status':'confirmed'})
        self.basis['coin_execution_sha256']=digest(eraw);self.basis['all_ledger_sha256']=digest(lraw)
        self.valid={'parent_id':self.parent_id,'parent_fields_sha256':self.player.basis_parent_hash(self.parent),'basis':copy.deepcopy(self.basis)}
        request={'job_id':str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+self.cid)),'coin_execution_id':self.cid,'config_revision':8,'automatic_basis':self.valid}
        policy={'system_enabled':True,'mode':'auto','revision':28}
        return request,audit,copy.deepcopy(self.parent),policy,eraw,lraw
    def test_manual_confirmed_basis_requires_durable_fresh_auto_parent(self):
        request,audit,parent,policy,eraw,lraw=self.capsule()
        self.assertEqual(self.player.validate_automatic_basis(request,audit,self.config,parent,policy,eraw,lraw,self.at),{'status':'confirmed'})
    def test_capsule_rejects_changed_parent_policy_coin_hash_and_deterministic_identity(self):
        for field in ['parent_status','parent_actor','parent_age','parent_basis','coin_status','coin_sync','coin_hash','all_hash','coin_policy','player_off','player_revision','parent_hash','child_id']:
            with self.subTest(field=field):
                request,audit,parent,policy,eraw,lraw=self.capsule();config=copy.deepcopy(self.config)
                if field=='parent_status':parent['status']='failed'
                if field=='parent_actor':parent['actor']='wulv'
                if field=='parent_age':parent['completed_at']=(self.at-timedelta(seconds=301)).isoformat();request['automatic_basis']['parent_fields_sha256']=self.player.basis_parent_hash(parent)
                if field=='parent_basis':parent['player_sync_basis']['coin_execution_id']=self.old
                if field=='coin_status':audit['status']='UNCERTAIN'
                if field=='coin_sync':audit['sync_confirmed']=False
                if field=='coin_hash':eraw+=b' '
                if field=='all_hash':lraw+=b' '
                if field=='coin_policy':policy['revision']=29
                if field=='player_off':config['enabled']=False
                if field=='player_revision':config['revision']=9
                if field=='parent_hash':request['automatic_basis']['parent_fields_sha256']='0'*64
                if field=='child_id':request['job_id']=self.parent_id
                with self.assertRaises(ValueError):self.player.validate_automatic_basis(request,audit,config,parent,policy,eraw,lraw,self.at)
    def test_arbitrary_manual_execution_is_blocked_before_session_or_post(self):
        request={'job_id':self.parent_id,'coin_execution_id':self.cid,'config_revision':8}
        values={self.player.REQUEST:request,self.player.EXECUTION:{'execution_id':self.cid,'status':'CONFIRMED','automatic':False},self.player.POLICY:self.config}
        with patch.object(self.player,'read',side_effect=lambda p:values[p]),patch.object(self.player,'SessionManager') as session,patch.object(self.player,'recalculate_category') as post:
            with self.assertRaisesRegex(ValueError,'player_sync_preflight_changed'):self.player.bulk_main()
            session.assert_not_called();post.assert_not_called()
    def test_invalid_new_basis_is_blocked_before_session_or_post(self):
        request,audit,parent,policy,eraw,lraw=self.capsule()
        values={self.player.REQUEST:request,self.player.EXECUTION:audit,self.player.POLICY:self.config}
        with patch.object(self.player,'read',side_effect=lambda p:values[p]),patch.object(self.player,'current_automatic_basis',side_effect=ValueError('basis changed')),patch.object(self.player,'SessionManager') as session,patch.object(self.player,'recalculate_category') as post:
            with self.assertRaisesRegex(ValueError,'basis changed'):self.player.bulk_main()
            session.assert_not_called();post.assert_not_called()

    def host_basis(self):
        raws={}
        jid=self.parent_id;at=self.at.isoformat()
        raws['runs/'+jid+'.json']=encode({'run_id':jid,'status':'ready_for_quote','created_at':at,'costs':[{'platform':p,'status':'valid','run_id':jid,'checked_at':at} for p in self.worker.PLATFORMS],'competitors':[{'platform':p,'source':s,'status':'valid','run_id':jid,'captured_at':at} for p in self.worker.PLATFORMS for s in self.worker.SITES],'fx':{'status':'valid','checked_at':at},'storefront':{'collection_run_id':jid,'status':'ok','rows':{p:{'status':'ok','checked_at':at} for p in self.worker.PLATFORMS}}})
        raws['quotes/'+jid+'.json']=encode({'run_id':jid,'created_at':at,'snapshot_sha256':digest(raws['runs/'+jid+'.json'])})
        raws['previews/'+jid+'.json']=encode({'preview_id':jid,'run_id':jid,'status':'review_only','backend_before':{'rows':[{'platform':p,'b2c':'.1'} for p in self.worker.PLATFORMS]},'targets':[{'platform':p,'quote':'.1'} for p in self.worker.PLATFORMS]})
        raws['jobs/'+self.old+'.json']=encode({'job_id':self.old,'status':'superseded'})
        raws['all-coin-sync/'+self.cid+'.json']=encode({'status':'confirmed'})
        self.basis['source_sha256']={k:digest(v) for k,v in raws.items() if k.split('/')[0] in ['runs','quotes','previews']}
        self.basis['all_ledger_sha256']=digest(raws['all-coin-sync/'+self.cid+'.json'])
        pending={k:self.basis[k] for k in ['old_player_job_id','coin_execution_id','coin_execution_sha256','supersession_proof_sha256']}
        return raws,pending
    def test_host_parent_rechecks_source_and_existing_pricing_rule(self):
        raws,pending=self.host_basis()
        with patch.object(self.worker,'supersession_bytes',side_effect=raws.__getitem__),patch.object(self.worker,'superseded_basis',return_value=pending),patch.object(self.worker,'load_policy',return_value={'system_enabled':True,'mode':'auto','revision':28}),patch.object(self.worker,'check_write') as check:
            receipt=self.worker.validate_nochange_parent(self.parent,self.config)
            self.assertEqual(receipt['parent_id'],self.parent_id);check.assert_called_once()
    def test_host_source_off_revision_and_current_basis_negative_checks(self):
        for case in ['source','coin_changed','off','revision','age','pricing']:
            with self.subTest(case=case):
                raws,pending=self.host_basis();parent=copy.deepcopy(self.parent);policy={'system_enabled':True,'mode':'auto','revision':28}
                if case=='source':raws['runs/'+self.parent_id+'.json']+=b' '
                if case=='coin_changed':pending['coin_execution_id']=self.old
                if case=='off':policy['system_enabled']=False
                if case=='revision':policy['revision']=29
                if case=='age':parent['completed_at']=(self.at-timedelta(seconds=310)).isoformat()
                with patch.object(self.worker,'supersession_bytes',side_effect=raws.__getitem__),patch.object(self.worker,'superseded_basis',return_value=pending),patch.object(self.worker,'load_policy',return_value=policy),patch.object(self.worker,'check_write',side_effect=ValueError('existing price policy') if case=='pricing' else None):
                    with self.assertRaises(ValueError):self.worker.validate_nochange_parent(parent,self.config)
    def test_fresh_collection_rejects_missing_cost_competitor_fx_and_changed_preview(self):
        for case in ['cost','competitor','fx','stale','run_id','snapshot_hash','preview_rate']:
            with self.subTest(case=case):
                raws,pending=self.host_basis();snapshot=json.loads(raws['runs/'+self.parent_id+'.json']);quote=json.loads(raws['quotes/'+self.parent_id+'.json']);preview=json.loads(raws['previews/'+self.parent_id+'.json'])
                if case=='cost':snapshot['costs'].pop()
                if case=='competitor':snapshot['competitors'][0]['status']='invalid'
                if case=='fx':snapshot['fx']['status']='unavailable'
                if case=='stale':snapshot['created_at']=(self.at-timedelta(seconds=3601)).isoformat()
                if case=='run_id':snapshot['run_id']=self.old
                if case=='preview_rate':preview['targets'][0]['quote']='.9'
                raws['runs/'+self.parent_id+'.json']=encode(snapshot);quote['snapshot_sha256']=digest(raws['runs/'+self.parent_id+'.json'])
                if case=='snapshot_hash':quote['snapshot_sha256']='0'*64
                raws['quotes/'+self.parent_id+'.json']=encode(quote);raws['previews/'+self.parent_id+'.json']=encode(preview)
                with patch.object(self.worker,'check_write'):
                    with self.assertRaises(ValueError):self.worker.validate_nochange_sources(self.parent_id,self.parent_id,raws,{'revision':28})
    def gate_basis(self):
        marker={'superseding_coin_execution_id':self.cid,'player_revision':8,'readback_proof_sha256':'d'*64}
        rows={'jobs/'+self.old+'.json':{'job_id':self.old,'kind':'player_sync','status':'superseded','request':{'config_revision':8},'created_at':self.at.isoformat(),'supersession':marker},'player-sync/'+self.old+'.json':{'status':'superseded','supersession':marker}}
        raws={k:encode(v) for k,v in rows.items()};raws['executions/'+self.cid+'.json']=encode({'execution_id':self.cid})
        receipt={'status':'superseded','player_job_id':self.old,'marker':marker,'after_sha256':{k:digest(raws[k]) for k in rows},'basis_sha256':{'executions/'+self.cid+'.json':digest(raws['executions/'+self.cid+'.json'])}}
        return rows,raws,receipt
    def test_superseded_gate_requires_exact_private_receipt_and_both_published_hashes(self):
        rows,raws,receipt=self.gate_basis()
        with patch.object(self.tick,'supersession_bytes',side_effect=raws.__getitem__),patch.object(self.tick,'supersession_receipt',return_value=receipt),patch.object(self.tick,'latest_confirmed_coin',return_value={'execution_id':self.cid}):
            self.assertEqual(self.tick.superseded_basis(rows['jobs/'+self.old+'.json'])['coin_execution_id'],self.cid)
            for key in receipt['after_sha256']:
                original=raws[key];raws[key]+=b' '
                with self.assertRaisesRegex(ValueError,'supersession_partial_or_changed'):self.tick.superseded_basis(rows['jobs/'+self.old+'.json'])
                raws[key]=original
    def test_gate_current_coin_policy_and_receipt_corruption_stay_blocked(self):
        for case in ['current','revision','off','receipt']:
            rows,raws,receipt=self.gate_basis();config=copy.deepcopy(self.config)
            if case=='revision':config['revision']=9
            if case=='off':config['enabled']=False
            if case=='receipt':receipt['status']='prepared'
            with self.subTest(case=case),patch.object(self.tick,'load_player_sync_policy',return_value=config),patch.object(self.tick,'supersession_bytes',side_effect=raws.__getitem__),patch.object(self.tick,'supersession_receipt',return_value=receipt),patch.object(self.tick,'latest_confirmed_coin',return_value={'execution_id':self.old if case=='current' else self.cid}):
                with self.assertRaises(ValueError):self.tick.superseded_basis(rows['jobs/'+self.old+'.json'])
    def test_root_gate_receipt_unavailable_remains_blocked(self):
        rows,raws,receipt=self.gate_basis();(self.root/'jobs'/(self.old+'.json')).write_bytes(raws['jobs/'+self.old+'.json'])
        with patch.object(self.tick.os,'geteuid',return_value=0,create=True),patch.object(self.tick,'supersession_receipt',side_effect=PermissionError('isolated')),patch.object(self.tick,'supersession_bytes',side_effect=raws.__getitem__):
            self.assertEqual(self.tick.player_sync_gate(),'needs_reconcile')
    def test_unprivileged_api_requires_fresh_root_worker_approval_and_matching_targets(self):
        rows,raws,receipt=self.gate_basis();(self.root/'jobs'/(self.old+'.json')).write_bytes(raws['jobs/'+self.old+'.json'])
        pulse={'at':datetime.now(timezone.utc).isoformat(),'supersession_gate':{'player_job_id':self.old,'coin_execution_id':self.cid,'after_sha256':receipt['after_sha256']}}
        raws['state/worker-heartbeat.json']=encode(pulse)
        with patch.object(self.tick.os,'geteuid',return_value=994,create=True),patch.object(self.tick,'latest_confirmed_coin',return_value={'execution_id':self.cid}),patch.object(self.tick,'supersession_bytes',side_effect=raws.__getitem__):
            self.assertEqual(self.tick.player_sync_gate(),'ready')
            pulse['at']=(datetime.now(timezone.utc)-timedelta(seconds=16)).isoformat();raws['state/worker-heartbeat.json']=encode(pulse)
            self.assertEqual(self.tick.player_sync_gate(),'needs_reconcile')
            pulse['at']=datetime.now(timezone.utc).isoformat();raws['state/worker-heartbeat.json']=encode(pulse);raws['player-sync/'+self.old+'.json']+=b' '
            self.assertEqual(self.tick.player_sync_gate(),'needs_reconcile')
    def price_fixture(self):
        fixture=Fixture();fixture.setUp();backend={}
        for row in fixture.proof['coin_readbacks']:
            backend[(row['platform'],row['site_id'])]={'id':row['product_id'],'unit_price':row['actual_unit_price'],'more':{'gold':row['tier_gold'],'give':row['tier_give'],'discount':row['tier_discount'],'price':row['tier_price']}}
        public={}
        for row in fixture.proof['coins_public']:
            public[row['platform']]={'goods':{'index':{'list':[{'id':row['sku_id'],'unit':'K','goods_list':{str(i):tier for i,tier in enumerate(row['tiers'])}}]}}}
        return fixture,backend,public
    def check_prices(self,fixture,backend,public):
        coins=importlib.import_module('coin_all_sync_job');sf=importlib.import_module('storefront_monitor');mapping={'servers':{k:k for k in sf.PLATFORMS},'cid':'9623','site_id':'266'}
        def fetch(url,form=None,*args,**kwargs):return 'page' if form is None else json.dumps(public[sf.PLATFORMS[form['aid']]])
        with patch.object(coins,'read_row',side_effect=lambda manager,p,site:backend[(p,site)]) as reads,patch.object(sf,'page_mapping',return_value=mapping),patch.object(sf,'fetch',side_effect=fetch):
            self.player.validate_basis_prices(object(),fixture.audit,fixture.all_ledger)
            self.assertEqual(reads.call_count,6)
    def test_new_player_basis_reads_both_sites_and_all_public_quantities(self):self.check_prices(*self.price_fixture())
    def test_basis_backend_all_public_and_quantity_negative_checks(self):
        for case in ['all_unit','backend_unit','backend_gift','public_price','public_gift','public_scope']:
            with self.subTest(case=case):
                fixture,backend,public=self.price_fixture()
                if case=='all_unit':fixture.all_ledger['steps'][0]['payload']['unit_price']='.9'
                if case=='backend_unit':backend[('PS',0)]['unit_price']='.9'
                if case=='backend_gift':backend[('PS',0)]['more']['give']=list(backend[('PS',0)]['more']['give']);backend[('PS',0)]['more']['give'][0]=999
                if case=='public_price':public['PS']['goods']['index']['list'][0]['goods_list']['0']['price']='.9'
                if case=='public_gift':public['PS']['goods']['index']['list'][0]['goods_list']['0']['give']=999
                if case=='public_scope':public['PS']['goods']['index']['list'][0]['id']=1
                with self.assertRaises(ValueError):self.check_prices(fixture,backend,public)

class BindingIncrementTests(unittest.TestCase):
    def test_supersession_binding_requires_old_and_new_exact_cas_closure_and_shell(self):
        scope,schema=fixtures.LoaderTests().binding();old='00000000-0000-4000-8000-000000000009'
        scope['supersession']={'mode':'later_confirmed_coin','old_coin_execution_id':old}
        scope['shell_source']={'path':'/opt/fc27-cloud-browser/sync_players.sh','sha256':'d'*64,'metadata':{'uid':0,'gid':0,'mode':'0o750'}}
        for prefix in ['executions','jobs','all-coin-sync']:
            key=prefix+'/'+old+'.json';scope['expected_files'][key]='a'*64;scope['file_metadata'][key]={}
        launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
        missing=scope['expected_files'].pop('jobs/'+old+'.json')
        with self.assertRaisesRegex(ValueError,'cas_closure_incomplete'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
        scope['expected_files']['jobs/'+old+'.json']=missing;scope['shell_source']={}
        with self.assertRaisesRegex(ValueError,'shell_source_invalid'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')

@unittest.skipUnless(sys.platform=='linux' and hasattr(os,'geteuid') and os.geteuid()==0,'requires real Linux root')
class NativeSupersessionIncrementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):FollowupIncrementTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):FollowupIncrementTests.tearDownClass.__func__(cls)
    def test_descriptor_record_read_refuses_symlink_and_group_write(self):
        with tempfile.TemporaryDirectory(prefix='fc-supersession-fd-',dir='/run') as folder:
            root=Path(folder);jobs=root/'jobs';jobs.mkdir(mode=0o750);pid='00000000-0000-4000-8000-000000000001';path=jobs/(pid+'.json');path.write_bytes(b'{}');os.chown(path,0,11028);os.chmod(path,0o640)
            with patch.object(self.tick,'ROOT',root):
                self.assertEqual(self.tick.supersession_bytes('jobs/'+path.name),b'{}')
                os.chmod(path,0o660)
                with self.assertRaisesRegex(ValueError,'record_untrusted'):self.tick.supersession_bytes('jobs/'+path.name)
                os.chmod(path,0o640);target=jobs/'outside.json';path.rename(target);path.symlink_to(target)
                with self.assertRaises(OSError):self.tick.supersession_bytes('jobs/'+path.name)
    def test_private_receipt_and_container_basis_metadata_are_enforced(self):
        with tempfile.TemporaryDirectory(prefix='fc-supersession-receipt-',dir='/run') as folder:
            root=Path(folder);pid='00000000-0000-4000-8000-000000000001';rollback=root/'rollback';rollback.mkdir(mode=0o700);tx=rollback/('player-reconcile-v2-'+pid+'-supersession');tx.mkdir(mode=0o700);receipt=tx/'supersession-receipt.json';receipt.write_bytes(b'{}');os.chmod(receipt,0o600)
            with patch.object(self.tick,'ROOT',root):
                self.assertEqual(self.tick.supersession_receipt(pid),{})
                os.chmod(receipt,0o640)
                with self.assertRaisesRegex(ValueError,'receipt_untrusted'):self.tick.supersession_receipt(pid)
            parent=root/'parent.json';parent.write_bytes(b'{}');os.chown(parent,0,11028);os.chmod(parent,0o640)
            self.assertEqual(self.player.trusted_basis_bytes(parent),b'{}')
            other=root/'hardlink.json';os.link(parent,other)
            with self.assertRaisesRegex(ValueError,'file_untrusted'):self.player.trusted_basis_bytes(parent)

if __name__=='__main__':unittest.main(verbosity=2)
