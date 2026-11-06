"""One daily outcome review over saved price windows and isolated shadow results."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import uuid

from .financial import fingerprint,instant

LOCAL=timezone(timedelta(hours=8))
STATE=Path('/var/lib/fc-pricing-v3-shadow')


def due_date(now):
    local=now.astimezone(LOCAL)
    return (local.date()-timedelta(days=1)).isoformat() if (local.hour,local.minute)>=(2,20) else None


def hourly_actual(selected,coverage,date):
    complete=coverage.get('status')=='complete'
    hours=[dict(hour=h,orders=0,net_paid_usd='0') for h in range(24)]
    unplaced=0
    for archived,_ in (selected or {}).values():
        try:
            paid=instant(archived['paidAt']).astimezone(LOCAL)
            if paid.date().isoformat()!=date:raise ValueError('daily_paid_date_mismatch')
            row=hours[paid.hour]
            row['orders']+=1
            row['net_paid_usd']=str(Decimal(row['net_paid_usd'])+Decimal(archived['salesUsd']))
        except (KeyError,ValueError,TypeError):unplaced+=1
    periods=[]
    for first in range(0,24,6):
        rows=hours[first:first+6]
        periods.append(dict(start_hour=first,end_hour=first+6,orders=sum(r['orders'] for r in rows),
            net_paid_usd=str(sum((Decimal(r['net_paid_usd']) for r in rows),Decimal(0)))))
    return dict(local_date=date,timezone='Asia/Shanghai',currency='USD',basis='paid_Coins_orders_site266_game1327',
        status='complete' if complete and not unplaced else 'partial',hourly=hours,periods=periods,
        unplaced_orders=unplaced,missing_hours_are_zero=complete and not unplaced,
        low_demand_period=min(periods,key=lambda r:r['orders']) if complete and not unplaced else None,
        high_demand_period=max(periods,key=lambda r:r['orders']) if complete and not unplaced else None,
        source_sha256=fingerprint(coverage),profit_status='actual_cost_coverage_required_not_inferred_from_USD_revenue')


def exposure_scope(windows,date):
    from .business_source import _window_end
    start=datetime.fromisoformat(date).replace(tzinfo=LOCAL);stop=start+timedelta(days=1)
    periods=[]
    valid=[w for w in windows if w.get('origin')=='confirmed_public_price_window' and w.get('mode')=='production']
    for window in valid:
        opened=instant(window['opened_at'])
        for resource in window.get('mutable_resources',[]):
            group=resource.removeprefix('base:') if resource.startswith('base:') else resource.removeprefix('region:')
            if not resource.startswith(('base:','region:')):continue
            end=_window_end(window,group,valid,stop)
            if max(start,opened)<min(stop,end):periods.append((max(start,opened),min(stop,end),window['operation_id']))
    return dict(status='confirmed_windows_available' if periods else 'no_confirmed_exposure',
        first_exposure_at=min((p[0] for p in periods),default=None).isoformat() if periods else None,
        last_observed_through=max((p[1] for p in periods),default=None).isoformat() if periods else None,
        confirmed_operation_count=len({p[2] for p in periods}),source_sha256=fingerprint(windows),
        attribution='only_orders_bound_by_creation_and_actual_price_are_effect_samples; full_day_orders_are_business_context; range_is_not_continuous_coverage_proof')


def collect_outcomes(date,windows):
    """Admin/Order business reads only; no competitor, public price or write endpoint."""
    import sys
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages,COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    from .business_source import _period_population,online_window_context
    selected,coverage=_period_population(dict(start=date,end=date))
    session=auth.Session()
    token,_=auth.admin_token_from_service()
    if not token:raise ValueError('pricing_daily_shared_admin_unavailable')
    session.bind_admin_token(token);del token
    from .selective_sources import history_period
    now=datetime.now(timezone.utc)
    learning_rows,_=_period_population(history_period(now))
    learning_rows = dict(learning_rows or {}, **(selected or {}))
    try:online=online_window_context(session,pages,windows,now,learning_rows or {})
    finally:session.close()
    return dict(actual=hourly_actual(selected,coverage,date),online=online)


def run(body):
    from .runtime import ledger,write_json,ROOT
    from .scheduler import export_shadow_snapshot
    import hermes_pricing_bridge as bridge
    db=ledger();date=body['local_date'];key='daily:'+date
    record=db.get('metadata',key) or dict(local_date=date,request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-daily:'+date)),
        phase='created',price_write_performed=False,automatic_strategy_switch=False)
    if record.get('phase')=='completed':return record
    if 'actual' not in record:
        process=subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.daily'],
            input=json.dumps(dict(local_date=date,windows=db.all('actual_price_windows'))),text=True,
            capture_output=True,timeout=240,cwd='/opt/fc27-cloud-browser')
        if process.returncode:raise ValueError('pricing_daily_outcome_collection_failed')
        outcomes=json.loads(process.stdout)
        record['actual']=outcomes['actual']
        record['price_exposure']=exposure_scope(db.all('actual_price_windows'),date)
        db.put('metadata','daily_online_context',outcomes['online'])
        for settlement in outcomes['online'].get('budget_settlements',[]):db.settle_order(settlement)
        record['learning_coverage']=outcomes['online'].get('learning_coverage')
        db.put('metadata',key,record)
    export_shadow_snapshot(db,force=True)
    from .history import ensure_shadow
    dispatched=ensure_shadow(db,'daily',record['request_id'],date)
    if dispatched['status']=='pending':raise ValueError('pricing_daily_shadow_pending')
    if dispatched['status']=='unknown':
        record.update(phase='unknown',shadow=dispatched)
        db.put('metadata',key,record);db.put('metadata','latest_daily_review',record)
        return record
    record['shadow']=dispatched.get('result') or dispatched
    if 'decision_basis' not in record:
        with db.connect() as conn:
            row=conn.execute('SELECT body FROM pricing_snapshots ORDER BY rowid DESC LIMIT 1').fetchone()
        snapshot=json.loads(row[0]) if row else {}
        evidence=snapshot.get('evidence') or {}
        model=evidence.get('demand_model') or {}
        plan=db.active_plan() or {}
        mix=evidence.get('historical_discount_mix') or {}
        record['decision_basis']=dict(snapshot_id=snapshot.get('snapshot_id'),mode=plan.get('mode'),plan_state=plan.get('state'),
            snapshot_sha256=fingerprint(evidence) if snapshot.get('snapshot_id') and isinstance(snapshot.get('evidence'),dict) else None,
            parameters=plan.get('parameters'),budget_policy='none',financial_contract_version=((snapshot.get('result') or {}).get('decision_receipt') or {}).get('financial_contract_version'),
            history={k:mix.get(k) for k in ('period','net_order_usd','discount_usd','undiscounted_order_usd','retained_ratio','sha256')},
            demand_model={k:model.get(k) for k in ('status','elasticity','groups','observed_window_hours','rate_window_hours')},
            source_plan=evidence.get('source_plan'),basis_is_latest_saved_input=True)
    report={k:record.get(k) for k in ('local_date','actual','learning_coverage','shadow','decision_basis','price_exposure')}
    quote=dict(run_id=record['request_id'],daily_report=report,result=dict(decision_receipt=dict(sha256=fingerprint(report))))
    record['phase']='review_prepared'
    db.put('metadata',key,record);db.put('metadata','latest_daily_review',record)
    receipt=bridge.review(dict(job_id=record['request_id'],actor='wulv'),quote,mode='daily_review',wait_seconds=0)
    record['hermes']=receipt
    record['phase']='completed' if receipt['phase']=='completed' else receipt['phase']
    db.put('metadata',key,record)
    db.put('metadata','latest_daily_review',record)
    if receipt['phase'] in ('unknown','failed','timeout'):
        db.incident('pricing_daily_hermes_'+receipt['phase'],'daily_effect_review',['FC27'],phase='daily_review',error='original_request_id:'+record['request_id'])
        return record
    if receipt['phase']!='completed':raise ValueError('pricing_daily_hermes_pending')
    return record


if __name__=='__main__':
    data=json.load(__import__('sys').stdin)
    print(json.dumps(collect_outcomes(data['local_date'],data['windows'])))
