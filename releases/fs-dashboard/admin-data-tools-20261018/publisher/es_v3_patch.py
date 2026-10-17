"""Restricted traffic/ES bridge over the exact existing publisher bytes.

No source/timer schedule changes outside the closed target map. Default is inspect.
"""
import argparse,contextlib,hashlib,json,os,re,stat,subprocess,types
from copy import deepcopy
from pathlib import Path

BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
SCOPE='admin-analysis-20261018-v1'
DOCKER_SHA='09e725135cd34240dbecec42ef226eed7b38a1d727b0fba1a096c4720ac006b0'
HERE=Path(__file__).resolve().parent
SESSION='/opt/fc27-cloud/marketing-session-20261009'
TARGETS={'hermes/es_order_structure.py': '/opt/fs-hermes-fc/es_order_structure.py', 'hermes/research.py': '/opt/fs-hermes-fc/research.py', 'hermes/fs_evidence.py': '/opt/fs-hermes-fc/fs_evidence.py', 'hermes/admin_discount_analysis.py': '/opt/fs-hermes-fc/admin_discount_analysis.py', 'hermes/admin_product_orders.py': '/opt/fs-hermes-fc/admin_product_orders.py', 'session/es_order_structure.py': '/opt/fc27-cloud/marketing-session-20261009/es_order_structure.py', 'session/p2pah_session_service.py': '/opt/fc27-cloud/marketing-session-20261009/p2pah_session_service.py', 'session/admin_discount_analysis.py': '/opt/fc27-cloud/marketing-session-20261009/admin_discount_analysis.py', 'session/admin_product_orders.py': '/opt/fc27-cloud/marketing-session-20261009/admin_product_orders.py', 'session/fc27-p2pah-session.service': '/etc/systemd/system/fc27-p2pah-session.service', 'session/Dockerfile.session': '/opt/fc27-cloud/marketing-session-20261009/Dockerfile.session'}
NEW_ALLOWED={'session/admin_product_orders.py', 'session/admin_discount_analysis.py', 'hermes/admin_discount_analysis.py', 'hermes/admin_product_orders.py'}
EXPECTED_AFTER={'/opt/fs-hermes-fc/es_order_structure.py': 'b8679f8931f7b39020319ddccfe7d1ae1e40262b116fc4f024c37e228968cec1', '/opt/fs-hermes-fc/research.py': 'd1edc7629a8d54553fcd6523b476e07710ceae706d31ca272b3dcfe155b8705e', '/opt/fs-hermes-fc/fs_evidence.py': '2e2f86c1fb2c44072f947074266b13d3de30efeca907b779d153850d6e653e54', '/opt/fs-hermes-fc/admin_discount_analysis.py': 'e43d689746e83ea474432a5aa1f6acf66cb8732172035b86e6f4e7df12d9ad98', '/opt/fs-hermes-fc/admin_product_orders.py': 'cc9d8afb240a63a98c417e129d5720fcb15e41c43546c0dc6cbf2a379950550d', '/opt/fc27-cloud/marketing-session-20261009/es_order_structure.py': 'b8679f8931f7b39020319ddccfe7d1ae1e40262b116fc4f024c37e228968cec1', '/opt/fc27-cloud/marketing-session-20261009/p2pah_session_service.py': '7c1482d630d814f2fa3a0de30579b19aebf35abaaa187cf0d08d3ab3051ee0ab', '/opt/fc27-cloud/marketing-session-20261009/admin_discount_analysis.py': 'e43d689746e83ea474432a5aa1f6acf66cb8732172035b86e6f4e7df12d9ad98', '/opt/fc27-cloud/marketing-session-20261009/admin_product_orders.py': 'cc9d8afb240a63a98c417e129d5720fcb15e41c43546c0dc6cbf2a379950550d', '/etc/systemd/system/fc27-p2pah-session.service': '240cafc7b4b9a3e8b625099a495c9df95698e56b58abfaf93e9a82c0af81dd6a', '/opt/fc27-cloud/marketing-session-20261009/Dockerfile.session': '09e725135cd34240dbecec42ef226eed7b38a1d727b0fba1a096c4720ac006b0'}
MARKETING_LOCK='/opt/mmoexp-marketing/data/verified-readonly/collector.lock'
PRESERVED=('/opt/fs-hermes-fc/nightly.py','/opt/fs-hermes-fc/source_snapshots.py','/var/lib/fs-hermes-fc/fs/nightly-schedule.json','/var/lib/fs-hermes-fc/fs/maintenance-resume-20261017.json','/etc/systemd/system/fs-marketing-range.service')
ABSENT='/var/lib/fs-hermes-fc/fs/nightly-schedule.maintenance-paused-20261016.json'
TIMERS=('mmoexp-marketing-daily.timer','fs-boss-game-monitor.timer','fs-boss-management.timer')
RUNTIME={'fs-business-range.service':{'ActiveState':'active'},'fs-hermes-fc.service':{'ActiveState':'active'},'fc27-p2pah-session.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'},'mmoexp-marketing-daily.service':{'ActiveState':'inactive'}}


def reviewed_leaf(manifest):
    path=HERE/'es_v3_image_lifecycle.py';raw=path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest()!=manifest.get('imageLifecycleSha256'):raise ValueError('es_lifecycle_source_changed')
    module=types.ModuleType('_reviewed_es_image_leaf');exec(compile(raw,str(path),'exec'),module.__dict__)
    return module



def load_base():
    path=HERE/'release_navigation_base.py';raw=path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_base_publisher_changed')
    source=raw.decode('utf-8')
    # Six explicit source seams; the original journal/CAS/admission/rollback code is intact.
    edits=[("r['candidate']=='source/source_snapshots.py'","r['candidate'] in TRAFFIC_NEW"),
        ("   if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_apply(manifest,backup,journal,root)","   traffic_apply(manifest,backup,journal,root)\n   if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_apply(manifest,backup,journal,root)"),
        (" journal['status']='rolled-back';journal_write(backup,journal)"," traffic_restore(backup,journal,root)\n journal['status']='rolled-back';journal_write(backup,journal)")]
    edits.append(("ordered=sorted(journal['files'],key=lambda row:(row['candidate']=='fs-home/index.html',row['candidate']=='hubnav.js',row['candidate']))","ordered=sorted(journal['files'],key=traffic_install_key)"))
    edits.append(("   if manifest.get('scope')==TITLE_GOAL_SCOPE:admission_fence.stop_then_unlock_database()","   if manifest.get('scope')==TITLE_GOAL_SCOPE:admission_fence.stop_then_unlock_database()\n   traffic_before_write(manifest,backup,journal,root)"))
    edits.append(("  rollback_credentials(backup,journal,approved_sha)","  if journal.get('status')=='applied-awaiting-actual-http-role-acceptance':raise ValueError('completed_release_manual_full_rollback_refused; keep_contract_phase_forward_fix_or_UI_only_revert')\n  rollback_credentials(backup,journal,approved_sha)"))
    for before,after in edits:
        if source.count(before)!=1:raise ValueError('frozen_publisher_seam_changed')
        source=source.replace(before,after)
    base=types.ModuleType('_reviewed_traffic_base');base.__file__=str(path);base.TRAFFIC_NEW=NEW_ALLOWED
    exec(compile(source,str(path),'exec'),base.__dict__)
    base.TITLE_GOAL_SCOPE=SCOPE;base.TITLE_GOAL_TARGETS=TARGETS
    active_fence={}
    inherited_fence=base.hermes_admission_fence
    @contextlib.contextmanager
    def fence(manifest,root):
        with inherited_fence(manifest,root) as value:
            active_fence['value']=value
            try:yield value
            finally:active_fence.pop('value',None)
    base.hermes_admission_fence=fence
    def reader_stop(self):
        expected=current['journal']['manifest']['businessStopContract']['properties']
        fields=('Id','KillMode','ControlGroup','FragmentPath','DropInPaths','UnitFileState')
        raw=subprocess.check_output(['systemctl','show','fs-business-range.service',*[v for k in fields for v in ('-p',k)]],text=True,timeout=15)
        actual=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        if any(actual.get(k)!=expected.get(k) for k in fields if k!='ControlGroup') or actual.get('ControlGroup') not in ('',expected['ControlGroup']):raise ValueError('business_reader_identity_drift')
        subprocess.run(['systemctl','stop','fs-business-range.service'],check=True,timeout=35)
        raw=subprocess.check_output(['systemctl','show','fs-business-range.service','-p','ActiveState','-p','MainPID'],text=True,timeout=15)
        props=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        if props!={'ActiveState':'inactive','MainPID':'0'}:raise ValueError('business_reader_stop_unknown')
        cgroup=self.root/current['journal']['manifest']['businessStopContract']['cgroupPath'].lstrip('/')
        if any(p.is_symlink() for p in (cgroup,*cgroup.parents)) or cgroup.exists() and cgroup.read_text().strip() or not cgroup.exists() and cgroup.parent.exists():raise ValueError('business_reader_residual_or_unknown')
        self.unlock_database()
    base.HermesAdmissionFence.stop_then_unlock_database=reader_stop

    def install_key(row):
        name=row['candidate']
        return (0 if name.endswith('/traffic_contract.py') else 1 if name.startswith('contract/') else 2 if name.endswith(('/es_order_structure.py','/action_ledger.py')) else 5 if name=='hermes/brain.js' else 4 if name.startswith('session/') else 3,name)
    base.traffic_install_key=install_key
    original_validate=base.validate
    def validate(manifest,stage):
        if manifest.get('baselinePending'):raise ValueError('read_only_baselines_pending')
        if manifest.get('scope')!=SCOPE or manifest.get('basePublisherSha256')!=BASE_SHA or manifest.get('publisherBridgeSha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('restricted_bridge_identity')
        if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False or manifest.get('nightlyChanges') is not False:raise ValueError('readonly_schedule_contract')
        if not re.fullmatch('[a-f0-9]{40}',manifest.get('sourceCommit','')):raise ValueError('source_commit_required')
        expected_runtime=dict(RUNTIME,**{name:{'ActiveState':'active','SubState':'waiting','UnitFileState':'enabled'} for name in TIMERS})
        if manifest.get('runtimeRequired')!=expected_runtime:raise ValueError('exact_runtime_preconditions')
        protected={r['path']:r['sha256'] for r in manifest['unchangedRequired']}
        if any(not protected.get(path) for path in PRESERVED) or manifest.get('absenceRequired')!=[ABSENT]:raise ValueError('nightly_and_range_preservation_contract')
        business=manifest.get('businessStopContract') or {}
        bp=business.get('properties') or {}
        if bp.get('Id')!='fs-business-range.service' or bp.get('KillMode')!='control-group' or bp.get('ControlGroup')!='/system.slice/fs-business-range.service' or business.get('cgroupPath')!='/sys/fs/cgroup/systemd/system.slice/fs-business-range.service/cgroup.procs':raise ValueError('business_reader_contract_missing')
        if any(not protected.get(p) for p in [bp.get('FragmentPath'),*bp.get('DropInPaths','').split()]):raise ValueError('business_reader_unit_baselines_missing')
        if manifest.get('imageId')!='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544':raise ValueError('hermes_image_contract')
        leaf=reviewed_leaf(manifest)
        files=original_validate(manifest,stage)
        if {r['target']:r['sha256'] for r in files}!=EXPECTED_AFTER:raise ValueError('exact_v3_after_sha_required')
        rows={r['candidate']:r for r in files}
        for candidate,row in rows.items():
            if row['beforeSha256'] is None and candidate not in NEW_ALLOWED:raise ValueError('new_file_outside_whitelist')
        # Three identical rule copies and the paired ES reader cannot drift.
        for candidates in [('hermes/'+n,'session/'+n) for n in ('es_order_structure.py','admin_discount_analysis.py','admin_product_orders.py')]:
            if len({rows[n]['sha256'] for n in candidates})!=1:raise ValueError('paired_shared_source_mismatch')
        unit=(stage/'candidate/session/fc27-p2pah-session.service').read_bytes()
        reconstructed=unit.replace(leaf.NEW_TAG.encode(),leaf.OLD_TAG.encode())
        if unit.count(leaf.NEW_TAG.encode())!=1 or unit.count(b' --mount type=bind,src=/var/lib/fc27-es-exports,dst=/var/lib/fc27-es-exports')!=1 or hashlib.sha256(reconstructed).hexdigest()!=rows['session/fc27-p2pah-session.service']['beforeSha256']:raise ValueError('session_unit_expanded_scope')
        if rows['session/Dockerfile.session']['sha256']!=DOCKER_SHA:raise ValueError('session_dockerfile_contract')
        return files
    base.validate=validate
    original_credentials=base.rollback_credentials
    def rollback_credentials(backup,journal,approved_sha):
        manifest=journal['manifest']
        if manifest.get('scope')!=SCOPE or manifest.get('basePublisherSha256')!=BASE_SHA or manifest.get('publisherBridgeSha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('rollback_bridge_identity')
        reviewed_leaf(manifest)
        return original_credentials(backup,journal,approved_sha)
    base.rollback_credentials=rollback_credentials
    current={'journal':None,'backup':None}
    original_write=base.journal_write
    def journal_write(backup,journal):
        if journal['manifest'].get('scope')==SCOPE:current.update(journal=journal,backup=backup)
        return original_write(backup,journal)
    base.journal_write=journal_write
    original_guards=base.guards
    def guards(manifest,root,reader_stopped=False):
        journal=current['journal']
        adjusted=manifest
        if journal and journal.get('marketingStopped'):
            adjusted=deepcopy(manifest);adjusted['runtimeRequired']['fs-marketing-range.service']={'ActiveState':'inactive'}
        result=original_guards(adjusted,root,reader_stopped)
        attempts=root/'var/lib/fs-hermes-fc/fs/es-structures'
        if any(attempts.glob('*.attempt')):raise ValueError('es_attempt_requires_readonly_reconcile_before_session_restart')
        for path in manifest.get('absenceRequired',[]):
            target=base.rooted(root,path);base.no_target_link(target)
            if target.exists():raise ValueError('preserved_absence_drift')
        return result
    base.guards=guards
    def before_write(manifest,backup,journal,root):
        return None
    base.traffic_before_write=before_write
    original_rollback=base.rollback_journal
    def rollback_journal(backup,journal,root):
        current.update(journal=journal,backup=backup)
        if any(r.get('intent') for r in journal['files']):
            fence=active_fence.get('value')
            if fence is None:raise ValueError('rollback_requires_current_admission_fence')
            fence.stop_then_unlock_database()
        return original_rollback(backup,journal,root)
    base.rollback_journal=rollback_journal
    original_inspect=base.inspect
    def inspect(manifest,stage,root=Path('/')):
        result=original_inspect(manifest,stage,root);reviewed_leaf(manifest).baseline(manifest,root)
        return dict(result,scope=SCOPE,basePublisherSha256=BASE_SHA,sessionImageCAS='passed',archivePolicy='512MiB/512files; preserve evidence',timersChanged=False)
    base.inspect=inspect
    base.traffic_apply=lambda m,b,j,r:reviewed_leaf(m).apply(m,b,j,r,base.atomic,base.journal_write,base.digest,base.no_target_link)
    base.traffic_restore=lambda b,j,r:reviewed_leaf(j['manifest']).restore(b,j,r,base.journal_write)
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
    return base


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',nargs='?',choices=['inspect','apply','rollback'],default='inspect');parser.add_argument('--manifest',type=Path,default=HERE.parent/'approved-manifest.json');parser.add_argument('--approved-manifest-sha');parser.add_argument('--release-id');parser.add_argument('--backup',type=Path)
    args=parser.parse_args();base=load_base()
    if args.action!='inspect' and os.name!='posix':raise ValueError('mutations_require_linux')
    if args.action=='rollback':
        if not args.backup or args.backup.parent!=Path('/var/backups/fs-navigation-20261006'):raise ValueError('exact_backup_parent_required')
        result=base.rollback(args.backup,args.approved_manifest_sha)
    else:
        raw=args.manifest.read_bytes();manifest=json.loads(raw)
        result=base.inspect(manifest,args.manifest.parent) if args.action=='inspect' else base.apply(manifest,args.manifest.parent,args.approved_manifest_sha,raw,args.release_id)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
