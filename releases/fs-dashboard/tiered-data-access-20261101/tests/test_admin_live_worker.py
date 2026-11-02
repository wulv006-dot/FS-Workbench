import base64,datetime,io,json,sys,unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_worker import handle
def valid_params():
 value={'page':1,'limit':10,'order':'id,desc','search[2][render]':'datetime'}
 for i,(field,op,val) in enumerate((('site_id','=','266'),('gid','=','1327'),('paytime','RANGE','2026-10-01 00:00:00,2026-10-02 23:59:59'))):
  for k,v in (('field',field),('operator',op),('val',val)):value['search[%d][%s]'%(i,k)]=v
 return value

class Response:
 def __init__(self,body):self.body=body;self.status=200
 def read(self,n):return self.body[:n]
 def __enter__(self):return self
 def __exit__(self,*args):pass
class Fake:
 HEADERS={'Accept':'application/json'};API_BASES=('http://127.0.0.1:8912',)
 calls=[];body=b'{"code":1}'
 class SessionManager:
  def __init__(self,config):self.config={};self.opener=self
  def open(self,req,timeout):Fake.calls.append((req,timeout));return Response(Fake.body)
 @staticmethod
 def api_base(config):return 'http://127.0.0.1:8912'

class TestWorker(unittest.TestCase):
 def setUp(self):Fake.calls=[];Fake.body=b'{"code":1}';self.payload={'path':'/admin/order.Order/index','params':valid_params(),'max_bytes':4096}
 def test_one_fixed_page_over_shared_hmac_proxy(self):
  value=handle(self.payload,lambda:Fake);self.assertEqual(value['status'],200);self.assertEqual(base64.b64decode(value['body']),Fake.body);self.assertEqual(len(Fake.calls),1)
 def test_rejects_wrong_endpoint_search_or_extra_data_without_network(self):
  for change in ({'path':'http://evil.invalid'},{'max_bytes':0},{'unknown':'x'}):
   with self.subTest(change=change),self.assertRaises(ValueError):handle(dict(self.payload,**change),lambda:Fake)
  params=valid_params();params['search[0][field]']='email'
  with self.assertRaises(ValueError):handle(dict(self.payload,params=params),lambda:Fake)
  self.assertEqual(Fake.calls,[])
 def test_source_response_cap_is_enforced(self):
  Fake.body=b'x'*4097
  with self.assertRaises(ValueError):handle(self.payload,lambda:Fake)
 def test_bad_or_unexpected_proxy_denied(self):
  class Wrong(Fake):
   @staticmethod
   def api_base(config):return 'http://127.0.0.1:9999'
  with self.assertRaises(ValueError):handle(self.payload,lambda:Wrong)
  self.assertEqual(Fake.calls,[])
 def test_worker_rejects_window_that_expired_after_midnight(self):
  params=valid_params();params['search[2][val]']='2025-11-02 00:00:00,2025-11-02 23:59:59'
  with self.assertRaises(ValueError):handle(dict(self.payload,params=params),lambda:Fake,today=lambda:datetime.date(2026,11,3))
  self.assertEqual(Fake.calls,[])
 def test_worker_rechecks_after_session_setup_immediately_before_io(self):
  params=valid_params();params['search[2][val]']='2025-11-02 00:00:00,2025-11-02 23:59:59'
  dates=iter((datetime.date(2026,11,2),datetime.date(2026,11,3)))
  with self.assertRaises(ValueError):handle(dict(self.payload,params=params),lambda:Fake,today=lambda:next(dates))
  self.assertEqual(Fake.calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
