"""Run: python green_plan_20261009/deploy/check_release.py (temporary roots only)."""
import hashlib,json,tempfile,sqlite3,contextlib,os
from pathlib import Path
from unittest.mock import patch
import release_navigation as r
h=lambda b:hashlib.sha256(b).hexdigest()
def run(fail=False):
 with tempfile.TemporaryDirectory() as folder:
  root=Path(folder)/'root';stage=Path(folder)/'stage';rows=[]
  for key,target in r.GREEN_TARGETS.items():
   src=stage/'candidate'/key;src.parent.mkdir(parents=True,exist_ok=True);src.write_bytes(b'new')
   dst=r.rooted(root,target);before=None
   if key in ('backend/taskboard_server.py','fs-home/navigation.json'):
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b'old');before=h(b'old')
   rows.append(dict(candidate=key,target=target,sha256=h(b'new'),beforeSha256=before))
  protected=r.rooted(root,'/var/www/dashboard/index.html');protected.parent.mkdir(parents=True,exist_ok=True);protected.write_bytes(b'protected')
  db=r.rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db');db.parent.mkdir(parents=True,exist_ok=True)
  with contextlib.closing(sqlite3.connect(str(db))) as c:c.execute('CREATE TABLE members(username TEXT,role TEXT)');c.execute("INSERT INTO members VALUES('test','viewer')");c.execute('CREATE TABLE tasks(id INTEGER)');c.execute('INSERT INTO tasks VALUES(1)');c.commit()
  manifest=dict(schemaVersion=1,scope='green-plan-20261009',releaseReady=True,files=rows,unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256=h(b'protected'))]);raw=json.dumps(manifest).encode()
  bad=json.loads(raw);bad['files'][0]['beforeSha256']=None
  try:r.validate(bad,stage)
  except ValueError:pass
  else:raise AssertionError('missing existing consumer baseline accepted')
  oldatomic=r.atomic;tripped=[False]
  def atomic(path,data,mode=0o644):
   if fail and path.name=='green_plan.py' and not tripped[0]:tripped[0]=True;raise OSError('simulated replacement failure')
   return oldatomic(path,data,mode)
  with (patch.object(r,'directory_sync') if os.name!='posix' else contextlib.nullcontext()), (patch.object(r,'locks',lambda root:contextlib.nullcontext()) if os.name!='posix' else contextlib.nullcontext()), patch.object(r,'retirement'),patch.object(r,'restart_taskboard'),patch.object(r,'atomic',atomic):
   try:result=r.apply(manifest,stage,h(raw),raw,'nav-20261009T010101Z',root)
   except OSError:assert fail
   else:
    assert not fail
    r.rollback(Path(result['backup']),h(raw),root)
  for row in rows:assert r.digest(r.rooted(root,row['target']))==row['beforeSha256'],row['candidate']
  assert r.db_state(root)['counts']=={'members':1,'tasks':1}
  assert protected.read_bytes()==b'protected'
run();run(True)
print('PASS: exact targets, private SQLite backup, apply/code rollback, failure rollback, original database preserved')
