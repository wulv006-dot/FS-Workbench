"""Test the actual shell wrapper with fake Docker, and actual retry proof function."""
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

HERE = Path(__file__).resolve().parents[1]


class CostTimeout(unittest.TestCase):
    def wrapper(self, code, payload='', baseline=False, read_failure=False):
        if os.name == 'nt':
            self.skipTest('shell integration requires Linux; run before publication')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'evidence').mkdir()
            (root / 'state').mkdir()
            docker = root / 'docker'
            docker.write_text('#!/bin/sh\nprintf "%s" "$TEST_PAYLOAD"\nexit "$TEST_EXIT"\n')
            docker.chmod(0o700)
            shell = (HERE / ('baseline' if baseline else 'source') / 'collect_p2pah_cost.sh').read_text()
            shell = shell.replace('/var/lib/fc27-cloud', str(root))
            result = subprocess.run(['sh'], input=shell, text=True, capture_output=True,
                env=dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                         TEST_PAYLOAD=payload, TEST_EXIT=str(code)), timeout=10)
            files = list((root / 'evidence').glob('*'))
            self.assertEqual(len(files), 1)
            values = result.returncode, json.loads(result.stdout), files[0].name
            if read_failure:
                return (*values, json.loads(files[0].read_text()))
            return values

    def test_baseline_loses_timeout_and_fix_preserves_it(self):
        self.assertEqual(self.wrapper(124, baseline=True)[1]['reason'], 'collector_failed')
        code, value, filename = self.wrapper(124)
        self.assertEqual(code, 1)
        self.assertEqual(value['reason'], 'collector_process_timeout')
        self.assertEqual(value['diagnostic'], {'exit_code': 124, 'timeout_seconds': 180})
        self.assertEqual(value['evidence_file'], filename)

    def test_order_http_wrapper_keeps_p0_budget_and_shared_session_mounts(self):
        shell = (HERE / 'source/collect_p2pah_cost.sh').read_text()
        self.assertIn('timeout 180s docker run', shell)
        self.assertIn('src=/opt/fs-order-session,dst=/opt/fs-order-session,readonly', shell)
        self.assertIn('src=/run/fs-order-session,dst=/run/fs-order-session,readonly', shell)

    def test_other_failures_and_invalid_success_stay_failures(self):
        for code, payload, reason in ((137, '', 'collector_output_empty'), (1, '', 'collector_output_empty'),
                                      (0, '{}', 'collector_payload_invalid')):
            self.assertEqual(self.wrapper(code, payload)[1]['reason'], reason)
        value = self.wrapper(1, json.dumps({'status': 'missing', 'reason': 'login_expired'}))[1]
        self.assertEqual(value['reason'], 'login_expired')

    def test_valid_cost_and_delivery_validation_remain(self):
        payload = {'status': 'valid', 'costs': [dict(platform=p, status='valid', genre='1',
                    delivery_type='订单发货') for p in ('PS', 'XBOX', 'PC')]}
        self.assertEqual(self.wrapper(0, json.dumps(payload))[0], 0)
        payload['costs'][0]['delivery_type'] = 'other'
        self.assertEqual(self.wrapper(0, json.dumps(payload))[0], 1)

    def test_failed_file_matches_sanitized_report(self):
        for code, payload, reason in (
            (124, '', 'collector_process_timeout'),
            (137, '', 'collector_output_empty'),
            (0, '{}', 'collector_payload_invalid'),
            (1, json.dumps({'status': 'missing', 'reason': 'login_expired',
                            'diagnostic': {'url': 'private-url', 'checked_at': 'private-url',
                                           'observed': {'typeHeader': 'private-url', 'table': True,
                                                        'page': '2', 'game': {'secret': 'private-url'}}}}),
             'login_expired'),
        ):
            with self.subTest(code=code, reason=reason):
                status, value, filename, saved = self.wrapper(code, payload, read_failure=True)
                self.assertEqual(status, 1)
                self.assertTrue(filename.endswith('.failed.json'))
                self.assertEqual(saved, value)
                self.assertEqual(saved['reason'], reason)
                self.assertEqual(saved['diagnostic']['exit_code'], code)
                self.assertNotIn('private-url', json.dumps(saved))
                if reason == 'login_expired':
                    self.assertEqual(saved['diagnostic']['observed'],
                                     {'table': True, 'page': '2', 'delivery_type_header_matches': False})

    def test_retry_requires_same_run_and_no_write_artifacts(self):
        tree = ast.parse((HERE / 'source/automation_tick.py').read_text())
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in {'valid_job_id', 'read_record', 'proven_prewrite_timeout'}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('runs', 'quotes', 'previews', 'requests', 'executions', 'all-coin-sync', 'player-sync'):
                (root / name).mkdir()
            namespace = dict(ROOT=root, json=json, uuid=uuid, TRANSIENT_TIMEOUTS={'TimeoutExpired'})
            exec(compile(tree, 'automation_tick.py', 'exec'), namespace)
            jid = str(uuid.uuid4())
            run = dict(run_id=jid, status='incomplete', quote_status='NO_QUOTE',
                       reason='IGGM:http_blocked;P2PAH:collector_process_timeout')
            job = dict(kind='auto_cycle', job_id=jid, status='failed', error='collection_incomplete',
                       completed_at='2026-10-25T21:17:50+08:00',
                       request={'policy_revision': 40}, snapshot=run, error_detail=run['reason'])
            path = root / 'runs' / (jid + '.json')
            path.write_text(json.dumps(run))
            check = namespace['proven_prewrite_timeout']
            self.assertTrue(check(job, 40))
            self.assertFalse(check(job, 41))
            for folder in ('quotes', 'previews', 'requests', 'executions', 'all-coin-sync', 'player-sync'):
                artifact = root / folder / (jid + '.json')
                artifact.write_text('{}')
                self.assertFalse(check(job, 40), folder)
                artifact.unlink()
            for reason in ('collector_failed', 'RuntimeError', 'login_expired', 'collector_process_timeout:extra'):
                run['reason'] = job['error_detail'] = 'P2PAH:' + reason
                path.write_text(json.dumps(run))
                self.assertFalse(check(job, 40), reason)


if __name__ == '__main__':
    unittest.main()
