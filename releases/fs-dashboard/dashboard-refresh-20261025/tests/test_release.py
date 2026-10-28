import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('actual_release',R/'deploy/actual_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class Release(unittest.TestCase):
 def test_filter_release_covers_shared_summary_and_exact_new_assets(self):
  spec=importlib.util.spec_from_file_location('filter_release',R/'deploy/filter_release.py');wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
  actual=types.SimpleNamespace(load_base=lambda:'original-publisher')
  with patch.dict(sys.modules,{'actual_release':actual}):self.assertEqual(wrapper.load_base(),'original-publisher')
  self.assertEqual(actual.SCOPE,'business-filter-layout-20261025');self.assertEqual(len(actual.TARGETS),11)
  self.assertEqual(actual.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js','site_summary.py')))
  for n in ('live_summary.py','daily_archive.py','summary_bridge.py','site_summary.py'):self.assertEqual(actual.TARGETS['source/'+n],'/opt/fs-exact-range-20261001/'+n)
  self.assertFalse(any('units/' in n or 'auth' in n for n in actual.TARGETS))
 def test_rs_followup_is_exact_existing_backend_and_versioned_ui(self):
  spec=importlib.util.spec_from_file_location('backlog_release',R/'deploy/backlog_release.py');wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
  actual=types.SimpleNamespace(load_base=lambda:'original-publisher')
  with patch.dict(sys.modules,{'actual_release':actual}):self.assertEqual(wrapper.load_base(),'original-publisher')
  self.assertEqual(actual.TARGETS['source/rs_backlog.py'],'/opt/fs-exact-range-20261001/rs_backlog.py');self.assertEqual(len(actual.TARGETS),6);self.assertEqual(actual.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js')));self.assertEqual(actual.SCOPE,'business-dashboard-backlog-20261025')
 def test_exact_scope_and_targets(self):
  self.assertEqual(release.SCOPE,'business-dashboard-refresh-20261025');self.assertEqual(len(release.TARGETS),11)
  self.assertEqual(release.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js','rs_backlog.py')))
  self.assertEqual(release.TARGETS['source/channel_effects.py'],'/opt/fs-hermes-fc/channel_effects.py')
  self.assertFalse(any('units/' in n or 'auth' in n for n in release.TARGETS))
 def test_original_publisher_and_health_wait_preserved(self):
  base=types.SimpleNamespace(approved_daily_group=lambda *args:False);original=types.SimpleNamespace(load_base=lambda:base);seen=[]
  with patch.dict(sys.modules,{'release':original,'shipping_readiness':types.SimpleNamespace(extend=lambda b,s:seen.append((b,s)))}):self.assertIs(release.load_base(),base)
  self.assertEqual(original.TARGETS,release.TARGETS);self.assertEqual(base.TARGETS_CHANGED_NAV,set(release.TARGETS.values()));self.assertEqual(seen,[(base,release.SCOPE)])
 def test_existing_knowledge_parent_reuses_exact_original_group_boundary(self):
  def group(m,root,item,info):return info.st_gid==0 or (m['scope']=='original-night' and item==root/'var/lib/fs-hermes-fc' and info.st_uid==0 and info.st_gid==9876 and info.st_mode==0o750)
  base=types.SimpleNamespace(approved_daily_group=group,HERMES_NIGHT_SCOPE='original-night',rooted=lambda r,p:r/p.lstrip('/'))
  with patch.dict(sys.modules,{'release':types.SimpleNamespace(load_base=lambda:base),'shipping_readiness':types.SimpleNamespace(extend=lambda *a:None)}):release.load_base()
  for gid,mode,uid,expected in [(9876,0o750,0,True),(9876,0o770,0,False),(9877,0o750,0,False),(9876,0o750,1,False)]:
   self.assertEqual(base.approved_daily_group({'scope':release.SCOPE},Path('/'),Path('/var/lib/fs-hermes-fc'),types.SimpleNamespace(st_uid=uid,st_gid=gid,st_mode=mode)),expected)
  self.assertFalse(base.approved_daily_group({'scope':'other'},Path('/'),Path('/var/lib/fs-hermes-fc'),types.SimpleNamespace(st_uid=0,st_gid=9876,st_mode=0o750)))

class TransactionPublisher(unittest.TestCase):
 def module(self):
  spec=importlib.util.spec_from_file_location('transaction_release_contract',R/'deploy/transaction_release.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 def base(self,root):
  import hashlib,os
  from contextlib import contextmanager
  self.original_calls=[]
  @contextmanager
  def web(manifest,base_root):
   import fcntl
   path=base_root/'var/www/dashboard/fs-home/transactions/collector.lock';path.parent.mkdir(parents=True,exist_ok=True)
   fd=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
   try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.original_calls.append('web-enter');yield
   finally:self.original_calls.append('web-exit');os.close(fd)
  return types.SimpleNamespace(HERMES_HISTORY_SCOPE=self.module().SCOPE,live_lock=web,
   inspect=lambda m,s,r:dict(original=True),rooted=lambda r,p:Path(r)/p.lstrip('/'),
   no_target_link=lambda p:None,digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
 def legacy(self,root):
  import base64,hashlib
  path=root/'opt/fs-transaction-snapshot/atomic_snapshot.py';path.parent.mkdir(parents=True)
  raw=base64.b64decode((R/'tests/fixtures/atomic_snapshot_live_20261028.b64').read_bytes())
  self.assertEqual(hashlib.sha256(raw).hexdigest(),self.module().LEGACY_ATOMIC_SHA);path.write_bytes(raw)
  (root/'var/www/dashboard/fs-home/transactions').mkdir(parents=True)
 def test_scope_is_only_two_existing_targets_through_original_actual_adapter(self):
  module=self.module();base=self.base(Path('/'));actual=types.SimpleNamespace(load_base=lambda:base)
  with patch.dict(sys.modules,actual_release=actual):self.assertIs(module.load_base(),base)
  self.assertEqual(actual.SCOPE,module.SCOPE);self.assertEqual(actual.NEW,frozenset())
  self.assertEqual(actual.TARGETS,{'source/atomic_snapshot.py':'/opt/fs-transaction-snapshot/atomic_snapshot.py','source/collector.py':'/opt/fs-transaction-snapshot/collector.py'})
  base.HERMES_HISTORY_SCOPE='unbound'
  with self.assertRaisesRegex(ValueError,'web_fence_not_bound'):module.extend(base)
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_legacy_bootstrap_is_readonly_until_apply_and_unknown_missing_inode_is_rejected(self):
  import os,tempfile
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root));lock=base.rooted(root,module.SNAPSHOT_LOCK)
   self.assertTrue(base.inspect(manifest,root,root)['original']);self.assertFalse(lock.exists())
   with base.live_lock(manifest,root):self.assertTrue(lock.exists());self.assertEqual(lock.stat().st_mode&0o777,0o600)
   self.assertTrue(lock.exists())
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root));base.rooted(root,module.ATOMIC_TARGET).write_bytes(b'new or unknown collector')
   with self.assertRaisesRegex(ValueError,'snapshot_lock_missing'):base.inspect(manifest,root,root)
   with self.assertRaisesRegex(ValueError,'snapshot_lock_missing'):
    with base.live_lock(manifest,root):pass
   self.assertFalse(base.rooted(root,module.SNAPSHOT_LOCK).exists())
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_running_collection_blocks_publish_but_not_unrelated_knowledge(self):
  import fcntl,os,tempfile
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root));lock=base.rooted(root,module.SNAPSHOT_LOCK)
   fd=os.open(lock,os.O_RDWR|os.O_CREAT,0o600)
   try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with self.assertRaisesRegex(ValueError,'transaction_snapshot_busy'):base.inspect(manifest,root,root)
    with self.assertRaisesRegex(ValueError,'transaction_snapshot_busy'):
     with base.live_lock(manifest,root):pass
    other=dict(scope='knowledge-only')
    with base.live_lock(other,root):self.assertTrue(base.inspect(other,root,root)['original'])
   finally:os.close(fd)
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_legacy_browser_owner_also_blocks_both_publication_entries(self):
  import fcntl,tempfile
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root))
   with (root/'var/www/dashboard/fs-home/transactions/collector.lock').open('a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with self.assertRaises(BlockingIOError):base.inspect(manifest,root,root)
    with self.assertRaises(BlockingIOError):
     with base.live_lock(manifest,root):pass
   with base.live_lock(manifest,root):self.assertTrue(base.inspect(manifest,root,root)['original'])
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_actual_context_holds_both_locks_allows_inner_inspect_and_releases_on_failure(self):
  import fcntl,tempfile
  from concurrent.futures import ThreadPoolExecutor
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root))
   with self.assertRaisesRegex(RuntimeError,'fixture_failure'):
    with base.live_lock(manifest,root):
     self.assertTrue(base.inspect(manifest,root,root)['original'])
     for name in ('transaction-snapshot.lock','collector.lock'):
      with (root/'var/www/dashboard/fs-home/transactions'/name).open('a+b') as lock:
       with self.assertRaises(BlockingIOError):fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
     with ThreadPoolExecutor(max_workers=1) as pool:
      with self.assertRaisesRegex(ValueError,'transaction_snapshot_busy'):pool.submit(base.inspect,manifest,root,root).result(timeout=1)
     raise RuntimeError('fixture_failure')
   for name in ('transaction-snapshot.lock','collector.lock'):
    with (root/'var/www/dashboard/fs-home/transactions'/name).open('a+b') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)

if __name__=='__main__':unittest.main()
