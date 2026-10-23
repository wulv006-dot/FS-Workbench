"""Install the receipt trigger using the existing Hermes atomic publisher."""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

STAGE=Path(__file__).resolve().parent
sys.path.insert(0,'/opt/fs-hermes-ops')
from host import publisher

WATCH=Path('/var/lib/fs-hermes-fc/profile/scripts/fs-ops-watchdog/watch.py')
STATE=Path('/var/lib/fs-pricing-alerts')
OPERATION='pricing-immediate-alerts-20261023-v1'
BEFORE='d6aca8463473c433423e15d8b261289358e2dedad1f9a62cfce6d2e014a2d58a'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest=json.loads((STAGE/'manifest.json').read_text())
    assert all(sha(STAGE/name)==value for name,value in manifest['files'].items()),'candidate_drift'
    targets={
        'source/watch.py':WATCH,
        'source/pricing_probe.py':Path('/opt/fs-pricing-alerts/pricing_probe.py'),
        'source/fs-pricing-alerts.service':Path('/etc/systemd/system/fs-pricing-alerts.service'),
        'source/fs-pricing-alerts.path':Path('/etc/systemd/system/fs-pricing-alerts.path'),
        'source/pricing-alerts-bridge.conf':Path('/etc/systemd/system/fs-hermes-ops-bridge.service.d/pricing-alerts.conf'),
    }
    assert set(manifest['files'])==set(targets),'exact_scope_required'
    assert sha(WATCH)==BEFORE,'watch_source_drift'
    assert all(not path.exists() for path in targets.values() if path!=WATCH),'new_target_already_exists'
    atomic=publisher().atomic
    STATE.mkdir(mode=0o700,exist_ok=True)
    receipt=STATE/'deployment.json'
    assert not receipt.exists(),'reconcile_original_operation'
    backup=Path('/var/backups')/OPERATION
    backup.mkdir(mode=0o700)
    shutil.copy2(WATCH,backup/'watch.py')
    with ExitStack() as held:
        for path in [Path('/var/lock/fs-navigation-release.lock'),Path('/var/lock/fs-dashboard-release.lock'),
                     Path('/var/lib/fs-hermes-fc/profile/ops-watchdog/.watch.lock')]:
            handle=held.enter_context(path.open('a+b'))
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert sha(WATCH)==BEFORE
        with sqlite3.connect('file:/opt/d4follow/data/iggm_follow.db?mode=ro',uri=True,timeout=2) as conn:
            rows=conn.execute("SELECT id,result_json FROM local_job WHERE status='failed' ORDER BY id").fetchall()
        assert len(rows)==30 and all(not json.loads(raw or '{}').get('write_state') for _,raw in rows),'legacy_baseline_changed'
        baseline=dict(captured_at=datetime.now(timezone.utc).isoformat(),job_ids=[row[0] for row in rows],
                      classification='legacy_unclassified_not_zero_write_proof',count=30)
        atomic(STATE/'legacy-baseline.json',json.dumps(baseline).encode(),0o600)
        event=dict(operation=OPERATION,status='started',backup=str(backup),files=manifest['files'],
                   price_requests=0,business_timers_changed=False)
        atomic(receipt,json.dumps(event).encode(),0o600)
        for name,path in targets.items():
            path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
            if path==WATCH:assert sha(WATCH)==BEFORE
            atomic(path,(STAGE/name).read_bytes(),0o644 if path.suffix in ('.service','.path','.conf') else 0o600)
            assert sha(path)==manifest['files'][name]
        subprocess.run(['systemctl','daemon-reload'],check=True,timeout=15)
        subprocess.run(['systemctl','enable','fs-pricing-alerts.path'],check=True,timeout=15)
        subprocess.run(['systemctl','start','fs-pricing-alerts.path'],check=True,timeout=15)
        event.update(status='installed_path_active',installed_at=datetime.now(timezone.utc).isoformat())
        atomic(receipt,json.dumps(event).encode(),0o600)
    subprocess.run(['systemctl','start','fs-pricing-alerts.service'],check=True,timeout=105)
    event.update(status='deployed_real_probe_and_original_watch_checked',
                 initial_snapshot=json.loads((STATE/'latest.json').read_text())['issues'])
    atomic(receipt,json.dumps(event).encode(),0o600)
    print(json.dumps(event))

if __name__=='__main__':main()
