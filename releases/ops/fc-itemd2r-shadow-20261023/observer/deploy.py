"""Publish only the new read-only observer using the existing atomic publisher."""
from contextlib import ExitStack
from datetime import datetime,timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

STAGE=Path(__file__).resolve().parent
STATE=Path('/var/lib/fc27-price-observer')
OPERATION='fc-itemd2r-shadow-observer-20261023-v1'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    sys.path.insert(0,'/opt/fs-hermes-ops')
    from host import publisher
    atomic=publisher().atomic
    manifest=json.loads((STAGE/'manifest.json').read_text())
    assert set(manifest['files'])=={'itemd2r.py','observe.py','reference_shadow.py','fc27-price-observer.service','fc27-price-observer.path'}
    targets={name:Path('/etc/systemd/system' if name.endswith(('.service','.path')) else '/opt/fc27-price-observer')/name for name in manifest['files']}
    with ExitStack() as held:
        for path in (Path('/var/lock/fs-navigation-release.lock'),Path('/var/lock/fs-dashboard-release.lock')):
            lock=held.enter_context(path.open('a+b'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for path,expected in manifest['protected'].items():assert sha(Path(path))==expected,'protected_drift:'+path
        assert not any(p.exists() for p in targets.values()),'existing_target_requires_original_receipt'
        assert not STATE.exists(),'state_exists_reconcile_original_operation'
        for name,expected in manifest['files'].items():
            assert sha(STAGE/'source'/name)==expected,'candidate_drift:'+name
            if name.endswith('.py'):compile((STAGE/'source'/name).read_bytes(),name,'exec')
        STATE.mkdir(mode=0o700)
        event=dict(operation=OPERATION,status='started',started_at=datetime.now(timezone.utc).isoformat(),
                   files=manifest['files'],protected=manifest['protected'],business_rule_changes=0,price_requests=0,
                   original_schedule_changed=False,simulation_only=True,rollback='stop new path; retain samples and original business data')
        atomic(STATE/'deployment.json',json.dumps(event).encode(),0o600)
        for name,path in targets.items():
            path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            atomic(path,(STAGE/'source'/name).read_bytes(),0o644 if name.endswith(('.service','.path')) else 0o600)
            assert sha(path)==manifest['files'][name]
        subprocess.run(['systemctl','daemon-reload'],check=True,timeout=15)
        subprocess.run(['systemctl','enable','--now','fc27-price-observer.path'],check=True,timeout=15)
        event.update(status='observer_path_installed',installed_at=datetime.now(timezone.utc).isoformat())
        atomic(STATE/'deployment.json',json.dumps(event).encode(),0o600)
    subprocess.run(['systemctl','start','fc27-price-observer.service'],check=True,timeout=85)
    deadline=time.monotonic()+75
    while time.monotonic()<deadline:
        active=subprocess.run(['systemctl','show','fc27-price-observer.service','-p','ActiveState'],check=True,text=True,capture_output=True,timeout=4).stdout.strip()
        if active=='ActiveState=inactive':break
        if active=='ActiveState=failed':raise RuntimeError('observer_service_failed_read_original_receipt')
        time.sleep(1)
    else:raise TimeoutError('observer_service_original_result_required')
    sample=json.loads((STATE/'latest.json').read_text()) if (STATE/'latest.json').exists() else None
    assert all(sha(Path(p))==v for p,v in manifest['protected'].items()),'business_source_drift'
    event.update(status='deployed_readonly_observer_verified',sample_status=sample.get('status') if sample else 'deferred',
                 sample_run_id=sample.get('run_id') if sample else None,
                 sample_original_unchanged=sample.get('original_snapshot_unchanged') if sample else None)
    atomic(STATE/'deployment.json',json.dumps(event).encode(),0o600)
    print(json.dumps(event))

if __name__=='__main__':main()
