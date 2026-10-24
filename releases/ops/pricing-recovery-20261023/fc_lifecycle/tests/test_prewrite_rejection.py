import ast, json, sys, tempfile, unittest, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
SOURCE = Path(__file__).parents[1] / 'source/automation_tick.py'

class PrewriteTests(unittest.TestCase):

    def run_case(self, extra=None, marker=False):
        names = {'proven_prewrite_rejection', 'utc', 'valid_job_id', 'read_record', 'resolved_execution'}
        nodes = [n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('queue', 'jobs', 'runs', 'quotes', 'previews', 'requests', 'executions', 'all-coin-sync', 'player-sync'):
                (root / name).mkdir()
            jid = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            result = {'status': 'FAILED', 'reason': 'hook_scope_paused'}
            if extra:
                result.update(extra)
            job = {'job_id': jid, 'run_id': jid, 'kind': 'auto_cycle', 'status': 'failed', 'error': 'writer_not_confirmed', 'error_detail': 'hook_scope_paused', 'writer_result': result, 'request': {'policy_revision': 40}, 'created_at': (now - timedelta(minutes=1)).isoformat(), 'completed_at': now.isoformat()}
            if marker:
                (root / 'executions' / ('run-' + jid + '.used')).touch()
            env = {'ROOT': root, 'json': json, 'uuid': uuid, 'datetime': datetime, 'timezone': timezone}
            exec(compile(ast.Module(body=nodes, type_ignores=[]), 'prewrite', 'exec'), env)
            return env['proven_prewrite_rejection'](job, 40)

    def test_original_shape_is_proven(self):
        self.assertTrue(self.run_case())

    def test_recorded_null_diagnostic_is_proven(self):
        self.assertTrue(self.run_case({'missing_module': None}))

    def test_non_null_module_is_rejected(self):
        self.assertFalse(self.run_case({'missing_module': 'unknown'}))

    def test_unexpected_field_is_rejected(self):
        self.assertFalse(self.run_case({'sent': True}))

    def test_used_run_is_rejected(self):
        self.assertFalse(self.run_case({'missing_module': None}, True))
