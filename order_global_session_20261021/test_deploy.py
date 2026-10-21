import sys
import types
import unittest
from unittest.mock import patch
from deploy_fc import prefix, once
import deploy_fc_admin_consumer as deploy


COIN = '''"""Synthetic consumer."""
from __future__ import annotations
def check(identity):
    if not isinstance(identity, dict) or identity.get('adminInfo', {}).get('username') != 'chenchao':
        raise ValueError('coin_identity_invalid')
    return True
'''
PLAYER = '''from p2pah_session_service import SessionManager
def check(username):
    return username != "chenchao"
'''
CACHE = '''from p2pah_session_service import SessionManager
def check(username):
    return username == "chenchao"
'''
SHELL = '  --mount type=bind,src=/etc/fc27-cloud/fc27.env,dst=/run/secrets/fc27.env,readonly \\\n'


class DeploymentTests(unittest.TestCase):
    def test_real_import_regression_and_two_principals(self):
        def source(path, *args, **kwargs):
            return {'coin_all_sync_job.py': COIN, 'player_sync_job.py': PLAYER,
                    'clear_cache_after_write.py': CACHE}.get(path.name, SHELL)
        with patch('pathlib.Path.read_text', source):
            changes = deploy.changes()
        text = next(v for p, v in changes.items() if p.name == 'coin_all_sync_job.py')
        namespace = {}
        # Entry-point imports must succeed before /usr/local/bin is added by the caller.
        with patch.dict(sys.modules, {'p2pah_session_service': None}):
            exec(compile(text, 'synthetic_coin.py', 'exec'), namespace)
        fake = types.ModuleType('p2pah_session_service')
        fake.allowed_admin_usernames = lambda: ['wulv', 'chenchao']
        with patch.dict(sys.modules, {'p2pah_session_service': fake}):
            for account in ('wulv', 'chenchao'):
                self.assertTrue(namespace['check']({'adminInfo': {'username': account}}))
            with self.assertRaisesRegex(ValueError, 'coin_identity_invalid'):
                namespace['check']({'adminInfo': {'username': 'unapproved'}})
        for p, value in changes.items():
            if p.suffix == '.sh':
                self.assertIn('fc_shared_admin.py', value)
                self.assertNotIn('src=/etc/fc27-cloud/fc27.env', value)

    def test_future_import_preserved(self):
        compile(prefix('"""fixture"""\nfrom __future__ import annotations\nx=1\n'), 'fixture', 'exec')

    def test_drift_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'source_shape_changed'):
            once('changed source', 'expected source', 'replacement')


if __name__ == '__main__':
    unittest.main()
