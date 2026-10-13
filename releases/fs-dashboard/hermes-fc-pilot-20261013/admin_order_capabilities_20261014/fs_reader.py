"""FS-only source clients; the model supplies only checked capability arguments."""
from pathlib import Path
import json,subprocess
from urllib.request import Request,build_opener,HTTPRedirectHandler
from .capabilities import checked_query,result

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def admin_read(args):
    raw=json.dumps(args,separators=(',',':')).encode()
    if len(raw)>4096:raise ValueError('capability_body')
    req=Request('http://127.0.0.1:8767/business/fc-capability',data=raw,headers={'Content-Type':'application/json'},method='POST')
    with build_opener(NoRedirect).open(req,timeout=60) as response:data=response.read(1000001)
    if len(data)>1000000:raise ValueError('projected_response_size')
    return json.loads(data)

def order_read(q,config,web,source_root=Path('/opt/fs-exact-range-20261001'),timeout=120):
    import fcntl
    # Recheck closed arguments at the trusted boundary, never pass endpoints/code.
    args={k:v for k,v in q.items() if k in ('kind','profile','platform','pages','samples')}
    checked=checked_query(args,config)
    if not config.get('enabled'):return {'contract':'fc-order-events-raw-v1','status':'not_available','reason':'source_unavailable'}
    with (Path(web)/'collector.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'contract':'fc-order-events-raw-v1','status':'not_sent','reason':'collector_busy'}
        diagnostics=(source_root/'fc_order_diagnostics.py').read_text('utf-8')
        reader=(source_root/'fc_order_reader.py').read_text('utf-8')
        projection=Path(__file__).with_name('order_detail_projection.py').read_text('utf-8')
        program=('import sys,types,json\n'
                 'm=types.ModuleType("fc_order_diagnostics");exec(%r,m.__dict__);sys.modules[m.__name__]=m\n'
                 'p=types.ModuleType("fc_capability_projection");exec(%r,p.__dict__)\n'
                 'r=types.ModuleType("fc_capability_reader");exec(%r,r.__dict__)\n'
                 'print(json.dumps(r.run(%r,p.read_open_detail),ensure_ascii=True,allow_nan=False))\n')%(diagnostics,projection,reader,{k:checked[k] for k in ('platform','pages','samples')})
        try:
            proc=subprocess.run(['docker','exec','-i','fc27-cloud-browser','python3','-'],input=program.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            if proc.returncode or len(proc.stdout)>1000000:raise ValueError('order_reader_failed')
            value=json.loads(proc.stdout)
            if value.get('contract')!='fc-order-events-raw-v1':raise ValueError('order_reader_contract')
            return value
        except (ValueError,OSError,subprocess.TimeoutExpired):
            return {'contract':'fc-order-events-raw-v1','status':'not_available','reason':'source_unavailable'}
