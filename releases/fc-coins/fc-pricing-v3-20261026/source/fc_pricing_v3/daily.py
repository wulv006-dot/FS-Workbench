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
        db.put('metadata','daily_online_context',outcomes['online'])
        for settlement in outcomes['online'].get('budget_settlements',[]):db.settle_order(settlement)
        record['learning_coverage']=outcomes['online'].get('learning_coverage')
        db.put('metadata',key,record)
    export_shadow_snapshot(db,force=True)
    result_path=STATE/('daily-'+date+'.json')
    if not result_path.exists():
        active=subprocess.run(['systemctl','is-active','--quiet','fc-pricing-v3-shadow.service'],timeout=10).returncode==0
        if not active:
            write_json(STATE/'request.json',dict(local_date=date,request_id=record['request_id']))
            started=subprocess.run(['systemctl','start','--no-block','fc-pricing-v3-shadow.service'],capture_output=True,timeout=15)
            if started.returncode:raise ValueError('pricing_daily_shadow_start_failed')
        raise ValueError('pricing_daily_shadow_pending')
    shadow=json.loads(result_path.read_text())
    if shadow.get('local_date')!=date:raise ValueError('pricing_daily_shadow_date_mismatch')
    record['shadow']=shadow
    if 'decision_basis' not in record:
        with db.connect() as conn:
            row=conn.execute('SELECT body FROM pricing_snapshots ORDER BY rowid DESC LIMIT 1').fetchone()
        snapshot=json.loads(row[0]) if row else {}
        evidence=snapshot.get('evidence') or {}
        model=evidence.get('demand_model') or {}
        plan=db.active_plan() or {}
        mix=evidence.get('historical_discount_mix') or {}
        record['decision_basis']=dict(snapshot_id=snapshot.get('snapshot_id'),mode=plan.get('mode'),plan_state=plan.get('state'),
            parameters=plan.get('parameters'),daily_budget_usd=plan.get('daily_budget'),
            history={k:mix.get(k) for k in ('period','net_order_usd','discount_usd','undiscounted_order_usd','retained_ratio','sha256')},
            demand_model={k:model.get(k) for k in ('status','elasticity','groups','observed_window_hours','rate_window_hours')},
            source_plan=evidence.get('source_plan'),basis_is_latest_saved_input=True)
    report={k:record.get(k) for k in ('local_date','actual','learning_coverage','shadow','decision_basis')}
    quote=dict(run_id=record['request_id'],daily_report=report,result=dict(decision_receipt=dict(sha256=fingerprint(report))))
    receipt=bridge.review(dict(job_id=record['request_id'],actor='wulv'),quote,mode='daily_review',wait_seconds=0)
    record['hermes']=receipt
    record['phase']='completed' if receipt['phase']=='completed' else receipt['phase']
    db.put('metadata',key,record)
    db.put('metadata','latest_daily_review',record)
    if receipt['phase'] in ('unknown','failed','timeout'):
        db.incident('pricing_daily_hermes_'+receipt['phase'],'daily_effect_review',['FC27'],original_request_id=record['request_id'])
        return record
    if receipt['phase']!='completed':raise ValueError('pricing_daily_hermes_pending')
    return record


if __name__=='__main__':
    data=json.load(__import__('sys').stdin)
    print(json.dumps(collect_outcomes(data['local_date'],data['windows'])))
