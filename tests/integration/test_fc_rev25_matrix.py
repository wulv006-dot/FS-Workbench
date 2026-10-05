"""Actual Python/JS quote + Python write-gate with dedicated rev25 synthetic vectors. No writer runs."""
import copy,importlib.util,json,os,socket,subprocess,sys,unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'fc27_cloud_browser'),str(ROOT/'tools')]
import fc27_quote_engine as engine
import automation_policy as gates
import fc_migration_contract as migration

class Rev25Matrix(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  fixtures=json.loads((ROOT/'docs/fc27-coins/discount-config-release-20261005/tests/audit-vectors.json').read_text(encoding='utf-8'))['cases']
  cls.rules=engine.normalize_discount_rules({'schema_version':1,'bands':{k:dict(zip(('min_discount_pct','max_discount_pct'),v)) for k,v in migration.APPROVED_BANDS.items()}})
  cls.policy={**gates.initial_policy(),'revision':25,'schedule_revision':23,'system_enabled':True,'mode':'auto','pricing_rules':cls.rules}
  cls.edits={'minimum_gross_margin_pct':'10','pricing_rules':cls.rules}
  cls.cases=copy.deepcopy(fixtures)
  for name,price in [('rev25_min6','99.00'),('rev25_max8','1.00')]:
   item=copy.deepcopy(next(x for x in fixtures if x['name']=='average3'));item['name']=name
   for platform in engine.PLATFORMS:
    for site in ('U4GM','IGGM'):item['evidence']['offers'][platform][site]['usd_price']=price
   cls.cases.append(item)
  cls.py=[engine.calculate(x['evidence'],cls.edits) for x in cls.cases]
  # The only child process is this reviewed pure preview. No servers, subprocess writers or production calls.
  result=subprocess.run(['node',str(Path(__file__).with_name('fc_rev25_preview.cjs'))],
    input=json.dumps([{'evidence':x['evidence'],'edits':cls.edits} for x in cls.cases]),text=True,
    capture_output=True,timeout=20,encoding='utf-8')
  if result.returncode:raise AssertionError('Pure Node quote comparison failed: '+result.stderr[:1000])
  cls.js=json.loads(result.stdout)
 def quote(self,item,result):
  return {'automation_policy_revision':25,'pricing_rules_schema_version':1,'pricing_rules':self.rules,
          'pricing_rules_sha256':engine.discount_rules_sha256(self.rules),'evidence':item['evidence'],
          'edits':self.edits,'result':result}
 def test_real_python_js_same_price_and_band_decisions(self):
  fields=('platform','proposal','auto_proposal','floor_usd_per_1k','target_page_usd','requested_discount_pct',
          'pricing_tier','auto_blocked_reason','margin_below_minimum','cost_cny','own_bonus_k','auto_price_source')
  for item,py,js in zip(self.cases,self.py,self.js):
   for a,b in zip(py['rows'],js['rows']):
    with self.subTest(case=item['name'],platform=a['platform']):
     self.assertEqual({k:a.get(k) for k in fields},{k:b.get(k) for k in fields})
 def test_exact_three_thresholds_both_sides_four_bands(self):
  expected={'exact40':'at_least_40','just_below40':'30_to_40','exact30':'30_to_40',
            'just_below30':'20_to_30','exact20':'20_to_30','just_below20':'below_20'}
  for item,result in zip(self.cases,self.py):
   if item['name'] in expected:self.assertEqual(result['rows'][0]['pricing_tier'],expected[item['name']])
  self.assertEqual(set(expected.values()),set(migration.APPROVED_BANDS))
 def test_actual_requested_discounts_approved_bounds_and_clips(self):
  for item,result in zip(self.cases,self.py):
   for row in result['rows']:
    if row.get('requested_discount_pct') is None:continue
    low,high=migration.APPROVED_BANDS[row['pricing_tier']]
    self.assertLessEqual(Decimal(low),Decimal(row['requested_discount_pct']));self.assertLessEqual(Decimal(row['requested_discount_pct']),Decimal(high))
   if item['name']=='rev25_min6':self.assertEqual(result['rows'][0]['requested_discount_pct'],'6.00')
   if item['name']=='rev25_max8':self.assertEqual(result['rows'][0]['requested_discount_pct'],'8.00')
 def test_automatic_gate_accepts_feasible_and_rejects_cost_blocked(self):
  accepted=blocked=0
  for item,result in zip(self.cases,self.py):
   for row in result['rows']:
    if row.get('missing') or row.get('margin_below_minimum') or row.get('auto_blocked_reason'):
     with self.assertRaises(ValueError):gates.check_write(self.policy,self.quote(item,result),[row['platform']],automatic=True)
     blocked+=1
    else:
     self.assertEqual(gates.check_write(self.policy,self.quote(item,result),[row['platform']],automatic=True),[]);accepted+=1
  self.assertGreater(accepted,0);self.assertGreater(blocked,0)
 def test_xbox_follows_ps_but_cost_floor_denies_write(self):
  index=next(i for i,x in enumerate(self.cases) if x['name']=='xbox_floor_blocks_follow')
  result=self.py[index];ps,xbox=result['rows'][:2]
  self.assertEqual(xbox['proposal'],ps['proposal']);self.assertEqual(xbox['auto_price_source'],'PS')
  self.assertTrue(xbox['margin_below_minimum'])
  with self.assertRaises(ValueError):gates.check_write(self.policy,self.quote(self.cases[index],result),['XBOX'],automatic=True)
 def test_revision_hash_rules_and_price_tampering_deny(self):
  item,result=self.cases[0],self.py[0];q=self.quote(item,result)
  for field,value in [('automation_policy_revision',24),('pricing_rules_sha256','0'*64),('pricing_rules_schema_version',2),('pricing_rules',engine.default_discount_rules())]:
   bad=copy.deepcopy(q);bad[field]=value
   with self.assertRaises(ValueError):gates.check_write(self.policy,bad,['PS'],automatic=True)
  bad=copy.deepcopy(q);row=bad['result']['rows'][0];row['proposal']='1.0000';row['target_page_usd']='100.00'
  with self.assertRaises(ValueError):gates.check_write(self.policy,bad,['PS'],automatic=True)
  for band in migration.APPROVED_BANDS:
   bad=copy.deepcopy(self.policy);bad['pricing_rules']['bands'][band]['max_discount_pct']='9.00'
   with self.assertRaises(ValueError):migration.validate_policy_migration(bad)

if __name__=='__main__':
 with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')):
  result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 print(json.dumps({'run':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'scope':'16 synthetic cases; actual Python/JS quotes and Python check_write only; no save/writer/timer/production'}))
 sys.exit(not result.wasSuccessful())
