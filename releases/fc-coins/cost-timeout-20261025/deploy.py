"""Cost-timeout adapter of the installed FC CAS publisher and existing release locks."""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/opt/fc27-cloud-browser')
import automation_tick as tick
import fc27_cloud_api as api
from snapshot_layer import atomic_json

HERE = Path(__file__).resolve().parent
ROOT = Path('/var/lib/fc27-cloud')
TARGETS = {name: Path('/opt/fc27-cloud-browser') / name
           for name in ('automation_tick.py', 'collect_p2pah_cost.sh')}
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    manifest = json.loads((HERE / 'manifest.json').read_text())
    assert set(manifest['files']) == set(TARGETS), 'exact_scope_required'
    publisher_path = ROOT / 'maintenance/local-collection-20261017/publish.py'
    assert sha(publisher_path) == manifest['publisher_sha256'], 'publisher_drift'
    spec = importlib.util.spec_from_file_location('installed_fc_publisher', publisher_path)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    subprocess.run([sys.executable, str(HERE / 'tests/test_timeout.py')], check=True, timeout=30)
    with ExitStack() as held:
        for name in ('fs-navigation-release.lock', 'fs-dashboard-release.lock'):
            fd = os.open('/var/lock/' + name, os.O_RDWR | os.O_NOFOLLOW)
            info = os.fstat(fd)
            assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
            handle = held.enter_context(os.fdopen(fd, 'r+b'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held.enter_context(tick.queue_mutation())
        for name in tick.RETRY_LOCKS:
            handle = held.enter_context((ROOT / 'state' / name).open('rb'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert tick.retry_guard() == 'ready', 'unresolved_or_active_operation'
        assert api.health()['incomplete_executions'] == 0, 'unresolved_execution'
        assert all(sha(path) == digest for path, digest in manifest['protected'].items()), 'protected_drift'
        for name, target in TARGETS.items():
            assert sha(target) == manifest['files'][name]['before'], 'source_drift:' + name
            assert sha(HERE / 'source' / name) == manifest['files'][name]['after'], 'candidate_drift'
            (compile((HERE / 'source' / name).read_bytes(), name, 'exec') if name.endswith('.py') else subprocess.run(['sh', '-n', str(HERE / 'source' / name)], check=True))
        if '--apply' not in sys.argv:
            print(json.dumps({'status': 'checked', 'files': 2, 'linux_tests': 4}))
            return
        receipt = HERE / 'deployment.json'
        assert not receipt.exists(), 'reconcile_existing_deployment'
        backup = ROOT / 'rollback/fc-cost-timeout-20261025'
        backup.mkdir(mode=0o700)
        for name, target in TARGETS.items():
            shutil.copy2(target, backup / name)
            assert sha(backup / name) == manifest['files'][name]['before']
        result = dict(status='started', at=datetime.now(timezone.utc).isoformat(),
                      backup=str(backup), files=manifest['files'], timers_changed=False,
                      policy_changed=False, business_writes=0)
        atomic_json(receipt, result)
        changed = []
        try:
            for name, target in TARGETS.items():
                assert sha(target) == manifest['files'][name]['before'], 'source_drift_before_swap'
                publisher.publish(HERE / 'source' / name, target, target.stat())
                changed.append(name)
                assert sha(target) == manifest['files'][name]['after']
            subprocess.run(['systemctl', 'restart', 'fc27-cloud-api'], check=True, timeout=20)
            subprocess.run(['systemctl', 'is-active', '--quiet', 'fc27-cloud-api',
                            'fc27-cloud-worker', 'fc27-automation-tick.timer'], check=True, timeout=10)
            assert all(sha(path) == digest for path, digest in manifest['protected'].items()), 'protected_drift_after'
            result.update(status='deployed', api_reloaded=True, worker_restarted=False)
        except Exception as exc:
            for name in reversed(changed):
                target = TARGETS[name]
                assert sha(target) == manifest['files'][name]['after'], 'rollback_drift'
                publisher.publish(backup / name, target, target.stat())
            subprocess.run(['systemctl', 'restart', 'fc27-cloud-api'], check=True, timeout=20)
            result.update(status='rolled_back', error=type(exc).__name__)
            raise
        finally:
            atomic_json(receipt, result)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
