"""Exact FC V2 adapter: existing FS CAS/rollback publisher plus original FC locks."""
from contextlib import contextmanager,closing,ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import types

HERE=Path(__file__).resolve().parent
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
FC_PUBLISHER=Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
FC_SHA='b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'
SCOPE='fc-pricing-v2-20261022'
RESTART_FC=True
FC_NAMES=('automation_policy.py','fc27_cloud_api.py','fc27_cloud_worker.py','fc27_quote_engine.py',
    'server_quote_job.py','preview_backend.py','price_writer.py','restore_price.py',
    'execute_price.sh','restore_price.sh','repricing_logic.js','pricing_v2.py','pricing_sources.py',
    'pricing_state.py','hermes_pricing_bridge.py')
FS_NAMES=('strategy_tools.py','conversation_service.py','runs_contract.py','pricing_simulation.py','pricing_operations.py','business-baseline.md')
TARGETS={**{'source/'+n:'/opt/fc27-cloud-browser/'+n for n in FC_NAMES},
         **{'source/'+n:'/opt/fs-hermes-fc/'+n for n in FS_NAMES},
         **{'source/'+n:'/var/www/dashboard/'+n for n in ('fc27-coins.html','fc27-quote-cloud.js')}}
NEW=frozenset('source/'+n for n in ('pricing_v2.py','pricing_sources.py','pricing_state.py','hermes_pricing_bridge.py','pricing_operations.py'))


def checked_manifest(value):
    rows=value.get('files',[])
    if value.get('scope')!=SCOPE or len(rows)!=len(TARGETS) or {r['candidate']:r['target'] for r in rows}!=TARGETS:
        raise ValueError('exact_fc_v2_targets_required')
    for row in rows:
        if (row.get('beforeSha256') is None)!=(row['candidate'] in NEW) or row.get('owner')!='0:0' or row.get('mode') not in ('0o644','0o700','0o755'):
            raise ValueError('exact_fc_v2_existing_new_modes_required')
    if value.get('businessWrites') is not False or value.get('timersChanged') is not False:
        raise ValueError('release_is_code_only_existing_policy_and_schedule_preserved')
    return value


def approved_auth_source(source):
    if SCOPE != 'fc-dot-observer-20261022':
        return source
    exact = {'source/rbac.py':'/opt/fs-access-policy/rbac.py',
             'source/access_policy.py':'/opt/fs-access-policy/access_policy.py',
             'source/fc27_cloud_api.py':'/opt/fc27-cloud-browser/fc27_cloud_api.py',
             'source/fc_observer.py':'/opt/fc27-cloud-browser/fc_observer.py'}
    if TARGETS != exact or NEW != frozenset({'source/fc_observer.py'}):
        raise ValueError('exact_observer_auth_replacement_required')
    anchor = "  if not required.issubset(protected) or set(protected)&set(targets.values()):raise ValueError('Hermes protected consumer boundary differs')"
    if source.count(anchor) != 1:
        raise ValueError('frozen_observer_auth_boundary_drift')
    # This approved target is protected by beforeSha256/CAS, not unchangedRequired.
    return source.replace(anchor, "  required -= {'/opt/fs-access-policy/access_policy.py'}\n" + anchor, 1)


def load_base():
    raw=(HERE/'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_publisher_drift')
    approved=checked_manifest(json.loads((HERE/'approved-manifest.json').read_text('utf-8')))
    source=raw.decode('utf-8');anchor="r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor)!=1:raise ValueError('frozen_new_file_anchor_drift')
    source=source.replace(anchor,"r.get('beforeSha256') is None for r in files if r['candidate'] not in V2_NEW if not (",1)
    source=approved_auth_source(source)
    base=types.ModuleType('frozen_fc_v2_publisher');base.__file__=str(HERE/'release_navigation_base.py');base.V2_NEW=NEW
    exec(compile(source,base.__file__,'exec'),base.__dict__)
    base.HERMES_HISTORY_SCOPE,base.HERMES_HISTORY_TARGETS=SCOPE,TARGETS
    base.expected_files=lambda m:set(TARGETS) if m.get('scope')==SCOPE else set()
    base.target_for=lambda relative:TARGETS[relative]
    validate=base.validate
    def exact_validate(manifest,stage):
        if manifest!=approved:raise ValueError('frozen_manifest_required')
        return validate(manifest,stage)
    base.validate=exact_validate

    original_quiescent=base.hermes_quiescent
    def quiescent(root):
        original_quiescent(root)
        for path,query in (
            ('/var/lib/fs-hermes-fc/fs/conversations/conversations.db',"SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',"SELECT count(*) FROM scan_jobs WHERE state='pending'"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',"SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')")):
            database=base.rooted(root,path);base.no_target_link(database)
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                if db.execute(query).fetchone()[0]:raise ValueError('active_conversation_or_tracking')
        with closing(sqlite3.connect(base.rooted(root,'/var/lib/fs-hermes-fc/fs/tasks.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_events'").fetchone():
                if db.execute("SELECT count(*) FROM learning_events WHERE state IN ('running','unknown')").fetchone()[0]:
                    raise ValueError('active_or_unreconciled_learning')
    base.hermes_quiescent=quiescent

    if hashlib.sha256(FC_PUBLISHER.read_bytes()).hexdigest()!=FC_SHA:raise ValueError('original_fc_publisher_drift')
    fc=types.ModuleType('original_fc_publisher');fc.__file__=str(FC_PUBLISHER)
    exec(compile(FC_PUBLISHER.read_bytes(),str(FC_PUBLISHER),'exec'),fc.__dict__)
    original_locks=base.locks
    @contextmanager
    def combined_locks(root):
        if root!=Path('/'):raise ValueError('real_existing_release_locks_required')
        with original_locks(root),ExitStack() as stack:
            import fcntl,os,stat
            stack.enter_context(fc.api.queue_mutation())
            for name in fc.tick.RETRY_LOCKS:
                path=fc.ROOT/'state'/name;base.no_target_link(path)
                fd=os.open(str(path),os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
                stream=stack.enter_context(os.fdopen(fd,'r+b'))
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1:raise ValueError('unsafe_original_fc_lock')
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
    base.locks=combined_locks
    original_guards=base.guards
    def guards(manifest,root,reader_stopped=False):
        original_guards(manifest,root,reader_stopped)
        if fc.tick.retry_guard()!='ready' or fc.api.health()['incomplete_executions']!=0:
            raise ValueError('original_fc_execution_not_quiescent')
        for row in manifest['files']:
            path=base.rooted(root,row['target'])
            if path.exists():
                info=path.stat()
                if info.st_uid!=0 or info.st_gid!=0 or oct(info.st_mode&0o777)!=row['mode']:
                    raise ValueError('fc_v2_target_metadata_drift')
    base.guards=guards
    original_restart=base.restart_for
    def restart(manifest,admission_fence=None):
        original_restart(manifest,admission_fence)
        if manifest.get('scope')==SCOPE and RESTART_FC:
            for name in ('fc27-cloud-api.service','fc27-cloud-worker.service'):
                subprocess.run(['systemctl','restart',name],check=True,timeout=30)
                subprocess.run(['systemctl','is-active','--quiet',name],check=True,timeout=10)
    base.restart_for=restart
    return base


if __name__=='__main__':load_base().main()
