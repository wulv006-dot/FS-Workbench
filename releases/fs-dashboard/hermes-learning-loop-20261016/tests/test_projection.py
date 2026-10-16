import sys,unittest,copy
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'baseline')]
from boss_projection import project
from report_semantics import intelligence,article_introduction

class ArticleIntroductions(unittest.TestCase):
 def document(self,title,text):
  return {'title':title,'text':text,'source_url':'https://www.ea.com/games/ea-sports-fc/fc-27/news/'+title.lower().replace(' ','-'),
          'observed_at':'2026-10-16T00:00:00Z','published_at':'2026-10-09'}
 def test_shared_bundle_does_not_copy_action_plan_into_articles(self):
  eid='ev_'+'d'*24
  docs=[self.document('Launch Feedback Update','October 13, 2026 Matchmaking issue was fixed. Career issues are under review.'),
        self.document('Future Stars','October 9, 2026 Future Stars introduces dynamic player items. Upgrades follow domestic league performances.')]
  result={'period':{'start':'2026-10-15','end':'2026-10-15'},'research_text':'## 建议与复查\n### R5 官方内容准备\n- **对象**：Future Stars\n- **最小动作**：准备页面\n- **证据**：'+eid}
  cards,pending,note=intelligence(result,{eid:{'data':{'documents':docs}}})
  self.assertEqual(len(cards),2);self.assertNotEqual(cards[0]['source_preview'],cards[1]['source_preview'])
  self.assertTrue(all('中文内容简介尚未生成' in c['fact'] for c in cards))
  self.assertTrue(all('最小动作' not in c['fact'] and '**' not in c['fact'] for c in cards))
 def test_chinese_introduction_matches_article_not_bundle_id(self):
  result={'research_text':'## 游戏内容与版本节点（EA 官方）\n- **Launch Feedback Update**：匹配问题已修复，仍在监控转会市场。\n- **Future Stars**：年轻球员卡根据真实联赛表现升级。\n\n### R5 官方内容准备\n- Future Stars：建议检查商品供给与发布入口。'}
  a,_=article_introduction(self.document('EA SPORTS FC™ 27 | Launch Feedback Update','fallback'),result)
  b,_=article_introduction(self.document('Football Ultimate Team™ 27 - Future Stars','fallback'),result)
  self.assertIn('匹配问题已修复',a);self.assertNotIn('联赛表现',a)
  self.assertIn('联赛表现升级',b);self.assertNotIn('建议检查',b)
 def test_other_release_version_is_not_used_as_introduction(self):
  doc=self.document('EA SPORTS FC™ 27 | Title Update v1.0.4','October 7, 2026 No gameplay balance changes. Match errors were addressed.')
  text,basis=article_introduction(doc,{'research_text':'## 官方版本\n- TU v1.0.3/v1.0.4 改进职业模式多个问题。'})
  self.assertIn('中文内容简介尚未生成',text);self.assertNotIn('职业模式',text)
 def test_article_table_uses_introduction_not_action_column(self):
  text='## 游戏情报（官方）\n| 发布日 | 文章标题 | 内容简介 | 建议行动 |\n|---|---|---|---|\n| 10-09 | Future Stars | 年轻球员卡根据联赛表现升级，学院进化回归。 | 最小动作：核对供给，复查时间：明日。 |'
  fact,_=article_introduction(self.document('Football Ultimate Team™ 27 - Future Stars','fallback'),{'research_text':text})
  self.assertIn('联赛表现升级',fact);self.assertNotIn('最小动作',fact);self.assertNotIn('复查时间',fact)
 def test_old_article_table_has_source_bound_chinese_introduction(self):
  text='## 专题：游戏内容与版本节点\n| 发布日 | 事件 | 与业务的关系 |\n|---|---|---|\n| 10-13 | Launch Feedback Update | 确认匹配问题已在10-09修复，仍监控市场。 |'
  fact,_=article_introduction(self.document('EA SPORTS FC™ 27 | Launch Feedback Update','fallback'),{'research_text':text})
  self.assertIn('匹配问题',fact);self.assertNotIn('fallback',fact)

class PartialProjection(unittest.TestCase):
 def test_single_day_reference_uses_validated_day_total_without_day_group(self):
  from decimal import Decimal
  from report_constraints import estimated_profit
  main=self.evidence();eid='ev_'+'f'*24
  record={'date':'2026-10-15','status':'available','stale':False,'currency':'USD','source':'order.p2pah.cn','profileKey':'FC27','timezone':'Asia/Shanghai','marginUnit':'percent',
          'period':{'start':'2026-10-15 00:00','end':'2026-10-16 00:00'},'scope':{'orderGameId':'1322','orderProductType':'','orderStatus':'','sites':'all-websites'},'profitMarginPct':20,'capturedAt':'2026-10-16T00:00:00Z'}
  reference={'source':'Order参考利润/历史','analysis_anchor_id':'fixture','data':{'status':'available','reference_only':True,'missingDays':[],
       'query':{'profile':'FC27','start':'2026-10-15','end':'2026-10-15'},'rows':[record]}}
  def estimate():return estimated_profit({eid:reference},'fixture','2026-10-15','2026-10-15',('ev_'+'a'*24,Decimal(100),Decimal(2),main),lambda _:True)
  self.assertEqual(estimate()['amount_usd'],'20.00');self.assertEqual(estimate()['reference_margin_percent'],'20')
  record['stale']=True;self.assertEqual(estimate()['status'],'missing')
 def evidence(self,day='2026-10-15',group=None):
  fact={'revenue_usd':'100','orders':2,'unpriced_orders':0}
  return {'source':'Admin FC支付明细','scope':'main','project':'FC27','snapshot_id':'fixture','timezone':'Asia/Shanghai','captured_at':'2026-10-16T00:00:00Z',
    'query':{'start':day,'end':day,'filters':{},'group_by':[group] if group else [],'page':1},
    'data':{'status':'available','coverage':{'paid_complete':True,'missing_days':[]},'pagination':{'complete':True,'page':1,'page_size':100,'total_groups':1 if group else 0},'filters_applied':{},'total':fact,
            'groups':[dict(fact,group={group:day if group=='day' else 'PS'})] if group else []}}
 def result(self):return {'period':{'start':'2026-10-15','end':'2026-10-15'},'snapshot_id':'fixture','summary':'本期有效，缺对照单独说明。','research_text':'## 关键判断\n本期有效。','limitations':[]}
 def test_current_survives_missing_comparison(self):
  evidence={'ev_'+'a'*24:self.evidence(),'ev_'+'b'*24:self.evidence(group='platform'),'ev_'+'c'*24:self.evidence(group='day')}
  content=project(self.result(),evidence,{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(content['metrics'][0]['value'],'$100.00')
  charts={v['id']:v for v in content['charts']}
  self.assertTrue(charts['platform']['rows']);self.assertTrue(charts['daily']['rows'])
  self.assertIsNone(charts['platform']['rows'][0]['previous'])
 def test_comparison_conflict_does_not_erase_current(self):
  result=self.result();result['research_text']='对照：2026-10-08\n对照：2026-10-14\n## 关键判断\n本期有效。'
  c=project(result,{'ev_'+'a'*24:self.evidence()},{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(c['metrics'][0]['value'],'$100.00');self.assertEqual(c['metrics'][0]['previous'],'未提供')
 def test_daily_primary_point_does_not_hide_fourteen_day_trend(self):
  from datetime import date,timedelta
  daily=self.evidence(group='day');daily['query']['start']='2026-10-02'
  daily['data']['groups']=[{'group':{'day':(date(2026,10,2)+timedelta(days=i)).isoformat()},'revenue_usd':'100','orders':2,'unpriced_orders':0} for i in range(14)]
  daily['data']['total']={'revenue_usd':'1400','orders':28,'unpriced_orders':0};daily['data']['pagination']['total_groups']=14
  evidence={'ev_'+'a'*24:self.evidence(),'ev_'+'b'*24:self.evidence('2026-10-14'),'ev_'+'c'*24:daily}
  result=self.result();result['comparison_period']={'start':'2026-10-14','end':'2026-10-14'}
  c=project(result,evidence,{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  trend=next(x for x in c['charts'] if x['id']=='daily')
  self.assertEqual(len(trend['rows']),14);self.assertEqual(len(trend['coverage']['observed_dates']),14)
  self.assertEqual(trend['period_basis'],'observed_daily_series');self.assertEqual(trend['labels'][1],'2026-10-02 — 2026-10-15')
  self.assertEqual(c['report']['period']['comparison_start'],'2026-10-14')
 def test_missing_primary_margin_keeps_previous_day_separately(self):
  def estimate(evidence,anchor,start,end,total,eligible):
   base={'period':{'start':start,'end':end},'evidence_ids':[]}
   if start=='2026-10-08':return dict(base,status='missing',reason='fixture missing primary rate')
   return dict(base,status='estimated',reference_margin_percent='20',amount_usd='20',main_revenue_usd='100',sources=[],formula='fixture')
  with patch('report_constraints.estimated_profit',side_effect=estimate):
   c=project(self.result(),{'ev_'+'a'*24:self.evidence(),'ev_'+'b'*24:self.evidence('2026-10-14'),'ev_'+'e'*24:self.evidence('2026-10-08')},{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(c['report']['period']['comparison_start'],'2026-10-08')
  self.assertEqual(c['finance']['estimates']['previous']['status'],'missing')
  self.assertEqual(c['finance']['estimates']['previous_day']['period']['start'],'2026-10-14')
  margin=next(x for x in c['charts'] if x['id']=='margin');self.assertEqual(margin['period_basis'],'previous_day_reference');self.assertIn('2026-10-14',margin['labels'][0])
 def test_payment_orders_survive_missing_primary_partition(self):
  e={'ev_'+'a'*24:self.evidence(),'ev_'+'b'*24:self.evidence('2026-10-14'),'ev_'+'c'*24:self.evidence(group='payment'),'ev_'+'d'*24:self.evidence('2026-10-14',group='payment'),'ev_'+'e'*24:self.evidence('2026-10-08')}
  c=project(self.result(),e,{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(c['payment_period']['start'],'2026-10-14');self.assertEqual(c['payment'][0]['current_orders'],2)
  self.assertEqual(c['report']['period']['comparison_start'],'2026-10-08')
 def test_module_judgments_are_from_model_and_full_text_is_collapsed(self):
  import boss_renderer
  headings=['销售与订单结论','平台与商品结论','客户、支付与未完成订单结论','利润与成本结论','游戏与市场情报结论']
  r=self.result();r['research_text']+=''.join('\n\n### '+h+'\n本模块的变化已有证据，优先核查主要变化的具体来源。' for h in headings)
  e={'ev_'+'a'*24:self.evidence()};c=project(r,e,{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(len(c['section_conclusions']),5)
  with patch.object(boss_renderer,'HERE',ROOT/'baseline'):html=boss_renderer.render(c,e)
  self.assertEqual(html.count('<b>经营判断：</b>'),5)
  self.assertNotIn('历史原文',html);self.assertNotIn('<details open class="research-body">',html)
  self.assertIn('<details class="research-body"><summary>完整研究阅读校正版',html)
  self.assertEqual(r['research_text'],c['research_text'])

if __name__=='__main__':unittest.main()
