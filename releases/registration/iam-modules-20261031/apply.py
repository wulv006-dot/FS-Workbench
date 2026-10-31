"""Task-scoped adapter: existing publisher owns validation, backups, CAS and rollback."""
import contextlib
import hashlib
import importlib.util
import json
import py_compile
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

stage = Path(__file__).resolve().parent
raw = (stage / 'manifest.json').read_bytes()
manifest = json.loads(raw)
assert manifest['scope'] == 'iam-modules-20261031'
assert hashlib.sha256(raw).hexdigest() == sys.argv[2]
assert hashlib.sha256((stage / 'publisher.py').read_bytes()).hexdigest() == manifest['publisherSha256']
spec = importlib.util.spec_from_file_location('existing_publisher', stage / 'publisher.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
targets = {'rbac.py': '/opt/fs-access-policy/rbac.py', 'iam_console.py': '/opt/fs-access-policy/iam_console.py', 'module_permissions.py': '/opt/auth-portal/registration-runtime/20261007-ca6258ad/module_permissions.py', 'web/app.js': '/opt/fs-access-policy/web/app.js', 'web/app.css': '/opt/fs-access-policy/web/app.css', 'web/registration.js': '/opt/fs-access-policy/web/registration.js'}
base.RELATIVE = set(targets)
base.target_for = lambda name: targets[name]
base.validate(manifest, stage)
for name in ('rbac.py','module_permissions.py','iam_console.py'): py_compile.compile(str(stage / 'candidate' / name), doraise=True)

def restart():
    subprocess.run(['systemctl', 'restart', 'auth-portal.service'], check=True)
    deadline = time.monotonic() + 20
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8895/iam/api/session', timeout=2) as response:
                assert response.status == 200 and json.load(response)['user'] == ''
            return
        except (OSError, AssertionError):
            if time.monotonic() >= deadline: raise
            time.sleep(.2)

if sys.argv[1] == 'inspect':
    print(json.dumps(base.inspect(manifest, stage)))
elif sys.argv[1] == 'apply':
    # 原共享锁在外层持有，覆盖五文件发布、认证重启、读回及必要回退。
    with base.locks(Path('/')):
        base.locks = lambda root: contextlib.nullcontext()
        result = base.apply(manifest, stage, sys.argv[2], raw, sys.argv[3])
        try:
            restart()
            base.guards(manifest, Path('/'))
            assert all(base.digest(Path(row['target'])) == row['sha256'] for row in manifest['files'])
        except BaseException:
            journal_path = Path(result['backup']) / 'journal.json'
            base.rollback_journal(journal_path.parent, json.loads(journal_path.read_text()), Path('/'))
            restart()
            raise
        print(json.dumps(result))
else:
    raise ValueError('inspect or apply required')
