"""Shared bounded readiness for the existing V3 code and knowledge publishers."""
import json
import subprocess
import time
import urllib.request


def superseded_all_code_release(tick, health, *, locks_held=False):
    """Prove same-ID Order/Admin closure or later ALL convergence for code release."""
    from contextlib import ExitStack
    from datetime import datetime, timezone
    import hashlib, os, stat
    root=tick.ROOT
    def check():
        if health.get('queue_depth')!=0 or health.get('incomplete_executions')!=0:return False
        for name in ('queue','jobs','executions','all-coin-sync'):
            if not (root/name).is_dir() or (root/name).is_symlink():return False
        if any((root/'queue').glob('*.json')):return False
        if any(tick.read_record(p).get('status')=='running' for p in (root/'jobs').glob('*.json')):return False
        if any(not tick.resolved_execution(tick.read_record(p)) for p in (root/'executions').glob('*.json')):return False
        def read(path):
            if path.is_symlink() or not path.is_file():raise ValueError('unsafe_all_evidence')
            raw=path.read_bytes()
            return json.loads(raw),hashlib.sha256(raw).hexdigest()
        def stamp(value):
            result=datetime.fromisoformat(value.replace('Z','+00:00'))
            if result.tzinfo is None:raise ValueError('all_evidence_time_unknown')
            return result
        pending=[]; confirmed=[]; closed=[]
        for path in (root/'all-coin-sync').glob('*.json'):
            record,digest=read(path)
            if record.get('execution_id')!=path.stem:return False
            if record.get('status')=='confirmed':confirmed.append((path,record,digest));continue
            if record.get('status')!='needs_reconcile':return False
            if any(s.get('status') not in ('pending','confirmed') for s in record.get('steps',[])):return False
            audit,audit_sha=read(root/'executions'/path.name)
            if (audit.get('execution_id')!=path.stem or not tick.resolved_execution(audit)
                    or audit.get('sync_confirmed') is not True):return False
            from fc_pricing_v3.order_close import ledger_operation_status
            if (audit.get('status') in ('ORDER_ADMIN_CONFIRMED','PUBLIC_CONFIRMED')
                    and ledger_operation_status(path.stem,root=root,require_order_admin_close=True)=='COMPLETED'):
                closed.append(dict(execution_id=path.stem,all_sha256=digest,audit_sha256=audit_sha))
                continue
            pending.append((path.stem,digest,audit_sha,stamp(audit['updated_at'])))
        if closed and not pending:
            print(json.dumps({'code_release_order_admin_closed':closed,'price_posts':0}),flush=True)
            return True
        if not pending or not confirmed:return False
        path,record,record_sha=max(confirmed,key=lambda item:stamp(item[1]['completed_at']))
        completed=stamp(record['completed_at'])
        if completed>datetime.now(timezone.utc) or any(completed<=p[3] for p in pending):return False
        audit,audit_sha=read(root/'executions'/path.name)
        if (audit.get('execution_id')!=path.stem or audit.get('status')!='CONFIRMED'
                or audit.get('sync_confirmed') is not True or not tick.resolved_execution(audit)
                or audit.get('all_baseline',{}).get('status')!='confirmed'
                or record.get('source_confirmation',{}).get('status')!='confirmed'):return False
        import fc_shared_admin as admin, coin_all_sync_job as coins
        steps=record['steps']
        if len(steps)!=3 or {s.get('platform') for s in steps}!=set(coins.PRODUCTS):return False
        for step in steps:
            ids=coins.PRODUCTS[step['platform']]
            if step.get('status')!='confirmed' or (step.get('product_id'),step.get('source_product_id'))!=ids[:2]:return False
        manager=admin.SessionManager(admin.read_private_config())
        if not manager.ensure():return False
        previous=None
        for attempt in range(2):
            snapshot={}
            for step in steps:
                platform=step['platform']
                source=coins.read_row(manager,platform,266);actual=coins.read_row(manager,platform,0)
                if not coins.unchanged(step['source'],source,platform) or not coins.unchanged(step['payload'],actual,platform):return False
                coins.verify_step(step,actual,source)
                snapshot[platform]={'source':coins.editable(source),'all':coins.editable(actual)}
            if previous is not None and previous!=snapshot:return False
            previous=snapshot
            if attempt==0:time.sleep(3)
        print(json.dumps({'code_release_all_supersession':{'originals':[{'execution_id':p[0],'all_sha256':p[1],'audit_sha256':p[2]} for p in pending],
            'superseding_execution_id':path.stem,'all_sha256':record_sha,'audit_sha256':audit_sha,
            'checked_at':datetime.now(timezone.utc).isoformat(),'stable_rounds':2,'price_posts':0,
            'snapshot_sha256':hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()}}),flush=True)
        return True
    try:
        if locks_held:return check()
        import fcntl
        with tick.queue_mutation(),ExitStack() as stack:
            for name in tick.RETRY_LOCKS:
                path=root/'state'/name
                if path.is_symlink():return False
                stream=stack.enter_context(path.open('rb'));info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:return False
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return check()
    except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError,ImportError):
        return False


def paused_code_release(tick,health,*,locks_held=False):
    """Allow code repair while paused; leave all business reconciliation gates intact."""
    from contextlib import closing,ExitStack
    import os,sqlite3,stat
    root=tick.ROOT
    def paused_and_idle():
        if health.get('queue_depth')!=0:return False
        if any(not (root/name).is_dir() or (root/name).is_symlink() for name in ('queue','jobs','executions')):return False
        if any((root/'queue').glob('*.json')):return False
        if any(tick.read_record(p).get('status')=='running' for p in (root/'jobs').glob('*.json')):return False
        if any(not tick.resolved_execution(tick.read_record(p)) for p in (root/'executions').glob('*.json')):return False
        path=root/'v3/control.sqlite3'
        if not path.is_file() or path.is_symlink():return False
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            row=db.execute("SELECT body FROM metadata WHERE id='generation'").fetchone()
            generation=json.loads(row[0]).get('id') if row else None
            if not generation:return False
            owners=db.execute('SELECT DISTINCT plan_id,revision,generation FROM plan_ownership WHERE generation=?',(generation,)).fetchall()
            if not owners:return False
            for ident,revision,owner_generation in owners:
                row=db.execute('SELECT body FROM pricing_plans WHERE id=?',(ident,)).fetchone()
                plan=json.loads(row[0]) if row else {}
                if (plan.get('state')!='SUSPENDED' or plan.get('plan_id')!=ident
                        or plan.get('revision')!=revision or plan.get('generation')!=owner_generation):return False
        return True
    try:
        if locks_held:return paused_and_idle()
        import fcntl
        with tick.queue_mutation(),ExitStack() as stack:
            for name in tick.RETRY_LOCKS:
                path=root/'state'/name
                if path.is_symlink():return False
                stream=stack.enter_context(path.open('rb'))
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:return False
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return paused_and_idle()
    except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError,ImportError,sqlite3.Error):
        return False


def fc_release_quiescent(tick,api,*,locks_held=False):
    """A proven preflight refusal is a failed follow-up, not an in-flight POST."""
    health=api.health()
    if health['incomplete_executions']!=0:return False
    guard=tick.retry_guard()
    if guard=='ready':return True
    if guard=='all_sync_unconfirmed' and superseded_all_code_release(tick,health,locks_held=locks_held):
        if tick.player_sync_gate()=='ready':return True
        guard='player_sync_unconfirmed'
    if guard in ('all_sync_unconfirmed','player_sync_unconfirmed') and paused_code_release(tick,health,locks_held=locks_held):return True
    if guard!='player_sync_unconfirmed':return False
    config=tick.load_player_sync_policy()
    jobs=[tick.read_record(p) for p in (tick.ROOT/'jobs').glob('*.json')]
    jobs=[r for r in jobs if r.get('kind')=='player_sync' and r.get('request',{}).get('config_revision')==config['revision']]
    if not jobs:return False
    latest=max(jobs,key=lambda r:r['created_at'])
    return (latest.get('status')=='failed' and latest.get('error')=='player_sync_not_confirmed' and
            latest.get('sync_result')=={'status':'blocked_before_write','reason':'player_sync_preflight_changed'} and
            not (tick.ROOT/'player-sync'/(latest['job_id']+'.json')).exists())


def restart_with_hermes_readiness(base, original_restart, manifest, admission_fence):
    scope = manifest.get('scope')
    range_scope=scope==getattr(base,'DEEP_SCOPE',None)
    worker_deadline = time.monotonic()+60 if scope==base.HERMES_WORKER_SCOPE or range_scope else None
    try:
        return original_restart(manifest, admission_fence)
    except ValueError as exc:
        expected_error='range health failed' if range_scope else 'Hermes worker health failed'
        if (not range_scope and (scope!=base.HERMES_WORKER_SCOPE or admission_fence is None)) or str(exc)!=expected_error:
            raise
        # Docker startup can exceed the frozen probe window; retain its fence
        # and require the original service's health contract within 60 seconds.
        if range_scope:
            request=urllib.request.Request('http://127.0.0.1:8931/health')
        else:
            key_path=base.rooted(admission_fence.root,'/run/fs-hermes-fc/api-key')
            base.no_target_link(key_path)
            request=urllib.request.Request('http://127.0.0.1:8941/v1/capabilities',
                headers={'Authorization':'Bearer '+key_path.read_text('ascii').strip()})
        while time.monotonic() < worker_deadline:
            unit='fs-business-range.service' if range_scope else 'fs-hermes-fc.service'
            if subprocess.run(['systemctl', 'is-active', '--quiet',unit],
                              check=False, timeout=10).returncode == 0:
                try:
                    with urllib.request.urlopen(request, timeout=1) as response:
                        raw = response.read(128001)
                        value=json.loads(raw)
                        if len(raw)>128000 or not isinstance(value,dict) or range_scope and value.get('ok') is not True:
                            if range_scope:raise ValueError('range health contract')
                            raise ValueError('Hermes capabilities contract')
                        return
                except OSError:
                    pass
            time.sleep(min(1, max(0, worker_deadline - time.monotonic())))
        raise ValueError(expected_error+' after 60s') from exc
