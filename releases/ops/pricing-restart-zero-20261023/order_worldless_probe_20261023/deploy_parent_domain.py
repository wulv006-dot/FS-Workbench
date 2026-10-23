"""Publish the helper compatibility fix through the same idle maintenance boundary."""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
import deploy as original

ROOT = Path(__file__).parent
SERVICE = Path('/opt/fs-order-session/service.py')
HELPER = SERVICE.with_name('raw_node_helper.js')
SERVICE_SHA = '35b950f23ba45d662b755ef33f415e7ca22c749331baad4fd43de04aa59e76b0'
BEFORE = '53ee945adbafde58140f2d2705b488ad83d99b7dab30d138d1c6082997713425'
PROOF = Path('/var/lib/fs-order-session/browser-isolation-20261023.json')
RECEIPT = PROOF.with_name('worldless-parent-domain-20261023.json')
OP = 'order-worldless-parent-domain-20261023-v1'


def main(apply=False):
    expected = json.loads((ROOT/'parent-domain-manifest.json').read_text())['helper_after']
    assert len(expected) == 64 and all(c in '0123456789abcdef' for c in expected)
    assert not RECEIPT.exists(), 'reconcile_original_patch_no_replay'
    assert original.sha(SERVICE) == SERVICE_SHA and original.sha(HELPER) == BEFORE
    candidate = ROOT/'source/raw_node_helper.js'
    assert original.sha(candidate) == expected
    proof_bytes = PROOF.read_bytes(); proof = json.loads(proof_bytes)
    assert proof.get('status') == 'verified' and proof.get('durability_verified') is True
    assert proof['service_sha256'] == SERVICE_SHA and proof['probe_helper_sha256'] == BEFORE
    with original.business_idle(), ExitStack() as held:
        lock = held.enter_context(original.ISOLATION_LOCK.open('a+b'))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original.idle(); original.no_active_rpg_container()
        assert subprocess.check_output(['systemctl','is-active','p2pah-srv-exec.service'],text=True,timeout=5).strip() == 'active'
        before = original.inspect(); value = original.health()
        assert before['State']['Running'] and value['ready'] is True and value['login_attempts'] == 0
        assert '--restore-last-session' in before['Config']['Cmd']
        assert any(m['Source'] == '/var/lib/fs-order-session/browser' and m['Destination'] == m['Source'] for m in before['Mounts'])
        assert proof['worldless_probe_recovery']['container_id'] == before['Id'] and proof['worldless_probe_recovery']['started_at'] == before['State']['StartedAt']
        assert original.sha(SERVICE) == SERVICE_SHA and original.sha(HELPER) == BEFORE and PROOF.read_bytes() == proof_bytes
        if not apply:
            return {'status':'checked','targets':1,'browser_restart':False,'business_requests':0}
        event = dict(operation=OP,status='started',started_at=datetime.now(timezone.utc).isoformat(),
                     helper_before=BEFORE,helper_after=expected,service_unchanged=SERVICE_SHA,
                     container_restarted=False,profile_preserved=True,price_requests=0)
        original.atomic_json(RECEIPT,event)
        execution = None
        try:
            original.idle(); original.no_active_rpg_container()
            subprocess.run(['systemctl','stop','p2pah-srv-exec.service'],check=True,timeout=20)
            execution = held.enter_context(original.EXEC_LOCK.open('r+b'))
            fcntl.flock(execution,fcntl.LOCK_EX | fcntl.LOCK_NB)
            original.idle(); original.no_active_rpg_container()
            assert original.sha(SERVICE) == SERVICE_SHA and original.sha(HELPER) == BEFORE and PROOF.read_bytes() == proof_bytes
            old_pid = original.pid()
            # This file now exists: the original Order publisher preserves its backup.
            original.publish({str(HELPER):candidate.read_text('utf-8')},OP)
            (Path('/var/backups')/OP/'browser-isolation-before.json').write_bytes(proof_bytes)
            assert original.sha(HELPER) == expected and original.sha(SERVICE) == SERVICE_SHA
            subprocess.run(['systemctl','restart','fs-order-session.service'],check=True,timeout=20)
            assert original.pid() != old_pid
            deadline = time.monotonic()+45
            while True:
                try:
                    value = original.health()
                    if value.get('ready') is True and value.get('login_attempts') == 0 and 0 <= value.get('verified_age_seconds',100) <= 45:
                        break
                except (OSError,ValueError,TypeError,KeyError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('native_parent_domain_helper_unverified')
                time.sleep(1)
            after = original.inspect()
            assert after['Id'] == before['Id'] and after['State']['StartedAt'] == before['State']['StartedAt']
            assert original.sha(HELPER) == expected and original.sha(SERVICE) == SERVICE_SHA and PROOF.read_bytes() == proof_bytes
            proof.update(probe_helper_sha256=expected,parent_domain_recovery=dict(operation=OP,helper_before=BEFORE,
                         helper_after=expected,verified_at=datetime.now(timezone.utc).isoformat(),profile_preserved=True,
                         container_id=after['Id'],started_at=after['State']['StartedAt'],original_durability_proof_retained=True))
            original.atomic_json(PROOF,proof)
            event.update(status='verified',finished_at=datetime.now(timezone.utc).isoformat(),
                         health={k:value.get(k) for k in ('ready','login_attempts','last_error','probe_seconds')})
        except Exception as error:
            event.update(status='unknown',error=type(error).__name__)
            raise
        finally:
            try:
                original.atomic_json(RECEIPT,event)
            finally:
                try:
                    if execution is not None:
                        fcntl.flock(execution,fcntl.LOCK_UN)
                        execution.close()
                finally:
                    subprocess.run(['systemctl','start','p2pah-srv-exec.service'],check=True,timeout=20)
        return event


if __name__ == '__main__':
    print(json.dumps(main('--apply' in sys.argv)))
