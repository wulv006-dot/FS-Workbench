import sys,unittest,copy
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
  self.assertEqual(len(cards),2);self.assertNotEqual(cards[0]['fact'],cards[1]['fact'])
  self.assertIn('Matchmaking issue was fixed',cards[0]['fact']);self.assertIn('dynamic player items',cards[1]['fact'])
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
  self.assertIn('No gameplay balance changes',text);self.assertNotIn('职业模式',text)

class PartialProjection(unittest.TestCase):
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

if __name__=='__main__':unittest.main()
