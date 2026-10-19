import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'releases/fs-dashboard/traffic-hermes-20261017/source'
sys.path[:0]=[str(SOURCE),str(Path(__file__).parent)]
spec=importlib.util.spec_from_file_location('game_range_api',SOURCE/'range_api.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
class GameCache(unittest.TestCase):
 def test_old_contract_refreshes_but_retains_history(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(api,'CACHE',Path(folder)):
   old=dict(status='available',start='2026-10-17',end='2026-10-17',period={'rule_version':api.RULE_VERSION})
   api.save_cache(old['start'],old['end'],old)
   self.assertIsNone(api.cached(old['start'],old['end']))
   self.assertIsNotNone(api.cached(old['start'],old['end'],allow_stale=True))
   newer={**old,'period':{**old['period'],'game_projection_version':api.GAME_VERSION}}
   api.save_cache(old['start'],old['end'],newer)
   self.assertIsNotNone(api.cached(old['start'],old['end']))
   self.assertEqual(len(list((Path(folder)/'versions').iterdir())),2)
 def test_custom_range_includes_country(self):
  from custom_range import collect
  calls=[]
  class R:
   def ga_fields(self):pass
   def ads_metadata(self,c):pass
   def ads(self,c,n,s,e):calls.append(n);return {'rows':[]}
  collect('2026-10-17','2026-10-17',R(),lambda *a:{},[],[],['1430398974'])
  self.assertIn('country_campaign',calls)
if __name__=='__main__':unittest.main()
