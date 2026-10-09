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
NONCORE = '--noncore-emergency' in sys.argv
HOOKS = '--hooks' in sys.argv
if NONCORE:
    if HOOKS:
        raise ValueError('deployment_modes_conflict')
    STAGE = Path(sys.argv[sys.argv.index('--noncore-emergency')+1])
    if STAGE.is_symlink() or STAGE.parent != Path('/opt') or not STAGE.name.startswith('fc-ops-monitor-stage-'):
        raise ValueError('fixed_noncore_stage_required')
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


def noncore_checks(stage, checks):
    import re
    files = checks['files']
    patterns = ['test_pipeline.py', 'test_selfheal.py']
    required = {'tests/'+name for name in patterns} | {'tests/legacy_engine.py','tests/legacy_repricing_logic.js','tests/test_js.cjs'}
    if checks.get('patterns') != patterns or not required.issubset(files) or type(checks['test_count']) is not int or checks['test_count'] < 1 or type(checks['node_count']) is not int or checks['node_count'] < 1:
        raise ValueError('frozen_noncore_checks_required')
    for relative, wanted in files.items():
        path = stage/relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or not path.resolve().is_relative_to(stage.resolve()) or not path.is_file() or digest(path) != wanted:
            raise ValueError('noncore_check_input_changed')
    logs=[];total=0
    for pattern in patterns:
        result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(stage/'tests'), '-p', pattern], capture_output=True, text=True, timeout=60)
        logs.append(result.stderr);count=re.search(r'Ran (\d+) tests?',result.stderr)
        if result.returncode or not count or not result.stderr.rstrip().endswith('OK'):
            (stage/'noncore-linux-tests.txt').write_text('\n'.join(logs),encoding='utf-8')
            raise RuntimeError('noncore_linux_checks_failed')
        total+=int(count.group(1))
    (stage/'noncore-linux-tests.txt').write_text('\n'.join(logs),encoding='utf-8')
    if total != checks['test_count']:
        raise RuntimeError('noncore_linux_checks_failed')
    node=subprocess.run(['node',str(stage/'tests'/'test_js.cjs')],capture_output=True,text=True,timeout=60)
    (stage/'noncore-node-tests.txt').write_text(node.stdout+'\n'+node.stderr,encoding='utf-8')
    try:summary=json.loads(node.stdout)
    except ValueError:raise RuntimeError('noncore_node_checks_failed')
    if node.returncode or summary.get('passed') is not True or summary.get('checks') != checks['node_count']:
        raise RuntimeError('noncore_node_checks_failed')


def noncore_idle():
    from automation_tick import retry_guard
    idle()
    if retry_guard() != 'ready':
        raise RuntimeError('noncore_unresolved_operation')


def noncore_emergency(apply):
    manifest = json.loads((STAGE/'noncore-fc-manifest.json').read_text())
    targets = manifest['targets']
    expected = {name: '/opt/fc27-cloud-browser/'+name for name in (
        'fc27_quote_engine.py', 'snapshot_layer.py', 'server_quote_job.py',
        'automation_policy.py', 'fc27_cloud_api.py', 'repricing_logic.js', 'automation_tick.py')}
    expected['fc27-quote-cloud.js'] = '/var/www/dashboard/fc27-quote-cloud.js'
    if os.geteuid() != 0 or set(targets) != set(expected) or any(row['target'] != expected[name] for name, row in targets.items()):
        raise ValueError('exact_noncore_fc_scope_required')
    protected = {str(ROOT/'config'/name) for name in ('automation.json', 'player-sync.json')}
    protected.update('/opt/fc27-cloud-browser/'+name for name in (
        'fc27_cloud_worker.py', 'price_writer.py', 'coin_all_sync_job.py', 'execute_price.sh'))
    if not protected.issubset(manifest['before']) or any(manifest['before'].get(row['target']) != row['before'] for row in targets.values()):
        raise ValueError('noncore_protected_baseline_required')
    protected = set(manifest['before']) - {row['target'] for row in targets.values()}
    for name, row in targets.items():
        source = STAGE/'source'/name
        if source.is_symlink() or not source.resolve().is_relative_to(STAGE.resolve()) or digest(source) != row['after']:
            raise RuntimeError('candidate_changed:'+name)
        if name.endswith('.py'):
            compile(source.read_text(), name, 'exec')
        else:
            command('node', '--check', str(source))
    noncore_checks(STAGE, manifest['checks'])
    with queue_mutation():
        lock = os.open(ROOT/'state/price-writer.lock', os.O_RDONLY|os.O_NOFOLLOW)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            noncore_idle()
            for path, wanted in manifest['before'].items():
                if Path(path).is_symlink() or digest(Path(path)) != wanted:
                    raise RuntimeError('noncore_baseline_changed:'+path)
            for unit in ('fc27-cloud-api', 'fc27-cloud-worker', 'fc27-automation-tick.timer'):
                command('systemctl', 'is-active', '--quiet', unit)
            receipt = {'status': 'checked', 'applied': False, 'checks': manifest['checks']['test_count'], 'node_checks':manifest['checks']['node_count']}
            if not apply:
                print(json.dumps(receipt)); return receipt
            backup = ROOT/'rollback'/('noncore-emergency-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
            backup.mkdir(mode=0o700)
            for name, row in targets.items():
                shutil.copy2(row['target'], backup/name)
            (backup/'manifest.json').write_text(json.dumps(manifest, indent=2))
            installed = []
            try:
                # Loaded API and worker imports require an idle code reload.
                command('systemctl', 'stop', 'fc27-cloud-worker')
                command('systemctl', 'stop', 'fc27-cloud-api')
                noncore_idle()
                for path, wanted in manifest['before'].items():
                    if Path(path).is_symlink() or digest(Path(path)) != wanted:
                        raise RuntimeError('noncore_baseline_changed_before_replace:'+path)
                for name, row in targets.items():
                    source = STAGE/'source'/name
                    if source.is_symlink() or not source.resolve().is_relative_to(STAGE.resolve()) or digest(source) != row['after']:
                        raise RuntimeError('candidate_changed_before_replace:'+name)
                    swap(source, Path(row['target'])); installed.append(name)
                command('systemctl', 'start', 'fc27-cloud-api')
                command('systemctl', 'start', 'fc27-cloud-worker')
                monitor = None
                for _ in range(20):
                    try:
                        with urlopen(Request('http://127.0.0.1:8879/monitor', headers={'X-Authenticated-User':'wulv'}), timeout=5) as response:
                            monitor = json.load(response)
                        if monitor['health']['worker'] == 'ok': break
                    except OSError:
                        pass
                    time.sleep(0.5)
                if not monitor or monitor['health']['worker'] != 'ok':
                    raise RuntimeError('noncore_runtime_not_ready')
                for unit in ('fc27-cloud-api', 'fc27-cloud-worker', 'fc27-automation-tick.timer'):
                    command('systemctl', 'is-active', '--quiet', unit)
                actual = {row['target']:digest(Path(row['target'])) for row in targets.values()}
                if any(actual[row['target']] != row['after'] for row in targets.values()):
                    raise RuntimeError('noncore_installed_hash_mismatch')
                if any(digest(Path(path)) != manifest['before'][path] for path in protected):
                    raise RuntimeError('noncore_protected_input_changed')
                receipt.update(status='deployed', applied=True, at=datetime.now(timezone.utc).isoformat(), backup=str(backup), installed_sha256=actual,
                               protected_sha256={path:manifest['before'][path] for path in protected}, policy_revision=monitor['automation']['revision'], health=monitor['health'])
                (backup/'receipt.json').write_text(json.dumps(receipt, indent=2))
                print(json.dumps(receipt)); return receipt
            except Exception:
                command('systemctl', 'stop', 'fc27-cloud-worker')
                command('systemctl', 'stop', 'fc27-cloud-api')
                for name in reversed(installed):
                    swap(backup/name, Path(targets[name]['target']))
                command('systemctl', 'start', 'fc27-cloud-api')
                command('systemctl', 'start', 'fc27-cloud-worker')
                raise
        finally:
            os.close(lock)


def main():
    if NONCORE:
        return noncore_emergency('--apply' in sys.argv)
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
