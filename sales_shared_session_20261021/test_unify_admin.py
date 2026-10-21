import unittest
from unittest.mock import Mock
from unify_admin import transform


class Tests(unittest.TestCase):
    def test_class_consumers_preserve_contract_and_deny_direct_auth(self):
        for kind in ('mlb', 'sbc'):
            source = '''import urllib.parse
class AdminAuthError(Exception): pass
class AuthState:
    def __init__(self, *args): self.args = args
class Client:
    def clear_auth(self): self._token = None
    @property
    def authenticated(self): return bool(self._token)
    def login_with_ocr(self, username, password, ocr=None, *, keep=True, tries=3):
        raise AssertionError('old login')
    def login(self, username, password, captcha, captcha_id, *, google_code=''):
        raise AssertionError('old login')
    def _headers(self, *, auth):
        if auth and not self._token: raise AdminAuthError('missing')
        return self._token
    def _bytes(self, method, path, *, auth=True):
        if auth and not self._token: raise AdminAuthError('missing')
        return self._token
    def _request(self, method, path):
        raise AssertionError('unexpected network')
    def _json(self, method, path):
        raise AssertionError('unexpected network')
'''
            # The real modules have exactly one of these two login contracts.
            other = 'login' if kind == 'mlb' else 'login_with_ocr'
            import ast
            tree = ast.parse(source)
            cls = tree.body[-1]
            cls.body = [n for n in cls.body if n.name != other]
            namespace = {}
            exec(transform(ast.unparse(tree) + '\n', kind), namespace)
            token = Mock(return_value='synthetic-current')
            namespace['_fs_shared_admin_token'] = token
            client = namespace['Client']()
            state = (client.login_with_ocr('', '') if kind == 'mlb'
                     else client.login('', '', '', ''))
            self.assertEqual(state.args[0], 'synthetic-current')
            self.assertEqual(state.args[1], '')
            request = client._request if kind == 'mlb' else client._bytes
            with self.assertRaisesRegex(namespace['AdminAuthError'], 'FS_SHARED_AUTH_ONLY'):
                request('POST', '/admin/index/login')
            with self.assertRaisesRegex(namespace['AdminAuthError'], 'FS_SHARED_AUTH_ONLY'):
                request('POST', '/admin/index/loginGoogle')
            if kind == 'sbc':
                self.assertEqual(client.login('', '', '', '', google_code='synthetic').args[0], 'synthetic-current')
            namespace['_fs_shared_admin_token'] = Mock(side_effect=RuntimeError('no session'))
            with self.assertRaisesRegex(namespace['AdminAuthError'], 'FS_SHARED_SESSION_UNAVAILABLE'):
                if kind == 'mlb': client._headers(auth=True)
                else: client._bytes('GET', '/admin/index/index')
            self.assertIsNone(client._token)

    def test_dashboard_never_reads_old_cache_or_refreshes(self):
        source = '''import json
def do_login(cfg, allow_manual=True):
    raise AssertionError('login')
def ensure_token(cfg, no_login=False, allow_manual=True):
    raise AssertionError('refresh')
'''
        namespace = {}
        exec(transform(source, 'dashboard'), namespace)
        namespace['_fs_shared_admin_token'] = lambda: 'synthetic'
        self.assertEqual(namespace['do_login']({}), ('synthetic', None))
        self.assertEqual(namespace['ensure_token']({}), 'synthetic')

    def test_nba_no_local_token_or_credentials(self):
        source = '''import json
CRED = {'password': 'synthetic-old'}
def login():
    raise AssertionError('login')
def ensure_token():
    raise AssertionError('login')
def api(method, path, data=None, token=True):
    if token:
        tk = open('must-not-read').read()
        return tk
'''
        namespace = {}
        candidate = transform(source, 'nba')
        self.assertNotIn('synthetic-old', candidate)
        exec(candidate, namespace)
        namespace['_fs_shared_admin_token'] = lambda: 'synthetic'
        self.assertEqual(namespace['login'](), 'synthetic')
        self.assertTrue(namespace['ensure_token']())
        self.assertEqual(namespace['api']('GET', '/admin/index/index'), 'synthetic')
        with self.assertRaisesRegex(RuntimeError, 'FS_SHARED_AUTH_ONLY'):
            namespace['api']('POST', '/api/common/refreshToken')


if __name__ == '__main__':
    unittest.main()
