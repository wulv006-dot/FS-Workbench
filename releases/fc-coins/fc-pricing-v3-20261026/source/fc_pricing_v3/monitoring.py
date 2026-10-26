"""Read-only projections for the existing FC monitor and shared Hermes watchdog."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sqlite3


def source_coverage(snapshots,plans,now):
    """Validate the last real owned snapshot per plan, within that plan's sampling interval."""
    from .financial import number,instant,required_history_ratio,envelope_ratio,fingerprint
    from .engine import market_quote
    if not plans:return dict(status='not_required_without_active_plan',plans=[],issues=[])
    checks=[];issues=[]
    for plan in plans:
        relevant=[row for row in snapshots if row.get('origin')=='live_collector' and row.get('mode')=='production' and
                  not row.get('authorization_purpose') and (plan is None or row.get('result',{}).get('decision_receipt',{}).get('plan_id')==plan['plan_id'])]
        snapshot=max(relevant,key=lambda row:row.get('created_at',''),default=None)
        scope=(plan or {}).get('plan_id','current_collection')
        failures=[]
        if not snapshot:failures.append('snapshot_missing')
        else:
            evidence=snapshot.get('evidence') or {};receipt=snapshot.get('result',{}).get('decision_receipt',{})
            mode=(plan or {}).get('mode',receipt.get('mode'))
            interval=10 if mode=='revenue_sprint' else 30 if mode=='flash_sale' else 120
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
                    quote=evidence['offers'][platform]['Lootbar'];number(quote['usd_price'])
                    if quote.get('comparable') is False or quote.get('conditional') or abs((as_of-instant(quote['checked_at'])).total_seconds())>900:
                        failures.append('lootbar_not_current_comparable:'+platform)
                    if mode=='revenue_sprint':
                        try:market_quote(evidence,platform,'ItemD2R',as_of)
                        except ValueError as exc:failures.append(str(exc)+':'+platform)
                required_history_ratio(evidence,as_of);envelope_ratio(evidence['promotion_envelope'],as_of)
                proof=receipt.get('financial_proof') or {}
                if proof.get('pass_all') is not True or proof.get('execution_eligible') is not True:failures.append('financial_proof_missing')
                if snapshot.get('snapshot_id')!=evidence.get('run_id') or receipt.get('snapshot_id')!=evidence.get('run_id'):
                    failures.append('snapshot_identity_mismatch')
            except (ValueError,KeyError,TypeError,StopIteration):failures.append('source_fields_unverified')
        checks.append(dict(plan_id=scope,snapshot_id=(snapshot or {}).get('snapshot_id'),failures=failures))
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
        active=[p for p in plans if p['state'] in ('ACTIVE','ENDING')]
        operations=[json.loads(row[0]) for row in db.execute('SELECT body FROM operations')]
        snapshots=[]
        for plan in active:
            pointer=db.execute('SELECT body FROM metadata WHERE id=?',('latest_snapshot:'+plan['plan_id'],)).fetchone()
            if pointer:
                snapshot_id=json.loads(pointer[0])['snapshot_id']
                row=db.execute('SELECT body FROM pricing_snapshots WHERE id=?',(snapshot_id,)).fetchone()
                if row:snapshots.append(json.loads(row[0]))
        jobs=[dict(id=row[0],kind=row[1],due_at=row[2],state=row[3],body=json.loads(row[4])) for row in db.execute("SELECT id,kind,due_at,state,body FROM durable_jobs WHERE state IN ('queued','running')")]
    policy_path=root/'config/automation.json'
    operator_enabled=json.loads(policy_path.read_text()).get('system_enabled') if policy_path.exists() else True
    coverage=source_coverage(snapshots,active if operator_enabled else [],now)
    issues.extend(coverage['issues'])
    for job in jobs:
        if job['kind'] in ('cycle','postwrite_refresh') and job['body'].get('error'):
            issues.append(dict(level='warning',code='coin_v3_dependency_retry:'+str(job['body'].get('source_failure',{}).get('code') or job['body']['error'])))
    pending=[op for op in operations if op['status'] not in ('COMPLETED','NO_CHANGE','REJECTED_PREWRITE','CANCELLED_NOT_SENT','SUPERSEDED','KNOWN_PARTIAL_EXITED')]
    for op in pending:
        if op['status'] in ('UNKNOWN','PARTIALLY_APPLIED'):issues.append(dict(level='critical',code='coin_v3_original_operation_'+op['status'].lower()+':'+op['operation_id']))
    next_at=min((j['due_at'] for j in jobs),default=None)
    status='unknown' if not checked else 'needs_reconcile' if pending else 'waiting' if active else 'no_active_plan'
    return dict(enabled=True,scheduler='single_fc_v3',checked_at=heartbeat.get('checked_at'),generation=heartbeat.get('generation'),
                active_plans=[{k:p.get(k) for k in ('plan_id','revision','mode','state','resources','ends_at')} for p in active],
                schedule=dict(status=status,next_at=next_at,collection_status='v3_durable_due_queue'),
                pending_operations=[dict(operation_id=o['operation_id'],status=o['status'],plan_id=o.get('plan_id')) for o in pending],
                issues=issues,source_coverage=coverage,pending_count=len(pending),read_only=True)
