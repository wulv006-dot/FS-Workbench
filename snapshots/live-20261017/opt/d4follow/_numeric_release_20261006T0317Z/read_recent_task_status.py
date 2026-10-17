"""Reviewed GET SSE only, broaden timer IDs to retained recent task logs.
No state API, business imports, config/DB content reads or log content output.
Source register keeps MAX_TASKS40; spawn refuses concurrent running tasks.
"""
import pathlib,hashlib,json,urllib.request,re,datetime,ast,time
r=pathlib.Path('/opt/d4follow');h=hashlib.sha256((r/'app.py').read_bytes()).hexdigest()
assert h in ['3f80de209d14d1b077111f97ed44fae2682a4c166d95fd6d0c34dee807cbe280','655503d5b352e22d26cf256c978c88c330f13c0c4570138b8ad5b57a26923bb7']
files=sorted(r.joinpath('logs').glob('task_*.log'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:80]
tree=ast.parse((r/'app.py').read_text())
spawn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='spawn')
wrapper=next(n for n in spawn.body if isinstance(n,ast.FunctionDef) and n.name=='wrapper')
tr=next(n for n in wrapper.body if isinstance(n,ast.Try))
assert isinstance(tr.body[-1],ast.Expr) and isinstance(tr.body[-1].value,ast.Call) and tr.body[-1].value.func.attr=='finish' and tr.body[-1].value.args[0].value=='done'
msg=tr.body[-2].value.args[0];assert isinstance(msg,ast.BinOp) and isinstance(msg.left,ast.Constant)
prefix=msg.left.value.split('%')[0]
out={'UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tasks':[],'runningOrUnconfirmed':[],'limit':'Latest80 log IDs; reviewed wrapper terminal marker older than15seconds or SSE status; no state/config API and no atomic memory enumeration. Unknowns block release.'}
api_reads=0
for p in files:
 m=re.fullmatch(r'task_([a-f0-9]{12})\.log',p.name)
 if not m:continue
 tid=m.group(1);s={'id':tid}
 with p.open('rb') as f:
  f.seek(max(0,p.stat().st_size-8192));tail=f.read().decode('utf-8','replace')
 age=time.time()-p.stat().st_mtime
 last=next((line for line in reversed(tail.splitlines()) if line.strip()),'')
 if prefix in last and age>15:
  s.update(status='done',basis='reviewed-wrapper-final-success-marker',logAgeSec=round(age,1));out['tasks'].append(s);continue
 if api_reads>=5:
  s['errorClass']='bounded-api-budget-unconfirmed';out['runningOrUnconfirmed'].append(s);out['tasks'].append(s);continue
 api_reads+=1
 try:
  with urllib.request.urlopen('http://127.0.0.1:8900/api/logs/'+tid,timeout=5) as resp:
   count=0
   while count<4*1024*1024:
    line=resp.readline();count+=len(line)
    if not line:break
    if line.startswith(b'data: '):
     obj=json.loads(line[6:])
     if 'status' in obj:s['status']=obj['status'];break
   if s.get('status') not in ['done','error']:out['runningOrUnconfirmed'].append(s)
 except urllib.error.HTTPError as ex:
  if ex.code==404:s['status']='expired'
  else:s['errorClass']='HTTPError';s['httpStatus']=ex.code;out['runningOrUnconfirmed'].append(s)
 except Exception as ex:s['errorClass']=type(ex).__name__;out['runningOrUnconfirmed'].append(s)
 out['tasks'].append(s)
print(json.dumps(out,ensure_ascii=True))
