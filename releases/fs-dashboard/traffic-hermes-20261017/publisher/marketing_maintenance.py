"""Bounded maintenance stop of the read-only range service, never its collector/timers."""
import hashlib,json,os,stat,subprocess,time,urllib.request,urllib.error
from pathlib import Path

UNIT='fs-marketing-range.service'
FIELDS=('MainPID','ControlGroup','KillMode','Id','ActiveState','SubState','FragmentPath','DropInPaths','UnitFileState')


def state(unit):
    raw=subprocess.check_output(['systemctl','show',unit,'--no-pager',*[v for name in FIELDS for v in ('-p',name)]],text=True,timeout=15)
    return dict(line.split('=',1) for line in raw.splitlines() if '=' in line)


def unit_identity(manifest,root):
    expected=manifest['marketingStopContract']['properties'];actual=state(UNIT)
    for name in ('KillMode','Id','FragmentPath','DropInPaths','UnitFileState'):
        if actual.get(name)!=expected.get(name):raise ValueError('marketing_unit_identity_drift')
    protected={row['path']:row['sha256'] for row in manifest['unchangedRequired']}
    for name in [actual['FragmentPath'],*actual.get('DropInPaths','').split()]:
        source=root/name.lstrip('/')
        if any(p.is_symlink() for p in (source,*source.parents)) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=protected.get(name):raise ValueError('marketing_unit_source_sha_drift')
    return actual


def identity(manifest,root,original_pid=False):
    contract=manifest['marketingStopContract'];expected=contract['properties'];actual=unit_identity(manifest,root)
    if actual.get('ControlGroup')!=expected['ControlGroup']:raise ValueError('marketing_unit_identity_drift')
    if actual.get('ActiveState')!='active' or actual.get('SubState')!='running' or not actual.get('MainPID','').isdigit() or int(actual['MainPID'])<=0:raise ValueError('marketing_not_running_before_controlled_stop')
    if original_pid and actual['MainPID']!=expected['MainPID']:raise ValueError('marketing_main_pid_drift')
    group=expected['ControlGroup'];path=contract['cgroupPath']
    if expected['KillMode']!='control-group' or group!='/system.slice/'+UNIT or path not in ('/sys/fs/cgroup'+group+'/cgroup.procs','/sys/fs/cgroup/systemd'+group+'/cgroup.procs'):raise ValueError('marketing_cgroup_contract')
    daily=state('mmoexp-marketing-daily.service')
    if daily.get('ActiveState')!='inactive' or daily.get('MainPID')!='0' or daily.get('ControlGroup')==group:raise ValueError('daily_collector_not_separate_and_idle')
    proc=root/('proc/'+actual['MainPID']+'/cgroup')
    if not any(line.rsplit(':',1)[-1]==group for line in proc.read_text().splitlines()):raise ValueError('marketing_pid_cgroup_drift')
    processes=cgroup_pids(root,path)
    if int(actual['MainPID']) not in processes:raise ValueError('marketing_cgroup_missing_main_pid')
    return actual


def cgroup_pids(root,path):
    target=root/path.lstrip('/')
    if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('marketing_cgroup_symlink')
    if not target.exists():
        if target.parent.exists():raise ValueError('marketing_cgroup_file_unknown')
        return []
    raw=target.read_text().split()
    if any(not value.isdecimal() or int(value)<=0 for value in raw):raise ValueError('marketing_cgroup_pid_invalid')
    return [int(v) for v in raw]


def stopped(manifest,root):
    actual=unit_identity(manifest,root)
    if actual.get('ControlGroup') not in ('',manifest['marketingStopContract']['properties']['ControlGroup']):raise ValueError('marketing_inactive_cgroup_identity_drift')
    if actual.get('ActiveState')!='inactive' or actual.get('MainPID')!='0' or cgroup_pids(root,manifest['marketingStopContract']['cgroupPath']):raise ValueError('marketing_stop_outcome_unknown_or_residual')


def stop(manifest,backup,journal,root,write,rollback=False):
    if journal.get('marketingStopUnknown'):raise ValueError('marketing_previous_stop_unknown_requires_reconcile')
    identity(manifest,root,original_pid=not rollback)
    journal.update(marketingStopIntent=True,marketingStopped=False);write(backup,journal)
    try:
        subprocess.run(['systemctl','stop',UNIT],check=True,timeout=35)
        stopped(manifest,root)
    except (OSError,ValueError,subprocess.SubprocessError):
        journal['marketingStopUnknown']=True;write(backup,journal);raise ValueError('marketing_stop_unknown_zero_replacement_requires_reconcile')
    journal.update(marketingStopped=True,marketingStopUnknown=False);write(backup,journal)


def ensure_stopped(manifest,backup,journal,root,write):
    # A persisted true can precede a successful start whose journal write was lost.
    actual=state(UNIT)
    if actual.get('ActiveState')=='inactive' and actual.get('MainPID')=='0':
        stopped(manifest,root)
        journal.update(marketingStopped=True,marketingStopUnknown=False);write(backup,journal)
        return
    if actual.get('ActiveState')!='active':raise ValueError('marketing_rollback_state_unknown_no_file_restore')
    identity(manifest,root,original_pid=False)
    if journal.get('marketingStopUnknown'):
        journal.update(marketingPreviousStopUnknown=True,marketingStopUnknown=False);write(backup,journal)
    stop(manifest,backup,journal,root,write,rollback=True)


def start(manifest,backup,journal,root,write):
    stopped(manifest,root)
    journal['marketingStartIntent']=True;write(backup,journal)
    try:
        subprocess.run(['systemctl','start',UNIT],check=True,timeout=35)
        subprocess.run(['systemctl','is-active','--quiet',UNIT],check=True,timeout=10)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8935/range',timeout=min(1,max(.01,deadline-time.monotonic()))):raise ValueError('anonymous_marketing_unexpected_success')
            except urllib.error.HTTPError as error:
                try:
                    if error.code!=401:raise ValueError('marketing_health_denial_contract')
                finally:
                    if error.fp is not None:error.close()
                journal['marketingHealth']='anonymous_401';break
            except OSError:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ValueError('marketing_health_timeout')
                time.sleep(min(.2,remaining))
        else:raise ValueError('marketing_health_timeout')
    except (OSError,ValueError,subprocess.SubprocessError):
        journal.update(marketingStopped=False,marketingStartUnknown=True,marketingHealth='failed_to_verify');write(backup,journal);raise
    journal.update(marketingStopped=False,marketingStartUnknown=False,marketingRestoredActive=True);write(backup,journal)
