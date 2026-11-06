"""2026-11-06 exact-scope adapter for the existing locked IAM publisher.

Never writes accounts, policies, sessions, targets or business databases. The two
public JSON files retain their bytes and get mode 0644; rollback restores modes.
"""
import contextlib
import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path('/opt/fs-release-stage/iam-modules-20261031/publisher.py')
BASE_SHA = 'df4441db0e718585862cb4dbd7c84f06b1f2373cd5d262dafa537524205926c7'
SCOPE = 'registered-session-fix-20261106'
RUNTIME = '/opt/auth-portal/registration-runtime/20261007-ca6258ad/'
TARGETS = {'iam_console.py': '/opt/fs-access-policy/iam_console.py',
           'module_permissions.py': RUNTIME + 'module_permissions.py',
           'consumer_seams.py': RUNTIME + 'consumer_seams.py',
           'navigation.json': '/var/www/dashboard/fs-home/navigation.json',
           'module-registry.json': '/var/www/dashboard/fs-home/module-registry.json'}
PUBLIC = {Path(TARGETS[key]) for key in ('navigation.json', 'module-registry.json')}
UNITS = ('auth-portal.service', 'mmoexp-taskboard.service', 'fc27-gate.service')


def publisher():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('existing publisher drift')
    spec = importlib.util.spec_from_file_location('session_existing_publisher', BASE)
    pub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pub)
    pub.RELATIVE = set(TARGETS)
    pub.target_for = lambda key: TARGETS[key]
    return pub


def restart():
    # Only identity consumers; collectors, writers and their sessions stay up.
    for unit in UNITS:
        subprocess.run(['systemctl', 'restart', unit], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True)
    deadline = time.monotonic() + 20
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8895/iam/api/session', timeout=2) as response:
                assert json.load(response)['user'] == ''
            return
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)


def main():
    pub = publisher()
    raw = (HERE / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    assert manifest['scope'] == SCOPE
    assert manifest['businessWrites'] is False and manifest['timersChanged'] is False
    sha = hashlib.sha256(raw).hexdigest()
    assert sys.argv[2] == sha
    pub.validate(manifest, HERE)
    for row in manifest['files']:
        if Path(row['target']) in PUBLIC:
            assert row['beforeSha256'] == row['sha256'], 'public bytes must not change'
    if sys.argv[1] == 'inspect':
        result = pub.inspect(manifest, HERE)
    elif sys.argv[1] == 'rollback':
        backup = Path(sys.argv[3])
        with pub.locks(Path('/')):
            journal = json.loads((backup / 'journal.json').read_text())
            pub.rollback_credentials(backup, journal, sha)
            pub.rollback_journal(backup, journal, Path('/'))
            restart()
        result = dict(status='rolled-back', backup=str(backup), databasesRestored=False)
    elif sys.argv[1] == 'apply':
        with pub.locks(Path('/')):
            pub.locks = lambda root: contextlib.nullcontext()
            original_atomic, original_rollback = pub.atomic, pub.rollback_journal
            def rollback(*args):
                pub.atomic = original_atomic
                return original_rollback(*args)
            pub.rollback_journal = rollback
            pub.atomic = lambda path, data, mode=0o644: original_atomic(
                path, data, 0o644 if path in PUBLIC else mode)
            result = pub.apply(manifest, HERE, sha, raw, sys.argv[3])
            pub.atomic = original_atomic
            backup = Path(result['backup'])
            try:
                restart()
                pub.guards(manifest, Path('/'))
                for row in manifest['files']:
                    path = Path(row['target'])
                    assert pub.digest(path) == row['sha256']
                    if path in PUBLIC:
                        assert stat.S_IMODE(path.stat().st_mode) == 0o644
            except BaseException:
                journal = json.loads((backup / 'journal.json').read_text())
                original_rollback(backup, journal, Path('/'))
                restart()
                raise
    else:
        raise ValueError('inspect/apply/rollback only')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
