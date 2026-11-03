import importlib.util,json,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'))
spec=importlib.util.spec_from_file_location('management_facts',ROOT/'source/management_facts.py');facts=importlib.util.module_from_spec(spec);spec.loader.exec_module(facts)

class NovemberTests(unittest.TestCase):
 def test_game_pages_name_and_month(self):
  c=json.loads((ROOT/'source/targets.json').read_text(encoding='utf8'))
  for g in c['overview']['games']:
   page=(ROOT/'source'/g['file']).read_text(encoding='utf8')
   self.assertIn('<h1 class="vh">'+g['name']+' KPI 驾驶舱</h1>',page)
   self.assertIn('11/1–11/30',page)
   self.assertNotIn('10 月',page);self.assertNotIn('10/1–10/31',page)
 def test_shipping_registration_uses_verified_order_ids(self):
  import types
  sys.modules.setdefault('rs_admin',types.SimpleNamespace(number=lambda x:float(x)))
  spec=importlib.util.spec_from_file_location('business_shipping',ROOT/'source/business_shipping.py');shipping=importlib.util.module_from_spec(spec);spec.loader.exec_module(shipping)
  from management_profiles import PROFILES
  for key,name,gid,game,group in PROFILES:
   self.assertEqual(shipping.selection({'profile':key})['gid'],str(gid))
  with self.assertRaises(ValueError):shipping.selection({'profile':'NOT_REGISTERED'})
 def test_targets_and_history(self):
  c=json.loads((ROOT/'source/targets.json').read_text(encoding='utf8'));old=json.loads((ROOT/'source/targets-2026-10.json').read_text(encoding='utf8'))
  self.assertEqual(c['period'],'2026-11');self.assertEqual(old['period'],'2026-10')
  games=c['overview']['games'];self.assertEqual(len(games),25);self.assertEqual(sum(g['tgt']['rev'] for g in games),2000680)
  self.assertEqual({grp:sum(g['tgt']['rev'] for g in games if g['grp']==grp) for grp in ('球类运营组','综合运营组','RPG运营组')},{'球类运营组':954300,'综合运营组':330500,'RPG运营组':715880})
  self.assertEqual(c['models']['COD_MW4']['sourceRow']['revenue_target_usd'],80000)
  self.assertTrue(all(g['tgt']['prof'] is None and g['tgt']['ord'] is None for g in games))
  self.assertEqual(next(g['tgt']['rev'] for g in games if g['profile']=='ODIN'),380)
  self.assertEqual(c['models']['GTA_5_6']['components'],['GTA5','GTA6'])
  self.assertTrue(all((ROOT/'source'/g['file']).is_file() for g in games))
 def test_complete_days(self):
  from datetime import date
  p=facts.periods(date(2026,11,3),'2026-11');self.assertEqual((p['observed'],p['month_days'],p['start'],p['end']),(2,30,'2026-11-01','2026-11-02'))
 def test_gta_sum_not_average(self):
  row=lambda rev,ord,prof:{'values':dict(rev=rev,ord=ord,prof=prof,new=None,mar=40,rep=90,ful=80,aov=999),'status':'available','freshness':'fresh','period':{'start':'2026-11-01','end':'2026-11-02'},'sources':{},'notes':{}}
  r=facts.aggregate_components([row(120,3,30),row(80,1,10)])
  self.assertEqual((r['values']['rev'],r['values']['ord'],r['values']['prof'],r['values']['aov']),(200,4,40,50))
  self.assertIsNone(r['values']['mar']);self.assertIsNone(r['values']['rep'])
  r=facts.aggregate_components([row(120,3,30),row(None,None,None)])
  self.assertIsNone(r['values']['rev']);self.assertIsNone(r['values']['ord'])

if __name__=='__main__':unittest.main()
