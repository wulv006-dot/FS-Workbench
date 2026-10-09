"""Temporary-root checks. Windows substitutes only POSIX locks/directory fsync."""
import contextlib, hashlib, importlib.util, json, os, tempfile, sqlite3, urllib.error
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('release',Path(__file__).parents[1]/'source'/'release_navigation.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
def sha(data):return hashlib.sha256(data).hexdigest()
def fixture(root,fix=False):
 stage=root/'stage';files=[]
 for i,rel in enumerate(sorted(r.GREEN_FIX_TARGETS if fix else r.RELATIVE)):
  old=None if i==2 and not fix else ('before:'+rel).encode();new=('after:'+rel).encode()
  target=r.rooted(root,r.target_for(rel));target.parent.mkdir(parents=True,exist_ok=True)
  if old is not None:target.write_bytes(old)
  src=stage/'candidate'/rel;src.parent.mkdir(parents=True,exist_ok=True);src.write_bytes(new)
  files.append(dict(candidate=rel,target=r.target_for(rel),beforeSha256=sha(old) if old else None,sha256=sha(new)))
 manifest=dict(schemaVersion=1,releaseReady=True,files=files,unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256=sha(b'protected'))],runtimeRequired={'other.service':{'MainPID':'100'}})
 if fix:
  manifest['scope']=r.GREEN_FIX_SCOPE;manifest['runtimeRequired']={'auth-portal.service':{'ActiveState':'active'}}
  db=r.rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db');db.parent.mkdir(parents=True,exist_ok=True)
  with contextlib.closing(sqlite3.connect(str(db))) as conn:
   conn.execute('CREATE TABLE members(username TEXT)');conn.execute("INSERT INTO members VALUES ('user')");conn.execute('CREATE TABLE green_tasks(progress INTEGER)');conn.execute('INSERT INTO green_tasks VALUES (7)');conn.commit()
 payload=json.dumps(manifest).encode();return stage,manifest,payload,sha(payload)
def applied(root):
 stage,m,p,h=fixture(root)
 with patch.object(r,'guards'),patch.object(r,'retirement'):
  result=r.apply(m,stage,h,p,'nav-20261009T000000Z',root)
 return Path(result['backup']),m,h
def original(root,m):
 assert all(r.digest(r.rooted(root,x['target']))==x['beforeSha256'] for x in m['files'])
def rejected(fn):
 try:fn()
 except ValueError:return
 raise AssertionError('expected fail-closed refusal')
def run():
 count=0
 with contextlib.ExitStack() as platform:
  if os.name!='posix':
   platform.enter_context(patch.object(r,'locks',lambda root:contextlib.nullcontext()))
   platform.enter_context(patch.object(r,'directory_sync'))
  for scenario in ('normal','PID','unrelated','target','backup','approval','journal','interrupted','interrupted-new'):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);backup,m,h=applied(root)
    db=r.rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db');db.parent.mkdir(parents=True,exist_ok=True);db.write_bytes(b'user-progress')
    blocked=scenario in ('target','backup','approval','journal')
    if scenario=='target':r.rooted(root,m['files'][0]['target']).write_bytes(b'third-party')
    if scenario=='backup':(backup/'files'/m['files'][0]['candidate']).write_bytes(b'corrupt')
    if scenario=='approval':h='0'*64
    if scenario=='journal':
     j=json.loads((backup/'journal.json').read_text());j['files'][0]['target']='/unapproved';(backup/'journal.json').write_text(json.dumps(j))
    if scenario=='unrelated':
     other=r.rooted(root,'/var/www/dashboard/index.html');other.parent.mkdir(parents=True,exist_ok=True);other.write_bytes(b'unrelated update')
    before=[r.digest(r.rooted(root,x['target'])) for x in m['files']]
    with patch.object(r,'guards',side_effect=ValueError('PID or unrelated file changed')) as guard,patch.object(r,'retirement',side_effect=ValueError('unrelated retirement state')):
     if blocked:
      rejected(lambda:r.rollback(backup,h,root));assert before==[r.digest(r.rooted(root,x['target'])) for x in m['files']]
     elif scenario in ('interrupted','interrupted-new'):
      atomic=r.atomic;failed=[False]
      def interrupted(path,data,mode=0o644):
       atomic(path,data,mode)
       if path==r.rooted(root,m['files'][-1]['target']) and not failed[0]:failed[0]=True;raise OSError('crash after restore rename')
      def interrupted_journal(backup_path,journal):
       new=r.rooted(root,m['files'][2]['target'])
       if scenario=='interrupted-new' and not new.exists() and not failed[0]:failed[0]=True;raise OSError('crash after new-file unlink')
       journal_write(backup_path,journal)
      journal_write=r.journal_write
      with patch.object(r,'atomic',interrupted if scenario=='interrupted' else atomic),patch.object(r,'journal_write',interrupted_journal):
       try:r.rollback(backup,h,root)
       except OSError:pass
       else:raise AssertionError('injection did not run')
      r.rollback(backup,h,root);original(root,m)
     else:r.rollback(backup,h,root);original(root,m)
     guard.assert_not_called()
    assert db.read_bytes()==b'user-progress';count+=1
  # Fail after one write because an unrelated guard changes; recovery still works.
  for reason in ('PID changed','protected unrelated file changed'):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);stage,m,p,h=fixture(root);calls=[0]
    def changing_guard(*args):
     calls[0]+=1
     if calls[0]>=3:raise ValueError(reason)
    with patch.object(r,'guards',changing_guard),patch.object(r,'retirement'):
     try:r.apply(m,stage,h,p,'nav-20261009T000001Z',root)
     except ValueError as e:assert str(e)==reason
     else:raise AssertionError('release should fail')
    original(root,m)
    j=json.loads((r.rooted(root,'/var/backups/fs-navigation-20261006/nav-20261009T000001Z')/'journal.json').read_text());assert j['status']=='rolled-back';count+=1
  for failure in (False,True):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);stage,m,p,h=fixture(root,True);assert set(x['candidate'] for x in r.validate(m,stage))==set(r.GREEN_FIX_TARGETS)
    broken=json.loads(p);broken['files'][0]['beforeSha256']=None;rejected(lambda:r.validate(broken,stage))
    calls=[0];restarts=[]
    def fix_guard(*args):
     calls[0]+=1
     if failure and calls[0]>=3:raise ValueError('unrelated PID changed')
    with patch.object(r,'guards',fix_guard),patch.object(r,'retirement'),patch.object(r,'restart_for',lambda manifest:restarts.append(manifest['scope'])):
     if failure:
      rejected(lambda:r.apply(m,stage,h,p,'nav-20261009T000002Z',root));assert restarts==[r.GREEN_FIX_SCOPE]
     else:
      result=r.apply(m,stage,h,p,'nav-20261009T000002Z',root);r.rollback(Path(result['backup']),h,root);assert restarts==[r.GREEN_FIX_SCOPE,r.GREEN_FIX_SCOPE]
    original(root,m)
    with contextlib.closing(sqlite3.connect(str(r.rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db')))) as conn:assert conn.execute('SELECT progress FROM green_tasks').fetchone()==(7,)
    count+=1
  # Real restart dispatch remains exactly auth + taskboard, with anonymous 401.
  class Healthy:
   status=200
   def __enter__(self):return self
   def __exit__(self,*args):pass
  def health(url,**kwargs):
   if ':8895/' in url:raise urllib.error.HTTPError(url,401,'Unauthorized',{},None)
   return Healthy()
  with patch.object(r.subprocess,'run') as command,patch.object(r.urllib.request,'urlopen',health):
   r.restart_for({'scope':r.GREEN_FIX_SCOPE})
   assert [c.args[0] for c in command.call_args_list]==[['systemctl','restart','auth-portal.service'],['systemctl','is-active','--quiet','auth-portal.service'],['systemctl','restart','mmoexp-taskboard.service'],['systemctl','is-active','--quiet','mmoexp-taskboard.service']]
   count+=1
 print('PASS',count,'rollback scenarios; POSIX locks/directory fsync '+('real' if os.name=='posix' else 'substituted; Linux check required'))
if __name__=='__main__':run()
