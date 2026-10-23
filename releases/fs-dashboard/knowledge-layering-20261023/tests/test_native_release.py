import contextlib
import hashlib
import importlib.util
import json
import multiprocessing
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
spec = importlib.util.spec_from_file_location('native_release', DEPLOY / 'native_release.py')
native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)


def attempt_native_turn(path, queue):
    with contextlib.closing(sqlite3.connect(path, timeout=0)) as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT INTO session_turn_leases VALUES('parallel','test',0,0)")
            db.commit()
            queue.put('admitted')
        except sqlite3.OperationalError as error:
            queue.put(str(error))


class NativeRelease(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.before, self.after = 'sha256:' + 'a' * 64, 'sha256:' + 'b' * 64
        self.unit_before = ('[Service]\nExecStart=/usr/bin/docker run --mount old ' + self.before + '\n').encode()
        self.policy = {'contract': 'fs-knowledge-load-policy-v1', 'requests': {'old': {'release': 'keep'}}, 'native': {'enabled': False}}
        preserved = {k: v for k, v in self.policy.items() if k != 'native'}
        self.manifest = dict(schemaVersion=1, scope=native.SCOPE, releaseReady=False, imageId='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',
                             businessWrites=False, timersChanged=False, nativeUnits=list(native.UNITS),
                             nativeImageBefore=self.before, nativeImageAfter=self.after,
                             nativeSQLiteVersion=sqlite3.sqlite_version,
                             nativeImageSources={'/opt/hermes/tui_gateway/server.py': 'c' * 64, '/opt/hermes/fs_native_entry.py': 'd' * 64},
                             policyPreservedSha256=hashlib.sha256(json.dumps(preserved, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                             files=[])
        protected = self.root / 'protected-static'; protected.mkdir()
        info = protected.stat()
        self.manifest['nativeProtection'] = dict(metadata={'/protected-static': dict(kind='directory',
            uid=info.st_uid, gid=info.st_gid, mode=oct(stat.S_IMODE(info.st_mode)))}, trees={'/protected-static': []})
        for name, target in native.TARGETS.items():
            data = (self.unit_before.replace(self.before.encode(), self.after.encode()) if name.startswith('native/') else
                    json.dumps(self.policy).encode() if name.startswith('policy/') else
                    (ROOT / 'releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/__init__.py').read_bytes() if name.endswith('__init__.py') else b'candidate')
            p = self.root / 'candidate' / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
            self.manifest['files'].append(dict(candidate=name, target=target, sha256=hashlib.sha256(data).hexdigest(),
                beforeSha256=hashlib.sha256(self.unit_before).hexdigest() if name.startswith('native/') else None if name != 'plugin/__init__.py' else native.original_plugin_sha(data),
                owner='0:0', mode='0o644'))
        db = native.native_database(self.root); db.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(db)) as connection, connection:
            connection.execute('CREATE TABLE session_turn_leases(conversation_id TEXT PRIMARY KEY, holder TEXT NOT NULL, acquired_at REAL NOT NULL, expires_at REAL NOT NULL)')
            connection.execute("CREATE TABLE messages_fts_trigram_config(k PRIMARY KEY, v) WITHOUT ROWID")

    def fake_base(self):
        class Fence:
            def __init__(self, root): self.root, self.modified, self.confirmed = root, False, False
            def close(self): pass
        return types.SimpleNamespace(HermesAdmissionFence=Fence, no_target_link=lambda p: None,
            restart_for=Mock(side_effect=AssertionError('business restart must never be used')),
            rollback_journal=Mock(), journal_write=Mock(), rooted=lambda root, target: root / target.lstrip('/'))

    def test_new_or_deleted_skill_paths_cannot_pass_a_release_snapshot(self):
        native.verify_protection(self.manifest, self.root)
        skill = self.root / 'protected-static' / 'new-skill'; skill.mkdir()
        with self.assertRaisesRegex(ValueError, 'tree_drift'): native.verify_protection(self.manifest, self.root)
        skill.rmdir(); native.verify_protection(self.manifest, self.root)
        self.manifest['nativeProtection']['trees']['/protected-static'] = ['/protected-static/missing']
        with self.assertRaisesRegex(ValueError, 'tree_drift'): native.verify_protection(self.manifest, self.root)

    def test_metadata_or_missing_production_snapshot_denies_release(self):
        self.manifest['nativeProtection']['metadata']['/protected-static']['uid'] += 1
        with self.assertRaisesRegex(ValueError, 'metadata_drift'): native.verify_protection(self.manifest, self.root)
        self.manifest.update(releaseReady=True, nativeProtection={})
        with self.assertRaisesRegex(ValueError, 'complete_protection'): native.checked(self.manifest)

    def test_exact_native_scope_and_only_unit_image_substitution(self):
        native.checked(self.manifest, self.root)
        unit = self.root / 'candidate/native/desktop.service'
        unit.write_bytes(unit.read_bytes() + b'Environment=EXTRA=1\n')
        with self.assertRaisesRegex(ValueError, 'only_image_substitution'): native.checked(self.manifest, self.root)
        unit.write_bytes(self.unit_before.replace(self.before.encode(), self.after.encode()))
        plugin = self.root / 'candidate/plugin/__init__.py'; plugin.write_bytes(plugin.read_bytes() + b'EXTRA=True\n')
        with self.assertRaisesRegex(ValueError, 'original_tools_source_drift'): native.checked(self.manifest, self.root)

    def test_plugin_update_reuses_only_verified_constructor_and_preserves_other_three_targets(self):
        self.manifest.update(nativePluginOnly=True,nativeImageAfter=self.before,nativeImageSources=native.PATCHED_NATIVE_SOURCES)
        unit=self.root/'candidate/native/desktop.service';unit.write_bytes(self.unit_before)
        for row in self.manifest['files']:
            if row['candidate']!='plugin/knowledge.py':
                row['sha256']=row['beforeSha256']=hashlib.sha256((self.root/'candidate'/row['candidate']).read_bytes()).hexdigest()
            else:row['beforeSha256']='f'*64
        native.checked(self.manifest,self.root)
        self.manifest['nativeImageSources']=dict(native.PATCHED_NATIVE_SOURCES,**{'/opt/hermes/fs_native_entry.py':'f'*64})
        with self.assertRaisesRegex(ValueError,'exact_existing_runtime'):native.checked(self.manifest,self.root)
        self.manifest['nativeImageSources']=native.PATCHED_NATIVE_SOURCES
        policy=next(r for r in self.manifest['files'] if r['candidate'].startswith('policy/'))
        policy['beforeSha256']='f'*64
        with self.assertRaisesRegex(ValueError,'exact_existing_runtime'):native.checked(self.manifest,self.root)

    def test_unchanged_image_without_plugin_only_proof_still_refused(self):
        self.manifest['nativeImageAfter']=self.before
        with self.assertRaisesRegex(ValueError,'must_include_constructor_patch'):native.checked(self.manifest)

    def test_fc_or_additional_service_cannot_enter_scope(self):
        for field, value in [('nativeUnits', ['fs-hermes-fc.service']), ('businessWrites', True), ('timersChanged', True)]:
            changed = dict(self.manifest, **{field: value})
            with self.assertRaisesRegex(ValueError, 'exact_scope'): native.checked(changed)

    def test_requests_and_unknown_policy_fields_are_preserved(self):
        policy = self.root / 'candidate/policy/knowledge-load-policy.json'
        changed = dict(self.policy, requests={})
        policy.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'existing_requests_changed'): native.checked(self.manifest, self.root)

    def test_active_even_expired_lease_denies_without_clearing_evidence(self):
        with contextlib.closing(sqlite3.connect(native.native_database(self.root))) as db, db:
            db.execute("INSERT INTO session_turn_leases VALUES('old-unreconciled','test',0,0)")
        with self.assertRaisesRegex(ValueError, 'active_or_unreconciled'):
            native.acquire_native_database(self.fake_base(), self.root, sqlite3.sqlite_version)
        with contextlib.closing(sqlite3.connect(native.native_database(self.root))) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM session_turn_leases').fetchone()[0], 1)

    def test_database_fence_denies_parallel_admission_then_releases(self):
        base = self.fake_base(); native.install_native_scope(base, self.manifest)
        with base.hermes_admission_fence(self.manifest, self.root):
            with contextlib.closing(sqlite3.connect(native.native_database(self.root), timeout=0)) as connection:
                with self.assertRaises(sqlite3.OperationalError): connection.execute('BEGIN IMMEDIATE')
        with contextlib.closing(sqlite3.connect(native.native_database(self.root), timeout=0)) as connection:
            connection.execute('BEGIN IMMEDIATE')

    def test_real_format_schema_probe_and_exact_runtime_pin(self):
        native.probe_native_database(self.fake_base(), self.root, sqlite3.sqlite_version)
        with patch.object(native.sqlite3, 'connect') as connect:
            for version in (None, '3.7.17', '3.999.0'):
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'native_sqlite_'):
                    native.acquire_native_database(self.fake_base(), self.root, version)
            connect.assert_not_called()
        base = self.fake_base(); native.install_native_scope(base, self.manifest)
        with self.assertRaisesRegex(ValueError, 'approved_version_changed'):
            with base.hermes_admission_fence(dict(self.manifest, nativeSQLiteVersion='3.999.0'), self.root):
                self.fail('must not enter publication')

    def test_schema_failure_releases_database_and_outer_fence_without_entering(self):
        with contextlib.closing(sqlite3.connect(native.native_database(self.root))) as db, db:
            db.execute('DROP TABLE session_turn_leases')
        base = self.fake_base(); closed = Mock(); base.HermesAdmissionFence.close = lambda self: closed()
        native.install_native_scope(base, self.manifest)
        with self.assertRaisesRegex(sqlite3.OperationalError, 'no such table'):
            with base.hermes_admission_fence(self.manifest, self.root):
                self.fail('must not enter publication')
        closed.assert_called_once()
        with contextlib.closing(sqlite3.connect(native.native_database(self.root), timeout=0)) as db:
            db.execute('BEGIN IMMEDIATE')

    def test_malformed_schema_is_not_swallowed_or_repaired(self):
        path = native.native_database(self.root)
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute('PRAGMA writable_schema=ON')
            db.execute("UPDATE sqlite_master SET sql='CREATE TABLE broken ( invalid syntax WITHOUT)' WHERE name='messages_fts_trigram_config'")
        before = path.read_bytes()
        base = self.fake_base(); native.install_native_scope(base, self.manifest)
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'malformed database schema'):
            with base.hermes_admission_fence(self.manifest, self.root):
                self.fail('must not enter publication')
        self.assertEqual(path.read_bytes(), before)

    def test_cross_process_admission_and_stale_zero_rechecked_under_lock(self):
        context = multiprocessing.get_context('spawn')
        def attempt():
            queue = context.Queue()
            process = context.Process(target=attempt_native_turn, args=(str(native.native_database(self.root)), queue))
            process.start()
            try:
                result = queue.get(timeout=15)
                process.join(timeout=15)
                self.assertEqual(process.exitcode, 0)
                return result
            finally:
                if process.is_alive(): process.terminate(); process.join()
                queue.close(); queue.join_thread()
        base = self.fake_base(); native.install_native_scope(base, self.manifest)
        with base.hermes_admission_fence(self.manifest, self.root):
            self.assertIn('locked', attempt())
        # A prior zero observation cannot authorize a later publication.
        native.probe_native_database(base, self.root, sqlite3.sqlite_version)
        self.assertEqual(attempt(), 'admitted')
        with self.assertRaisesRegex(ValueError, 'active_or_unreconciled'):
            with base.hermes_admission_fence(self.manifest, self.root): self.fail('stale zero admitted')
        with contextlib.closing(sqlite3.connect(native.native_database(self.root))) as db:
            self.assertEqual(db.execute('SELECT holder FROM session_turn_leases').fetchall(), [('test',)])

    def test_only_native_units_and_no_business_stop_on_failure_cleanup(self):
        base = self.fake_base(); native.install_native_scope(base, self.manifest)
        unit = self.root / native.TARGETS['native/desktop.service'].lstrip('/'); unit.parent.mkdir(parents=True)
        unit.write_bytes(self.unit_before.replace(self.before.encode(), self.after.encode()))
        events = []
        def command(args, **kwargs):
            events.append(args)
        replies = iter(['ActiveState=inactive\n', 'ActiveState=inactive\n', 'true ' + self.after, self.after])
        def read(args, **kwargs):
            events.append(args)
            return next(replies)
        with patch.object(native.subprocess, 'run', side_effect=command) as run, patch.object(native.subprocess, 'check_output', side_effect=read) as output:
            with base.hermes_admission_fence(self.manifest, self.root) as fence:
                fence.modified = True
                base.restart_for(self.manifest, fence)
        commands = [c.args[0] for c in run.call_args_list]
        self.assertTrue(any(c[:2] == ['systemctl', 'start'] for c in commands))
        self.assertFalse(any('fs-business-range.service' in c or 'fs-hermes-fc.service' in c or 'nginx' in c for c in commands))
        starts = [c for c in commands if c[:2] == ['systemctl', 'start']]
        self.assertEqual(starts, [['systemctl', 'start', 'fs-hermes-desktop.service'], ['systemctl', 'start', 'hermes-dingtalk.service']])
        self.assertEqual(output.call_args_list[2].args[0][3], '{{.State.Running}} {{.Image}}')
        self.assertLess(events.index(output.call_args_list[2].args[0]), events.index(starts[1]))

    def test_gateway_waits_for_actual_container_and_pinned_image(self):
        missing = subprocess.CalledProcessError(1, ['docker', 'inspect'])
        with patch.object(native.subprocess, 'check_output', side_effect=[missing, 'false ' + self.after, 'true ' + self.after]) as read, patch.object(native.time, 'sleep') as sleep:
            native.wait_for_native_container(self.after)
        self.assertEqual(read.call_count, 3); self.assertEqual(sleep.call_count, 2)
        with patch.object(native.subprocess, 'check_output', return_value='true ' + self.before):
            with self.assertRaisesRegex(ValueError, 'image_differs'): native.wait_for_native_container(self.after)

    def test_plugin_only_restart_and_restore_accept_the_same_pinned_image(self):
        self.manifest.update(nativePluginOnly=True, nativeImageAfter=self.before)
        self.after = self.before
        self.test_only_native_units_and_no_business_stop_on_failure_cleanup()

    def test_container_wait_is_bounded_and_does_not_start_a_gateway_on_timeout(self):
        with patch.object(native.time, 'monotonic', side_effect=[0, 0, 31]), patch.object(native.time, 'sleep'), patch.object(native.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, ['docker'])):
            with self.assertRaisesRegex(TimeoutError, 'before_gateway_start'): native.wait_for_native_container(self.after)

    def test_unknown_restart_and_concurrent_lease_prevents_blind_restore(self):
        base = self.fake_base(); restore = base.rollback_journal
        native.install_native_scope(base, self.manifest)
        with base.hermes_admission_fence(self.manifest, self.root) as fence:
            fence.unlock_native()
            with contextlib.closing(sqlite3.connect(native.native_database(self.root))) as db, db: db.execute("INSERT INTO session_turn_leases VALUES('live','test',0,0)")
            journal = {'status': 'prepared'}
            with self.assertRaises(ValueError): base.rollback_journal(self.root, journal, self.root)
            self.assertEqual(journal['status'], 'unknown-needs-reconcile')
        restore.assert_not_called()

    def test_safe_restore_uses_original_journal_and_unknown_stop_is_preserved(self):
        base = self.fake_base(); restore = base.rollback_journal
        native.install_native_scope(base, self.manifest)
        with patch.object(native.subprocess, 'run'), patch.object(native.subprocess, 'check_output', return_value='ActiveState=inactive\n'):
            with base.hermes_admission_fence(self.manifest, self.root): base.rollback_journal(self.root, {}, self.root)
        restore.assert_called_once()
        with patch.object(native.subprocess, 'run', side_effect=TimeoutError('unknown stop')):
            with base.hermes_admission_fence(self.manifest, self.root):
                journal = {}
                with self.assertRaises(TimeoutError): base.rollback_journal(self.root, journal, self.root)
                self.assertEqual(journal['status'], 'unknown-needs-reconcile')
        self.assertEqual(restore.call_count, 1)

    def test_load_uses_frozen_existing_publisher_and_keeps_its_cas(self):
        # Exact existing adapters are loaded, not a replacement implementation of apply/rollback.
        root = Path(__file__).resolve().parents[4]
        (self.root / 'release_adapter_base.py').write_bytes((root / 'releases/fs-dashboard/user-analytics-20261022/deploy/release.py').read_bytes().replace(b'\r\n', b'\n'))
        (self.root / 'release_navigation_base.py').write_bytes((root / 'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py').read_bytes())
        (self.root / 'approved-manifest.json').write_text(json.dumps(self.manifest))
        with patch.object(native, 'HERE', self.root): base = native.load_base()
        self.assertEqual(base.apply.__module__, 'frozen_hermes_v2_publisher')
        self.assertEqual(base.target_for('native/desktop.service'), native.TARGETS['native/desktop.service'])
        with self.assertRaisesRegex(ValueError, 'releaseReady=false'):
            base.apply(self.manifest, self.root, '0' * 64, b'', 'nav-20261023T000000Z', self.root)

    def test_existing_publisher_midwrite_failure_restores_exact_prevalues_and_keeps_original_id(self):
        root = Path(__file__).resolve().parents[4]
        for name, source in [('release_adapter_base.py', 'user-analytics-20261022/deploy/release.py'),
                             ('release_navigation_base.py', 'channel-effects-20261021/deploy/release_navigation_base.py')]:
            data = (root / 'releases/fs-dashboard' / source).read_bytes()
            (self.root / name).write_bytes(data.replace(b'\r\n', b'\n') if name == 'release_adapter_base.py' else data)
        previous = {}
        for row in self.manifest['files']:
            if row['candidate'] == 'plugin/knowledge.py': continue
            data = self.unit_before if row['candidate'].startswith('native/') else (
                json.dumps(self.policy).encode() if row['candidate'].startswith('policy/') else
                (self.root / 'candidate/plugin/__init__.py').read_bytes().replace(
                    b'    from .knowledge import register as register_knowledge\n    register_knowledge(ctx)\n', b''))
            path = self.root / row['target'].lstrip('/'); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            row['beforeSha256'] = hashlib.sha256(data).hexdigest(); previous[row['target']] = data
        (self.root / 'approved-manifest.json').write_text(json.dumps(self.manifest))
        with patch.object(native, 'HERE', self.root): peek = native.load_base()
        required = set(peek.HERMES_TARGETS.values()) | {'/opt/fs-exact-range-20261001/' + name for name in
            ('boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py', 'fc_detail.py', 'fc_detail_model.py',
             'fc_detail_reader.py', 'fc_detail_config.json', 'fc_deep_sources.py', 'summary_bridge.py')}
        required |= {'/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
                     '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py'}
        required -= set(native.TARGETS.values())
        for target in required:
            path = self.root / target.lstrip('/'); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'protected')
        self.manifest.update(releaseReady=True, runtimeRequired={name: {'ActiveState': 'active'} for name in
            ('fs-business-range.service', 'fs-hermes-fc.service')}, unchangedRequired=[
                {'path': target, 'sha256': hashlib.sha256(b'protected').hexdigest()} for target in sorted(required)])
        raw = json.dumps(self.manifest).encode(); (self.root / 'approved-manifest.json').write_bytes(raw)
        with patch.object(native, 'HERE', self.root), patch.object(native, 'install_native_scope', side_effect=lambda b, a: b):
            base = native.load_base()
        class TaskFence:
            def __init__(self, path): self.root, self.modified, self.confirmed = path, False, False
            def close(self): pass
        base.HermesAdmissionFence = TaskFence
        # Exercise the original journal/CAS engine; only OS/service boundaries are injected.
        native.install_native_scope(base, self.manifest)
        base.locks = lambda *a: contextlib.nullcontext(); base.live_lock = lambda *a: contextlib.nullcontext()
        base.model_release_lock = lambda *a: contextlib.nullcontext(); base.retirement = lambda *a: None
        base.directory_sync = lambda *a: None
        base.guards = lambda manifest, path, **kw: [self.assertEqual(base.digest(base.rooted(path, r['path'])), r['sha256']) for r in manifest['unchangedRequired']]
        original_atomic = base.atomic; injected = []
        def atomic(path, data, mode=0o644):
            if path == self.root / native.TARGETS['plugin/knowledge.py'].lstrip('/') and not injected:
                injected.append(True); raise OSError('injected_after_prior_atomic_write')
            return original_atomic(path, data, mode)
        base.atomic = atomic
        def output(command, **kwargs):
            if command[0] == 'systemctl': return 'ActiveState=inactive\n'
            if command[:2] == ['docker', 'inspect']:
                unit = (self.root / native.TARGETS['native/desktop.service'].lstrip('/')).read_bytes()
                image = self.after if self.after.encode() in unit else self.before
                return 'true ' + image if command[3] == '{{.State.Running}} {{.Image}}' else image
            return ''.join(sha + '  ' + path + '\n' for path, sha in self.manifest['nativeImageSources'].items())
        release_id = 'nav-20261023T000000Z'
        with patch.object(native.subprocess, 'run') as calls, patch.object(native.subprocess, 'check_output', side_effect=output):
            with self.assertRaisesRegex(OSError, 'injected_after_prior_atomic_write'):
                base.apply(self.manifest, self.root, hashlib.sha256(raw).hexdigest(), raw, release_id, self.root)
            for target, expected in previous.items(): self.assertEqual((self.root / target.lstrip('/')).read_bytes(), expected)
            self.assertFalse((self.root / native.TARGETS['plugin/knowledge.py'].lstrip('/')).exists())
            backup = self.root / 'var/backups/fs-navigation-20261006' / release_id
            self.assertEqual(json.loads((backup / 'journal.json').read_bytes())['status'], 'rolled-back')
            self.assertEqual((backup / 'files/plugin/__init__.py').read_bytes(), previous[native.TARGETS['plugin/__init__.py']])
            with self.assertRaisesRegex(ValueError, 'release id already used'):
                base.apply(self.manifest, self.root, hashlib.sha256(raw).hexdigest(), raw, release_id, self.root)
            self.assertFalse(any('fs-business-range.service' in c.args[0] or 'fs-hermes-fc.service' in c.args[0] for c in calls.call_args_list))


if __name__ == '__main__': unittest.main()
