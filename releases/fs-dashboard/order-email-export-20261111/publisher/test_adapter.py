import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('email_export_adapter', Path(__file__).with_name('adapter.py'))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def manifest():
    return {'schemaVersion': 1, 'scope': a.SCOPE, 'releaseReady': True,
            'businessWrites': False, 'timersChanged': False, 'sourceCommit': 'a' * 40,
            'runtimeRequired': copy.deepcopy(a.RUNTIME),
            'unchangedRequired': [{'path': p, 'sha256': 'b' * 64} for p in sorted(a.PROTECTED)],
            'files': [{'candidate': name, 'target': target, 'sha256': hashlib.sha256(name.encode()).hexdigest(),
                       'beforeSha256': None if name == 'admin_order_email_export.py' or name.startswith('order-email-') else hashlib.sha256(b'old').hexdigest()}
                      for name, target in a.TARGETS.items()]}


class ContractTests(unittest.TestCase):
    def test_exact_contract(self):
        self.assertEqual(len(a.contract(manifest())), 9)

    def test_fail_closed(self):
        for change in (lambda m: m.update(scope='old'), lambda m: m.update(businessWrites=True),
                       lambda m: m.update(timersChanged=True), lambda m: m.update(imageId='old'),
                       lambda m: m.update(runtimeRequired={}), lambda m: m.update(unchangedRequired=[]),
                       lambda m: m['files'][0].update(target='/tmp/arbitrary'),
                       lambda m: m['files'][0].update(beforeSha256=None),
                       lambda m: next(r for r in m['files'] if r['candidate'] == 'admin_order_email_export.py').update(beforeSha256='bad'),
                       lambda m: m['files'].append(dict(m['files'][0])),
                       lambda m: m['files'][0].update(sha256='bad'),
                       lambda m: m['unchangedRequired'].append({'path': '/tmp/arbitrary', 'sha256': 'b' * 64})):
            m = manifest()
            change(m)
            with self.subTest(manifest=m), self.assertRaises((ValueError, TypeError)):
                a.contract(m)

    def test_hash_checked_before_exec(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'base.py'
            p.write_text("raise RuntimeError('must not execute')")
            with patch.object(a, 'BASE', p), self.assertRaisesRegex(ValueError, 'SHA differs'):
                a.load_base()

    def test_pending_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            base = types.SimpleNamespace(rooted=lambda r, p: r / p.lstrip('/'), no_target_link=lambda p: None)
            root = Path(folder)
            p = root / a.PENDING.lstrip('/')
            p.parent.mkdir(parents=True)
            p.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'pending'):
                a.pending_guard(base, root)


class FrozenWriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = Path(__file__).with_name('frozen_base.py').read_bytes()
        if hashlib.sha256(raw).hexdigest() != a.BASE_SHA256:
            raise AssertionError('integration fixture is not the frozen writer')
        cls.raw = raw

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'stage'
        self.m = manifest()
        base = types.ModuleType('frozen_fixture')
        base.__file__ = str(a.BASE)
        exec(compile(self.raw, str(a.BASE), 'exec'), base.__dict__)
        self.base = a.adapt(base)
        for row in self.m['files']:
            p = self.stage / 'candidate' / row['candidate']
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(row['candidate'].encode())
            if row['beforeSha256'] is not None:
                target = base.rooted(self.root, row['target'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'old')
        self.restart = Mock()
        self.fence = types.SimpleNamespace(modified=False, confirmed=False)
        for name in ('locks', 'live_lock', 'model_release_lock'):
            setattr(base, name, lambda *args: contextlib.nullcontext())
        base.hermes_admission_fence = lambda *args: contextlib.nullcontext(self.fence)
        base.guards = lambda m, r: (a.contract(m), a.pending_guard(base, r))
        base.directory_sync = lambda p: None  # Windows lacks POSIX directory fsync.
        base.restart_for = self.restart
        self.raw_manifest = json.dumps(self.m).encode()
        self.sha = hashlib.sha256(self.raw_manifest).hexdigest()

    def apply(self):
        return self.base.apply(self.m, self.stage, self.sha, self.raw_manifest, 'nav-20261111T080000Z', self.root)

    def test_inspect_no_mutation(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        self.assertFalse(self.base.inspect(self.m, self.stage, self.root)['mutations'])
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))
        self.restart.assert_not_called()

    def test_payload_and_existing_null_cas_rejected(self):
        row = self.m['files'][0]
        (self.stage / 'candidate' / row['candidate']).write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError, 'payload'):
            self.base.inspect(self.m, self.stage, self.root)
        (self.stage / 'candidate' / row['candidate']).write_bytes(row['candidate'].encode())
        row = self.m['files'][1]
        target = self.base.rooted(self.root, row['target'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'preexisting')
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            self.base.inspect(self.m, self.stage, self.root)

    def test_followup_apply_and_rollback_requires_exact_live_cas(self):
        for row in self.m['files']:
            target = self.base.rooted(self.root, row['target'])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'previous deployed payload')
            row['beforeSha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        self.raw_manifest = json.dumps(self.m).encode()
        self.sha = hashlib.sha256(self.raw_manifest).hexdigest()
        backup = Path(self.apply()['backup'])
        self.base.rollback(backup, self.sha, self.root)
        self.assert_restored()

    def test_apply_rollback_and_ledger(self):
        result = self.apply()
        backup = Path(result['backup'])
        self.assertEqual(result['staticFiles'], 9)
        self.assertEqual(json.loads((backup / 'journal.json').read_text())['approvedManifestSha256'], self.sha)
        self.base.rollback(backup, self.sha, self.root)
        self.assert_restored()
        self.assertEqual(self.restart.call_count, 2)

    def assert_restored(self):
        for row in self.m['files']:
            target = self.base.rooted(self.root, row['target'])
            self.assertEqual(self.base.digest(target), row['beforeSha256'])

    def test_failed_restart_restores_original_files(self):
        self.restart.side_effect = [ValueError('health failed'), None]
        with self.assertRaisesRegex(ValueError, 'health failed'):
            self.apply()
        self.assert_restored()
        self.assertEqual(self.restart.call_count, 2)

    def test_wrong_manifest_sha_and_repeat_id(self):
        with self.assertRaisesRegex(ValueError, 'SHA differs'):
            self.base.apply(self.m, self.stage, '0' * 64, self.raw_manifest, 'nav-20261111T080000Z', self.root)
        self.apply()
        with self.assertRaises(ValueError):
            self.apply()

    def test_pending_rejects_apply_before_write(self):
        pending = self.base.rooted(self.root, a.PENDING)
        pending.parent.mkdir(parents=True)
        pending.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'pending'):
            self.apply()
        self.assert_restored()

    def test_rollback_wrong_sha_and_target_drift_fail_closed(self):
        backup = Path(self.apply()['backup'])
        with self.assertRaises(ValueError):
            self.base.rollback(backup, '0' * 64, self.root)
        target = self.base.rooted(self.root, self.m['files'][0]['target'])
        target.write_bytes(b'newer independent release')
        with self.assertRaises(ValueError):
            self.base.rollback(backup, self.sha, self.root)
        self.assertEqual(target.read_bytes(), b'newer independent release')

    def test_original_fence_selected_and_pending_rejected(self):
        base = types.ModuleType('fence_fixture')
        exec(compile(self.raw, str(a.BASE), 'exec'), base.__dict__)
        held = object()
        original = Mock(return_value=contextlib.nullcontext(held))
        base.hermes_admission_fence = original
        a.adapt(base)
        with base.hermes_admission_fence(self.m, self.root) as actual:
            self.assertIs(actual, held)
        self.assertEqual(original.call_args[0][0]['scope'], base.HERMES_UPDATE_SCOPE)
        pending = base.rooted(self.root, a.PENDING)
        pending.parent.mkdir(parents=True)
        pending.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'pending'):
            with base.hermes_admission_fence(self.m, self.root):
                self.fail('pending must reject before fence entry')
        self.assertEqual(original.call_count, 1)

    def test_scope_restart_requires_fence_and_only_range(self):
        base = types.ModuleType('fresh_frozen_fixture')
        base.__file__ = str(a.BASE)
        exec(compile(self.raw, str(a.BASE), 'exec'), base.__dict__)
        commands = []
        base.subprocess = types.SimpleNamespace(run=lambda cmd, **kwargs: commands.append(cmd))
        base.urllib = types.SimpleNamespace(request=types.SimpleNamespace(urlopen=lambda *args, **kwargs: contextlib.nullcontext(types.SimpleNamespace(read=lambda: b'{"ok":true}'))))
        # Original health parser uses json.load(response).
        import io
        base.urllib.request.urlopen = lambda *args, **kwargs: contextlib.nullcontext(io.StringIO('{"ok":true}'))
        a.adapt(base)
        with self.assertRaisesRegex(ValueError, 'fence'):
            base.restart_for(self.m)
        held = types.SimpleNamespace(stop_then_unlock_database=Mock())
        base.restart_for(self.m, held)
        held.stop_then_unlock_database.assert_called_once()
        self.assertEqual(commands, [['nginx', '-t'], ['systemctl', 'restart', 'fs-business-range.service'], ['systemctl', 'is-active', '--quiet', 'fs-business-range.service'], ['systemctl', 'reload', 'nginx'], ['systemctl', 'is-active', '--quiet', 'nginx']])

    def test_invalid_nginx_stops_before_range_restart(self):
        base = types.ModuleType('bad_nginx_fixture')
        exec(compile(self.raw, str(a.BASE), 'exec'), base.__dict__)
        run = Mock(side_effect=ValueError('nginx syntax rejected'))
        base.subprocess = types.SimpleNamespace(run=run)
        a.adapt(base)
        held = types.SimpleNamespace(stop_then_unlock_database=Mock())
        with self.assertRaisesRegex(ValueError, 'nginx syntax'):
            base.restart_for(self.m, held)
        held.stop_then_unlock_database.assert_not_called()
        run.assert_called_once_with(['nginx', '-t'], check=True, timeout=30)


if __name__ == '__main__':
    unittest.main()
