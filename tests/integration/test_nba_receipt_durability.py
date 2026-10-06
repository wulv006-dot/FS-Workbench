"""Offline fake-effect tests; Linux syscalls are mocked on Windows, never power-loss proof."""
import ast,contextlib,hashlib,importlib.util,io,json,os,socket,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('writer',ROOT/'opt/nba-reprice/backend/write_contract.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
def envelope(request='a'*32,price=1):
 raw=json.dumps({'confirm':'NBA_PRICE_APPLY','operator':'wulv','prices':{'PlayStation 5':price}},separators=(',',':'))
 return {'requestId':request,'planSha256':hashlib.sha256(raw.encode()).hexdigest(),'planJson':raw}

class Durability(unittest.TestCase):
 def test_actual_cli_bound_setup_failure_keeps_unknown_identity(self):
  tree=ast.parse((ROOT/'opt/nba-reprice/backend/p2pah_api.py').read_text(encoding='utf-8'))
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='write_from_file')
  def refused(*args):raise OSError('synthetic lock/setup/read failure')
  ns={'os':os,'json':json,'validate_envelope':w.validate_envelope,'persistence_capability':w.persistence_capability,'execute_bound_plan':refused,'DATA_DIR':'synthetic','_write_prices':lambda p:None}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'p2pah_api.py','exec'),ns)
  with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'WRITE_READY':'true'}):
   p=Path(root)/'plan.json';p.write_text(json.dumps(envelope()),encoding='utf-8');out=io.StringIO()
   with contextlib.redirect_stdout(out):ns['write_from_file'](p)
   r=json.loads(out.getvalue());self.assertEqual(r['state'],'unknown');self.assertEqual(r['requestId'],'a'*32);self.assertEqual(r['operator'],'wulv');self.assertEqual(r['planSha256'],envelope()['planSha256'])
 def test_pending_and_completed_order_including_new_receipts_parent(self):
  with tempfile.TemporaryDirectory() as root:
   events=[];replace=os.replace;fsync=os.fsync
   def sync_dir(path):events.append(('directory',str(path)))
   def sync_file(fd):events.append(('file',));fsync(fd)
   def rename(src,dst):events.append(('replace',));replace(src,dst)
   def effect(plan):events.append(('effect',));return {'ok':True}
   with patch.object(w,'_sync_directory',side_effect=sync_dir),patch.object(w.os,'fsync',side_effect=sync_file),patch.object(w.os,'replace',side_effect=rename):
    r=w.execute_bound_plan(root,envelope(),effect)
   self.assertTrue(r['ok']);i=events.index(('effect',))
   self.assertEqual(events[i-3:i],[('file',),('replace',),('directory',str(Path(root)/'receipts'))])
   self.assertEqual(events[i+1:],[('file',),('replace',),('directory',str(Path(root)/'receipts'))])
   self.assertIn(('directory',root),events[:i-3]);self.assertIn(('directory',str(Path(root).parent)),events[:i-3])
 def test_pending_file_sync_replace_and_directory_failures_prevent_effect(self):
  for phase in ['file','replace','directory']:
   with self.subTest(phase=phase),tempfile.TemporaryDirectory() as root:
    calls=[];hits=[];receipt_fds=set();folder=Path(root)/'receipts';receipt=folder/('a'*32+'.json')
    fsync=os.fsync;sync=w._sync_directory;mkstemp=tempfile.mkstemp
    def receipt_temp(*args,**kwargs):
     fd,name=mkstemp(*args,**kwargs)
     self.assertEqual(Path(name).parent,folder);self.assertTrue(Path(name).name.startswith('.receipt-'))
     receipt_fds.add(fd);return fd,name
    def file_failure(fd):
     if fd in receipt_fds:
      self.assertFalse(receipt.exists());hits.append('pending-file');raise OSError('synthetic pending file sync')
     return fsync(fd)  # Initial directory fsync must reach the real platform implementation.
    def replace_failure(src,dst):
     self.assertEqual(Path(dst),receipt);self.assertEqual(json.loads(Path(src).read_text(encoding='utf-8'))['state'],'pending')
     hits.append('pending-replace');raise OSError('synthetic pending rename')
    def dir_failure(path):
     if Path(path)==folder and receipt.exists():
      self.assertEqual(json.loads(receipt.read_text(encoding='utf-8'))['state'],'pending')
      hits.append('pending-directory');raise OSError('synthetic pending directory sync')
     return sync(path)
    target={'file':patch.object(w.os,'fsync',side_effect=file_failure),
            'replace':patch.object(w.os,'replace',side_effect=replace_failure),
            'directory':patch.object(w,'_sync_directory',side_effect=dir_failure)}[phase]
    with patch.object(tempfile,'mkstemp',side_effect=receipt_temp),target:
     r=w.execute_bound_plan(root,envelope(),lambda p:calls.append(p))
    self.assertEqual(hits,['pending-'+phase]);self.assertEqual(r['state'],'rejected')
    self.assertEqual(r['error'],'PENDING_PERSIST_FAILED');self.assertEqual(calls,[])
    self.assertEqual(list(folder.glob('.receipt-*')),[])
    self.assertEqual(receipt.exists(),phase=='directory')
 def test_initial_runtime_directory_sync_failure_prevents_effect(self):
  with tempfile.TemporaryDirectory() as root:
   calls=[];hits=[];sync=w._sync_directory
   def initial_failure(path):
    if Path(path)==Path(root):
     self.assertFalse((Path(root)/'receipts').exists());hits.append('initial-runtime')
     raise OSError('synthetic initial runtime sync')
    return sync(path)
   with patch.object(w,'_sync_directory',side_effect=initial_failure),self.assertRaisesRegex(OSError,'initial runtime sync'):
    w.execute_bound_plan(root,envelope(),lambda p:calls.append(p))
   self.assertEqual(hits,['initial-runtime']);self.assertEqual(calls,[])
   self.assertFalse((Path(root)/'writer.lock').exists());self.assertFalse((Path(root)/'receipts').exists())
 def test_new_receipts_parent_sync_failure_prevents_effect(self):
  with tempfile.TemporaryDirectory() as root:
   calls=[];hits=[];original=w._sync_directory
   def sync(path):
    if Path(path)==Path(root) and (Path(root)/'receipts').exists():
     hits.append('new-receipts-parent');raise OSError('synthetic mkdir sync')
    return original(path)
   with patch.object(w,'_sync_directory',side_effect=sync),self.assertRaisesRegex(OSError,'mkdir sync'):
    w.execute_bound_plan(root,envelope(),lambda p:calls.append(p))
   self.assertEqual(hits,['new-receipts-parent']);self.assertEqual(calls,[])
   self.assertEqual(list((Path(root)/'receipts').iterdir()),[])
 def test_completion_sync_failure_unknown_and_restart_never_reexecutes(self):
  with tempfile.TemporaryDirectory() as root:
   calls=[];original=w._persist
   def persist(path,value):
    if value['state']=='completed':raise OSError('synthetic completion failure')
    original(path,value)
   with patch.object(w,'_persist',side_effect=persist):r=w.execute_bound_plan(root,envelope(),lambda p:(calls.append(p) or {'ok':True}))
   self.assertEqual(r['state'],'unknown')
   self.assertEqual(w.execute_bound_plan(root,envelope(),lambda p:calls.append(p))['state'],'unknown');self.assertEqual(len(calls),1)
 def test_same_id_concurrent_one_fake_effect_and_changed_hash_refused(self):
  import concurrent.futures
  with tempfile.TemporaryDirectory() as root:
   calls=[]
   def run():return w.execute_bound_plan(root,envelope(),lambda p:(calls.append(p) or {'ok':True}))
   with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:run(),range(4)))
   self.assertEqual(len(calls),1);self.assertEqual(sum(bool(r.get('replayedReceipt')) for r in results),3)
   with self.assertRaisesRegex(ValueError,'CONFLICT'):w.execute_bound_plan(root,envelope(price=2),lambda p:calls.append(p))
 def test_linux_syscall_contract_and_unsupported_platform_boundary(self):
  events=[]
  with patch.object(w.sys,'platform','linux'),patch.object(w.os,'O_DIRECTORY',65536,create=True),patch.object(w.os,'open',side_effect=lambda *args:(events.append(('open',args)) or 42)),patch.object(w.os,'fsync',side_effect=lambda fd:events.append(('fsync',fd))),patch.object(w.os,'close',side_effect=lambda fd:events.append(('close',fd))):
   w._sync_directory(Path('/synthetic'));self.assertEqual(w.persistence_capability(),'linux-directory-fsync')
  self.assertEqual([e[0] for e in events],['open','fsync','close'])
  with patch.object(w.sys,'platform','win32'),patch.object(w.os,'open',side_effect=AssertionError('directory fsync unsupported')):
   w._sync_directory(Path('synthetic'));self.assertEqual(w.persistence_capability(),'file-fsync-only-no-power-loss-guarantee')
 def test_completed_failed_receipt_replayed_and_corrupt_receipt_blocks_effect(self):
  with tempfile.TemporaryDirectory() as root:
   calls=[];p=envelope()
   r=w.execute_bound_plan(root,p,lambda plan:(calls.append(plan) or {'ok':False,'error':'SYNTHETIC_PARTIAL'}))
   self.assertEqual(r['state'],'completed');self.assertFalse(r['ok'])
   self.assertTrue(w.execute_bound_plan(root,p,lambda plan:calls.append(plan))['replayedReceipt']);self.assertEqual(len(calls),1)
   (Path(root)/'receipts'/('a'*32+'.json')).write_text('corrupt',encoding='utf-8')
   self.assertEqual(w.execute_bound_plan(root,p,lambda plan:calls.append(plan))['state'],'unknown')
   self.assertEqual(len(calls),1)

if __name__=='__main__':
 with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')),patch('subprocess.Popen',side_effect=AssertionError('subprocess forbidden')):
  unittest.main(verbosity=2)
