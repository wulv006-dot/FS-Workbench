"""Correct the view's optional legacy field through the same FC atomic publisher."""
from contextlib import ExitStack
import fcntl,hashlib,importlib.util,json,shutil,subprocess
from pathlib import Path

STAGE=Path(__file__).resolve().parent

def main():
    spec=importlib.util.spec_from_file_location('ui_release',STAGE/'deploy.py')
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    assert base.digest(base.PUBLISHER)==base.PUBLISHER_SHA
    spec=importlib.util.spec_from_file_location('original_fc',base.PUBLISHER)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    target=Path('/opt/fc27-cloud-browser/reference_observer_view.py')
    state=Path('/var/lib/fc27-price-observer')
    receipt=state/'ui-projection-patch.json'
    manifest=json.loads((STAGE/'manifest.json').read_text())
    candidate=STAGE/'fc_reference_observer_ui_20261023/source/reference_observer_view.py'
    assert not receipt.exists(),'reconcile_projection_patch'
    with ExitStack() as held:
        for name in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock',str(state/'lock')):
            handle=held.enter_context(open(name,'a+b'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert base.digest(target)==manifest['after']['reference_observer_view.py']
        assert all(base.digest(p)==v for p,v in manifest['protected'].items())
        compile(candidate.read_bytes(),str(candidate),'exec')
        backup=state/'reference_observer_view-before-optional-field.py';assert not backup.exists()
        shutil.copy2(target,backup)
        event={'operation':'fc-reference-observer-ui-20261023-v1-projection','status':'started',
               'before':base.digest(target),'after':base.digest(candidate),'backup':str(backup)}
        receipt.write_text(json.dumps(event))
        original.publish(candidate,target,target.stat())
        assert base.digest(target)==event['after']
        sys_path='/opt/fc27-cloud-browser'
        spec=importlib.util.spec_from_file_location('view_patch',target)
        view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)
        payload=view.publish_view()
        assert len([r for r in payload['latest_observed']['market'] if r['source']=='Lootbar' and r['status']=='valid'])==3
        subprocess.run(['systemctl','restart','fc27-cloud-api.service'],check=True,timeout=30)
        subprocess.run(['systemctl','is-active','--quiet','fc27-cloud-api.service'],check=True,timeout=10)
        event.update(status='deployed',price_requests=0,model_requests=0,original_sources_unchanged=True)
        receipt.write_text(json.dumps(event));print(json.dumps(event))

if __name__=='__main__':main()
