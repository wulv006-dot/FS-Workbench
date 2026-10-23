"""Extend the original monitor using its existing state lock and atomic publisher."""
from contextlib import ExitStack
import fcntl,hashlib,importlib.util,json,shutil,sys
from pathlib import Path
from datetime import datetime,timezone
TARGET=Path('/opt/fs-pricing-alerts/pricing_probe.py')
BEFORE='ea612dd87b141b29f8f7c9a2725e3a5b602eddec9ae379f5fc43b1833b2dea06'
PUBLISHER=Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
RECEIPT=Path('/var/lib/fs-pricing-alerts/order-memory-release-20261023.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(apply=False):
    root=Path(__file__).parent;manifest=json.loads((root/'order-memory-manifest.json').read_text())
    candidate=root/'source/pricing_probe.py'
    assert not RECEIPT.exists(),'reconcile_original_release'
    assert sha(PUBLISHER)=='b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'
    assert sha(TARGET)==BEFORE and sha(candidate)==manifest['after']
    spec=importlib.util.spec_from_file_location('original_publisher',PUBLISHER)
    publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
    sys.path.insert(0,'/opt/fc27-cloud-browser')
    from snapshot_layer import atomic_json
    with ExitStack() as held:
        for name in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock','/var/lib/fs-pricing-alerts/lock'):
            handle=held.enter_context(open(name,'a+b'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert sha(TARGET)==BEFORE
        if not apply:return {'status':'checked','targets':1}
        backup=Path('/var/lib/fs-pricing-alerts/order-memory-backup-20261023.py')
        assert not backup.exists();shutil.copy2(TARGET,backup)
        event=dict(status='started',before=BEFORE,after=manifest['after'],price_requests=0,timers_changed=False,
                   started_at=datetime.now(timezone.utc).isoformat())
        atomic_json(RECEIPT,event)
        publisher.publish(candidate,TARGET,TARGET.stat())
        assert sha(TARGET)==manifest['after']
        event.update(status='deployed',finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(RECEIPT,event);return event
if __name__=='__main__':print(json.dumps(main('--apply' in sys.argv)))
