import sys,unittest,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'baseline')]
from report_tracks import report_title,request_report_kind
import test_projection as fixtures
from boss_projection import project
from pricing_report import project as pricing_project

class TitlesAndGoals(unittest.TestCase):
 def test_types_and_single_or_range_dates(self):
  for period,kind,want in [({'start':'2026-10-15','end':'2026-10-15'},None,'FC27 2026-10-15 日报'),
   ({'start':'2026-10-05','end':'2026-10-11'},None,'FC27 2026-10-05 至 2026-10-11 周报'),
   ({'start':'2026-09-01','end':'2026-09-30'},None,'FC27 2026-09-01 至 2026-09-30 月报'),
   ({'start':'2026-10-15','end':'2026-10-15'},'pricing','FC27 2026-10-15 定价策略研究')]:
   self.assertEqual(report_title(period,kind),want)
 def facts(self):
  f=fixtures.PartialProjection();result=f.result();result['research_text']+='\n### 游戏与市场情报结论\n这是该模块独立经营判断，不能覆盖整份报告标题。'
  eid='ev_'+'a'*24;record=fixtures.GlobalFieldAuthority().record('order.p2pah.cn',20)
  rate={'analysis_anchor_id':'fixture','project':'FC27','timezone':'Asia/Shanghai','query':{'profile':'FC27','start':'2026-10-15','end':'2026-10-15'},'data':{'status':'available','source_contract':'admin-main-order-labelled-supplement-v1','source_records':{'order':record}}}
  return result,{eid:f.evidence(),'ev_'+'f'*24:rate,'ev_native':f.native()}
 def test_module_heading_does_not_overwrite_report_title(self):
  r,e=self.facts();out=project(r,e,{},'f'*64)
  self.assertEqual(out['report']['title'],'FC27 2026-10-15 日报')
  self.assertIn('intelligence',out['section_conclusions'])
 def test_target_analysis_keeps_its_type_in_the_title(self):
  r,e=self.facts();r['report_kind']='kpi'
  self.assertEqual(project(r,e,{},'f'*64)['report']['title'],'FC27 2026-10-15 经营目标分析')
 def test_estimated_profit_directly_compares_configured_target(self):
  r,e=self.facts();out=project(r,e,{'profit_target_snapshot':{'period':'2026-10','monthly_profit_usd':3100}},'f'*64)
  m=out['metrics'][3];self.assertEqual(m['value'],'20.0%');self.assertEqual(m['target_usd'],'100')
  self.assertEqual(m['actual_usd'],'20.00');self.assertIn('-80.00',m['delta'])
  import boss_renderer
  from unittest.mock import patch
  with patch.object(boss_renderer,'HERE',ROOT/'baseline'):html=boss_renderer.render(out,e)
  self.assertIn('参考利润 $20.00',html);self.assertIn('本期目标 $100.00',html)
 def test_missing_other_month_or_zero_target_is_not_invented(self):
  r,e=self.facts()
  for target in ({},{'period':'2026-09','monthly_profit_usd':3100},{'period':'2026-10','monthly_profit_usd':0}):
   out=project(r,e,{'profit_target_snapshot':target},'f'*64)
   self.assertEqual(out['metrics'][3]['status'],'missing')
 def test_pricing_title_uses_period_without_changing_track(self):
  r,e=self.facts();r['report_track']='pricing';out=pricing_project(r,e,{'report_track':'pricing'})
  self.assertEqual(out['report']['title'],'FC27 2026-10-15 定价策略研究')
 def test_general_html_title_and_heading_match(self):
  from report_html import render_report
  r={'report_format':'markdown','summary':'只读研究。','findings':[],'actions':[],'reviews':[],'number_claims':[],'limitations':[],'raw_model_text':'内容。'}
  out=render_report(r,{}, {'start':'2026-09-01','end':'2026-09-30'})
  self.assertIn('<h1>FC27 2026-09-01 至 2026-09-30 月报</h1>',out)
  self.assertIn('<title>FC27 2026-09-01 至 2026-09-30 月报</title>',out)

 def test_weekly_monthly_word_requirements_reach_actual_admission(self):
  import types,textwrap
  from datetime import date,timedelta
  source=(ROOT/'source/controller.py').read_text('utf8')
  a=source.index("            admission={'session_id'");b=source.index('            from background import task_context',a)
  for question in ('请生成周报','请生成月报'):
   ns={'prepared':None,'body':{'start':'2026-10-01','end':'2026-10-15','question':question,'mode':'investigation'},'session_id':'fixture','token':'fixture','effort':'max',
    'item_gateway':types.SimpleNamespace(budget=types.SimpleNamespace(policy={'model':'fixture'})),'book':types.SimpleNamespace(capture_id='fixture',skills={}),
    'knowledge':dict(version='v',identity={},files=[],memory_path='frozen',native_skip_reason='isolated'),'desktop_context':'memory','management':None,
    'FORMAT':'format','date':date,'timedelta':timedelta,'encoded':lambda x:json.dumps(x,ensure_ascii=False)}
   ns['request_report_kind']=request_report_kind
   exec(textwrap.dedent(source[a:b]),ns);text=ns['admission']['prompt']
   for required in ('经营数据','广告投放与SEO','不要求模拟网站体验','目标完成与下期目标','行动计划','CB拒付争议','FC只需最近30天','FC26上年同日期','主管支持','kind=native_loss','loss_groups.cb.count'):
    self.assertIn(required,text)
   if '月报' in question:self.assertIn('主对照：2026-09-16 至 2026-09-30',text)

 def test_month_to_date_kind_and_comparison_survive_projection(self):
  r,e=self.facts();r['period']={'start':'2026-10-01','end':'2026-10-15'};r['report_kind']='monthly'
  out=project(r,{}, {'artifact_written_at':'2026-10-16T08:00:00+00:00'},'f'*64)
  self.assertEqual(out['report']['kind'],'monthly')
  self.assertEqual(out['report']['title'],'FC27 2026-10-01 至 2026-10-15 月报')
  from report_html import render_report
  r.update(report_format='markdown',raw_model_text='月度累计。')
  self.assertIn('<title>FC27 2026-10-01 至 2026-10-15 月报</title>',render_report(r,{},r['period']))
 def test_recent30_capture_preserves_daily_default_and_comparison(self):
  import ast
  from datetime import date,timedelta
  tree=ast.parse((ROOT/'source/fs_evidence.py').read_text('utf8'))
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_book')
  assignment=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='read_start' for t in n.targets))
  expression=ast.Expression(assignment.value);ast.fix_missing_locations(expression)
  run=lambda a,b,n:eval(compile(expression,'window','eval'),{'lo':date.fromisoformat(a),'hi':date.fromisoformat(b),'recent_days':n,'timedelta':timedelta})
  self.assertEqual(run('2026-10-15','2026-10-15',14),'2026-10-02')
  self.assertEqual(run('2026-10-05','2026-10-11',30),'2026-09-12')
  self.assertEqual(run('2026-10-01','2026-10-15',30),'2026-09-16')
 def test_nightly_natural_periods_select_the_same_weekly_monthly_kind(self):
  self.assertEqual(request_report_kind({'start':'2026-10-05','end':'2026-10-11','mode':'investigation','question':'调查上个完整自然周FC经营变化。'}),'weekly')
  self.assertEqual(request_report_kind({'start':'2026-09-01','end':'2026-09-30','mode':'investigation','question':'调查上个完整自然月FC经营变化。'}),'monthly')
  self.assertEqual(request_report_kind({'start':'2026-10-01','end':'2026-10-15','mode':'investigation','question':'本月累计月报'}),'monthly')
  self.assertEqual(request_report_kind({'start':'2026-10-15','end':'2026-10-15','mode':'pricing','question':'定价策略'}),'pricing')
