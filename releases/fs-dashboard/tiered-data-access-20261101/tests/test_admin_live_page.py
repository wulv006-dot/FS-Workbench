import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_page import AdminLivePage, LivePageError

class LivePage(unittest.TestCase):
 def setUp(self):
  self.grant={'scope_hash':'configured-site-and-game','permission_epoch':'1','policy_version':'v1'};self.calls=[]
  self.req=dict(site_id='266',game_id='1327',start='2026-10-29',end_exclusive='2026-10-30',fields=['order_id','paid_at','status'])
  self.row=dict(id=123,site_id=266,gid=1327,paytime='2026-10-29 11:12:13',status='11',email='fixture@example.test')
  def fetch(path,params,timeout,cap):self.calls.append((path,params,timeout,cap));return 200,json.dumps({'code':1,'data':{'total':1,'list':[self.row]}}).encode()
  self.fetch=fetch;self.adapter=AdminLivePage(fetch=fetch,authorize=lambda q:dict(self.grant),expected_grant=dict(self.grant),page_size=10,max_bytes=4096,timeout_seconds=5,observed_at=lambda:'2026-11-02T00:00:00Z')
 def test_first_page_is_explicit_partial_not_snapshot_and_drops_pii(self):
  result=self.adapter(self.req);self.assertEqual(result['status'],'partial');self.assertFalse(result['complete']);self.assertEqual(result['semantics'],'live_non_snapshot');self.assertIsNone(result['next_cursor']);self.assertEqual(result['observed_at'],'2026-11-02T00:00:00Z');self.assertEqual(result['data'][0]['order_id'],'123');self.assertNotIn('email',result['data'][0]);self.assertEqual(len(self.calls),1)
 def test_empty_is_observation_not_full_history_zero(self):
  self.adapter.fetch=lambda *a:(200,b'{"code":1,"data":{"total":0,"list":[]}}')
  result=self.adapter(self.req);self.assertEqual(result['status'],'partial');self.assertFalse(result['complete']);self.assertEqual(result['data'],[])
 def test_invalid_scope_fields_and_dates_fail_before_source(self):
  for change in (dict(site_id=''),dict(fields=['email']),dict(cursor='1'),dict(end_exclusive='2027-01-01'),dict(start=''),dict(start='2020-01-01',end_exclusive='2020-01-02'),dict(start='2026-11-04',end_exclusive='2026-11-05')):
   with self.subTest(change=change),self.assertRaises(LivePageError):self.adapter(dict(self.req,**change))
  self.assertEqual(self.calls,[])
 def test_authorization_revoked_after_call_never_returns_rows(self):
  def fetch(*a):self.grant['permission_epoch']='2';return self.fetch(*a)
  self.adapter.fetch=fetch
  with self.assertRaises(LivePageError) as e:self.adapter(self.req)
  self.assertEqual(e.exception.code,'permission_denied')
 def test_source_unavailable_and_scope_mismatch_are_not_empty(self):
  for status,code in ((401,'source_auth'),(429,'source_rate_limited')):
   self.adapter.fetch=lambda *a:(status,b'{}')
   with self.assertRaises(LivePageError) as e:self.adapter(self.req)
   self.assertEqual(e.exception.code,code)
  self.adapter.fetch=lambda *a:(_ for _ in ()).throw(TimeoutError())
  with self.assertRaises(LivePageError) as e:self.adapter(self.req)
  self.assertEqual(e.exception.code,'source_timeout')
  self.row['site_id']=999;self.adapter.fetch=self.fetch
  with self.assertRaises(LivePageError):self.adapter(self.req)
 def test_source_truncation_and_byte_cap(self):
  self.adapter.fetch=lambda *a:(200,b'x'*4097)
  with self.assertRaises(LivePageError):self.adapter(self.req)
  self.adapter.fetch=lambda *a:(200,b'{"code":1,"data":{"total":3,"list":[]}}')
  with self.assertRaises(LivePageError):self.adapter(self.req)

if __name__=='__main__':unittest.main(verbosity=2)
