import datetime,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_page import AdminLivePage,LivePageError
from admin_live_dispatch import private_body_params,handle
from admin_live_worker import handle as worker
from test_admin_live_worker import Fake,valid_params

class CustomerLookup(unittest.TestCase):
 def setUp(self):
  self.grant={'scope_hash':'actor-site-game','permission_epoch':'e1','policy_version':'v1'};self.calls=[]
  self.query={'site_id':'266','game_id':'1327','start':'2026-10-01','end_exclusive':'2026-10-29','customer_email':'fixture@example.test','fields':['order_id','paid_at','status','pay_status','customer_email']}
  self.row={'id':100,'site_id':266,'gid':1327,'paytime':'2026-10-15 10:00:00','status':'11','pay_status':'1','email':'fixture@example.test'}
  def fetch(path,params,timeout,cap):
   self.calls.append(params)
   return 200,json.dumps({'code':1,'data':{'total':1,'list':[self.row]}}).encode()
  self.adapter=AdminLivePage(fetch=fetch,authorize=lambda q:dict(self.grant),expected_grant=self.grant,page_size=20,max_bytes=4096,timeout_seconds=5,observed_at=lambda:'2026-11-02T00:00:00Z',cursor_key=b'a'*32)
 def test_exact_email_is_fixed_filter_and_not_claimed_first(self):
  result=self.adapter(self.query);p=self.calls[0]
  self.assertEqual((p['search[3][field]'],p['search[3][operator]'],p['search[3][val]']),('email','=','fixture@example.test'))
  self.assertEqual(result['data'][0]['customer_email'],'fixture@example.test');self.assertFalse(result['complete'])
  self.assertNotIn('first_purchase',result)
 def test_mismatching_source_email_fails_closed(self):
  self.row['email']='someone-else@example.test'
  with self.assertRaises(LivePageError) as e:self.adapter(self.query)
  self.assertEqual(e.exception.code,'source_filter_mismatch')
 def test_customer_filter_requires_private_fields_before_io(self):
  with self.assertRaises(LivePageError):self.adapter(dict(self.query,fields=[]))
  self.assertEqual(self.calls,[])
 def test_request_body_is_bounded_and_has_no_extra_filters(self):
  body={k:v for k,v in self.query.items() if k!='fields'}
  params=private_body_params(json.dumps(body).encode());self.assertEqual(params['customer_email'],['fixture@example.test'])
  for invalid in (dict(body,extra='x'),dict(body,customer_email='x\r\ny'),dict(body,customer_email='*')):
   with self.assertRaises(ValueError):private_body_params(json.dumps(invalid).encode())
  with self.assertRaises(ValueError):private_body_params(b'x'*4097)
  with self.assertRaises(ValueError):private_body_params(b'{"site_id":"1","site_id":"2"}')
 def test_ordinary_viewer_cannot_filter_private_email(self):
  body={k:[v] for k,v in self.query.items() if k!='fields'}
  status,_=handle(body,'staff',authorize_for_user=lambda user:lambda q:dict(self.grant),fetch=self.adapter.fetch,enabled=True,select_fields=lambda q:[])
  self.assertEqual(status,403);self.assertEqual(self.calls,[])
 def test_worker_accepts_only_fixed_email_equality_filter(self):
  params=valid_params()
  for k,v in (('field','email'),('operator','='),('val','fixture@example.test')):params['search[3][%s]'%k]=v
  Fake.calls=[];result=worker({'path':'/admin/order.Order/index','params':params,'max_bytes':4096},lambda:Fake,today=lambda:datetime.date(2026,11,2))
  self.assertEqual(result['status'],200)
  params['search[3][operator]']='LIKE'
  with self.assertRaises(ValueError):worker({'path':'/admin/order.Order/index','params':params,'max_bytes':4096},lambda:Fake,today=lambda:datetime.date(2026,11,2))

if __name__=='__main__':unittest.main()
