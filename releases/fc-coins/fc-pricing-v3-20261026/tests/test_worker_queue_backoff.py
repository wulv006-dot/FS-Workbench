"""Queue conflicts preserve their records and yield instead of spinning on the lock."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class StopLoop(BaseException):pass


class WorkerQueueBackoff(unittest.TestCase):
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
