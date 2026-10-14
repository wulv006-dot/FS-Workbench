"""Portable exact-scope, lifecycle and historical-state preservation checks."""
import ast
from contextlib import closing
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('revision_ai_publisher', HERE / 'release_navigation.py')
publisher = importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)
SERVICE = 'ExecStart=/opt/python39/bin/python3 -B /opt/fs-exact-range-20261001/fs_cleanup.py --apply\n'
TIMER = 'OnCalendar=*-*-* 06:30:00 Asia/Shanghai\nPersistent=false\nUnit=fs-maintenance-cleanup.service\n'


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-revision-ai-publisher-')
        self.root = Path(self.temp.name)
        self.stage = self.root / 'stage'
        self.files = []
        for rel, target in publisher.AI_REVISION_TARGETS.items():
            path = self.stage / 'candidate' / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SERVICE if rel.endswith('.service') else TIMER if rel.endswith('.timer') else 'synthetic reviewed bytes')
            self.files.append(dict(candidate=rel, target=target, beforeSha256=None if rel in publisher.AI_REVISION_NEW else 'a' * 64, sha256=publisher.digest(path)))
        self.manifest = dict(schemaVersion=1, scope=publisher.AI_REVISION_SCOPE, files=self.files, releaseReady=False,
            runtimeRequired={'fs-business-range.service': {'ActiveState': 'active'}}, cleanupActivationDuringRelease=False,
            unchangedRequired=[dict(path='/var/www/dashboard/index.html', sha256='b' * 64)])
        for name in ('advisor/advisor.sqlite3', 'fc-daily/daily.sqlite3'):
            path = publisher.rooted(self.root, '/var/lib/fs-business-ranges/' + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,state TEXT)')
                db.execute("INSERT INTO jobs VALUES('historical','failed')"); db.commit()
        path = publisher.rooted(self.root, '/var/lib/fs-hermes-fc/fs/tasks.sqlite3')
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,state TEXT)'); db.commit()

    def tearDown(self):
        self.temp.cleanup()

    def inactive(self, *args, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout='ActiveState=inactive\nUnitFileState=disabled\nLoadState=loaded\nMainPID=0\n', stderr='')

    def test_twenty_targets_seven_new_and_account_scope_still_exact(self):
        self.assertEqual(20, len(publisher.validate(self.manifest, self.stage)))
        self.assertEqual(7, len(publisher.AI_REVISION_NEW))
        self.assertEqual(9, len(publisher.expected_files(dict(scope=publisher.ACCOUNT_SCOPE))))
        self.assertIn('/opt/fs-hermes-fc/assets/knowledge-derived.json', publisher.AI_REVISION_TARGETS.values())
        self.assertIn('/opt/fs-exact-range-20261001/fs_cleanup.py', publisher.AI_REVISION_TARGETS.values())
        self.assertNotIn('/opt/fs-exact-range-20261001/cache_guard.py', publisher.AI_REVISION_TARGETS.values())

    def test_exact_existing_baselines_and_no_unapproved_files(self):
        with self.assertRaises(ValueError): publisher.validate(dict(self.manifest, files=self.files[:-1]), self.stage)
        old = next(row for row in self.files if row['candidate'] not in publisher.AI_REVISION_NEW)
        old['beforeSha256'] = None
        with self.assertRaises(ValueError): publisher.validate(self.manifest, self.stage)

    def test_cleanup_activation_is_deferred_and_exact_apply_command_frozen(self):
        for value in (True, None):
            with self.assertRaises(ValueError): publisher.validate(dict(self.manifest, cleanupActivationDuringRelease=value), self.stage)
        row = next(row for row in self.files if row['candidate'].endswith('.service'))
        path = self.stage / 'candidate' / row['candidate']; path.write_text(SERVICE.replace(' --apply', ''))
        row['sha256'] = publisher.digest(path)
        with self.assertRaises(ValueError): publisher.validate(self.manifest, self.stage)

    def test_nonpersistent_idle_timer_required(self):
        row = next(row for row in self.files if row['candidate'].endswith('.timer'))
        path = self.stage / 'candidate' / row['candidate']; path.write_text(TIMER.replace('Persistent=false', 'Persistent=true'))
        row['sha256'] = publisher.digest(path)
        with self.assertRaises(ValueError): publisher.validate(self.manifest, self.stage)

    def test_old_pending_job_blocks_without_relabeling_or_deleting_history(self):
        path = publisher.rooted(self.root, '/var/lib/fs-business-ranges/advisor/advisor.sqlite3')
        with closing(sqlite3.connect(path)) as db:
            db.execute("INSERT INTO jobs VALUES('original-pending-id','pending')"); db.commit()
        with patch.object(publisher.subprocess, 'run', side_effect=self.inactive):
            with self.assertRaisesRegex(ValueError, 'original ID'):
                publisher.revision_ai_quiescent(self.root)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual([('historical', 'failed'), ('original-pending-id', 'pending')], db.execute('SELECT * FROM jobs ORDER BY id').fetchall())

    def test_hermes_running_unknown_and_boss_active_block(self):
        path = publisher.rooted(self.root, '/var/lib/fs-hermes-fc/fs/tasks.sqlite3')
        for state in ('RUNNING', 'DISPATCH_UNKNOWN', 'NEEDS_RECONCILE'):
            with closing(sqlite3.connect(path)) as db:
                db.execute('DELETE FROM requests'); db.execute('INSERT INTO requests VALUES(?,?)', ('original', state)); db.commit()
            with patch.object(publisher.subprocess, 'run', side_effect=self.inactive):
                with self.assertRaises(ValueError): publisher.revision_ai_quiescent(self.root)
        active = types.SimpleNamespace(returncode=0, stdout='ActiveState=active\nUnitFileState=static\nLoadState=loaded\nMainPID=2\n', stderr='')
        with patch.object(publisher.subprocess, 'run', return_value=active):
            with self.assertRaises(ValueError): publisher.revision_units_inactive(publisher.AI_REVISION_BOSS_UNITS)

    def test_existing_boss_enabled_inactive_is_preserved_cleanup_enabled_refused(self):
        enabled = types.SimpleNamespace(returncode=0, stdout='ActiveState=inactive\nUnitFileState=enabled\nLoadState=loaded\nMainPID=0\n', stderr='')
        with patch.object(publisher.subprocess, 'run', return_value=enabled):
            publisher.revision_units_inactive(publisher.AI_REVISION_BOSS_UNITS)
            with self.assertRaises(ValueError): publisher.revision_units_inactive(publisher.AI_REVISION_CLEAN_UNITS)

    def test_failed_boss_pid_zero_allowed_failed_pid_positive_refused_cleanup_failed_refused(self):
        failed = types.SimpleNamespace(returncode=0, stdout='ActiveState=failed\nUnitFileState=static\nLoadState=loaded\nMainPID=0\n', stderr='')
        with patch.object(publisher.subprocess, 'run', return_value=failed):
            publisher.revision_units_inactive(publisher.AI_REVISION_BOSS_UNITS)
            with self.assertRaises(ValueError): publisher.revision_units_inactive(publisher.AI_REVISION_CLEAN_UNITS)
        failed.stdout = failed.stdout.replace('MainPID=0', 'MainPID=23')
        with patch.object(publisher.subprocess, 'run', return_value=failed):
            with self.assertRaises(ValueError): publisher.revision_units_inactive(publisher.AI_REVISION_BOSS_UNITS)

    def test_only_range_restarted_no_cleanup_enable_start_or_worker_restart(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            return self.inactive()
        fence = types.SimpleNamespace(root=self.root, stop_then_unlock_database=lambda: commands.append(['fenced-stop-range']))
        with patch.object(publisher.subprocess, 'run', side_effect=run), patch.object(publisher.urllib.request, 'urlopen', side_effect=lambda *a, **kw: io.BytesIO(b'{"ok":true}')):
            publisher.restart_for(self.manifest, fence)
        self.assertIn(['systemctl', 'restart', 'fs-business-range.service'], commands)
        self.assertIn(['systemctl', 'daemon-reload'], commands)
        self.assertFalse(any('enable' in command or ('start' in command and any('cleanup' in part for part in command)) for command in commands))
        self.assertFalse(any('restart' in command and 'fs-hermes-fc.service' in command for command in commands))

    def test_existing_shared_locks_cas_fence_and_retirement_body_preserved(self):
        base = (HERE.parent / 'deploy/release_navigation.py').read_text(encoding='utf-8')
        source = (HERE / 'release_navigation.py').read_text(encoding='utf-8')
        old = {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(base).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        new = {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        for name in ('locks', 'atomic', 'retirement', 'rollback_credentials', 'rollback_journal', 'HermesAdmissionFence', 'hermes_quiescent', 'account_snapshot'):
            self.assertEqual(old[name], new[name])
        for function in ('model_release_lock', 'hermes_admission_fence', 'live_lock'):
            self.assertIn('AI_REVISION_SCOPE', ast.get_source_segment(source, next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == function)))


if __name__ == '__main__':
    unittest.main()
