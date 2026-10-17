import ast,copy,json,sys,unittest
from decimal import Decimal,InvalidOperation
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'baseline')]
import boss_renderer
from boss_projection import project
from report_constraints import review_paragraph
import test_projection as fixtures

class ActualAcceptanceFixes(unittest.TestCase):
 def customer_evidence(self,current_start='2026-10-05',current_end='2026-10-11',previous_start='2026-09-28',previous_end='2026-10-04'):
  def row(start,end,count,rate):return {'analysis_anchor_id':'fixture','captured_at':'2026-10-16T00:00:00+00:00','query':{'profile':'FC27','start':start,'end':end},'data':{'status':'available','authoritative_fields':{'newCustomers':{'status':'available','value':count,'unit':'people'},'repeatRatePct':{'status':'available','value':rate,'unit':'percent'},'refundOrders':{'status':'available','value':0,'unit':'orders'}}}}
  return {'ev_current':row(current_start,current_end,10,80),'ev_previous':row(previous_start,previous_end,20,70)}
 def test_native_customer_comparison_uses_same_period_fields_zero_and_latest_source(self):
  from report_constraints import native_customer_comparison
  period={'start':'2026-10-05','end':'2026-10-11'};rows=self.customer_evidence()
  result=native_customer_comparison(rows,'fixture',period)
  self.assertEqual(result['fields']['newCustomers']['direction'],'下降');self.assertEqual(result['fields']['newCustomers']['delta'],'-10')
  self.assertEqual(result['fields']['repeatRatePct']['direction'],'上升');self.assertEqual(result['fields']['refundOrders']['delta'],'0')
  newer=copy.deepcopy(rows['ev_current']);newer['captured_at']='2026-10-16T01:00:00+00:00';newer['data']['authoritative_fields']['newCustomers']['value']=12;rows['ev_newer']=newer
  self.assertEqual(native_customer_comparison(rows,'fixture',period)['fields']['newCustomers']['delta'],'-8')
  newer['data']['authoritative_fields']['newCustomers']['unit']='USD'
  self.assertNotIn('newCustomers',native_customer_comparison(rows,'fixture',period)['fields'])
  self.assertFalse(native_customer_comparison(rows,'wrong-anchor',period))
  self.assertFalse(native_customer_comparison(rows,'fixture',{'start':'2026-10-01','end':'2026-10-15'}))
  day=self.customer_evidence('2026-10-15','2026-10-15','2026-10-14','2026-10-14')
  self.assertFalse(native_customer_comparison(day,'fixture',{'start':'2026-10-15','end':'2026-10-15'}))
  self.assertIn('newCustomers',native_customer_comparison(day,'fixture',{'start':'2026-10-15','end':'2026-10-15','comparison_start':'2026-10-14','comparison_end':'2026-10-14'})['fields'])
 def test_customer_decline_cannot_be_described_as_all_better_than_comparison(self):
  from report_constraints import constraints,reviewed_text
  content={'report':{'period':{'start':'2026-10-05','end':'2026-10-11'},'snapshot_id':'fixture','business_data_captured_at':'2026-10-16T00:00:00+00:00'},'payment':[],'payment_evidence_ids':[]}
  bounds=constraints(content,self.customer_evidence());ledger=[]
  self.assertIn('本句待证',reviewed_text('新客10人、复购率80%、发货完成率90%均略好于对照。',bounds,ledger,'research_text'))
  self.assertIn('native_customer_direction_conflict',ledger[0]['codes'])
  for text in ('新客10人下降，复购和发货率均略好于对照。','新客10人、复购率80%均略好于目标。'):
   self.assertEqual(reviewed_text(text,bounds,[],'research_text'),text)
 def test_payment_table_residual_uses_delta_column_not_current_amount(self):
  bounds={'verified_quantity_price_discount':False,'payment_delta':{'applepay':'-20','paypal':'-10','klarna':'30'},'payment_evidence_ids':['ev_payment']}
  table='|通道|本期|对照|金额变化|\n|---|---|---|---|\n|applepay|$100|$120|-$20|\n|paypal|$90|$100|-$10|\n|其他|$200|$170|+$30|'
  self.assertEqual(review_paragraph(table,bounds)[0],[])
  self.assertIn('payment_residual_direction_conflict',[c for c,_ in review_paragraph(table.replace('+$30','-$30'),bounds)[0]])
 def test_native_model_view_retains_canonical_totals_and_full_frozen_audit(self):
  from test_learning_loop import calculation_module
  import threading,hashlib
  module=calculation_module();method=module.ResearchBook.research
  method.__globals__.update(deepcopy=copy.deepcopy,period=lambda *a:None,digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest())
  book=module.ResearchBook.__new__(module.ResearchBook);book.data={'as_of':'2026-10-16T00:00:00+00:00'};book.capture_id='fixture'
  book._lock=threading.RLock();book.trace=[];book.evidence={};book.persist=None;book.target={'start':'2026-10-05','end':'2026-10-11'}
  native={'status':'available','authoritative_fields':self.authority(self.records()),'source_records':self.records()}
  book.native=lambda args:native;before=copy.deepcopy(native)
  result=book.research('fc.query_native_statistics',{'profile':'FC26','start':'2025-10-05','end':'2025-10-11'})
  self.assertEqual(result['data']['selected_totals']['orders'],17);self.assertEqual(result['data']['selected_totals']['revenueUsd'],1300.50)
  self.assertNotIn('source_records',result['data']);self.assertEqual(book.evidence[result['evidence_id']]['data']['source_records'],before['source_records'])
  self.assertEqual(native,before)
  bound=book.research('fc.calculate',{'operation':'sum','values':['17'],'evidence_ids':[result['evidence_id']],'value_paths':[{'evidence_id':result['evidence_id'],'path':'/data/selected_totals/orders'}],'assumptions':['']})
  self.assertEqual(bound['data']['result']['sum'],'17.00')
  rows=self.customer_evidence();book.native=lambda args:copy.deepcopy(rows['ev_current' if args['start']=='2026-10-05' else 'ev_previous']['data'])
  book.research('fc.query_native_statistics',{'profile':'FC27','start':'2026-10-05','end':'2026-10-11'})
  other=book.research('fc.query_native_statistics',{'profile':'FC27','start':'2026-09-28','end':'2026-10-04'})
  self.assertEqual(other['data']['native_customer_comparison']['fields']['newCustomers']['direction'],'下降')
  self.assertEqual(book.evidence[other['evidence_id']]['data']['native_customer_comparison'],other['data']['native_customer_comparison'])
  bound=book.research('fc.calculate',{'operation':'sum','values':['-10'],'evidence_ids':[other['evidence_id']],'value_paths':[{'evidence_id':other['evidence_id'],'path':'/data/native_customer_comparison/fields/newCustomers/delta'}],'assumptions':['']})
  self.assertEqual(bound['data']['result']['sum'],'-10.00')
 def test_fc26_same_period_quotation_conflicts_are_withheld_not_rewritten(self):
  from report_constraints import constraints,reviewed_text
  content={'report':{'period':{'start':'2026-10-05','end':'2026-10-11'},'snapshot_id':'fixture','business_data_captured_at':'2026-10-16T00:00:00+00:00'},'payment':[],'payment_evidence_ids':[]}
  row={'analysis_anchor_id':'fixture','query':{'profile':'FC26','start':'2025-10-05','end':'2025-10-11'},'data':{'status':'available','authoritative_fields':self.authority(self.records())}}
  bounds=constraints(content,{'ev_native':row});ledger=[]
  wrong='FC26 同比：FC26 同日期区间营收 $1,600.25、订单 19。'
  self.assertIn('本句待证',reviewed_text(wrong,bounds,ledger,'research_text'));self.assertEqual(ledger[0]['severity'],'error')
  correct='FC26 同比：FC26 同日期区间营收 $1,300.50、订单 17。'
  self.assertEqual(reviewed_text(correct,bounds,[],'research_text'),correct)
  for text in ('FC26 同比：订单增长 50%，营收增长 $100。','FC26 同期订单 50%，仅为参考比。','FC26 同期营收 $1.3k、订单约17。'):
   self.assertEqual(reviewed_text(text,bounds,[],'research_text'),text)
  row['query']['start']='2025-10-04';self.assertFalse(constraints(content,{'ev_native':row})['native_comparisons'])
 def test_fc26_quotation_does_not_bind_other_period_in_same_paragraph(self):
  bounds={'native_comparisons':[{'values':{'revenueUsd':'1300.50','orders':17},'evidence_id':'ev_fixture'}],'verified_quantity_price_discount':False,'payment_delta':{}}
  correct='最近30天：营收 $7,200.00、订单 118。\nFC26 同期：营收 $1,300.50、订单 17。'
  self.assertFalse(review_paragraph(correct,bounds)[0])
  before='最近30天营收 $7,200.00；FC26 同期营收 $1,300.50、订单 17。'
  self.assertFalse(review_paragraph(before,bounds)[0])
  wrong=correct.replace('$1,300.50','$2,300.50')
  self.assertTrue(any(code=='native_statistic_value_conflict' for code,_ in review_paragraph(wrong,bounds)[0]))
 def test_advisory_action_role_and_combined_success_failure_label_are_preserved(self):
  from report_semantics import markdown_actions,sections,index
  text='## 建议与复查\n### R1 结构复核\n- 对象：合成品类。\n- 责任角色（建议）：运营与数据分析。\n- 最小动作：核对订单行。\n- 成功/失败标准：成功=定位原因；失败=保留未知。\n'
  items=markdown_actions(sections(text),{});self.assertEqual(len(items),1)
  self.assertEqual(items[0]['role'],'运营与数据分析。');self.assertIn('失败=保留未知',items[0]['success_check'])
  old={**items[0],'role':'待补：责任角色'};value={'report_format':'markdown','research_text':text,'actions':[old]}
  self.assertEqual(index(value,{})['actions'][0]['role'],'运营与数据分析。')
  value['report_format']='structured_v2';self.assertEqual(index(value,{})['actions'][0]['role'],'待补：责任角色')
 def test_calculations_preserve_intermediate_precision_and_final_rounding(self):
  from test_learning_loop import calculation_module
  research=calculation_module()
  value=research.calculation({'operation':'ratio','values':['9.425','10'],'evidence_ids':['ev_fixture']})
  self.assertEqual(value['result']['ratio'],'0.94');self.assertEqual(value['result']['percent'],'94.25')
  self.assertEqual(value['result']['ratio_unrounded'],'0.9425')
  product=research.calculation({'operation':'multiply','values':['1.23','0.045'],'evidence_ids':['ev_fixture']})
  self.assertEqual(product['result']['product'],'0.06');self.assertEqual(product['result']['product_unrounded'],'0.05535')
  final=research.calculation({'operation':'sum','values':[product['result']['product_unrounded']]*2,'evidence_ids':['ev_fixture']})
  self.assertEqual(final['result']['sum'],'0.11')
  book=research.ResearchBook.__new__(research.ResearchBook);book.evidence={}
  with self.assertRaisesRegex(ValueError,'calculation_evidence'):book.research('fc.calculate',{'evidence_ids':[{}]})
 def test_question_about_unit_contribution_is_not_an_asserted_quantity_mechanism(self):
  bounds={'verified_quantity_price_discount':False,'payment_delta':{}}
  self.assertEqual(review_paragraph('再看是否为单件贡献下降。',bounds)[0],[])
  self.assertEqual(review_paragraph('变化可能来自单件贡献下降，需要核对订单行。',bounds)[0],[])
  self.assertIn('quantity_mechanism_unbound',[code for code,_ in review_paragraph('变化来自单件贡献下降。',bounds)[0]])
 def test_existing_published_search_terms_and_pages_are_filtered_without_url_query_leaks(self):
  from marketing_snapshot import projection
  rows=lambda field,labels:[{'dimensions':{field:label},'metrics':{'clicks':'2','impressions':'10','ctr':'0.2','position':'3'}} for label in labels]
  model={'schemaVersion':1,'isMock':False,'details':{'schemaVersion':1,'isMock':False,'periods':[{'start':'2026-10-05','end':'2026-10-11','sources':{'gsc':{'resource':'sc-domain:mmoexp.com','timezone':'America/Los_Angeles','metrics':{},'breakdowns':{'query':{'rows':rows('query',['buy FC27 coins','FC26 coins','Madden coins','fc27 <script>'])},'page':{'rows':rows('page',['https://www.mmoexp.com/fc-27.html?private=secret','https://other.example/fc27','https://[fc27'])}}}},'adsAccounts':[]}]}}
  out=projection(model,{'profile':'FC27','start':'2026-10-05','end':'2026-10-11'},'a'*64)['sources']['gsc']['fc27_name_rows']
  self.assertEqual([r['label'] for r in out['query']['rows']],['buy FC27 coins'])
  self.assertEqual([r['label'] for r in out['page']['rows']],['/fc-27.html']);self.assertNotIn('secret',json.dumps(out))
  empty=boss_renderer.marketing_section({'status':'partial','sources':{},'ads_accounts':[],'note':'','evidence_ids':[],'fc27_by_name':{'search':{'query':{'rows':[]}}}})
  self.assertIn('不代表FC自然搜索为零',empty)
 def test_fc_name_filter_and_weighted_marketing_totals_keep_currency_and_coverage(self):
  from report_tracks import fc27_name,fc27_marketing_view
  for name in ('FC27-SN-Buy-UK','fc 27 coins','EA FC-27','FC_27 buy','Coins','buy coins','SN-COINS-US'):self.assertTrue(fc27_name(name))
  for name in ('FC26-SN','FC270','FC26 coins','FC270 coins','Madden-SN-Coins','madden27 coins','Madden-NFL-27-Coins','NBA2K27 Coins','MLB-Coins','Diablo 4 Coins','PoE2-Coins','Aion2-Coins','bitcoin','A2-Kinah','MSC-Mesos',None):self.assertFalse(fc27_name(name))
  def row(name,cost,clicks,conversions,value):return {'campaign_name':name,'metrics':dict(cost=cost,clicks=clicks,conversions=conversions,conversionsValue=value,impressions='100')}
  data={'ads_accounts':[{'customer_id':'a','currency':'USD','metrics':{'cost':'160'},'campaigns':{'rows':[row('FC27-A','30','10','2','40'),row('FC 27-B','20','5','3','60'),row('A2','100','50','1','10'),row('Madden-SN-Coins','10','2','1','20')],'output_capped':False,'rejected_rows':0,'status':{'quality':{'pagination_complete':True}}}}]}
  original=copy.deepcopy(data);out=fc27_marketing_view(data)['ads_accounts'][0]
  self.assertEqual(out['metrics']['cost'],'50');self.assertEqual(out['metrics']['cpa'],'10');self.assertEqual(out['metrics']['platformRoas'],'2')
  self.assertEqual(out['currency'],'USD');self.assertTrue(out['selection_complete']);self.assertEqual(data,original)
  data['ads_accounts'][0]['campaigns']['output_capped']=True;self.assertFalse(fc27_marketing_view(data)['ads_accounts'][0]['selection_complete'])
 def authority(self,records,sources=None):
  tree=ast.parse((ROOT/'source/fs_evidence.py').read_text('utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='authoritative_native_fields')
  scope=dict(Decimal=Decimal,InvalidOperation=InvalidOperation,date=date,timedelta=timedelta)
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-native-authority','exec'),scope)
  return scope['authoritative_native_fields'](records,{'profile':'FC26','start':'2025-10-05','end':'2025-10-11'},sources)
 def records(self):
  base=dict(status='available',stale=False,period={'start':'2025-10-05 00:00','end':'2025-10-12 00:00'})
  return {'primary':dict(base,system='order.p2pah.cn',orders=19,revenueUsd=1600.25,metrics={'profitMarginPct':{'status':'available','unit':'percent','value':22.5},'refundOrders':{'status':'available','value':5,'unit':'count'}}),
          'supplement':dict(copy.deepcopy(base),system='admin.p2pah.cn',orders=17,revenueUsd=1300.50,metrics={'refundOrders':{'status':'available','value':0,'unit':'count'},'profitMarginPct':{'status':'missing','value':None}})}
 def test_year_ago_native_fields_choose_admin_and_keep_zero_with_order_fallback(self):
  records=self.records();before=copy.deepcopy(records);fields=self.authority(records)
  self.assertEqual(fields['orders']['value'],17);self.assertEqual(fields['revenueUsd']['system'],'admin.p2pah.cn')
  self.assertEqual(fields['refundOrders']['value'],0);self.assertEqual(fields['profitMarginPct']['value'],22.5)
  self.assertEqual(records,before)
 def test_wrong_period_stale_and_non_finite_values_are_not_promoted(self):
  records=self.records();records['supplement']['period']['start']='2025-10-06 00:00';self.assertEqual(self.authority(records)['orders']['value'],19)
  records=self.records();records['supplement']['stale']=True;self.assertEqual(self.authority(records)['orders']['value'],19)
  records=self.records();records['supplement']['orders']=float('nan');self.assertEqual(self.authority(records)['orders']['value'],19)
 def test_real_native_shape_keeps_available_metrics_when_top_level_is_null(self):
  records=self.records();admin=records['supplement'];admin.update(orders=None,revenueUsd=None)
  admin['metrics'].update(orders={'status':'available','value':37,'unit':'count'},revenueUsd={'status':'available','value':2800.75,'unit':'USD'})
  fields=self.authority(records);self.assertEqual(fields['orders']['value'],37)
  self.assertEqual(fields['revenueUsd']['value'],2800.75);self.assertEqual(fields['profitMarginPct']['system'],'order.p2pah.cn')
 def test_real_admin_freshness_is_on_the_outer_source_status(self):
  records=self.records();del records['supplement']['stale']
  self.assertEqual(self.authority(records,{'Admin':{'status':'available','stale':False}})['orders']['value'],17)
  for sources in ({},{'Admin':{'status':'available','stale':True}}):self.assertEqual(self.authority(records,sources)['orders']['value'],19)
 def test_real_model_bold_wrapped_conclusion_headings_are_visible_in_each_module(self):
  result=fixtures.PartialProjection().result()
  result['research_text']='\n\n'.join('**### '+title+'**\n这是模型在该模块给出的具体经营判断。' for title in ('销售与订单结论','平台与商品结论','客户、支付与未完成订单结论','利润与成本结论','游戏与市场情报结论'))
  c=project(result,{}, {'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(set(c['section_conclusions']),{'analysis','products','customers','finance','intelligence'})
 def test_existing_visual_template_is_preserved(self):
  import hashlib
  self.assertEqual(hashlib.sha256((ROOT/'baseline/report.template.html').read_bytes()).hexdigest(),'1a576686e212372533c10ce05f208ee7ebf891ffc386d704492016fb11514922')
 def test_meeting_supplement_preserves_nested_tables_and_does_not_replace_core_sections(self):
  from unittest.mock import patch
  fixture=fixtures.PartialProjection();result=fixture.result();result.update(report_kind='weekly',period={'start':'2026-10-05','end':'2026-10-11'})
  c=project(result,{}, {'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64);c['report']['kind']='weekly'
  c['reviewed_research_text']='## 二、广告投放与SEO\n模型判断。<script>危险</script>\n### 渠道\n| 渠道 | 花费 |\n| --- | --- |\n| A | 10 |\n## 三、网站体验问题与修改需求\n旧版六环节清单。\n## 四、目标完成与下期目标\n待确认目标。'
  with patch.object(boss_renderer,'HERE',ROOT/'baseline'):out=boss_renderer.render(c,{})
  for sid in ('analysis','products','customers','finance','intelligence','actions','meeting'):self.assertIn('id="'+sid+'"',out)
  self.assertIn('<details><summary>广告投放与SEO</summary>',out);self.assertIn('<td>10</td>',out)
  self.assertNotIn('<summary>网站体验问题与修改需求</summary>',out);self.assertNotIn('旧版六环节清单',out.split('id="meeting"',1)[1])
  self.assertIn('待确认目标',out);self.assertNotIn('<script>危险</script>',out)
  c['report']['kind']='daily';c['report']['period'].update(start='2026-10-15',end='2026-10-15')
  with patch.object(boss_renderer,'HERE',ROOT/'baseline'):self.assertNotIn('id="meeting"',boss_renderer.render(c,{}))
 def test_direct_no_inventory_is_not_a_recommendation_but_reversed_negation_is(self):
  self.assertFalse(boss_renderer.inventory_advice('评估页面展示位与供应商沟通（订单驱动、无囤货）。'))
  for text in ('建议囤货。','并非不囤货。','不囤货不合理。','无需囤货；但应囤货。'):
   self.assertTrue(boss_renderer.inventory_advice(text),text)
 def test_combined_payment_residual_recognizes_spaced_channel_names(self):
  bounds={'verified_quantity_price_discount':False,'stable_order_intersection_verified':False,
   'payment_delta':{'applepay':'-8567.60','paypal':'-8505.18','cardpay':'3865.44'},'payment_evidence_ids':['fixture']}
  good='Apple Pay 与 PayPal 合计 -$17,072.78，其他通道合计 +$3,865.44。'
  self.assertEqual(review_paragraph(good,bounds)[0],[])
  self.assertIn('payment_residual_direction_conflict',[code for code,_ in review_paragraph('PayPal 减少，其他通道合计 +$3,865.44。',bounds)[0]])
  self.assertIn('payment_residual_mismatch',[code for code,_ in review_paragraph(good.replace('3,865.44','3,000.00'),bounds)[0]])
 def test_month_to_date_is_closed_and_within_one_month(self):
  fixture=fixtures.PartialProjection();r=fixture.result();r.update(period={'start':'2026-10-01','end':'2026-10-15'},report_kind='monthly')
  c=project(r,{}, {'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  boss_renderer.validate(c,{})
  for start,end in [('2026-10-02','2026-10-15'),('2026-09-01','2026-10-15'),('2026-10-01','2026-10-16')]:
   bad=copy.deepcopy(c);bad['report']['period'].update(start=start,end=end)
   with self.assertRaises(ValueError):boss_renderer.validate(bad,{})
 def countries(self,complete=True):
  fixture=fixtures.PartialProjection();total=fixture.evidence();grouped=fixture.evidence(group='country')
  fact={'revenue_usd':'910','orders':13,'unpriced_orders':0}
  total['data']['total']=dict(fact);grouped['data']['total']=dict(fact)
  grouped['data']['pagination'].update(total_groups=13,complete=complete)
  grouped['data']['groups']=[{'group':{'country':'C'+str(i)},'revenue_usd':str(i*10),'orders':1,'unpriced_orders':0} for i in range(1,14)]
  return project(fixture.result(),{'ev_'+'a'*24:total,'ev_'+'b'*24:grouped},{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)['country_sales']
 def test_country_top_ten_and_other_reconcile_with_weighted_aov(self):
  c=self.countries();self.assertEqual(len(c['rows']),11)
  self.assertEqual(sum(Decimal(x['revenue_usd']) for x in c['rows']),Decimal(910))
  self.assertEqual(sum(Decimal(x['orders']) for x in c['rows']),Decimal(13))
  other=c['rows'][-1];self.assertEqual(other['country'],'其他');self.assertEqual(Decimal(other['aov_usd']),Decimal(20))
  self.assertIsNone(other['previous_revenue_usd']);self.assertIsNone(other['change_percent'])
 def test_incomplete_country_pages_do_not_invent_other_or_zero(self):
  self.assertEqual(self.countries(False)['rows'],[])
 def test_month_to_date_trend_keeps_day_one_when_prior_month_days_are_missing(self):
  fixture=fixtures.PartialProjection();total=fixture.evidence();total['query'].update(start='2026-10-01',end='2026-10-15')
  total['data']['total'].update(revenue_usd='1500',orders=30)
  daily=fixture.evidence(group='day');daily['query'].update(start='2026-09-16',end='2026-10-15')
  daily['data']['total'].update(revenue_usd='3000',orders=60);daily['data']['pagination']['total_groups']=30
  daily['data']['groups']=[{'group':{'day':(date(2026,9,16)+timedelta(days=i)).isoformat()},'revenue_usd':'100','orders':2,'unpriced_orders':0} for i in range(30)]
  result=fixture.result();result.update(period={'start':'2026-10-01','end':'2026-10-15'},report_kind='monthly')
  c=project(result,{'ev_'+'a'*24:total,'ev_'+'b'*24:daily},{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  chart=next(x for x in c['charts'] if x['id']=='daily')
  self.assertEqual(len(chart['rows']),15);self.assertEqual(chart['rows'][0]['current_date'],'2026-10-01')
