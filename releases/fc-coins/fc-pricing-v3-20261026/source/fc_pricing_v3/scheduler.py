"""Single durable FC due scheduler; recovery/deadlines never wait for collection."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import sqlite3
import tempfile
import time
import uuid

from .engine import POLICIES
from .financial import fingerprint, instant
from .ledger import clock
from .runtime import ledger, ROOT, STORE, execute_run, reconcile, complete_player_followup

PRIORITY={'deadline':0,'exit':1,'reconcile':2,'start':3,'postwrite_refresh':3,'uk_retirement':3,'cycle':4,'observe':5,'daily':5,'history':5}
BACKOFF=(5,15,30,60)
SHADOW_EXPORT=STORE/'shadow-readonly.sqlite3'

def cycle_interval(policy=None):
    from automation_policy import load_policy
    value=(policy or load_policy())['interval_minutes']
    if type(value) is not int or not 1 <= value <= 9999:
        raise ValueError('automation_interval_invalid')
    return timedelta(minutes=value)


def next_cycle_at(db,plan,policy=None):
    """One configured clock per plan, without replaying paused or old due slots."""
    anchor=plan.get('last_cycle_at')
    if not anchor:
        def completed_times(conn):
            completed=[]
            for row in conn.execute('SELECT body FROM operations'):
                op=json.loads(row[0])
                if op.get('plan_id')==plan['plan_id'] and op.get('status') in ('COMPLETED','NO_CHANGE') and op.get('completed_at'):
                    completed.append(instant(op['completed_at']))
            return completed
        if isinstance(db,sqlite3.Connection):
            completed=completed_times(db)
        else:
            with db.connect() as conn:completed=completed_times(conn)
        if completed:anchor=max(completed).isoformat()
    anchors=[instant(anchor or plan['starts_at'])]
    if plan.get('resumed_at'):anchors.append(instant(plan['resumed_at']))
    if policy is None:
        from automation_policy import load_policy
        policy=load_policy()
    if policy.get('updated_at'):anchors.append(instant(policy['updated_at']))
    return max(anchors)+cycle_interval(policy)


def finish_cycle(db,conn,body,result,at):
    if result.get('status')=='superseded':return
    plan=db.get('pricing_plans',body.get('plan_id'),conn) if body.get('plan_id') else None
    if plan:
        plan['last_cycle_at']=at
        db.put('pricing_plans',plan['plan_id'],plan,conn)


def cycle_matches_plan(db,plan,body,ident,conn=None):
    if body.get('plan_id')!=plan['plan_id']:return False
    if 'revision' in body:return body['revision']==plan['revision']
    # The old exit producer created revision 1 and one exact durable ID. No
    # other revisionless cycle carries evidence of its originating revision.
    if (ident!='exit-cycle:'+plan['plan_id'] or plan['revision']!=1
            or plan.get('transition_reason')!='EXIT' or not plan.get('parent_plan_id')):return False
    parent=db.get('pricing_plans',plan['parent_plan_id'],conn)
    return bool(parent and parent.get('exit_plan_id')==plan['plan_id'])


def export_shadow_snapshot(db, target=SHADOW_EXPORT, *, force=False):
    """Publish one consistent, read-only SQLite snapshot for the isolated consumer.

    CentOS SQLite 3.7 cannot open the live WAL from a read-only mount.  The
    coordinator already owns this database; its online backup preserves the
    outbox sequence without granting the shadow process production write access.
    """
    target=Path(target)
    with db.connect() as source:
        current=source.execute('SELECT coalesce(max(id),0) FROM event_outbox').fetchone()[0]
        if target.exists():
            with closing(sqlite3.connect('file:'+str(target.resolve())+'?mode=ro',uri=True)) as published:
                old=published.execute('SELECT coalesce(max(id),0) FROM event_outbox').fetchone()[0]
            if old==current and not force:
                return dict(status='current',cursor=current)
        fd,name=tempfile.mkstemp(prefix='.shadow-export-',suffix='.sqlite3',dir=str(target.parent))
        os.close(fd)
        try:
            with closing(sqlite3.connect(name)) as destination:
                source.backup(destination)
                if destination.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower()!='delete':
                    raise ValueError('shadow_export_delete_journal_required')
                exported=destination.execute('SELECT coalesce(max(id),0) FROM event_outbox').fetchone()[0]
            if os.name=='posix':
                os.chmod(name,0o640)
                if target==SHADOW_EXPORT:
                    if os.geteuid()!=0:
                        raise ValueError('production_shadow_export_requires_root')
                    os.chown(name,0,11028)
            os.replace(name,target)
            if os.name=='posix':
                directory=os.open(str(target.parent),os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(directory)
                finally:os.close(directory)
            return dict(status='published',cursor=exported)
        finally:
            Path(name).unlink(missing_ok=True)


def cycle(body=None):
    import fc27_cloud_worker as worker
    from automation_policy import load_policy
    db=ledger()
    body=body or {}
    requested=db.get('pricing_plans',body['plan_id']) if body.get('plan_id') else db.active_plan()
    if not requested or requested['mode'] not in POLICIES or requested['state']!='ACTIVE' or body.get('revision',requested['revision'])!=requested['revision']:
        return dict(status='superseded')
    if body.get('_durable_job_id') and not cycle_matches_plan(db,requested,body,body['_durable_job_id']):
        return dict(status='superseded')
    with db.connect() as conn:
        try:db.owns(requested,requested['resources'],conn)
        except ValueError:return dict(status='superseded')
    root_key=body.get('request_id') or body.get('_durable_job_id') or requested['plan_id']+':'+str(int(clock().timestamp())//600)
    operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-operation:'+root_key))
    existing=db.get('operations',operation_id)
    if existing:
        return complete_player_followup(existing) if existing['status'] in ('COMPLETED','NO_CHANGE') else reconcile(operation_id)
    if body.get('manual_preview_id'):
        original=db.get('manual_previews',body['manual_preview_id'])
        existing=db.get('operations',original['operation_id']) if original else None
        if existing:
            return reconcile(existing['operation_id']) if existing['status'] not in ('COMPLETED','NO_CHANGE') else complete_player_followup(existing)
    pending=[o for o in db.all('operations') if o['status'] in ('DISPATCHED','UNKNOWN','PARTIALLY_APPLIED','BACKEND_CONFIRMED','CACHE_CONFIRMED','PUBLIC_PENDING','KNOWN_PARTIAL_PUBLIC_PENDING') and set(o['resources'])&set(requested['resources'])]
    for op in pending:
        reconcile(op['operation_id'])
    if pending:
        return dict(status='original_operation_reconciliation_pending')
    policy=load_policy()
    if not policy['system_enabled'] or not body.get('manual_requested') and policy['mode']!='auto':
        return dict(status='operator_paused')
    from .business_source import history_ES_blocker
    from .selective_sources import history_period
    blocked=history_ES_blocker(history_period(clock()))
    if blocked:
        db.incident(blocked['reason'],'ES_export',['FC27'],phase='source_precheck',error=blocked['reason'])
        raise ValueError(blocked['reason'])
    ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-collection:'+root_key+':'+str(body.get('_attempt',0))))
    job=dict(job_id=ident,kind='v3_cycle',actor='system-automation',status='running',
             created_at=clock().isoformat(),request=dict(policy_revision=policy['revision'],v3_plan_id=requested['plan_id'],
                 v3_operation_id=operation_id,manual_requested=bool(body.get('manual_requested')),request_id=root_key),
             engine_generation=db.generation()['id'])
    worker.save_job(job)
    try:
        collected=worker.collect_quote(job)
        quote=json.loads((ROOT/'quotes'/(collected['run_id']+'.json')).read_text())
        if body.get('manual_preview_id'):
            manual=db.get('manual_previews',body['manual_preview_id'])
            if not manual or manual['actor']!=body.get('actor') or manual['plan_id']!=requested['plan_id'] or manual['revision']!=requested['revision']:
                raise ValueError('pricing_manual_preview_scope_changed')
            if clock()>=instant(manual['valid_until']):
                raise ValueError('pricing_manual_preview_expired')
            from .runtime import override_quote,calculate,write_json
            checked=override_quote(quote['evidence'],manual['explicit_prices'],manual['reason'],manual.get('restore_source_execution_id'),requested)
            db.put('strategy_decisions','before-manual:'+quote['result']['decision_receipt']['decision_bundle_id'],quote['result']['decision_receipt'])
            quote['result']=calculate(quote['evidence'],quote.get('edits'),selected_action=checked['selected']['action'],override_reason=manual['reason'],operation_id=manual['operation_id'])
            write_json(ROOT/'quotes'/(collected['run_id']+'.json'),quote)
        job['decision_source']='program_current_strategy'
        worker.save_job(job)
        outcome=execute_run(collected['run_id'])
        plan=db.get('pricing_plans',outcome.get('plan_id') or quote['result']['decision_receipt']['plan_id'])
        if plan and plan.get('parent_plan_id') and outcome.get('status') in ('COMPLETED','NO_CHANGE'):
            with db.transaction() as conn:
                old=db.get('pricing_plans',plan['parent_plan_id'],conn)
                old.update(state='ENDED',ended_at=clock().isoformat(),exit_operation_id=outcome['operation_id'])
                db.put('pricing_plans',old['plan_id'],old,conn)
                for row in conn.execute('SELECT id,body FROM operations'):
                    original=json.loads(row['body'])
                    if original.get('plan_id')==old['plan_id'] and original.get('status')=='KNOWN_PARTIAL_EXIT_PENDING':
                        original.update(status='KNOWN_PARTIAL_EXITED',exit_operation_id=outcome['operation_id'],completed_at=clock().isoformat())
                        db.put('operations',row['id'],original,conn)
        job.update(status='ready',v3_outcome=outcome,result=dict(status='confirmed' if outcome.get('status')=='COMPLETED' else 'no_price_change' if outcome.get('status')=='NO_CHANGE' else outcome.get('status'),execution_id=outcome.get('operation_id'),platforms=outcome.get('readback',{}).get('public',{}).get('platforms',[])),completed_at=clock().isoformat())
        if outcome.get('status')=='COMPLETED':
            complete_player_followup(outcome,job)
    except Exception as exc:
        code=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        if isinstance(exc,ValueError) and code.lower().startswith(('pricing_v3_infeasible:','pricing_v3_capacity_unresolved:')):
            result=dict(status='INFEASIBLE',reason=code)
            job.update(status='ready',result=result,completed_at=clock().isoformat())
            worker.save_job(job)
            return result
        job.update(status='failed',error=code[:400],completed_at=clock().isoformat())
        if not any(word in code.lower() for word in ('infeasible','capacity_unresolved')):
            db.incident(code.split(':')[0],'collection_or_execution',['FC27'],error=type(exc).__name__)
        worker.save_job(job)
        raise
    worker.save_job(job)
    return job['result']


def refresh_postwrite(body):
    """Fresh proof for one original ALL continuation; no new Order save or sync."""
    import fc27_cloud_worker as worker
    from .runtime import calculate,write_json,postwrite_owner
    from automation_policy import load_policy
    db=ledger();operation_id=body['operation_id'];op=db.get('operations',operation_id)
    if not op or op['status'] in ('COMPLETED','NO_CHANGE'):return dict(status='original_completed')
    try:plan=postwrite_owner(db,op)
    except ValueError as exc:
        op['auto_postwrite_stopped']=dict(reason=str(exc),checked_at=clock().isoformat())
        db.put('operations',operation_id,op)
        return dict(status='original_target_no_longer_authorized',operation_id=operation_id,reason=str(exc))
    ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-postwrite:'+body['_durable_job_id']+':'+str(body.get('_attempt',0))))
    job=dict(job_id=ident,kind='v3_postwrite_collection',actor=op['dispatch_context']['actor'],status='running',created_at=clock().isoformat(),
             request=dict(v3_plan_id=plan['plan_id'],v3_operation_id=operation_id,policy_revision=load_policy()['revision'],
                          v3_authorization_purpose='original_unsent_ALL_steps_only'))
    worker.save_job(job)
    try:
        collected=worker.collect_quote(job)
        path=ROOT/'quotes'/(collected['run_id']+'.json');quote=json.loads(path.read_text())
        bundle=quote['result']['decision_receipt']
        if bundle.get('authorization_purpose')!='original_unsent_ALL_steps_only':raise ValueError('pricing_postwrite_purpose_missing')
        auth=STORE/'postwrite-authorizations'/(operation_id+'.json');auth.parent.mkdir(parents=True,exist_ok=True)
        write_json(auth,dict(operation_id=operation_id,original_operation_id=operation_id,quote_run_id=collected['run_id'],generation=op['generation'],
                             current_generation=plan['generation'],authorizing_plan_id=plan['plan_id'],revision=plan['revision'],
                             quote_sha256=bundle['sha256'],authorizes='original_unsent_ALL_steps_only'))
        result=reconcile(operation_id)
        job.update(status='ready',result=dict(status=result['status'],operation_id=operation_id),completed_at=clock().isoformat())
        worker.save_job(job)
        return result
    except Exception as exc:
        job.update(status='failed',error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__,completed_at=clock().isoformat())
        worker.save_job(job);raise


def exit_plan(body):
    db=ledger()
    old=db.get('pricing_plans',body['plan_id'])
    if not old or old['revision']!=body['revision']:
        return dict(status='superseded')
    with db.connect() as conn:
        owned=[r[0] for r in conn.execute('SELECT resource FROM plan_ownership WHERE plan_id=? AND revision=?',
                                       (old['plan_id'],old['revision']))]
    if not owned:
        if old.get('exit_plan_id') and old['state']=='ENDING':
            return old
        old['state']='ENDED'
        db.put('pricing_plans',old['plan_id'],old)
        return old
    if old['state']=='SUSPENDED' or old.get('deadline_pending_while_suspended'):
        return dict(status='suspended_no_exit_price',plan_id=old['plan_id'])
    # New EXIT lineage has its own current proof/authority; old deadline or spend cannot block it.
    next_plan=db.get('pricing_plans',old['exit_plan_id']) if old.get('exit_plan_id') else None
    if not next_plan:
        next_plan=db.create_plan('daily',owned,old['price_anchor'],
                                 actor=old['actor'],manual_locked=False,
                                 plan_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-exit:'+old['plan_id']+':'+str(old['revision']))))
        next_plan['parent_plan_id']=old['plan_id']
        next_plan['transition_reason']='EXIT'
        from automation_policy import load_policy
        policy=load_policy()
        next_plan['last_cycle_at']=(next_cycle_at(db,old,policy)-cycle_interval(policy)).isoformat()
        db.put('pricing_plans',next_plan['plan_id'],next_plan)
        old.update(state='ENDING',exit_plan_id=next_plan['plan_id'],exit_status='EXIT_PENDING')
        db.put('pricing_plans',old['plan_id'],old)
    db.activate_plan(next_plan['plan_id'])
    due_at=max(clock(),next_cycle_at(db,next_plan))
    db.enqueue('cycle','exit-cycle:'+next_plan['plan_id'],due_at,dict(plan_id=next_plan['plan_id'],revision=next_plan['revision']))
    return next_plan


def run_job(job):
    db=ledger()
    body=json.loads(job['body'])
    body['_durable_job_id']=job['id']
    body['_attempt']=job['attempt']
    kind=job['kind']
    try:
        if kind=='deadline':
            result=db.deadline(body['plan_id'],body['revision'])
        elif kind=='exit':
            result=exit_plan(body)
        elif kind=='start':
            result=db.activate_plan(body['plan_id'])
        elif kind=='reconcile':
            result=reconcile(body['operation_id'])
        elif kind=='postwrite_refresh':
            result=refresh_postwrite(body)
        elif kind=='uk_retirement':
            from .uk_retirement import run as retire_uk
            result=retire_uk(body)
        elif kind=='history':
            from .history import run as historical_run
            result=historical_run(body)
        elif kind=='daily':
            from .daily import run as daily_run
            result=daily_run(body)
        elif kind=='observe':
            from .observations import observe
            result=observe(body['snapshot_id'])
        else:
            result=cycle(body)
        with db.transaction() as conn:
            completed_at=clock().isoformat()
            if kind=='cycle':finish_cycle(db,conn,body,result,completed_at)
            body['completed_at']=completed_at
            conn.execute('UPDATE durable_jobs SET state=\'done\',body=? WHERE id=?',
                         (json.dumps(dict(body,result=result)),job['id']))
    except Exception as exc:
        code=str(exc)
        terminal=('INFEASIBLE','CAPACITY_UNRESOLVED','pricing_generation_retired','pricing_resource_taken_over',
                  'pricing_plan_expired','pricing_plan_scope','pricing_competitive_band','pricing_review_pending')
        if any(t.lower() in code.lower() for t in terminal):
            with db.transaction() as conn:
                body.update(result=dict(status='INFEASIBLE' if 'INFEASIBLE' in code.upper() or 'CAPACITY_UNRESOLVED' in code.upper() else 'REJECTED_PREWRITE',reason=code))
                body['completed_at']=clock().isoformat()
                if kind=='cycle':finish_cycle(db,conn,body,body['result'],body['completed_at'])
                conn.execute('UPDATE durable_jobs SET state=\'done\',body=? WHERE id=?',(json.dumps(body),job['id']))
            return
        attempt=job['attempt']+1
        delay=BACKOFF[min(attempt-1,len(BACKOFF)-1)]
        retry_after=getattr(exc,'retry_after_seconds',0)
        delay_seconds=max(delay*60,retry_after)
        body.update(error=str(exc)[:300],timeout_kind='subprocess_timeout' if type(exc).__name__=='TimeoutExpired' else None,
                    exit_code=getattr(exc,'returncode',None),circuit='open_low_frequency_probe' if attempt>=len(BACKOFF) else 'retry')
        with db.transaction() as conn:
            conn.execute('UPDATE durable_jobs SET state=\'queued\',attempt=?,due_at=?,body=? WHERE id=?',
                         (attempt,(clock()+timedelta(seconds=delay_seconds)).isoformat(),json.dumps(body),job['id']))


def tick(executors, running):
    db=ledger()
    now=clock()
    for key,future in list(running.items()):
        if future.done():
            future.result()
            del running[key]
    from .daily import due_date
    date=due_date(now)
    if date:db.enqueue('daily','daily:'+date,now,dict(local_date=date))
    plans=db.active_plans()
    for plan in plans:
        if plan and plan.get('deadline_pending_while_suspended') and plan.get('ends_at') and now>=instant(plan['ends_at']):
            db.deadline(plan['plan_id'],plan['revision'])
    from .daily import due_date
    date=due_date(now)
    if date:db.enqueue('daily','daily:'+date,now,dict(local_date=date))
    plans=db.active_plans()
    for plan in plans:
      if plan and plan['state']=='ACTIVE':
        due_at=next_cycle_at(db,plan)
        with db.connect() as conn:
            pending=any(cycle_matches_plan(db,plan,json.loads(row['body']),row['id'],conn) for row in
                        conn.execute('SELECT id,body FROM durable_jobs WHERE kind=\'cycle\' AND state IN (\'queued\',\'running\')'))
        if not pending and now>=due_at:
            key='cycle:'+plan['plan_id']+':'+str(int(due_at.timestamp()))+':r'+str(plan.get('resume_count',0))
            db.enqueue('cycle',key,now,dict(plan_id=plan['plan_id'],revision=plan['revision']))
    for op in db.all('operations'):
        if op['status'] in ('DISPATCHED','UNKNOWN','PARTIALLY_APPLIED','BACKEND_CONFIRMED','CACHE_CONFIRMED','PUBLIC_PENDING','KNOWN_PARTIAL_PUBLIC_PENDING'):
            with db.connect() as conn:
                pending=any(json.loads(row[0]).get('operation_id')==op['operation_id'] for row in
                            conn.execute('SELECT body FROM durable_jobs WHERE kind=\'reconcile\' AND state IN (\'queued\',\'running\')'))
            if not pending:
                db.enqueue('reconcile','reconcile:'+op['operation_id']+':'+str(int(now.timestamp())//300),now,
                           dict(operation_id=op['operation_id']))
    with db.transaction() as conn:
        cursor=conn.execute("SELECT value FROM consumer_cursors WHERE id='external_market_observer'").fetchone()
        after=cursor[0] if cursor else 0
        for event in conn.execute('SELECT id,kind,body FROM event_outbox WHERE id>? ORDER BY id LIMIT 100',(after,)).fetchall():
            if event['kind']=='snapshot_ready':
                snapshot_id=json.loads(event['body'])['snapshot_id']
                job_path=ROOT/'jobs'/(snapshot_id+'.json')
                job=json.loads(job_path.read_text()) if job_path.exists() else {}
                if job.get('status') in ('queued','running'):break
                db.enqueue('observe','observe:'+snapshot_id,now,dict(snapshot_id=snapshot_id),conn)
            if conn.execute("UPDATE consumer_cursors SET value=? WHERE id='external_market_observer'",(event['id'],)).rowcount==0:
                conn.execute("INSERT INTO consumer_cursors VALUES ('external_market_observer',?)",(event['id'],))
    with db.connect() as conn:
        due=[dict(row) for row in conn.execute('SELECT * FROM durable_jobs WHERE state=\'queued\' AND due_at<=?',(now.isoformat(),))]

    for job in sorted(due,key=lambda j:(PRIORITY[j['kind']],j['due_at'])):
        lane='observation' if job['kind'] in ('observe','daily','history') else 'collection' if job['kind'] in ('cycle','postwrite_refresh','uk_retirement') else 'control'
        if lane in running:
            continue
        with db.transaction() as conn:
            if conn.execute('UPDATE durable_jobs SET state=\'running\' WHERE id=? AND state=\'queued\'',(job['id'],)).rowcount!=1:
                continue
        running[lane]=executors[lane].submit(run_job,job)
    export_shadow_snapshot(db)
    from .runtime import write_json
    write_json(STORE/'heartbeat.json',dict(checked_at=now.isoformat(),generation=db.generation(),
               active_plans=plans,running=list(running),due_jobs=len(due),scheduler='single_fc_v3'))


def main():
    db=ledger()
    # A crashed collection can retry; any dispatch is reconciled from its durable operation first.
    with db.transaction() as conn:
        conn.execute('UPDATE durable_jobs SET state=\'queued\' WHERE state=\'running\'')
    keeper=db.connect()
    stop=[]
    signal.signal(signal.SIGTERM,lambda *_:stop.append(True))
    executors={lane:ThreadPoolExecutor(max_workers=1) for lane in ('collection','control','observation')}
    running={}
    try:
        while not stop:
            tick(executors,running)
            for _ in range(60):
                if stop:
                    break
                time.sleep(1)
    finally:
        keeper.close()
        for executor in executors.values():
            executor.shutdown(wait=True)


if __name__=='__main__':
    main()
