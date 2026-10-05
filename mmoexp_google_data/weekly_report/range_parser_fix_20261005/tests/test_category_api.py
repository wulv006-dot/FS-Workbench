import unittest,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
import test_range_api as fixture
api=fixture.api
from test_category_contract import record,TYPES

def params(**extra):return fixture.params(**{'profile':'FC27','analysis':'fc27-categories',**extra})
def source(period,tid):
 r=record(tid,20,200,-7 if tid=='2' else 25);r['period']=period;return r
class Tests(unittest.TestCase):
 def setUp(self):api.JOBS.clear();api.STARTS.clear()
 def test_normal_contract_identical(self):
  q=api.query(fixture.params(),fixture.data);self.assertNotIn('analysis',q)
  self.assertEqual(set(q),{'profile','start','end','grain','baseSnapshotId','period'})
 def test_analysis_profile_and_values_whitelist(self):
  for x in [fixture.params(analysis='fc27-categories'),params(analysis='anything'),params(grain='hour'),params(tid='4')]:
   with self.assertRaises(ValueError):api.query(x,fixture.data)
 def test_distinct_cache_namespace(self):
  p=params();normal=dict(p);normal.pop('analysis')
  self.assertNotEqual(hashlib.sha256(api.encoded(api.query(p,fixture.data))).hexdigest(),hashlib.sha256(api.encoded(api.query(normal,fixture.data))).hexdigest())
 def test_native_category_capture_and_margin(self):
  q=api.query(params(),fixture.data)
  def call(container,script,requests,timeout):
   self.assertEqual(script,'fc_category_reader.py');self.assertEqual(len(requests),4);self.assertEqual(timeout,200)
   return {r['key']:source(q['period'],r['tid']) for r in requests}
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'WEB',Path(t)),patch.object(api,'snapshot',return_value=fixture.data),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'existing_call',side_effect=call):
   api.capture(q,'fixture');result=json.loads((Path(t)/'fixture.json').read_text(encoding='utf-8'));self.assertEqual(result['fc27Analytics']['categories'][1]['profitMarginPct'],-7);self.assertNotIn('profile',result);self.assertEqual(result['fc27Analytics']['period'],q['period'])
 def test_partial_failure_never_cached_as_success(self):
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'WEB',Path(t)),patch.object(api,'snapshot',return_value=fixture.data),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'existing_call',return_value={'all':{'status':'unavailable'}}):
   api.capture(api.query(params(),fixture.data),'fixture');self.assertFalse((Path(t)/'fixture.json').exists());self.assertEqual(api.JOBS['fixture']['error'],'native_category_read_failed')
 def test_base_changed_during_capture_not_published(self):
  q=api.query(params(),fixture.data);changed={**fixture.data,'snapshotId':'new'}
  records={key:source(q['period'],tid) for key,tid in [('all','')]+[(k,t) for k,t,_ in TYPES]}
  with tempfile.TemporaryDirectory() as t,patch.object(api,'CACHE',Path(t)),patch.object(api,'WEB',Path(t)),patch.object(api,'snapshot',side_effect=[fixture.data,changed]),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'existing_call',return_value=records):
   api.capture(q,'fixture');self.assertFalse((Path(t)/'fixture.json').exists());self.assertEqual(api.JOBS['fixture']['error'],'base_snapshot_changed')
 def test_anonymous_and_write_handler_preserved(self):
  handler=object.__new__(api.Handler);handler.path='/range';handler.headers={};out=[];handler.reply=lambda s,d:out.append(s)
  handler.do_GET();self.assertEqual(out[-1],401)
  for method in ['do_POST','do_PUT','do_PATCH','do_DELETE']:getattr(handler,method)();self.assertEqual(out[-1],405)
if __name__=='__main__':unittest.main()
