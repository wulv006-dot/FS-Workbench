"""Prepare a separate candidate from exact live bytes; never edit the input."""
import ast
import hashlib
from pathlib import Path

BASE_SHA = 'b3f5b93de88a9f38584ea14a96208bc315d9d75aea73e8b1571a7822c8bae231'


def patch(source):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits = []

    def replace(node, text):
        edits.append((node.lineno - 1, node.end_lineno, text + '\n'))

    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    cls, = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Session']
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    # Keep Order login/cookies and the surrounding source byte-for-byte.
    boot = functions['bootstrap']
    cookie_start, = [n for n in boot.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'ck' for t in n.targets)]
    tail = ''.join(lines[cookie_start.lineno - 1:boot.end_lineno]).rstrip('\r\n')
    replace(boot, '''def bootstrap(reuse: bool = True) -> Session:
    s = Session()
    token, _ = admin_token_from_service()
    if not token:
        s.close()
        raise RuntimeError('shared_admin_unavailable')
    s.token = token
    st = _load_state() if reuse else {}
''' + tail)
    replace(functions['admin_token_from_service'], '''def admin_token_from_service(timeout=8.0):
    from shared_admin import admin_token_from_service as read_shared
    return read_shared(timeout)''')
    replace(functions['admin_login'], '''def admin_login(*args, **kwargs):
    raise RuntimeError('sales_admin_login_disabled')''')
    # No Admin token survives on disk; the old file is not copied into this bundle.
    save = methods['save']
    state, = [n for n in ast.walk(save) if isinstance(n, ast.Dict)
              and any(isinstance(k, ast.Constant) and k.value == 'admin_token' for k in n.keys)]
    keys = [k.value for k in state.keys]
    if keys != ['admin_token', 'admin_at', 'order_cookies', 'order_at']:
        raise ValueError('unexpected_session_state_contract')
    state.keys = state.keys[2:]
    state.values = state.values[2:]
    replace(save, '    ' + ast.unparse(save).replace('\n', '\n    '))
    found = set()
    for n in tree.body:
        if not isinstance(n, ast.Assign) or len(n.targets) != 1:
            continue
        target = n.targets[0]
        if isinstance(target, ast.Name) and target.id in {'USER', 'PASSWORD'}:
            found.add(target.id)
            keys = [call.args[0].value for call in ast.walk(n.value)
                    if isinstance(call, ast.Call) and ast.unparse(call.func) == 'os.environ.get'
                    and call.args and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)]
            if not keys:
                raise ValueError('missing_credential_environment')
            replace(n, target.id + ' = ' + ' or '.join("os.environ.get(%r, '')" % k for k in keys))
    if found != {'USER', 'PASSWORD'}:
        raise ValueError('unexpected_credentials_contract')
    for n in tree.body:
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name) and n.test.left.id == '__name__':
            replace(n, "if __name__ == '__main__':\n    raise SystemExit('Use the collector entry; standalone auth probing is disabled')")
    order_login = functions['order_login']
    first = order_login.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        first = order_login.body[1]
    edits.append((first.lineno - 1, first.lineno - 1,
                  "    if not USER or not PASSWORD:\n"
                  "        raise RuntimeError('order_credentials_missing')\n"))
    for start, end, text in sorted(edits, reverse=True):
        lines[start:end] = [text]
    result = ''.join(lines)
    compile(result, 'p2pah_auth.py', 'exec')
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise SystemExit('baseline_changed: re-review current source; do not bypass SHA')
    candidate = patch(raw.decode('utf-8'))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'p2pah_auth.py').write_text(candidate, encoding='utf-8')
    (args.output / 'shared_admin.py').write_bytes(Path(__file__).with_name('shared_admin.py').read_bytes())
    print('candidate_ready; no input or service changed')


if __name__ == '__main__':
    main()
