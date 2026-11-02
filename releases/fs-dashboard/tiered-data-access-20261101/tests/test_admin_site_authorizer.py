import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_site_authorizer import ConfiguredAdminAuthorizer

class RBAC:
 @staticmethod
 def validate(p):return p
 @staticmethod
 def authorize(p,user,method,path):return 200 if user in p['admins'] and method=='GET' and path=='/dashboard/users/' else 403
 @staticmethod
 def is_admin(p,user):return user in p['admins']

class Authorization(unittest.TestCase):
 def setUp(self):
  self.policy={'admins':['trusted']};self.config={'activation_status':'W0_verified','sites':{'266':{}},'projects':{'1327':{}}}
  self.req={'site_id':'266','game_id':'1327'}
  def existing(user,scope,private=False):return RBAC.authorize(self.policy,user,'GET','/dashboard/users/')==200 and (not private or RBAC.is_admin(self.policy,user))
  self.auth=ConfiguredAdminAuthorizer(subject='trusted',load_policy=lambda:self.policy,load_config=lambda:self.config,rbac=RBAC,policy_version='fixture',existing_authorizer=existing)
 def test_only_admin_with_explicit_configured_site_and_game(self):
  grant=self.auth(self.req);self.assertEqual(set(grant),{'scope_hash','permission_epoch','policy_version'})
  self.assertIsNone(self.auth(dict(self.req,site_id='267')));self.assertIsNone(self.auth(dict(self.req,game_id='999')))
  self.policy['admins']=[];self.assertIsNone(self.auth(self.req))
 def test_global_denial_and_missing_configuration_denied(self):
  self.assertIsNone(ConfiguredAdminAuthorizer(subject='viewer',load_policy=lambda:self.policy,load_config=lambda:self.config,rbac=RBAC,policy_version='fixture')(self.req))
  self.config['sites']['267']={};self.assertIsNotNone(self.auth(self.req))
  self.config['sites']={'266':{}};self.config['activation_status']='unknown';self.assertIsNone(self.auth(self.req))
 def test_policy_and_config_changes_change_epoch(self):
  first=self.auth(self.req);self.policy['revision']='new';self.assertNotEqual(first['permission_epoch'],self.auth(self.req)['permission_epoch'])
  second=self.auth(self.req);self.config['projects']['1327']['note']='changed';self.assertNotEqual(second['permission_epoch'],self.auth(self.req)['permission_epoch'])
 def test_missing_policy_fails_closed(self):
  def unavailable():raise OSError('not available')
  auth=ConfiguredAdminAuthorizer(subject='trusted',load_policy=unavailable,load_config=lambda:self.config,rbac=RBAC,policy_version='fixture')
  self.assertIsNone(auth(self.req))
 def test_live_page_uses_same_realistic_grant_before_and_after(self):
  import json
  from admin_live_page import AdminLivePage,LivePageError
  request=dict(self.req,start='2026-10-29',end_exclusive='2026-10-30',fields=['order_id','status'])
  expected=self.auth(request)
  row=dict(id=1,site_id=266,gid=1327,paytime='2026-10-29 12:00:00',status='11')
  def fetch(*args):return 200,json.dumps({'code':1,'data':{'total':1,'list':[row]}}).encode()
  page=AdminLivePage(fetch=fetch,authorize=self.auth,expected_grant=expected,page_size=1,max_bytes=4096,timeout_seconds=5)
  result=page(request);self.assertEqual(result['status'],'partial');self.assertFalse(result['complete'])
  def revoke(*args):self.policy['admins']=[];return fetch(*args)
  page.fetch=revoke
  with self.assertRaisesRegex(LivePageError,'permission_denied'):page(request)

if __name__=='__main__':unittest.main(verbosity=2)
