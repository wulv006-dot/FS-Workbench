"""Three-target admission rollout using the original CAS and native lifecycle."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request

HERE=Path(__file__).resolve().parent
SCOPE='fs-admission-fairness-20261029'
TARGETS={'source/cache_retention.py':'/opt/fs-hermes-fc/cache_retention.py',
         'source/controller.py':'/opt/fs-hermes-fc/controller.py',
         'native/desktop.service':'/etc/systemd/system/fs-hermes-desktop.service'}
UNITS=('fs-hermes-desktop.service','hermes-dingtalk.service')
ENTRY='/opt/hermes/fs_native_entry.py'
BEFORE='sha256:0a6b8e71c8b88db2d008024306c87a7feaeec105b8232598d91df5854374bc3c'
SQLITE_LIBRARY='/opt/auth-portal/registration-runtime-deps/sqlite-3.53.4/lib/libsqlite3.so.0'
SQLITE_SHA='d3d896ba27628b174c67cfc6127c92f29c97b48dc3dfe70c84c5f6c28ca4c5f8'
IMAGE=re.compile(r'sha256:[a-f0-9]{64}')


def digest(raw):return hashlib.sha256(raw).hexdigest()


def checked(manifest,stage):
    if (manifest.get('scope')!=SCOPE or manifest.get('businessWrites') is not False
            or manifest.get('timersChanged') is not False or manifest.get('nativeUnits')!=list(UNITS)
            or len(manifest.get('files',[]))!=3 or {r['candidate']:r['target'] for r in manifest['files']}!=TARGETS
            or any(not r.get('beforeSha256') or r.get('owner')!='0:0' or r.get('mode')!='0o644' for r in manifest['files'])
            or manifest.get('nativeImageBefore')!=BEFORE or not IMAGE.fullmatch(manifest.get('nativeImageAfter',''))
            or manifest['nativeImageAfter']==BEFORE or manifest.get('nativeSQLiteVersion')!='3.53.4'):
        raise ValueError('admission_exact_rollout_required')
    before,after=manifest.get('nativeImageBeforeSources',{}),manifest.get('nativeImageSources',{})
    if (set(before)!=set(after) or ENTRY not in before or len(before)!=4
            or any(not re.fullmatch('[a-f0-9]{64}',v) for v in (*before.values(),*after.values()))
            or before[ENTRY]==after[ENTRY] or any(before[n]!=after[n] for n in before if n!=ENTRY)):
        raise ValueError('admission_only_native_entry_may_change')
    for unit in UNITS:
        if manifest.get('runtimeRequired',{}).get(unit)!={'ActiveState':'active','UnitFileState':'enabled'}:
            raise ValueError('admission_original_native_states_required')
    raw=(Path(stage)/'candidate/native/desktop.service').read_bytes()
    row=next(r for r in manifest['files'] if r['candidate']=='native/desktop.service')
    if (raw.count(manifest['nativeImageAfter'].encode())!=1
            or digest(raw.replace(manifest['nativeImageAfter'].encode(),BEFORE.encode(),1))!=row['beforeSha256']):
        raise ValueError('admission_unit_image_only_delta_required')
    if digest((Path(stage)/'native-image-context/fs_native_entry.py').read_bytes())!=after[ENTRY]:
        raise ValueError('admission_native_source_changed')
    if not all(manifest.get('nativeProtection',{}).get(k) for k in ('metadata','trees')):
        raise ValueError('admission_native_protection_required')
    return manifest


def image_sources(image,names):
    raw=subprocess.check_output(['docker','run','--rm','--read-only','--network','none','--entrypoint','sha256sum',image,*sorted(names)],text=True)
    return {line.split()[1]:line.split()[0] for line in raw.splitlines()}


def compose(base,native,manifest,concurrent,control_factory=None,runtime_path=None):
    """NativeFence must be captured by the existing concurrent adapter, not replace it."""
    native.verify_sqlite_runtime(manifest['nativeSQLiteVersion'])
    native.TARGETS=TARGETS
    base=native.install_native_scope(base,manifest)
    runtime_path=Path(runtime_path) if runtime_path is not None else HERE/'admission-runtime-state.json'
    def record(status,phase,error=None):
        base.no_target_link(runtime_path)
        state=json.loads(runtime_path.read_bytes()) if runtime_path.exists() else {'events':[]}
        event=dict(status=status,phase=phase,at=time.time())
        if error is not None:event['error']=type(error).__name__+':'+str(error)[:240]
        state['events'].append(event);state.update(status=status,phase=phase)
        base.atomic(runtime_path,json.dumps(state,indent=2).encode(),0o600)
    native_restart=base.restart_for
    def restart(value,admission_fence=None):
        record('load_intent','native')
        try:
            if admission_fence is None:raise ValueError('native_admission_fence_required')
            unit=next(r for r in value['files'] if r['candidate']=='native/desktop.service')
            path=base.rooted(admission_fence.root,unit['target']);base.no_target_link(path)
            actual=base.digest(path)
            if actual==unit['sha256']:epoch='sha256'
            elif actual==unit['beforeSha256']:epoch='beforeSha256'
            else:raise ValueError('admission_runtime_sources_not_consistent')
            for row in value['files']:
                path=base.rooted(admission_fence.root,row['target']);base.no_target_link(path)
                if base.digest(path)!=row[epoch]:raise ValueError('admission_runtime_sources_not_consistent')
            native_restart(value,admission_fence)
        except BaseException as error:
            record('unknown-needs-reconcile','native',error);raise
        record('native_image_verified','native')
    base.restart_for=restart
    if control_factory is None:
        class Control(concurrent.SystemControl):
            def restore(self,allow_reader):
                if not allow_reader:
                    record('unknown-needs-reconcile','restore_blocked');return
                try:
                    paused,self.paused=self.paused,[]
                    try:
                        super().restore(allow_reader)
                        for attempt in range(100):
                            try:
                                with urllib.request.urlopen('http://127.0.0.1:8931/health',timeout=1) as response:
                                    if json.load(response).get('ok') is True:break
                            except OSError:pass
                            time.sleep(.1)
                        else:raise ValueError('admission_range_reload_health_unknown')
                    finally:self.paused=paused
                    super().restore(allow_reader)
                    record('all_readers_loaded','range')
                except BaseException as error:
                    record('unknown-needs-reconcile','range',error);raise
        control_factory=Control
    base=concurrent.extend(base,control_factory)
    inspect,guards,validate=base.inspect,base.guards,base.validate
    def validate_all(value,stage):
        checked(value,stage)
        return validate(value,stage)
    def guards_all(value,root,reader_stopped=False):
        native.verify_protection(value,root)
        return guards(value,root,reader_stopped)
    def inspect_all(value,stage,root=Path('/')):
        native.probe_native_database(base,root,value['nativeSQLiteVersion'])
        actual=subprocess.check_output(['docker','inspect','-f','{{.Image}}','fs-hermes-desktop'],text=True).strip()
        if actual!=value['nativeImageBefore']:raise ValueError('admission_native_image_baseline_drift')
        for image,expected in ((value['nativeImageBefore'],value['nativeImageBeforeSources']),(value['nativeImageAfter'],value['nativeImageSources'])):
            if image_sources(image,expected)!=expected:raise ValueError('admission_image_sources_differ')
        return inspect(value,stage,root)
    base.validate,base.guards,base.inspect=validate_all,guards_all,inspect_all
    return base


def load_base():
    approved=checked(json.loads((HERE/'approved-manifest.json').read_text()),HERE)
    if digest(Path(SQLITE_LIBRARY).read_bytes())!=SQLITE_SHA:raise ValueError('admission_sqlite_library_drift')
    import actual_release,transaction_release,concurrent_release
    actual_release.SCOPE,actual_release.TARGETS,actual_release.NEW=SCOPE,TARGETS,frozenset()
    base=actual_release.load_base()
    transaction_release.SCOPE=SCOPE
    base=transaction_release.extend(base)
    raw=(HERE/'native_release_base.py').read_bytes()
    if digest(raw)!=approved['nativeLifecycleSha256']:raise ValueError('admission_native_lifecycle_drift')
    spec=importlib.util.spec_from_file_location('original_native_lifecycle',HERE/'native_release_base.py')
    native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    concurrent_release.SCOPE=SCOPE
    base=compose(base,native,approved,concurrent_release)
    return base


if __name__=='__main__':load_base().main()
