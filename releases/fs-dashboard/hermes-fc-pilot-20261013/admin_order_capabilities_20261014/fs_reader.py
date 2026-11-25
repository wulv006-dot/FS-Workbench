"""FS-only source clients; the model supplies only checked capability arguments."""
from pathlib import Path
import json,subprocess,sys
from .capabilities import checked_query,result,collect_admin

def admin_read(args):
    raw=json.dumps(args,separators=(',',':')).encode()
    if len(raw)>4096:raise ValueError('capability_body')
    sys.path.insert(0,'/opt/sales-dashboard/collector')
    from p2pah_auth import Session
    client=Session()
    def request(path,body):
        status,value=client.get_admin(path) if body is None else client.post_admin(path,payload=body)
        return status,json.dumps(value).encode('utf-8')
    try:value=collect_admin(request,args,{'enabled':True,'game_id':1327,'main_site_id':266})
    finally:client.close()
    if len(json.dumps(value).encode())>1000000:raise ValueError('projected_response_size')
    return value

def order_read(q,config,web,source_root=Path('/opt/fs-exact-range-20261001'),timeout=120):
    import fcntl
    # Recheck closed arguments at the trusted boundary, never pass endpoints/code.
    args={k:v for k,v in q.items() if k in ('kind','profile','platform','pages','samples')}
    checked=checked_query(args,config)
    if not config.get('enabled'):return {'contract':'fc-order-events-raw-v1','status':'not_available','reason':'source_unavailable'}
    with (Path(web)/'collector.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'contract':'fc-order-events-raw-v1','status':'not_sent','reason':'collector_busy'}
        reader=source_root/'fc_order_reader.py'
        payload=json.dumps({k:checked[k] for k in ('platform','pages','samples')})
        try:
            proc=subprocess.run([sys.executable,'-B',str(reader),payload],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            if proc.returncode or len(proc.stdout)>1000000:raise ValueError('order_reader_failed')
            value=json.loads(proc.stdout)
            if value.get('contract')!='fc-order-events-raw-v1':raise ValueError('order_reader_contract')
            return value
        except (ValueError,OSError,subprocess.TimeoutExpired):
            return {'contract':'fc-order-events-raw-v1','status':'not_available','reason':'source_unavailable'}
