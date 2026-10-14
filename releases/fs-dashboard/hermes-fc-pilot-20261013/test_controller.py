from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from controller import HermesService
from pilot import digest,encoded
from proxy_gateway import ModelGateway,ScopedTools,UnifiedBudget
from research import ResearchBook
from skill_bundle import load_bundle
from test_research import dataset
from report_validation import validate_output
from runs_contract import WIRE_TOOLS


class InlinePool:
    def submit(self,fn,*args):fn(*args)


class Daily:
    def __init__(self,root):
        self.root=root;self.path=root/'daily.db'
        with self.db() as db:db.execute('CREATE TABLE model_calls(fingerprint TEXT PRIMARY KEY,day TEXT,state TEXT,content TEXT)')
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run_root=self.root/'run';(self.run_root/'admissions').mkdir(parents=True)
        self.daily=Daily(self.root);self.at=datetime(2026,10,13,15,tzinfo=timezone.utc)
        self.service=HermesService(None,self.daily,None,None,self.root/'state',self.run_root,Path(__file__).parent,lambda u:u=='owner',clock=lambda:self.at)
        self.service.pool.shutdown();self.service.pool=InlinePool()
        self.body={'kind':'hermes_report','request_id':'request_fixture','start':'2026-10-05','end':'2026-10-11','question':'调查销售与积压的经营变化并给出行动。','mode':'investigation'}
        self.headers={'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'}
        self.book=ResearchBook(dataset(),{}, {'start':'2026-10-05','end':'2026-10-11'},skills=load_bundle(Path(__file__).parent))

    def build_gateway(self,daily,tasks,book):
        budget=UnifiedBudget(daily.db,{'id':'fixture','model':'deepseek-v4.1-flash','price_version':'fake','input_microcny':2,'output_microcny':8},lambda:self.at)
        @contextmanager
        def slot():yield True
        def provider(request):
            self.assertTrue(request['enable_thinking']);self.assertEqual(request['reasoning_effort'],'max')
            return {'id':'receipt_fixture','usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30},'choices':[{'message':{'role':'assistant','content':'fixture'}}]}
        return ModelGateway(ScopedTools(tasks,book,lambda:self.at),budget,slot,provider,lambda _:100000,lambda:0)

    def remote(self,method,path,body=None,idempotency=None):
        admission_path=next((self.run_root/'admissions').glob('fc_*.json'))
        admission=json.loads(admission_path.read_text('utf-8'))
        grant=self.service.grants.resolve(admission['token'])
        task=self.service.tasks.get(grant.task_id,grant.owner)
        if method=='POST':
            self.assertFalse(admission['ready']);self.assertEqual(task['state'],'DISPATCH_UNKNOWN')
            return 202,{'run_id':'run_'+'a'*32,'status':'queued'}
        self.assertTrue(admission['ready']);self.assertEqual(task['state'],'RUNNING')
        ref=self.service.proxy.dispatch('POST','/fc/tools/call',admission['token'],{'name':WIRE_TOOLS[6],
             'arguments':{'start':'2026-10-05','end':'2026-10-11','group_by':['platform'],'filters':{},'page':1}})['data']['evidence_id']
        self.service.proxy.dispatch('POST','/v1/chat/completions',admission['token'],{'model':'deepseek-v4.1-flash','reasoning_effort':'max','max_tokens':50,'messages':[{'role':'user','content':'fixture'}]})
        return 200,{'status':'completed','output':encoded({'summary':'合成调查完成，仍需业务验收。',
               'findings':[{'statement':'主站已读两单，其中一单金额缺失。','claim_type':'fact','evidence_ids':[ref],'alternative':'','missing':'交付进度未提供'}],
               'actions':[{'target':'PS问题单','action':'复核最新障碍','condition':'仍为问题状态','cost_risk':'人工时间，旧备注可能失效','review_at':'次日','success_check':'状态与障碍复核','evidence_ids':[ref]}],
               'reviews':[],'limitations':['合成输入不能作经营事实。'],'number_claims':[]})}

    def test_end_to_end_handshake_model_receipt_and_owner_idempotency(self):
        with patch('controller.build_book',return_value=self.book),patch('controller.gateway',side_effect=self.build_gateway),patch.object(self.service,'remote',side_effect=self.remote),patch.dict('sys.modules',{'ai_advisor_model':type('Module',(),{'clean_question':staticmethod(lambda q:q)})()}):
            code,job=self.service.post(self.body,'owner',self.headers)
            self.assertEqual(code,202);self.assertEqual(job['state'],'COMPLETED',job)
            self.assertTrue(job['result']['model_generated']);self.assertEqual(job['result']['business_acceptance'],'user_review_required')
            self.assertEqual(job['model_usage']['calls'],1)
            self.assertEqual(job['result']['reasoning_effort'],'max')
            self.assertEqual(self.service.post(self.body,'owner',self.headers)[0],200)
            _,retry=self.service.post(dict(self.body,request_id='different_transport_request'),'owner',self.headers)
            self.assertEqual(retry['id'],job['id']);self.assertEqual(retry['run_id'],job['run_id']);self.assertEqual(retry['model_usage']['calls'],1)
            self.assertEqual(self.service.get_job('other',job['id']),None)
            self.assertEqual(list((self.run_root/'admissions').glob('*.json')),[])

    def test_large_final_report_survives_validation_storage_and_readback(self):
        def remote(*args,**kwargs):
            code,payload=self.remote(*args,**kwargs)
            if payload.get('output'):
                result=json.loads(payload['output']);result['summary']='Synthetic completed report. '*8000
                payload['output']=encoded(result)
            return code,payload
        with patch('controller.build_book',return_value=self.book),patch('controller.gateway',side_effect=self.build_gateway),patch.object(self.service,'remote',side_effect=remote):
            _,job=self.service.post(self.body,'owner',self.headers)
            self.assertEqual(job['state'],'COMPLETED',job)
            self.assertGreater(len(encoded(job['result']).encode()),128000)
            self.assertEqual(self.service.get_job('owner',job['id'])['result'],job['result'])

    def test_direct_provider_identity_never_aliases_same_input_old_bailian_failure(self):
        self.assert_separate_failed_policy('existing-ledger-public-estimate')

    def test_stream_transport_identity_never_aliases_nonstream_failed_task(self):
        self.assert_separate_failed_policy('no-pilot-quotas-deepseek-direct-tokens-only-v1')

    def assert_separate_failed_policy(self, old_policy):
        from direct_provider import POLICY_ID
        old_spec={'period':{'start':self.body['start'],'end_exclusive':'2026-10-12','timezone':'Asia/Shanghai'},
                  'snapshot_id':self.book.capture_id,'template_version':'v3-1m-'+digest({k:v for k,v in self.body.items() if k!='request_id'})[:20],
                  'knowledge_version':self.book.skills['version'],'budget_policy_id':old_policy}
        old=self.service.tasks.create('owner',old_spec)
        self.service.tasks.reserve_dispatch(old['id'],'owner','old_lease')
        self.service.tasks.bind_run(old['id'],'owner','old_lease','run_'+'b'*32)
        self.service.tasks.observe(old['id'],'owner','old_lease','failed',worker_stopped=True)
        with patch('controller.build_book',return_value=self.book),patch('controller.gateway',side_effect=self.build_gateway),patch.object(self.service,'remote',side_effect=self.remote) as remote:
            _,job=self.service.post(self.body,'owner',self.headers)
        self.assertEqual(job['state'],'COMPLETED',job)
        self.assertNotEqual(job['task_id'],old['id'])
        self.assertEqual(self.service.tasks.get(old['id'],'owner')['state'],'FAILED')
        self.assertEqual(self.service.tasks.get(job['task_id'],'owner')['spec']['budget_policy_id'],POLICY_ID)
        self.assertEqual(self.service.gateways,{},'finished task token/provider state not leaked')
        self.assertEqual(sum(args.args[0]=='POST' and args.args[1]=='/v1/runs' for args in remote.call_args_list),1)

    def test_anonymous_foreign_role_and_cross_origin_cannot_submit(self):
        self.assertEqual(self.service.post(self.body,None,self.headers)[0],401)
        self.assertEqual(self.service.post(self.body,'other',self.headers)[0],403)
        self.assertEqual(self.service.post(self.body,'owner',dict(self.headers,**{'Sec-Fetch-Site':'cross-site'}))[0],403)

    def test_release_exclusive_lock_refuses_admission_without_creating_task(self):
        import os
        path=self.service.root/'admission.lock'
        fd=os.open(str(path),os.O_RDWR|os.O_CREAT,0o600)
        try:
            if os.name=='posix':
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            else:
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            self.assertEqual(self.service.post(self.body,'owner',self.headers),(503,{'error':'release_in_progress'}))
            with self.service.tasks.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],0)
        finally:os.close(fd)

    def test_cancel_while_sources_load_never_admits_runtime(self):
        key=digest({'owner':'owner','request_id':self.body['request_id']})[:32]
        def load(*args):
            self.service.post({'kind':'hermes_cancel','id':key},'owner',self.headers)
            return self.book
        with patch('controller.build_book',side_effect=load),patch.object(self.service,'remote') as remote,patch.dict('sys.modules',{'ai_advisor_model':type('Module',(),{'clean_question':staticmethod(lambda q:q)})()}):
            _,job=self.service.post(self.body,'owner',self.headers)
            self.assertEqual(job['state'],'CANCELLED');self.assertIsNone(job['task_id']);remote.assert_not_called()

    def test_cancel_during_admission_keeps_run_mapping_and_revokes_spending(self):
        key=digest({'owner':'owner','request_id':self.body['request_id']})[:32];calls=[]
        def remote(method,path,body=None,idempotency=None):
            calls.append((method,path))
            if path=='/v1/runs':
                self.service.post({'kind':'hermes_cancel','id':key},'owner',self.headers)
                return 202,{'run_id':'run_'+'a'*32,'status':'queued'}
            if path.endswith('/stop'):return 200,{'status':'stopping'}
            admission=json.loads(next((self.run_root/'admissions').glob('*.json')).read_text('utf-8'))
            with self.assertRaises(PermissionError):self.service.grants.resolve(admission['token'])
            return 200,{'status':'cancelled'}
        with patch('controller.build_book',return_value=self.book),patch('controller.gateway',side_effect=self.build_gateway),patch.object(self.service,'remote',side_effect=remote),patch.dict('sys.modules',{'ai_advisor_model':type('Module',(),{'clean_question':staticmethod(lambda q:q)})()}):
            _,job=self.service.post(self.body,'owner',self.headers)
            self.assertEqual(job['state'],'CANCELLED',job);self.assertEqual(job['task_state'],'CANCELLED')
            self.assertEqual(job['run_id'],'run_'+'a'*32);self.assertEqual(job['model_usage']['calls'],0)
            self.assertEqual(calls.count(('POST','/v1/runs')),1)

    def test_restart_preserves_unknown_without_spending(self):
        key=digest({'owner':'owner','request_id':'fixture'})[:32]
        with self.service.tasks.db() as db:db.execute("INSERT INTO requests VALUES(?,?,?,?,'RUNNING',NULL,NULL,NULL)",(key,'owner','fixture',encoded(self.body)))
        again=HermesService(None,self.daily,None,None,self.root/'state',self.run_root,Path(__file__).parent,lambda _:True,clock=lambda:self.at)
        self.addCleanup(again.pool.shutdown)
        self.assertEqual(again.get_job('owner',key)['state'],'NEEDS_RECONCILE')
        self.assertIsNone(again.server)

    def test_report_reference_integrity_has_no_three_item_or_number_ban(self):
        ref=self.book.query({'start':'2026-10-05','end':'2026-10-11','group_by':[],'filters':{},'page':1})['evidence_id']
        row={'statement':'已读2单，已知金额$10.00，1单金额缺失。','claim_type':'fact','evidence_ids':[ref],'alternative':'','missing':'交付数据缺失'}
        claims=[]
        for i in range(4):
            for token,path in [('2','/data/total/orders'),('10.00','/data/total/known_revenue_usd'),('1','/data/total/unpriced_orders')]:
                claims.append({'report_field':f'/findings/{i}/statement','text':token,'evidence_id':ref,'path':path,'scale':'as_stored'})
        result={'summary':'合成数据数值验证。','findings':[dict(row) for _ in range(4)],'actions':[],'reviews':[],'limitations':[],'number_claims':claims}
        self.assertEqual(len(validate_output(encoded(result),self.book)['findings']),4)
        result['findings'][0]['evidence_ids']=['fabricated']
        with self.assertRaisesRegex(ValueError,'fabricated_evidence'):validate_output(encoded(result),self.book)

    def test_incorrect_or_unbound_numbers_with_valid_reference_are_rejected(self):
        ref=self.book.query({'start':'2026-10-05','end':'2026-10-11','group_by':[],'filters':{},'page':1})['evidence_id']
        finding={'statement':'已知金额$999.00。','claim_type':'fact','evidence_ids':[ref],'alternative':'','missing':''}
        claim={'report_field':'/findings/0/statement','text':'999.00','evidence_id':ref,'path':'/data/total/known_revenue_usd','scale':'as_stored'}
        value={'summary':'核实金额。','findings':[finding],'actions':[],'reviews':[],'limitations':[],'number_claims':[claim]}
        with self.assertRaisesRegex(ValueError,'number_claim_mismatch'):validate_output(encoded(value),self.book)
        value['number_claims']=[]
        with self.assertRaisesRegex(ValueError,'unbound_report_number'):validate_output(encoded(value),self.book)
        finding['statement']='已知金额$10.00。';claim['text']='10.00';value['number_claims']=[claim]
        self.assertTrue(validate_output(encoded(value),self.book)['analysis_completed'])
        scenario=self.book.call('fc.calculate',{'operation':'sum','values':['999.00'],'evidence_ids':[ref],
              'value_paths':[None],'assumptions':['假设销售目标']})['evidence_id']
        finding.update(statement='假设金额$999.00。',evidence_ids=[scenario])
        claim.update(text='999.00',evidence_id=scenario,path='/data/result/sum')
        with self.assertRaisesRegex(ValueError,'scenario_presented_as_fact'):validate_output(encoded(value),self.book)
        finding.update(claim_type='hypothesis',alternative='只是情景输入，并非真实销售')
        self.assertTrue(validate_output(encoded(value),self.book)['analysis_completed'])

    def test_hermes_question_sk_policy_is_independent_of_legacy_advisor(self):
        from controller import clean_hermes_question
        for value in ('Use task-scoped evidence.','Use risk-based review.','sk-SYNTHETIC'):
            self.assertEqual(clean_hermes_question(value),value)
        for value in ('Bearer fixture','Cookie: fixture','password=fixture','密码：fixture','user@example.com','https://example.com','123456789012'):
            with self.assertRaises(ValueError):clean_hermes_question(value)
        body=dict(self.body,question='Use task-scoped evidence.')
        with patch('controller.build_book',return_value=self.book),patch('controller.gateway',side_effect=self.build_gateway),patch.object(self.service,'remote',side_effect=self.remote):
            code,job=self.service.post(body,'owner',self.headers)
        self.assertEqual(code,202);self.assertEqual(job['state'],'COMPLETED',job)

    def test_report_sk_text_allowed_and_other_private_markers_rejected(self):
        ref=self.book.query({'start':'2026-10-05','end':'2026-10-11','group_by':[],'filters':{},'page':1})['evidence_id']
        value={'summary':'Use "task-scoped" evidence.',
               'findings':[{'statement':'A task-scoped sample is partial.','claim_type':'fact','evidence_ids':[ref],'alternative':'','missing':''}],
               'actions':[],'reviews':[],'limitations':[],'number_claims':[]}
        for marker in ('sk-SYNTHETIC','task-scoped','risk-based','Use "task-scoped." evidence.'):
            value['summary']=marker;self.assertTrue(validate_output(encoded(value),self.book)['analysis_completed'])
        for marker in ('Bearer fixture','Cookie: fixture','password=fixture','密码：fixture','user@example.com'):
            value['summary']=marker
            with self.assertRaisesRegex(ValueError,'sensitive_analysis'):validate_output(encoded(value),self.book)


if __name__=='__main__':unittest.main()
