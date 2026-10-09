"""Loopback-only, single-worker date-range reads; nginx authenticates callers."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit,parse_qs
import json,subprocess,sys,time,urllib.request,urllib.parse
from custom_range import validate
POOL=ThreadPoolExecutor(max_workers=1);LOCK=RLock();JOBS={};BUSY=None
def run(start,end):
 try:
  value=subprocess.run([sys.executable,str(Path(__file__).with_name('custom_range.py')),start,end],capture_output=True,timeout=600)
  if value.returncode:raise ValueError('query_failed')
  result=json.loads(value.stdout)
  if result.get('schemaVersion')!=1 or result.get('start')!=start or result.get('end')!=end:raise ValueError('invalid_query_response')
  return result
 except (OSError,ValueError,subprocess.TimeoutExpired):return {'schemaVersion':1,'status':'unavailable','start':start,'end':end,'reason':'来源查询未成功或超过查询时间，未填零。'}
def run_links(start,end):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8767/marketing/summary?'+urllib.parse.urlencode({'start':start,'end':end}),timeout=75) as response:return json.load(response)
 except (OSError,ValueError):return {'status':'unavailable','start':start,'end':end}

def query(start,end,submit=POOL.submit,kind='range'):
 global BUSY
 validate(start,end);key=(kind,start,end)
 with LOCK:
  now=time.monotonic()
  for old,record in list(JOBS.items()):
   if record['future'].done():
    record.setdefault('completed',now)
    if now-record['completed']>300:del JOBS[old]
  if key not in JOBS:
   if BUSY is not None and not BUSY.done():return 429,{'status':'busy','reason':'已有一个区间查询正在运行，请稍后再试。'}
   future=submit(run_links if kind=='links' else run,start,end);JOBS[key]={'future':future,'created':now};BUSY=future
  future=JOBS[key]['future']
  return (200,future.result()) if future.done() else (202,{'status':'pending','start':start,'end':end})
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  p=urlsplit(self.path)
  if p.path not in ('/range','/links'):self.send_error(404);return
  if not self.headers.get('X-Auth-User'):self.send_error(401);return
  try:
   params=parse_qs(p.query,keep_blank_values=True)
   if set(params)!={'start','end'} or any(len(v)!=1 for v in params.values()):raise ValueError('invalid_parameters')
   code,result=query(params['start'][0],params['end'][0],kind=p.path[1:])
  except (ValueError,TypeError):code,result=400,{'status':'invalid','reason':'请输入有效起止日期，起始不晚于结束，范围不超过366天。'}
  raw=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
  self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,*args):pass
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8935),Handler).serve_forever()
