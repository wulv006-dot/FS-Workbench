import ast,os,types,unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

ROOT=Path(__file__).resolve().parent
class SecureRoute(unittest.TestCase):
 def setUp(self):
  path=ROOT/'fixtures'/'range_api_secure_live.py'
  self.assertTrue(path.exists(),'secure route candidate missing')
  tree=ast.parse(path.read_text(encoding='utf8'))
  handler=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Handler')
  method=next(x for x in handler.body if isinstance(x,ast.FunctionDef) and x.name=='do_GET')
  mod=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
  self.calls=[];self.session=(200,'real-user');self.responses=[]
  self.env={'urlsplit':urlsplit,'parse_qs':parse_qs,'date':date,'CONVERSATION_PREFIX':'/conversation',
    'LIVE_ADMIN':types.SimpleNamespace(run=lambda operation,timeout:operation()),
    'verify_live_session':lambda cookie:self.session,
    'get_live_orders':self.get}
  exec(compile(mod,'candidate','exec'),self.env)
 def get(self,params,actor,*,run_source):
  self.calls.append(actor);return 206,{'status':'partial','complete':False}
 def invoke(self,headers=None,query='site_id=266&game_id=1327&start=2026-10-29&end_exclusive=2026-10-30'):
  h=types.SimpleNamespace(path='/users/live-orders?'+query,headers=headers or {},reply=lambda s,b:self.responses.append((s,b)))
  self.env['do_GET'](h);return self.responses[-1]
 def test_forged_username_ignored_and_session_actor_used(self):
  status,_=self.invoke({'X-Auth-User':'forged','Cookie':'MMOEXP_AUTH=fixture'})
  self.assertEqual(status,206);self.assertEqual(self.calls,['real-user'])
 def test_missing_expired_and_auth_error_never_call_source(self):
  for status in (401,403,503,429):
   self.session=(status,None);self.assertEqual(self.invoke({'X-Auth-User':'forged'})[0],status)
  self.assertEqual(self.calls,[])
 def test_bad_range_and_extra_parameter_never_call_source(self):
  self.assertEqual(self.invoke(query='site_id=266&game_id=1327&start=2026-10-29&end_exclusive=2026-10-31')[0],422)
  self.assertEqual(self.invoke(query='site_id=266&game_id=1327&start=2026-10-29&end_exclusive=2026-10-30&extra=1')[0],422)
  self.assertEqual(self.calls,[])
 def test_session_is_rechecked_before_queued_source_work(self):
  count=[]
  def verifier(cookie):
   count.append(1);return (200,'real-user') if len(count)==1 else (401,None)
  self.env['verify_live_session']=verifier
  def fetch(params,actor,*,run_source):
   try:run_source(lambda:self.calls.append(actor),10)
   except PermissionError:return 403,{'error':'session_denied'}
   return 206,{}
  self.env['get_live_orders']=fetch
  self.assertEqual(self.invoke({'Cookie':'MMOEXP_AUTH=fixture'})[0],403)
  self.assertEqual(self.calls,[]);self.assertEqual(len(count),2)

if __name__=='__main__':unittest.main(verbosity=2)
