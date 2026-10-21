"""Narrow source transforms for the inventoried Admin credential consumers."""
import ast

BASELINES = {
    '/opt/nba-reprice/backend/p2pah_api.py': 'ff2813767824273a7b2c0268ff63611188688e6d8ccd5836c974a2f6bc7db2e3',
    '/opt/mlb-admin-write/src/admin_api_client.py': '14b7ed16dd0bd5b806cf6e231d58fde5a973c37c850824ff89a4549aa6435a76',
    '/opt/fc27-pack-bundles/vendor/admin_api_client.py': '14b7ed16dd0bd5b806cf6e231d58fde5a973c37c850824ff89a4549aa6435a76',
    '/opt/fc27-sbc-tool/admin_client.py': '46675e93ba047d7493862a58a1153062fed30cf7456596bba37b1af7bfdf5bd6',
    '/opt/fc27-sbc-tool/webapp.py': '3279009ebf90bdbe0405bc1af3c12a8b5c73291a8cd0797e78285af5b2433b41',
    '/opt/dashboard-collect/p2pah_unified.py': '1232d1c461f1c69f05468433f7aefecceeac11340b95f264b35fb729cebdb6d1',
    '/opt/fc27-cloud-browser/p2pah_auth_probe.py': '40138c30b6a3afecbbef9b5155c02358839b1f5343e00b9252c0bccc5cc93733',
}

SHARED = '''
def _fs_shared_admin_token():
    import importlib.util
    spec = importlib.util.spec_from_file_location('fs_shared_admin', '/opt/fs-shared-session/shared_admin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token, _ = module.admin_token_from_service()
    if not token:
        raise RuntimeError('FS_SHARED_SESSION_UNAVAILABLE')
    return token
'''


def transform(source, kind):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits = []
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def body(node, text):
        first = node.body[0]
        indent = ' ' * first.col_offset
        edits.append((first.lineno - 1, node.end_lineno,
                      '\n'.join(indent + line if line else '' for line in text.splitlines()) + '\n'))

    def insert(node, text):
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            first = node.body[1]
        indent = ' ' * first.col_offset
        edits.append((first.lineno - 1, first.lineno - 1,
                      '\n'.join(indent + line if line else '' for line in text.splitlines()) + '\n'))

    if kind == 'nba':
        body(functions['login'], 'return _fs_shared_admin_token()')
        body(functions['ensure_token'], 'return bool(_fs_shared_admin_token())')
        api = functions['api']
        token_assign, = [n for n in ast.walk(api) if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'tk' for t in n.targets)]
        edits.append((token_assign.lineno - 1, token_assign.end_lineno,
                      ' ' * token_assign.col_offset + 'tk = _fs_shared_admin_token()\n'))
        insert(api, "if path in ('/admin/index/login', '/admin/index/loginGoogle', '/api/common/refreshToken'):\n    raise RuntimeError('FS_SHARED_AUTH_ONLY')")
        credentials, = [n for n in tree.body if isinstance(n, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == 'CRED' for t in n.targets)]
        edits.append((credentials.lineno - 1, credentials.end_lineno, 'CRED = {}\n'))
    elif kind in ('mlb', 'sbc'):
        login_name = 'login_with_ocr' if kind == 'mlb' else 'login'
        cls, = [n for n in tree.body if isinstance(n, ast.ClassDef)
                and any(isinstance(m, ast.FunctionDef) and m.name == login_name for m in n.body)]
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        login = methods['login_with_ocr' if kind == 'mlb' else 'login']
        body(login, "self.clear_auth()\ntry:\n    self._token = _fs_shared_admin_token()\nexcept RuntimeError:\n    raise AdminAuthError('FS_SHARED_SESSION_UNAVAILABLE') from None\n"
             + "self._refresh_token = ''\nreturn AuthState(self._token, ''" + (', {})' if kind == 'mlb' else ')'))
        if kind == 'sbc':
            body(methods['authenticated'], "try:\n    self._token = _fs_shared_admin_token()\nexcept RuntimeError:\n    self._token = None\nreturn bool(self._token)")
        boundary = methods['_headers' if kind == 'mlb' else '_bytes']
        # Existing authenticated checks and role/business validation remain in place.
        insert(boundary, "if auth:\n    try:\n        self._token = _fs_shared_admin_token()\n    except RuntimeError:\n        self._token = None\n        raise AdminAuthError('FS_SHARED_SESSION_UNAVAILABLE') from None")
        request = methods['_request' if kind == 'mlb' else '_bytes']
        insert(request, "if urllib.parse.urlsplit(path).path in ('/admin/index/login', '/admin/index/loginGoogle', '/api/common/refreshToken'):\n    raise AdminAuthError('FS_SHARED_AUTH_ONLY')")
    elif kind == 'dashboard':
        body(functions['do_login'], "return _fs_shared_admin_token(), None")
        body(functions['ensure_token'], "return _fs_shared_admin_token()")
    elif kind == 'probe':
        body(functions['main'], "raise SystemExit('Independent auth probe retired; use FS 8767 status')")
    elif kind == 'sbc_web':
        body(functions['_save_session'], 'return None')
        body(functions['_restore_session'], 'return False')
    else:
        raise ValueError('unknown_consumer')
    if kind not in ('probe', 'sbc_web'):
        last_import = max(n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
        edits.append((last_import, last_import, SHARED + '\n'))
    for start, end, text in sorted(edits, reverse=True):
        lines[start:end] = [text]
    candidate = ''.join(lines)
    compile(candidate, '<shared-admin-candidate>', 'exec')
    return candidate


def kind_for(path):
    if path.endswith('/fc27-sbc-tool/webapp.py'):
        return 'sbc_web'
    if path.endswith('p2pah_api.py'):
        return 'nba'
    if path.endswith('admin_api_client.py'):
        return 'mlb'
    if path.endswith('admin_client.py'):
        return 'sbc'
    if path.endswith('p2pah_unified.py'):
        return 'dashboard'
    return 'probe'
