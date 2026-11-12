"""Synthetic D2 facts; no source sessions, exports, prices or production writes."""
import copy,json,sys,unittest
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT.parent/'cache-archive-retention-20261025/source')]
from order_facts import build_order_facts
SITES={'266':'www.mmoexp.com','320':'www.rsorders.com'}

def order(sn='O1',site='266',cny='350',usd='50',**more):
 return dict(site_id=site,order_no=sn,amount_rmb_format=cny,amount_usd_format=usd,
             status_format='已完成',pay_status='1',gid='1327',game_format='FC 27',paytime='2026-11-10 10:00:00',**more)
def delivery(did='D1',sn='O1',source='www.mmoexp.com',cost='150',**more):
 return dict(delivery_id=did,sn=sn,source=source,genre='1',cost_total=cost,sale_total='350.22',**more)
def attribution(sn='O1',site='266',channel='PPC'):
 return {'site_id':site,'order_no':sn,'归因渠道':channel,'归因来源明细':'raw-source','首访时间':'unverified-time','订单来源':'google-example'}
def build(orders,attrs=(),costs=(),complete=()):
 return build_order_facts(orders,attrs,costs,sites=SITES,scope={'period':['2026-11-10','2026-11-11'],'basis':'selected_paid_orders'},
                         source_coverage={'admin_complete':True,'revision':'synthetic-r1'},complete_cost_orders=complete)

class OrderFacts(unittest.TestCase):
 def test_multiline_revenue_once_multiple_deliveries_and_repeated_record(self):
  a=order(line_id='a');b=order(line_id='b');d1=delivery();d2=delivery('D2',cost='50')
  inputs=([a,b],[attribution()],[d1,d2,copy.deepcopy(d1)]);old=copy.deepcopy(inputs)
  result=build(*inputs,complete=[('266','O1')]);fact=result['orders'][0]
  self.assertEqual(result['totals']['orders'],1);self.assertEqual(Decimal(fact['admin_paid_cny']),350)
  self.assertEqual(Decimal(fact['actual_cost_cny']),200);self.assertEqual(Decimal(fact['procurement_gross_cny']),150)
  self.assertEqual(len(fact['cost_records']),2);self.assertEqual(result['coverage']['duplicate_cost_rows'],1)
  self.assertEqual(inputs,old);json.dumps(result)
 def test_cross_site_same_order_and_same_delivery_id_never_merge(self):
  result=build([order(),order(site='320',cny='90')],[attribution(),attribution(site='320',channel='SEO')],
               [delivery(),delivery(source='www.rsorders.com',cost='20')],complete=[('266','O1'),('320','O1')])
  self.assertEqual(result['totals']['orders'],2)
  facts={r['site_id']:r for r in result['orders']}
  self.assertEqual(Decimal(facts['266']['actual_cost_cny']),150);self.assertEqual(Decimal(facts['320']['actual_cost_cny']),20)
  self.assertEqual(facts['320']['channel'],'SEO')
 def test_missing_site_cannot_be_inferred_from_unique_order_number(self):
  a=order();a.pop('site_id');attr=attribution();attr.pop('site_id')
  result=build([order(),a],[attr],[delivery(source='unknown-site')])
  self.assertEqual(result['totals']['orders'],1);self.assertEqual(len(result['unlinked_admin_rows']),1)
  self.assertEqual(result['orders'][0]['channel'],'unknown');self.assertIsNone(result['orders'][0]['actual_cost_cny'])
  self.assertEqual(len(result['unlinked_attribution_rows']),1);self.assertEqual(len(result['unlinked_cost_records']),1)
  self.assertEqual(result['status'],'partial')
 def test_missing_or_partial_cost_is_not_zero_but_explicit_zero_is_retained(self):
  for costs,complete in [([],[]),([delivery()],[])]:
   result=build([order()],costs=costs,complete=complete);row=result['orders'][0]
   self.assertIsNone(row['actual_cost_cny']);self.assertIsNone(row['procurement_gross_cny'])
   self.assertEqual(Decimal(result['totals']['missing_cost_revenue_cny']),350)
  result=build([order()],costs=[delivery(cost='0')],complete=[('266','O1')])
  self.assertEqual(Decimal(result['orders'][0]['actual_cost_cny']),0)
 def test_new_channel_only_unknown_and_conflicting_attribution_not_backfilled(self):
  for attrs in ([attribution(channel='Direct')],[attribution(channel='')],[attribution(channel='unrecognized')],
                [attribution(channel='Direct'),attribution(channel='PPC')],[]):
   row=build([order()],attrs)['orders'][0]
   self.assertEqual(row['channel'],'Direct' if len(attrs)==1 and attrs[0]['归因渠道']=='Direct' else 'unknown')
 def test_conflicting_parent_money_or_delivery_revision_explicitly_rejected(self):
  with self.assertRaisesRegex(ValueError,'admin_order_revision_conflict'):build([order(),order(cny='351')])
  with self.assertRaisesRegex(ValueError,'cost_record_revision_conflict'):build([order()],costs=[delivery(),delivery(cost='151')])
 def test_same_scope_channel_counts_revenue_cost_and_coverage_conserve(self):
  orders=[order('O1'),order('O2',cny='100'),order('O3',cny='50')]
  result=build(orders,[attribution('O1'),attribution('O2',channel='Direct')],
      [delivery(),delivery('D2',cost='50'),delivery('D3',sn='O2',cost='20')],complete=[('266','O1'),('266','O2')])
  self.assertEqual(sum(x['orders'] for x in result['channels']),3)
  for key in ('admin_paid_cny','admin_paid_usd','observed_cost_cny','covered_revenue_cny','missing_cost_revenue_cny'):
   self.assertEqual(sum(Decimal(x[key]) for x in result['channels']),Decimal(result['totals'][key]))
  self.assertEqual(sum(x['cost_records'] for x in result['channels']),3)
  self.assertEqual(result['totals']['unknown_channel_orders'],1)
  self.assertIsNone(result['totals']['known_fee_contribution_cny'])
 def test_dispute_and_missing_amount_preserved_without_mature_profit(self):
  a=order();a.update(status_format='投诉·追回',amount_usd_format=None)
  row=build([a],costs=[delivery()],complete=[('266','O1')])['orders'][0]
  self.assertEqual(row['status'],'投诉·追回');self.assertIsNone(row['admin_paid_usd'])
  self.assertIsNone(row['procurement_gross_cny']);self.assertEqual(Decimal(row['actual_cost_cny']),150)
  self.assertEqual(row['cost_records'][0]['order_sale_cny'],'350.22')
 def test_equivalent_money_formats_deduplicate_and_missing_record_id_stays_partial(self):
  r=build([order(),order(cny='350.00',usd='$50.00')],costs=[delivery(),delivery(cost='150.00')],complete=[('266','O1')])
  self.assertEqual(r['totals']['orders'],1);self.assertEqual(r['coverage']['duplicate_cost_rows'],1)
  for invalid in (delivery('',cost='5'),delivery('D2',cost=None),delivery('D2',cost='-5')):
   row=build([order()],costs=[delivery(),invalid],complete=[('266','O1')])['orders'][0]
   self.assertIsNone(row['actual_cost_cny']);self.assertIsNone(row['procurement_gross_cny'])
 def test_existing_d0_namespace_keeps_unknown_revision_and_hash_needs_real_bridge(self):
  from order_attribution import normalize_order_attribution,HEADERS
  raw=attribution(channel='Direct');fact=normalize_order_attribution(raw,set(raw),{'fields':HEADERS})
  fact.update(source_revision='fixture-publication',available_at='fixture-time',evidence_ref=['fixture-manifest'])
  bridge={'site_id':'266','order_no':'O1','marketing_attribution':fact}
  value=build([order()],[bridge]);self.assertEqual(value['orders'][0]['marketing_attribution'],fact)
  fact['status']='conflict';self.assertEqual(build([order()],[bridge])['orders'][0]['channel'],'unknown')
  bridge.pop('order_no');bridge['订单号']='existing-d0-hash'
  value=build([order()],[bridge]);self.assertEqual(len(value['unlinked_attribution_rows']),1)
  self.assertEqual(value['orders'][0]['channel'],'unknown')
if __name__=='__main__':unittest.main()
