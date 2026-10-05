"""Isolated contracts; no real sessions, HTTP services, source calls or account writes."""
import unittest,types,sys,json,importlib.util,tempfile,hashlib
from pathlib import Path
from datetime import timezone,timedelta
from unittest.mock import patch
collector=types.ModuleType('collector');collector.PROFILES=json.loads((Path(__file__).parent/'profiles.json').read_text(encoding='utf-8'))
collector.call=lambda *a:None;collector.dimensions=lambda p:{}
collector.profile_record=lambda k,n,p,s:{'key':k,'primary':p,'supplement':s,'period':p['period'],'metrics':{'orders':{'value':p['orders'],'source':'primary'},'revenueUsd':{'value':p['revenueUsd'],'source':'primary'},**p.get('metrics',{})}}
atomic=types.ModuleType('atomic_snapshot');atomic.SHANGHAI=timezone(timedelta(hours=8));atomic.encoded=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
sys.modules['collector']=collector;sys.modules['atomic_snapshot']=atomic
fcntl=types.ModuleType('fcntl');fcntl.LOCK_EX=1;fcntl.LOCK_NB=2;fcntl.flock=lambda *a:None;sys.modules['fcntl']=fcntl
ACTIVE_SOURCE=Path(__file__).resolve().parents[2]/'range_parser_release_20261005/source/range_api.py'
assert ACTIVE_SOURCE.read_bytes() == (Path(__file__).parent.parent/'candidate/range_api.py').read_bytes(), 'generated range mirror drift'
spec=importlib.util.spec_from_file_location('range_api',ACTIVE_SOURCE);api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
data={'snapshotId':'20261001T012140Z-0123456789abcdef','dashboard':{'profiles':{k:{'coverage':{'from':'2026-07-03'}} for k in [p[0] for p in collector.PROFILES]}},'profiles':{k:{'period':{'end':'2026-10-01 09:16'}} for k in [p[0] for p in collector.PROFILES]}}
def params(start='2026-09-29',end='2026-09-30',**extra):return {k:[v] for k,v in {'profile':'MMOEXP','start':start,'end':end,'snapshotId':data['snapshotId'],**extra}.items()}
class Tests(unittest.TestCase):
 def setUp(self):api.JOBS.clear();api.STARTS.clear()
 def test_closed_end_exclusive(self):self.assertEqual(api.query(params(),data)['period'],{'start':'2026-09-29 00:00','end':'2026-10-01 00:00'})
 def test_today_caps_published_cutoff(self):self.assertEqual(api.query(params('2026-10-01','2026-10-01'),data)['period']['end'],'2026-10-01 09:16')
 def test_fc_retained_verified_history(self):
  d=json.loads(json.dumps(data));d['fcOps']={'rows':[{'d':'2026-07-02','source_schema':3,'site':'all'}]}
  self.assertEqual(api.query(params('2026-07-02',profile='FC27'),d)['period']['start'],'2026-07-02 00:00')
  d['fcOps']['rows'][0]['site']='266'
  with self.assertRaises(ValueError):api.query(params('2026-07-02',profile='FC27'),d)
 def test_hour_inclusive_then_cap(self):self.assertEqual(api.query(params('2026-10-01 08:00','2026-10-01 09:00',grain='hour'),data)['period']['end'],'2026-10-01 09:16')
 def test_outside_ranges(self):
  for p in [params('2026-07-02'),params(end='2026-10-02'),params('2026-09-30','2026-09-29'),params('bad'),params(grain='minute')]:
   with self.assertRaises(ValueError):api.query(p,data)
 def test_stale_version(self):
  with self.assertRaises(LookupError):api.query(params(snapshotId='old'),data)
 def test_unknown_and_duplicate(self):
  with self.assertRaises(ValueError):api.query(params(site='266'),data)
  p=params();p['profile'].append('D4')
  with self.assertRaises(ValueError):api.query(p,data)
 def test_duplicate_requests_submit_once(self):
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'snapshot',return_value=data),patch.object(api.POOL,'submit') as submit:
   for _ in range(12):self.assertEqual(api.get_range(params())[0],202)
   self.assertEqual(submit.call_count,1)
 def test_native_people_and_margin_not_daily_sums(self):
  q=api.query(params(),data)
  primary={'period':q['period'],'orders':25,'revenueUsd':500,'metrics':{'averageOrderUsd':{'value':20},'profitMarginPct':{'value':-5}}}
  supplement={'period':q['period'],'status':'available','metrics':{'orders':{'value':20},'newCustomers':{'value':7},'newCustomerSharePct':{'value':35},'payingCustomers':{'value':13},'repeatRatePct':{'value':66.66}}}
  def native(container,*args):return {'range':primary if container=='fc27-cloud-browser' else supplement}
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'WEB',Path(t)),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'call',side_effect=native):
   api.capture(q,'fixture');result=json.loads((Path(t)/'fixture.json').read_text(encoding='utf-8'))
   self.assertEqual(result['profile']['metrics']['profitMarginPct']['value'],-5);self.assertEqual(result['profile']['supplement']['metrics']['payingCustomers']['value'],13)
   self.assertEqual(result['profile']['metrics']['orders']['value'],25);self.assertEqual(result['profile']['supplement']['metrics']['newCustomerSharePct']['value'],35)
 def test_primary_failure_never_replaced(self):
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'WEB',Path(t)),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'call',side_effect=RuntimeError('failed')):
   api.capture(api.query(params(),data),'fixture');self.assertEqual(api.JOBS['fixture']['status'],'unavailable');self.assertFalse((Path(t)/'fixture.json').exists())
 def test_preserve_natural_collection(self):
  with patch.object(api,'timer_seconds',return_value=100),patch.object(api,'call') as call:
   api.capture(api.query(params(),data),'fixture');self.assertEqual(api.JOBS['fixture']['error'],'scheduled_collection_due');call.assert_not_called()
 def test_rate_limit(self):
  api.STARTS[:]=[api.time.monotonic()]*6
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'snapshot',return_value=data):self.assertEqual(api.get_range(params())[0],429)
if __name__=='__main__':unittest.main()
