import hashlib,json,subprocess,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'source')]
from admin_live_host import build_handler,WORKER_SHA256
from test_admin_site_authorizer import RBAC

class Host(unittest.TestCase):
 def setUp(self):
  self.config={'activation_status':'W0_verified','sites':{'266':{}},'projects':{'1327':{}}};self.policy={'admins':['trusted']};self.calls=[]
  def fetch(path,params,timeout,cap):self.calls.append(path);return 200,json.dumps({'code':1,'data':{'total':0,'list':[]}}).encode()
  self.fetch=fetch;self.params={'site_id':['266'],'game_id':['1327'],'start':['2026-10-29'],'end_exclusive':['2026-10-30']}
  self.handler=build_handler(load_config=lambda:self.config,load_policy=lambda:self.policy,rbac=RBAC,fetch=self.fetch)
 def test_default_disabled_never_calls_source(self):
  status,data=self.handler(self.params,'trusted');self.assertEqual(status,503);self.assertEqual(data['error'],'live_source_not_enabled');self.assertEqual(self.calls,[])
 def test_worker_pin_matches_delivery_source(self):
  source=Path(__file__).resolve().parents[1]/'source'/'admin_live_worker.py'
  self.assertEqual(WORKER_SHA256,hashlib.sha256(source.read_bytes()).hexdigest())
 def test_explicit_enable_admin_and_site_with_revocation(self):
  self.config['live_admin_single_page']=True
  status,data=self.handler(self.params,'trusted');self.assertEqual(status,206);self.assertFalse(data['complete']);self.assertEqual(len(self.calls),1)
  self.policy['admins']=[];status,data=self.handler(self.params,'trusted');self.assertEqual(status,403);self.assertEqual(len(self.calls),1)
 def test_disabled_when_policy_missing_or_configuration_ambiguous(self):
  self.config['live_admin_single_page']=True;self.config['sites']['267']={}
  self.assertEqual(self.handler(self.params,'trusted')[0],403);self.assertEqual(self.calls,[])
  def unavailable():raise OSError('missing')
  handler=build_handler(load_config=lambda:self.config,load_policy=unavailable,rbac=RBAC,fetch=self.fetch)
  self.assertEqual(handler(self.params,'trusted')[0],403);self.assertEqual(self.calls,[])
 def test_complete_host_dispatch_through_supervisor_and_worker_fixture(self):
  from admin_live_worker import handle as worker_handle
  from admin_supervised_transport import SupervisedAdminTransport
  from test_admin_live_worker import Fake
  Fake.calls=[];Fake.body=json.dumps({'code':1,'data':{'total':1,'list':[dict(id=1,site_id=266,gid=1327,paytime='2026-10-29 12:00:00',status='11',email='fixture@example.test')]}}).encode()
  def runner(args,**kwargs):return subprocess.CompletedProcess(args,0,json.dumps(worker_handle(json.loads(kwargs['input']),lambda:Fake)).encode())
  worker=Path(__file__).resolve().parents[1]/'source'/'admin_live_worker.py'
  fetch=SupervisedAdminTransport(worker=worker,worker_sha256=WORKER_SHA256,python=sys.executable,runner=runner)
  handler=build_handler(load_config=lambda:self.config,load_policy=lambda:self.policy,rbac=RBAC,fetch=fetch)
  self.config['live_admin_single_page']=True
  status,result=handler(self.params,'trusted');self.assertEqual(status,206);self.assertFalse(result['complete']);self.assertEqual(result['data'][0]['order_id'],'1');self.assertNotIn('email',result['data'][0]);self.assertEqual(len(Fake.calls),1)

if __name__=='__main__':unittest.main(verbosity=2)
