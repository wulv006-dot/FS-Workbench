"""Binding/control-flow selfcheck only: no candidate import, child spawn or Linux locks."""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import hashlib
import errno
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('registration_mp_harness_v2', HERE / 'multiprocess_probe.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
assert hashlib.sha256((HERE / 'multiprocess_probe.py').read_bytes()).hexdigest() == '5436f1eeb4f66977d7b88ae337a3520e1b7e90902a512425f47220a9b1b2b1bb'
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--package', type=Path, default=HERE.parents[1] / 'registration_approval_runtime_v3_20261006')
fixture_options, unittest_options = parser.parse_known_args()
FIXTURE = fixture_options.package


class HarnessSelfcheck(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-registration-harness-selfcheck-')
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(Path(tempfile.gettempdir()).resolve())
        assert self.root.name.startswith('fs-registration-harness-selfcheck-')
        self.stage = self.root / 'stage'
        self.stage.mkdir()
        manifest = json.loads(h.MANIFEST.read_text())
        fixture_binding = h.verify_package(FIXTURE)  # bytes only, never import fixture
        source_stage = Path(fixture_binding['package'])
        for row in manifest['payloads']:
            path = self.stage / row['path'][len(h.PREFIX):]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((source_stage / row['path'][len(h.PREFIX):]).read_bytes())

    def tearDown(self):
        self.temp.cleanup()  # only this verified, uniquely created synthetic root

    def test_exact32_identity_without_import(self):
        before = set(sys.modules)
        binding = h.verify_package(self.stage)
        self.assertEqual(32, binding['payloads'])
        self.assertEqual(h.SUBTREE, binding['source_subtree'])
        self.assertEqual(h.COMMIT, binding['commit'])
        self.assertEqual(h.TREE, binding['tree'])
        self.assertFalse(set(h.MODULES) & (set(sys.modules) - before))

    def test_modified_payload_rejected_before_import(self):
        path = self.stage / 'runtime.py'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'payload mismatch'):
            h.verify_package(self.stage)

    def test_missing_extra_and_empty_pycache_rejected(self):
        extra = self.stage / 'unlisted.txt'
        extra.write_text('synthetic')
        with self.assertRaisesRegex(ValueError, 'exactly'):
            h.verify_package(self.stage)
        extra.unlink()
        (self.stage / '__pycache__').mkdir()
        with self.assertRaisesRegex(ValueError, 'bytecode'):
            h.verify_package(self.stage)
        (self.stage / '__pycache__').rmdir()
        (self.stage / 'runtime.py').unlink()
        with self.assertRaises(FileNotFoundError):
            h.verify_package(self.stage)

    def test_wrong_manifest_and_relative_input_rejected(self):
        manifest = self.root / 'wrong-manifest.json'
        manifest.write_text('{}')
        with patch.object(h, 'MANIFEST', manifest), self.assertRaisesRegex(ValueError, 'manifest mismatch'):
            h.verify_package(self.stage)
        with self.assertRaisesRegex(ValueError, 'absolute'):
            h.verify_package('relative-stage')

    def test_exact_module_origins_and_outside_origin_rejected(self):
        modules = {name: types.SimpleNamespace(__file__=str(self.stage / relative)) for name, relative in h.MODULES.items()}
        with patch.dict(sys.modules, modules):
            self.assertEqual({name: str((self.stage / relative).resolve()) for name, relative in h.MODULES.items()}, h.module_origins(self.stage))
            modules['runtime'].__file__ = str(HERE / 'multiprocess_probe.py')
            with self.assertRaisesRegex(ValueError, 'origin mismatch'):
                h.module_origins(self.stage)

    def test_preloaded_candidate_never_imported(self):
        with patch.dict(sys.modules, {'runtime': types.SimpleNamespace(__file__=str(self.stage / 'runtime.py'))}), patch.object(h.importlib, 'import_module') as importer:
            with self.assertRaisesRegex(ValueError, 'preloaded'):
                h.bound_modules(self.stage)
            importer.assert_not_called()

    def test_second_launch_failure_retains_first_for_cleanup(self):
        first = Mock()
        first.returncode = None
        first.poll.side_effect = [None, -15]
        def terminate(): first.returncode = -15
        first.terminate.side_effect = terminate
        first.communicate.return_value = ('', '')
        children = h.Children()
        with patch.object(h.subprocess, 'Popen', side_effect=[first, OSError('synthetic launch failure')]) as popen:
            children.start('register-a', self.stage, self.root)
            with self.assertRaises(OSError):
                children.start('register-b', self.stage, self.root)
        self.assertEqual([('register-a', first)], children.items)
        self.assertEqual('-B', popen.call_args_list[0].args[0][1])
        self.assertEqual([{'phase': 'register-a', 'returncode': -15}], children.cleanup())
        first.terminate.assert_called_once()
        first.kill.assert_not_called()

    def test_prepare_registered_and_bounded_without_spawn(self):
        child = Mock(returncode=0)
        child.communicate.return_value = ('PREPARED\n', '')
        children = h.Children()
        with patch.object(h.subprocess, 'Popen', return_value=child) as popen:
            children.finish(children.start('prepare', self.stage, self.root), 'PREPARED')
        self.assertEqual([('prepare', child)], children.items)
        child.communicate.assert_called_once_with(timeout=20)
        self.assertEqual('1', popen.call_args.kwargs['env']['PYTHONDONTWRITEBYTECODE'])
        self.assertFalse({'PYTHONPATH', 'PYTHONHOME', 'PYTHONOPTIMIZE'} & popen.call_args.kwargs['env'].keys())

    def test_cleanup_timeout_kills_only_registered_object(self):
        child = Mock()
        child.returncode = -9
        child.poll.side_effect = [None, -9]
        child.communicate.side_effect = [subprocess.TimeoutExpired('synthetic', 5), ('', '')]
        children = h.Children()
        children.items.append(('prepare', child))
        self.assertEqual([{'phase': 'prepare', 'returncode': -9}], children.cleanup())
        child.terminate.assert_called_once()
        child.kill.assert_called_once()

    def lock_unit_case(self, nonblocking_error):
        # Stub verifies delegation/error propagation only; NEVER a real flock acceptance.
        calls = []
        fake = types.ModuleType('fcntl')
        fake.LOCK_EX, fake.LOCK_NB, fake.LOCK_UN = 2, 4, 8
        def acquire(fd, operation):
            calls.append(operation)
            if operation == 6 and nonblocking_error is not None:
                raise nonblocking_error
        fake.flock = acquire
        directory = self.root / 'registration-approval'
        directory.mkdir()
        with (directory / 'namespace.lock').open('w+b') as lock, patch.dict(sys.modules, {'fcntl': fake}):
            try:
                with h.observe_real_lock(self.root):
                    fake.flock(lock.fileno(), fake.LOCK_EX)
            finally:
                self.assertIs(acquire, fake.flock)
                self.lock_calls = calls

    def test_busy_handshake_delegates_actual_blocking_operation(self):
        self.lock_unit_case(BlockingIOError(errno.EAGAIN, 'synthetic busy'))
        self.assertEqual([6, 2], self.lock_calls)
        self.assertEqual('kernel-blocked', (self.root / 'contender-attempt').read_text())

    def test_unexpected_free_lock_fails_and_unlocks(self):
        with self.assertRaisesRegex(AssertionError, 'did not exclude'):
            self.lock_unit_case(None)
        self.assertEqual([6, 8], self.lock_calls)
        self.assertFalse((self.root / 'contender-attempt').exists())

    def test_other_kernel_error_is_not_busy_evidence(self):
        with self.assertRaises(PermissionError):
            self.lock_unit_case(PermissionError(errno.EPERM, 'synthetic denied'))
        self.assertEqual([6], self.lock_calls)
        self.assertFalse((self.root / 'contender-attempt').exists())

    def test_ready_barriers_and_no_sleep_claim_static(self):
        source = (HERE / 'multiprocess_probe.py').read_text(encoding='utf-8')
        tree = ast.parse(source, feature_version=(3, 9))
        sleeps = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'sleep']
        self.assertEqual(1, len(sleeps))
        await_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'await_file')
        self.assertTrue(await_node.lineno < sleeps[0].lineno <= await_node.end_lineno)
        start = source.index("(root / 'start-race').write_text('start')")
        for phase in ('register-a', 'register-b'):
            self.assertLess(source.index("await_file(root / '" + phase + "-ready',"), start)

    def test_windows_refused_before_candidate_import(self):
        with patch.object(h.os, 'name', 'nt'), patch.object(h, 'bound_modules') as importer:
            with self.assertRaisesRegex(ValueError, 'Windows cannot'):
                h.controller(self.stage)
            importer.assert_not_called()


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]] + unittest_options, verbosity=2)
