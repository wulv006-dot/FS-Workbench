import ast,copy,hashlib,json
from pathlib import Path
from decimal import Decimal
import sys,tempfile,unittest
SOURCE=Path(__file__).resolve().parents[1]/'source'
LEGACY=SOURCE.parents[1]/'fc-pricing-v2-20261022'
if not LEGACY.is_dir():LEGACY=SOURCE.parents[1]/'fc_reference_weighting_20261024'
sys.path[:0]=[str(SOURCE),str(LEGACY/'source'),str(LEGACY/'tests')]
import pricing_v2 as p
from test_pricing_v2 import fixture as base_fixture,NOW

def fixture(item='19.5',cost='.7'):
 e,rows,goods=base_fixture();e['run_id']='original'
 for r in e['costs'].values():r['cny_per_1k']=cost
 e['reference_market']=dict(status='available',run_id='original',offers=[dict(source='ItemD2R',platform=platform,run_id='original',status='valid',currency='USD',conditional=False,comparable=True,purchase_k='100',bonus_k='0',gross_usd=item,captured_at=NOW.isoformat(),url='https://www.itemd2r.com/ea-sports-fc/fc-27-coins') for platform in ('PS','XBOX','PC')])
 return e,rows

class OwnerPolicy(unittest.TestCase):
 def test_not_above_either_qualified_peer(self):
  for item in ('18','19.5','22'):
   e,rows=fixture(item);receipt=p.apply_decision(rows,e,{},now=NOW)
   cap=min(Decimal('20'),Decimal(item)*Decimal('1.05')).quantize(Decimal('.01'),rounding='ROUND_DOWN')
   for r in rows:self.assertLessEqual(Decimal(r['target_page_usd']),cap)
   self.assertEqual(receipt['position_policy_version'],p.POSITION_VERSION)
 def test_manual_or_hermes_cannot_exceed_ceiling(self):
  e,rows=fixture()
  with self.assertRaisesRegex(ValueError,'pricing_position_ceiling'):p.apply_decision(rows,e,{'quotes':{'PC':'.2001'}},now=NOW)
 def test_ceiling_rounds_down_not_up(self):
  e,rows=fixture('18.001');p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['position_ceiling_usd'],'18.90')
 def test_gift_normalization_allows_same_actual_unit(self):
  e,rows=fixture('19');p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['position_ceiling_usd'],'19.95')
 def test_missing_peer_does_not_fake_completeness(self):
  e,rows=fixture();e['reference_market']={'status':'unavailable','offers':[]}
  receipt=p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['auto_blocked_reason'],'pricing_position_peer_missing')
  self.assertEqual(receipt['decisions'][0]['position_status'],'missing_itemd2r')
 def test_floor_conflict_not_undersold(self):
  e,rows=fixture(cost='2');p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['auto_blocked_reason'],'pricing_position_floor_conflict')
  self.assertGreaterEqual(Decimal(rows[0]['proof']['catalog']['minimum_estimated_average_margin_pct']),10)
 def test_manual_price_below_floor_still_rejected(self):
  e,rows=fixture()
  with self.assertRaises(ValueError):p.apply_decision(rows,e,{'quotes':{'PS':'.01','XBOX':'.01'}},now=NOW)
 def test_40_warning_and_50_urgent_not_price_caps(self):
  for cost,level in (('.9','normal'),('.72','warning'),('.6','urgent')):
   e,rows=fixture(cost=cost);p.apply_decision(rows,e,{},now=NOW)
   self.assertEqual(rows[0]['margin_review']['level'],level)
   self.assertFalse(rows[0]['margin_review']['automatic_margin_cap'])
 def test_high_old_price_not_hidden_by_lower_new_margin(self):
  e,rows=fixture(cost='.7')
  for r in e['storefront']['rows'].values():r['package_usd']='40'
  p.apply_decision(rows,e,{},now=NOW);self.assertEqual(rows[0]['margin_review']['level'],'urgent')
 def test_old_confirmed_hold_cannot_beat_new_ceiling(self):
  e,rows=fixture();old=p.apply_decision(rows,e,{},now=NOW)
  e['previous_confirmed_decision']=dict(execution_id='old',receipt=old)
  for r in e['storefront']['rows'].values():r['package_usd']='20.17'
  receipt=p.apply_decision(rows,e,{},now=NOW)
  self.assertLessEqual(Decimal(receipt['decisions'][0]['model_unavailable_fallback_usd']),20)
 def test_verified_manual_hold_survives_model_loss(self):
  e,rows=fixture();prior=p.apply_decision(rows,e,{},now=NOW)
  e['previous_observed_manual_decision']=dict(job_id='manual',receipt=prior)
  for r in e['storefront']['rows'].values():r['package_usd']='18'
  receipt=p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(Decimal(receipt['decisions'][0]['model_unavailable_fallback_usd']),18)
  self.assertEqual(receipt['decisions'][0]['model_unavailable_fallback_reason'],'unchanged_market_verified_manual_intent')
  self.assertIsNone(receipt['decisions'][0]['previous_confirmed_execution_id'])
 def test_market_move_or_cost_floor_overrides_manual_hold(self):
  e,rows=fixture();prior=p.apply_decision(rows,e,{},now=NOW)
  e['previous_observed_manual_decision']=dict(job_id='manual',receipt=prior)
  for r in e['storefront']['rows'].values():r['package_usd']='18'
  for offers in e['offers'].values():offers['Lootbar']['usd_price']='19.5'
  receipt=p.apply_decision(rows,e,{},now=NOW)
  self.assertNotEqual(receipt['decisions'][0]['model_unavailable_fallback_reason'],'unchanged_market_verified_manual_intent')
 def test_all_package_redlines_retained(self):
  e,rows=fixture();p.apply_decision(rows,e,{},now=NOW)
  for r in rows:
   self.assertGreaterEqual(Decimal(r['proof']['catalog']['minimum_estimated_average_margin_pct']),10)
   self.assertGreaterEqual(Decimal(r['proof']['catalog']['worst_published_margin_pct']),10)
 def test_simulator_sha_tracks_actual_policy(self):
  tree=ast.parse((SOURCE/'pricing_simulation.py').read_text(encoding='utf-8'))
  expected=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='V2_CODE_SHA' for t in n.targets))
  self.assertEqual(expected,hashlib.sha256((SOURCE/'pricing_v2.py').read_bytes()).hexdigest())
 def test_legacy_quote_not_executable_ui(self):
  source=(SOURCE/'pricing_state.py').read_text(encoding='utf-8')
  self.assertIn("get('position_policy_version')==POSITION_VERSION",source)
 def test_manual_intent_requires_candidate_backend_and_public(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   for folder in ('jobs','quotes','previews'):(root/folder).mkdir()
   e,rows=fixture();receipt=p.apply_decision(rows,e,{'quotes':{platform:'.18' for platform in ('PS','XBOX','PC')}},now=NOW)
   prior=dict(evidence=e,edits={'quotes':{platform:'.18' for platform in ('PS','XBOX','PC')},'reason':'operator price position'},result={'decision_receipt':receipt})
   raw=json.dumps(prior).encode();(root/'quotes/old.json').write_bytes(raw)
   (root/'jobs/manual.json').write_text(json.dumps(dict(job_id='manual',kind='recalculate',actor='wulv',status='ready',request={'run_id':'old'})))
   (root/'jobs/preview.json').write_text(json.dumps(dict(kind='preview',actor='wulv',status='ready',request={'run_id':'old'},result={'preview_id':'preview'})))
   view=dict(quote_sha256=hashlib.sha256(raw).hexdigest(),backend_before={'rows':[dict(platform=platform,b2c='.18') for platform in ('PS','XBOX','PC')]})
   (root/'previews/preview.json').write_text(json.dumps(view))
   tree=ast.parse((SOURCE/'server_quote_job.py').read_text(encoding='utf-8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observed_manual_decision')
   env=dict(ROOT=root,json=json,hashlib=hashlib,PLATFORMS=('PS','XBOX','PC'),positive=lambda v,k:p.number(v),nonnegative=lambda v,k:p.number(v,zero=True))
   exec(compile(ast.Module(body=[fn],type_ignores=[]),'manual-intent','exec'),env)
   public=copy.deepcopy(e['storefront'])
   for row in public['rows'].values():row['package_usd']='18'
   value=env['observed_manual_decision']('new',public);self.assertEqual(value['job_id'],'manual');self.assertFalse(value['write_performed'])
   public['rows']['PC']['package_usd']='18.01';self.assertIsNone(env['observed_manual_decision']('new',public))
   public['rows']['PC']['package_usd']='18';view['quote_sha256']='wrong';(root/'previews/preview.json').write_text(json.dumps(view));self.assertIsNone(env['observed_manual_decision']('new',public))
 def test_original_alert_chain_receives_margin_and_conflict(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'quotes').mkdir();e,rows=fixture(cost='.6');receipt=p.apply_decision(rows,e,{},now=NOW)
   (root/'quotes/current.json').write_text(json.dumps(dict(run_id='run',created_at=NOW.isoformat(),result={'rows':rows,'decision_receipt':receipt})))
   tree=ast.parse((SOURCE/'pricing_probe.py').read_text(encoding='utf-8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='owner_price_review')
   env=dict(Path=Path,json=json);exec(compile(ast.Module(body=[fn],type_ignores=[]),'alert','exec'),env)
   codes,details=env['owner_price_review'](root);self.assertIn('coin_margin_review_urgent_PS',codes);self.assertEqual(details['run_id'],'run')
 def test_python39_syntax(self):
  for file in SOURCE.glob('*.py'):ast.parse(file.read_text(encoding='utf-8'),feature_version=(3,9))

if __name__=='__main__':unittest.main()
