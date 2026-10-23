"""Single-file adapter of the original FC publisher; original business locks remain."""
from contextlib import ExitStack
from datetime import datetime,timezone
import fcntl,hashlib,importlib.util,json,shutil,sys
from pathlib import Path
STAGE=Path(__file__).resolve().parent
TARGET=Path('/opt/fc27-cloud-browser/browser_lifecycle.py')
BEFORE='2f4a9b7cd6a73f2b09e16379a3ce8d4af29e1edbc748f6215c5b1c320ea92d3c'
HELPER=TARGET.with_name('browser_probe.js')
HELPER_BEFORE='89e6e7a0c8b1bbc30f2520e07fc2fb4aa39d54bf4fa445f890973b05a91d4c6d'
PUBLISHER=Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(apply=False):
    manifest=json.loads((STAGE/'manifest.json').read_text())
    assert sha(PUBLISHER)=='b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'
    spec=importlib.util.spec_from_file_location('original_fc_publisher',PUBLISHER)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    sys.path.insert(0,'/opt/fc27-cloud-browser')
    from snapshot_layer import atomic_json
    receipt=original.ROOT/'recovery-receipts/restart-idle-release-20261023-v5.json'
    assert not receipt.exists(),'reconcile_original_release_before_retry'
    with ExitStack() as held:
        for path in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock'):
            h=held.enter_context(open(path,'a+b'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
        held.enter_context(original.api.queue_mutation())
        for name in original.tick.RETRY_LOCKS:
            h=held.enter_context((original.ROOT/'state'/name).open('rb'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert original.tick.retry_guard()=='ready' and not list((original.ROOT/'queue').glob('*.json'))
        assert original.api.health()['incomplete_executions']==0
        assert not any(original.api.read_json(p).get('status') in ('running','queued') for p in (original.ROOT/'jobs').glob('*.json'))
        assert sha(TARGET)==BEFORE and sha(STAGE/'source/browser_lifecycle.py')==manifest['after']
        assert sha(HELPER)==HELPER_BEFORE and sha(STAGE/'source/browser_probe.js')==manifest['helper_after']
        assert all(sha(Path(p))==s for p,s in manifest['protected'].items())
        compile((STAGE/'source/browser_lifecycle.py').read_bytes(),'candidate','exec')
        if not apply:return {'status':'checked','targets':2}
        backup=original.ROOT/'rollback/restart-idle-release-20261023-v5'
        backup.mkdir(mode=0o700)
        shutil.copy2(TARGET,backup/TARGET.name)
        shutil.copy2(HELPER,backup/HELPER.name)
        # Preserve the complete original event before the natural tick appends release proof.
        shutil.copy2(original.ROOT/'state/browser-lifecycle.json',backup/'browser-lifecycle-before.json')
        event=dict(status='started',before=BEFORE,after=manifest['after'],backup=str(backup),
                   price_requests=0,model_requests=0,services_restarted=False,started_at=datetime.now(timezone.utc).isoformat())
        atomic_json(receipt,event)
        try:
            original.publish(STAGE/'source/browser_probe.js',HELPER,TARGET.stat())
            assert sha(HELPER)==manifest['helper_after']
            original.publish(STAGE/'source/browser_lifecycle.py',TARGET,TARGET.stat())
            assert sha(TARGET)==manifest['after']
            assert all(sha(Path(p))==s for p,s in manifest['protected'].items())
            event.update(status='deployed',completed_at=datetime.now(timezone.utc).isoformat())
        except Exception:
            if sha(TARGET)==manifest['after']:
                original.publish(backup/TARGET.name,TARGET,TARGET.stat())
                event['status']='rolled_back'
            else:event['status']='unknown'
            if sha(HELPER)==manifest['helper_after']:
                original.publish(backup/HELPER.name,HELPER,HELPER.stat())
            atomic_json(receipt,event)
            raise
        atomic_json(receipt,event)
        return event
if __name__=='__main__':print(json.dumps(main('--apply' in sys.argv)))
