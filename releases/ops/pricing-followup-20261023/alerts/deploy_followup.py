"""CAS the final two alert consumers; keep original delivery and business state."""
from contextlib import ExitStack
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone

sys.path.insert(0,'/opt/fs-hermes-ops')
from host import publisher

HERE=Path(__file__).parent
TARGETS={
 'watch.py':('/var/lib/fs-hermes-fc/profile/scripts/fs-ops-watchdog/watch.py','b1851faa087108b249d38591442ffe7a2ca638986c775d4bc8ba42eba4e218c4'),
 'pricing_probe.py':('/opt/fs-pricing-alerts/pricing_probe.py','4343d89e9070ae1dd602d252a3d81d114b9e56ddd8eb350e49e6978228797414'),
}

def main():
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    manifest=json.loads((HERE/'final-manifest.json').read_text())
    assert set(manifest)==set(TARGETS)
    for name in TARGETS:
        assert sha(HERE/'source'/name)==manifest[name]
        compile((HERE/'source'/name).read_bytes(),name,'exec')
    atomic=publisher().atomic
    receipt=Path('/var/lib/fs-pricing-alerts/final-consumer-release.json')
    assert not receipt.exists(),'reconcile_original_publication'
    with ExitStack() as held:
        for path in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock','/var/lib/fs-hermes-fc/profile/ops-watchdog/.watch.lock'):
            handle=held.enter_context(Path(path).open('r+b'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert all(sha(Path(path))==before for path,before in TARGETS.values()),'active_source_drift'
        backup=Path('/var/backups/pricing-alert-final-consumers-20261023');backup.mkdir(mode=0o700)
        event=dict(status='started',before={name:before for name,(_,before) in TARGETS.items()},after=manifest,
                   started_at=datetime.now(timezone.utc).isoformat(),price_requests=0,outbox_reset=False)
        atomic(receipt,json.dumps(event).encode(),0o600)
        for name,(path,before) in TARGETS.items():
            target=Path(path)
            atomic(backup/name,target.read_bytes(),0o600)
            assert sha(target)==before
            atomic(target,(HERE/'source'/name).read_bytes(),0o600)
            assert sha(target)==manifest[name]
        event.update(status='deployed_sha_readback_verified',finished_at=datetime.now(timezone.utc).isoformat())
        atomic(receipt,json.dumps(event).encode(),0o600)
    print(json.dumps(event))

if __name__=='__main__':main()
