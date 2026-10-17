"""Two-file delta through the restricted four-file history publisher scope."""
import contextlib,hashlib,json,os,re,stat,types
from pathlib import Path
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
HERE=Path(__file__).resolve().parent
CONTROLLER='/opt/fs-hermes-fc/controller.py'
COLLECTOR='/opt/mmoexp-marketing/details/collect_details.py'
MARKETING_LOCK='/opt/mmoexp-marketing/data/verified-readonly/collector.lock'

def load_base():
    path=HERE/'release_navigation_base.py';raw=path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_base_changed')
    base=types.ModuleType('controller_patch_base');base.__file__=str(path);exec(compile(raw,str(path),'exec'),base.__dict__)
    base.HERMES_HISTORY_TARGETS=dict(base.HERMES_HISTORY_TARGETS,**{'contract/details/collect_details.py':COLLECTOR})
    original_target=base.target_for
    base.target_for=lambda rel:COLLECTOR if rel=='contract/details/collect_details.py' else original_target(rel)
    # Frozen base's early News-only gate shadows its existing history branch.
    base.expected_files=lambda manifest:set(base.HERMES_HISTORY_TARGETS) if manifest.get('scope')==base.HERMES_HISTORY_SCOPE else (_ for _ in ()).throw(ValueError('controller_scope_required'))
    original=base.validate
    def validate(manifest,stage):
        if manifest.get('scope')!=base.HERMES_HISTORY_SCOPE or manifest.get('basePublisherSha256')!=BASE_SHA or manifest.get('controllerBridgeSha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('controller_patch_identity')
        if any(manifest.get(k) is not False for k in ('businessWrites','timersChanged','nightlyChanges')):raise ValueError('controller_patch_readonly')
        if not re.fullmatch('[a-f0-9]{40}',manifest.get('sourceCommit','')):raise ValueError('source_commit_required')
        if manifest.get('baselinePending'):raise ValueError('controller_patch_baseline_pending')
        files=original(manifest,stage)
        if any(not row.get('beforeSha256') for row in files):raise ValueError('controller_patch_existing_only')
        if {r['target'] for r in files if r['sha256']!=r['beforeSha256']}!={CONTROLLER,COLLECTOR}:raise ValueError('controller_only_delta_required')
        protected={r['path']:r['sha256'] for r in manifest['unchangedRequired']}
        if protected!=manifest.get('controllerProtectedBaseline'):raise ValueError('controller_protected_baseline_changed')
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
