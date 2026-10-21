"""Server-only, narrow FC patch with protected backup and compare-before-replace."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path('/opt/fc27-cloud-browser')
PREFIX = '''
import sys as _order_sys
from pathlib import Path as _OrderPath
for _order_root in ('/opt/fs-order-session', '/opt/fc27-collector', '/opt/madden-workbench', '/srv'):
    if _OrderPath(_order_root, 'fs_order_client.py').is_file():
        _order_sys.path.insert(0, _order_root)
        break
import fs_order_client as _global_order
'''


def prefix(text):
    tree = ast.parse(text)
    futures = [n.end_lineno for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == '__future__']
    position = max(futures, default=tree.body[0].end_lineno if isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) else 0)
    lines = text.splitlines(keepends=True)
    lines.insert(position, PREFIX)
    return ''.join(lines)


def function(text, name, replacement, cls=None):
    tree = ast.parse(text)
    body = next(n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls) if cls else tree.body
    node = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = text.splitlines(keepends=True)
    indent = ' ' * node.col_offset
    lines[node.lineno-1:node.end_lineno] = [indent + l + '\n' for l in replacement.strip().splitlines()]
    return ''.join(lines)


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('source_shape_changed')
    return text.replace(old, new, 1)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def publish(changes, operation):
    backup = Path('/var/backups') / operation
    backup.mkdir(mode=0o700, exist_ok=False)
    prepared = []
    for path, text in changes.items():
        path = Path(path)
        original = path.read_bytes()
        if path.suffix == '.py':
            compile(text, str(path), 'exec')
        elif path.suffix == '.sh':
            subprocess.run(['sh', '-n'], input=text, text=True, check=True)
        target = backup / str(path).lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(path, target)
        prepared.append((path, original, text.encode()))
    records = []
    for path, original, updated in prepared:
        if path.read_bytes() != original:
            raise RuntimeError('concurrent_source_change')
        staging = path.with_name('.' + path.name + '.' + operation)
        with staging.open('xb') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(path, staging)
        stat = path.stat()
        os.chown(staging, stat.st_uid, stat.st_gid)
        if path.read_bytes() != original:
            raise RuntimeError('concurrent_source_change')
        os.replace(staging, path)
        assert path.read_bytes() == updated
        records.append({'path': str(path), 'before': digest(original), 'after': digest(updated)})
    (backup / 'receipt.json').write_text(json.dumps(records, indent=2))
    print(json.dumps({'operation': operation, 'files': records}))


def fc_changes():
    changes = {}
    path = ROOT / 'p2pah_browser_login.py'
    text = prefix(path.read_text())
    text = function(text, 'login', '''def login(page, config=None):
    _global_order.apply(page.context)
    page.goto(BASE, wait_until="domcontentloaded", timeout=35000)
    if 'login' in page.url.lower() or page.locator('input[type="password"]').count():
        raise ValueError('global_order_identity_unverified')
    return 'global_order'
''')
    changes[path] = text
    for name in ('price_writer.py', 'preview_backend.py', 'restore_price.py'):
        path = ROOT / name
        text = prefix(path.read_text())
        indent = '    ' if name == 'restore_price.py' else '        '
        old = indent + 'page = browser.contexts[0].new_page()'
        text = once(text, old, indent + '_global_order.apply(browser.contexts[0])\n' + old)
        changes[path] = text
    path = ROOT / 'collect_p2pah_cost.py'
    text = prefix(path.read_text())
    text = once(text, '    config = read_private_config()', '    config = {}')
    text = once(text, 'from p2pah_browser_login import login', '''def login(page, config=None):
    _global_order.apply(page.context)
    return 'global_order'
''')
    changes[path] = text
    for name in ('collect_p2pah_cost.sh', 'preview_backend.sh', 'execute_price.sh', 'restore_price.sh'):
        path = ROOT / name
        text = path.read_text()
        marker = '  --tmpfs /tmp:rw,noexec,nosuid,size=64m \\\n'
        mounts = ('  --mount type=bind,src=/opt/fs-order-session,dst=/opt/fs-order-session,readonly \\\n'
                  '  --mount type=bind,src=/run/fs-order-session,dst=/run/fs-order-session,readonly \\\n')
        text = once(text, marker, marker + mounts)
        if name == 'collect_p2pah_cost.sh':
            text = once(text, '  --mount type=bind,src=/etc/fc27-cloud/fc27.env,dst=/run/secrets/fc27.env,readonly \\\n', '')
        changes[path] = text
    return changes


if __name__ == '__main__':
    publish(fc_changes(), 'order-global-fc-20261021-v1')
