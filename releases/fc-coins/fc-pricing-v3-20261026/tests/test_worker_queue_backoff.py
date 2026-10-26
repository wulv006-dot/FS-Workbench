"""Queue conflicts preserve their records and yield instead of spinning on the lock."""
import ast
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class StopLoop(BaseException):pass


class WorkerQueueBackoff(unittest.TestCase):
    def test_manual_readonly_collection_reports_infeasible_without_hiding_unknown(self):
        source=Path(__file__).resolve().parents[1]/'source/fc27_cloud_worker.py'
        main=next(node for node in ast.parse(source.read_text()).body if isinstance(node,ast.FunctionDef) and node.name=='main')
        for reason,business in [('pricing_v3_infeasible:NO_SAFE_COMMIT_PATH',True),('UNKNOWN',False)]:
            with self.subTest(reason=reason):
                job=dict(job_id='original',kind='collect',storefront=dict(status='ok'));saved=[]
                scope=dict(threading=SimpleNamespace(Thread=Mock()),heartbeat=Mock(),time=SimpleNamespace(sleep=Mock()),subprocess=SimpleNamespace(TimeoutExpired=TimeoutError),datetime=datetime,timezone=timezone,
                    recover_running_jobs=Mock(),retry_player_followups=Mock(),claim_next_job=Mock(side_effect=[job,StopLoop()]),handle=Mock(side_effect=ValueError(reason)),save_job=lambda row:saved.append(deepcopy(row)))
                exec(compile(ast.Module(body=[main],type_ignores=[]),str(source),'exec'),scope)
                with self.assertRaises(StopLoop):scope['main']()
                self.assertEqual(len(saved),1)
                if business:
                    self.assertEqual(saved[0]['status'],'ready');self.assertEqual(saved[0]['result']['status'],'INFEASIBLE');self.assertNotIn('error',saved[0])
                else:
                    self.assertEqual(saved[0]['status'],'failed');self.assertEqual(saved[0]['error'],'UNKNOWN')

    def test_queue_errors_back_off_without_claiming_or_replaying_work(self):
        source=Path(__file__).resolve().parents[1]/'source/fc27_cloud_worker.py'
        main=next(node for node in ast.parse(source.read_text()).body if isinstance(node,ast.FunctionDef) and node.name=='main')
        for failure in ('retry_player_followups','claim_next_job'):
            with self.subTest(failure=failure):
                scope=dict(threading=SimpleNamespace(Thread=Mock()),heartbeat=Mock(),time=SimpleNamespace(sleep=Mock()),
                    recover_running_jobs=Mock(),retry_player_followups=Mock(),claim_next_job=Mock())
                scope[failure].side_effect=[ValueError('queue_claim_needs_reconcile'),StopLoop()]
                exec(compile(ast.Module(body=[main],type_ignores=[]),str(source),'exec'),scope)
                with self.assertRaises(StopLoop):scope['main']()
                scope['time'].sleep.assert_called_once_with(2)
                if failure=='retry_player_followups':scope['claim_next_job'].assert_not_called()
                scope['recover_running_jobs'].assert_called_once_with()


if __name__=='__main__':unittest.main()
