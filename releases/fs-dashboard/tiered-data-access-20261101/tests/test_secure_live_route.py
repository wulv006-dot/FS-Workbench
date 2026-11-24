import ast,io,json,os,re,types,unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_dispatch import handle, private_body_params
from admin_live_page import LivePageError

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
  method=next(x for x in handler.body if isinstance(x,ast.FunctionDef) and x.name=='do_POST')
  self.env.update({'json':json,'re':re,'private_live_body':private_body_params})
  exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'candidate','exec'),self.env)
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
  self.assertEqual(self.invoke(query='site_id=266&game_id=1327&start=2026-10-01&end_exclusive=2026-10-30')[0],422)
  self.assertEqual(self.invoke(query='site_id=266&game_id=1327&start=2026-10-29&end_exclusive=2026-10-30&extra=1')[0],422)
  self.assertEqual(self.calls,[])
 def test_bounded_multi_day_and_cursor_reach_authorized_handler(self):
  status,_=self.invoke({'Cookie':'MMOEXP_AUTH=fixture'},query='site_id=266&game_id=1327&start=2026-10-01&end_exclusive=2026-10-29&cursor=fixture')
  self.assertEqual(status,206);self.assertEqual(self.calls,['real-user'])
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
 def test_active_get_distinguishes_session_recheck_failure_from_busy_and_unavailable(self):
  source=ROOT.parents[1]/'management-november-20261103'/'source'/'range_api.py'
  tree=ast.parse(source.read_text(encoding='utf8'))
  handler=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Handler')
  method=next(node for node in handler.body if isinstance(node,ast.FunctionDef) and node.name=='do_GET')
  def get(params,actor,*,run_source):
   return handle(params,actor,enabled=True,
                 authorize_for_user=lambda subject:lambda query:dict(scope_hash='fixture',permission_epoch='1',policy_version='v1'),
                 fetch=lambda *args:run_source(lambda:self.calls.append(actor),10),
                 observed_at=lambda:'2026-10-30T12:00:00+08:00')
  self.env.update(LivePageError=LivePageError,get_live_orders=get)
  exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),self.env)
  for status,actor,expected in (
      (429,None,(429,{'error':'source_busy','retryAfter':10})),
      (503,None,(503,{'error':'session_unavailable'})),
      (401,None,(403,{'error':'scope_denied'})),
      (403,None,(403,{'error':'scope_denied'})),
      (200,'other-user',(403,{'error':'scope_denied'})),
  ):
   with self.subTest(status=status,actor=actor):
    answers=iter([(200,'real-user'),(status,actor)])
    self.env['verify_live_session']=lambda cookie:next(answers)
    self.assertEqual(self.invoke({'Cookie':'MMOEXP_AUTH=fixture'}),expected)
    self.assertEqual(self.calls,[])
 def invoke_private(self,body,headers=None,query=''):
  raw=json.dumps(body).encode() if not isinstance(body,bytes) else body
  hdr={'Content-Type':'application/json','Content-Length':str(len(raw)),'Sec-Fetch-Site':'same-origin','Cookie':'MMOEXP_AUTH=fixture'};hdr.update(headers or {})
  h=types.SimpleNamespace(path='/users/live-orders'+query,headers=hdr,rfile=io.BytesIO(raw),connection=types.SimpleNamespace(settimeout=lambda n:None),reply=lambda s,b:self.responses.append((s,b)))
  self.env['do_POST'](h);return self.responses[-1]
 def test_customer_search_uses_verified_session_and_body(self):
  body={'site_id':'266','game_id':'1327','start':'2026-10-01','end_exclusive':'2026-10-29','customer_email':'fixture@example.test'}
  status,_=self.invoke_private(body,{'X-Auth-User':'forged'});self.assertEqual(status,206);self.assertEqual(self.calls,['real-user'])
 def test_customer_search_rejects_missing_session_and_bad_body(self):
  body={'site_id':'266','game_id':'1327','start':'2026-10-01','end_exclusive':'2026-10-29','customer_email':'fixture@example.test'}
  self.session=(401,None);self.assertEqual(self.invoke_private(body)[0],401);self.assertEqual(self.calls,[])
  self.session=(200,'real-user')
  for bad,headers,query in ((dict(body,unknown='x'),{},''),(body,{'Content-Type':'text/plain'},''),(body,{'Content-Length':'4097'},''),(body,{},'?customer_email=fixture')):
   with self.subTest(headers=headers,query=query):self.assertNotEqual(self.invoke_private(bad,headers,query)[0],206)
  self.assertEqual(self.calls,[])
 def test_customer_search_rechecks_session_after_admission(self):
  body={'site_id':'266','game_id':'1327','start':'2026-10-01','end_exclusive':'2026-10-29','customer_email':'fixture@example.test'};count=[]
  def verifier(cookie):
   count.append(1);return (200,'real-user') if len(count)==1 else (401,None)
  self.env['verify_live_session']=verifier
  def fetch(params,actor,*,run_source):
   try:run_source(lambda:self.calls.append(actor),10)
   except PermissionError:return 403,{'error':'session_denied'}
   return 206,{}
  self.env['get_live_orders']=fetch
  self.assertEqual(self.invoke_private(body)[0],403);self.assertEqual(self.calls,[]);self.assertEqual(len(count),2)

if __name__=='__main__':unittest.main(verbosity=2)
