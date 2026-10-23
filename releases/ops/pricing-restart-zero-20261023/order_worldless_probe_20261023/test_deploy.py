"""Offline publisher contract checks: synthetic files and mocked systemd only."""
import ast
from contextlib import ExitStack, nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).with_name('deploy.py')


def function(name, scope):
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope[name]


class DeploymentTests(unittest.TestCase):
    def test_systemd_219_pid_parses_one_positive_integer_without_value_option(self):
        for output in ('MainPID=123\n', 'Other=unused\nMainPID=123\n'):
            command = Mock(return_value=output)
            get = function('pid', {'subprocess': SimpleNamespace(check_output=command)})
            self.assertEqual(get(), 123)
            self.assertNotIn('--value', command.call_args.args[0])
        for output in ('', 'MainPID=0\n', 'MainPID=bad\n', 'MainPID=1\nMainPID=2\n', 'MainPID=-1\n'):
            get = function('pid', {'subprocess': SimpleNamespace(check_output=Mock(return_value=output))})
            with self.assertRaises(AssertionError):
                get()

    def run_publish(self, fail_at=None, resume=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'source').mkdir()
            target = root/'service.py'; target.write_text('old-service')
            helper = root/'raw_node_helper.js'
            for name, text in (('service.py', 'new-service'), ('raw_node_helper.js', 'new-helper')):
                (root/'source'/name).write_text(text)
            digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            proof = root/'isolation.json'; original = {'status': 'verified', 'durability_verified': True, 'service_sha256': digest(target), 'old_durability': 'retained'}
            proof.write_text(json.dumps(original))
            execution = root/'exec.lock'; execution.touch()
            order = []; writes = []; runs = []
            def publish(values, op):
                for name in values: Path(name).read_bytes()  # Original dict publisher requires an existing target.
                order.extend(values)
                for name, text in values.items(): Path(name).write_text(text)
                (root/'backups'/op).mkdir(parents=True, exist_ok=True)
            def publish_helper(source, target, metadata):
                self.assertEqual(source, root/'source/raw_node_helper.js')
                self.assertFalse(target.exists()); self.assertEqual(metadata.st_mode, (root/'service.py').stat().st_mode)
                order.append(str(target)); target.write_bytes(source.read_bytes())
                if fail_at == 'after_helper': raise RuntimeError('synthetic_publish_failure')
            def atomic(path, value):
                writes.append((path, dict(value)))
                if fail_at == 'receipt_final' and value.get('status') == 'verified': raise OSError('synthetic_receipt_failure')
                path.write_text(json.dumps(value))
            def system(args, **kwargs): runs.append(args); return Mock(returncode=0)
            state = {'Id': 'same-container', 'State': {'Running': True, 'StartedAt': 'same-start'}, 'Config': {'Cmd': ['--restore-last-session']},
                     'Mounts': [{'Source': '/var/lib/fs-order-session/browser', 'Destination': '/var/lib/fs-order-session/browser'}]}
            scope = dict(ROOT=root, TARGET=target, HELPER=helper, BEFORE=digest(target), AFTER=digest(root/'source/service.py'), HELPER_SHA=digest(root/'source/raw_node_helper.js'),
                ISOLATION=proof, RECEIPT=root/'receipt.json', ISOLATION_LOCK=root/'isolation.lock', EXEC_LOCK=execution, OP='synthetic-operation', sha=digest,
                business_idle=nullcontext, ExitStack=ExitStack, idle=Mock(), no_active_rpg_container=Mock(), inspect=Mock(return_value=state),
                fcntl=SimpleNamespace(flock=Mock(), LOCK_EX=1, LOCK_NB=2, LOCK_UN=3),
                subprocess=SimpleNamespace(check_output=Mock(return_value='active\n'), run=system),
                health=Mock(return_value={'ready': True, 'login_attempts': 0, 'verified_age_seconds': 0}), pid=Mock(side_effect=[100, 101]),
                datetime=datetime, timezone=timezone, publish=publish, publish_helper=publish_helper, atomic_json=atomic, hashlib=hashlib, json=json, time=SimpleNamespace(monotonic=Mock(return_value=0), sleep=Mock()),
                Path=lambda value: root/'backups' if value == '/var/backups' else Path(value))
            with self.assertRaises(FileNotFoundError): publish({str(helper): 'must-not-write'}, 'old-publisher')
            function('verified_prewrite_failure', scope)
            initial = None
            if resume:
                initial = dict(operation=scope['OP'], status='unknown', error='FileNotFoundError', started_at='original-start',
                    service_before=scope['BEFORE'], service_after=scope['AFTER'], helper_after=scope['HELPER_SHA'],
                    original_isolation_sha256=hashlib.sha256(proof.read_bytes()).hexdigest())
                (root/'receipt.json').write_text(json.dumps(initial))
            main = function('main', scope)
            if fail_at:
                with self.assertRaises((RuntimeError, OSError)): main(True, resume)
            else:
                result = main(True, resume); self.assertEqual(result['status'], 'verified')
                self.assertEqual(json.loads(proof.read_text())['old_durability'], 'retained')
                self.assertEqual(json.loads(proof.read_text())['service_sha256'], scope['AFTER'])
                if resume:
                    self.assertEqual(result['initial_failure'], initial); self.assertEqual(result['started_at'], 'original-start')
                    self.assertEqual(result['operation'], initial['operation']); self.assertTrue(result['resumed_at'])
            self.assertEqual(order[0], str(helper))
            if fail_at != 'after_helper': self.assertEqual(order[1], str(target))
            else: self.assertEqual(json.loads(proof.read_text()), original)
            self.assertEqual(runs[-1], ['systemctl', 'start', 'p2pah-srv-exec.service'])
            self.assertFalse(any('docker' in command for command in runs))
            return writes

    def test_helper_precedes_service_then_native_ready_proof_preserves_history(self):
        self.run_publish()

    def test_partial_publish_or_receipt_failure_resumes_executor_and_does_not_replay(self):
        writes = self.run_publish('after_helper')
        self.assertEqual(writes[-1][1]['status'], 'unknown')
        self.run_publish('receipt_final')

    def test_same_id_resume_keeps_original_failure_evidence(self):
        self.run_publish(resume=True)

    def test_resume_rejects_wrong_phase_source_proof_or_prior_resume(self):
        before, after, helper = 'before', 'after', 'helper'
        scope = dict(OP='original-op', BEFORE=before, AFTER=after, HELPER_SHA=helper, hashlib=hashlib)
        verify = function('verified_prewrite_failure', scope)
        proof = b'original-proof'
        event = dict(operation='original-op', status='unknown', error='FileNotFoundError', service_before=before,
            service_after=after, helper_after=helper, original_isolation_sha256=hashlib.sha256(proof).hexdigest())
        verify(event, proof, before, False)
        for changes in ({'operation': 'different-op'}, {'status': 'started'}, {'error': 'TimeoutExpired'}, {'service_after': 'other'},
                        {'original_isolation_sha256': 'other'}, {'resumed_at': 'already'}, {'initial_failure': {'old': True}}):
            with self.assertRaises(AssertionError): verify(dict(event, **changes), proof, before, False)
        with self.assertRaises(AssertionError): verify(event, proof, before, True)
        with self.assertRaises(AssertionError): verify(event, proof, 'changed-service', False)


if __name__ == '__main__':
    unittest.main()
