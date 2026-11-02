import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_dispatch import handle

class Dispatch(unittest.TestCase):
 def setUp(self):
  self.grant={'scope_hash':'site-game','permission_epoch':'1','policy_version':'v1'};self.calls=[]
  self.params={'site_id':['266'],'game_id':['1327'],'start':['2026-10-29'],'end_exclusive':['2026-10-30']}
  def auth(user):return lambda query:dict(self.grant) if user=='admin' else None
  def fetch(path,params,timeout,cap):
   self.calls.append((path,params,timeout,cap));return 200,json.dumps({'code':1,'data':{'total':0,'list':[]}}).encode()
  self.auth,self.fetch=auth,fetch
 def test_disabled_and_anonymous_do_not_contact_source(self):
  self.assertEqual(handle(self.params,'admin',authorize_for_user=self.auth,fetch=self.fetch)[0],503)
  self.assertEqual(handle(self.params,'',authorize_for_user=self.auth,fetch=self.fetch,enabled=True)[0],401)
  self.assertEqual(self.calls,[])
 def test_authorized_page_explicit_partial_never_full_zero(self):
  status,result=handle(self.params,'admin',authorize_for_user=self.auth,fetch=self.fetch,enabled=True)
  self.assertEqual(status,206);self.assertEqual(result['status'],'partial');self.assertFalse(result['complete']);self.assertEqual(len(self.calls),1)
 def test_denied_and_extra_parameters_do_not_contact_source(self):
  self.assertEqual(handle(self.params,'viewer',authorize_for_user=self.auth,fetch=self.fetch,enabled=True)[0],403)
  self.assertEqual(handle(dict(self.params,url=['http://x']),'admin',authorize_for_user=self.auth,fetch=self.fetch,enabled=True)[0],422)
  self.assertEqual(self.calls,[])
 def test_source_timeout_returns_error_not_zero(self):
  def timeout(*a):raise TimeoutError()
  status,result=handle(self.params,'admin',authorize_for_user=self.auth,fetch=timeout,enabled=True)
  self.assertEqual(status,503);self.assertEqual(result['error'],'source_timeout');self.assertNotIn('data',result)

if __name__=='__main__':unittest.main(verbosity=2)
