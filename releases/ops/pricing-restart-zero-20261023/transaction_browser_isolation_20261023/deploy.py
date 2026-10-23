"""Original transaction lock plus existing atomic publisher; no collector invocation."""
from contextlib import ExitStack
from datetime import datetime,timezone
import fcntl,hashlib,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).parent
TARGET=Path('/opt/fs-transaction-snapshot/collector.py')
RUNNER=TARGET.with_name('order_reader_runner.py')
BEFORE='08b4ca6029c5f81eedc390f918936e1c1295f9669fd523822e952f7c392a9e31'
AFTER='891990d1dd6a21d15eea6bfae619192205e5f689651c6b37a1bca3eca57d9e8e'
PUBLISHER=Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
RECEIPT=Path('/var/lib/fs-order-session/transaction-browser-isolation-20261023.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(apply=False):
    assert not RECEIPT.exists(),'reconcile_original_release'
    manifest=json.loads((ROOT/'manifest.json').read_text())
    assert sha(TARGET)==BEFORE and not RUNNER.exists()
    assert sha(ROOT/'source/order_reader_runner.py')==manifest['runner_sha256']
    spec=importlib.util.spec_from_file_location('reader_candidate',ROOT/'prepare_candidate.py')
    generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
    candidate=ROOT/'collector.candidate.py'
    assert generator.prepare(TARGET,candidate)==AFTER
    assert sha(PUBLISHER)=='b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'
    spec=importlib.util.spec_from_file_location('original_fc_publisher',PUBLISHER)
    publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
    sys.path.insert(0,'/opt/fc27-cloud-browser')
    from snapshot_layer import atomic_json
    with ExitStack() as held:
        for name in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock','/var/www/dashboard/fs-home/transactions/collector.lock'):
            h=held.enter_context(open(name,'a+b'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=subprocess.check_output(['systemctl','show','fs-transaction-collect.service','-p','ActiveState'],text=True,timeout=5).strip()
        assert state in ('ActiveState=inactive','ActiveState=failed'),'original_transaction_cycle_active'
        assert sha(TARGET)==BEFORE and not RUNNER.exists()
        assert all(sha(Path(p))==value for p,value in manifest['protected'].items())
        if not apply:return {'status':'checked','targets':2,'business_requests':0}
        backup=Path('/var/backups/transaction-browser-isolation-20261023');backup.mkdir(mode=0o700)
        shutil.copy2(TARGET,backup/'collector.py')
        event=dict(status='started',operation='transaction-browser-isolation-20261023',before=BEFORE,after=AFTER,
                   runner=manifest['runner_sha256'],price_requests=0,collector_invoked=False,timer_changed=False,
                   started_at=datetime.now(timezone.utc).isoformat())
        atomic_json(RECEIPT,event)
        try:
            info=TARGET.stat()
            publisher.publish(ROOT/'source/order_reader_runner.py',RUNNER,info)
            assert sha(RUNNER)==manifest['runner_sha256']
            publisher.publish(candidate,TARGET,info)
            assert sha(TARGET)==AFTER and all(sha(Path(p))==value for p,value in manifest['protected'].items())
            event.update(status='deployed',finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as error:
            event.update(status='unknown',error=type(error).__name__)
            atomic_json(RECEIPT,event);raise
        atomic_json(RECEIPT,event);return event
if __name__=='__main__':print(json.dumps(main('--apply' in sys.argv)))
