"""Four exact report-input deltas; preserve controller and inherited admission/rollback fences."""
import contextlib,hashlib,json,os,re,stat,types
from pathlib import Path
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
HERE=Path(__file__).resolve().parent
MARKETING='/opt/fs-hermes-fc/marketing_snapshot.py'
SNAPSHOTS='/opt/fs-hermes-fc/source_snapshots.py'
CONTROLLER='/opt/fs-hermes-fc/controller.py'
EXPECTED_SHA={
 CONTROLLER:'7adfc4bea88e78599766021b79a7c139b3c2bb6725ec9a8892ee0e15990f7f81',
 MARKETING:'46cba455ddcd0a60e4f1b55b3d26453fa02986923528433617a26298d70bdcc6',
 SNAPSHOTS:'2b05df6cce8dc0bff83cfaa1e3698bf916d2f694a7cecec19eeb1ac22130ef96',
 '/opt/fs-hermes-fc/research.py':'d7e334a4e48bf6b5e6376940737dd20d75bfa296fe14f7bde798b44e36d7de4c',
 '/opt/fs-hermes-fc/fs_evidence.py':'1e4b19b95dcb9f9d2a308fb614b88a9d4930316e7a8c5d80f62ea5ec7be6f065'}
DELTAS=set(EXPECTED_SHA)-{CONTROLLER}

MARKETING_LOCK='/opt/mmoexp-marketing/data/verified-readonly/collector.lock'

def load_base():
    path=HERE/'release_navigation_base.py';raw=path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_base_changed')
    base=types.ModuleType('report_inputs_patch_base');base.__file__=str(path);exec(compile(raw,str(path),'exec'),base.__dict__)
    base.HERMES_HISTORY_TARGETS=dict(base.HERMES_HISTORY_TARGETS,**{'hermes/runtime/marketing_snapshot.py':MARKETING,'hermes/runtime/source_snapshots.py':SNAPSHOTS})
    original_target=base.target_for
    base.target_for=lambda rel:base.HERMES_HISTORY_TARGETS[rel] if rel in base.HERMES_HISTORY_TARGETS else original_target(rel)
    # Frozen base's early News-only gate shadows its existing history branch.
    base.expected_files=lambda manifest:set(base.HERMES_HISTORY_TARGETS) if manifest.get('scope')==base.HERMES_HISTORY_SCOPE else (_ for _ in ()).throw(ValueError('report_inputs_scope_required'))
    original=base.validate
    def validate(manifest,stage):
        if manifest.get('scope')!=base.HERMES_HISTORY_SCOPE or manifest.get('basePublisherSha256')!=BASE_SHA or manifest.get('reportInputsBridgeSha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('report_inputs_patch_identity')
        if any(manifest.get(k) is not False for k in ('businessWrites','timersChanged','nightlyChanges')):raise ValueError('report_inputs_patch_readonly')
        if not re.fullmatch('[a-f0-9]{40}',manifest.get('sourceCommit','')):raise ValueError('source_commit_required')
        if manifest.get('baselinePending'):raise ValueError('report_inputs_patch_baseline_pending')
        files=original(manifest,stage)
        if any(not row.get('beforeSha256') for row in files):raise ValueError('report_inputs_patch_existing_only')
        if {r['target']:r['sha256'] for r in files}!=EXPECTED_SHA:raise ValueError('exact_report_input_source_sha_required')
        if {r['target'] for r in files if r['sha256']!=r['beforeSha256']}!=DELTAS:raise ValueError('report_inputs_only_delta_required')
        protected={r['path']:r['sha256'] for r in manifest['unchangedRequired']}
        if protected!=manifest.get('reportProtectedBaseline'):raise ValueError('report_protected_baseline_changed')
        return files
    base.validate=validate
    original_locks=base.locks
    @contextlib.contextmanager
    def locks(root):
        import fcntl
        with original_locks(root):
            path=base.rooted(root,MARKETING_LOCK);base.no_target_link(path)
            fd=os.open(str(path),os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise ValueError('marketing_collector_lock_boundary')
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);yield
            finally:os.close(fd)
    base.locks=locks
    original_guards=base.guards
    def guards(manifest,root,**kwargs):
        original_guards(manifest,root,**kwargs)
        for target in manifest.get('absenceRequired',[]):
            path=base.rooted(root,target)
            if path.exists() or path.is_symlink():raise ValueError('protected_absence_changed')
    base.guards=guards
    return base

if __name__=='__main__':load_base().main()
