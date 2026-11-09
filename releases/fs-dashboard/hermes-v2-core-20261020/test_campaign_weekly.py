from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import threading
import unittest
import uuid
import ast
from unittest.mock import patch

import test_campaign_recommendations as fixture
from pilot import TaskStore
from campaign_recommendations import CampaignRecommendations,checked_result
from campaign_weekly import CampaignWeekly,CampaignDelegation


def pool_input():
    catalog=[dict(key='fc-'+name+'-ps',title=name,product_ref=dict(site_id='266',game_id='1327',goods_id=str(100+i),model_id=str(200+i)),platform=dict(code='ps',attribute_id='21587'),available=False,binding_state='unknown') for i,name in enumerate(('core','a','b','c','d','e','f'))]
    keys=[p['key'] for p in catalog]
    return dict(source_revision='7',sbc_update=dict(id='weekly-source',observed_at='2026-11-15T04:00:00+00:00',expires_at=None,context='Fresh pools',sources=[]),catalog=catalog,
        pages=[dict(page_id='fc27-weekly',product_keys=keys[1:4]),dict(page_id='fc27-trio',product_keys=keys[1:]),dict(page_id='fc27-sbc',product_keys=keys[:5],core_product_keys=keys[:1])],rules=dict(version='fc27_weekly_selection_v1',scout_top_keys=keys[1:4]))


def selection(value):
    rows=[]
    for key in value['rules']['scout_top_keys']:rows.append(dict(page_id='fc27-weekly',product_key=key,core_product_key=None,reason='Popular order',evidence_indices=[]))
    for key in ('fc-d-ps','fc-e-ps','fc-f-ps'):rows.append(dict(page_id='fc27-trio',product_key=key,core_product_key=None,reason='Grounded trio',evidence_indices=[0]))
    for key in ('fc-a-ps','fc-b-ps'):rows.append(dict(page_id='fc27-sbc',product_key=key,core_product_key='fc-core-ps',reason='Companion',evidence_indices=[]))
    return dict(model='gpt-6.1-sol',source_revision=value['source_revision'],sbc_update_id=value['sbc_update']['id'],recommendations=rows)


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.pool=ThreadPoolExecutor(max_workers=2);self.addCleanup(self.pool.shutdown)
        self.at=[datetime(2026,11,15,3,59,tzinfo=timezone.utc)];self.current=True;self.calls=[];self.paid=0
        self.host=SimpleNamespace(tasks=TaskStore(Path(self.tmp.name)/'tasks.sqlite3'),root=Path(self.tmp.name),pool=self.pool,lock=threading.RLock(),authorizer=lambda owner:self.current and owner=='alice',clock=lambda:self.at[0])
        def model(scope,value):
            scope.mark_dispatch();self.paid+=1;result=selection(value)
            if not value['sbc_update']['sources']:
                for row in result['recommendations']:row['evidence_indices']=[]
            return result
        self.base=CampaignRecommendations(self.host,session_verify=lambda cookie,owner:cookie=='session-private' and owner=='alice',admission=fixture.guard,execute=model)
        self.saved={}
        def cli(body):
            self.calls.append(deepcopy(body));key=body['operation_id']
            if body['action']=='prepare':return dict(status='prepared',operation_id=key,plan_ref=key,rules_version='fc27_weekly_selection_v1',input=pool_input(),trio_players=[dict(name=name+'/90/CM/Test',model_id=str(204+i),key='fc-'+name+'-ps') for i,name in enumerate(('d','e','f'))],evidence_refs=[])
            if body['action']=='apply_draft':self.saved[key]=dict(status='draft_saved',operation_id=key,draft_revision=8);return self.saved[key]
            return self.saved.get(key,dict(status='not_found',operation_id=key))
        def evidence(players,at):return dict(status='partial',sources=[dict(url='https://www.futbin.com/fixture',title='Fixture',observed_at=at.isoformat())],context='Actual fixture source 0',coverage=dict(categories=['vertical'],failures=['social_unavailable']),documents=[dict(model_ids=['204','205','206'])])
        self.weekly=CampaignWeekly(self.host,self.base,cli=cli,evidence=evidence)
    def configure(self,enabled=True):return self.weekly.configure(dict(action='configure',operation_id=str(uuid.uuid4()),revision=self.weekly.config()['revision'],enabled=enabled),'alice','session-private')
    def finish(self):self.pool.shutdown(wait=True)
    def test_manual_and_scheduled_use_same_pipeline_only_save_draft_and_never_persist_cookie(self):
        self.assertFalse(self.weekly.config()['enabled']);key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish()
        result=self.weekly.lookup(key,'alice','session-private');self.assertEqual(result['status'],'completed');self.assertFalse(result['publication']);self.assertEqual(self.paid,1)
        self.assertEqual([c['action'] for c in self.calls],['prepare','prepare','apply_draft']);self.assertEqual(self.calls[-1]['owner'],'alice');self.assertTrue(self.calls[-1]['evidence_sources'])
        self.assertEqual(result['external_status'],'partial');self.assertNotIn('session-private',Path(self.host.tasks.path).read_bytes().decode('latin1'))
    def test_sunday_noon_uses_revocable_authenticated_owner_once_without_session(self):
        self.weekly.tick();self.assertEqual(self.calls,[]);grant=self.configure();self.weekly.tick();self.assertEqual(self.calls,[])
        self.at[0]+=timedelta(minutes=1);self.weekly.tick();self.finish();self.weekly.tick()
        self.assertEqual(self.paid,1);self.assertEqual(self.weekly.config()['owner'],'alice')
        with self.host.tasks.db() as db:row=db.execute('SELECT trigger,grant_revision FROM campaign_weekly_runs').fetchone()
        self.assertEqual(row['trigger'],'scheduled');self.assertEqual(row['grant_revision'],grant['revision'])
    def test_forged_delegation_and_changed_grant_cannot_authorize(self):
        self.configure();authority=CampaignDelegation(self.weekly,'alice',self.weekly.config()['revision']);self.assertTrue(authority.authorized(self.host,'alice'))
        self.configure(False);self.assertFalse(authority.authorized(self.host,'alice'))
        with self.assertRaises(PermissionError):self.base.authorized('alice',authority)
        with self.assertRaises(PermissionError):self.base.authorized('alice',SimpleNamespace(campaign_delegation=True))
        with self.assertRaises(PermissionError):self.weekly.configure(dict(action='configure',operation_id=str(uuid.uuid4()),revision=0,enabled=True),'bob','session-private')
    def test_revoke_after_research_prevents_model_and_draft_with_visible_coverage(self):
        self.configure();authority=CampaignDelegation(self.weekly,'alice',self.weekly.config()['revision']);original=self.weekly.evidence
        def research(players,at):result=original(players,at);self.configure(False);return result
        self.weekly.evidence=research;key=str(uuid.uuid4());self.weekly.run(key,'alice',authority,trigger='scheduled',due_day='2026-11-15');self.finish()
        result=self.weekly.lookup(key,'alice','session-private');self.assertEqual(self.paid,0);self.assertEqual(len(self.calls),1);self.assertEqual(result['evidence_coverage']['categories'],['vertical'])
    def test_page_pool_and_scout_order_trio_count_and_sbc_slots_are_enforced(self):
        value=pool_input();value['sbc_update']['sources']=[dict(url='https://www.futbin.com/fixture',title='Fixture',observed_at='2026-11-15T04:00:00+00:00')]
        good=selection(value);self.assertEqual(checked_result(good,value),good)
        for change in (lambda r:r['recommendations'].reverse(),lambda r:r['recommendations'].pop(),lambda r:r['recommendations'].__setitem__(3,dict(r['recommendations'][3],product_key='fc-core-ps'))):
            bad=deepcopy(good);change(bad)
            with self.assertRaises(ValueError):checked_result(bad,value)
    def test_apply_timeout_is_reconciled_by_original_receipt_without_new_model(self):
        original=self.weekly.cli
        def cli(body):
            result=original(body)
            if body['action']=='apply_draft':raise RuntimeError('campaign_cli_outcome_unknown')
            return result
        self.weekly.cli=cli;key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish()
        self.assertEqual(self.weekly.lookup(key,'alice','session-private')['status'],'unknown')
        result=self.weekly.reconcile(key,'alice','session-private');self.assertEqual(result['status'],'completed');self.assertEqual(self.paid,1);self.assertEqual(self.calls[-1]['action'],'inspect_operation')
    def test_configure_original_id_has_readable_receipt_without_reenabling_schedule(self):
        configured=self.configure();self.assertEqual(self.weekly.config()['operation_id'],configured['operation_id'])
        self.configure(False);proof=self.weekly.reconcile(configured['operation_id'],'alice','session-private')
        self.assertEqual(proof['status'],'configured');self.assertEqual(proof['operation_id'],configured['operation_id']);self.assertFalse(self.weekly.config()['enabled'])
    def test_absent_external_evidence_produces_explicit_metadata_only_provisional_draft(self):
        self.weekly.evidence=lambda *args:dict(status='unavailable',sources=[],context='No public evidence available; metadata only.',coverage={'categories':[],'failures':['unavailable']},documents=[])
        key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish();result=self.weekly.lookup(key,'alice','session-private')
        self.assertEqual(result['status'],'completed');self.assertEqual(result['external_status'],'unavailable');self.assertTrue(result['provisional']);self.assertTrue(result['review_required']);self.assertEqual(self.paid,1)
        self.assertEqual(self.calls[-1]['evidence_sources'],[])
    def test_auxiliary_switch_off_after_research_prevents_new_model_even_when_schedule_enabled(self):
        self.configure();original=self.weekly.cli;prepared_count=[0]
        def cli(body):
            if body['action']=='prepare':
                prepared_count[0]+=1
                if prepared_count[0]>1:return dict(status='disabled',operation_id=body['operation_id'],reason='hermes_disabled')
            return original(body)
        self.weekly.cli=cli;key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish();result=self.weekly.lookup(key,'alice','session-private')
        self.assertEqual(result['status'],'disabled');self.assertEqual(self.paid,0);self.assertTrue(self.weekly.config()['enabled']);self.assertNotIn('apply_draft',[r['action'] for r in self.calls])
    def test_current_host_tick_preserves_original_jobs_when_campaign_tick_fails(self):
        source=fixture.ROOT/'releases/fs-dashboard/knowledge-layering-20261023/source/controller.py';tree=ast.parse(source.read_text('utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HermesService');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_recover_loop')
        events=[];iterations=iter((False,True))
        def bad():events.append('campaign');raise ValueError('fixture failure')
        host=SimpleNamespace(recovery_stop=SimpleNamespace(wait=lambda _:next(iterations)),root=Path(self.tmp.name),clock=lambda:self.at[0],recover_reports=lambda:events.append('reports'),source_preparation=SimpleNamespace(tick=lambda _:events.append('sources')),nightly=SimpleNamespace(tick=lambda:events.append('nightly')),campaign_weekly=SimpleNamespace(tick=bad),detail=None)
        env=dict(atomic=lambda *args,**kwargs:events.append('diagnostic'))
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),env)
        with patch.dict(sys.modules,{'cohort_reader':SimpleNamespace(reader_for=lambda _:SimpleNamespace(tick=lambda:events.append('cohort')))}):env['_recover_loop'](host)
        self.assertEqual(events,['reports','sources','nightly','campaign','diagnostic','cohort'])
    def test_manual_resume_reuses_the_completed_model_and_original_apply_id(self):
        original=self.weekly.cli;fail=[True]
        def cli(body):
            if body['action']=='apply_draft' and fail[0]:self.calls.append(deepcopy(body));raise RuntimeError('campaign_cli_outcome_unknown')
            return original(body)
        self.weekly.cli=cli;key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish()
        self.assertEqual(self.weekly.reconcile(key,'alice','session-private')['status'],'unknown');self.assertEqual(self.paid,1)
        self.pool=ThreadPoolExecutor(max_workers=2);self.addCleanup(self.pool.shutdown);self.host.pool=self.pool;fail[0]=False
        self.weekly.resume(key,'alice','session-private');self.finish();result=self.weekly.lookup(key,'alice','session-private')
        self.assertEqual(result['status'],'completed');self.assertEqual(self.paid,1)
        self.assertTrue(all(c['operation_id']==key for c in self.calls));self.assertEqual([c['action'] for c in self.calls].count('apply_draft'),2)
    def test_original_model_known_terminal_is_persisted_when_reconciling_interrupted_stage(self):
        key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish()
        for state in ('unavailable','failed'):
            self.weekly._update(key,state='unknown',stage='model',result=dict(status='unknown',operation_id=key))
            model=dict(status=state,operation_id=key,error='WEEKLY_HERMES_RECOMMENDATION_FAILED' if state=='failed' else 'WEEKLY_HERMES_PROVIDER_UNAVAILABLE',provider_outcome='completed' if state=='failed' else 'not_dispatched',receipt={'operation_id':key,'model':'gpt-6.1-sol'})
            with patch.object(self.base,'lookup',return_value=model):result=self.weekly.reconcile(key,'alice','session-private')
            self.assertEqual(result['status'],state);self.assertEqual(result['receipt'],model['receipt']);self.assertEqual(result['evidence_coverage']['categories'],['vertical'])
            self.assertEqual(self.weekly._record(key,'alice')['state'],state);self.assertEqual(self.paid,1)
    def test_resumed_apply_known_precondition_failure_preserves_safe_reason_and_model_receipt(self):
        key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish()
        for code in ('REVISION_CONFLICT','WEEKLY_SELECTION_RULE_MISMATCH','INVALID_WEEKLY_HERMES_INPUT','WEEKLY_OPERATION_OWNER_MISMATCH','REQUEST_CONFLICT'):
            self.weekly._update(key,state='pending',stage='apply_draft',result=None)
            with patch.object(self.weekly,'cli',side_effect=ValueError(code)):self.weekly._apply_existing(key,'alice','session-private')
            result=self.weekly.lookup(key,'alice','session-private')
            self.assertEqual(result['status'],'unknown' if code=='REQUEST_CONFLICT' else 'failed');self.assertEqual(result['error'],code)
            self.assertEqual(result['receipt']['operation_id'],key);self.assertEqual(result['evidence_coverage']['categories'],['vertical']);self.assertEqual(self.paid,1)
    def test_admission_busy_without_a_model_record_is_known_not_dispatched(self):
        key=str(uuid.uuid4());busy=dict(status='unavailable',operation_id=key,error='WEEKLY_HERMES_PROVIDER_UNAVAILABLE',provider_outcome='not_dispatched')
        with patch.object(self.base,'submit',return_value=busy):self.weekly.run(key,'alice','session-private');self.finish()
        result=self.weekly.lookup(key,'alice','session-private');self.assertEqual(result['status'],'unavailable');self.assertEqual(result['provider_outcome'],'not_dispatched');self.assertEqual(self.paid,0)
        self.assertIsNone(self.base._record(key,'alice'));self.assertEqual(result['evidence_coverage']['categories'],['vertical'])
    def test_stale_reconcile_cannot_regress_a_concurrently_completed_draft(self):
        key=str(uuid.uuid4());self.weekly.run(key,'alice','session-private');self.finish();completed=self.weekly.lookup(key,'alice','session-private')
        model=self.base.lookup(key,'alice','session-private');self.weekly._update(key,state='unknown',stage='model',result=dict(status='unknown',operation_id=key))
        def lookup(*args):self.weekly._update(key,state='completed',stage='apply_draft',result=completed);return model
        with patch.object(self.base,'lookup',side_effect=lookup):result=self.weekly.reconcile(key,'alice','session-private')
        self.assertEqual(result['status'],'completed');self.assertEqual(self.weekly._record(key,'alice')['state'],'completed');self.assertEqual(self.paid,1)

if __name__=='__main__':unittest.main()
