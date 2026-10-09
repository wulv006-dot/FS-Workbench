import ast,concurrent.futures,importlib.util,json,sys,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
ROOT=Path(__file__).resolve().parent
REPO=next(p for p in ROOT.parents if (p/'registration_approval_runtime_v3_20261006').is_dir())
sys.path.insert(0,str(ROOT))
import admin_links as admin,custom_range as ranges,range_api as api

class BackendTests(unittest.TestCase):
 def tearDown(self):api.JOBS.clear();api.BUSY=None
 def test_date_boundaries(self):
  self.assertEqual(('2026-10-01','2026-10-08'),ranges.validate('2026-10-01','2026-10-08'))
  ranges.validate('2026-01-01','2027-01-01')
  for start,end in [('2026-10-08','2026-10-01'),('2026-2-01','2026-02-02'),('2026-02-30','2026-03-01'),('2026-01-01','2027-01-02')]:
   with self.assertRaises(ValueError):ranges.validate(start,end)
 def test_number_missing_zero_and_bad(self):
  self.assertEqual(0,admin.number('0',True));self.assertEqual(1234.5,admin.number('1,234.50'))
  for value in (None,True,'NaN','Infinity','-1','bad'):self.assertIsNone(admin.number(value))
  self.assertIsNone(admin.number('1.5',True))
 def test_member_query_and_units(self):
  calls=[]
  def request(path,**kw):calls.append((path,kw));return 200,json.dumps({'code':1,'data':{'data':{'register_total':0,'new_member_order_amount':'2.30'}}})
  value=admin.membership(request,'2026-10-01','2026-10-08')
  self.assertEqual(266,calls[0][1]['data']['site']);self.assertEqual(['2026-10-01 00:00:00','2026-10-08 23:59:59'],calls[0][1]['data']['date'])
  self.assertEqual(9,len(value['metrics']));self.assertEqual(0,value['metrics'][0]['value']);self.assertIsNone(value['metrics'][1]['value']);self.assertEqual('USD',value['metrics'][2]['unit'])
 def test_inventory_filters_and_privacy(self):
  row={'id':1,'title':'SYNTHETIC','code':'SYNTHETIC','count':0,'fetch_qty':3,'used_qty':1,'site':{'full_title':'www.mmoexp.com'},'member':{'email':'private@example.invalid'},'member_id':123,'ip':'private','order_no':'private','uid':123}
  def request(path,**kw):return 200,json.dumps({'code':1,'data':{'list':[row,dict(row,site={'full_title':'other.invalid'})],'total':100}})
  for kind in ('discount','coupon','usage'):
   value=admin.inventory(request,kind);self.assertEqual('partial',value['status']);self.assertEqual(1,len(value['rows']));self.assertEqual(100,value['totalAllSites'])
   raw=json.dumps(value);self.assertNotIn('private',raw);self.assertNotIn('member_id',raw);self.assertNotIn('order_no',raw)
 def test_failed_sources_do_not_become_zero(self):
  def request(*a,**kw):raise OSError('SENSITIVE_NOT_EXPORTED')
  value=admin.collect(request,'2026-10-01','2026-10-08')
  for key in ('membership','discount','coupon','usage'):self.assertEqual('unavailable',value[key]['status'])
  self.assertNotIn('SENSITIVE',json.dumps(value))
 def test_google_exact_range_and_metadata(self):
  class Reader:
   def __init__(self):self.calls=[];self.metadata=False
   def ga_fields(self):pass
   def ads_metadata(self,c):self.metadata=True
   def ga(self,n,s,e):self.calls.append(('ga',n,s,e));return {'rows':[]}
   def gsc(self,n,s,e):self.calls.append(('gsc',n,s,e));return {'rows':[]}
   def ads(self,c,n,s,e):assert self.metadata;self.calls.append(('ads',n,s,e));return {'rows':[]}
  reader=Reader()
  def model(s,e,reports):
   self.assertEqual(4,len(reports));self.assertTrue(all(r['start_date']==s and r['end_date']==e for r in reports.values()));return {'start':s,'end':e}
  value=ranges.collect('2026-10-01','2026-10-09',reader,model,{'total':[]},{'total':[]},{'customer':None})
  self.assertEqual('available',value['status']);self.assertEqual([],value['failures']);self.assertTrue(all(call[2:]==('2026-10-01','2026-10-09') for call in reader.calls))
 def test_single_worker_cache_and_busy(self):
  future=concurrent.futures.Future();calls=[]
  def submit(*args):calls.append(args);return future
  self.assertEqual(202,api.query('2026-10-01','2026-10-08',submit)[0]);self.assertEqual(202,api.query('2026-10-01','2026-10-08',submit)[0]);self.assertEqual(1,len(calls))
  self.assertEqual(429,api.query('2026-10-02','2026-10-08',submit)[0]);future.set_result({'status':'available'});self.assertEqual(200,api.query('2026-10-01','2026-10-08',submit)[0])
  self.assertEqual(1,len(calls))
 def test_completed_long_job_is_not_expired_on_first_poll(self):
  future=concurrent.futures.Future();future.set_result({'status':'available'})
  api.JOBS[('range','2026-10-01','2026-10-08')]={'future':future,'created':0}
  self.assertEqual(200,api.query('2026-10-01','2026-10-08')[0])
 def test_http_auth_bad_request_and_method(self):
  server=ThreadingHTTPServer(('127.0.0.1',0),api.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
  try:
   for path,headers,method,code in [('/range?start=2026-10-01&end=2026-10-08',{},'GET',401),('/range?start=2026-10-01&end=2026-10-08&cmd=1',{'X-Auth-User':'SYNTHETIC'},'GET',400),('/other',{},'GET',404),('/range',{},'POST',501)]:
    with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(urllib.request.Request(base+path,headers=headers,method=method))
    self.assertEqual(code,caught.exception.code);caught.exception.close()
  finally:server.shutdown();server.server_close();thread.join()
 def test_existing_session_methods_unchanged(self):
  def methods(path):
   return {node.name+'.'+method.name:ast.dump(method) for node in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(node,ast.ClassDef) for method in node.body if isinstance(method,ast.FunctionDef)}
  baseline=ROOT/'test-input/session-before.py'
  old=methods(baseline if baseline.exists() else REPO/'fc27_cloud_browser/p2pah_session_service.py');new=methods(ROOT/'service/p2pah_session_service.py')
  for name,value in old.items():
   if name!='Handler.do_GET':self.assertEqual(value,new[name],name)
  method=new['SessionManager.marketing_summary'];self.assertNotIn('ensure',method);self.assertNotIn('login',method)
 def test_registered_guard_precise_addition(self):
  original=REPO/'registration_account_management_20261009/source/runtime'
  if not original.exists():original=REPO/'releases/registration/account-management-20261009/source/runtime'
  base=REPO/'registration_approval_runtime_v3_20261006'
  sys.path[:0]=[str(original),str(original/'vendor'),str(base),str(base/'vendor')];spec=importlib.util.spec_from_file_location('traffic_auth',ROOT/'auth/runtime.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
  guard=runtime.RouteGuard(json.loads((ROOT/'auth/route-contract.json').read_text()))
  uri='/dashboard/marketing/range.json?start=2026-10-01&end=2026-10-08'
  self.assertTrue(guard.allowed('GET',uri,'dashboard'))
  for method,path,group in [('POST',uri,'dashboard'),('GET',uri+'&cmd=1','dashboard'),('GET',uri+'&start=2026-10-02','dashboard'),('GET',uri,'deploy'),('GET','/dashboard/marketing/other.json?start=2026-10-01','dashboard'),('GET','/dashboard/?start=2026-10-01','dashboard')]:self.assertFalse(guard.allowed(method,path,group))
  import module_permissions
  grants=dict(module_permissions.DEFAULT);grants['marketing']='none';self.assertFalse(module_permissions.permitted(guard,grants,'GET',uri,'dashboard'))
  grants['marketing']='readonly';self.assertTrue(module_permissions.permitted(guard,grants,'GET',uri,'dashboard'))
if __name__=='__main__':unittest.main(verbosity=2)
