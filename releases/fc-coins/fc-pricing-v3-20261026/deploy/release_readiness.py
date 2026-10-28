"""Shared bounded readiness for the existing V3 code and knowledge publishers."""
import json
import subprocess
import time
import urllib.request


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
