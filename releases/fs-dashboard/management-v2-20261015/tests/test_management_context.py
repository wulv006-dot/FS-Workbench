import sys,unittest,json,tempfile,copy
from pathlib import Path
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'source/backend'),str(Path(__file__).resolve().parents[1]/'baseline')]
import management_context as m
import nightly
class Context(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'facts').mkdir()
  self.facts={'contract':'fs-management-daily-v2','timezone':'Asia/Shanghai','businessDate':'2026-10-15','generatedAt':'2026-10-15T00:30:00+08:00','validUntil':'2026-10-16T00:00:00+08:00','targetVersion':'a'*64,'targetPeriod':'2026-10','period':{'start':'2026-10-01','end':'2026-10-14'},'profitPolicy':'预估非实结','forecastMethod':'线性情景','status':'available','projects':[{'profile':'FC27','name':'FC27','group':'球类','owner':'项目负责人','month':{'values':{'rev':100}},'yesterday':{'values':{'rev':10}},'targets':{'rev':200},'daily':[]}]}
  self.facts['snapshotId']='management-'+m.digest(self.facts)[:24];self.path=self.root/'facts'/(self.facts['snapshotId']+'.json');self.path.write_text(m.encoded(self.facts));self.path.chmod(0o600)
  self.body={'mode':'kpi','question':m.MARKER+' 分析 '+self.facts['snapshotId'],'start':'2026-10-01','end':'2026-10-14'}
 def test_other_jobs_unchanged(self):
  self.assertIsNone(m.request_snapshot({'mode':'daily','question':'普通FC日报'}));self.assertIsNone(m.load({'mode':'kpi','question':'普通KPI'},self.root))
 def test_load_period_and_hash(self):
  self.assertEqual(m.load(self.body,self.root)['snapshotId'],self.facts['snapshotId'])
  body=dict(self.body,end='2026-10-13')
  with self.assertRaises(ValueError):m.load(body,self.root)
  changed=copy.deepcopy(self.facts);changed['projects'][0]['month']['values']['rev']=999;self.path.write_text(m.encoded(changed))
  with self.assertRaisesRegex(ValueError,'snapshot_hash'):m.load(self.body,self.root)
 def test_symlink_denied(self):
  other=self.root/'other';self.path.rename(other);self.path.symlink_to(other)
  with self.assertRaisesRegex(ValueError,'boundary'):m.load(self.body,self.root)
 def test_frozen_data_evidence_scope_and_existing_calculator_paths(self):
  book=SimpleNamespace(capture_id='fc-detail-test',evidence={},trace=[]);context=m.attach(book,self.body,self.root)
  ev=context['evidence'];self.assertEqual(ev['project'],'ALL_MANAGEMENT_PROJECTS');self.assertEqual(len(book.evidence),1);self.assertIn(ev['evidence_id'],context['prompt']);self.assertNotIn('new_token',context)
 def test_scheduled_question_current_day_only(self):
  p=self.root/'public.json';p.write_text(m.encoded(self.facts));now=datetime(2026,10,15,1,tzinfo=m.SH)
  self.assertIn(self.facts['snapshotId'],m.scheduled_question(now,p))
  with self.assertRaises(ValueError):m.scheduled_question(now+timedelta(days=1),p)
 def result(self):
  ev='ev_'+'a'*24
  return {'numeric_checks':{'month_revenue':100.0,'target_revenue':200.0},'summary':'先处理 FC27 目标缺口。','research_text':'## 关键判断\n实际100，目标200，需验证近期转化。','management_context':{'evidenceId':ev},'actions':[{'target':'FC27｜复购转化','action':'对昨日未完成购买的已授权营销人群检查漏斗。','role':'项目运营','success_check':'对比次日转化，未提升则停止扩大。','evidence_ids':[ev]}],'findings':[{'statement':'FC27：当前收入距目标仍有缺口。'}],'limitations':['利润为参考估算'],'reasoning_effort':'high'}
 def test_publish_same_snapshot_once_and_expire(self):
  p=self.root/'public.json';p.write_text(m.encoded(self.facts));now=datetime(2026,10,15,1,tzinfo=m.SH)
  self.assertTrue(m.publish(self.body,self.result(),'task1',root=self.root,public=p,now=now));raw=p.read_bytes();self.assertTrue(m.publish(self.body,self.result(),'task1',root=self.root,public=p,now=now));self.assertEqual(p.read_bytes(),raw)
  self.assertFalse(m.publish(self.body,self.result(),'task2',root=self.root,public=p,now=now+timedelta(days=1)))
 def test_insufficient_advice_not_success(self):
  out=m.analysis_from_result({'summary':'正常','research_text':'总体正常。'},self.facts,'task1',datetime(2026,10,15,1,tzinfo=m.SH));self.assertEqual(out['status'],'needs_review')
 def test_newer_facts_are_not_overwritten(self):
  p=self.root/'public.json';p.write_text(m.encoded(dict(self.facts,snapshotId='management-'+'b'*24)));before=p.read_bytes();self.assertFalse(m.publish(self.body,self.result(),'task1',root=self.root,public=p,now=datetime(2026,10,15,1,tzinfo=m.SH)));self.assertEqual(before,p.read_bytes())
 def test_nightly_window_and_existing_schedule(self):
  now=datetime(2026,10,19,2,tzinfo=m.SH);jobs=nightly.due(now)
  self.assertEqual([x['kind'] for x in jobs],['management','daily','weekly']);self.assertEqual(nightly.due(now.replace(hour=7)),[])
  weekly=next(x for x in jobs if x['kind']=='weekly');self.assertEqual((weekly['start'],weekly['end']),('2026-10-12','2026-10-18'))
  mg=jobs[0];self.assertEqual((mg['start'],mg['end']),('2026-10-01','2026-10-18'));self.assertEqual(nightly.closed_period(__import__('datetime').date(2026,11,1),'management'),('2026-10-01','2026-10-31'))
if __name__=='__main__':unittest.main()

class ManagementRuntime(unittest.TestCase):
 setUp=Context.setUp
 def test_no_fc_ingestion_needed(self):
  book=m.build_book(self.body,self.root);ctx=m.attach(book,self.body,self.root)
  self.assertEqual(book.capture_id,self.facts['snapshotId'])
  catalog=book.call('fc.get_data_catalog',{})
  self.assertEqual(catalog['scope'],'ALL_MANAGEMENT_PROJECTS')
  self.assertIn(ctx['evidence']['evidence_id'],catalog['evidence_ids'])
  self.assertEqual(book.call('fc.query_business',{})['reason'],'management_frozen_context_only')
  self.assertEqual(book.call('fc.get_business_snapshot',{'snapshot_id':book.capture_id,'window':'target'})['project'],'ALL_MANAGEMENT_PROJECTS')
 def test_mixed_continuation_rejected(self):
  for field in ('parent_report','continuation_from'):
   with self.assertRaisesRegex(ValueError,'mixed_request'):m.load(dict(self.body,**{field:'previous'}),self.root)
 def test_readiness_facts_ready_not_failed(self):
  public=self.root/'public';public.mkdir();now=datetime(2026,10,15,1,tzinfo=m.SH)
  (public/'game-monitor.status.json').write_text(json.dumps({'day':'2026-10-15','phase':'completed','status':'succeeded'}))
  mg={'day':'2026-10-15','phase':'completed','status':'facts_ready','fact_status':'available'}
  (public/'management.status.json').write_text(json.dumps(mg))
  marketing=self.root/'marketing.json';marketing.write_text(json.dumps({'completed_at_utc':'2026-10-14T16:10:00+00:00','steps':{'fetch':0},'publication_performed':True}))
  self.assertEqual(nightly.preparation_status(now,boss_root=self.root,marketing_record=marketing),(True,[]))
  mg['fact_status']='partial';(public/'management.status.json').write_text(json.dumps(mg))
  self.assertEqual(nightly.preparation_status(now,boss_root=self.root,marketing_record=marketing),(True,['management_facts_partial']))

class ToolDelivery(unittest.TestCase):
 setUp=Context.setUp
 def test_calculation_binds_real_management_evidence(self):
  book=m.build_book(self.body,self.root);ctx=m.attach(book,self.body,self.root);ev=ctx['evidence']['evidence_id']
  args={'operation':'multiply','values':['100','2'],'evidence_ids':[ev],'value_paths':[{'evidence_id':ev,'path':'/data/projects/0/month/values/rev'},None],'assumptions':['','情景：假设翻倍，并非预测']}
  out=book.call('fc.calculate',args);self.assertEqual(out['project'],'ALL_MANAGEMENT_PROJECTS');self.assertEqual(out['data']['basis'],'declared_scenario')
  args['values'][0]='999'
  self.assertEqual(book.call('fc.calculate',args)['code'],'calculation_operand_mismatch')
 def test_delivery_unknown_evidence_dropped(self):
  book=m.build_book(self.body,self.root);ctx=m.attach(book,self.body,self.root);ev=ctx['evidence']['evidence_id']
  raw={'report_contract':'fs-report-v2','summary':'经营判断','research_text':'正文','actions':[{'action':'可验证动作','evidence_ids':[ev]},{'action':'虚构引用','evidence_ids':['ev_'+'f'*24]}]}
  out=m.deliver(json.dumps(raw),book);self.assertEqual(len(out['actions']),1);self.assertEqual(out['actions'][0]['action'],'可验证动作');self.assertTrue(out['limitations'])
  out=m.deliver('未结构化正文',book);self.assertEqual(out['delivery_status'],'raw_saved');self.assertEqual(out['actions'],[])

class VerifiedRollups(unittest.TestCase):
 setUp=Context.setUp
 def test_decimal_totals_and_month_independent_of_daily_gaps(self):
  f=copy.deepcopy(self.facts);f['projects'][0]['daily']=[{'d':'2026-10-02','rev':None,'ord':None}]
  p=copy.deepcopy(f['projects'][0]);p.update(profile='SECOND',group='另一组');p['month']['values']['rev']=.1;p['targets']['rev']=.2;f['projects'].append(p)
  out=m.projection(f)
  self.assertEqual(out['verifiedRollups']['all']['month']['rev'],100.1)
  self.assertEqual(out['verifiedRollups']['all']['targets']['rev'],200.2)
  self.assertEqual(len(out['verifiedRollups']['groups']),2)
  self.assertIn('独立',out['monthBasis']);self.assertEqual(out['projects'][0]['dailyCoverage']['available'],0)
 def test_wrong_totals_require_review(self):
  result=Context.result(self);result['numeric_checks']['target_revenue']=199
  self.assertEqual(m.analysis_from_result(result,self.facts,'task1',datetime(2026,10,15,1,tzinfo=m.SH))['status'],'needs_review')

class ModelEnvelope(unittest.TestCase):
 def test_prose_then_one_json_only(self):
  value={'report_contract':'fs-report-v2','summary':'结论','research_text':'正文','numeric_checks':{'month_revenue':1,'target_revenue':2}}
  self.assertEqual(m.decode_management_output('本次仅使用冻结数据。\n'+json.dumps(value)),value)
  for text in ['{} {}','前言 '+json.dumps(value)+' {}','{bad}',json.dumps(value)+'尾部另一个结论']:
   with self.assertRaises((ValueError,TypeError)):m.decode_management_output(text)

class FinalProseRecovery(unittest.TestCase):
 def test_unescaped_quotes_preserve_prose_and_strict_numbers(self):
  raw='前言\n{"report_contract":"fs-report-v2","numeric_checks":{"target_revenue":2},"research_text":"他说"变化"并非因果。\\n下一行"}'
  v=m.decode_management_output(raw);self.assertEqual(v['research_text'],'他说"变化"并非因果。\n下一行');self.assertEqual(v['numeric_checks']['target_revenue'],2)
  with self.assertRaises(ValueError):m.decode_management_output(raw.replace('"target_revenue":2','"target_revenue":bad'))
