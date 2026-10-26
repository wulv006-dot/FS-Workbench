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
from .financial import instant
from .ledger import clock
from .runtime import ledger, ROOT, STORE, execute_run, reconcile

PRIORITY={'deadline':0,'exit':1,'reconcile':2,'start':3,'postwrite_refresh':3,'cycle':4,'observe':5}
BACKOFF=(5,15,30,60)
SHADOW_EXPORT=STORE/'shadow-readonly.sqlite3'


def export_shadow_snapshot(db, target=SHADOW_EXPORT):
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
            if old==current:
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
                os.chown(name,0,11028)
                os.chmod(name,0o640)
            os.replace(name,target)
            if os.name=='posix':
                directory=os.open(str(target.parent),os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(directory)
                finally:os.close(directory)
            return dict(status='published',cursor=exported)
        finally:
            Path(name).unlink(missing_ok=True)


def backlog_cleared(evidence, now):
    queue=(evidence.get('fulfillment_estimates') or {}).get('current_backlog_source') or {}
    order=queue.get('order_status_intersection') or {}
    try:
        return (queue.get('status')=='normal_delivery_gross_quantity_upper_estimate' and
                order.get('status')=='native_Order_status_1_2_verified' and
                bool(queue.get('source_sha256')) and
                int((queue.get('counts') or {})['active_Coins_orders'])==0 and
                float(queue['gross_ordered_delivery_k'])==0 and
                0<=(now-instant(queue['checked_at'])).total_seconds()<=900)
    except (KeyError,TypeError,ValueError):
        return False


def cycle(body=None):
    import fc27_cloud_worker as worker
    from automation_policy import load_policy
    db=ledger()
    body=body or {}
    requested=db.get('pricing_plans',body['plan_id']) if body.get('plan_id') else db.active_plan()
    if not requested or requested['state']!='ACTIVE' or body.get('revision',requested['revision'])!=requested['revision']:
        return dict(status='superseded')
    with db.connect() as conn:
        try:db.owns(requested,requested['resources'],conn)
        except ValueError:return dict(status='superseded')
    root_key=body.get('request_id') or body.get('_durable_job_id') or requested['plan_id']+':'+str(int(clock().timestamp())//600)
    operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-operation:'+root_key))
    existing=db.get('operations',operation_id)
    if existing:
        return existing if existing['status'] in ('COMPLETED','NO_CHANGE') else reconcile(operation_id)
    if body.get('manual_preview_id'):
        original=db.get('manual_previews',body['manual_preview_id'])
        existing=db.get('operations',original['operation_id']) if original else None
        if existing:
            return reconcile(existing['operation_id']) if existing['status'] not in ('COMPLETED','NO_CHANGE') else existing
    pending=[o for o in db.all('operations') if o['status'] in ('DISPATCHED','UNKNOWN','PARTIALLY_APPLIED','BACKEND_CONFIRMED','CACHE_CONFIRMED','PUBLIC_PENDING','KNOWN_PARTIAL_PUBLIC_PENDING') and set(o['resources'])&set(requested['resources'])]
    for op in pending:
        reconcile(op['operation_id'])
    if pending:
        return dict(status='original_operation_reconciliation_pending')
    policy=load_policy()
    if not policy['system_enabled'] or not body.get('manual_requested') and policy['mode']!='auto':
        return dict(status='operator_paused')
    ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-collection:'+root_key+':'+str(body.get('_attempt',0))))
    job=dict(job_id=ident,kind='v3_cycle',actor='system-automation',status='running',
             created_at=clock().isoformat(),request=dict(policy_revision=policy['revision'],v3_plan_id=requested['plan_id'],
                 v3_operation_id=operation_id,manual_requested=bool(body.get('manual_requested')),request_id=root_key),
             engine_generation=db.generation()['id'])
    worker.save_job(job)
    try:
        collected=worker.collect_quote(job)
        quote=json.loads((ROOT/'quotes'/(collected['run_id']+'.json')).read_text())
        if requested['mode']=='backlog' and backlog_cleared(quote['evidence'],clock()):
            db.deadline(requested['plan_id'],requested['revision'])
            job.update(status='ready',result=dict(status='backlog_cleared_exit_pending',plan_id=requested['plan_id']),completed_at=clock().isoformat())
            worker.save_job(job)
            return job['result']
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
        from hermes_pricing_bridge import review as hermes_review
        try:
            review=hermes_review(job,quote)
        except Exception as exc:
            review=dict(phase='unknown',reason=type(exc).__name__,do_not_replay=True,applied=False)
        job['hermes_review']=review
        worker.save_job(job)
        recommendation=review.get('recommendation') if review.get('phase')=='completed' else None
        if not body.get('manual_preview_id') and recommendation and recommendation.get('action_vector') and recommendation['action_vector']!=quote['result']['decision_receipt']['action']:
            from .runtime import calculate,write_json
            db.put('strategy_decisions','before-model:'+quote['result']['decision_receipt']['decision_bundle_id'],quote['result']['decision_receipt'])
            quote['result']=calculate(quote['evidence'],quote.get('edits'),selected_action=recommendation['action_vector'],override_reason='valid_hermes_current_candidate:'+recommendation['operation_id'],operation_id=operation_id)
            write_json(ROOT/'quotes'/(collected['run_id']+'.json'),quote)
        from .runtime import attach_review
        attach_review(collected['run_id'],review)
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
            config=worker.load_player_sync_policy()
            job['player_sync_intent']={'enabled':config['enabled'],'revision':config['revision']}
            worker.save_job(job)
            try:job['player_sync']=worker.enqueue_player_sync(job,config)
            except (OSError,ValueError) as exc:
                job['player_sync']=dict(status='pending',reason=type(exc).__name__,original_coin_execution_id=outcome['operation_id'])
    except Exception as exc:
        code=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        job.update(status='failed',error=code[:400],completed_at=clock().isoformat())
        if not any(word in code.lower() for word in ('infeasible','capacity_unresolved','budget_exhausted')):
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
    # New EXIT lineage has its own current proof/authority; old deadline or spend cannot block it.
    next_plan=db.get('pricing_plans',old['exit_plan_id']) if old.get('exit_plan_id') else None
    if not next_plan:
        next_plan=db.create_plan('daily',owned,old['price_anchor'],daily_budget=old['daily_budget'],
                                 actor=old['actor'],manual_locked=False,
                                 plan_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-exit:'+old['plan_id']+':'+str(old['revision']))))
        next_plan['parent_plan_id']=old['plan_id']
        next_plan['transition_reason']='EXIT'
        db.put('pricing_plans',next_plan['plan_id'],next_plan)
        old.update(state='ENDING',exit_plan_id=next_plan['plan_id'],exit_status='EXIT_PENDING')
        db.put('pricing_plans',old['plan_id'],old)
    db.activate_plan(next_plan['plan_id'])
    db.enqueue('cycle','exit-cycle:'+next_plan['plan_id'],clock(),dict(plan_id=next_plan['plan_id']))
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
        elif kind=='observe':
            from .observations import observe
            result=observe(body['snapshot_id'])
        else:
            result=cycle(body)
        with db.transaction() as conn:
            conn.execute('UPDATE durable_jobs SET state=\'done\',body=? WHERE id=?',
                         (json.dumps(dict(body,result=result)),job['id']))
    except Exception as exc:
        code=str(exc)
        if 'budget_exhausted' in code.lower():
            plan=db.get('pricing_plans',body.get('plan_id')) if body.get('plan_id') else db.active_plan()
            if plan and plan['mode'] in ('acquisition','flash_sale','revenue_sprint'):
                db.deadline(plan['plan_id'],plan['revision'])
            with db.transaction() as conn:
                body['result']=dict(status='BUDGET_EXHAUSTED',reason=code)
                conn.execute('UPDATE durable_jobs SET state=\'done\',body=? WHERE id=?',(json.dumps(body),job['id']))
            return
        terminal=('INFEASIBLE','CAPACITY_UNRESOLVED','pricing_generation_retired','pricing_resource_taken_over',
                  'pricing_plan_expired','pricing_plan_scope','pricing_competitive_band','pricing_review_pending')
        if any(t.lower() in code.lower() for t in terminal):
            with db.transaction() as conn:
                body.update(result=dict(status='INFEASIBLE' if 'INFEASIBLE' in code or 'CAPACITY_UNRESOLVED' in code else 'REJECTED_PREWRITE',reason=code))
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
    plans=db.active_plans()
    for plan in plans:
      if plan and plan['state']=='ACTIVE':
        interval=10 if plan['mode']=='revenue_sprint' else 30 if plan['mode']=='flash_sale' else 120
        bucket=int(now.timestamp())//(interval*60)
        with db.connect() as conn:
            pending=any(json.loads(row[0]).get('plan_id')==plan['plan_id'] for row in
                        conn.execute('SELECT body FROM durable_jobs WHERE kind=\'cycle\' AND state IN (\'queued\',\'running\')'))
        if not pending:
            db.enqueue('cycle','cycle:'+plan['plan_id']+':'+str(bucket),now,dict(plan_id=plan['plan_id'],revision=plan['revision']))
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
        lane='observation' if job['kind']=='observe' else 'collection' if job['kind'] in ('cycle','postwrite_refresh') else 'control'
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
