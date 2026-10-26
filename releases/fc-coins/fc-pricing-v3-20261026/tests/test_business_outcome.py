import ast,json,sys,tempfile
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
SOURCE=Path(__file__).resolve().parents[1]/'source';sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import runtime,scheduler
from fc_pricing_v3.ledger import Ledger
import automation_policy
from fixtures import NOW


class BusinessOutcome(unittest.TestCase):
    def test_worker_preserves_original_quote_reason_before_any_execution(self):
        source=SOURCE/'fc27_cloud_worker.py'
        fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='collect_quote')
        reason='pricing_v3_infeasible:NO_SAFE_COMMIT_PATH'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runs').mkdir();(root/'monitor').mkdir();ident='original'
            (root/'runs/original.json').write_text(json.dumps(dict(run_id=ident,status='ready_for_quote')))
            (root/'monitor/storefront.json').write_text(json.dumps(dict(collection_run_id=ident,status='ok',rows={p:dict(status='ok') for p in ('PS','XBOX','PC')})))
            scope=dict(ROOT=root,APP=Path('/fixture'),PLATFORMS=('PS','XBOX','PC'),local_collection=SimpleNamespace(pin=lambda _:dict(mode='server')),save_job=Mock(),run=Mock(side_effect=[(0,dict(status='ready_for_quote')),(1,dict(status='NO_QUOTE',reason=reason))]),refresh_storefront=Mock(return_value=dict(status='ok')),atomic_json=Mock(),os=SimpleNamespace(chown=Mock(),chmod=Mock()),json=json,datetime=datetime,timezone=timezone)
            exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),scope)
            with patch.object(runtime,'ledger'),patch.object(runtime,'collection_scope',return_value=dict(active_mode='daily',scope={})),self.assertRaisesRegex(ValueError,reason):scope['collect_quote'](dict(job_id=ident))
            self.assertEqual(scope['run'].call_count,2)

    def test_business_infeasible_finishes_normally_but_technical_failure_still_raises(self):
        plan=dict(plan_id='p',state='ACTIVE',revision=2,resources=['base:console','base:pc'])
        for reason,business in [('pricing_v3_infeasible:NO_SAFE_COMMIT_PATH',True),('storefront_incomplete',False),('UNKNOWN',False)]:
            with self.subTest(reason=reason):
                db=Mock();db.active_plan.return_value=plan;db.get.return_value=None;db.all.return_value=[];db.generation.return_value=dict(id='g')
                db.connect.return_value=closing(Mock(close=Mock()))
                saved=[];worker=SimpleNamespace(collect_quote=Mock(side_effect=ValueError(reason)),save_job=lambda j:saved.append(deepcopy(j)))
                with patch.dict(sys.modules,{'fc27_cloud_worker':worker}),patch.object(scheduler,'ledger',return_value=db),patch.object(automation_policy,'load_policy',return_value=dict(system_enabled=True,mode='auto',revision=41)),patch.object(scheduler,'execute_run') as execute:
                    if business:
                        result=scheduler.cycle(dict(request_id='same-original'));self.assertEqual(result['status'],'INFEASIBLE');db.incident.assert_not_called();self.assertEqual(saved[-1]['status'],'ready')
                    else:
                        with self.assertRaisesRegex(ValueError,reason):scheduler.cycle(dict(request_id='same-original'))
                        db.incident.assert_called_once();self.assertEqual(saved[-1]['status'],'failed')
                execute.assert_not_called()

    def test_lowercase_business_code_is_done_infeasible_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3');db.enqueue('cycle','original',NOW,dict(plan_id='missing'))
            with db.transaction() as conn:
                conn.execute("UPDATE durable_jobs SET state='running' WHERE id='original'")
                job=dict(conn.execute("SELECT * FROM durable_jobs WHERE id='original'").fetchone())
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'cycle',side_effect=ValueError('pricing_v3_infeasible:NO_SAFE_COMMIT_PATH')),patch.object(scheduler,'clock',return_value=NOW):scheduler.run_job(job)
            with db.connect() as conn:row=conn.execute("SELECT state,attempt,body FROM durable_jobs WHERE id='original'").fetchone()
            self.assertEqual(row['state'],'done');self.assertEqual(row['attempt'],0)
            self.assertEqual(json.loads(row['body'])['result']['status'],'INFEASIBLE')


if __name__=='__main__':unittest.main()
