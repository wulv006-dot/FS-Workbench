"""Four-file CAS deployment; retains runtime configuration and historical records."""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from urllib.request import Request, urlopen

STAGE = Path(__file__).resolve().parent
sys.path.insert(0, '/opt/fc27-cloud-browser')
from automation_tick import queue_mutation

ROOT = Path('/var/lib/fc27-cloud')
HOOKS = '--hooks' in sys.argv
if HOOKS:
    STAGE = Path(sys.argv[sys.argv.index('--hooks')+1])
    if STAGE.parent != Path('/opt') or not STAGE.name.startswith('fc-ops-monitor-stage-'):
        raise ValueError('fixed_hook_stage_required')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args):
    subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def idle():
    if list((ROOT / 'queue').glob('*.json')):
        raise RuntimeError('queue_not_idle')
    for path in (ROOT / 'jobs').glob('*.json'):
        if json.loads(path.read_text()).get('status') in {'queued', 'running'}:
            raise RuntimeError('job_not_idle')
    for path in (ROOT / 'executions').glob('*.json'):
        if json.loads(path.read_text()).get('status') in {'RUNNING', 'UNCERTAIN', 'PARTIAL'}:
            raise RuntimeError('coin_execution_unresolved')


def swap(source, target):
    meta = target.stat()
    temp = target.with_name('.' + target.name + '.price-rule-tmp')
    with temp.open('xb') as stream:
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, stat.S_IMODE(meta.st_mode))
    os.chown(temp, meta.st_uid, meta.st_gid)
    os.replace(temp, target)
    fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    manifest = json.loads((STAGE / 'manifest.json').read_text())
    targets = manifest['targets']
    if HOOKS:
        names={'automation_policy.py','price_writer.py','coin_all_sync_job.py','execute_price.sh'}
        if set(targets)!=names or any(row['target']!='/opt/fc27-cloud-browser/'+name for name,row in targets.items()):
            raise ValueError('exact_fc_hook_scope_required')
    if os.geteuid() != 0 or len(targets) != 4:
        raise RuntimeError('deployment_scope_invalid')
    for name, row in targets.items():
        source = STAGE / 'candidate' / name
        if source.is_symlink() or digest(source) != row['after']:
            raise RuntimeError('candidate_changed:' + name)
        if name.endswith('.py'):
            compile(source.read_text(), name, 'exec')
    with queue_mutation():
        lock = os.open(ROOT / 'state/price-writer.lock', os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            idle()
            for target, wanted in manifest['before'].items():
                path = Path(target)
                if path.is_symlink() or digest(path) != wanted:
                    raise RuntimeError('baseline_changed:' + target)
            for unit in ('fc27-cloud-api', 'fc27-cloud-worker', 'fc27-automation-tick.timer'):
                command('systemctl', 'is-active', '--quiet', unit)
            backup = ROOT / 'rollback' / (('fs-hooks-' if HOOKS else 'player-price-verification-off-') +
                                           datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
            backup.mkdir(mode=0o700)
            for name, row in targets.items():
                shutil.copy2(row['target'], backup / name)
            (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2))
            try:
                if not HOOKS:
                    command('systemctl', 'stop', 'fc27-cloud-worker')
                if not HOOKS:
                    command('systemctl', 'stop', 'fc27-cloud-api')
                idle()
                for target, wanted in manifest['before'].items():
                    if digest(Path(target)) != wanted:
                        raise RuntimeError('baseline_changed_before_replace:' + target)
                for name, row in targets.items():
                    swap(STAGE / 'candidate' / name, Path(row['target']))
                if not HOOKS:
                    command('systemctl', 'start', 'fc27-cloud-api')
                if not HOOKS:
                    command('systemctl', 'start', 'fc27-cloud-worker')
                monitor = None
                for _ in range(20):
                    try:
                        with urlopen(Request('http://127.0.0.1:8879/monitor',
                                             headers={'X-Authenticated-User': 'wulv'}), timeout=5) as res:
                            monitor = json.load(res)
                        if monitor['health']['worker'] == 'ok':
                            break
                    except OSError:
                        pass
                    time.sleep(0.5)
                if (not monitor or monitor['health']['worker'] != 'ok'
                        or (not HOOKS and (monitor['player_sync'].get('price_verification') != 'disabled'
                        or not monitor['player_sync'].get('price_verification_waived')
                        or monitor['automation']['schedule']['status'].startswith('player_sync_')))):
                    raise RuntimeError('runtime_rule_not_effective')
                if HOOKS:
                    control=json.loads(Path('/var/lib/fc-ops-readonly-monitor/gates/control.json').read_text())
                    if (control.get('mode')!='RULES_ARMED' or control.get('unknown_operations')
                            or control.get('policy_revision')!=monitor['automation']['revision']):
                        raise RuntimeError('hook_runtime_control_not_ready')
                actual = {}
                for name, row in targets.items():
                    actual[row['target']] = digest(Path(row['target']))
                    if actual[row['target']] != row['after']:
                        raise RuntimeError('installed_hash_mismatch')
                protected = {p: value for p, value in manifest['before'].items()
                             if p not in actual}
                if any(digest(Path(p)) != value for p, value in protected.items()):
                    raise RuntimeError('protected_input_changed')
                receipt = {'status': 'deployed', 'at': datetime.now(timezone.utc).isoformat(),
                           'backup': str(backup), 'installed_sha256': actual,
                           'protected_sha256': protected,
                           'schedule': monitor['automation']['schedule'],
                           'player_sync': monitor['player_sync'], 'health': monitor['health']}
                (backup / 'receipt.json').write_text(json.dumps(receipt, indent=2))
                print(json.dumps(receipt, ensure_ascii=False))
            except Exception:
                if not HOOKS:
                    command('systemctl', 'stop', 'fc27-cloud-worker')
                if not HOOKS:
                    command('systemctl', 'stop', 'fc27-cloud-api')
                for name, row in targets.items():
                    swap(backup / name, Path(row['target']))
                if not HOOKS:
                    command('systemctl', 'start', 'fc27-cloud-api')
                if not HOOKS:
                    command('systemctl', 'start', 'fc27-cloud-worker')
                raise
        finally:
            os.close(lock)


if __name__ == '__main__':
    main()
