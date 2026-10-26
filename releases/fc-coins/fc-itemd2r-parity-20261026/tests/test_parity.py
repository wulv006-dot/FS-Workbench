import ast,copy,hashlib,json,sys,unittest
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
LEGACY=SOURCE.parents[1]/'fc-pricing-v2-20261022'
if not LEGACY.is_dir():LEGACY=SOURCE.parents[1]/'fc_reference_weighting_20261024'
sys.path[:0]=[str(SOURCE),str(LEGACY/'source'),str(LEGACY/'tests')]
import pricing_v2 as p
from test_pricing_v2 import fixture as base_fixture,NOW

def fixture(item='18',cost='.7'):
 e,rows,_=base_fixture();e['run_id']='original'
 for row in e['costs'].values():row['cny_per_1k']=cost
 e['reference_market']=dict(status='available',run_id='original',offers=[dict(source='ItemD2R',platform=platform,run_id='original',status='valid',currency='USD',conditional=False,comparable=True,purchase_k='100',bonus_k='0',gross_usd=item,captured_at=NOW.isoformat(),url='https://www.itemd2r.com/ea-sports-fc/fc-27-coins') for platform in ('PS','XBOX','PC')])
 return e,rows

class TemporaryParity(unittest.TestCase):
 def test_delivered_unit_parity_no_extra_one_percent(self):
  e,rows=fixture();receipt=p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual([r['target_page_usd'] for r in rows],['18.90']*3)
  self.assertEqual(receipt['temporary_reference']['ratio'],'1')
  self.assertEqual(receipt['temporary_reference']['expires'],'only_after_explicit_user_release')
 def test_no_tail_price_or_rounding_up(self):
  e,rows=fixture('18.001');p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['target_page_usd'],'18.90')
  self.assertEqual(rows[0]['ending_reason'],'temporary_reference_no_ending')
 def test_gifts_on_both_sides(self):
  e,rows=fixture()
  for offer in e['reference_market']['offers']:offer['bonus_k']='5'
  p.apply_decision(rows,e,{},now=NOW);self.assertEqual(rows[0]['target_page_usd'],'18.00')
 def test_lootbar_cap_remains(self):
  e,rows=fixture('22');p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['target_page_usd'],'20.00');self.assertEqual(rows[2]['target_page_usd'],'20.00')
 def test_common_console_pool_takes_lower_platform(self):
  e,rows=fixture();e['reference_market']['offers'][1]['gross_usd']='19'
  p.apply_decision(rows,e,{},now=NOW);self.assertEqual(rows[0]['target_page_usd'],rows[1]['target_page_usd']);self.assertEqual(rows[0]['target_page_usd'],'18.90')
 def test_weighted_index_does_not_override_parity(self):
  e,rows=fixture('19.04')
  for offers in e['offers'].values():offers['U7Buy']=dict(offers['Lootbar'],site='U7Buy',usd_price='16')
  receipt=p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['target_page_usd'],'19.99');self.assertNotEqual(Decimal(receipt['decisions'][0]['raw_weighted_usd']),Decimal('19.99'))
 def test_different_manual_and_hermes_prices_rejected(self):
  for price in ('.18','.1891'):
   e,rows=fixture()
   with self.assertRaises(ValueError):p.apply_decision(rows,e,{'quotes':{'PC':price}},now=NOW)
 def test_matching_explicit_candidate_is_accepted(self):
  e,rows=fixture();p.apply_decision(rows,e,{'quotes':{s:'.189' for s in ('PS','XBOX','PC')}},now=NOW)
  self.assertEqual(rows[2]['target_page_usd'],'18.90')
 def test_fallback_does_not_return_to_confirmed_or_manual_hold(self):
  for prior_key in ('previous_confirmed_decision','previous_observed_manual_decision'):
   e,rows=fixture();prior=p.apply_decision(rows,e,{},now=NOW)
   for row in e['storefront']['rows'].values():row['package_usd']='18'
   e[prior_key]=dict(execution_id='previous',job_id='manual',receipt=prior)
   result=p.apply_decision(rows,e,{},now=NOW)
   for d in result['decisions']:
    self.assertEqual(Decimal(d['model_unavailable_fallback_usd']),Decimal('18.90'));self.assertNotIn('hold',d['candidates'])
    self.assertEqual(d['model_unavailable_fallback_reason'],'temporary_itemd2r_parity')
 def test_no_change_choice_only_if_already_parity(self):
  e,rows=fixture()
  for row in e['storefront']['rows'].values():row['package_usd']='18.90'
  result=p.apply_decision(rows,e,{},now=NOW);self.assertEqual(result['decisions'][0]['candidates']['hold'],'18.90')
 def test_missing_stale_conditional_and_cross_run_sources_block(self):
  for change in ({'run_id':'other'},{'currency':'CNY'},{'conditional':True},{'captured_at':(NOW-timedelta(minutes=16)).isoformat()}):
   e,rows=fixture();e['reference_market']['offers'][0].update(change)
   result=p.apply_decision(rows,e,{},now=NOW);self.assertEqual(rows[0]['auto_blocked_reason'],'pricing_position_peer_missing')
   self.assertEqual(result['decisions'][0]['position_status'],'missing_itemd2r')
 def test_floor_conflict_does_not_lower_guard(self):
  e,rows=fixture(cost='2');p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['auto_blocked_reason'],'pricing_position_floor_conflict')
  for row in rows:
   self.assertGreaterEqual(Decimal(row['proof']['catalog']['minimum_estimated_average_margin_pct']),10)
   self.assertGreaterEqual(Decimal(row['proof']['catalog']['worst_published_margin_pct']),10)
 def test_all_catalog_and_integer_quantities_proved(self):
  e,rows=fixture();p.apply_decision(rows,e,{},now=NOW)
  for row in rows:
   proof=row['proof']['catalog'];self.assertTrue(proof['all_integer_custom_quantities_covered']);self.assertGreater(proof['published_packages'],1)
   self.assertGreaterEqual(Decimal(proof['minimum_estimated_average_margin_pct']),10)
 def test_margin_warning_is_still_visible(self):
  e,rows=fixture(cost='.6');p.apply_decision(rows,e,{},now=NOW)
  self.assertEqual(rows[0]['margin_review']['level'],'urgent');self.assertFalse(rows[0]['margin_review']['automatic_margin_cap'])
 def test_stale_cost_not_reused_for_execution(self):
  e,rows=fixture()
  with self.assertRaisesRegex(ValueError,'pricing_source_stale'):p.apply_decision(rows,e,{},now=NOW+timedelta(minutes=16))
 def test_release_flag_retains_previous_owner_policy(self):
  e,rows=fixture()
  with patch.object(p,'TEMPORARY_ITEMD2R_PARITY',False):
   result=p.apply_decision(rows,e,{'quotes':{s:'.18' for s in ('PS','XBOX','PC')}},now=NOW)
  self.assertEqual(rows[0]['target_page_usd'],'18.00');self.assertFalse(result['temporary_reference']['active'])
 def test_simulator_uses_current_implementation_hash(self):
  tree=ast.parse((SOURCE/'pricing_simulation.py').read_text(encoding='utf-8'))
  value=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='V2_CODE_SHA' for t in n.targets))
  self.assertEqual(value,hashlib.sha256((SOURCE/'pricing_v2.py').read_bytes()).hexdigest())
 def test_temporary_policy_receipt_and_display_cannot_be_tampered(self):
  e,rows=fixture();receipt=p.apply_decision(rows,e,{},now=NOW)
  q=dict(evidence=e,edits={},result=dict(rows=rows,decision_receipt=receipt));policy={'minimum_gross_margin_pct':'10'}
  p.verify_quote(q,policy,['PS','XBOX','PC'],now=NOW)
  q['result']['rows'][0]['temporary_itemd2r_parity']=False
  with self.assertRaisesRegex(ValueError,'pricing_quote_tampered'):p.verify_quote(q,policy,['PS','XBOX','PC'],now=NOW)
 def test_python39_and_bridge_scope(self):
  for f in SOURCE.glob('*.py'):ast.parse(f.read_text(encoding='utf-8'),feature_version=(3,9))
  bridge=(SOURCE/'hermes_pricing_bridge.py').read_text(encoding='utf-8');self.assertIn('直到用户明确解除',bridge);self.assertIn('不能另选不同的hold/evaluated',bridge)

if __name__=='__main__':unittest.main()
