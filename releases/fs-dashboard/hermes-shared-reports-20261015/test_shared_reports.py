"""Real controller, SQLite and report files; no network or paid model calls."""
import importlib.util,json,shutil,sys,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
repo=next((p for p in HERE.parents if (p/'releases/fs-dashboard/hermes-report-quality-20261015/test_support.py').exists()),None)
quality=(repo/'releases/fs-dashboard/hermes-report-quality-20261015') if repo else HERE.parent/'hermes-report-quality-repair-20261015/followup'
spec=importlib.util.spec_from_file_location('shared_quality_support',quality/'test_support.py');support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
ROOT=support.SOURCE_ROOT
for source in (HERE/'candidate').glob('*.py'):shutil.copyfile(source,ROOT/source.name)
sys.path.insert(0,str(ROOT))
from controller import HermesService
from pilot import encoded,digest
from continuation import load_report_followup
from skill_bundle import load_bundle
from research import ResearchBook
from report_artifacts import save_raw,save_result,read_file
import test_controller as controller_fixtures
Daily=controller_fixtures.Daily
from test_research import dataset

class Queue:
    def __init__(self):self.calls=[]
    def submit(self,*args):self.calls.append(args)

class SharedReports(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.run=self.root/'run';(self.run/'admissions').mkdir(parents=True)
        self.daily=Daily(self.root);self.at=datetime(2026,10,15,7,tzinfo=timezone.utc)
        self.service=HermesService(None,self.daily,None,None,self.root/'state',self.run,ROOT,lambda u:u in {'wulv','DY'},clock=lambda:self.at)
        self.service.pool.shutdown();self.service.pool=Queue();self.headers={'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'}
        self.n=0;self.version=load_bundle(ROOT)['version']
        self.book=ResearchBook(dataset(),{}, {'start':'2026-10-05','end':'2026-10-11'},skills=load_bundle(ROOT))
        self.book.call('fc.get_data_catalog',{})
        self.hold=patch('controller.spending_hold',return_value=None);self.hold.start();self.addCleanup(self.hold.stop)

    def body(self,**changes):
        self.n+=1
        return dict({'kind':'hermes_report','request_id':'fixture_'+str(self.n),'start':'2026-10-05','end':'2026-10-11','question':'请分析本周FC经营并保留证据。','mode':'investigation'},**changes)

    def seed(self,owner='wulv',state='COMPLETED',**changes):
        body=self.body(**changes);key=digest({'owner':owner,'request_id':body['request_id']})[:32]
        task=self.service.tasks.create(owner,{'period':{'start':body['start'],'end_exclusive':'2026-10-12','timezone':'Asia/Shanghai'},'snapshot_id':self.book.capture_id,'template_version':body['request_id'],'knowledge_version':self.version,'budget_policy_id':'fixture'})
        result={'summary':'合成原版报告，不是经营事实。','research_text':'## 关键判断\n合成原版报告。','model_generated':True,'limitations':[],'snapshot_id':self.book.capture_id,'period':{'start':body['start'],'end':body['end']}}
        with self.service.tasks.db() as db:
            db.execute('UPDATE tasks SET state=? WHERE id=?',('PARTIAL' if state=='COMPLETED' else state,task['id']))
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?)',(key,owner,body['request_id'],encoded(body),state,task['id'],None,encoded(result) if state=='COMPLETED' else None))
            for ev in self.book.evidence.values():db.execute('INSERT INTO evidence VALUES(?,?,?)',(task['id'],ev['evidence_id'],encoded(ev)))
        if state=='COMPLETED':
            save_raw(self.service.root,task['id'],'synthetic public report',self.book.evidence,{'owner':owner,'skills_version':self.version,'skill_sha256':load_bundle(ROOT)['sha256']})
            save_result(self.service.root,task['id'],result,'<html>合成原版报告</html>')
        return key,task['id'],body

    def get(self,user='wulv',**params):return self.service.get({k:[v] for k,v in dict(mode='hermes',**params).items()},user)

    def snapshot(self):
        with self.service.tasks.db() as db:return {table:[tuple(r) for r in db.execute('SELECT * FROM '+table)] for table in ('requests','tasks','evidence')}

    def test_shared_read_artifacts_and_nonmember_denial(self):
        key,task,_=self.seed('DY');own,_,_=self.seed('viewer')
        self.assertEqual(self.get(id=key)[1]['owner'],'DY')
        self.assertIn('合成原版',self.get(id=key,artifact='html')[1]['content'])
        self.assertEqual(self.get(id=key,artifact='boss')[0],200)
        self.assertEqual(self.get('viewer',id=key)[0],404)
        self.assertEqual(self.get('viewer',id=key,artifact='json')[0],404)
        self.assertEqual([r['id'] for r in self.get('viewer')[1]['items']],[own])
        self.assertEqual(self.service.get({'mode':['hermes']},None)[0],401)

    def test_trash_restore_keeps_requests_evidence_files_and_usage(self):
        key,task,_=self.seed('DY');before=self.snapshot();report=read_file(self.service.root,task,'json')
        self.assertEqual(self.service.post({'kind':'hermes_delete','id':key},'viewer',self.headers)[0],404)
        self.assertEqual(self.service.post({'kind':'hermes_delete','id':key},'DY',self.headers)[0],200)
        self.assertEqual(self.get(id=key)[0],404);self.assertEqual(self.get(id=key,artifact='raw')[0],404)
        self.assertEqual(self.get(scope='trash')[1]['items'][0]['id'],key)
        self.assertEqual(self.snapshot(),before);self.assertEqual(read_file(self.service.root,task,'json'),report)
        self.assertEqual(self.service.post({'kind':'hermes_restore','id':key},'wulv',self.headers)[0],200)
        self.assertEqual(self.get(id=key)[0],200);self.assertEqual(self.snapshot(),before)
        self.assertFalse(self.service.pool.calls)

    def test_author_can_delete_own_after_generate_permission_removed(self):
        key,_,_=self.seed('viewer')
        self.assertEqual(self.service.post({'kind':'hermes_delete','id':key},'viewer',self.headers)[0],200)
        self.assertEqual(self.service.post({'kind':'hermes_restore','id':key},'viewer',self.headers)[0],200)

    def test_active_unknown_and_pending_reports_cannot_be_hidden(self):
        for state in ('RUNNING','NEEDS_RECONCILE','DISPATCH_UNKNOWN','REPORT_PENDING','PREPARING'):
            with self.subTest(state=state):
                key,_,_=self.seed(state=state)
                self.assertEqual(self.service.post({'kind':'hermes_delete','id':key},'wulv',self.headers)[0],409)

    def test_same_origin_required_and_no_owner_override(self):
        key,_,_=self.seed()
        self.assertEqual(self.service.post({'kind':'hermes_delete','id':key},'wulv',{})[0],403)
        self.assertEqual(self.service.post({'kind':'hermes_delete','id':key,'owner':'DY'},'wulv',self.headers)[0],422)
        self.assertEqual(self.service.post(self.body(owner='DY'),'wulv',self.headers)[0],422)

    def test_duplicate_cross_owner_reuses_without_queue_or_new_ledger(self):
        key,_,body=self.seed('DY');before=self.snapshot()
        code,job=self.service.post(dict(body,request_id='another_request'),'wulv',self.headers)
        self.assertEqual(code,200);self.assertTrue(job['reused']);self.assertEqual(job['id'],key);self.assertEqual(job['owner'],'DY')
        self.assertEqual(before,self.snapshot());self.assertFalse(self.service.pool.calls)

    def test_explicit_refresh_does_not_reuse_and_retries_are_idempotent(self):
        self.seed('DY');body=self.body(force_generate=True)
        first=self.service.post(body,'wulv',self.headers);second=self.service.post(body,'wulv',self.headers)
        self.assertEqual(first[0],202);self.assertEqual(second[0],200);self.assertEqual(first[1]['id'],second[1]['id']);self.assertEqual(len(self.service.pool.calls),1)

    def test_concurrent_same_requirement_creates_one_preparing_request(self):
        bodies=[self.body(),self.body()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers=list(pool.map(lambda b:self.service._submit_report(b,'wulv',True),bodies))
        self.assertEqual(sorted(a[0] for a in answers),[200,202]);self.assertEqual(answers[0][1]['id'],answers[1][1]['id'])

    def test_failed_deleted_and_old_skill_reports_are_not_reused(self):
        failed,_,_=self.seed('DY',state='FAILED');deleted,_,_=self.seed('DY');old,task,_=self.seed('DY')
        self.service.trash_report('DY',deleted)
        with self.service.tasks.db() as db:
            spec=json.loads(db.execute('SELECT spec FROM tasks WHERE id=?',(task,)).fetchone()[0]);spec['knowledge_version']='old'
            db.execute('UPDATE tasks SET spec=? WHERE id=?',(encoded(spec),task))
        self.assertEqual(self.service.post(self.body(),'wulv',self.headers)[0],202)

    def test_search_literal_wildcards_period_mine_and_paging(self):
        key,_,_=self.seed('DY',question='合成100%_样本，不是业务事实。')
        self.seed('wulv',question='合成100个样本。')
        found=self.get(q='100%_')[1]['items'];self.assertEqual([r['id'] for r in found],[key])
        self.assertFalse(self.get(start='2026-10-06')[1]['items']);self.assertEqual(len(self.get(scope='mine')[1]['items']),1)
        for n in range(41):self.seed(question='合成分页 '+str(n))
        first=self.get()[1];second=self.get(before=str(first['next_before']))[1]
        self.assertEqual(len(first['items']),40);self.assertFalse(set(r['id'] for r in first['items'])&set(r['id'] for r in second['items']))
        self.assertEqual(len(first['items'])+len(second['items']),43)
        self.assertEqual(self.get(before='-1')[0],422);self.assertEqual(self.get(scope='other')[0],422)

    def test_followup_frozen_evidence_and_parent_immutability(self):
        key,task,body=self.seed('DY');before=self.snapshot()
        book=load_report_followup(self.service.tasks,key,body['start'],body['end'],ROOT,self.service.root)
        self.assertEqual(book.evidence,self.book.evidence);self.assertIn('合成原版报告',book.continuation_context)
        code,job=self.service.post(self.body(parent_report=key,question='请将原报告压缩为周会摘要。'),'wulv',self.headers)
        self.assertEqual(code,202);self.assertEqual(job['body']['parent_report'],key);self.assertNotEqual(job['id'],key)
        after=self.snapshot();self.assertEqual(after['tasks'],before['tasks']);self.assertEqual(after['evidence'],before['evidence'])
        self.assertIn(before['requests'][0],after['requests']);self.assertEqual(job['owner'],'wulv')
        thread=self.get(id=job['id'],thread='1')[1]['items'];self.assertEqual([r['id'] for r in thread],[key,job['id']])

    def test_followup_rejects_changed_period_deleted_unsettled_and_invalid_source(self):
        key,_,body=self.seed('DY')
        self.assertEqual(self.service.post(self.body(parent_report=key,start='2026-10-06'),'wulv',self.headers)[0],422)
        self.assertEqual(self.service.post(self.body(parent_report={'id':key}),'wulv',self.headers)[0],422)
        active,_,_=self.seed('DY',state='RUNNING')
        self.assertEqual(self.service.post(self.body(parent_report=active),'wulv',self.headers)[0],403)
        self.service.trash_report('DY',key)
        self.assertEqual(self.service.post(self.body(parent_report=key),'wulv',self.headers)[0],404)

    def test_followup_detects_source_artifact_tampering(self):
        key,task,body=self.seed('DY');path=self.service.root/'reports'/task/'evidence.json';path.write_bytes(b'{}')
        self.assertEqual(self.service.post(self.body(parent_report=key),'wulv',self.headers)[0],422)

    def test_completed_07_report_can_be_revised_with_current_08_guards(self):
        key,task,body=self.seed('DY')
        with self.service.tasks.db() as db:
            spec=json.loads(db.execute('SELECT spec FROM tasks WHERE id=?',(task,)).fetchone()[0]);spec['knowledge_version']='0.7.0-report-semantic-quality'
            db.execute('UPDATE tasks SET spec=? WHERE id=?',(encoded(spec),task))
        book=load_report_followup(self.service.tasks,key,body['start'],body['end'],ROOT,self.service.root)
        self.assertEqual(book.skills['version'],'0.8.0-proof-constraints');self.assertEqual(book.evidence,self.book.evidence)

    def test_nonmember_cannot_follow_or_view_thread(self):
        key,_,_=self.seed('DY')
        self.assertEqual(self.get('viewer',id=key,thread='1')[0],404)
        self.assertEqual(self.service.post(self.body(parent_report=key),'viewer',self.headers)[0],403)

    def test_followup_full_controller_delivery_reuses_evidence_and_creates_new_version(self):
        parent,task,body=self.seed('DY');original=read_file(self.service.root,task,'json');prompts=[]
        class Immediate:
            def submit(_,fn,*args):fn(*args)
        self.service.pool=Immediate();self.run_root=self.run
        def remote(method,path,body=None,idempotency=None):
            admission=json.loads(next((self.run/'admissions').glob('*.json')).read_text(encoding='utf-8'));prompts.append(admission['prompt'])
            if method=='POST':return 202,{'run_id':'run_'+'f'*32,'status':'queued'}
            ref=self.service.proxy.dispatch('POST','/fc/tools/call',admission['token'],{'name':'mcp__fcro__fc_get_data_catalog','arguments':{}})['data']['evidence_id']
            self.service.proxy.dispatch('POST','/v1/chat/completions',admission['token'],{'model':'deepseek-v4.1-flash','reasoning_effort':'max','max_tokens':50,'messages':[{'role':'user','content':'synthetic fixture'}]})
            return 200,{'status':'completed','output':encoded({'report_contract':'fs-report-v2','summary':'合成修订完成，不是经营事实。','research_text':'## 关键判断\n合成修订，证据 '+ref,'findings':[],'actions':[],'limitations':['合成测试']})}
        gateway=lambda *args:controller_fixtures.ControllerTests.build_gateway(self,*args)
        with patch('controller.build_book',side_effect=AssertionError('no fresh source capture')),patch('controller.gateway',side_effect=gateway),patch.object(self.service,'remote',side_effect=remote):
            code,job=self.service.post(self.body(parent_report=parent,question='请精简原报告并保留证据。'),'wulv',self.headers)
        self.assertEqual(code,202);self.assertEqual(job['state'],'COMPLETED',job);self.assertNotEqual(job['task_id'],task)
        self.assertEqual(job['result']['parent_report'],parent);self.assertFalse(job['result']['source_capture_repeated'])
        self.assertTrue(all('合成原版报告' in p for p in prompts));self.assertEqual(read_file(self.service.root,task,'json'),original)
        self.assertIn('合成修订',self.get(id=job['id'],artifact='html')[1]['content']);self.assertEqual(job['model_usage']['calls'],1)
        self.assertEqual(self.get(id=job['id'],artifact='boss')[0],200)

if __name__=='__main__':unittest.main()
