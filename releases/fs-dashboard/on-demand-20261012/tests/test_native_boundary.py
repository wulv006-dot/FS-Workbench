import hashlib, importlib.util, json, sys, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import test_range
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_boundary',ROOT/'native-boundary/source/range_api.py')
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)

class Clock(datetime):
 value=datetime(2026,10,12,13,1,tzinfo=timezone(timedelta(hours=8)))
 @classmethod
 def now(cls,*args):return cls.value

class Boundary(unittest.TestCase):
 def setUp(self):
  self.p={'profile':['FC27'],'start':['2026-10-01'],'end':['2026-10-12'],'grain':['day'],'snapshotId':['catalog-0123456789abcdef'],'analysis':['fc27-categories'],'until':['2026-10-12 13:00']}
  self.catalog={'snapshotId':'catalog-0123456789abcdef','catalogId':'catalog-0123456789abcdef'}
 def test_source_summary_boundary_is_stable_across_poll_minutes(self):
  with patch.object(api,'datetime',Clock):
   Clock.value=datetime(2026,10,12,13,1,tzinfo=timezone(timedelta(hours=8)));a=api.query(self.p,self.catalog)
   Clock.value+=timedelta(minutes=2);b=api.query(self.p,self.catalog)
  self.assertEqual(a,b);self.assertEqual(a['period']['end'],'2026-10-12 13:00')
  self.assertEqual(hashlib.sha256(api.encoded(a)).hexdigest(),hashlib.sha256(api.encoded(b)).hexdigest())
 def test_future_partial_historical_and_non_analysis_boundaries_rejected(self):
  for change in [{'until':['2026-10-12 23:59']},{'until':['2026-10-11 10:00']},{'analysis':['other']},{'profile':['RS']}]:
   with patch.object(api,'datetime',Clock),self.assertRaises(ValueError):api.query({**self.p,**change},self.catalog)
  p={**self.p,'end':['2026-10-11'],'until':['2026-10-11 10:00']}
  with patch.object(api,'datetime',Clock),self.assertRaises(ValueError):api.query(p,self.catalog)
 def test_historical_whole_period_and_existing_requests_unchanged(self):
  p={**self.p,'end':['2026-10-11'],'until':['2026-10-12 00:00']}
  with patch.object(api,'datetime',Clock):q=api.query(p,self.catalog)
  p.pop('until')
  with patch.object(api,'datetime',Clock):old=api.query(p,self.catalog)
  self.assertEqual(q['period'],old['period']);self.assertNotIn('until',old)
 def test_frontend_uses_financial_period_and_exact_one_file_publisher(self):
  text=(ROOT/'entry-native-boundary-final/frontend/assets/business.js').read_text(encoding='utf-8')
  self.assertIn("query.set('until',period.end)",text)
  self.assertNotIn('cutoff=INSIGHTS_SNAPSHOT?.profiles?.[key]?.period?.end',text)
  conf=(ROOT/'entry-native-boundary-final/frontend/candidate/formal.conf').read_text(encoding='utf-8')
  block=conf.split('location = /s/wulv/fc27-ops/ {',1)[1].split('}',1)[0]
  self.assertNotIn('alias ',block)
  self.assertIn('rewrite ^ /s/wulv/fc27-ops/index.html last;',conf)
  self.assertIn('auth_request /__fc27_verify;',conf)
  sys.path.insert(0,str(ROOT/'native-boundary'))
  spec=importlib.util.spec_from_file_location('boundary_publisher',ROOT/'native-boundary/release_navigation.py');publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
  self.assertEqual(publisher.expected_files({'scope':publisher.BOUNDARY_SCOPE}),{'live/range_api.py'})

if __name__=='__main__':unittest.main()
