"""Rollout composition, using the frozen CAS engine and real temporary locks/DBs.

Docker/systemd are simulated: these tests do not prove an image was built or a
service was loaded. Host-root ownership/provider surroundings are adapted to a
private temporary directory; apply, rollback, atomic writes, admission and both
SQLite fences remain the real implementations. The release's exact production
SQLite pin is checked separately from the fixture's real linked SQLite version.
"""
from contextlib import ExitStack, closing, contextmanager
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


try:
    import fcntl
except ImportError:
    fcntl = None


class ManifestFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.stage = self.root / 'stage'
        self.rollout = load('test_admission_rollout_adapter', DEPLOY / 'admission_release.py')
        self.before = self.rollout.BEFORE
        self.after = 'sha256:' + 'b' * 64
        self.unit_before = ('[Service]\nUser=root\nExecStart=/usr/bin/docker run --read-only '
                            '--mount type=bind,src=/existing,dst=/fs ' + self.before + '\n').encode()
        self.previous = {}
        self.manifest = dict(schemaVersion=1, scope=self.rollout.SCOPE, releaseReady=True,
                             businessWrites=False, timersChanged=False,
                             nativeUnits=list(self.rollout.UNITS),
                             nativeImageBefore=self.before, nativeImageAfter=self.after,
                             nativeSQLiteVersion='3.53.4', files=[], unchangedRequired=[],
                             runtimeRequired={u: dict(ActiveState='active', UnitFileState='enabled')
                                              for u in self.rollout.UNITS})
        sources = {'/opt/hermes/fs_native_entry.py': sha(b'old entry'),
                   '/opt/hermes/tui_gateway/server.py': sha(b'gateway'),
                   '/opt/hermes/gateway/run_turn_runner.py': sha(b'runner'),
                   '/opt/hermes/reviewed_skills.py': sha(b'skills')}
        self.manifest['nativeImageBeforeSources'] = sources
        self.manifest['nativeImageSources'] = dict(sources)
        entry = b'# exact fixture entry\nVALUE = 1\n'
        self.manifest['nativeImageSources'][self.rollout.ENTRY] = sha(entry)
        self.write(self.stage / 'native-image-context/fs_native_entry.py', entry)
        for name, target in self.rollout.TARGETS.items():
            previous = self.unit_before if name.startswith('native/') else b'# previous ' + name.encode() + b'\n'
            candidate = (self.unit_before.replace(self.before.encode(), self.after.encode())
                         if name.startswith('native/') else b'# new ' + name.encode() + b'\n')
            self.write(self.root / target.lstrip('/'), previous)
            self.write(self.stage / 'candidate' / name, candidate)
            self.previous[target] = previous
            self.manifest['files'].append(dict(candidate=name, target=target, sha256=sha(candidate),
                                               beforeSha256=sha(previous), owner='0:0', mode='0o644'))
        protected = self.root / 'protected-static'
        protected.mkdir(mode=0o700)
        info = protected.stat()
        self.manifest['nativeProtection'] = dict(metadata={'/protected-static': dict(kind='directory',
            uid=info.st_uid, gid=info.st_gid, mode=oct(stat.S_IMODE(info.st_mode)))},
            trees={'/protected-static': []})

    def write(self, path, raw, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)

    def check_unit_delta_rejects_mount_user_or_other_changes(self):
        self.rollout.checked(self.manifest, self.stage)
        unit = self.stage / 'candidate/native/desktop.service'
        original = unit.read_bytes()
        for old, new in ((b'User=root', b'User=someone'),
                         (b'src=/existing', b'src=/additional'),
                         (b'--read-only', b'--privileged')):
            with self.subTest(change=new):
                unit.write_bytes(original.replace(old, new))
                with self.assertRaisesRegex(ValueError, 'image_only_delta'):
                    self.rollout.checked(self.manifest, self.stage)
        unit.write_bytes(original)

    def check_exact_scope_runtime_pin_and_other_image_sources_cannot_expand(self):
        for changes in (dict(nativeSQLiteVersion='3.7.17'), dict(businessWrites=True),
                        dict(nativeUnits=['fs-hermes-fc.service'])):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'exact_rollout'):
                self.rollout.checked(dict(self.manifest, **changes), self.stage)
        changed = copy.deepcopy(self.manifest)
        changed['nativeImageSources']['/opt/hermes/reviewed_skills.py'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'only_native_entry'):
            self.rollout.checked(changed, self.stage)


class ManifestRules(ManifestFixture, unittest.TestCase):
    def test_unit_delta_rejects_mount_user_or_other_changes(self):
        self.check_unit_delta_rejects_mount_user_or_other_changes()

    def test_exact_scope_runtime_pin_and_other_image_sources_cannot_expand(self):
        self.check_exact_scope_runtime_pin_and_other_image_sources_cannot_expand()


@unittest.skipUnless(fcntl is not None, 'real Linux flock required')
class ComposedRollout(ManifestFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.base = load('frozen_admission_rollout_publisher', ROOT /
                         'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py')
        self.native = load('original_admission_native_lifecycle', ROOT /
                           'releases/fs-dashboard/knowledge-layering-20261023/deploy/native_release.py')
        self.concurrent = load('composed_admission_concurrent', DEPLOY / 'concurrent_release.py')
        self.concurrent.SCOPE = self.rollout.SCOPE
        self.base.HERMES_HISTORY_SCOPE = self.rollout.SCOPE
        # Bind the exact three-file adapter while retaining frozen validation.
        self.base.HERMES_HISTORY_TARGETS = dict(self.rollout.TARGETS)
        self.base.expected_files = lambda value: set(self.rollout.TARGETS)
        self.base.target_for = lambda name: self.rollout.TARGETS[name]
        self.events = []
        self.first_stop = True
        self.current_image = self.before
        self.fail_start_once = False
        self.fail_native_stop = False
        self.bad_image = False
        self.states = {u: self.state_value('active') for u in
                       (*self.concurrent.TIMERS, self.concurrent.RANGE, *self.rollout.UNITS,
                        'fs-hermes-fc.service')}
        self.manifest['runtimeRequired'].update({u: dict(ActiveState='active') for u in
                                                 (self.concurrent.RANGE, 'fs-hermes-fc.service')})
        self.manifest['imageId'] = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
        protected = set(self.base.HERMES_TARGETS.values()) | {
            '/opt/fs-exact-range-20261001/' + name for name in (
                'boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py',
                'fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py', 'fc_detail_config.json',
                'fc_deep_sources.py', 'summary_bridge.py')}
        protected |= {'/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
                      '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py'}
        for target in sorted(protected - set(self.rollout.TARGETS.values())):
            self.write(self.root / target.lstrip('/'), b'# protected fixture consumer\n')
            self.manifest['unchangedRequired'].append(dict(path=target, sha256=sha(b'# protected fixture consumer\n')))
        self.manifest['maintenanceBefore'] = {u: dict(ActiveState='active', UnitFileState='enabled')
                                             for u in (*self.concurrent.TIMERS, self.concurrent.RANGE)}
        self.manifest['nativeSQLiteVersion'] = sqlite3.sqlite_version
        tasks = self.root / 'var/lib/fs-hermes-fc/fs/tasks.sqlite3'
        self.make_db(tasks, 'CREATE TABLE requests(state TEXT)')
        self.native_db = self.native.native_database(self.root)
        self.make_db(self.native_db, 'CREATE TABLE session_turn_leases(conversation_id TEXT, holder TEXT, acquired_at REAL, expires_at REAL)')
        with closing(sqlite3.connect(self.native_db)) as db, db:
            db.execute('CREATE TABLE messages_fts_trigram_config(k PRIMARY KEY,v) WITHOUT ROWID')
        for name in (*self.concurrent.RELEASE_LOCKS, *self.concurrent.LEGACY_LOCKS,
                     self.concurrent.ADMISSION, '/fixture/web.lock', '/fixture/provider.lock'):
            self.write(self.root / name.lstrip('/'), b'', 0o600)
        for name in self.concurrent.QUERY_ROOTS:
            (self.root / name.lstrip('/')).mkdir(parents=True, exist_ok=True)
        # Keep the original retirement verifier; supply real isolated masks.
        for unit in ('dashboard-pipeline.service', 'dashboard-publish.service', 'dashboard-fallback.service'):
            path = self.root / 'etc/systemd/system' / unit
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to('/dev/null')

        @contextmanager
        def isolated_lock(manifest, root, name):
            with self.concurrent.lease(self.base, root, name):
                yield
        self.base.live_lock = lambda m, r: isolated_lock(m, r, '/fixture/web.lock')
        self.base.model_release_lock = lambda m, r: isolated_lock(m, r, '/fixture/provider.lock')
        # This is the OS-root metadata boundary only; preserve the original task,
        # runtime and all protected-consumer guards as well as all validation.
        host_guards = self.base.guards
        def fixture_guards(value, root, reader_stopped=False):
            self.base.hermes_quiescent(root)
            return host_guards(dict(value, scope='fixture-root-metadata-boundary'), root, reader_stopped)
        self.base.guards = fixture_guards
        outer = self

        class Control(self.concurrent.SystemControl):
            def __init__(self, root):
                self.before, self.paused = {}, []
            def state(self, unit):
                return dict(outer.states[unit])
            def idle(self):
                outer.events.append(('idle',))
            def restore(self, allow):
                outer.events.append(('restore', allow, outer.gates_held()))
                if allow:
                    outer.assertTrue(outer.gates_held(), 'restoration escaped the publication fence')
                super().restore(allow)

        # All real linked SQLite operations remain enabled. Only the manifest's
        # production-specific version constant is translated for this fixture.
        production_checked = self.rollout.checked
        def fixture_checked(value, stage):
            self.assertEqual(value['nativeSQLiteVersion'], sqlite3.sqlite_version)
            return production_checked(dict(value, nativeSQLiteVersion='3.53.4'), stage)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.rollout, 'checked', side_effect=fixture_checked))
        self.stack.enter_context(patch.object(subprocess, 'run', side_effect=self.command))
        self.stack.enter_context(patch.object(subprocess, 'check_output', side_effect=self.output))
        self.stack.enter_context(patch.object(self.rollout.urllib.request, 'urlopen',
                                               side_effect=lambda *a, **k: io.BytesIO(b'{"ok":true}')))
        self.original_apply, self.original_rollback = self.base.apply, self.base.rollback
        self.original_global_locks = self.base.locks
        self.original_rollback_journal = self.base.rollback_journal
        self.runtime_path = self.root / 'admission-runtime.json'
        default_control = 'default_control' in self._testMethodName
        if default_control:
            self.stack.enter_context(patch.object(self.concurrent, 'SystemControl', Control))
        self.base = self.rollout.compose(self.base, self.native, self.manifest,
                                         self.concurrent, control_factory=None if default_control else Control,
                                         runtime_path=self.runtime_path)
        self.release_id = 'nav-20261029T075000Z'

    @staticmethod
    def state_value(active):
        return dict(LoadState='loaded', ActiveState=active,
                    SubState='running' if active == 'active' else 'dead',
                    MainPID='100' if active == 'active' else '0', ControlPID='0', UnitFileState='enabled')

    def make_db(self, path, ddl):
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(ddl)

    def gates_held(self):
        for name in (self.concurrent.PUBLICATION, self.concurrent.READER_ENTRY, self.concurrent.ADMISSION):
            try:
                fd = os.open(self.root / name.lstrip('/'), os.O_RDONLY)
            except FileNotFoundError:
                return False
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    return False
                except BlockingIOError:
                    pass
            finally:
                os.close(fd)
        return True

    def unit_image(self):
        raw = (self.root / self.rollout.TARGETS['native/desktop.service'].lstrip('/')).read_bytes()
        return self.after if self.after.encode() in raw else self.before

    def command(self, args, **kwargs):
        self.events.append(('command', tuple(args), self.gates_held()))
        if args[:2] == ['systemctl', 'show']:
            unit = args[2]
            if unit.startswith('dashboard-'):
                value = dict(UnitFileState='disabled', ActiveState='inactive')
            else:
                fields = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == '-p']
                value = {k: self.states[unit][k] for k in fields}
            return subprocess.CompletedProcess(args, 0, '\n'.join(k + '=' + v for k, v in value.items()) + '\n')
        if args[:2] == ['systemctl', 'stop']:
            if self.first_stop:
                self.first_stop = False
                # Service control is reached only after both real DB fences.
                for database in (self.native_db, self.root / 'var/lib/fs-hermes-fc/fs/tasks.sqlite3'):
                    with closing(sqlite3.connect(database, timeout=0)) as db:
                        with self.assertRaises(sqlite3.OperationalError):
                            db.execute('BEGIN IMMEDIATE')
            if any(u in self.rollout.UNITS for u in args[2:]) and self.fail_native_stop:
                raise TimeoutError('injected native stop outcome unknown')
            for unit in args[2:]:
                self.states[unit] = self.state_value('inactive')
        elif args[:2] == ['systemctl', 'start']:
            unit = args[2]
            if unit == self.rollout.UNITS[0]:
                if self.fail_start_once and self.unit_image() == self.after:
                    self.fail_start_once = False
                    raise subprocess.CalledProcessError(1, args, 'injected new image start failure')
                self.current_image = self.unit_image()
            self.states[unit] = self.state_value('active')
        return subprocess.CompletedProcess(args, 0, '')

    def output(self, args, **kwargs):
        self.events.append(('output', tuple(args), self.gates_held()))
        if args[0] == 'systemctl':
            return 'ActiveState=' + self.states[args[2]]['ActiveState'] + '\n'
        if args[:2] == ['docker', 'inspect']:
            image = 'sha256:' + 'f' * 64 if self.bad_image else self.current_image
            return 'true ' + image if args[3] == '{{.State.Running}} {{.Image}}' else image
        if args[:2] == ['docker', 'run']:
            expected = (self.manifest['nativeImageBeforeSources'] if self.before in args
                        else self.manifest['nativeImageSources'])
            return ''.join(value + '  ' + name + '\n' for name, value in sorted(expected.items()))
        raise AssertionError('unexpected external read: ' + repr(args))

    def apply(self):
        raw = json.dumps(self.manifest).encode()
        return self.base.apply(self.manifest, self.stage, sha(raw), raw, self.release_id, self.root)

    def journal(self):
        backups = list((self.root / 'var/backups/fs-navigation-20261006').glob('nav-*'))
        self.assertEqual(len(backups), 1)
        return json.loads((backups[0] / 'journal.json').read_bytes())

    def assert_previous(self):
        for target, previous in self.previous.items():
            self.assertEqual((self.root / target.lstrip('/')).read_bytes(), previous)

    def assert_no_reopen(self):
        starts = [e[1][2] for e in self.events if e[0] == 'command' and e[1][:2] == ('systemctl', 'start')]
        self.assertNotIn(self.concurrent.RANGE, starts)
        self.assertFalse(set(starts) & set(self.concurrent.TIMERS))

    def test_native_lease_denies_before_any_stop_or_file_write(self):
        with closing(sqlite3.connect(self.native_db)) as db, db:
            db.execute("INSERT INTO session_turn_leases VALUES('old','unreconciled',0,0)")
        before_db = self.native_db.read_bytes()
        with self.assertRaisesRegex(ValueError, 'native_turn_active_or_unreconciled'):
            self.apply()
        self.assert_previous()
        self.assertEqual(self.native_db.read_bytes(), before_db)
        self.assertFalse(any(e[0] == 'command' and e[1][:2] in
                             (('systemctl', 'stop'), ('systemctl', 'start')) for e in self.events))
        self.assertFalse((self.root / 'var/backups/fs-navigation-20261006').exists())
        with closing(sqlite3.connect(self.native_db, timeout=0)) as db:
            db.execute('BEGIN IMMEDIATE')

    def test_success_default_control_retains_original_apply_and_one_journal_and_recovers_inside_gates(self):
        self.assertIs(self.base.apply, self.original_apply)
        self.assertIs(self.base.rollback, self.original_rollback)
        self.assertIs(self.base.locks, self.original_global_locks)
        result = self.apply()
        journal = self.journal()
        self.assertEqual(result['status'], 'applied-awaiting-actual-http-role-acceptance')
        self.assertEqual(journal['status'], result['status'])
        self.assertEqual(len(journal['files']), 3)
        self.assertTrue(all(row['written'] for row in journal['files']))
        self.assertEqual(self.current_image, self.after)
        self.assertTrue(all(self.states[u]['ActiveState'] == 'active'
                            for u in (*self.rollout.UNITS, self.concurrent.RANGE, *self.concurrent.TIMERS)))
        self.assertTrue(all(e[2] for e in self.events if e[0] == 'command' and
                            e[1][:2] in (('systemctl', 'stop'), ('systemctl', 'start'))))
        self.assertEqual([e[1] for e in self.events if e[0] == 'restore'], [True, True])
        self.assertEqual(json.loads(self.runtime_path.read_bytes())['status'], 'all_readers_loaded')
        for name in (self.concurrent.PUBLICATION, self.concurrent.READER_ENTRY):
            self.assertEqual((self.root / name.lstrip('/')).stat().st_size, 0)
        # A duplicate ID cannot activate or replace the original journal.
        before = copy.deepcopy(journal)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.journal(), before)

    def test_midwrite_failure_uses_original_cas_rollback_and_old_image(self):
        atomic = self.base.atomic
        injected = []
        target = self.root / self.rollout.TARGETS['source/controller.py'].lstrip('/')
        def fail_one(path, data, mode=0o644):
            if path == target and not injected:
                injected.append(True)
                raise OSError('injected exact target replacement failure')
            return atomic(path, data, mode)
        with patch.object(self.base, 'atomic', side_effect=fail_one):
            with self.assertRaisesRegex(OSError, 'exact target replacement'):
                self.apply()
        self.assert_previous()
        self.assertEqual(self.current_image, self.before)
        self.assertEqual(self.journal()['status'], 'rolled-back')
        self.assertEqual([e[1] for e in self.events if e[0] == 'restore'], [True])

    def test_new_image_start_failure_rolls_back_three_targets_and_loads_old_image(self):
        self.fail_start_once = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.apply()
        self.assert_previous()
        self.assertEqual(self.current_image, self.before)
        self.assertEqual(self.journal()['status'], 'rolled-back')
        self.assertEqual(self.states[self.concurrent.RANGE]['ActiveState'], 'active')

    def test_cas_drift_is_not_overwritten_and_does_not_activate_mixed_sources(self):
        atomic = self.base.atomic
        cache = self.root / self.rollout.TARGETS['source/cache_retention.py'].lstrip('/')
        controller = self.root / self.rollout.TARGETS['source/controller.py'].lstrip('/')
        other_writer = b'# another operation changed this target\n'
        injected = []
        def concurrent_change(path, data, mode=0o644):
            result = atomic(path, data, mode)
            if path == cache and sha(data) == next(r['sha256'] for r in self.manifest['files']
                                                  if r['candidate'] == 'source/cache_retention.py') and not injected:
                injected.append(True)
                controller.write_bytes(other_writer)
            return result
        with patch.object(self.base, 'atomic', side_effect=concurrent_change):
            with self.assertRaises(ValueError):
                self.apply()
        self.assertEqual(controller.read_bytes(), other_writer)
        for target, before in self.previous.items():
            if target != self.rollout.TARGETS['source/controller.py']:
                self.assertEqual((self.root / target.lstrip('/')).read_bytes(), before)
        self.assert_no_reopen()
        self.assertEqual(json.loads(self.runtime_path.read_bytes())['status'], 'unknown-needs-reconcile')

    def test_unknown_native_stop_does_not_restore_sources_or_blindly_start_readers(self):
        self.fail_native_stop = True
        with self.assertRaisesRegex(TimeoutError, 'stop outcome unknown'):
            self.apply()
        self.assertEqual(self.journal()['status'], 'unknown-needs-reconcile')
        self.assertEqual(json.loads(self.runtime_path.read_bytes())['status'], 'unknown-needs-reconcile')
        self.assert_no_reopen()
        self.assertEqual([e[1] for e in self.events if e[0] == 'restore'], [False])

    def test_wrong_image_during_recovery_never_reopens_range_or_timers(self):
        # Initial baseline is correct; image readback becomes bad only on start.
        command = self.command
        def wrong_after_start(args, **kwargs):
            result = command(args, **kwargs)
            if args[:3] == ['systemctl', 'start', self.rollout.UNITS[0]]:
                self.bad_image = True
            return result
        with patch.object(subprocess, 'run', side_effect=wrong_after_start):
            with self.assertRaisesRegex(ValueError, 'image_differs'):
                self.apply()
        self.assert_previous()
        self.assert_no_reopen()
        self.assertEqual(json.loads(self.runtime_path.read_bytes())['status'], 'unknown-needs-reconcile')
        self.assertEqual([e[1] for e in self.events if e[0] == 'restore'], [False])

    def test_default_control_health_unknown_keeps_source_timers_paused(self):
        with patch.object(self.rollout.urllib.request, 'urlopen', side_effect=OSError('isolated health unavailable')), \
                patch.object(self.rollout.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'range_reload_health_unknown'):
                self.apply()
        self.assertEqual(json.loads(self.runtime_path.read_bytes())['status'], 'unknown-needs-reconcile')
        starts = [e[1][2] for e in self.events if e[0] == 'command' and e[1][:2] == ('systemctl', 'start')]
        self.assertFalse(set(starts) & set(self.concurrent.TIMERS))
        self.assertTrue(all(self.states[u]['ActiveState'] == 'inactive' for u in self.concurrent.TIMERS))


class DerivedImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = load('test_admission_image_builder', DEPLOY / 'admission_image.py')
        self.context = self.root / 'context'
        self.context.mkdir()
        self.source = b'VALUE = 1\n'
        (self.context / 'Dockerfile').write_bytes(self.image.DOCKERFILE)
        (self.context / 'fs_native_entry.py').write_bytes(self.source)
        self.state = self.root / 'build.json'
        self.after = 'sha256:' + 'b' * 64
        self.expected = dict(self.image.BEFORE_SOURCES)
        self.expected[self.image.ENTRY] = sha(self.source)
        self.child_layers = ['original-layer', 'only-copy-layer']
        self.child_user = '"runtime-user"'
        self.runs = []

    def read(self, template, image):
        if template == '{{.Id}}':
            return self.image.BEFORE if image in (self.image.BEFORE, self.image.BASE_TAG) else self.after
        if template == '{{json .RootFS.Layers}}':
            return json.dumps(['original-layer'] if image == self.image.BEFORE else self.child_layers)
        if template == '{{json .Config.User}}':
            return '"runtime-user"' if image == self.image.BEFORE else self.child_user
        raise AssertionError(template)

    def build(self):
        def command(args, **kwargs):
            self.runs.append(args)
            if args[:3] == ['docker', 'image', 'inspect']:
                return subprocess.CompletedProcess(args, 1, '', 'Error: No such image: fixture')
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(self.image, 'read', side_effect=self.read), \
                patch.object(self.image, 'sources', side_effect=lambda image:
                             self.image.BEFORE_SOURCES if image == self.image.BEFORE else self.expected), \
                patch.object(self.image.subprocess, 'run', side_effect=command):
            return self.image.build(self.context, self.state, 'a' * 40, sha(self.source))

    def test_only_copy_layer_preserves_user_and_base_layers_without_activation(self):
        result = self.build()
        self.assertEqual(result['status'], 'built_verified_not_activated')
        self.assertEqual(result['child_layers'], self.child_layers)
        self.assertEqual(result['runtime_user'], '"runtime-user"')
        build = next(args for args in self.runs if args[:2] == ['docker', 'build'])
        self.assertEqual(build[:4], ['docker', 'build', '--network', 'none'])
        self.assertIn('--pull=false', build)
        self.assertEqual(self.image.DOCKERFILE.count(b'COPY '), 1)
        self.assertNotIn(b'RUN ', self.image.DOCKERFILE)
        self.assertFalse(any(args[0] == 'systemctl' for args in self.runs))

    def test_changed_user_or_extra_layer_preserves_unknown_operation_and_never_replays(self):
        self.child_user = '"root"'
        with self.assertRaisesRegex(ValueError, 'derived_image_readback_differs'):
            self.build()
        first = self.state.read_bytes()
        self.assertEqual(json.loads(first)['status'], 'unknown-needs-reconcile')
        count = len(self.runs)
        with self.assertRaisesRegex(ValueError, 'reconcile_original_operation'):
            self.build()
        self.assertEqual(len(self.runs), count)
        self.assertEqual(self.state.read_bytes(), first)

    def test_extra_or_replaced_base_layers_are_refused(self):
        for layers in (['replaced', 'only-copy-layer'], ['original-layer', 'extra', 'copy']):
            with self.subTest(layers=layers):
                if self.state.exists():
                    self.state.unlink()
                self.child_layers = layers
                with self.assertRaisesRegex(ValueError, 'derived_image_readback_differs'):
                    self.build()
                self.assertEqual(json.loads(self.state.read_bytes())['status'], 'unknown-needs-reconcile')


if __name__ == '__main__':
    unittest.main()
