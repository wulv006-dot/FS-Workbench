import ast,json,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
import source_snapshots as snapshots

def readiness():
    tree=ast.parse((SOURCE/'nightly.py').read_text(encoding='utf-8'))
    tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('civil','preparation_status')]
    scope=dict(datetime=datetime,Path=Path,json=json,hashlib=__import__('hashlib'),SHANGHAI=snapshots.SHANGHAI)
    exec(compile(tree,'nightly-readiness','exec'),scope)
    return scope['preparation_status']

class ReportReadiness(unittest.TestCase):
    def test_scheduler_submits_original_due_request_with_explicit_estimate_policy(self):
        import sqlite3,importlib.util
        from contextlib import contextmanager
        with tempfile.TemporaryDirectory() as temp:
            db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
            self.addCleanup(db.close);db.execute('CREATE TABLE requests(state TEXT)')
            @contextmanager
            def database():
                with db:yield db
            spec=importlib.util.spec_from_file_location('nightly_fixture',SOURCE/'nightly.py')
            module=importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules,{'pilot':SimpleNamespace(digest=lambda v:__import__('hashlib').sha256(json.dumps(v,sort_keys=True).encode()).hexdigest(),encoded=json.dumps)}):spec.loader.exec_module(module)
            now=datetime(2026,10,22,0,45,tzinfo=snapshots.SHANGHAI)
            service=SimpleNamespace(tasks=SimpleNamespace(db=database),clock=lambda:now,get_job=lambda *a:None,submit_scheduled=Mock(return_value=(202,{'state':'PREPARING'})))
            scheduler=module.NightlyScheduler(service,readiness=lambda t:(True,['marketing_preparation_missing']))
            daily=[r for r in module.due(now) if r['kind']=='daily']
            with patch.object(scheduler,'config',return_value={'owner':'wulv'}),patch.object(module,'due',return_value=daily):
                scheduler.tick();scheduler.tick()
            service.submit_scheduled.assert_called_once()
            body=service.submit_scheduled.call_args.args[0]
            self.assertEqual(body['request_id'],'night_daily_20261022')
            self.assertIn('marketing_preparation_missing',body['question'])
            self.assertIn('真实数据暂未提供',body['question'])
            self.assertIn('核对误差',body['question'])

    def test_missing_sources_and_invalid_receipt_are_disclosed_without_postponing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'public').mkdir()
            ready,warnings=readiness()(datetime(2026,10,22,0,45,tzinfo=snapshots.SHANGHAI),boss_root=root,marketing_record=root/'marketing.json')
            self.assertTrue(ready)
            self.assertEqual(set(warnings),{'game-monitor_preparation_missing','management_preparation_missing','marketing_preparation_missing'})
            (root/'marketing.json').write_text('{')
            self.assertIn('marketing_preparation_invalid',readiness()(datetime.now(timezone.utc),boss_root=root,marketing_record=root/'marketing.json')[1])

    def test_prepared_input_lists_partial_sources_and_estimate_boundary(self):
        book=SimpleNamespace(native=None,query=lambda q:{'evidence_id':'ev_trend','data':{}},research=lambda n,q:{'evidence_id':'ev_gap','data':{'status':'partial'}})
        brief=snapshots.prepared_brief(book,'2026-10-21','2026-10-21')
        self.assertFalse(brief['collection_readiness']['blocks_publication'])
        self.assertEqual(brief['collection_readiness']['status'],'partial')
        self.assertTrue(brief['collection_readiness']['gaps'])
        self.assertIn('真实数据暂未提供',brief['rule'])
        self.assertIn('不可写入真实归档',brief['rule'])
        self.assertIn('误差',brief['rule'])

    def test_retry_survives_restart_and_complete_receipt_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            store=snapshots.SnapshotStore(Path(temp)/'private');store.directory()
            receipt=store.root/'preparation-2026-10-22.json'
            now=datetime(2026,10,22,1,0,tzinfo=snapshots.SHANGHAI)
            partial=dict(status='partial',attempt=1,retry_after=now.timestamp()-1,results=['original'])
            snapshots.atomic(receipt,partial)
            service=SimpleNamespace(nightly=SimpleNamespace(config=lambda:True),detail=SimpleNamespace(config={'enabled':True}))
            thread=SimpleNamespace(start=Mock(),is_alive=lambda:False)
            with patch.object(snapshots,'SnapshotStore',return_value=store),patch.object(snapshots.threading,'Thread',return_value=thread) as factory:
                snapshots.Preparation(service).tick(now)
                self.assertEqual(factory.call_args.kwargs['args'][2],2)
                self.assertEqual(store.read(receipt)['attempt'],2)
                snapshots.Preparation(service).tick(now+timedelta(seconds=1))
                self.assertEqual(thread.start.call_count,1)
                self.assertEqual(store.read(receipt.with_name('preparation-2026-10-22-attempt-1.json')),partial)
                snapshots.atomic(receipt,dict(status='ready',results=[dict(native_statuses=['ready'],supplements=[dict(status='available')])]))
                snapshots.Preparation(service).tick(now+timedelta(hours=2))
                self.assertEqual(thread.start.call_count,1)
                snapshots.Preparation(service).tick(now.replace(hour=8))
                self.assertEqual(thread.start.call_count,1)

    def test_partial_supplement_keeps_retry_pending_with_immutable_attempt(self):
        self.assertFalse(snapshots.preparation_complete([dict(native_statuses=['ready'],supplements=[dict(status='partial')])]))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);receipt=root/'preparation-2026-10-22.json'
            service=SimpleNamespace(nightly=SimpleNamespace(config=lambda:True),detail=SimpleNamespace(config={'enabled':True}),daily=None,read_range=None,diagnostics=None,source_root=root)
            fake=SimpleNamespace(build_book=lambda *a,**k:SimpleNamespace(capture_id='fixture'))
            brief={'native':[{'preparation_status':'ready'}],'supplements':[{'status':'partial'}]}
            now=datetime(2026,10,22,1,0,tzinfo=snapshots.SHANGHAI)
            with patch.dict(sys.modules,{'fs_evidence':fake,'nightly':SimpleNamespace(closed_period=lambda *a:('2026-10-21','2026-10-21'))}),patch.object(snapshots,'prepared_brief',return_value=brief):
                snapshots.Preparation(service).run(now,receipt,2)
            value=json.loads(receipt.read_text())
            self.assertEqual(value['status'],'partial');self.assertFalse(value['blocks_publication'])
            self.assertEqual(value['model_calls'],0)
            self.assertEqual(json.loads((root/'preparation-2026-10-22-attempt-2.json').read_text()),value)

if __name__=='__main__':unittest.main()
