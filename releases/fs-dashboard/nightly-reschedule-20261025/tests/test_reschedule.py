import ast,hashlib,importlib.util,json,os,re,secrets,sqlite3,stat,sys,tempfile,threading,traceback,types,unittest
from contextlib import contextmanager,ExitStack
from pathlib import Path
from datetime import date,datetime,timedelta
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
sys.path.append(str(ROOT.parents[0]/'cache-archive-retention-20261025/source'))
encoded=lambda v:json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
sys.modules.setdefault('pilot',types.SimpleNamespace(encoded=encoded,digest=lambda v:hashlib.sha256(encoded(v).encode()).hexdigest()))
import nightly
import nightly_data
import nightly_ops

class Service:
    def __init__(self,now):
        self.now=now;self.jobs={};self.calls=[];self.contexts={};self.failure=None;self.after_admission=False
        self.connection=sqlite3.connect(':memory:');self.connection.row_factory=sqlite3.Row
        self.connection.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,state TEXT)')
        self.tasks=types.SimpleNamespace(db=lambda:self.connection)
    def clock(self):return self.now
    def get_job(self,owner,key):return self.jobs.get(key)
    def submit_scheduled(self,body,context=None):
        self.calls.append(body['request_id'])
        self.contexts[body['request_id']]=context
        key=hashlib.sha256(encoded({'owner':'wulv','request_id':body['request_id']}).encode()).hexdigest()[:32]
        if self.after_admission:
            self.jobs[key]={'state':'DISPATCH_UNKNOWN','error':'original_receipt_required'}
            self.connection.execute('INSERT INTO requests VALUES(?,?)',(key,'DISPATCH_UNKNOWN'))
        if self.failure and self.failure in body['request_id']:raise ValueError('knowledge_source_changed:case')
        return 202,{'state':'PREPARING'}

class Scheduler(nightly.NightlyScheduler):
    def config(self):return {'owner':'wulv'}

class Scheduling(unittest.TestCase):
    def at(self,h,m=0,day=2):return datetime(2026,11,day,h,m,tzinfo=nightly.SHANGHAI)
    def scheduler(self,now):
        s=Service(now);self.addCleanup(s.connection.close)
        return s,Scheduler(s,readiness=lambda now:(True,[]))
    def seed(self,s,kind,state):
        request='night_'+kind+'_'+s.now.strftime('%Y%m%d')
        key=hashlib.sha256(encoded({'owner':'wulv','request_id':request}).encode()).hexdigest()[:32]
        s.connection.execute('INSERT INTO nightly_requests VALUES(?,?,?,?,?,?,NULL)',(request,key,'wulv',kind,s.now.replace(hour=7,minute=49).isoformat(),state))
        return key
    def test_daily_first_and_new_start_times(self):
        self.assertEqual(nightly.due(self.at(1,39)),[])
        self.assertEqual([v['kind'] for v in nightly.due(self.at(1,40))],['daily'])
        self.assertEqual([v['kind'] for v in nightly.due(self.at(2,10))],['daily','management'])
        self.assertIn('weekly',[v['kind'] for v in nightly.due(self.at(2,40))])
        self.assertIn('management_weekly',[v['kind'] for v in nightly.due(self.at(3,25))])
        self.assertNotIn('monthly',[v['kind'] for v in nightly.due(self.at(4,10))])
        self.assertIn('monthly',[v['kind'] for v in nightly.due(self.at(4,10,1))])
    def test_closed_windows_unchanged(self):
        self.assertEqual(nightly.closed_period(self.at(3).date(),'weekly'),('2026-10-26','2026-11-01'))
        self.assertEqual(nightly.closed_period(self.at(3).date(),'daily'),('2026-11-01','2026-11-01'))
    def test_no_new_submission_at_deadline(self):
        self.assertTrue(nightly.due(self.at(7,48)))
        self.assertEqual(nightly.due(self.at(7,49)),[])
        self.assertTrue(nightly.inside(self.at(7,49)))
        self.assertFalse(nightly.inside(self.at(7,50)))
    def test_waiting_expired_but_no_fake_daily_failure(self):
        s,n=self.scheduler(self.at(7,49));self.seed(s,'management','WAITING')
        n.tick();rows=s.connection.execute('SELECT kind,state FROM nightly_requests').fetchall()
        self.assertEqual([tuple(r) for r in rows],[('management','EXPIRED')]);self.assertEqual(s.calls,[])
    def test_value_error_does_not_block_next_due_report(self):
        s,n=self.scheduler(self.at(2,45));self.seed(s,'daily','COMPLETED');s.failure='management'
        with patch.dict(sys.modules,{'management_context':types.SimpleNamespace(scheduled_question=lambda n:'management case',scheduled_weekly_question=lambda n:'weekly case')}):n.tick()
        self.assertEqual(s.calls,['night_management_20261102','night_weekly_20261102'])
        rows=s.connection.execute('SELECT kind,state,error FROM nightly_requests ORDER BY rowid').fetchall()
        self.assertEqual(rows[1]['state'],'WAITING')
        self.assertEqual(rows[1]['error'],'nightly_admission_ValueError:knowledge_source_changed:case')
        self.assertEqual(rows[2]['state'],'PREPARING')
    def test_failed_daily_can_retry_same_id(self):
        s,n=self.scheduler(self.at(1,45));s.failure='daily';n.tick()
        first=s.connection.execute('SELECT id,state FROM nightly_requests').fetchone();self.assertEqual(first['state'],'WAITING')
        s.failure=None;n.tick();second=s.connection.execute('SELECT id,state FROM nightly_requests').fetchone()
        self.assertEqual(first['id'],second['id']);self.assertEqual(second['state'],'PREPARING')
        self.assertEqual(s.calls,['night_daily_20261102','night_daily_20261102'])
    def test_post_admission_unknown_never_replayed(self):
        s,n=self.scheduler(self.at(2,45));s.failure='daily';s.after_admission=True;n.tick();n.tick()
        self.assertEqual(s.calls,['night_daily_20261102'])
        self.assertEqual(s.connection.execute('SELECT state FROM nightly_requests').fetchone()[0],'DISPATCH_UNKNOWN')
    def test_waiting_source_does_not_block_other_report(self):
        s,n=self.scheduler(self.at(2,15))
        with patch.object(nightly,'preparation_status',side_effect=lambda now,kind:(kind=='management',['daily_gap'] if kind=='daily' else [])) as ready:
            n.readiness=ready
            with patch.dict(sys.modules,{'management_context':types.SimpleNamespace(scheduled_question=lambda n:'management case',scheduled_weekly_question=lambda n:'weekly case')}):n.tick()
        self.assertEqual(s.calls,['night_management_20261102'])
        self.assertEqual(s.connection.execute("SELECT state FROM nightly_requests WHERE kind='daily'").fetchone()[0],'WAITING')
    def test_running_global_request_keeps_serial(self):
        s,n=self.scheduler(self.at(2,45));s.connection.execute("INSERT INTO requests VALUES('case','RUNNING')");n.tick()
        self.assertEqual(s.calls,[])
    def test_running_source_preparation_does_not_block_ready_report(self):
        s,n=self.scheduler(self.at(2,15))
        s.source_preparation=types.SimpleNamespace(thread=types.SimpleNamespace(is_alive=lambda:True))
        original=s.submit_scheduled;questions=[]
        def submit(body,context=None):
            questions.append(body['question']);return original(body,context=context)
        s.submit_scheduled=submit
        n.tick()
        self.assertEqual(s.calls,['night_daily_20261102'])
        self.assertLessEqual(len(questions[0]),600)
        context=s.contexts['night_daily_20261102']
        self.assertIn('nightly_preparation_still_running',context['preparation_gaps'])
        self.assertIn('archive_status',context);self.assertIn('未知不填零',context['rule'])
        self.assertIn('真实数据暂未提供',context['rule']);self.assertIn('核对误差',context['rule'])
    def test_early_fallback_preserves_gap_labels(self):
        with patch.object(nightly,'source_status',return_value=(True,['marketing_partial'])),patch.object(nightly_data,'preparation_gaps',return_value=['source_gap']):
            self.assertFalse(nightly.preparation_status(self.at(1,59))[0])
            self.assertEqual(nightly.preparation_status(self.at(2)),(True,['marketing_partial','source_gap']))
    def test_status_time_matches_dispatch(self):
        s,n=self.scheduler(self.at(2));v=n.status('wulv')
        self.assertEqual(v['starts']['daily'],'01:40');self.assertEqual(v['starts']['management'],'02:10')
        self.assertEqual(v['stop_at'],'07:49');self.assertFalse(v['daytime_catchup'])
    def test_original_retry_and_unknown_policy(self):
        self.assertFalse(nightly_ops.retry_decision(self.at(2),{'ActiveState':'active','Result':'exit-code'},[]))
        self.assertFalse(nightly_ops.retry_decision(self.at(2),{'ActiveState':'inactive','Result':'exit-code'},[{'state':'unknown'}]))
        self.assertTrue(nightly_ops.retry_decision(self.at(2),{'ActiveState':'failed','Result':'exit-code'},[]))
    def test_recovery_window_and_native_original_id_guards(self):
        tree=ast.parse((ROOT/'source/nightly_recovery_job.py').read_text(encoding='utf-8'))
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        source=ast.get_source_segment((ROOT/'source/nightly_recovery_job.py').read_text(encoding='utf-8'),main)
        self.assertIn('70 <= now.hour*60+now.minute < 90',source)
        self.assertIn('unknown_no_replay',source);self.assertIn("j.get('name') == name",source)
        self.assertIn('01:30前停止补查',source)
    def test_controller_records_stage_and_safe_trace(self):
        tree=ast.parse((ROOT/'source/controller.py').read_text(encoding='utf-8'))
        node=next(n for cls in tree.body if isinstance(cls,ast.ClassDef) and cls.name=='HermesService' for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_recover_loop')
        scope={'Path':Path,'traceback':traceback,'re':re};seen=[]
        scope['atomic']=lambda p,v,**kw:seen.append((str(p),v))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'recovery-loop-case','exec'),scope)
        stop=iter([False,True])
        def fail(*a):raise ValueError('knowledge_source_changed:case')
        service=types.SimpleNamespace(recovery_stop=types.SimpleNamespace(wait=lambda _:next(stop)),recover_reports=lambda:None,
            source_preparation=types.SimpleNamespace(tick=lambda _:None),nightly=types.SimpleNamespace(tick=fail),root=Path('/case'),clock=lambda:self.at(2),detail=None)
        with patch.dict(sys.modules,{'cohort_reader':types.SimpleNamespace(reader_for=lambda _:types.SimpleNamespace(tick=lambda:None))}):scope['_recover_loop'](service)
        v=seen[0][1];self.assertEqual(v['stage'],'report_schedule');self.assertEqual(v['reason'],'knowledge_source_changed:case');self.assertTrue(v['frames'])
    def test_sources_compile(self):
        for p in (ROOT/'source').glob('*.py'):compile(p.read_bytes(),str(p),'exec')
    def test_publisher_retains_exact_targets_and_original_guards(self):
        spec=importlib.util.spec_from_file_location('nightly_reschedule_release',ROOT/'deploy/release.py')
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory() as d:
            release.HERE=Path(d)
            rows=[dict(candidate=k,target=v,beforeSha256='a'*64,sha256='b'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()]
            manifest=dict(scope=release.SCOPE,files=rows,businessWrites=False,timersChanged=True)
            p=Path(d)/'approved-manifest.json';p.write_text(json.dumps(manifest),encoding='utf-8')
            base=release.load_base()
            self.assertEqual(base.expected_files(manifest),set(release.TARGETS))
            self.assertTrue(callable(base.hermes_quiescent));self.assertTrue(callable(base.rollback))
            rows[0]['beforeSha256']=None;p.write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'existing_sources'):release.load_base()
            rows[0]['beforeSha256']='a'*64;manifest['businessWrites']=True;p.write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'no_business_writes'):release.load_base()
    def test_publisher_restores_exact_line_endings_and_rejects_content_drift(self):
        spec=importlib.util.spec_from_file_location('reschedule_publisher_line_endings',ROOT/'deploy/release.py')
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        original=release.LEGACY.read_bytes()
        frozen=release.LEGACY.with_name('release_navigation_base.py').read_bytes().replace(b'\r\n',b'\n')
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);release.HERE=folder;release.LEGACY=folder/'legacy.py'
            release.LEGACY.write_bytes(original)
            p=folder/'release_navigation_base.py';p.write_bytes(frozen)
            rows=[dict(candidate=k,target=v,beforeSha256='a'*64,sha256='b'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()]
            (folder/'approved-manifest.json').write_text(json.dumps(dict(scope=release.SCOPE,files=rows,businessWrites=False,timersChanged=True)),encoding='utf-8')
            self.assertEqual(release.load_base().HERMES_HISTORY_SCOPE,release.SCOPE)
            p.write_bytes(frozen+b'\n# unexpected content\n')
            with self.assertRaisesRegex(ValueError,'frozen_publisher_drift'):release.load_base()

class RealScheduledAdmission(unittest.TestCase):
    controller_source=ROOT/'source/controller.py'
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.now=datetime(2026,11,2,2,45,tzinfo=nightly.SHANGHAI)
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE requests(id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,body TEXT,state TEXT,task_id TEXT,error TEXT,result TEXT);CREATE TABLE request_knowledge(id TEXT PRIMARY KEY,version TEXT);')
        tree=ast.parse(self.controller_source.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HermesService')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('submit_scheduled','_submit_report','execute')]
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('clean_hermes_question','admission_guard')]
        self.knowledge=dict(version='frozen-test',skills={'version':'skills','sha256':'e'*64},text='frozen rules',
            identity={'knowledge_sha256':'d'*64},files=[],memory_path=None,native_skip_reason=None)
        self.writes=[];self.remote_inputs=[];self.queued=[];self.task=None
        namespace=dict(Path=Path,date=date,datetime=datetime,timedelta=timedelta,SHANGHAI=nightly.SHANGHAI,
            re=re,json=json,os=os,stat=stat,secrets=secrets,contextmanager=contextmanager,ExitStack=ExitStack,
            digest=sys.modules['pilot'].digest,encoded=encoded,load_bundle=lambda *a,**k:{},
            freeze_learning=lambda *a,**k:self.knowledge,loaded_learning=lambda *a:self.knowledge,
            spending_hold=lambda *a:None,html_design_context=lambda q:('',None),
            request_report_kind=lambda b:'daily',build_book=lambda *a,**k:types.SimpleNamespace(capture_id='snapshot',evidence={}),
            attach_owner_history=lambda *a:None,gateway=lambda *a,**k:types.SimpleNamespace(budget=types.SimpleNamespace(policy={'model':'fixture'})),
            submission=lambda t:{'body':{'session_id':'fc_fixture','input':'protocol'},'headers':{'Idempotency-Key':'original'}},
            FORMAT='format',POLICY_ID='policy',data_request_context=lambda b:'',
            atomic=lambda p,v,**k:self.writes.append((Path(p),json.loads(json.dumps(v)))))
        self.namespace=namespace
        exec(compile(ast.Module(body=functions+methods,type_ignores=[]),str(self.controller_source),'exec'),namespace)
        @contextmanager
        def database():
            with self.db:yield self.db
        def get_job(owner,key):
            row=self.db.execute('SELECT * FROM requests WHERE owner=? AND id=?',(owner,key)).fetchone()
            return dict(row) if row else None
        def update(key,**fields):
            self.db.execute('UPDATE requests SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),key))
        def create(owner,spec):
            self.task={'id':'a'*32,'state':'QUEUED','spec':spec};return self.task
        def reserve(*a):self.task['state']='DISPATCH_UNKNOWN'
        service=types.SimpleNamespace(root=self.folder,source_root=ROOT,run_root=self.folder/'run',clock=lambda:self.now,
            tasks=types.SimpleNamespace(db=database,create=create,reserve_dispatch=reserve,get=lambda *a:self.task),
            authorizer=lambda owner:owner=='wulv',proxy=types.SimpleNamespace(background={}),daily=None,
            matching_report=lambda *a:None,get_job=get_job,update=update,
            pool=types.SimpleNamespace(submit=lambda *a,**k:self.queued.append((a,k))),
            detail=None,read_range=None,diagnostics=None,lock=threading.RLock(),action_history=lambda owner:[],
            grants=types.SimpleNamespace(mint=lambda *a,**k:'fixture-token',revoke=lambda *a:None),tokens={},books={},gateways={})
        for name in ('_submit_report','submit_scheduled','execute'):setattr(service,name,types.MethodType(namespace[name],service))
        self.service=service
        service.nightly=Scheduler(service,readiness=lambda now:(True,['marketing_preparation_missing']))
        self.registry=types.SimpleNamespace(manifest=lambda *a:{'experiences':[]},record_use=lambda *a:None)
        self.catalog=types.SimpleNamespace(report_selection=lambda *a,**k:{'entries':[]})
        self.observed={'status':'partial','coverage_complete':None,'missingCount':16,'blocks_publication':False,
            'missing':[{'status':'failed','reason':'es_export_permission_denied','retryable':False,'query':{'profile':'FC27','start':'2026-11-01','end':'2026-11-01'}} for _ in range(16)]}

    def patches(self):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.dict(sys.modules,{'learning_registry':self.registry,'knowledge_catalog':self.catalog,
            'management_context':types.SimpleNamespace(scheduled_question=lambda n:'经营管理台全项目经营复盘',scheduled_weekly_question=lambda n:'经营管理台全项目自然周复盘'),
            'background':types.SimpleNamespace(task_context=lambda *a:('',{'context_sha256':'c'*64}))}))
        stack.enter_context(patch('source_snapshots.archive_status',return_value=self.observed))
        stack.enter_context(patch('source_snapshots.prepared_brief',return_value={'status':'partial'}))
        return stack

    def test_real_controller_boundary_accepts_large_gap_context_and_keeps_original_id(self):
        with self.patches():self.service.nightly.tick()
        self.assertEqual(len(self.queued),1)
        args,kwargs=self.queued[0];key,owner,body=args[1:]
        self.assertEqual(body['request_id'],'night_daily_20261102')
        self.assertLessEqual(len(body['question']),600)
        self.assertNotIn('es_export_permission_denied',body['question'])
        context=kwargs['scheduled_context']
        self.assertGreater(len(encoded(context)),600)
        self.assertEqual(context['archive_status'],self.observed)
        self.assertEqual(context['preparation_gaps'],['marketing_preparation_missing'])
        self.assertIn('真实数据暂未提供',context['rule'])
        self.assertEqual(self.service.get_job(owner,key)['state'],'PREPARING')
        with self.patches():self.assertEqual(self.service._submit_report(body,owner,True)[0],200)
        self.assertEqual(len(self.queued),1)
        # Invoke the real execute method until the first network-dispatch boundary.
        class DispatchProbe(BaseException):pass
        def remote(method,path,value,*a,**kw):
            self.remote_inputs.append(value);raise DispatchProbe()
        self.service.remote=remote
        self.namespace['management_context']=types.SimpleNamespace(request_snapshot=lambda b:False,attach=lambda *a:None)
        with self.patches(),self.assertRaises(DispatchProbe):args[0](*args[1:],**kwargs)
        admissions=[value for path,value in self.writes if path.parent.name=='admissions']
        self.assertEqual(len(admissions),1)
        self.assertIn(encoded(context),admissions[0]['prompt'])
        self.assertIn(encoded(context),self.remote_inputs[0]['input'])
        self.assertEqual(admissions[0]['skill_question'],body['question'])

    def test_actual_question_limit_and_public_fields_are_not_relaxed(self):
        body=dict(kind='hermes_report',request_id='manual_fixture',start='2026-11-01',end='2026-11-01',mode='daily',question='x'*601)
        self.assertEqual(self.service._submit_report(body,'wulv',True),(422,{'error':'invalid_period_or_question'}))
        body['question']='检查经营变化'
        self.assertEqual(self.service._submit_report(dict(body,scheduled_context=self.observed),'wulv',True),(422,{'error':'report_fields'}))
        self.assertEqual(self.queued,[])

    def test_all_original_report_kinds_use_bounded_questions_and_preserve_scope(self):
        with self.patches():
            for kind in ('daily','weekly','monthly','management','management_weekly'):
                with self.subTest(kind=kind):
                    self.db.execute('DELETE FROM requests');self.db.execute('DELETE FROM request_knowledge');self.db.execute('DELETE FROM nightly_requests');self.queued.clear()
                    start,end=nightly.closed_period(self.now.date(),kind)
                    item=dict(kind=kind,request_id='night_'+kind+'_20261102',start=start,end=end,deadline=self.now.replace(hour=7,minute=49).isoformat())
                    with patch.object(nightly,'due',return_value=[item]):self.service.nightly.tick()
                    self.assertEqual(len(self.queued),1)
                    args,kwargs=self.queued[0];self.assertLessEqual(len(args[-1]['question']),600)
                    self.assertEqual(args[-1]['start'],start);self.assertEqual(args[-1]['end'],end)
                    self.assertEqual(kwargs['scheduled_context']['archive_status'],self.observed)


class MaintainedScheduledAdmission(RealScheduledAdmission):
    controller_source=ROOT.parent/'knowledge-layering-20261023/source/controller.py'

    def setUp(self):
        super().setUp()
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            return module
        # The maintained controller now reserves genuine native metadata rather
        # than invoking the historical frozen-bundle/legacy prompt executor.
        self.native_bridge=load('scheduled_native_reports',self.controller_source.with_name('native_reports.py'))
        self.catalog=load('scheduled_knowledge_catalog',self.controller_source.with_name('knowledge_catalog.py'))
        self.artifacts=load('scheduled_report_artifacts',ROOT.parent/'hermes-data-workspace-20261018/source/report_artifacts.py')

    def patches(self):
        stack=super().patches()
        stack.enter_context(patch.dict(sys.modules,{'native_reports':self.native_bridge,'report_artifacts':self.artifacts}))
        return stack

    def test_real_controller_boundary_accepts_large_gap_context_and_keeps_original_id(self):
        with self.patches():self.service.nightly.tick()
        self.assertEqual(len(self.queued),1)
        args,kwargs=self.queued[0];key,owner,body=args[1:]
        self.assertEqual(body['request_id'],'night_daily_20261102')
        self.assertLessEqual(len(body['question']),600)
        self.assertNotIn('es_export_permission_denied',body['question'])
        context=kwargs['scheduled_context']
        self.assertGreater(len(encoded(context)),600)
        self.assertEqual(context['archive_status'],self.observed)
        self.assertEqual(context['preparation_gaps'],['marketing_preparation_missing'])
        self.assertIn('真实数据暂未提供',context['rule'])
        self.assertEqual(self.service.get_job(owner,key)['state'],'PREPARING')
        with self.patches():
            self.assertEqual(self.service._submit_report(body,owner,True)[0],200)
            saved=self.native_bridge.metadata(self.service,key)
        self.assertEqual(saved['identity']['contract'],'fs-native-report-knowledge-v1')
        self.assertEqual(saved['identity']['owner'],owner)
        self.assertEqual(len(self.queued),1)
        # This producer test stops at the real native helper boundary. Its
        # downstream task/turn/worker lifecycle has separate real-store tests.
        class DispatchProbe(BaseException):pass
        dispatched=[]
        def native_execute(*values):dispatched.append(values);raise DispatchProbe()
        with self.patches(),patch.object(self.native_bridge,'execute',side_effect=native_execute),self.assertRaises(DispatchProbe):
            args[0](*args[1:],**kwargs)
        self.assertEqual(dispatched,[(self.service,key,owner,body,context)])
        self.assertEqual(self.writes,[])
        self.assertEqual(self.remote_inputs,[])

    def seed_original(self):
        body=dict(kind='hermes_report',request_id='night_daily_20261102',start='2026-11-01',end='2026-11-01',mode='daily',question='检查经营变化')
        key=self.namespace['digest']({'owner':'wulv','request_id':body['request_id']})[:32]
        self.db.execute('INSERT INTO nightly_requests VALUES(?,?,?,?,?,?,NULL)',(body['request_id'],key,'wulv','daily',self.now.replace(hour=7,minute=49).isoformat(),'WAITING'))
        return body,key

    def test_context_does_not_bypass_owner_authorization(self):
        body,key=self.seed_original();self.service.authorizer=lambda owner:False
        self.assertEqual(self.service.submit_scheduled(body,context=self.observed),(403,{'error':'nightly_owner_not_authorized'}))
        self.assertIsNone(self.service.get_job('wulv',key));self.assertEqual(self.queued,[])

    def test_expired_original_stays_expired_without_new_request(self):
        body,key=self.seed_original();self.service.clock=lambda:self.now.replace(hour=7,minute=50)
        self.assertEqual(self.service.submit_scheduled(body,context=self.observed),(403,{'error':'nightly_not_admitted'}))
        self.service.nightly.tick()
        self.assertEqual([tuple(r) for r in self.db.execute('SELECT request_id,state FROM nightly_requests')],[(body['request_id'],'EXPIRED')])
        self.assertIsNone(self.service.get_job('wulv',key));self.assertEqual(self.queued,[])


class KnowledgeEnvelope(unittest.TestCase):
    def bundle(self,context,source_bytes=220000):
        import business_context as b
        def read(path,*args,**kw):
            return b'x'*source_bytes if Path(path).name=='business-baseline.md' else None
        with patch.object(b,'read_regular',side_effect=read),patch.dict(sys.modules,{'knowledge_catalog':types.SimpleNamespace(context=lambda _:context)}):
            return b.learning_bundle('/case',selection={'entries':[]})
    def test_complete_sources_and_catalog_survive_envelope_growth(self):
        import business_context as b
        text,sha,rows=self.bundle('CATALOG'+('c'*43000)+'END')
        self.assertGreater(len(text.encode()),b.MAX_TOTAL)
        self.assertLess(len(text.encode()),b.MAX_CONTEXT)
        self.assertIn('x'*220000,text);self.assertTrue(text.endswith('END'))
        self.assertEqual(rows[0]['bytes'],220000)
        self.assertEqual(sha,hashlib.sha256(text.encode()).hexdigest())
    def test_original_source_budget_still_rejects(self):
        with self.assertRaisesRegex(ValueError,'desktop_learning_bundle_too_large'):self.bundle('',262145)
    def test_context_budget_still_rejects(self):
        with self.assertRaisesRegex(ValueError,'desktop_learning_bundle_too_large'):self.bundle('c'*110000)
    def test_snapshot_limit_still_rejects_before_write(self):
        import business_context as b
        writes=[]
        with tempfile.TemporaryDirectory() as d,patch.object(b,'learning_bundle',return_value=('x'*1048577,'a'*64,[])),patch.dict(sys.modules,{'report_artifacts':types.SimpleNamespace(write_file=lambda *a:writes.append(a))}):
            with self.assertRaisesRegex(ValueError,'desktop_learning_snapshot_too_large'):b.freeze_learning(d,{'sha256':'b'*64},{},'daily')
        self.assertEqual(writes,[])

if __name__=='__main__':unittest.main()
