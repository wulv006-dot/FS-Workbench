"""Original Order publisher and idle fences; run only by the coordinated publisher."""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, '/opt/d4follow/_stage-p0-20261023')
sys.path.insert(0, '/opt/fc27-cloud-browser')
from deploy_fc import publish
from deploy_order_isolation import business_idle, idle
from snapshot_layer import atomic_json

ROOT = Path(__file__).parent
TARGET = Path('/opt/fs-order-session/service.py')
HELPER = TARGET.with_name('raw_node_helper.js')
BEFORE = '89e8b6bba49397499c39c697f54d44a8ab892aed23fefafe34df0824058c0353'
AFTER = '35b950f23ba45d662b755ef33f415e7ca22c749331baad4fd43de04aa59e76b0'
HELPER_SHA = '53ee945adbafde58140f2d2705b488ad83d99b7dab30d138d1c6082997713425'
ISOLATION = Path('/var/lib/fs-order-session/browser-isolation-20261023.json')
RECEIPT = Path('/var/lib/fs-order-session/worldless-probe-recovery-20261023.json')
ISOLATION_LOCK = Path('/run/fs-order-browser-isolation.lock')
EXEC_LOCK = Path('/opt/d4follow/data/srv_exec.lock')
OP = 'order-worldless-probe-20261023-v1'
NEW_FILE_PUBLISHER = Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
NEW_FILE_PUBLISHER_SHA = 'b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect():
    return json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .}}', 'fs-order-browser'], text=True, timeout=5))


def health():
    with urllib.request.urlopen('http://127.0.0.1:8768/health', timeout=5) as response:
        return json.load(response)


def no_active_rpg_container():
    active = subprocess.check_output(['docker', 'ps', '--filter', 'ancestor=p2pah-srv:1', '--format', '{{.ID}}'], text=True, timeout=5)
    assert not active.split(), 'active_rpg_execution_container'


def pid():
    lines = subprocess.check_output(['systemctl', 'show', 'fs-order-session.service', '-p', 'MainPID'], text=True, timeout=5).splitlines()
    values = [line[len('MainPID='):] for line in lines if line.startswith('MainPID=')]
    assert len(values) == 1 and values[0].isdigit() and int(values[0]) > 0, 'broker_pid_unverified'
    return int(values[0])


def publish_helper(source, target, metadata):
    assert sha(NEW_FILE_PUBLISHER) == NEW_FILE_PUBLISHER_SHA, 'original_new_file_publisher_drift'
    spec = importlib.util.spec_from_file_location('original_order_helper_publisher', NEW_FILE_PUBLISHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.publish(source, target, metadata)


def verified_prewrite_failure(previous, original_isolation, service_sha, helper_exists):
    assert previous.get('operation') == OP and previous.get('status') == 'unknown' and previous.get('error') == 'FileNotFoundError', 'original_failure_not_proven_prewrite'
    assert previous.get('service_before') == BEFORE and previous.get('service_after') == AFTER and previous.get('helper_after') == HELPER_SHA
    assert service_sha == BEFORE and not helper_exists, 'partial_write_requires_manual_reconciliation'
    assert previous.get('original_isolation_sha256') == hashlib.sha256(original_isolation).hexdigest(), 'original_proof_drift'
    assert not previous.get('resumed_at') and not previous.get('initial_failure'), 'prior_resume_requires_reconciliation'


def main(apply=False, resume_verified_prewrite_failure=False):
    original_receipt = RECEIPT.read_bytes() if RECEIPT.exists() else None
    assert sha(TARGET) == BEFORE and not HELPER.exists(), 'active_source_or_new_helper_drift'
    assert sha(ROOT/'source/service.py') == AFTER and sha(ROOT/'source/raw_node_helper.js') == HELPER_SHA
    original_isolation = ISOLATION.read_bytes()
    previous = json.loads(original_receipt) if original_receipt is not None else None
    if previous is not None:
        assert resume_verified_prewrite_failure, 'reconcile_original_deployment_no_replay'
        verified_prewrite_failure(previous, original_isolation, sha(TARGET), HELPER.exists())
    else:
        assert not resume_verified_prewrite_failure, 'original_prewrite_failure_missing'
    proof = json.loads(original_isolation)
    assert proof.get('status') == 'verified' and proof.get('durability_verified') is True and proof.get('service_sha256') == BEFORE
    with business_idle(), ExitStack() as held:
        lock = held.enter_context(ISOLATION_LOCK.open('a+b'))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        idle(); no_active_rpg_container()
        assert subprocess.check_output(['systemctl', 'is-active', 'p2pah-srv-exec.service'], text=True, timeout=5).strip() == 'active'
        before = inspect()
        assert before['State']['Running'] and '--restore-last-session' in before['Config']['Cmd']
        assert any(m['Source'] == '/var/lib/fs-order-session/browser' and m['Destination'] == m['Source'] for m in before['Mounts'])
        value = health()
        assert value['ready'] is True and value['login_attempts'] == 0
        assert sha(TARGET) == BEFORE and not HELPER.exists() and ISOLATION.read_bytes() == original_isolation
        assert (RECEIPT.read_bytes() if RECEIPT.exists() else None) == original_receipt, 'original_receipt_drift'
        if not apply:
            return {'status': 'checked', 'targets': 2, 'container_restart': False, 'business_requests': 0}
        event = dict(operation=OP, status='started', started_at=datetime.now(timezone.utc).isoformat(),
                     service_before=BEFORE, service_after=AFTER, helper_after=HELPER_SHA,
                     container_restarted=False, profile_preserved=True, price_requests=0, login_attempts=0,
                     original_isolation_sha256=hashlib.sha256(original_isolation).hexdigest())
        if previous is not None:
            event.update(initial_failure=previous, resumed_at=event['started_at'])
            event['started_at'] = previous['started_at']
        atomic_json(RECEIPT, event)
        execution = None
        try:
            # Same established maintenance boundary: stop only the verified idle
            # executor, hold its original singleton lock, resume after native ready.
            idle(); no_active_rpg_container()
            subprocess.run(['systemctl', 'stop', 'p2pah-srv-exec.service'], check=True, timeout=20)
            execution = held.enter_context(EXEC_LOCK.open('r+b'))
            fcntl.flock(execution, fcntl.LOCK_EX | fcntl.LOCK_NB)
            idle(); no_active_rpg_container()
            assert sha(TARGET) == BEFORE and not HELPER.exists() and ISOLATION.read_bytes() == original_isolation
            old_pid = pid()
            assert old_pid > 0
            # Publish through the original publisher; the unused helper goes first.
            publish_helper(ROOT/'source/raw_node_helper.js', HELPER, TARGET.stat())
            assert sha(HELPER) == HELPER_SHA and sha(TARGET) == BEFORE
            publish({str(TARGET): (ROOT/'source/service.py').read_text('utf-8')}, OP)
            backup = Path('/var/backups')/OP
            (backup/'browser-isolation-before.json').write_bytes(original_isolation)
            assert sha(TARGET) == AFTER and sha(HELPER) == HELPER_SHA
            subprocess.run(['systemctl', 'restart', 'fs-order-session.service'], check=True, timeout=20)
            new_pid = pid()
            assert new_pid > 0 and new_pid != old_pid, 'new_broker_process_unverified'
            deadline = time.monotonic()+45
            while True:
                try:
                    value = health()
                    if value.get('ready') is True and value.get('login_attempts') == 0 and 0 <= value.get('verified_age_seconds', 100) <= 45:
                        break
                except (OSError, ValueError, TypeError, KeyError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('native_worldless_upkeep_identity_unverified')
                time.sleep(1)
            after = inspect()
            assert after['Id'] == before['Id'] and after['State']['StartedAt'] == before['State']['StartedAt'], 'browser_container_changed'
            assert sha(TARGET) == AFTER and sha(HELPER) == HELPER_SHA and ISOLATION.read_bytes() == original_isolation
            proof.update(service_sha256=AFTER, probe_helper_sha256=HELPER_SHA,
                         worldless_probe_recovery=dict(operation=OP, service_before=BEFORE, service_after=AFTER,
                             helper_sha256=HELPER_SHA, verified_at=datetime.now(timezone.utc).isoformat(),
                             profile_preserved=True, original_durability_proof_retained=True,
                             container_id=after['Id'], started_at=after['State']['StartedAt'], login_attempts=0))
            # A failed native probe never receives a current-service isolation proof.
            atomic_json(ISOLATION, proof)
            event.update(status='verified', health={k: value.get(k) for k in ('ready', 'last_error', 'login_attempts', 'probe_seconds')},
                         broker_pid_changed=True, natural_world_count='pending', finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as error:
            event.update(status='unknown', error=type(error).__name__)
            raise
        finally:
            try:
                atomic_json(RECEIPT, event)
            finally:
                try:
                    if execution is not None:
                        fcntl.flock(execution, fcntl.LOCK_UN)
                        execution.close()
                finally:
                    subprocess.run(['systemctl', 'start', 'p2pah-srv-exec.service'], check=True, timeout=20)
        return event


if __name__ == '__main__':
    print(json.dumps(main('--apply' in sys.argv, '--resume-verified-prewrite-failure' in sys.argv)))
