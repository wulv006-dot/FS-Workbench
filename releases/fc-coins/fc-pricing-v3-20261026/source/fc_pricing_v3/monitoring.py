"""Read-only projections for the existing FC monitor and shared Hermes watchdog."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sqlite3


def shadow_progress(db,root,now):
    """Read the original outbox sequence and the independent shadow cursor."""
    event=db.execute("SELECT id,kind,body FROM event_outbox WHERE kind='snapshot_ready' ORDER BY id DESC LIMIT 1").fetchone()
    latest=event[0] if event else 0
    path=(Path('/var/lib/fc-pricing-v3-shadow/shadow.sqlite3') if root==Path('/var/lib/fc27-cloud')
          else root/'shadow.sqlite3')
    cursor=0
    if path.exists():
        try:
            with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=2)) as shadow:
                row=shadow.execute("SELECT value FROM cursor WHERE id='production'").fetchone()
                cursor=row[0] if row else 0
        except (OSError,sqlite3.Error):
            return dict(status='cursor_unreadable',latest_event_id=latest,cursor=None,
                        pending=None,lag_seconds=None)
    if latest<=cursor:
        return dict(status='current' if latest else 'idle',latest_event_id=latest,cursor=cursor,
                    pending=0,lag_seconds=0)
    first=db.execute("SELECT id,kind,body FROM event_outbox WHERE kind='snapshot_ready' AND id>? ORDER BY id LIMIT 1",(cursor,)).fetchone()
    pending=db.execute("SELECT count(*) FROM event_outbox WHERE kind='snapshot_ready' AND id>?",(cursor,)).fetchone()[0]
    if not first:
        return dict(status='event_unverified',latest_event_id=latest,cursor=cursor,pending=None,lag_seconds=None)
    body=json.loads(first[2]);created_at=body.get('requested_at') if first[1]=='simulation_requested' else None
    if first[1]=='snapshot_ready':
        row=db.execute('SELECT body FROM pricing_snapshots WHERE id=?',(body['snapshot_id'],)).fetchone()
        if row:created_at=json.loads(row[0]).get('created_at')
    if not created_at:
        return dict(status='event_time_unverified',latest_event_id=latest,cursor=cursor,
                    pending=pending,lag_seconds=None,first_pending_event_id=first[0])
    age=(now-datetime.fromisoformat(created_at.replace('Z','+00:00'))).total_seconds()
    from .daily import LOCAL
    captured=datetime.fromisoformat(created_at.replace('Z','+00:00')).astimezone(LOCAL)
    due=(captured+timedelta(days=1)).replace(hour=2,minute=20,second=0,microsecond=0)
    return dict(status='scheduled_daily' if now<due else 'stalled' if now>due+timedelta(minutes=5) else 'catching_up',
                latest_event_id=latest,cursor=cursor,pending=pending,lag_seconds=round(age),
                first_pending_event_id=first[0],next_daily_at=due.isoformat(),cadence='daily')


def source_coverage(snapshots,plans,now,interval_minutes=60):
    """Validate the last real owned snapshot per plan, within that plan's sampling interval."""
    from .financial import number,instant,required_history_ratio,fingerprint
    from .selective_sources import input_ratio as envelope_ratio
    from .engine import current_market_quotes
    if not plans:return dict(status='not_required_without_active_plan',plans=[],issues=[])
    checks=[];issues=[]
    for plan in plans:
        relevant=[row for row in snapshots if row.get('origin')=='live_collector' and row.get('mode')=='production' and
                  not row.get('authorization_purpose') and (plan is None or row.get('result',{}).get('decision_receipt',{}).get('plan_id')==plan['plan_id'])]
        snapshot=max(relevant,key=lambda row:row.get('created_at',''),default=None)
        scope=(plan or {}).get('plan_id','current_collection')
        failures=[];competitive_sources={}
        if not snapshot:failures.append('snapshot_missing')
        else:
            evidence=snapshot.get('evidence') or {};receipt=snapshot.get('result',{}).get('decision_receipt',{})
            mode=(plan or {}).get('mode',receipt.get('mode'))
            interval=interval_minutes
            try:
                as_of=instant(snapshot['created_at'])
                if not -5<=(now-instant(evidence['checked_at'])).total_seconds()<=interval*60+900:
                    failures.append('source_stale_or_clock_invalid')
                if receipt.get('snapshot_sha256')!=fingerprint(evidence):failures.append('snapshot_hash_mismatch')
                number(evidence['fx']['cny_per_usd'])
                if abs((as_of-instant(evidence['fx']['checked_at'])).total_seconds())>3600:failures.append('fx_stale')
                resources=(plan or {}).get('resources',['base:console','base:pc'])
                platforms=set()
                for resource in resources:
                    if resource=='base:console':platforms.update(('PS','XBOX'))
                    elif resource=='base:pc':platforms.add('PC')
                    elif resource.startswith('region:'):platforms.add(resource.split(':')[-1])
                if platforms & {'PS','XBOX'}:platforms.update(('PS','XBOX'))
                for platform in platforms:
                    cost=evidence['costs'][platform];own=evidence['storefront']['rows'][platform]
                    number(cost['cny_per_1k']);number(own['package_usd'])
                    if not str(cost.get('record_id','')).isdigit():failures.append('cost_identity_missing:'+platform)
                    if abs((as_of-instant(cost['checked_at'])).total_seconds())>3600:failures.append('cost_stale:'+platform)
                    if abs((as_of-instant(own['checked_at'])).total_seconds())>3600:failures.append('public_stale:'+platform)
                    quotes,missing=current_market_quotes(evidence,[platform],as_of)
                    available=[quote['source'] for quote in quotes]
                    daily_pricing=receipt.get('daily_pricing',{}).get('pc' if platform=='PC' else 'console',{})
                    competitive_sources[platform]=dict(available=available,missing=missing,margin_floor_only=not available,
                        price_driver_source=daily_pricing.get('driver_source'),price_driver_platform=daily_pricing.get('driver_platform'),
                        item_target_met=daily_pricing.get('item_target_met'),
                        item_target_unmet_reason=daily_pricing.get('unmet_reason'),
                        reference_difference_pct=daily_pricing.get('platforms',{}).get(platform,{}).get('difference_pct'),
                        average_margin_target_pct='30' if mode=='daily' and not available else '20')
                    if mode=='daily' and not available and (receipt.get('daily_reference') or {}).get(platform,{}).get('average_margin_target_pct')!='30':
                        failures.append('daily_missing_market_average_30_unverified:'+platform)
                required_history_ratio(evidence,as_of);envelope_ratio(evidence['promotion_envelope'],as_of)
                proof=receipt.get('financial_proof') or {}
                infeasible=(snapshot.get('result',{}).get('status')=='INFEASIBLE' and receipt.get('status')=='INFEASIBLE' and receipt.get('execution_authorized') is False)
                if not infeasible and (proof.get('pass_all') is not True or proof.get('execution_eligible') is not True):failures.append('financial_proof_missing')
                if snapshot.get('snapshot_id')!=evidence.get('run_id') or receipt.get('snapshot_id')!=evidence.get('run_id'):
                    failures.append('snapshot_identity_mismatch')
            except (ValueError,KeyError,TypeError,StopIteration):failures.append('source_fields_unverified')
        checks.append(dict(plan_id=scope,snapshot_id=(snapshot or {}).get('snapshot_id'),failures=failures,competitive_sources=competitive_sources))
        issues += [dict(level='critical',code='coin_v3_'+failure+':'+scope) for failure in failures]
    return dict(status='verified' if not issues else 'unverified',plans=checks,issues=issues)


def projection(root=Path('/var/lib/fc27-cloud'),now=None):
    now=now or datetime.now(timezone.utc)
    control_path=root/'config/v3-control.json'
    if not control_path.exists() or not json.loads(control_path.read_text()).get('enabled'):
        return dict(enabled=False)
    heartbeat=json.loads((root/'v3/heartbeat.json').read_text()) if (root/'v3/heartbeat.json').exists() else {}
    issues=[]
    checked=datetime.fromisoformat(heartbeat['checked_at']) if heartbeat.get('checked_at') else None
    if checked is None or (now-checked).total_seconds()>180:issues.append(dict(level='critical',code='coin_v3_scheduler_stale'))
    with closing(sqlite3.connect('file:'+str(root/'v3/control.sqlite3')+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        plans=[json.loads(row[0]) for row in db.execute('SELECT body FROM pricing_plans')]
        from .ledger import fully_owned_plans
        executable=fully_owned_plans(db)
        active=[p for p in executable if p['state'] in ('ACTIVE','ENDING')]
        owned=[p for p in executable if p['state'] in ('ACTIVE','ENDING')]
        owned += [p for p in plans if p['state']=='SUSPENDED']
        operations=[json.loads(row[0]) for row in db.execute('SELECT body FROM operations')]
        completed_cycles=[json.loads(row[0]) for row in db.execute("SELECT body FROM durable_jobs WHERE kind='cycle' AND state='done'")]
        completed_cycles=[c for c in completed_cycles if (c.get('result') or {}).get('status')!='superseded']
        snapshots=[]
        for plan in owned:
            pointer=db.execute('SELECT body FROM metadata WHERE id=?',('latest_snapshot:'+plan['plan_id'],)).fetchone()
            if pointer:
                snapshot_id=json.loads(pointer[0])['snapshot_id']
                row=db.execute('SELECT body FROM pricing_snapshots WHERE id=?',(snapshot_id,)).fetchone()
                if row:snapshots.append(json.loads(row[0]))
        jobs=[dict(id=row[0],kind=row[1],due_at=row[2],state=row[3],body=json.loads(row[4])) for row in db.execute("SELECT id,kind,due_at,state,body FROM durable_jobs WHERE state IN ('queued','running')")]
        shadow=shadow_progress(db,root,now)
        from .scheduler import next_cycle_at
        last_cycles=[p['last_cycle_at'] for p in owned if p.get('last_cycle_at')]
        last_cycles += [o['completed_at'] for o in operations if o.get('plan_id') in {p['plan_id'] for p in owned}
                        and o.get('status') in ('COMPLETED','NO_CHANGE') and o.get('completed_at')]
        latest_summary=db.execute("SELECT body FROM metadata WHERE id='latest_snapshot_summary'").fetchone()
        latest_summary=json.loads(latest_summary[0]) if latest_summary else {}
    if shadow['status'] in ('stalled','cursor_unreadable','event_unverified','event_time_unverified'):
        issues.append(dict(level='warning',code='coin_v3_shadow_'+shadow['status']))
    policy_path=root/'config/automation.json'
    policy=json.loads(policy_path.read_text()) if policy_path.exists() else {'system_enabled':False,'interval_minutes':60}
    operator_enabled=policy.get('system_enabled')
    with closing(sqlite3.connect('file:'+str(root/'v3/control.sqlite3')+'?mode=ro',uri=True,timeout=2)) as conn:
        cycle_times=[next_cycle_at(conn,p,policy).isoformat() for p in owned if p['state']=='ACTIVE']
    coverage=source_coverage(snapshots,active if operator_enabled else [],now,policy['interval_minutes'])
    issues.extend(coverage['issues'])
    for job in jobs:
        if job['kind'] in ('cycle','postwrite_refresh') and job['body'].get('error'):
            issues.append(dict(level='warning',code='coin_v3_dependency_retry:'+str(job['body'].get('source_failure',{}).get('code') or job['body']['error'])))
    pending=[op for op in operations if op['status'] not in ('COMPLETED','NO_CHANGE','REJECTED_PREWRITE','CANCELLED_NOT_SENT','SUPERSEDED','KNOWN_PARTIAL_EXITED')]
    for op in pending:
        if op['status'] in ('UNKNOWN','PARTIALLY_APPLIED'):issues.append(dict(level='critical',code='coin_v3_original_operation_'+op['status'].lower()+':'+op['operation_id']))
    next_at=min(cycle_times,default=None)
    background_next_at=min((j['due_at'] for j in jobs if j['kind']!='cycle'),default=None)
    state=owned[0]['state'] if len(owned)==1 else 'MULTIPLE' if owned else 'NONE'
    latest_source=max((row.get('evidence',{}).get('checked_at') for row in snapshots if row.get('evidence',{}).get('checked_at')),default=None)
    if not latest_source and latest_summary.get('plan_id') in {p['plan_id'] for p in owned}:
        latest_source=latest_summary.get('source_checked_at')
    status='unknown' if not checked else 'needs_reconcile' if pending else 'paused' if state=='SUSPENDED' else 'waiting' if active else 'no_active_plan'
    owned_ids={p['plan_id'] for p in owned}
    last_operation=max((o for o in operations if o.get('plan_id') in owned_ids),key=lambda o:o.get('created_at',''),default={})
    last_cycle=max((c for c in completed_cycles if c.get('plan_id') in owned_ids),key=lambda c:c.get('completed_at',''),default={})
    last_stage=last_operation.get('status')
    if last_cycle.get('completed_at','')>last_operation.get('completed_at',last_operation.get('created_at','')):
        result_status=(last_cycle.get('result') or {}).get('status')
        last_stage={'confirmed':'COMPLETED','no_price_change':'NO_CHANGE'}.get(result_status,result_status)
    return dict(enabled=True,scheduler='single_fc_v3',checked_at=heartbeat.get('checked_at'),generation=heartbeat.get('generation'),
                active_plans=[{k:p.get(k) for k in ('plan_id','revision','mode','state','resources','ends_at')} for p in active],
                schedule=dict(status=status,next_at=next_at,next_cycle_at=next_at,cycle_interval_minutes=policy['interval_minutes'],
                              last_cycle_at=max(last_cycles,default=None),last_snapshot_at=latest_summary.get('created_at'),
                              last_source_checked_at=latest_source,last_execution_stage=last_stage,
                              active_plan_state=state,background_next_at=background_next_at,
                              collection_status='v3_durable_due_queue'),
                pending_operations=[dict(operation_id=o['operation_id'],status=o['status'],plan_id=o.get('plan_id')) for o in pending],
                issues=issues,source_coverage=coverage,shadow=shadow,pending_count=len(pending),read_only=True)
