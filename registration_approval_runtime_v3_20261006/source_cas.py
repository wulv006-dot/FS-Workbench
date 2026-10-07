"""Pure exact-source candidate construction. Does not read/write/deploy source paths.

Caller supplies bytes and an action-time expected SHA. No cached live SHA accepted
as a freshness claim. Output is reviewer material, not a deployment operation.
"""
import ast
import hashlib


def construct(source, expected_sha, kind, *, origin='https://47.85.224.112'):
    if hashlib.sha256(source).hexdigest() != expected_sha:
        raise ValueError('source CAS mismatch')
    text = source.decode('utf-8'); tree = ast.parse(text)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    servers = [n for n in ast.walk(main) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name) and n.value.func.id == 'ThreadingHTTPServer']
    if len(servers) != 1 or '_registration_boot_marker' in text:
        raise ValueError('unexpected listener topology/already patched')
    line = servers[0].lineno - 1
    lines = text.splitlines(keepends=True)
    indent = lines[line][:len(lines[line]) - len(lines[line].lstrip())]
    common = ["import sys as _registration_sys", "_registration_sys.path.insert(0, '/opt/auth-portal/registration_runtime')"]
    if kind == 'portal':
        boot = common + ['from portal_bridge import install as _registration_install',
            '_registration_install(_registration_sys.modules[__name__], ' + repr(origin) + ')']
    elif kind in ('taskboard', 'fc_gate'):
        boot = common + ["_registration_sys.path.insert(0, '/opt/fs-access-policy')",
            'import access_policy as _registration_policy',
            'from consumer_seams import install_' + ('taskboard' if kind == 'taskboard' else 'fc') + ' as _registration_install',
            '_registration_install(_registration_sys.modules[__name__], _registration_policy)']
        if kind == 'taskboard':
            before = 'role, registered = member_state(conn, user)'
            if text.count(before) != 1: raise ValueError('unexpected membership caller topology')
            text = text.replace(before, 'role, registered = _registration_member(conn, user, (self.headers.get("X-Auth-Role") or "").strip())')
            lines = text.splitlines(keepends=True)
        else:
            # Retired auth no longer needs startup writes to its legacy DB or janitor.
            for n in main.body:
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
                    expr = ast.unparse(n.value)
                    if expr in ('init_db()', 'purge_expired()') or expr.startswith('threading.Thread(target=janitor,'):
                        for number in range(n.lineno-1, n.end_lineno):
                            lines[number] = indent + 'pass  # independent FC auth retired\n'
    else: raise ValueError('unknown direct consumer')
    lines[line:line] = [indent + '_registration_boot_marker = True\n'] + [indent + code + '\n' for code in boot]
    output = ''.join(lines).encode()
    compile(output, '<reviewed-' + kind + '-candidate>', 'exec')
    return output
