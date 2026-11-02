import base64,hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_supervised_transport import SupervisedAdminTransport,SourceResponseTooLarge

class TestSupervised(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='fs-supervised-fixture-');self.addCleanup(self.tmp.cleanup)
  self.worker=Path(self.tmp.name)/'worker.py';self.worker.write_text('# fixture worker\n',encoding='utf-8');self.worker.chmod(0o600)
  self.sha=hashlib.sha256(self.worker.read_bytes()).hexdigest();self.calls=[]
  def runner(args,**kwargs):
   self.calls.append((args,kwargs));return subprocess.CompletedProcess(args,0,json.dumps({'status':200,'body':base64.b64encode(b'{"ok":1}').decode()}).encode())
  self.runner=runner;self.transport=SupervisedAdminTransport(worker=self.worker,worker_sha256=self.sha,python=sys.executable,runner=runner)
 def test_success_uses_hard_subprocess_timeout_and_bounded_output(self):
  status,body=self.transport('/admin/order.Order/index',{'page':1},3,100)
  self.assertEqual((status,body),(200,b'{"ok":1}'));args,kw=self.calls[0];self.assertEqual(kw['timeout'],3);self.assertEqual(args[1:3],['-I','-B']);self.assertNotIn('shell',kw)
 def test_worker_drift_or_symlink_fails_before_start(self):
  self.worker.write_text('changed',encoding='utf-8')
  with self.assertRaises(ValueError):self.transport('/admin/order.Order/index',{'page':1},3,100)
  self.assertEqual(self.calls,[])
 def test_timeout_unavailable_and_oversize_are_not_success(self):
  def timed(args,**kw):raise subprocess.TimeoutExpired(args,3)
  self.transport.runner=timed
  with self.assertRaises(TimeoutError):self.transport('/admin/order.Order/index',{'page':1},3,100)
  def bad(args,**kw):return subprocess.CompletedProcess(args,0,json.dumps({'status':200,'body':base64.b64encode(b'x'*101).decode()}).encode())
  self.transport.runner=bad
  with self.assertRaises(ValueError):self.transport('/admin/order.Order/index',{'page':1},3,100)
  def failed(args,**kw):return subprocess.CompletedProcess(args,1,b'')
  self.transport.runner=failed
  with self.assertRaises(OSError):self.transport('/admin/order.Order/index',{'page':1},3,100)
 def test_only_fixed_endpoint_and_budget(self):
  for path,timeout,cap in (('/other',3,100),('/admin/order.Order/index',0,100),('/admin/order.Order/index',3,0)):
   with self.assertRaises(ValueError):self.transport(path,{'page':1},timeout,cap)
  self.assertEqual(self.calls,[])
 def test_explicit_worker_byte_limit_is_not_generic_unavailable(self):
  self.transport.runner=lambda args,**kw:subprocess.CompletedProcess(args,0,b'{"error":"source_response_too_large"}')
  with self.assertRaises(SourceResponseTooLarge):self.transport('/admin/order.Order/index',{'page':1},3,100)

if __name__=='__main__':unittest.main(verbosity=2)
