import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
import session_state as state
from patch_service import continuity, legacy_entry


def manager():
    return types.SimpleNamespace(lock=threading.RLock(), status='ready', token='synthetic-only',
        refresh_token='synthetic-refresh', last_refresh=time.monotonic(), login_attempts=1,
        config={'P2PAH_API_BASE': 'https://example.test'}, identity_ok=lambda *a, **k: True,
        state_now=lambda: 'synthetic-time')


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'session.json'
        self.path.parent.chmod(0o700)
        self.nofollow = patch.object(state.os, 'O_NOFOLLOW', getattr(os, 'O_NOFOLLOW', 0), create=True)
        self.nofollow.start(); self.addCleanup(self.nofollow.stop)

    def as_root(self, path):
        info = path.lstat()
        return types.SimpleNamespace(st_mode=info.st_mode, st_uid=0,
                                     st_nlink=info.st_nlink, st_size=info.st_size)

    def test_preserves_token_refresh_and_login_count_without_login(self):
        real = Path.lstat
        def root_info(path):
            info = real(path)
            mode = (info.st_mode & ~0o777) | (0o700 if stat.S_ISDIR(info.st_mode) else 0o600)
            return types.SimpleNamespace(st_mode=mode, st_uid=0,
                                         st_nlink=info.st_nlink, st_size=info.st_size)
        with patch.object(Path, 'lstat', root_info):
            old = manager()
            state.save(old, self.path)
            new = manager(); new.token = new.refresh_token = None
            self.assertTrue(state.restore(new, self.path))
            self.assertEqual((new.token, new.refresh_token, new.login_attempts),
                             (old.token, old.refresh_token, 1))
            value = json.loads(self.path.read_text()); value['created'] -= 1801
            self.path.write_text(json.dumps(value))
            with self.assertRaisesRegex(RuntimeError, 'session_state_invalid'):
                state.restore(new, self.path)

    def test_rejects_invalid_identity_and_unsafe_file(self):
        value = {'version': 1, 'created': time.time(), 'api_base': 'https://example.test',
                 'token': 'synthetic', 'refresh_token': None, 'refresh_age': 0, 'login_attempts': 1}
        self.path.write_text(json.dumps(value)); self.path.chmod(0o600)
        real = Path.lstat
        unsafe = False
        def root_info(path):
            info = real(path)
            mode = (info.st_mode & ~0o777) | (0o644 if unsafe else 0o600)
            return types.SimpleNamespace(st_mode=mode, st_uid=0, st_nlink=info.st_nlink, st_size=info.st_size)
        with patch.object(Path, 'lstat', root_info):
            item = manager(); item.identity_ok = lambda *a, **k: False
            with self.assertRaisesRegex(RuntimeError, 'identity_unverified'):
                state.restore(item, self.path)
            self.path.chmod(0o644)
            unsafe = True
            with self.assertRaisesRegex(RuntimeError, 'file_unsafe'):
                state.restore(item, self.path)

    def test_missing_checkpoint_does_not_invent_a_session(self):
        self.assertFalse(state.restore(manager(), self.path))
        self.assertFalse(state.safe_token('bad\nvalue'))

    def test_access_only_resume_does_not_force_login_at_twenty_minutes(self):
        source = '''class Manager:
    def __init__(self):
        self.customer_reads = PrivateReads(self)
    def _ensure_locked(self):
        if self.token and time.monotonic() - self.last_refresh >= 1200:
            return self.login()
        return self.identity_ok(self.token)
    def ensure(self):
        with self.lock:
            ok = True
            self.consecutive_failures = 0 if ok else self.consecutive_failures + 1
def main():
    manager = SessionManager(read_private_config())
'''
        scope = {'time': time}
        exec(continuity(source), scope)
        item = scope['Manager'].__new__(scope['Manager'])
        item.token, item.refresh_token, item.last_refresh = 'synthetic', None, 0
        item.identity_ok = lambda token: token == 'synthetic'
        item.login = lambda: self.fail('existing access token must not force a login')
        self.assertTrue(item._ensure_locked())

    def test_source_drift_and_legacy_read_lock_release(self):
        with self.assertRaisesRegex(RuntimeError, 'source_drift'):
            continuity('changed source')
        source = '''def collect_with_manager(manager, query, config, now=None):
    with manager.lock:
        if not manager.identity_ok(manager.token):
            return {'status':'not_available'}
        return collect_admin(lambda path, body:manager.request(path, data=body, token=manager.token), query, config, now)
'''
        item = manager()
        def request(path, **kw):
            self.assertFalse(item.lock._is_owned())
            self.assertEqual(kw['timeout'], 90)
            return 'complete'
        item.request = request
        scope = {'collect_admin': lambda read, *args: read('/admin/test', {})}
        exec(legacy_entry(source), scope)
        self.assertEqual(scope['collect_with_manager'](item, {}, {}), 'complete')
