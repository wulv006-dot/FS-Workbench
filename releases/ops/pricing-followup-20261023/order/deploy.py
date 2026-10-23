"""Publish only the existing reader through the original backup/CAS publisher."""
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0,'/opt/d4follow/_stage-p0-20261023')
sys.path.insert(0,'/opt/fc27-cloud-browser')
from deploy_fc import publish
from deploy_order_isolation import business_idle, idle

TARGET=Path('/opt/d4follow/_p2pah_srv/p2pah_local.py')
BEFORE='120045f794f78bef4c4aaeb8dbc27d0049a30a2546ebb24a73193370f2c20593'
AFTER='a5662d2814277b4a72cc47820f9730359b6727b29cf2fc1892c9ac862bc6d176'
OPERATION='order-query-category-first-20261023-v1'
RECEIPT=Path('/var/lib/fs-order-session/order-query-recovery-20261023.json')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    folder=Path(__file__).parent
    spec=importlib.util.spec_from_file_location('order_query_candidate',folder/'prepare_candidate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    candidate=folder/'p2pah_local.candidate.py'
    if RECEIPT.exists():raise RuntimeError('reconcile_original_deployment')
    assert module.prepare(TARGET,candidate)==AFTER
    from snapshot_layer import atomic_json
    with business_idle():
        assert sha(TARGET)==BEFORE
        event=dict(operation=OPERATION,status='started',before=BEFORE,after=AFTER,
                   started_at=datetime.now(timezone.utc).isoformat(),price_requests=0)
        atomic_json(RECEIPT,event)
        subprocess.run(['systemctl','stop','p2pah-srv-exec.service'],check=True,timeout=20)
        try:
            idle()
            with Path('/opt/d4follow/data/srv_exec.lock').open('r+b') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                assert sha(TARGET)==BEFORE
                publish({str(TARGET):candidate.read_text('utf-8')},OPERATION)
                assert sha(TARGET)==AFTER
        finally:
            subprocess.run(['systemctl','start','p2pah-srv-exec.service'],check=True,timeout=20)
        event.update(status='deployed_sha_readback_verified',natural_cycle='pending',
                     finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(RECEIPT,event)
        print(json.dumps(event))

if __name__=='__main__':main()
