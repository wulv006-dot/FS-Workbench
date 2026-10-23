"""Observe completed FC cycles in a separate store. No pricing or model calls."""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

APP=Path('/opt/fc27-price-observer')
STATE=Path('/var/lib/fc27-price-observer')
FC=Path('/var/lib/fc27-cloud')

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def latest_completed():
    candidates=[]
    for path in sorted((p for p in (FC/'jobs').glob('*.json') if not p.name.startswith('.')),key=lambda p:p.stat().st_mtime,reverse=True)[:30]:
        job=read(path)
        if job.get('kind') in ('auto_cycle','collect') and job.get('status')=='ready':
            candidates.append(job)
    return max(candidates,key=lambda job:job.get('created_at') or '') if candidates else None

def business_job_pending():
    return any(read(path).get('status') in ('queued','running') for path in (FC/'jobs').glob('*.json') if not path.name.startswith('.'))

def run_coalesced():
    # Keep the original path-triggered process alive across progress writes; no business locks while waiting.
    deadline=time.monotonic()+300
    while True:
        if not business_job_pending():
            try:
                return main()
            except BlockingIOError:
                pass
        if time.monotonic()>=deadline:
            raise BlockingIOError('observer_wait_budget_exhausted')
        time.sleep(2)

def comparable_cohort(rows):
    stamps=[datetime.fromisoformat(r['captured_at'].replace('Z','+00:00')) for r in rows if r.get('status')=='valid']
    return bool(stamps) and all(t.tzinfo for t in stamps) and (max(stamps)-min(stamps)).total_seconds()<=300

def public_read():
    code=(APP/'itemd2r.py').read_text()+r'''
import signal
def terminate(signum,frame):raise TimeoutError('observer_read_budget')
signal.signal(signal.SIGTERM,terminate)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.connect_over_cdp('http://127.0.0.1:9225',timeout=8000,no_defaults=True)
 if len(b.contexts)!=1:raise ValueError('observer_context_ambiguous')
 print(json.dumps({'source':'ItemD2R','status':'valid','offers':collect(b.contexts[0])}))
'''
    result=subprocess.run(['docker','exec','-i','-u','fc27chrome','fc27-cloud-browser','timeout','--signal=TERM','--kill-after=5s','50s','python3','-'],input=code,text=True,capture_output=True,timeout=60)
    if result.returncode:
        raise ValueError('itemd2r_public_read_failed')
    payload=json.loads(result.stdout)
    if payload.get('source')!='ItemD2R' or payload.get('status')!='valid' or [r.get('platform') for r in payload.get('offers',[])]!=['PS','XBOX','PC']:
        raise ValueError('itemd2r_platform_coverage_invalid')
    return payload['offers']

def main():
    import fcntl
    sys.path.insert(0,'/opt/fc27-cloud-browser')
    import automation_tick as tick
    import fc27_cloud_api as api
    from snapshot_layer import atomic_json
    from reference_shadow import experimental_scenarios
    STATE.mkdir(mode=0o700,exist_ok=True)
    (STATE/'samples').mkdir(mode=0o700,exist_ok=True)
    with ExitStack() as held:
        lock=held.enter_context((STATE/'lock').open('a+b'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        job=latest_completed()
        if job is None:return {'status':'no_completed_cycle'}
        jid=str(job['job_id'])
        import uuid
        if str(uuid.UUID(jid))!=jid:raise ValueError('observer_job_identity_invalid')
        sample=STATE/'samples'/(jid+'.json')
        if sample.exists():return {'status':'already_observed','run_id':jid,'sample_status':read(sample).get('status')}
        snapshot_path=FC/'runs'/(jid+'.json')
        snapshot=read(snapshot_path)
        if snapshot.get('run_id')!=jid or snapshot.get('status')!='ready_for_quote':return {'status':'snapshot_not_ready','run_id':jid}
        created=datetime.fromisoformat(snapshot['created_at'].replace('Z','+00:00'))
        now=datetime.now(timezone.utc)
        if created.tzinfo is None or not 0<=(now-created).total_seconds()<=3600:return {'status':'completed_cycle_stale','run_id':jid}
        held.enter_context(tick.queue_mutation())
        for name in tick.RETRY_LOCKS:
            handle=held.enter_context((tick.ROOT/'state'/name).open('rb'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (tick.retry_guard()!='ready' or list((FC/'queue').glob('*.json')) or api.health()['incomplete_executions']
                or any(read(p).get('status') in ('queued','running') for p in (FC/'jobs').glob('*.json'))):
            raise BlockingIOError('business_cycle_busy')
        before=hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        record=dict(run_id=jid,status='fetching',started_at=now.isoformat(),original_snapshot_sha256=before,
                    production_rule_changed=False,price_write_performed=False,model_requests=0,
                    source_policy='Lootbar core; U7Buy and ItemD2R tier2; IGGM and U4GM tier3; shadow only')
        with sample.open('x',encoding='utf-8') as stream:json.dump(record,stream)
        try:
            rows=public_read()
            combined=snapshot['competitors']+[{**r,'run_id':jid} for r in rows]
            now=datetime.now(timezone.utc)
            simulation=(experimental_scenarios(combined,now=now,storefront=snapshot.get('storefront'))
                        if comparable_cohort(combined) else {'status':'not_comparable_capture_span','reason':'source_capture_span_over_300_seconds','scenarios':[]})
            record.update(status='observed',itemd2r=rows,original_competitors=snapshot['competitors'],
                costs=[{k:r.get(k) for k in ('platform','record_id','trade_at','checked_at','cny_per_1k','status')} for r in snapshot.get('costs',[])],
                fx={k:snapshot.get('fx',{}).get(k) for k in ('status','checked_at','cny_per_usd')},
                storefront=snapshot.get('storefront'),simulation=simulation)
        except Exception as exc:
            record.update(status='failed',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        record.update(completed_at=datetime.now(timezone.utc).isoformat(),
                      original_snapshot_unchanged=hashlib.sha256(snapshot_path.read_bytes()).hexdigest()==before)
        atomic_json(sample,record)
        atomic_json(STATE/'latest.json',record)
        return {k:record[k] for k in ('run_id','status','original_snapshot_unchanged','price_write_performed','model_requests')}

def cli():
    code=0
    try:print(json.dumps(run_coalesced()))
    except BlockingIOError:
        print(json.dumps({'status':'deferred_business_busy','price_write_performed':False}));code=75
    finally:
        try:
            sys.path.insert(0,'/opt/fc27-cloud-browser')
            from reference_observer_view import publish_view
            publish_view()
        except Exception as error:
            print(json.dumps({'status':'view_export_failed','error':type(error).__name__,
                              'sample_state_unchanged':True}),file=sys.stderr)
            code=2  # Existing RestartPreventExitStatus prevents blind fetch retries after export failure.
    return code

if __name__=='__main__':
    sys.exit(cli())
