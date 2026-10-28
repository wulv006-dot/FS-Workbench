"""Seven existing readers through the original CAS/journal/rollback publisher."""
from contextlib import contextmanager, ExitStack
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import threading

SCOPE='business-reader-concurrency-20261029'
TARGETS={**{'source/'+name:'/opt/fs-exact-range-20261001/'+name for name in
    ('live_summary.py','actual_profit.py','range_api.py')},
    **{'source/'+name:'/opt/fs-hermes-fc/'+name for name in ('channel_effects.py','cache_retention.py')},
    **{'source/'+name:'/opt/fs-transaction-snapshot/'+name for name in ('collector.py','atomic_snapshot.py')}}
NEW=frozenset()
RANGE='fs-business-range.service'
TIMERS=('fs-channel-cache.timer','fs-channel-backfill.timer','fs-data-archive.timer',
        'fs-transaction-collect.timer','fs-user-analytics.timer')
SOURCES=tuple(name.replace('.timer','.service') for name in TIMERS)
LEGACY_LOCKS=('/var/lib/fs-channel-effects/collector.lock','/var/lib/fs-channel-effects/order-deliveries.lock')
ADMISSION='/var/lib/fs-hermes-fc/fs/admission.lock'
QUERY_ROOTS=('/var/lib/fs-channel-effects','/var/lib/fs-channel-effects/actual-profit')


class SystemControl:
    """Only original source timers and the original range reader are controlled."""
    def __init__(self,root):
        if Path(root).resolve()!=Path('/'):raise ValueError('p4_live_control_requires_system_root')
        self.before={};self.paused=[]

    def state(self,unit):
        raw=subprocess.check_output(['systemctl','show',unit,'--no-pager','-p','LoadState',
            '-p','ActiveState','-p','SubState','-p','MainPID','-p','ControlPID','-p','UnitFileState'],text=True)
        value=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        if value.get('LoadState')!='loaded' or not value.get('UnitFileState'):raise ValueError('p4_source_unit_unavailable')
        return value

    def idle(self):
        for unit in SOURCES:
            value=self.state(unit)
            if (value.get('MainPID')!='0' or value.get('ControlPID')!='0'
                    or value.get('ActiveState') not in ('inactive','failed')):
                raise ValueError('p4_source_still_running')
        jobs=subprocess.check_output(['systemctl','list-jobs','--no-pager','--no-legend'],text=True)
        if any(unit in line.split() for line in jobs.splitlines() for unit in SOURCES):
            raise ValueError('p4_source_job_pending')
        # Read only the interpreter/script prefix; never read later business arguments.
        scripts={'/opt/fs-hermes-fc/channel_cache.py','/opt/fs-exact-range-20261001/archive_jobs.py',
                 '/opt/fs-transaction-snapshot/collector.py','/opt/fs-hermes-fc/user_jobs.py'}
        for process in Path('/proc').iterdir():
            if not process.name.isdecimal():continue
            try:
                with (process/'cmdline').open('rb') as stream:
                    for index in range(8):
                        word=bytearray()
                        while len(word)<1024:
                            char=stream.read(1)
                            if char in (b'',b'\0'):break
                            word.extend(char)
                        arg=os.fsdecode(word)
                        if index==0 and not Path(arg).name.startswith('python'):break
                        if not arg or arg in ('-c','-m'):break
                        if arg.endswith('.py'):
                            if arg in scripts:raise ValueError('p4_legacy_source_process_running')
                            break
            except (FileNotFoundError,ProcessLookupError):pass

    def remember(self,manifest):
        expected=manifest.get('maintenanceBefore',{})
        self.before={unit:self.state(unit) for unit in (*TIMERS,RANGE)}
        for unit,value in self.before.items():
            old=expected.get(unit)
            # Approved manifest is the durable pre-maintenance recovery record.
            if not isinstance(old,dict) or not {'ActiveState','UnitFileState'}<=set(old):raise ValueError('p4_original_unit_states_required')
            if any(value.get(k)!=v for k,v in old.items()):raise ValueError('p4_original_unit_state_drift')
        if self.before[RANGE].get('ActiveState')!='active':raise ValueError('p4_original_reader_not_active')

    def preview(self,manifest):
        self.remember(manifest)
        self.idle()
        value=self.state(RANGE)
        if value.get('ActiveState')!='active' or value.get('MainPID') in ('','0',None):raise ValueError('p4_original_reader_not_active')

    def pause(self,manifest):
        self.remember(manifest)
        for unit in TIMERS:
            if self.before[unit]['ActiveState']=='active':
                self.paused.append(unit)
                subprocess.run(['systemctl','stop',unit],check=True,timeout=20)
        self.idle()  # A running source is deferred, never stopped or force-killed.

    def stopped(self):
        value=self.state(RANGE)
        if value.get('ActiveState')!='inactive' or value.get('MainPID')!='0' or value.get('ControlPID')!='0':
            raise ValueError('p4_reader_stop_not_confirmed')
        if value.get('UnitFileState')!=self.before[RANGE]['UnitFileState']:raise ValueError('p4_unit_enable_state_changed')

    def restore(self,allow_reader):
        if not allow_reader:return  # Unconfirmed code/rollback must not reopen source timers either.
        errors=[]
        for unit in (RANGE,*self.paused):
            if unit not in self.before:continue
            try:
                old=self.before[unit];current=self.state(unit)
                if current['UnitFileState']!=old['UnitFileState']:raise ValueError('p4_unit_enable_state_changed')
                if old['ActiveState']=='active' and current['ActiveState']!='active':
                    subprocess.run(['systemctl','start',unit],check=True,timeout=30)
                    if self.state(unit)['ActiveState']!='active':raise ValueError('p4_original_active_state_not_restored')
            except Exception:errors.append(unit)
        if errors:raise ValueError('p4_original_states_restore_incomplete:'+','.join(errors))


@contextmanager
def lease(base,root,name):
    import fcntl
    path=base.rooted(root,name);base.no_target_link(path)
    fd=os.open(path,os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
    try:
        info=os.fstat(fd);current=path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1
                or info.st_mode&0o022 or (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino)):
            raise ValueError('p4_unsafe_source_lock')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('p4_source_or_query_busy') from None
        yield
    finally:os.close(fd)


def extend(base,control_factory=SystemControl):
    if base.HERMES_HISTORY_SCOPE!=SCOPE:raise ValueError('p4_original_scope_not_bound')
    original_live,original_inspect=base.live_lock,base.inspect
    original_admission,original_guards=base.hermes_admission_fence,base.guards
    original_rollback=base.rollback_journal
    owned=threading.local()

    def current(root):
        return getattr(owned,'root',None)==Path(root).resolve()

    @contextmanager
    def live_lock(manifest,root):
        if manifest.get('scope')!=SCOPE:
            with original_live(manifest,root):yield
            return
        control=control_factory(root);fence=None
        try:
            control.remember(manifest)
            with original_admission(manifest,root) as fence,ExitStack() as stack:
                if fence is None:raise ValueError('p4_original_admission_fence_required')
                control.pause(manifest)
                for path in LEGACY_LOCKS:stack.enter_context(lease(base,root,path))
                # The reused transaction adapter holds snapshot before original WEB.
                stack.enter_context(original_live(manifest,root))
                control.idle()
                # Bootstrap may interrupt retryable pure reads; no live writer owns these leases.
                fence.stop_then_unlock_database();control.stopped()
                for folder in QUERY_ROOTS:
                    directory=base.rooted(root,folder);base.no_target_link(directory)
                    if directory.exists():
                        for path in sorted(directory.glob('.capture-*.lock')):
                            stack.enter_context(lease(base,root,'/'+str(path.relative_to(Path(root)))))
                owned.root,owned.fence,owned.control=Path(root).resolve(),fence,control
                try:yield
                finally:owned.root=owned.fence=owned.control=None
        finally:
            control.restore(fence is None or not fence.modified or fence.confirmed)

    @contextmanager
    def admission(manifest,root):
        if manifest.get('scope')==SCOPE and current(root):
            yield owned.fence
        else:
            with original_admission(manifest,root) as fence:yield fence

    def guards(manifest,root,reader_stopped=False):
        if manifest.get('scope')!=SCOPE or not current(root):return original_guards(manifest,root,reader_stopped)
        expected=dict(manifest.get('runtimeRequired',{}))
        owned.control.stopped()
        if expected.get(RANGE,{}).get('ActiveState')!='active':raise ValueError('p4_original_reader_requirement_changed')
        expected[RANGE]={**expected[RANGE],'ActiveState':'inactive'}
        for unit in owned.control.paused:
            actual=owned.control.state(unit)
            if actual['ActiveState']!='inactive' or actual['UnitFileState']!=owned.control.before[unit]['UnitFileState']:
                raise ValueError('p4_controlled_timer_state_changed')
            if unit in expected:
                if expected[unit].get('ActiveState')!='active':raise ValueError('p4_original_timer_requirement_changed')
                expected[unit]={**expected[unit],'ActiveState':'inactive'}
        return original_guards(dict(manifest,runtimeRequired=expected),root,False)

    def inspect(manifest,stage,root=Path('/')):
        if manifest.get('scope')!=SCOPE or current(root):return original_inspect(manifest,stage,root)
        control_factory(root).preview(manifest)
        # Read-only leases only: no timer/service/signal changes in prepare or inspect.
        with ExitStack() as stack:
            stack.enter_context(lease(base,root,ADMISSION))
            for path in LEGACY_LOCKS:stack.enter_context(lease(base,root,path))
            return original_inspect(manifest,stage,root)

    def rollback_journal(backup,journal,root):
        if journal['manifest'].get('scope')==SCOPE:
            if not current(root):raise ValueError('p4_rollback_requires_real_maintenance')
            owned.fence.stop_then_unlock_database();owned.control.stopped()
        return original_rollback(backup,journal,root)

    base.live_lock,base.inspect=live_lock,inspect
    base.hermes_admission_fence,base.guards=admission,guards
    base.rollback_journal=rollback_journal
    return base


def load_base():
    import actual_release
    actual_release.SCOPE,actual_release.TARGETS,actual_release.NEW=SCOPE,TARGETS,NEW
    base=actual_release.load_base()
    # Isolate the existing transaction wrapper's scope binding; do not change a shared module.
    path=Path(__file__).with_name('transaction_release.py')
    spec=importlib.util.spec_from_file_location('p4_transaction_publication_fence',path)
    transaction=importlib.util.module_from_spec(spec);spec.loader.exec_module(transaction)
    transaction.SCOPE=SCOPE
    return extend(transaction.extend(base))


if __name__=='__main__':load_base().main()
