"""Durable private history inputs and original-request dispatch to the isolated worker."""
from datetime import datetime,timedelta
import json
from pathlib import Path
import subprocess
import uuid

from .financial import fingerprint,instant
from .ledger import clock
from .runtime import ledger,write_json

STATE=Path('/var/lib/fc-pricing-v3-shadow')
UNIT='fc-pricing-v3-shadow.service'


def ensure_shadow(db,kind,request_id,local_date=None):
    payload=dict(kind=kind,request_id=request_id)
    if kind=='daily':payload['local_date']=local_date
    output=STATE/(('daily-'+local_date+'-two-mode' if kind=='daily' else 'history-'+request_id)+'.json')
    if output.exists():
        result=json.loads(output.read_text())
        if result.get('local_date' if kind=='daily' else 'request_id')!=(local_date if kind=='daily' else request_id):raise ValueError('shadow_original_reply_mismatch')
        return dict(status='completed',result=result)
    key='shadow-dispatch:'+request_id;intent=db.get('metadata',key)
    if intent and intent['request']!=payload:raise ValueError('shadow_original_request_conflict')
    state=subprocess.run(['systemctl','show',UNIT,'--no-pager','-p','ActiveState'],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    if state in ('ActiveState=active','ActiveState=activating','ActiveState=reloading'):return dict(status='pending')
    if intent:
        if intent['phase'] in ('starting','unknown'):return dict(status='unknown',original_request_id=request_id,do_not_replay=True)
        if intent['phase']=='submitted':
            intent.update(phase='failed',reason='original_worker_stopped_without_result',checked_at=clock().isoformat())
            db.put('metadata',key,intent)
            db.incident('pricing_shadow_'+kind+'_failed','shadow_execution',['FC27'],phase='shadow',error='original_request_id:'+request_id)
        return dict(status='failed',reason=intent.get('reason'),original_request_id=request_id)
    intent=dict(request=payload,phase='starting',created_at=clock().isoformat())
    db.put('metadata',key,intent)
    write_json(STATE/'request.json',payload)
    try:
        subprocess.run(['systemctl','start','--no-block',UNIT],capture_output=True,text=True,check=True,timeout=15)
    except (OSError,subprocess.TimeoutExpired):intent.update(phase='unknown',do_not_replay=True)
    except subprocess.CalledProcessError:intent.update(phase='failed',reason='systemd_start_rejected')
    else:intent['phase']='submitted'
    db.put('metadata',key,intent)
    return dict(status='pending' if intent['phase']=='submitted' else intent['phase'],original_request_id=request_id)


def run(body):
    from .scheduler import export_shadow_snapshot
    db=ledger();ident=body['simulation_id'];key='simulation:'+ident
    record=db.get('metadata',key)
    if not record:raise ValueError('historical_original_request_missing')
    if record.get('phase') in ('completed','failed'):return record
    if not record.get('historical_input_id'):
        window=record['paid_window']
        period=dict(start=window['start'],end=(datetime.fromisoformat(window['end_exclusive'])-timedelta(days=1)).date().isoformat())
        process=subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.sources'],
            input=json.dumps(dict(action='historical',period=period)),capture_output=True,text=True,timeout=600,cwd='/opt/fc27-cloud-browser')
        if process.returncode:raise ValueError('historical_provider_failed')
        private=json.loads(process.stdout)
        if private['paid_window']!=window:raise ValueError('historical_provider_window_changed')
        coverage=private['historical_orders_coverage']
        private['provider_period_selector']=private['period_selector']
        private['provider_source_sha256']=private['source_sha256']
        private['period_selector']=coverage['period_selector']=record['period_selector']
        coverage['source_sha256']=fingerprint(dict(rows=private['historical_orders'],coverage={k:v for k,v in coverage.items() if k!='source_sha256'}))
        private['source_sha256']=coverage['source_sha256']
        with db.connect() as conn:
            snapshots=[json.loads(r[0]) for r in conn.execute('SELECT body FROM pricing_snapshots')]
        private.update(schema_version='fc-pricing-v3-history-input-v1',snapshot_ids=[s['snapshot_id'] for s in snapshots
            if s.get('origin')=='live_collector' and instant(s['created_at'])<=instant(private['available_at'])])
        input_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-history:'+ident+':'+fingerprint(private)))
        record.update(historical_input_id=input_id,coverage=coverage,phase='input_ready')
        with db.transaction() as conn:
            if db.get('historical_inputs',input_id,conn) is None:db.put('historical_inputs',input_id,private,conn)
            db.put('metadata',key,record,conn)
            event={field:record[field] for field in ('simulation_id','kind','closed_days','requested_at','period_selector','paid_window','historical_input_id')}
            conn.execute('INSERT OR IGNORE INTO event_outbox(event_key,kind,body) VALUES (?,?,?)',('simulation:'+ident,'simulation_requested',json.dumps(event)))
    export_shadow_snapshot(db,force=True)
    dispatched=ensure_shadow(db,'historical',ident)
    record['shadow']=dispatched
    record['phase']='completed' if dispatched['status']=='completed' else dispatched['status']
    db.put('metadata',key,record)
    if dispatched['status']=='pending':raise ValueError('pricing_historical_shadow_pending')
    return record
