"""Only synthetic temporary filesystem roots; systemctl responses are mocked."""
from pathlib import Path
import contextlib,hashlib,json,os,tempfile,unittest,time
from unittest.mock import patch
import release_profit_backend as R

@contextlib.contextmanager
def windows_locks(root):
 key=str(root)
 if key in windows_locks.held:raise BlockingIOError('fixture lock conflict')
 windows_locks.held.add(key)
 try:yield
 finally:windows_locks.held.remove(key)
windows_locks.held=set()

class Backend(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'root';self.stage=self.base/'stage';self.stack=contextlib.ExitStack()
  if os.name!='posix':
   self.stack.enter_context(patch.object(R,'locks',windows_locks))
   self.stack.enter_context(patch.object(R,'directory_sync',lambda p:None))
  def systemctl(args,**kwargs):
   assert args[:2]==['systemctl','show']
   unit=args[2]
   if unit=='fs-transaction-collect.service':text='ActiveState=inactive\nTimeoutStartUSec=30min\n'
   elif unit=='fs-transaction-collect.timer':text='ActiveState=active\nNextElapseUSecMonotonic='+str(time.monotonic()+600)+'s\n'
   else:text='UnitFileState=disabled\nActiveState=inactive\n'
   return type('Reply',(),dict(returncode=0,stdout=text,stderr=''))()
  self.systemctl=systemctl;self.stack.enter_context(patch.object(R.subprocess,'run',systemctl))
  protected=[]
  for target in sorted(R.PROTECTED):
   p=R.rooted(self.root,target);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('protected fixture '+target);protected.append(dict(path=target,sha256=R.digest(p)))
  rows=[]
  for name in R.WRITE_ORDER:
   src=self.stage/'candidate'/name;src.parent.mkdir(parents=True,exist_ok=True);src.write_text('candidate fixture '+name)
   dst=R.rooted(self.root,R.TARGETS[name]);dst.parent.mkdir(parents=True,exist_ok=True)
   dst.write_text('previous fixture '+name)
   rows.append(dict(candidate=name,target=R.TARGETS[name],sha256=R.digest(src),beforeSha256=R.digest(dst),afterMode=R.AFTER_MODES[name]))
  ledger=R.rooted(self.root,'/var/lib/fs-dashboard-release/current.json');ledger.parent.mkdir(parents=True,exist_ok=True);ledger.write_text(json.dumps(dict(releaseId='fixture-v4',version=100)))
  lock=R.rooted(self.root,'/var/www/dashboard/fs-home/transactions/collector.lock');lock.parent.mkdir(parents=True,exist_ok=True);lock.write_bytes(b'')
  if os.name=='posix':
   units=R.rooted(self.root,'/etc/systemd/system');units.mkdir(parents=True,exist_ok=True)
   for unit in ['dashboard-pipeline.service','dashboard-publish.service','dashboard-fallback.service']:(units/unit).symlink_to('/dev/null')
  else:self.stack.enter_context(patch.object(R,'retirement',lambda root:R.collector_idle()))
  self.m=dict(schemaVersion=1,releaseReady=True,files=rows,unchangedRequired=protected,expectedBusinessReleaseId='fixture-v4',expectedBusinessVersion=100)
  self.body=json.dumps(self.m).encode();self.approved=hashlib.sha256(self.body).hexdigest();self.before=self.hashes()
 def tearDown(self):self.stack.close();self.temp.cleanup()
 def hashes(self):return {r['target']:R.digest(R.rooted(self.root,r['target'])) for r in self.m['files']}
 def apply(self):return R.apply(self.m,self.stage,self.approved,self.body,'profit-backend-20261006T000001Z',self.root)
 def reject(self,action):
  before=self.hashes()
  with self.assertRaises((ValueError,OSError,RuntimeError)):action()
  self.assertEqual(self.hashes(),before)
 def test_inspection_zero_mutations(self):
  self.assertFalse(R.inspect(self.m,self.stage,self.root)['mutations']);self.assertEqual(self.hashes(),self.before)
 def test_happy_two_existing_and_exact_rollback(self):
  seen=[];actual=R.atomic
  def record(path,payload,mode=0o644):
   if str(path) in {str(R.rooted(self.root,p)) for p in self.before}:seen.append(path.name)
   return actual(path,payload,mode)
  with patch.object(R,'atomic',record):report=self.apply()
  self.assertEqual(seen,R.WRITE_ORDER);backup=Path(report['backup'])
  self.assertEqual(self.hashes(),{r['target']:r['sha256'] for r in self.m['files']})
  if os.name=='posix':self.assertEqual(R.rooted(self.root,R.TARGETS['profit_backfill.py']).stat().st_mode&0o777,0o644)
  R.rollback(backup,self.approved,self.root);self.assertEqual(self.hashes(),self.before)
  R.rollback(backup,self.approved,self.root);self.assertEqual(self.hashes(),self.before)
 def test_false_readiness(self):
  self.m['releaseReady']=False;self.reject(self.apply)
 def test_wrong_manifest_approval(self):
  self.approved='0'*64;self.reject(self.apply)
 def test_wrong_target_and_permissions(self):
  self.m['files'][0]['target']='/etc/auth.json';self.reject(self.apply)
  self.m['files'][0]['target']=R.TARGETS[self.m['files'][0]['candidate']];self.m['files'][0]['afterMode']=0o777;self.reject(self.apply)
 def test_existing_new_helper_peer_refused(self):
  R.rooted(self.root,R.TARGETS['profit_backfill.py']).write_text('peer');self.reject(self.apply)
 def test_protected_fc_client_drift_refused(self):
  R.rooted(self.root,'/var/www/dashboard/fs-home/transactions/exact-range-client.js').write_text('peer');self.reject(self.apply)
 def test_pending_gateway_refused(self):
  R.rooted(self.root,'/var/lib/fs-dashboard-release/pending.json').write_text('{}');self.reject(self.apply)
 def test_pending_native_ui_refused(self):
  p=R.rooted(self.root,'/var/backups/fs-navigation-native-20261006/pending.json');p.parent.mkdir(parents=True);p.write_text('{}');self.reject(self.apply)
 def test_new_native_business_js_and_html_drift_refused(self):
  for suffix in ('business.js','business.html'):
   p=R.rooted(self.root,'/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/'+suffix);original=p.read_bytes();p.write_text('peer native');self.reject(self.apply);p.write_bytes(original)
 def test_second_new_helper_existing_or_extra_target_refused(self):
  p=R.rooted(self.root,R.TARGETS['profit_daily_reader.py']);p.write_text('peer');self.reject(self.apply);p.unlink()
  self.m['files'].append(dict(self.m['files'][0],candidate='unapproved.py'));self.reject(self.apply)
 def test_ledger_newer_version_refused(self):
  R.rooted(self.root,'/var/lib/fs-dashboard-release/current.json').write_text(json.dumps(dict(releaseId='peer',version=101)));self.reject(self.apply)
 def test_active_collector_and_natural_deadline_refused(self):
  for text in ['ActiveState=active\nTimeoutStartUSec=30min\n','ActiveState=inactive\nTimeoutStartUSec=40min\n']:
   with patch.object(R.subprocess,'run',lambda *a,**k:type('Reply',(),dict(returncode=0,stdout=text,stderr=''))()):self.reject(self.apply)
  original=self.systemctl
  def near(args,**kwargs):
   if args[2]=='fs-transaction-collect.timer':return type('Reply',(),dict(returncode=0,stdout='ActiveState=active\nNextElapseUSecMonotonic='+str(time.monotonic()+20)+'s\n',stderr=''))()
   return original(args,**kwargs)
  with patch.object(R.subprocess,'run',near):self.reject(self.apply)
 def test_rename_failure_after_atomic_restores_two_existing(self):
  actual=R.atomic;fired=[False]
  def fault(path,data,mode=0o644):
   actual(path,data,mode)
   if path==R.rooted(self.root,R.TARGETS['profit_daily_reader.py']) and not fired[0]:fired[0]=True;raise OSError('fixture after rename')
  with patch.object(R,'atomic',fault):self.reject(self.apply)
  self.assertEqual(self.hashes(),self.before)
 def test_rollback_drift_never_clobbers_peer(self):
  backup=Path(self.apply()['backup']);R.rooted(self.root,R.TARGETS['profit_daily_reader.py']).write_text('peer');self.reject(lambda:R.rollback(backup,self.approved,self.root))
 def test_rollback_backup_corruption_refused(self):
  backup=Path(self.apply()['backup']);(backup/'files/profit_daily_reader.py').write_text('bad backup');self.reject(lambda:R.rollback(backup,self.approved,self.root))
 def test_shared_lock_conflict_refused(self):
  with R.locks(self.root):self.reject(self.apply)
 def test_collector_lock_conflict_refused(self):
  if os.name!='posix':self.skipTest('Real separate collector flock requires POSIX')
  import fcntl
  with R.rooted(self.root,'/var/www/dashboard/fs-home/transactions/collector.lock').open('a+b') as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);self.reject(self.apply)
 def test_weeks_timer_parser_is_preserved_and_unknown_refused(self):
  self.assertEqual(R.monotonic_schedule_seconds('1w 1d 2h 3min 4.5s'),698584.5)
  with self.assertRaises(RuntimeError):R.monotonic_schedule_seconds('unknown 3s')

 @unittest.skipUnless(os.name=='posix','POSIX directory alias test')
 def test_standard_var_lock_alias_same_inode_and_publish(self):
  canonical=R.rooted(self.root,'/run/lock');canonical.mkdir(parents=True)
  alias=R.rooted(self.root,'/var/lock');alias.parent.mkdir(parents=True,exist_ok=True);alias.symlink_to('../run/lock',target_is_directory=True)
  shared=canonical/'fs-dashboard-release.lock';shared.write_bytes(b'')
  inode=shared.stat().st_ino
  report=self.apply();self.assertEqual(shared.stat().st_ino,inode)
  R.rollback(Path(report['backup']),self.approved,self.root);self.assertEqual(self.hashes(),self.before)
 @unittest.skipUnless(os.name=='posix','POSIX directory alias test')
 def test_unexpected_lock_alias_refuses_before_writes(self):
  other=R.rooted(self.root,'/run/unreviewed');other.mkdir(parents=True)
  R.rooted(self.root,'/run/lock').mkdir(parents=True)
  alias=R.rooted(self.root,'/var/lock');alias.parent.mkdir(parents=True,exist_ok=True);alias.symlink_to('../run/unreviewed',target_is_directory=True)
  self.reject(self.apply)

 def test_null_baseline_refused_before_writes(self):
  self.m['files'][0]['beforeSha256']=None;self.reject(self.apply)
 def test_missing_existing_target_refused_before_writes(self):
  R.rooted(self.root,R.TARGETS['profit_backfill.py']).unlink();self.reject(self.apply)

if __name__=='__main__':unittest.main()
