"""Exact read-only UI adapter of the original FC atomic publisher and locks."""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

STAGE = Path(__file__).resolve().parent
PUBLISHER = Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
PUBLISHER_SHA = 'b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'
OPERATION = 'fc-reference-observer-ui-20261023-v1'
RECEIPT_NAME = 'ui-recovery-deployment.json'
TARGETS = {'fc27_cloud_api.py':'/opt/fc27-cloud-browser/fc27_cloud_api.py',
           'reference_observer_view.py':'/opt/fc27-cloud-browser/reference_observer_view.py',
           'fc27-coins.html':'/var/www/dashboard/fc27-coins.html',
           'fc27-reference-observer.js':'/var/www/dashboard/fc27-reference-observer.js',
           'observe.py':'/opt/fc27-price-observer/observe.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(apply=False):
    manifest=json.loads((STAGE/'manifest.json').read_text())
    assert manifest['targets']==TARGETS and digest(PUBLISHER)==PUBLISHER_SHA
    spec=importlib.util.spec_from_file_location('original_fc_publisher',PUBLISHER)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    receipt=Path('/var/lib/fc27-price-observer')/RECEIPT_NAME
    assert not receipt.exists(),'reconcile_original_ui_release'
    with ExitStack() as held:
        for path in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock',
                     '/var/lib/fc27-price-observer/lock'):
            handle=held.enter_context(open(path,'a+b'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        held.enter_context(original.api.queue_mutation())
        for name in original.tick.RETRY_LOCKS:
            handle=held.enter_context((original.ROOT/'state'/name).open('r+b'))
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert original.tick.retry_guard()=='ready' and not list((original.ROOT/'queue').glob('*.json'))
        assert original.api.health()['incomplete_executions']==0
        assert not any(original.api.read_json(p).get('status') in ('running','queued') for p in (original.ROOT/'jobs').glob('*.json'))
        assert subprocess.check_output(['systemctl','show','fc27-price-observer.service','-p','ActiveState'],text=True).strip() not in ('ActiveState=active','ActiveState=activating')
        for name,target in TARGETS.items():
            path=Path(target)
            assert not path.is_symlink()
            assert (digest(path) if path.exists() else None)==manifest['before'][name],'target_drift:'+name
            assert digest(STAGE/'source'/name)==manifest['after'][name],'candidate_drift:'+name
            if name.endswith('.py'):compile((STAGE/'source'/name).read_bytes(),name,'exec')
        assert all(digest(p)==v for p,v in manifest['protected'].items()),'protected_drift'
        if not apply:return {'status':'checked','targets':len(TARGETS),'price_requests':0}
        backup=Path('/var/lib/fc27-price-observer')/('ui-backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        backup.mkdir(mode=0o700)
        info={name:Path(target).stat() if Path(target).exists() else None for name,target in TARGETS.items()}
        for name,target in TARGETS.items():
            if info[name]:shutil.copy2(target,backup/name)
        event={'operation':OPERATION,'status':'started','backup':str(backup),
               'before':manifest['before'],'after':manifest['after'],'price_requests':0,'model_requests':0,'original_schedule_changed':False}
        receipt.write_text(json.dumps(event))
        installed=[]
        try:
            for name,target in TARGETS.items():
                original.publish(STAGE/'source'/name,Path(target),info[name]);installed.append(name)
                assert digest(target)==manifest['after'][name]
            sys.path.insert(0,'/opt/fc27-cloud-browser')
            from reference_observer_view import publish_view
            exported=publish_view()
            probe=subprocess.run(['/usr/sbin/runuser','-u','fc27api','--','/usr/bin/python3','-B','-c',
                                  'import sys;sys.path.insert(0,"/opt/fc27-cloud-browser");from reference_observer_view import read_view;assert read_view()["simulation_only"] is True'],
                                 capture_output=True,text=True,timeout=10)
            assert probe.returncode==0,'projection_permission_probe_failed'
            subprocess.run(['systemctl','restart','fc27-cloud-api.service'],check=True,timeout=30)
            subprocess.run(['systemctl','is-active','--quiet','fc27-cloud-api.service'],check=True,timeout=10)
            subprocess.run(['systemctl','reset-failed','fc27-price-observer.service'],check=True,timeout=10)
            assert all(digest(p)==v for p,v in manifest['protected'].items())
            event.update(status='deployed',exported_samples=exported['window_count'],observed_samples=exported['observed_count'],
                         original_sources_unchanged=True,observer_manually_started=False,
                         completed_at=datetime.now(timezone.utc).isoformat())
            receipt.write_text(json.dumps(event));return event
        except Exception:
            for name in reversed(installed):
                target=Path(TARGETS[name]);assert digest(target)==manifest['after'][name],'concurrent_rollback_refused'
                if info[name]:original.publish(backup/name,target,info[name])
                else:target.unlink()
            subprocess.run(['systemctl','restart','fc27-cloud-api.service'],check=True,timeout=30)
            event['status']='rolled_back';receipt.write_text(json.dumps(event));raise


if __name__=='__main__':print(json.dumps(main('--apply' in sys.argv)))
