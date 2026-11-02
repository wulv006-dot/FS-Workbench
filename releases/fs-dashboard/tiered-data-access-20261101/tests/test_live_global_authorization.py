import ast,inspect,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_host import build_handler

class RBAC:
 @staticmethod
 def validate(policy):return policy

class GlobalAuthorization(unittest.TestCase):
 def setUp(self):
  self.assertIn('existing_authorizer',inspect.signature(build_handler).parameters,'existing global authorizer not wired')
  self.policy={'viewers':['staff','admin'],'admins':['admin']}
  self.config={'activation_status':'W0_verified','sites':{'266':{}},'projects':{'1327':{}},'live_admin_single_page':True}
  self.params={'site_id':['266'],'game_id':['1327'],'start':['2026-10-29'],'end_exclusive':['2026-10-30']}
  self.calls=[]
  def authorize(user,scope,private=False):return user in self.policy['viewers'] and (not private or user in self.policy['admins'])
  self.authorize=authorize
  def fetch(*args):
   self.calls.append(1)
   return 200,b'{"code":1,"data":{"total":1,"list":[{"id":123,"site_id":266,"gid":1327,"paytime":"2026-10-29 11:12:13","status":"11","pay_status":"1","email":"fixture@example.test"}]}}'
  self.handler=build_handler(load_config=lambda:self.config,load_policy=lambda:self.policy,rbac=RBAC,fetch=fetch,run_source=lambda operation,timeout:operation(),existing_authorizer=authorize,observed_at=lambda:'2026-11-02T00:00:00Z')
 def test_regular_global_viewer_gets_nonprivate_aggregate(self):
  status,result=self.handler(self.params,'staff');self.assertEqual(status,206)
  self.assertEqual(result['data'],[]);self.assertEqual(result['observed_page_rows'],1);self.assertEqual(result['source_reported_total'],1)
  self.assertNotIn('123',str(result));self.assertNotIn('11:12:13',str(result))
  self.assertNotIn('fixture@example.test',str(result))
 def test_regular_viewer_cursor_does_not_disclose_private_order_ids(self):
  import json
  def many(*args):
   rows=[dict(id=n,site_id=266,gid=1327,paytime='2026-10-29 11:12:13',status='11') for n in range(100,80,-1)]
   return 200,json.dumps({'code':1,'data':{'total':21,'list':rows}}).encode()
  handler=build_handler(load_config=lambda:self.config,load_policy=lambda:self.policy,rbac=RBAC,fetch=many,run_source=lambda operation,timeout:operation(),existing_authorizer=self.authorize,observed_at=lambda:'2026-11-02T00:00:00Z')
  status,result=handler(self.params,'staff');self.assertEqual(status,206)
  import base64,json
  self.assertEqual(result['data'],[]);self.assertIsInstance(result['next_cursor'],str)
  body=result['next_cursor'].split('.')[0];state=json.loads(base64.urlsafe_b64decode(body+'='*((-len(body))%4)))
  self.assertIsInstance(state[2],str);self.assertNotIn(str(81),state[2])
 def test_existing_private_permission_exposes_private_order_rows(self):
  status,result=self.handler(self.params,'admin');self.assertEqual(status,206)
  self.assertEqual(result['data'][0],{'order_id':'123','paid_at':'2026-10-29 11:12:13','status':'11','pay_status':'1','customer_email':'fixture@example.test'})
 def test_no_global_permission_or_unknown_site_or_game_never_reads_source(self):
  self.assertEqual(self.handler(self.params,'outsider')[0],403)
  for key,value in [('site_id','535'),('game_id','999')]:self.assertEqual(self.handler(dict(self.params,**{key:[value]}),'staff')[0],403)
  self.assertEqual(self.calls,[])
 def test_existing_global_permission_revocation_is_immediate(self):
  self.assertEqual(self.handler(self.params,'staff')[0],206);self.policy['viewers'].remove('staff')
  self.assertEqual(self.handler(self.params,'staff')[0],403);self.assertEqual(len(self.calls),1)
 def test_revoking_private_during_fetch_never_returns_order_rows(self):
  def revoked(*args):
   self.policy['admins'].remove('admin')
   return 200,b'{"code":1,"data":{"total":0,"list":[]}}'
  handler=build_handler(load_config=lambda:self.config,load_policy=lambda:self.policy,rbac=RBAC,fetch=revoked,run_source=lambda operation,timeout:operation(),existing_authorizer=self.authorize,observed_at=lambda:'2026-11-02T00:00:00Z')
  self.assertEqual(handler(self.params,'admin')[0],403)
 def test_real_users_runtime_authorizer_is_reused_with_live_policy_changes(self):
  source=Path(__file__).resolve().parents[2]/'user-analytics-20261022'/'source'/'user_runtime.py'
  tree=ast.parse(source.read_text(encoding='utf8'))
  func=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='authorize')
  env={'Path':Path,'sys':sys};exec(compile(ast.fix_missing_locations(ast.Module(body=[func],type_ignores=[])),str(source),'exec'),env)
  with tempfile.TemporaryDirectory() as tmp:
   policy_file=Path(tmp)/'policy.json';policy_file.write_text('{}',encoding='utf8')
   fake=types.SimpleNamespace(LIVE_POLICY=str(policy_file),load_policy=lambda:self.policy,
    authorize=lambda policy,user,method,path:200 if user in policy['viewers'] else 403,
    is_admin=lambda policy,user:user in policy['admins'])
   with patch.dict(sys.modules,{'rbac':fake}):
    actual=env['authorize'];query={'scope':'site','scope_id':'266'}
    self.assertTrue(actual('staff',query,False));self.assertFalse(actual('staff',query,True))
    self.assertTrue(actual('admin',query,True));self.policy['viewers'].remove('staff')
    self.assertFalse(actual('staff',query,False))

if __name__=='__main__':unittest.main(verbosity=2)
