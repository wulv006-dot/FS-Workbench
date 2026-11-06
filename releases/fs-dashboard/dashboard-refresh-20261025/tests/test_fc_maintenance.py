"""FC maintenance over the frozen CAS engine; no live service is controlled.

Real temporary files, journal, flock and SQLite admission are retained. Only
systemd, HTTP and the host-root metadata boundary are simulated. This proves
controlled stop ordering, not graceful completion of already running reads.
"""
from contextlib import ExitStack, closing, contextmanager
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_admission_rollout import DEPLOY, ROOT, fcntl, load, sha


class RangeStopEvidence(unittest.TestCase):
    """Exercise the real stop verifier without a real systemd daemon."""
    def setUp(self):
        self.helper = load('isolated_fc_stop_evidence', DEPLOY / 'fc_maintenance.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.group = Path(self.tmp.name) / 'range.service'
        self.group.mkdir()
        (self.group / 'cgroup.procs').write_text('')
        self.control = object.__new__(self.helper.RangeControl)
        self.control.group = self.group
        self.control.before = dict(UnitFileState='enabled', KillMode='control-group',
            SendSIGKILL='yes', TimeoutStopUSec='1min 30s')
        self.state = dict(self.control.before, LoadState='loaded', ActiveState='inactive',
            MainPID='0', ControlPID='0', Job='', TriggeredBy='', Triggers='')
        self.control.state = lambda: dict(self.state)

    def test_stop_requires_both_zero_pids_inactive_and_unchanged_kill_policy(self):
        self.control.stopped()
        for key, value in (('MainPID', '41'), ('ControlPID', '42'),
                           ('ActiveState', 'deactivating'), ('KillMode', 'process'),
                           ('SendSIGKILL', 'no'), ('UnitFileState', 'disabled'),
                           ('TimeoutStopUSec', 'infinity')):
            with self.subTest(key=key):
                before = self.state[key]
                self.state[key] = value
                with self.assertRaisesRegex(ValueError, 'stop_not_confirmed'):
                    self.control.stopped()
                self.state[key] = before

    def test_zero_mainpid_does_not_hide_a_surviving_child(self):
        child = self.group / 'child'
        child.mkdir()
        (child / 'cgroup.procs').write_text('119\n')
        with self.assertRaisesRegex(ValueError, 'cgroup_not_empty'):
            self.control.stopped()
        (child / 'cgroup.procs').write_text('')
        self.control.stopped()

    def test_pending_job_or_automatic_trigger_blocks_stop_confirmation(self):
        for key, value in (('Job', '123'), ('TriggeredBy', 'range.socket'), ('Triggers', 'range.path')):
            with self.subTest(key=key):
                self.state[key] = value
                with self.assertRaisesRegex(ValueError, 'job_pending|automatic_trigger'):
                    self.control.stopped()
                self.state[key] = ''

    def test_stop_releases_database_only_after_verified_empty_group(self):
        from unittest.mock import Mock
        fence = Mock()
        with patch.object(self.helper.subprocess, 'run') as run:
            self.control.quiesce(fence)
        run.assert_called_once_with(['systemctl', 'stop', self.helper.RANGE], check=True, timeout=110)
        fence.unlock_database.assert_called_once_with()
        fence.reset_mock()
        (self.group / 'cgroup.procs').write_text('119\n')
        with patch.object(self.helper.subprocess, 'run'), self.assertRaisesRegex(ValueError, 'cgroup_not_empty'):
            self.control.quiesce(fence)
        fence.unlock_database.assert_not_called()

    def test_failed_systemd_stop_never_unlocks_database(self):
        from unittest.mock import Mock
        fence = Mock()
        with patch.object(self.helper.subprocess, 'run', side_effect=TimeoutError('stop timed out')):
            with self.assertRaisesRegex(TimeoutError, 'stop timed out'):
                self.control.quiesce(fence)
        fence.unlock_database.assert_not_called()

    def test_pending_stop_job_cannot_claim_unchanged_recovery(self):
        self.state.update(ActiveState='active', MainPID='119', Job='123')
        with patch.object(self.helper.subprocess, 'run') as run, patch.object(self.control, 'healthy') as healthy:
            with self.assertRaisesRegex(ValueError, 'job_pending_or_unknown'):
                self.control.restore_unchanged()
        run.assert_not_called()
        healthy.assert_not_called()

    def test_unchanged_inactive_unit_is_started_before_health(self):
        events = []
        def start(args, **kwargs):
            events.append(tuple(args))
            self.state.update(ActiveState='active', MainPID='119', SubState='running')
        with patch.object(self.helper.subprocess, 'run', side_effect=start), patch.object(self.control, 'healthy', side_effect=lambda: events.append('health')):
            self.control.restore_unchanged()
        self.assertEqual(events, [('systemctl', 'start', self.helper.RANGE), 'health'])

    def test_recovery_can_verify_an_already_stopped_unit_without_starting_it(self):
        self.control.allow_stopped = True
        self.state.update(SubState='dead', ControlGroup='')
        expected = {key: self.state[key] for key in
                    ('UnitFileState', 'KillMode', 'SendSIGKILL', 'TimeoutStopUSec')}
        expected['ActiveState'] = 'active'
        manifest = {'maintenanceBefore': {self.helper.RANGE: expected},
                    'runtimeRequired': {self.helper.RANGE: {'ActiveState': 'active'}}}
        with patch.object(Path, 'is_file', lambda p: p == Path('/sys/fs/cgroup/systemd/cgroup.procs')):
            self.control.remember(manifest)
        self.assertEqual(self.control.before['ActiveState'], 'inactive')
        with patch.object(self.helper.subprocess, 'run') as run:
            self.control.restore_unchanged()
        run.assert_not_called()


@unittest.skipUnless(fcntl is not None, 'real Linux flock required')
class FCMaintenanceCAS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.stage = self.root / 'stage'
        self.helper = load('isolated_fc_maintenance', DEPLOY / 'fc_maintenance.py')
        self.base = load('frozen_fc_maintenance_publisher', ROOT /
            'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py')
        self.base.HERMES_HISTORY_SCOPE = self.helper.SCOPE
        # Two exact fixtures exercise both an existing asset and Python module.
        # The real payload's complete target set is checked by its adapter test.
        self.targets = {'source/business.js': '/fixture/live/business.js',
                        'source/fc_dashboard.py': '/fixture/live/fc_dashboard.py'}
        self.base.HERMES_HISTORY_TARGETS = dict(self.targets)
        self.base.expected_files = lambda value: set(self.targets)
        self.base.target_for = lambda name: self.targets[name]
        self.events = []
        self.active = True
        self.stop_error = None
        self.stop_unconfirmed = False
        self.fail_restart_once = False
        self.before = {}
        self.manifest = dict(schemaVersion=1, scope=self.helper.SCOPE,
            releaseReady=True, businessWrites=False, timersChanged=False,
            imageId='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',
            runtimeRequired={self.helper.RANGE: {'ActiveState': 'active'},
                             'fs-hermes-fc.service': {'ActiveState': 'active'}},
            maintenanceBefore={self.helper.RANGE: dict(ActiveState='active',
                UnitFileState='enabled', KillMode='control-group', SendSIGKILL='yes',
                TimeoutStopUSec='1min 30s')}, files=[], unchangedRequired=[])
        for name, target in self.targets.items():
            previous, candidate = b'# old ' + name.encode(), b'# new ' + name.encode()
            self.write(self.root / target.lstrip('/'), previous)
            self.write(self.stage / 'candidate' / name, candidate)
            self.before[target] = previous
            self.manifest['files'].append(dict(candidate=name, target=target,
                sha256=sha(candidate), beforeSha256=sha(previous), owner='0:0', mode='0o644'))
        protected = set(self.base.HERMES_TARGETS.values()) | {
            '/opt/fs-exact-range-20261001/' + name for name in (
                'boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py',
                'fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py',
                'fc_detail_config.json', 'fc_deep_sources.py', 'summary_bridge.py')}
        protected |= {'/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
            '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py'}
        for target in sorted(protected - set(self.targets.values())):
            self.write(self.root / target.lstrip('/'), b'# protected\n')
            self.manifest['unchangedRequired'].append(dict(path=target, sha256=sha(b'# protected\n')))
        database = self.root / 'var/lib/fs-hermes-fc/fs/tasks.sqlite3'
        database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('CREATE TABLE requests(state TEXT)')
        self.database = database
        for name in ('admission.lock',):
            self.write(database.parent / name, b'', 0o600)
        for name in ('web.lock', 'provider.lock'):
            self.write(self.root / 'fixture' / name, b'', 0o600)
        for unit in ('dashboard-pipeline.service', 'dashboard-publish.service', 'dashboard-fallback.service'):
            path = self.root / 'etc/systemd/system' / unit
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to('/dev/null')

        @contextmanager
        def lock(value, root, name):
            with (root / 'fixture' / name).open('r+b') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        self.base.live_lock = lambda value, root: lock(value, root, 'web.lock')
        self.base.model_release_lock = lambda value, root: lock(value, root, 'provider.lock')
        original_guards = self.base.guards
        def guards(value, root, reader_stopped=False):
            self.base.hermes_quiescent(root)
            # Adapt only root ownership checks, retaining runtime and protected CAS.
            return original_guards(dict(value, scope='fixture-root-metadata-boundary'), root, reader_stopped)
        self.base.guards = guards
        outer = self
        class Control:
            def __init__(self, root):
                outer.assertEqual(root, outer.root)
            def remember(self, manifest):
                outer.assertEqual(set(manifest['maintenanceBefore']), {outer.helper.RANGE})
                if not outer.active:
                    outer.assertTrue(getattr(self, 'allow_stopped', False), 'only rollback may enter with a stopped reader')
                outer.events.append(('remember',))
            def quiesce(self, fence):
                outer.assertTrue(outer.held('web.lock'))
                outer.assertTrue(outer.admission_held())
                outer.events.append(('quiesce', fence.modified, fence.confirmed))
                if outer.stop_error:
                    raise outer.stop_error
                fence.stop_then_unlock_database()
                self.stopped()
            def stopped(self):
                outer.events.append(('stopped',))
                if outer.active or outer.stop_unconfirmed:
                    raise ValueError('injected range stop or cgroup not confirmed')
            def restore_unchanged(self):
                outer.assertTrue(outer.admission_held())
                outer.events.append(('restore_unchanged',))
                outer.active = True
            def healthy(self):
                outer.events.append(('healthy',))
                if not outer.active:
                    raise ValueError('injected range unhealthy')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(subprocess, 'run', side_effect=self.command))
        self.stack.enter_context(patch.object(self.base.urllib.request, 'urlopen',
            side_effect=lambda *a, **k: io.BytesIO(b'{"ok":true}')))
        # Use the original range-only restart and health path. No P4 composition,
        # native image lifecycle or timers are needed by this FC-only fixture.
        restart = self.base.restart_for
        def range_restart(value, fence=None):
            return restart(dict(value, scope=self.base.DEEP_SCOPE), fence)
        self.base.restart_for = range_restart
        self.original_apply, self.original_rollback = self.base.apply, self.base.rollback
        self.original_locks = self.base.locks
        self.original_journal = self.base.journal_write
        self.helper.extend(self.base, self.helper.SCOPE, Control)
        atomic = self.base.atomic
        def observed_atomic(path, data, mode=0o644):
            if str(path) in {str(self.root / value.lstrip('/')) for value in self.targets.values()}:
                self.assertFalse(self.active, 'live target write happened before confirmed stop')
                self.assertFalse(self.stop_unconfirmed)
                self.assertTrue(self.held('web.lock'))
                self.assertTrue(self.admission_held())
                self.events.append(('replace', str(path), sha(data)))
            return atomic(path, data, mode)
        self.base.atomic = observed_atomic
        self.raw = json.dumps(self.manifest).encode()
        self.approval = sha(self.raw)
        self.release_id = 'nav-20261106T120000Z'

    def write(self, path, raw, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)

    def held(self, name):
        path = self.root / 'fixture' / name
        return self.file_locked(path)

    def file_locked(self, path):
        with path.open('rb') as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True

    def admission_held(self):
        return self.file_locked(self.database.parent / 'admission.lock')

    def command(self, args, **kwargs):
        self.events.append(('command', tuple(args)))
        if args[:2] == ['systemctl', 'show']:
            unit = args[2]
            if unit.startswith('dashboard-'):
                values = dict(UnitFileState='disabled', ActiveState='inactive')
            else:
                expected = {'ActiveState': 'active' if unit != self.helper.RANGE or self.active else 'inactive'}
                fields = [args[index + 1] for index, word in enumerate(args[:-1]) if word == '-p']
                values = {key: expected[key] for key in fields}
            return subprocess.CompletedProcess(args, 0, '\n'.join(key + '=' + value for key, value in values.items()))
        if args[:2] == ['systemctl', 'stop']:
            self.assertEqual(args[2:], [self.helper.RANGE])
            self.assertTrue(self.admission_held())
            self.active = False
        elif args[:2] == ['systemctl', 'restart']:
            self.assertEqual(args[2:], [self.helper.RANGE])
            self.active = True
            if self.fail_restart_once:
                self.fail_restart_once = False
                raise subprocess.CalledProcessError(1, args, 'injected range restart failure')
        elif args[:2] == ['systemctl', 'is-active']:
            self.assertEqual(args[-1], self.helper.RANGE)
            self.assertTrue(self.active)
        else:
            raise AssertionError('unexpected service control: ' + repr(args))
        return subprocess.CompletedProcess(args, 0, '')

    def apply(self):
        return self.base.apply(self.manifest, self.stage, self.approval, self.raw, self.release_id, self.root)

    def backup(self):
        return self.root / 'var/backups/fs-navigation-20261006' / self.release_id

    def journal(self):
        return json.loads((self.backup() / 'journal.json').read_bytes())

    def assert_previous(self):
        for target, previous in self.before.items():
            self.assertEqual((self.root / target.lstrip('/')).read_bytes(), previous)

    def test_apply_retains_frozen_engine_and_stops_before_first_replace(self):
        self.assertIs(self.base.apply, self.original_apply)
        self.assertIs(self.base.rollback.__wrapped__, self.original_rollback)
        self.assertIs(self.base.locks, self.original_locks)
        self.assertIs(self.base.journal_write, self.original_journal)
        expected = copy.deepcopy(self.manifest)
        result = self.apply()
        self.assertEqual(result['status'], 'applied-awaiting-actual-http-role-acceptance')
        self.assertEqual(self.journal()['manifest'], expected)
        self.assertEqual(self.manifest, expected, 'temporary inactive guards mutated approved manifest')
        self.assertTrue(self.active)
        self.assertEqual(len([event for event in self.events if event[0] == 'replace']), 2)
        self.assertTrue(all(row['written'] and row['intent'] for row in self.journal()['files']))

    def test_stop_failure_has_no_backup_or_target_write_and_restores_unchanged(self):
        self.stop_error = TimeoutError('injected stop failure')
        with self.assertRaisesRegex(TimeoutError, 'stop failure'):
            self.apply()
        self.assert_previous()
        self.assertFalse(self.backup().exists())
        self.assertFalse(any(event[0] == 'replace' for event in self.events))
        self.assertTrue(self.active)
        self.assertIn(('restore_unchanged',), self.events)

    def test_unconfirmed_pid_or_cgroup_prevents_first_write(self):
        self.stop_unconfirmed = True
        with self.assertRaisesRegex(ValueError, 'not confirmed'):
            self.apply()
        self.assert_previous()
        self.assertFalse(self.backup().exists())
        self.assertFalse(any(event[0] == 'replace' for event in self.events))

    def test_restart_failure_automatically_rolls_back_under_a_second_stop(self):
        self.fail_restart_once = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.apply()
        self.assert_previous()
        self.assertEqual(self.journal()['status'], 'rolled-back')
        self.assertTrue(self.active)
        self.assertTrue(any(event[0] == 'quiesce' and event[1] for event in self.events))

    def test_explicit_rollback_uses_same_stop_and_original_journal(self):
        self.apply()
        self.events.clear()
        result = self.base.rollback(self.backup(), self.approval, self.root)
        self.assertEqual(result['status'], 'rolled-back')
        self.assert_previous()
        self.assertTrue(self.active)
        self.assertTrue(any(event[0] == 'replace' for event in self.events))
        self.assertTrue(any(event[0] == 'quiesce' and event[1] for event in self.events))

    def test_recovery_rollback_enters_with_reader_already_stopped(self):
        self.apply()
        self.active = False
        self.events.clear()
        self.base.rollback(self.backup(), self.approval, self.root)
        self.assert_previous()
        self.assertTrue(self.active)
        self.assertEqual(self.journal()['status'], 'rolled-back')

    def test_rollback_cas_failure_preserves_drift_and_never_reopens_reader(self):
        self.apply()
        path = self.root / next(iter(self.targets.values())).lstrip('/')
        path.write_bytes(b'# concurrent unrelated write\n')
        self.events.clear()
        with self.assertRaisesRegex(ValueError, 'rollback .*drift'):
            self.base.rollback(self.backup(), self.approval, self.root)
        self.assertEqual(path.read_bytes(), b'# concurrent unrelated write\n')
        self.assertFalse(self.active)
        self.assertFalse(any(event[0] == 'command' and event[1][1] in ('start', 'restart') for event in self.events))
        self.assertFalse(any(event[0] == 'restore_unchanged' for event in self.events))

    def test_midwrite_failure_rolls_back_already_written_file(self):
        atomic = self.base.atomic
        target = self.root / self.targets['source/fc_dashboard.py'].lstrip('/')
        failed = []
        def fail_once(path, data, mode=0o644):
            if path == target and not failed:
                failed.append(True)
                raise OSError('injected target replacement failure')
            return atomic(path, data, mode)
        with patch.object(self.base, 'atomic', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'target replacement failure'):
                self.apply()
        self.assert_previous()
        self.assertEqual(self.journal()['status'], 'rolled-back')
        self.assertTrue(self.active)

    def test_failed_automatic_rollback_does_not_reopen_unconfirmed_code(self):
        atomic = self.base.atomic
        first = self.root / self.targets['source/business.js'].lstrip('/')
        second = self.root / self.targets['source/fc_dashboard.py'].lstrip('/')
        def fail_with_drift(path, data, mode=0o644):
            if path == second:
                first.write_bytes(b'# drift after first durable intent\n')
                raise OSError('injected second target failure')
            return atomic(path, data, mode)
        with patch.object(self.base, 'atomic', side_effect=fail_with_drift):
            with self.assertRaisesRegex(ValueError, 'rollback .*drift'):
                self.apply()
        self.assertEqual(first.read_bytes(), b'# drift after first durable intent\n')
        self.assertFalse(self.active)
        self.assertFalse(any(event[0] == 'command' and event[1][1] in ('start', 'restart') for event in self.events))
        self.assertNotEqual(self.journal()['status'], 'rolled-back')


if __name__ == '__main__':
    unittest.main()
