"""Audited GET /api/logs/<id> only: memory log subscription, no DB/claim/config API."""
import pathlib,json,re,urllib.request,datetime,hashlib
ROOT=pathlib.Path('/opt/d4follow');out={'readUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tasks':[]}
out['appSHA256']=hashlib.sha256((ROOT/'app.py').read_bytes()).hexdigest()
assert out['appSHA256']=='3f80de209d14d1b077111f97ed44fae2682a4c166d95fd6d0c34dee807cbe280'
p=ROOT/'logs/auto_collect.log'
with p.open('rb') as f:f.seek(max(0,p.stat().st_size-256*1024));s=f.read().decode('utf-8','replace')
ids=list(dict.fromkeys(re.findall(r'"taskId"\s*:\s*"([a-f0-9]{12})"',s)))
out['latestCollectTaskIDs']=ids[-3:]
for tid in ids[-3:]:
 d={'id':tid,'source':'auto_collect.log'}
 try:
  with urllib.request.urlopen('http://127.0.0.1:8900/api/logs/'+tid,timeout=6) as r:
   count=0;flags=[]
   while count<1024*1024:
    line=r.readline();count+=len(line)
    if not line:break
    if not line.startswith(b'data: '):continue
    obj=json.loads(line[6:].decode('utf-8','replace'))
    msg=obj.get('line') or ''
    for name,pattern in [('auto-off',r'自动跟价.*(?:关|停)'),('auto-on',r'自动跟价.*(?:开启|打开)'),('master-off',r'系统总开关.*(?:关|OFF)'),('gold-apply',r'金币.*工单|自动.*金币')]:
     if re.search(pattern,msg):flags.append(name)
    if 'status' in obj:d['status']=obj['status'];break
   d['operationalFlags']=sorted(set(flags));d['historyBytesRead']=count
 except Exception as e:d['errorClass']=type(e).__name__;d['httpStatus']=getattr(e,'code',None)
 out['tasks'].append(d)
out['limit']='Only latest three timer-created IDs; no claim that all application TASKS enumerated.'
print(json.dumps(out,ensure_ascii=True))
