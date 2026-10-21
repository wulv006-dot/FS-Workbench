"""One complete request through the deployed 8767 HTTP entry, retaining only aggregates."""
from datetime import date, datetime
import json, re, threading, time, urllib.request
from pathlib import Path

OP='fs-admin-monthly-paid-20261021-v1'
ROOT=Path('/var/backups')/OP
QUERY={'profile':'FC27','start':'2026-09-17','end':'2026-10-20'}
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def local(path):
    with opener.open('http://127.0.0.1:8767'+path,timeout=8) as r:return json.load(r)

def main():
    target=ROOT/'live-verification.json'
    assert not target.exists(), 'existing verification requires readback'
    receipt=json.loads((ROOT/'receipt.json').read_text())
    assert receipt['state']=='DEPLOYED_READY'
    before,session=local('/health'),local('/session/admin-token')
    assert before['ready'] and session['ready']
    token=session['token'];stop=threading.Event();samples=[]
    def monitor():
        while not stop.is_set():
            try:
                started=time.monotonic();h=local('/health');s=local('/session/admin-token')
                samples.append({'ready':h.get('ready') and s.get('ready'),
                    'same_token':s.get('token')==token,'active':h.get('active_model_reads',0),
                    'seconds':round(time.monotonic()-started,4)})
            except Exception as e:samples.append({'ready':False,'same_token':False,'error_type':type(e).__name__})
            stop.wait(1)
    thread=threading.Thread(target=monitor,daemon=True);thread.start();started=time.monotonic()
    result={'operation':OP,'entry':'http://127.0.0.1:8767/business/fc-capability','query':QUERY,'complete':False}
    try:
        request=urllib.request.Request(result['entry'],data=json.dumps(dict(QUERY,kind='cohort_paid_orders')).encode(),headers={'Content-Type':'application/json'},method='POST')
        with opener.open(request,timeout=900) as response:
            raw=response.read(16*1024*1024+1)
            assert len(raw)<=16*1024*1024,'response_size'
            assert int(response.headers['Content-Length'])==len(raw),'response_truncated'
            result.update(http_status=response.status,response_bytes=len(raw),content_length_verified=True)
        value=json.loads(raw);c=value['coverage'];rows=value['orders']
        assert value['query']==QUERY and value['kind']=='cohort_paid_orders'
        assert value['status']=='available' and c['paid_complete'] is True
        assert c['period']=={'start':'2026-09-17 00:00','end':'2026-10-21 00:00'}
        assert c['source_total']==c['received']==len(rows)
        assert c['source_scanned_total']==c['source_scanned_received']==len(rows)+c['excluded_refunded']
        assert c['missing_days']==[] and c['missing_payment_time']==0
        ids=set()
        for row in rows:
            assert row['id_is_hashed'] is True and re.fullmatch('[a-f0-9]{64}',row['id'])
            assert row['id'] not in ids;ids.add(row['id'])
            assert row['customer_key'] is None or re.fullmatch('[a-f0-9]{24}',row['customer_key'])
            paid=datetime.fromisoformat(row['paid_at'])
            assert paid.utcoffset().total_seconds()==28800
            assert QUERY['start']<=paid.date().isoformat()<=QUERY['end']
        pages=c['pages'];assert [p['page'] for p in pages]==list(range(1,len(pages)+1))
        for segment in c['segments']:
            selected=[p for p in pages if p['segment_start']==segment['start'] and p['segment_end']==segment['end']]
            assert segment['paid_complete'] is True
            assert [p['source_page'] for p in selected]==list(range(1,len(selected)+1))
            assert sum(p['rows'] for p in selected)==segment['source_scanned_total']
            assert all(p['total']==segment['source_scanned_total'] for p in selected)
        assert sum(s['received'] for s in c['segments'])==len(rows)
        result.update(complete=True,status=value['status'],paid_complete=True,received=len(rows),source_total=c['source_total'],
            source_scanned_total=c['source_scanned_total'],source_scanned_received=c['source_scanned_received'],
            excluded_refunded=c['excluded_refunded'],pages=len(pages),segments=c['segments'],period=c['period'],
            unique_ids_verified=True,all_paid_timestamps_in_range=True,snapshot_id=value['snapshot_id'])
    except Exception as error:
        result.update(error_type=type(error).__name__,error=str(error) if re.fullmatch('[A-Za-z0-9_ ]{0,100}',str(error)) else 'detail_redacted')
        raise
    finally:
        stop.set();thread.join(10);after,current=local('/health'),local('/session/admin-token')
        result.update(seconds=round(time.monotonic()-started,3),concurrent_samples=len(samples),
            concurrent_all_ready=bool(samples) and all(s['ready'] for s in samples),
            concurrent_same_token=bool(samples) and all(s['same_token'] for s in samples),
            max_health_and_token_seconds=max((s.get('seconds',0) for s in samples),default=None),
            active_model_read_observed=any(s.get('active',0)>0 for s in samples),
            same_access_token=current.get('token')==token,login_attempts_before=before['login_attempts'],login_attempts_after=after['login_attempts'])
        target.write_text(json.dumps(result,indent=2));target.chmod(0o600)
        print(json.dumps(result),flush=True)
    assert result['concurrent_all_ready'] and result['concurrent_same_token'] and result['same_access_token']
    assert result['login_attempts_before']==result['login_attempts_after']

if __name__=='__main__':main()
