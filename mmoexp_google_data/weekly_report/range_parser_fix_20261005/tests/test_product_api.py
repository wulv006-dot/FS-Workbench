import unittest,tempfile,json,hashlib,copy
from pathlib import Path
from unittest.mock import patch
import test_range_api as fixture
api=fixture.api
from fc_product_contract import CONTRACT
def params(**extra):return fixture.params(**{'profile':'FC27','analysis':'fc27-products',**extra})
def extension(period):return {'contractId':CONTRACT,'status':'available','period':period,'rows':[{'productId':'123','nativeSales':'25','nativeGroupOrderCount':10}],'coverage':{'complete':True}}
class ProductAPI(unittest.TestCase):
 def setUp(self):api.JOBS.clear();api.STARTS.clear()
 def test_contract_period_caps_and_cache_distinct(self):
  q=api.query(params(),fixture.data);self.assertEqual(q['period']['end'],'2026-10-01 00:00')
  for analysis in ['fc27-categories',None]:
   p=params();p.pop('analysis') if analysis is None else p.update(analysis=[analysis]);self.assertNotEqual(api.encoded(q),api.encoded(api.query(p,fixture.data)))
 def test_products_only_fc_day(self):
  for kw in [{'profile':'D4'},{'grain':'hour'},{'analysis':'products'}]:
   with self.assertRaises(ValueError):api.query(params(**kw),fixture.data)
 def test_capture_pins_source_and_no_money(self):
  q=api.query(params(),fixture.data)
  def read(container,script,requests,timeout):
   self.assertEqual(container,'fc27-p2pah-session');self.assertEqual(script,'fc_product_reader.py');self.assertEqual(timeout,75);self.assertEqual(requests,[{'key':'range',**q['period']}]);return {'range':extension(q['period'])}
  with tempfile.TemporaryDirectory() as t,patch.object(api,'WEB',Path(t)),patch.object(api,'CACHE',Path(t)),patch.object(api,'snapshot',return_value=fixture.data),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'existing_call',side_effect=read),patch.object(api,'call') as core:
   api.capture(q,'p');v=json.loads((Path(t)/'p.json').read_text(encoding='utf-8'));self.assertEqual(v['baseSnapshotId'],fixture.data['snapshotId']);self.assertEqual(v['clientCheckSeconds'],60);self.assertNotIn('currency',v);self.assertNotIn('profile',v);core.assert_not_called()
 def test_partial_and_wrong_period_fail_not_publish(self):
  q=api.query(params(),fixture.data)
  for bad in [{'status':'unavailable'},extension({'start':'wrong','end':'wrong'}),{**extension(q['period']),'coverage':{'complete':False}}]:
   with tempfile.TemporaryDirectory() as t,patch.object(api,'WEB',Path(t)),patch.object(api,'CACHE',Path(t)),patch.object(api,'snapshot',return_value=fixture.data),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'existing_call',return_value={'range':bad}):
    api.capture(q,'p');self.assertFalse((Path(t)/'p.json').exists());self.assertEqual(api.JOBS['p']['error'],'native_product_read_failed')
 def test_version_changed_during_read_fails(self):
  q=api.query(params(),fixture.data)
  with tempfile.TemporaryDirectory() as t,patch.object(api,'WEB',Path(t)),patch.object(api,'CACHE',Path(t)),patch.object(api,'snapshot',side_effect=[fixture.data,{**fixture.data,'snapshotId':'new'}]),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'existing_call',return_value={'range':extension(q['period'])}):
   api.capture(q,'p');self.assertFalse((Path(t)/'p.json').exists());self.assertEqual(api.JOBS['p']['error'],'base_snapshot_changed')
 def test_no_capture_near_timer_boundary(self):
  with patch.object(api,'timer_seconds',return_value=60),patch.object(api,'existing_call') as call:
   api.capture(api.query(params(),fixture.data),'p');call.assert_not_called();self.assertEqual(api.JOBS['p']['error'],'scheduled_collection_due')
 def test_deduplicated_range_jobs(self):
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'snapshot',return_value=fixture.data),patch.object(api.POOL,'submit') as submit:
   for i in range(10):self.assertEqual(api.get_range(params())[0],202)
   self.assertEqual(submit.call_count,1)
 def test_anonymous_and_write_gate_preserved(self):
  h=object.__new__(api.Handler);h.path='/range';h.headers={};out=[];h.reply=lambda s,d:out.append(s);h.do_GET();self.assertEqual(out[-1],401)
  for name in ['do_POST','do_PUT','do_PATCH','do_DELETE']:getattr(h,name)();self.assertEqual(out[-1],405)
if __name__=='__main__':unittest.main()
