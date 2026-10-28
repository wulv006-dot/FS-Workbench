import ast,hashlib,importlib.util,json,re,sqlite3,sys,tempfile,traceback,types,unittest
from pathlib import Path
from datetime import datetime,timedelta
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
        self.now=now;self.jobs={};self.calls=[];self.failure=None;self.after_admission=False
        self.connection=sqlite3.connect(':memory:');self.connection.row_factory=sqlite3.Row
        self.connection.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,state TEXT)')
        self.tasks=types.SimpleNamespace(db=lambda:self.connection)
    def clock(self):return self.now
    def get_job(self,owner,key):return self.jobs.get(key)
    def submit_scheduled(self,body):
        self.calls.append(body['request_id'])
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
        def submit(body):
            questions.append(body['question']);return original(body)
        s.submit_scheduled=submit
        n.tick()
        self.assertEqual(s.calls,['night_daily_20261102'])
        self.assertIn('nightly_preparation_still_running',questions[0])
        self.assertIn('归档分项观察',questions[0]);self.assertIn('未知不填零',questions[0])
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
