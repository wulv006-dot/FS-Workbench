import json,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'source')]
from admin_orders_adapter import AdminOrdersAdapter,SourceError

class AdminOrders(unittest.TestCase):
 def setUp(self):
  self.grant={'scope_hash':'scope','permission_epoch':'1','policy_version':'p'}
  self.request=dict(source='Admin',site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-10-03',fields=['order_id','paid_at','status'],filters={},date_semantics='paid_at',cursor=None,watermark='fixed')
  self.rows=[dict(id=2,site_id=266,gid=1327,paytime='2026-10-02 12:00:00',status='11',email='never-return@example.test'),dict(id=1,site_id=266,gid=1327,paytime='2026-10-01 12:00:00',status='11')]
  self.calls=[]
  def client(path,params,timeout,max_bytes):
   self.calls.append((path,params,timeout,max_bytes));idx=params['page']-1
   return 200,json.dumps({'code':1,'data':{'total':2,'list':[self.rows[idx]]}}).encode()
  self.client=client;self.proof=lambda r:dict(stable=True,watermark='fixed')
  self.adapter=AdminOrdersAdapter(fetch=self.client,authorize=lambda r:dict(self.grant),expected_grant=dict(self.grant),source_proof=self.proof,secret=b'x'*32,page_size=1,max_pages=2,max_response_bytes=1024,timeout_seconds=3)
 def test_scoped_two_pages_and_projection_no_pii(self):
  a=self.adapter(self.request);self.assertFalse(a['complete']);self.assertEqual(a['rows'][0]['order_id'],'2');self.assertNotIn('email',a['rows'][0])
  b=self.adapter(dict(self.request,cursor=a['next_cursor']));self.assertTrue(b['complete']);self.assertEqual(b['rows'][0]['order_id'],'1')
  path,params,timeout,cap=self.calls[0];self.assertEqual(path,'/admin/order.Order/index');self.assertEqual(params['page'],1);self.assertEqual((timeout,cap),(3,1024))
  self.assertEqual(params['search[0][val]'],'266');self.assertEqual(params['search[1][val]'],'1327');self.assertEqual(params['search[2][val]'],'2026-10-01 00:00:00,2026-10-02 23:59:59')
 def test_untrusted_scope_and_fields_fail_before_io(self):
  for change in (dict(fields=['email']),dict(fields=[{}]),dict(site_id=''),dict(filters={'sql':'x'}),dict(url='x'),dict(date_semantics='unknown')):
   with self.subTest(change=change),self.assertRaises(SourceError):self.adapter(dict(self.request,**change))
  self.assertEqual(self.calls,[])
 def test_revoke_before_or_after_io_no_result(self):
  self.grant['permission_epoch']='2'
  with self.assertRaises(SourceError):self.adapter(self.request)
  self.assertEqual(self.calls,[])
  self.grant['permission_epoch']='1'
  def revoked(*args):self.grant['permission_epoch']='2';return self.client(*args)
  self.adapter.fetch=revoked
  with self.assertRaises(SourceError):self.adapter(self.request)
 def test_unknown_or_changed_watermark_fails_closed(self):
  for proof in (lambda r:None,lambda r:dict(stable=False,watermark='fixed'),lambda r:dict(stable=True,watermark='other')):
   self.adapter.source_proof=proof
   with self.assertRaises(SourceError):self.adapter(self.request)
  self.assertEqual(self.calls,[])
 def test_invalid_cursor_and_changed_total_not_complete(self):
  a=self.adapter(self.request)
  with self.assertRaises(SourceError):self.adapter(dict(self.request,cursor=a['next_cursor']+'x'))
  def unstable(*args):return 200,json.dumps({'code':1,'data':{'total':3,'list':[self.rows[1]]}}).encode()
  self.adapter.fetch=unstable
  with self.assertRaises(SourceError):self.adapter(dict(self.request,cursor=a['next_cursor']))
 def test_denied_rate_timeout_and_empty_are_distinct(self):
  for code,error in ((401,'source_auth'),(429,'source_rate_limited')):
   self.adapter.fetch=lambda *args:(code,b'{}')
   with self.assertRaises(SourceError) as e:self.adapter(self.request)
   self.assertEqual(e.exception.code,error)
  self.adapter.fetch=lambda *args:(_ for _ in ()).throw(TimeoutError())
  with self.assertRaises(SourceError) as e:self.adapter(self.request)
  self.assertEqual(e.exception.code,'source_timeout')
  self.adapter.fetch=lambda *args:(200,b'{"code":1,"data":{"total":0,"list":[]}}')
  v=self.adapter(self.request);self.assertTrue(v['complete']);self.assertTrue(v['confirmed_empty']);self.assertEqual(v['rows'],[])
 def test_budget_and_wrong_source_scope_fail(self):
  self.adapter.fetch=lambda *args:(200,b'x'*1025)
  with self.assertRaises(SourceError):self.adapter(self.request)
  self.rows[0]['site_id']=999;self.adapter.fetch=self.client
  with self.assertRaises(SourceError):self.adapter(self.request)
 def test_page_budget_and_invalid_row_never_return_partial_as_complete(self):
  self.adapter.max_pages=1
  with self.assertRaises(SourceError) as error:self.adapter(self.request)
  self.assertEqual(error.exception.code,'source_unstable')
  self.adapter.max_pages=2;self.rows[0]['paytime']='2026-09-30 23:59:59'
  with self.assertRaises(SourceError):self.adapter(self.request)
 def test_watermark_revoked_during_io_fails(self):
  state={'valid':True}
  self.adapter.source_proof=lambda r:dict(stable=state['valid'],watermark='fixed')
  def fetch(*args):state['valid']=False;return self.client(*args)
  self.adapter.fetch=fetch
  with self.assertRaises(SourceError) as error:self.adapter(self.request)
  self.assertEqual(error.exception.code,'source_unstable')
 def test_engine_reuses_planner_scope_and_pages_without_database(self):
  from threading import RLock
  import test_query_planner as fixtures
  from query_planner import plan
  from range_jobs import Engine
  fixture=fixtures.Planner();fixture.setUp()
  fixture.dataset.update(fields=['order_id','paid_at','status'],source_max_slice=dict(unit='days',value=28))
  req=dict(fixture.req,fields=['order_id','paid_at','status'],start='2026-10-01',end_exclusive='2026-10-03',policy_version='p')
  fixture.cap['policy_version']='p'
  p=plan(req,fixture.cap,fixture.dataset,fixture.budgets)
  jobs,subs,cache={},{},{}
  engine=Engine(jobs=jobs,subscriptions=subs,cache=cache,authorize=lambda identity,query:dict(self.grant),secret=b'y'*32,lock=RLock())
  handle=engine.submit('authorized-fixture',p,watermark='fixed',source_contract='fixture-admin-v1')
  key=subs[handle]['key'];engine.step(key,self.adapter);self.assertFalse(engine.status('authorized-fixture',handle)['complete'])
  engine.step(key,self.adapter);self.assertTrue(engine.status('authorized-fixture',handle)['complete'])
  result=engine.page('authorized-fixture',handle);self.assertEqual([x['order_id'] for x in result['data']],['2','1'])
  self.assertFalse(any('email' in row for row in result['data']))

if __name__=='__main__':unittest.main(verbosity=2)
