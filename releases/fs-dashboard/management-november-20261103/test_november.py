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

class QueryRetryTests(unittest.TestCase):
 def reply(self):
  period={'start':'2026-11-01 00:00','end':'2026-11-09 00:00'}
  metric=lambda value,unit:{'status':'available','value':value,'unit':unit}
  admin={'status':'available','normalisedScope':'all-websites','period':period,
   'filters':{'site':'','date':list(period.values()),'pay_status':1,'order_status':''},
   'metrics':{'revenueUsd':metric(2831.95,'USD'),'orders':metric(82,'orders'),'newCustomers':metric(27,'people')}}
  order={'status':'available','normalisedScope':'all-websites','period':period,'currency':'USD','metrics':{'profitMarginPct':metric(25,'percent')}}
  return {'http_status':200,'body':{'status':'available','scopeContractId':facts.SOURCE_CONTRACT,
   'query':{'profile':'WOW_FOREVER','start':'2026-11-01','end':'2026-11-08','timezone':'Asia/Shanghai','period':period},
   'sources':{'Admin':{'status':'available'},'Order':{'status':'available'}},
   'profile':{'key':'WOW_FOREVER','supplement':admin,'primary':order}}}
 def call(self,replies,deadline=12,required=('rev','ord','prof')):
  self.elapsed=0;self.calls=0;self.sleeps=[]
  sequence=iter(replies)
  def reader(path):
   self.calls+=1
   self.assertIn('profile=WOW_FOREVER',path)
   return next(sequence)
  def sleep(seconds):
   self.sleeps.append(seconds);self.elapsed+=seconds
  return facts.read_query(reader,'WOW_FOREVER','2026-11-01','2026-11-08',deadline,required=required,sleep=sleep,monotonic=lambda:self.elapsed)
 def test_contract_mismatch_recovers_with_real_projection(self):
  for kind in ('source','admin'):
   with self.subTest(kind=kind):
    bad=self.reply()
    if kind=='source':bad['body']['scopeContractId']='wrong'
    else:bad['body']['profile']['supplement']['filters']['site']='MMOEXP'
    row=self.call([bad,self.reply()])
    self.assertEqual((row['values']['rev'],row['values']['ord'],row['values']['new']),(2831.95,82,27))
    self.assertEqual(self.calls,2);self.assertEqual(self.sleeps,[5])
 def test_persistent_mismatch_preserves_error_and_bounds(self):
  for error in ('source_contract_mismatch','admin_all_sites_contract_mismatch'):
   for deadline,bound,count in ((12,12,3),(1000,100,20)):
    with self.subTest(error=error,deadline=deadline):
     bad=self.reply()
     if error=='source_contract_mismatch':bad['body']['scopeContractId']='wrong'
     else:bad['body']['profile']['supplement']['filters']['site']='MMOEXP'
     with self.assertRaisesRegex(ValueError,'^'+error+'$'):self.call([bad]*count,deadline)
     self.assertEqual(self.elapsed,bound);self.assertEqual(self.calls,count)
 def test_denied_is_immediate(self):
  for code in (401,403):
   with self.subTest(code=code):
    with self.assertRaisesRegex(ValueError,'^source_denied$'):self.call([{'http_status':code}])
    self.assertEqual(self.calls,1);self.assertEqual(self.sleeps,[])
 def test_unexpected_value_error_is_immediate(self):
  from unittest.mock import patch
  with patch.object(facts,'project_summary',side_effect=ValueError('invalid_metric')):
   with self.assertRaisesRegex(ValueError,'^invalid_metric$'):self.call([self.reply()])
  self.assertEqual(self.calls,1);self.assertEqual(self.sleeps,[])
 def test_pending_recovers(self):
  row=self.call([{'http_status':202},self.reply()])
  self.assertEqual(row['values']['ord'],82);self.assertEqual(self.calls,2)
 def test_valid_partial_survives_later_mismatch(self):
  partial=self.reply();partial['body']['profile']['primary']['status']='pending'
  bad=self.reply();bad['body']['scopeContractId']='wrong'
  row=self.call([partial,bad,bad])
  self.assertEqual(row['values']['rev'],2831.95);self.assertIsNone(row['values']['prof'])
  self.assertEqual(row['status'],'partial')

class ConfigPreservationTests(unittest.TestCase):
 def collect(self,components,**config):
  from datetime import datetime
  from unittest.mock import patch
  targets=json.loads((ROOT/'source/targets.json').read_text(encoding='utf8'))
  targets['overview']['games']=[g for g in targets['overview']['games'] if g['profile']=='WOW_FOREVER']
  targets['models']['WOW_FOREVER'].update(components=components,**config)
  self.row={'values':dict.fromkeys(facts.METRICS,10),'status':'available','freshness':'fresh','period':{'start':'2026-11-01','end':'2026-11-01'},'sources':{'Admin':{'status':'available'}},'notes':{'original':True}}
  with patch.object(facts,'read_query',return_value=self.row) as query:
   result=facts.collect(datetime(2026,11,2,tzinfo=facts.SH),targets,None)
  self.profiles=[call.args[1] for call in query.call_args_list]
  return result['projects'][0]
 def test_unbound_does_not_query_profile(self):
  result=self.collect([])
  self.assertEqual(result['month']['error'],'source_unbound')
  self.assertNotIn('WOW_FOREVER',self.profiles)
 def test_self_binding_reads_source_without_recursion(self):
  result=self.collect(['WOW_FOREVER'])
  self.assertIs(result['month'],self.row)
  self.assertIn('WOW_FOREVER',self.profiles)
 def test_single_source_preserves_original_fields(self):
  result=self.collect(['GTA5'])
  self.assertIs(result['month'],self.row)
  self.assertNotIn('WOW_FOREVER',self.profiles)
 def test_binding_key_and_disabled_forecast(self):
  result=self.collect(['GTA5'],bindingKey='binding-test',forecast_enabled=False)
  self.assertEqual(result['bindingKey'],'binding-test')
  self.assertTrue(all(value is None for value in result['forecast'].values()))

if __name__=='__main__':unittest.main()
