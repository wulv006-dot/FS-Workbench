import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_page import AdminLivePage,LivePageError
from admin_live_dispatch import handle as dispatch
from admin_live_worker import handle as worker
from test_admin_live_worker import Fake,valid_params
import datetime

class Pagination(unittest.TestCase):
 def setUp(self):
  self.grant={'scope_hash':'actor-site-game','permission_epoch':'epoch-1','policy_version':'v1'}
  self.request={'site_id':'266','game_id':'1327','start':'2026-10-29','end_exclusive':'2026-11-02','fields':['order_id','paid_at','status','pay_status','customer_email']}
  self.calls=[]
  self.rows=[dict(id=n,site_id=266,gid=1327,paytime='2026-10-30 10:00:00',status='11',pay_status='1',email='user%d@example.test'%n) for n in (9,8,7)]
  def fetch(path,params,timeout,cap):
   self.calls.append(params['page']); start=(params['page']-1)*2
   return 200,json.dumps({'code':1,'data':{'total':len(self.rows),'list':self.rows[start:start+2]}}).encode()
  self.adapter=AdminLivePage(fetch=fetch,authorize=lambda q:dict(self.grant),expected_grant=dict(self.grant),page_size=2,max_bytes=4096,timeout_seconds=5,observed_at=lambda:'2026-11-02T00:00:00Z',cursor_key=b'a'*32)
 def test_next_page_and_private_customer_identifier(self):
  first=self.adapter(self.request)
  self.assertEqual(len(first['data']),2);self.assertEqual(first['data'][0]['customer_email'],'user9@example.test')
  self.assertEqual(first['data'][0]['pay_status'],'1')
  self.assertIsInstance(first['next_cursor'],str)
  second=self.adapter(dict(self.request,cursor=first['next_cursor']))
  self.assertEqual([r['order_id'] for r in second['data']],['7']);self.assertIsNone(second['next_cursor'])
  self.assertFalse(second['complete']);self.assertEqual(second['limitation'],'live_pagination_not_snapshot');self.assertEqual(self.calls,[1,2])
 def test_cursor_tamper_scope_and_revocation_rejected_before_source(self):
  cursor=self.adapter(self.request)['next_cursor'];self.calls.clear()
  for change in ({'cursor':cursor+'a'},{'cursor':cursor,'game_id':'999'}):
   with self.subTest(change=change),self.assertRaises(LivePageError):self.adapter(dict(self.request,**change))
  self.grant['permission_epoch']='epoch-2'
  with self.assertRaises(LivePageError):self.adapter(dict(self.request,cursor=cursor))
  self.assertEqual(self.calls,[])
 def test_cursor_cannot_be_reused_by_another_actor_or_after_private_revocation(self):
  cursor=self.adapter(self.request)['next_cursor'];self.calls.clear()
  other=dict(self.grant,scope_hash='other-actor')
  other_adapter=AdminLivePage(fetch=self.adapter.fetch,authorize=lambda q:other,expected_grant=other,page_size=2,max_bytes=4096,timeout_seconds=5,observed_at=lambda:'2026-11-02T00:00:00Z',cursor_key=b'a'*32)
  with self.assertRaises(LivePageError):other_adapter(dict(self.request,cursor=cursor))
  self.adapter.authorize=lambda q:None
  with self.assertRaises(LivePageError):self.adapter(dict(self.request,cursor=cursor))
  self.assertEqual(self.calls,[])
 def test_moved_boundary_or_total_is_explicit_failure(self):
  cursor=self.adapter(self.request)['next_cursor'];self.rows.insert(0,dict(self.rows[0],id=10))
  with self.assertRaises(LivePageError) as e:self.adapter(dict(self.request,cursor=cursor))
  self.assertEqual(e.exception.code,'source_changed')
 def test_duplicate_across_page_boundary_is_explicit_failure(self):
  cursor=self.adapter(self.request)['next_cursor'];self.rows[2]=dict(self.rows[1])
  with self.assertRaises(LivePageError) as e:self.adapter(dict(self.request,cursor=cursor))
  self.assertEqual(e.exception.code,'source_changed')
 def test_missing_email_is_not_fabricated(self):
  del self.rows[0]['email']
  with self.assertRaises(LivePageError):self.adapter(self.request)
 def test_short_page_does_not_skip_source_rows(self):
  self.adapter.fetch=lambda *a:(200,json.dumps({'code':1,'data':{'total':3,'list':[self.rows[0]]}}).encode())
  with self.assertRaises(LivePageError) as e:self.adapter(self.request)
  self.assertEqual(e.exception.code,'source_changed')
 def test_http_dispatch_uses_cursor_and_private_fields(self):
  params={k:[v] for k,v in self.request.items() if k!='fields'}
  def auth(user):return lambda query:dict(self.grant)
  def fetch(path,params,timeout,cap):
   self.calls.append(params['page']); start=(params['page']-1)*50
   rows=[dict(id=n,site_id=266,gid=1327,paytime='2026-10-30 10:00:00',status='11',pay_status='1',email='fixture@example.test') for n in range(100,49,-1)]
   return 200,json.dumps({'code':1,'data':{'total':51,'list':rows[start:start+50]}}).encode()
  kw=dict(authorize_for_user=auth,fetch=fetch,enabled=True,observed_at=lambda:'2026-11-02T00:00:00Z',select_fields=lambda q:self.request['fields'])
  status,first=dispatch(params,'admin',**kw);self.assertEqual(status,206);self.assertEqual(len(first['data']),50)
  self.assertIn('customer_email',first['data'][0]);self.assertTrue(first['next_cursor'])
  status,second=dispatch(dict(params,cursor=[first['next_cursor']]),'admin',**kw)
  self.assertEqual(status,206);self.assertEqual(len(second['data']),1);self.assertEqual(self.calls,[1,2])
 def test_worker_accepts_bounded_page_two(self):
  params=valid_params();params['page']=2;Fake.calls=[]
  value=worker({'path':'/admin/order.Order/index','params':params,'max_bytes':4096},lambda:Fake,today=lambda:datetime.date(2026,11,2))
  self.assertEqual(value['status'],200);self.assertEqual(len(Fake.calls),1)

if __name__=='__main__':unittest.main()
