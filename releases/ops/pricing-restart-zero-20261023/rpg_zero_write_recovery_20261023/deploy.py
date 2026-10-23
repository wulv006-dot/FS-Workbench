"""Use the original RPG publisher and idle fences; never replay a job."""
import fcntl,hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,'/opt/d4follow/_stage-p0-20261023')
sys.path.insert(0,'/opt/fc27-cloud-browser')
from deploy_fc import publish
from deploy_order_isolation import business_idle,idle
from snapshot_layer import atomic_json
ROOT=Path(__file__).parent
TARGET=Path('/opt/d4follow/_p2pah_srv/p2pah_local.py')
PROBE=Path('/opt/fs-pricing-alerts/pricing_probe.py')
BEFORE='3ade09f1caefbe0deb0d69cdac8f6c5c98e705370bc1ed17cee3de0d595a5be3'
AFTER='1992ef596c26da63973a786200c45733ea66fdc98b45d99256184fd0d1c8958e'
OLD_PROBE='006aabd2275f43b28e2cf7c24a98d6983e1b2a202cc7d8d3d9ad89f7d7bb2a24'
NEW_PROBE='ea612dd87b141b29f8f7c9a2725e3a5b602eddec9ae379f5fc43b1833b2dea06'
OP='rpg-zero-write-receipt-20261023-v1'
RECEIPT=Path('/var/lib/fs-order-session/rpg-zero-write-recovery-20261023.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(apply=False):
    assert not RECEIPT.exists(),'reconcile_original_release'
    assert sha(TARGET)==BEFORE and sha(PROBE)==OLD_PROBE
    spec=importlib.util.spec_from_file_location('zero_write_candidate',ROOT/'prepare_candidate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    candidate=ROOT/'p2pah_local.candidate.py'
    assert module.prepare(TARGET,candidate)==AFTER
    assert sha(ROOT/'source/pricing_probe.py')==NEW_PROBE
    with business_idle():
        idle()
        assert subprocess.check_output(['systemctl','is-active','p2pah-srv-exec.service'],text=True).strip()=='active'
        if not apply:return {'status':'checked','targets':2}
        event=dict(operation=OP,status='started',started_at=datetime.now(timezone.utc).isoformat(),price_requests=0,
                   before={str(TARGET):BEFORE,str(PROBE):OLD_PROBE},after={str(TARGET):AFTER,str(PROBE):NEW_PROBE})
        atomic_json(RECEIPT,event)
        subprocess.run(['systemctl','stop','p2pah-srv-exec.service'],check=True,timeout=20)
        try:
            idle()
            with Path('/opt/d4follow/data/srv_exec.lock').open('r+b') as lock, Path('/var/lib/fs-pricing-alerts/lock').open('a+b') as monitor:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(monitor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                assert sha(TARGET)==BEFORE and sha(PROBE)==OLD_PROBE
                publish({str(TARGET):candidate.read_text('utf-8'),str(PROBE):(ROOT/'source/pricing_probe.py').read_text('utf-8')},OP)
                assert sha(TARGET)==AFTER and sha(PROBE)==NEW_PROBE
                event['status']='deployed_sha_readback_verified'
        except Exception:
            event['status']='unknown'
            atomic_json(RECEIPT,event)
            raise
        finally:
            subprocess.run(['systemctl','start','p2pah-srv-exec.service'],check=True,timeout=20)
        event.update(finished_at=datetime.now(timezone.utc).isoformat(),natural_cycle='pending')
        atomic_json(RECEIPT,event)
        return event
if __name__=='__main__':print(json.dumps(main('--apply' in sys.argv)))
