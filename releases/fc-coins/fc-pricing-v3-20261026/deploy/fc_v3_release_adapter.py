"""FC V3 code release through the existing FS publisher and original FC locks."""
from contextlib import contextmanager, closing, ExitStack, nullcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import types
import urllib.request

from release_readiness import restart_with_hermes_readiness,fc_release_quiescent

from target_map import COUPON_DISPLAY_NAMES, COUPON_DISPLAY_SCOPE, COUPON_DISPLAY_EXTRA, DAILY_SUMMARY_NAMES, DAILY_SUMMARY_SCOPE, DAILY_REPAIR_NAMES, DAILY_REPAIR_SCOPE, QUOTE_PREVIEW_NAMES, QUOTE_PREVIEW_SCOPE, QUOTE_FRAGMENT_NAMES, QUOTE_FRAGMENT_SCOPE, REPAIR_NAMES, REPAIR_SCOPE, BIDIRECTIONAL_NAMES, BIDIRECTIONAL_SCOPE, DELTA_NAMES, DELTA_SCOPE, DELTA_NEW, SHADOW_NAMES, SHADOW_SCOPE, OPERATING_SCOPE, OPERATING_NAMES, OPERATING_NEW, COLLECTION_SCOPE, COLLECTION_NAMES, targets
from target_map import (THREE_PLATFORM_NAMES, THREE_PLATFORM_SCOPE, THREE_PLATFORM_EXTRA,
                        THREE_PLATFORM_NEW, three_platform_targets, MONITOR_SQLITE_CANDIDATE,
                        MONITOR_SQLITE_SHA, MONITOR_SQLITE_SOURCE)

HERE = Path(__file__).resolve().parent
SCOPE = 'fc-pricing-v3-20261026'
# Exact Git LF normalization of the frozen original publisher (raw CRLF SHA 1d070ee8...).
BASE_SHA = '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'
FC_PUBLISHER = Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
FC_SHA = 'b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'
SOURCE = HERE.parent / 'candidate/source' if (HERE.parent / 'candidate/source').exists() else HERE.parent / 'source'
TARGETS = {'source/' + name: path for name, path in targets(SOURCE).items()}
THREE_PLATFORM_TARGETS = {'source/'+name:path for name,path in three_platform_targets(SOURCE).items()
                          if 'source/'+name in THREE_PLATFORM_NAMES}
THREE_PLATFORM_TARGETS.update(THREE_PLATFORM_EXTRA)
BIDIRECTIONAL_TARGETS = {name: TARGETS[name] for name in BIDIRECTIONAL_NAMES}
REPAIR_TARGETS = {name: TARGETS[name] for name in REPAIR_NAMES}
QUOTE_FRAGMENT_TARGETS = {name: TARGETS[name] for name in QUOTE_FRAGMENT_NAMES}
QUOTE_PREVIEW_TARGETS = {name: TARGETS[name] for name in QUOTE_PREVIEW_NAMES}
DAILY_REPAIR_TARGETS = {name: TARGETS[name] for name in DAILY_REPAIR_NAMES}
DAILY_SUMMARY_TARGETS = {name: TARGETS[name] for name in DAILY_SUMMARY_NAMES}
COUPON_DISPLAY_TARGETS = {name: TARGETS[name] for name in COUPON_DISPLAY_NAMES if name in TARGETS}
COUPON_DISPLAY_TARGETS.update(COUPON_DISPLAY_EXTRA)
DELTA_TARGETS = {name: TARGETS[name] for name in DELTA_NAMES}
SHADOW_TARGETS = {name: TARGETS[name] for name in SHADOW_NAMES}
OPERATING_TARGETS={name:TARGETS[name] for name in OPERATING_NAMES}
COLLECTION_TARGETS={name:TARGETS[name] for name in COLLECTION_NAMES}
BUNDLE_SOURCE=Path('/opt/fc27-pack-bundles/pack_bundles_server.py')
BUNDLE_CONFIG=Path('/opt/fc27-pack-bundles/data/config.json')


def bundle_config_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def bundle_state():
    with urllib.request.urlopen('http://127.0.0.1:8904/api/state',timeout=2) as response:
        raw=response.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise ValueError('bundles_readback_too_large')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('bundles_state_readback_invalid')
    return value


def bundle_live_snapshot(*,include_process=True):
    config=json.loads(BUNDLE_CONFIG.read_text('utf-8'))
    state=bundle_state()
    pid=int(subprocess.check_output(['systemctl','show','fc27-pack-bundles.service','-p','MainPID'],
            universal_newlines=True).strip().split('=',1)[1])
    if pid<=0:raise ValueError('bundles_process_missing')
    if not include_process:return config,state,dict(pid=pid,threads=[])
    # 187 is x86_64/Python3.9: time.sleep uses select(nfds=0, NULL,NULL,NULL).
    # wchan is also used for network polling and is deliberately not sufficient.
    import platform
    if platform.machine()!='x86_64':raise ValueError('bundles_bootstrap_architecture_unverified')
    threads=[]
    for path in (Path('/proc')/str(pid)/'task').iterdir():
        text=(path/'stat').read_text();fields=text[text.rfind(')')+2:].split()
        call=(path/'syscall').read_text().split()
        sleeping=(len(call)>=5 and call[0] in ('23','270') and all(int(x,16)==0 for x in call[1:5]))
        threads.append(dict(tid=int(path.name),start_ticks=int(fields[19]),scheduler_sleep=sleeping))
    return config,state,dict(pid=pid,threads=threads)


def checked_bundle_off_config(proof,config,state):
    if (config.get('revision')!=proof['configRevision'] or bundle_config_hash(config)!=proof['configSha256']
            or config.get('settings',{}).get('write_enabled') is not False
            or config.get('settings',{}).get('write_auto') is not False
            or state.get('revision')!=config['revision'] or state.get('settings')!=config['settings']
            or state.get('write',{}).get('enabled') is not False or state.get('write',{}).get('auto') is not False):
        raise ValueError('bundles_bootstrap_off_config_changed')


def checked_bundle_idle(proof,config,state,process):
    checked_bundle_off_config(proof,config,state)
    if state.get('last_refresh',{}).get('status') not in ('ok','partial','error','interrupted'):
        raise ValueError('bundles_bootstrap_refresh_not_idle')
    rows=process.get('threads') or []
    by={r['tid']:r for r in rows}
    if (process.get('pid')!=proof['pid'] or len(rows)!=2 or set(by)!={proof['pid'],proof['schedulerTid']}
            or by[proof['pid']]['start_ticks']!=proof['processStartTicks']
            or by[proof['schedulerTid']]['start_ticks']!=proof['schedulerStartTicks']
            or by[proof['schedulerTid']]['scheduler_sleep'] is not True):
        raise ValueError('bundles_bootstrap_threads_not_idle')


def capture_bundle_bootstrap(baseline):
    """Read-only proof after the owner CAS-disables dispatch; no config is written."""
    original=baseline['config']
    if set(original)!={'revision','settings','bundles'} or type(original['revision']) is not int:
        raise ValueError('bundles_original_config_invalid')
    off=json.loads(json.dumps(original));off['revision']+=1
    off['settings'].update(write_enabled=False,write_auto=False)
    config,state,process=bundle_live_snapshot()
    if config!=off:raise ValueError('bundles_bootstrap_only_dispatch_switches_may_change')
    proof=dict(contract='legacy_bundle_dispatch_off_v1',
        **{k:baseline[k] for k in ('pid','processStartTicks','schedulerTid','schedulerStartTicks')},
        configRevision=config['revision'],configSha256=bundle_config_hash(config),
        originalConfigSha256=bundle_config_hash(original),
        sourceSha256=hashlib.sha256(BUNDLE_SOURCE.read_bytes()).hexdigest())
    checked_bundle_idle(proof,config,state,process)
    return proof


def capture_bundle_baseline():
    """Private pre-maintenance snapshot for the existing CAS and later exact restore."""
    config,state,process=bundle_live_snapshot()
    by={row['tid']:row for row in process['threads']}
    other=sorted((row for row in process['threads'] if row['tid']!=process['pid']),
                 key=lambda row:(row['start_ticks'],row['tid']))
    if (process['pid'] not in by or not other or state.get('revision')!=config.get('revision')
            or state.get('settings')!=config.get('settings')):
        raise ValueError('bundles_original_baseline_changed')
    # Source starts its permanent scheduler before opening the HTTP server.
    scheduler=other[0]
    return dict(config=config,pid=process['pid'],processStartTicks=by[process['pid']]['start_ticks'],
                schedulerTid=scheduler['tid'],schedulerStartTicks=scheduler['start_ticks'])


def bundle_bootstrap_guard(manifest,base,root,*,locks_held=False,admitted=False,phase='before'):
    proof=manifest.get('bundleBootstrap')
    config,state,process=bundle_live_snapshot(include_process=bool(proof) and phase=='before')
    modern=state.get('write_admission_contract')=='bundle_write_admission_v1'
    if proof is None:
        if not modern:raise ValueError('bundles_bootstrap_proof_required')
        return
    row=next(r for r in manifest['files'] if r['candidate']=='source/pack_bundles_server.py')
    if proof.get('contract')!='legacy_bundle_dispatch_off_v1' or proof.get('sourceSha256')!=row['beforeSha256']:
        raise ValueError('bundles_bootstrap_source_changed')
    if phase in ('new','rollback'):
        if not locks_held or not admitted:raise ValueError('bundles_bootstrap_stage_not_admitted')
        expected='sha256' if phase=='new' else 'beforeSha256'
        for item in manifest['files']:
            path=base.rooted(root,item['target'])
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if actual!=item[expected]:raise ValueError('bundles_bootstrap_stage_source_changed')
        if phase=='new' and not modern:raise ValueError('bundles_loaded_admission_not_ready')
        # A new/rolled-back PID is expected after restart. Preserve the exact off
        # config while checking the appropriate loaded service, under the same fence.
        checked_bundle_off_config(proof,config,state)
        return
    if modern:raise ValueError('bundles_bootstrap_stage_not_admitted')
    checked_bundle_idle(proof,config,state,process)


def bundle_readiness(manifest):
    """Verify the loaded service, including the old service after a code rollback."""
    row=next(r for r in manifest['files'] if r['candidate']=='source/pack_bundles_server.py')
    actual=hashlib.sha256(Path(row['target']).read_bytes()).hexdigest()
    if actual not in (row['sha256'],row['beforeSha256']):
        raise ValueError('bundles_code_readback_changed')
    for attempt in range(20):
        try:
            state=bundle_state()
            if not isinstance(state,dict) or not isinstance(state.get('bundles'),list) or not isinstance(state.get('write'),dict):
                raise ValueError('bundles_state_readback_invalid')
            if actual==row['sha256'] and (state.get('price_scope_contract')!='fc27_three_platform_v1'
                    or state.get('write_admission_contract')!='bundle_write_admission_v1'):
                raise ValueError('bundles_loaded_contract_not_ready')
            return
        except OSError:
            if attempt==19:raise ValueError('bundles_service_readback_unavailable') from None
            time.sleep(.2)


@contextmanager
def bundle_release_admission(base, root, manifest=None):
    """Hold the same dispatch fence before replacement through service readback."""
    import fcntl, os, stat
    path=base.rooted(root,'/opt/fc27-pack-bundles/data/write-admission.lock')
    base.no_target_link(path)
    try:
        fd=os.open(str(path),os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
    except FileNotFoundError:
        if not manifest or not manifest.get('bundleBootstrap'):
            raise ValueError('bundles_write_lock_bootstrap_required') from None
        bundle_bootstrap_guard(manifest,base,root)
        fd=os.open(str(path),os.O_RDWR|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o640)
    with os.fdopen(fd,'r+b') as stream:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1
                or stat.S_IMODE(info.st_mode) not in (0o600,0o640)):
            raise ValueError('unsafe_bundle_write_admission')
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('bundles_write_in_progress') from None
        yield




def checked_manifest(value):
    rows = value.get('files', [])
    scope = value.get('scope')
    expected = (THREE_PLATFORM_TARGETS if scope == THREE_PLATFORM_SCOPE else COUPON_DISPLAY_TARGETS if scope == COUPON_DISPLAY_SCOPE else DAILY_SUMMARY_TARGETS if scope == DAILY_SUMMARY_SCOPE else DAILY_REPAIR_TARGETS if scope == DAILY_REPAIR_SCOPE else QUOTE_PREVIEW_TARGETS if scope == QUOTE_PREVIEW_SCOPE else QUOTE_FRAGMENT_TARGETS if scope == QUOTE_FRAGMENT_SCOPE else REPAIR_TARGETS if scope == REPAIR_SCOPE else BIDIRECTIONAL_TARGETS if scope == BIDIRECTIONAL_SCOPE else COLLECTION_TARGETS if scope == COLLECTION_SCOPE else TARGETS if scope == SCOPE else DELTA_TARGETS if scope == DELTA_SCOPE else
                SHADOW_TARGETS if scope == SHADOW_SCOPE else OPERATING_TARGETS if scope==OPERATING_SCOPE else {})
    if not expected or len(rows) != len(expected) or \
            {r['candidate']: r['target'] for r in rows} != expected:
        raise ValueError('exact_fc_v3_targets_required')
    new_targets=THREE_PLATFORM_NEW if scope==THREE_PLATFORM_SCOPE else OPERATING_NEW if scope==OPERATING_SCOPE else DELTA_NEW if scope==DELTA_SCOPE else frozenset()
    if sum(r.get('beforeSha256') is None for r in rows) != (54 if scope==SCOPE else len(new_targets)):
        raise ValueError('fc_v3_new_existing_target_boundary_changed')
    if scope in (OPERATING_SCOPE,DELTA_SCOPE,THREE_PLATFORM_SCOPE) and {r['candidate'] for r in rows if r.get('beforeSha256') is None}!=new_targets:
        raise ValueError('fc_v3_operating_new_target_identity_changed')
    if any(r.get('owner') != '0:0' or r.get('mode') not in ('0o644', '0o700', '0o750', '0o755') for r in rows):
        raise ValueError('exact_fc_v3_target_metadata_required')
    if scope == SCOPE and next(r for r in rows if r['candidate'] == 'source/reconcile_price.sh')['mode'] != '0o755':
        raise ValueError('fc_v3_reconcile_script_must_be_executable')
    if value.get('businessWrites') is not False or value.get('timersChanged') is not False:
        raise ValueError('code_release_does_not_change_business_or_timer_state')
    if value.get('releaseReady') is not True:
        raise ValueError('reviewed_code_release_required')
    if scope==THREE_PLATFORM_SCOPE:
        library=next(r for r in rows if r['candidate']==MONITOR_SQLITE_CANDIDATE)
        if library.get('sha256')!=MONITOR_SQLITE_SHA or {r.get('path'):r.get('sha256') for r in value.get('unchangedRequired',[])}.get(MONITOR_SQLITE_SOURCE)!=MONITOR_SQLITE_SHA:
            raise ValueError('monitor_sqlite_provenance_changed')
    if scope==THREE_PLATFORM_SCOPE and value.get('bundleBootstrap') is not None:
        proof=value['bundleBootstrap']
        required={'contract','pid','processStartTicks','schedulerTid','schedulerStartTicks',
                  'configRevision','configSha256','originalConfigSha256','sourceSha256'}
        if (not isinstance(proof,dict) or set(proof)!=required or proof.get('contract')!='legacy_bundle_dispatch_off_v1'
                or any(type(proof[k]) is not int or proof[k]<=0 for k in ('pid','processStartTicks','schedulerTid','schedulerStartTicks','configRevision'))
                or any(not isinstance(proof[k],str) or len(proof[k])!=64 or any(c not in '0123456789abcdef' for c in proof[k])
                       for k in ('configSha256','originalConfigSha256','sourceSha256'))):
            raise ValueError('bundles_bootstrap_proof_invalid')
    return value


def load_base():
    raw = (HERE / 'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    approved = checked_manifest(json.loads((HERE / 'approved-manifest.json').read_text('utf-8')))
    scope = approved['scope']
    active_targets = THREE_PLATFORM_TARGETS if scope == THREE_PLATFORM_SCOPE else COUPON_DISPLAY_TARGETS if scope == COUPON_DISPLAY_SCOPE else DAILY_SUMMARY_TARGETS if scope == DAILY_SUMMARY_SCOPE else DAILY_REPAIR_TARGETS if scope == DAILY_REPAIR_SCOPE else QUOTE_PREVIEW_TARGETS if scope == QUOTE_PREVIEW_SCOPE else QUOTE_FRAGMENT_TARGETS if scope == QUOTE_FRAGMENT_SCOPE else REPAIR_TARGETS if scope == REPAIR_SCOPE else BIDIRECTIONAL_TARGETS if scope == BIDIRECTIONAL_SCOPE else COLLECTION_TARGETS if scope == COLLECTION_SCOPE else TARGETS if scope == SCOPE else DELTA_TARGETS if scope == DELTA_SCOPE else OPERATING_TARGETS if scope==OPERATING_SCOPE else SHADOW_TARGETS
    new = frozenset(r['candidate'] for r in approved['files'] if r['beforeSha256'] is None)
    source = raw.decode('utf-8')
    anchor = "r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor) != 1:
        raise ValueError('frozen_new_file_anchor_drift')
    source = source.replace(anchor,
        "r.get('beforeSha256') is None for r in files if r['candidate'] not in V3_NEW if not (", 1)
    base = types.ModuleType('frozen_fc_v3_publisher')
    base.__file__ = str(HERE / 'release_navigation_base.py')
    base.V3_NEW = new
    exec(compile(source, base.__file__, 'exec'), base.__dict__)
    base.HERMES_HISTORY_SCOPE, base.HERMES_HISTORY_TARGETS = scope, active_targets
    if scope == COLLECTION_SCOPE:
        base.hermes_admission_fence = lambda manifest, root: nullcontext()
        base.model_release_lock = lambda manifest, root: nullcontext()
    base.expected_files = lambda m: set(active_targets) if m.get('scope') == scope else set()
    base.target_for = lambda relative: active_targets[relative]
    validate = base.validate

    def exact_validate(manifest, stage):
        if manifest != approved:
            raise ValueError('frozen_manifest_required')
        return validate(manifest, stage)

    base.validate = exact_validate

    original_quiescent = base.hermes_quiescent

    def quiescent(root):
        if scope == COLLECTION_SCOPE:
            return
        original_quiescent(root)
        for path, query in (
            ('/var/lib/fs-hermes-fc/fs/conversations/conversations.db',
             "SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',
             "SELECT count(*) FROM scan_jobs WHERE state='pending'"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',
             "SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')")):
            database = base.rooted(root,path)
            base.no_target_link(database)
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                if db.execute(query).fetchone()[0]:
                    raise ValueError('active_conversation_or_tracking')
        with closing(sqlite3.connect(base.rooted(root,
                '/var/lib/fs-hermes-fc/fs/tasks.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_events'").fetchone():
                if db.execute("SELECT count(*) FROM learning_events WHERE state IN ('running','unknown')").fetchone()[0]:
                    raise ValueError('active_or_unreconciled_learning')

    base.hermes_quiescent = quiescent
    if hashlib.sha256(FC_PUBLISHER.read_bytes()).hexdigest() != FC_SHA:
        raise ValueError('original_fc_publisher_drift')
    fc = types.ModuleType('original_fc_publisher')
    fc.__file__ = str(FC_PUBLISHER)
    exec(compile(FC_PUBLISHER.read_bytes(), str(FC_PUBLISHER), 'exec'), fc.__dict__)
    original_locks = base.locks
    holding_fc_locks = False
    bundle_release_state=dict(holding=False,admitted=False,phase='before')

    @contextmanager
    def combined_locks(root):
        nonlocal holding_fc_locks
        if root != Path('/'):
            raise ValueError('real_existing_release_locks_required')
        with original_locks(root), ExitStack() as stack:
            import fcntl, os, stat
            stack.enter_context(fc.api.queue_mutation())
            for name in fc.tick.RETRY_LOCKS:
                path = fc.ROOT / 'state' / name
                base.no_target_link(path)
                fd = os.open(str(path), os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
                stream = stack.enter_context(os.fdopen(fd, 'r+b'))
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
                    raise ValueError('unsafe_original_fc_lock')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if scope == THREE_PLATFORM_SCOPE:
                bundle_bootstrap_guard(approved,base,root)
                stack.enter_context(bundle_release_admission(base, root, approved))
                bundle_release_state.update(holding=True,admitted=bool(approved.get('bundleBootstrap')))
            holding_fc_locks = True
            try:
                yield
            finally:
                holding_fc_locks = False
                if scope == THREE_PLATFORM_SCOPE:bundle_release_state['holding']=False

    base.locks = combined_locks
    original_guards = base.guards

    def guards(manifest, root, reader_stopped=False):
        original_guards(manifest, root, reader_stopped)
        if not fc_release_quiescent(fc.tick,fc.api,locks_held=holding_fc_locks):
            raise ValueError('original_fc_execution_not_quiescent')
        if scope == THREE_PLATFORM_SCOPE:
            bundle_bootstrap_guard(manifest,base,root,locks_held=bundle_release_state['holding'],
                admitted=bundle_release_state['admitted'],phase=bundle_release_state['phase'])
        for row in manifest['files']:
            path = base.rooted(root, row['target'])
            if path.exists():
                info = path.stat()
                if info.st_uid != 0 or info.st_gid != 0 or oct(info.st_mode & 0o777) != row['mode']:
                    raise ValueError('fc_v3_target_metadata_drift')

    base.guards = guards
    original_atomic = base.atomic

    def atomic(path, data, mode=0o644):
        if str(path) == '/opt/fc27-cloud-browser/reconcile_price.sh':
            mode = 0o755
        return original_atomic(path, data, mode)

    base.atomic = atomic
    original_restart = base.restart_for

    def restart(manifest, admission_fence=None):
        # These three entries load in fresh quote/source subprocesses.
        if manifest.get('scope') == COLLECTION_SCOPE:
            return
        restart_with_hermes_readiness(base, original_restart, manifest, admission_fence)
        if manifest.get('scope') in (SCOPE,DELTA_SCOPE,SHADOW_SCOPE,OPERATING_SCOPE,COLLECTION_SCOPE,BIDIRECTIONAL_SCOPE,REPAIR_SCOPE,QUOTE_FRAGMENT_SCOPE,QUOTE_PREVIEW_SCOPE,DAILY_REPAIR_SCOPE,DAILY_SUMMARY_SCOPE,COUPON_DISPLAY_SCOPE,THREE_PLATFORM_SCOPE):
            subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
            for name in ('fc27-cloud-api.service', 'fc27-cloud-worker.service', 'fc-pricing-v3.service'):
                subprocess.run(['systemctl', 'restart', name], check=True, timeout=30)
                subprocess.run(['systemctl', 'is-active', '--quiet', name], check=True, timeout=10)
        if manifest.get('scope') == THREE_PLATFORM_SCOPE:
            if manifest.get('bundleBootstrap'):
                restored=all((hashlib.sha256(Path(r['target']).read_bytes()).hexdigest() if Path(r['target']).is_file() else None)==r['beforeSha256'] for r in manifest['files'])
                if restored:bundle_release_state['phase']='rollback'
            subprocess.run(['systemctl','restart','fc27-pack-bundles.service'],check=True,timeout=30)
            subprocess.run(['systemctl','is-active','--quiet','fc27-pack-bundles.service'],check=True,timeout=10)
            bundle_readiness(manifest)
            if manifest.get('bundleBootstrap') and not restored:bundle_release_state['phase']='new'

    base.restart_for = restart
    return base


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1] in ('capture-bundle-baseline','capture-bundle-bootstrap'):
        import argparse,os,stat
        parser=argparse.ArgumentParser(description='Read-only bundle bootstrap proof; does not disable or restore dispatch')
        capture_proof=sys.argv[1]=='capture-bundle-bootstrap'
        if capture_proof:parser.add_argument('--baseline',required=True)
        parser.add_argument('--output',required=True)
        args=parser.parse_args(sys.argv[2:])
        if capture_proof:
            baseline=Path(args.baseline)
            if any(p.is_symlink() for p in (baseline,*baseline.parents)) or not baseline.is_file():
                raise ValueError('unsafe_private_bundle_baseline')
            info=baseline.stat()
            if info.st_uid!=0 or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
                raise ValueError('unsafe_private_bundle_baseline')
            proof=capture_bundle_bootstrap(json.loads(baseline.read_text('utf-8')))
        else:proof=capture_bundle_baseline()
        output=Path(args.output)
        if any(p.is_symlink() for p in (output,*output.parents)):
            raise ValueError('unsafe_bundle_proof_output')
        raw=(json.dumps(proof,sort_keys=True,indent=2)+'\n').encode()
        fd=os.open(str(output),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        print(json.dumps(dict(proofSha256=hashlib.sha256(raw).hexdigest(),priceWrites=0,configWrites=0)))
    else:
        load_base().main()
