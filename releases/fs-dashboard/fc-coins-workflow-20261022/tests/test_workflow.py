"""Fictional monetary cases and real SQLite ownership; no external service or price writer."""
import ast,importlib.util,json,sqlite3,sys,tempfile,unittest
from contextlib import contextmanager,closing
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1]
def sibling(remote,local):return next(p for p in (HERE.parent/remote,HERE.parent/local) if p.exists())
sys.path[:0]=[str(HERE/'source'),str(sibling('hermes-fc-pilot-20261013','hermes_fc_pilot_20261013')),str(sibling('fs-business-baseline-20261021','fs_business_baseline_20261021')/'source'),str(sibling('fc-coins-evidence-20261021','fs_coins_evidence_20261021')/'source'),str(sibling('hermes-report-repair-20261019','fs_hermes_report_repair_20261019')/'source')]
from pricing_workflow import Workflow,evaluate,current_accounting,number,SOURCE,VERSION,schema
from pilot import digest,encoded
import learning_service as learning
import learning_registry as registry

def case():
 return dict(currency='USD',delivered_cost_includes_gifts=True,historical_retained_ratio='1',platforms=[dict(platform=p,current_usd='10.00',main_usd='9.20',delivered_cost_usd=c) for p,c in [('PS','7'),('XBOX','7'),('PC','5')]],discounts_pct=['0','5'])

class Arithmetic(unittest.TestCase):
 def test_estimated_average_is_a_second_floor_even_with_safe_base(self):
  c=case();c['historical_retained_ratio']='0.8';v=evaluate(c,'10')
  self.assertGreater(Decimal(v['rows'][0]['undiscounted']['main']['procurement_margin_pct']),10)
  self.assertFalse(v['console_main_pass']);self.assertIsNone(v['rows'][0]['selected_usd'])
  del c['historical_retained_ratio']
  with self.assertRaisesRegex(ValueError,'case_fields'):evaluate(c,'10')
 def test_main_change_is_not_limited_by_ending_budget(self):
  v=evaluate(case(),'10');self.assertTrue(v['console_main_pass']);self.assertEqual(v['rows'][0]['main_change_pct'],'-8.00');self.assertEqual(v['rows'][0]['selected_usd'],'9.20')
 def test_legal_promotion_can_cross_floor_but_base_price_cannot(self):
  c=case()
  for r in c['platforms'][:2]:r['delivered_cost_usd']='8'
  v=evaluate(c,'10')
  self.assertTrue(v['console_main_pass']);self.assertTrue(v['rows'][0]['transactions'][1]['main']['floor_pass']);self.assertLess(Decimal(v['rows'][0]['transactions'][1]['main']['procurement_margin_pct']),10)
  for r in c['platforms'][:2]:r['main_usd']='8.80'
  v=evaluate(c,'10');self.assertFalse(v['console_main_pass']);self.assertEqual([r['selected_usd'] for r in v['rows'][:2]],[None,None]);self.assertIsNotNone(v['rows'][2]['selected_usd'])
 def test_coupon_does_not_expand_base_ending_budget(self):
  c=case();c['discounts_pct']=['0','10']
  for r in c['platforms']:r.update(main_usd='10.09',delivered_cost_usd='7.90')
  v=evaluate(c,'10');r=v['rows'][0]
  self.assertTrue(r['ending_preview']['reason']=='applied');self.assertTrue(r['transactions'][1]['ending']['floor_pass'])
  self.assertTrue(r['transactions'][1]['ending_budget_pass']);self.assertEqual(r['selected_usd'],'9.99')
 def test_full_discount_loss_is_not_a_base_floor_failure(self):
  c=case();c['discounts_pct']=['0','30','100']
  v=evaluate(c,'10');r=v['rows'][0]
  self.assertTrue(r['main_pass']);self.assertLess(Decimal(r['transactions'][1]['main']['procurement_gross_usd']),0)
  self.assertEqual(r['transactions'][2]['main']['net_usd'],'0.00');self.assertIsNone(r['transactions'][2]['main']['procurement_margin_pct']);self.assertTrue(r['transactions'][2]['main']['floor_pass'])
 def test_one_console_ending_failure_retains_common_main(self):
  c=case()
  for r in c['platforms']:r['main_usd']='10.09'
  for r in c['platforms'][:2]:r['delivered_cost_usd']='8.6'
  v=evaluate(c,'10');self.assertEqual([r['selected_usd'] for r in v['rows'][:2]],['10.09','10.09'])
 def test_already_99_never_falls_another_dollar(self):
  c=case()
  for r in c['platforms']:r['main_usd']='109.99'
  self.assertTrue(all(r['selected_usd']=='109.99' for r in evaluate(c,'10')['rows']))
 def test_main_raise_can_end_below_actual_original_price(self):
  c=case();c['discounts_pct']=['0','8']
  for r,cost in zip(c['platforms'],['12.6','12.6','8.1']):r.update(current_usd='18.00',main_usd='18.09',delivered_cost_usd=cost)
  v=evaluate(c,'10');r=v['rows'][0];self.assertGreater(Decimal(r['main_change_pct']),0);self.assertEqual(r['selected_usd'],'17.99');self.assertEqual(r['selected_direction'],'down');self.assertLess(Decimal(r['selected_change_pct']),0)
 def test_gross_and_ad_contribution_and_ceiling(self):
  c=case();c['economics']={'before':dict(orders=100,net_unit_usd='10',delivered_cost_unit_usd='6',ads_usd='100'),'after':dict(orders=120,net_unit_usd='9',delivered_cost_unit_usd='6',ads_usd='150')}
  v=evaluate(c,'10')['economics'];self.assertEqual(v['totals']['before']['procurement_gross_usd'],'400');self.assertEqual(v['totals']['after']['ad_after_contribution_usd'],'210');self.assertEqual(v['minimum_whole_orders'],150)
  c['economics']['after']['ads_usd']='151';self.assertEqual(evaluate(c,'10')['economics']['minimum_whole_orders'],151)
  c['economics']['after']['ads_usd']=None;v=evaluate(c,'10')['economics'];self.assertIsNone(v['break_even_orders']);self.assertEqual(v['procurement_minimum_whole_orders'],134)
 def test_different_console_costs_are_source_conflict_not_platform_policy(self):
  c=case();c['platforms'][1]['delivered_cost_usd']='8'
  with self.assertRaisesRegex(ValueError,'console_common_cost'):evaluate(c,'10')
  m={'fx':{'status':'available','cny_per_usd':'7'},'costs':[dict(platform=p,status='available',cny_per_1k=v) for p,v in [('PS','0.7'),('XBOX','0.8')]],'storefront':{'rows':[dict(platform=p,status='available',base_k='100',bonus_k='5',gross_usd='15') for p in ('PS','XBOX')]}}
  v=current_accounting(m,'10');self.assertEqual(v['rows'],[]);self.assertEqual(v['console_common_cost_status'],'source_reconciliation_required');self.assertEqual(len(v['console_cost_observations']),2)
 def test_untrusted_fields_and_number_forms(self):
  for n in (True,1,'1e2','NaN','Infinity',' 1','-1','1000000000001','0.00000000001'):
   with self.assertRaises(ValueError):number(n)
  for field,value in [('minimum_margin','0'),('currency','CNY'),('delivered_cost_includes_gifts',False)]:
   c=case();c[field]=value
   with self.assertRaises(ValueError):evaluate(c,'10')
  c=case();c['platforms'][0]['main_usd']='9.201'
  with self.assertRaises(ValueError):evaluate(c,'10')
 def test_current_uses_delivered_gift_and_valid_fx_once(self):
  m={'fx':{'status':'available','cny_per_usd':'7'},'costs':[dict(platform='PS',status='available',cny_per_1k='0.7')],'storefront':{'rows':[dict(platform='PS',status='available',base_k='100',bonus_k='5',gross_usd='15')]}}
  r=current_accounting(m|{'costs':m['costs']+[dict(m['costs'][0],platform='XBOX')]},'10')['rows'][0];self.assertEqual(r['delivered_cost_usd'],'10.5');self.assertEqual(r['procurement_gross_usd'],'4.5')
  m['fx']['status']='unusable';self.assertEqual(current_accounting(m,'10')['rows'],[])

class Sources(unittest.TestCase):
 def setUp(self):
  self.q=dict(profile='FC27',action='review',start='2026-10-14',end='2026-10-20');self.calls=[];self.pending=True
  def call(name,args):
   self.calls.append((name,dict(args)));data={'status':'available'}
   if name=='fc.query_pricing_evidence' and args['kind']=='price_history':data.update(events=[args.get('page',1)],pagination=dict(has_more=args.get('page',1)==1,total_events=2))
   if name=='fc.query_pricing_evidence' and args['kind']=='order_costs':data.update(summary=dict(completedOrders=2,coveredOrders=1,missingCostOrders=1,saleCny=20,costCny=10,profitCny=10),quality_checks={'covered_profit_identity':True})
   if name=='fc.query_marketing_snapshot' and self.pending:data['status']='pending'
   ident='ev_'+digest([name,args,data])[:24];record=dict(evidence_id=ident,source=name,query=args,data=data);self.book.evidence[ident]=record
   return dict(record,data={'status':data['status'],'model_view_omitted':True})
  self.book=SimpleNamespace(call=call,evidence={});bridge=SimpleNamespace(baseline=lambda:(None,{'minimum_gross_margin_pct':'10'},{'revision':40,'sha256':'a'*64}))
  self.flow=Workflow(self.book,bridge)
 def test_pending_repoll_then_full_records_freeze_and_hash(self):
  a=self.flow(self.q);self.assertEqual(a['status'],'pending');self.pending=False;b=self.flow(self.q);self.assertEqual(b['status'],'partial')
  self.assertTrue(b['checks']['execution_pages_complete']);self.assertEqual(b['checks']['execution_events'],2);self.assertEqual(b['procurement_accounting']['profitCny'],10)
  self.assertEqual(b['procurement_revenue_basis'],'legacy_delivery');self.assertIn('admin_order_revenue_backfill_pending',b['gaps'])
  self.assertEqual(b['receipt_sha256'],digest({k:v for k,v in b.items() if k!='receipt_sha256'}));n=len(self.calls);self.assertEqual(self.flow(self.q),b);self.assertEqual(len(self.calls),n)
  self.assertFalse(b['execution_authorized']);self.assertFalse(b['existing_automation_changed']);self.assertIsNone(b['ad_after_contribution']['value'])
  self.assertIsNotNone(datetime.fromisoformat(b['captured_at']).tzinfo);self.assertEqual(len(b['workflow_sha256']),64)
 def test_v3_removed_load_returns_retired_receipt_without_triggering_evaluation(self):
  self.pending=False;read=self.book.call
  def call(name,args):
   row=read(name,args)
   if name=='fc.query_market_snapshot':self.book.evidence[row['evidence_id']]['data']['storefront']={'collection_run_id':'saved-snapshot'}
   return row
  self.book.call=call
  self.flow.bridge.evaluate=lambda *a: self.fail('must not start another evaluation')
  value=self.flow(self.q)
  self.assertEqual(value['original_engine_baseline'],{'status':'not_available','reason':'legacy_engine_baseline_retired_use_v3_pricing_control'})
  self.assertEqual(value['status'],'partial');self.assertFalse(value['write_performed']);self.assertFalse(value['execution_authorized'])
  self.assertTrue(value['source_refs']['market'])
 def test_isolated_legacy_bridge_load_contract_is_preserved(self):
  self.pending=False;read=self.book.call;calls=[]
  def call(name,args):
   row=read(name,args)
   if name=='fc.query_market_snapshot':self.book.evidence[row['evidence_id']]['data']['storefront']={'collection_run_id':'saved-snapshot'}
   return row
  self.book.call=call
  def load(*args):
   calls.append(args);return None,{'historical':'isolated'},['original-ref']
  self.flow.bridge.load=load
  value=self.flow(self.q)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],'saved-snapshot')
  self.assertEqual(value['original_engine_baseline']['status'],'available')
  self.assertEqual(value['original_engine_baseline']['calculation'],{'historical':'isolated'})
 def test_strict_tool_boundary(self):
  for q in (dict(self.q,url='http://bad'),dict(self.q,action='write'),dict(self.q,case=case()),dict(self.q,action='scenario'),dict(self.q,profile='ALL')):
   with self.assertRaises(ValueError):self.flow(q)
  v=self.flow(dict(self.q,action='scenario',case=case()));self.assertEqual(v['source_kind'],'declared_hypothesis');self.assertEqual(schema()['function']['name'],'mcp__fcro__fc_run_pricing_workflow')

class Learning(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'conversations').mkdir();self.source='a'*32;self.now=datetime.now(timezone.utc)
  with closing(sqlite3.connect(self.root/'conversations/conversations.db')) as db:
   db.executescript('CREATE TABLE conversations(id TEXT,owner TEXT); CREATE TABLE turns(id TEXT,conversation_id TEXT,state TEXT,task_id TEXT,text TEXT,run_id TEXT); CREATE TABLE events(seq INTEGER,turn_id TEXT,type TEXT,payload TEXT);')
   db.execute('INSERT INTO conversations VALUES(?,?)',('conv','wulv'));db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?)',(self.source,'conv','completed','task','question','run_real'));db.execute('INSERT INTO events VALUES(?,?,?,?)',(1,self.source,'run.completed',encoded({'output':'先查同范围来源，之后比较候选，并列出反证。'})))
   db.commit()
  self.task=dict(state='SUCCEEDED',spec={'snapshot_id':'fc-detail-conversation-'+self.source})
  self.db=sqlite3.connect(self.root/'tasks.sqlite3');self.db.row_factory=sqlite3.Row;self.db.execute('CREATE TABLE evidence(task_id TEXT,content TEXT)');self.addCleanup(self.db.close)
  @contextmanager
  def db():
   yield self.db
   self.db.commit()
  def get(ident,owner):
   if owner!='wulv' or ident!='task':raise PermissionError('task_not_found')
   return deepcopy(self.task)
  self.service=SimpleNamespace(root=self.root,tasks=SimpleNamespace(db=db,get=get),get_job=lambda *a:None,clock=lambda:self.now)
 def test_completed_conversation_is_owned_and_actual_output_required(self):
  v=learning.conversation_source(self.service,'wulv',self.source);self.assertIn('先查',v['report']['research_text']);self.assertEqual(v['job']['result']['run_id'],'run_real')
  for owner,source in [('DY',self.source),('wulv','../escape'),('wulv','b'*32)]:
   with self.assertRaises(PermissionError):learning.conversation_source(self.service,owner,source)
  for state in ('RUNNING','FAILED','CANCELLED'):
   self.task['state']=state
   with self.assertRaises(PermissionError):learning.conversation_source(self.service,'wulv',self.source)
 def test_original_learning_queue_uses_distinct_source_kind_idempotently(self):
  record=dict(evidence_id='ev_fixed',source=SOURCE,query={},data={'workflow_version':VERSION})
  self.db.execute('INSERT INTO evidence VALUES(?,?)',('task',encoded(record)))
  with patch.dict(sys.modules,report_artifacts=SimpleNamespace(),report_method=SimpleNamespace(HTML_DESIGN_MANIFEST_SHA256='b'*64)),patch.object(learning,'review_evidence',return_value={'coverage':{'complete':False}}),patch.object(learning,'visible_result',side_effect=lambda r:{'text':r['research_text']}):
   a=learning.enqueue_workflow_completed(self.service,'wulv',self.source,'task');b=learning.enqueue_workflow_completed(self.service,'wulv',self.source,'task')
  self.assertEqual(a['id'],b['id']);self.assertEqual(a['state'],'queued');self.assertEqual(a['event_type'],'completed_conversation');snapshot=json.loads(a['input']);self.assertEqual(snapshot['task_id'],'task');self.assertTrue(snapshot['evidence_refs'][-1].startswith('conversation:'))
  self.assertEqual(registry.manifest(self.db,'wulv','FS',self.now)['experiences'],[])
 def test_only_workflow_conversations_autoqueue(self):
  self.assertEqual(learning.enqueue_workflow_completed(self.service,'wulv',self.source,'task')['state'],'not_applicable')
 def test_original_completed_report_and_foreign_denial_are_retained(self):
  self.service.get_job=lambda *a:dict(owner='wulv',state='COMPLETED',task_id='task',body={'question':'old report'},result={'artifact_sha256':'d'*64})
  with patch.dict(sys.modules,report_artifacts=SimpleNamespace(read_file=lambda *a:{'content':encoded({'summary':'original report'})}),report_method=SimpleNamespace(HTML_DESIGN_MANIFEST_SHA256='b'*64)),patch.object(learning,'review_evidence',return_value={}),patch.object(learning,'visible_result',side_effect=lambda r:{'text':r['summary']}):
   v=learning.source_snapshot(self.service,'wulv',self.source);self.assertEqual(v['source_kind'],'completed_report');self.assertEqual(v['visible_result']['text'],'original report');self.assertTrue(v['evidence_refs'][-1].startswith('report:'))
   with self.assertRaises(PermissionError):learning.source_snapshot(self.service,'DY',self.source)
 def test_candidate_stays_unpublished_until_CAS_release_and_can_revoke(self):
  private=patch.dict(sys.modules,report_delivery=SimpleNamespace(private_report=lambda _:False));private.start();self.addCleanup(private.stop)
  source={'source_kind':'completed_conversation','evidence_refs':['ev_fixed']};base=registry.manifest(self.db,'wulv','FS',self.now)
  event=registry.enqueue(self.db,'wulv','FS',self.source,base['sha256'],'completed_conversation',source);attempt=registry.claim(self.db,'wulv','FS',event['id'])
  candidate=dict(kind='experience',lesson='先读取固定核算回执，再区分可行性与收益条件，并列反证。',applies_to='金币候选比较',evidence_refs=['ev_fixed'],counterexample='输入覆盖不全时只保留条件，不能据可行性断言增利。',expires_at=(self.now+timedelta(days=30)).isoformat())
  result=registry.candidate(self.db,'wulv','FS',event['id'],attempt,candidate,self.now);ident=result.get('id') or result['candidate']
  self.assertEqual(registry.manifest(self.db,'wulv','FS',self.now)['experiences'],[])
  with self.assertRaises(ValueError):registry.release(self.db,'wulv','FS',ident,'f'*64,'published','wulv','test',self.now)
  registry.release(self.db,'wulv','FS',ident,base['sha256'],'published','wulv','reviewed test',self.now);published=registry.manifest(self.db,'wulv','FS',self.now);self.assertEqual(len(published['experiences']),1)
  registry.release(self.db,'wulv','FS',ident,published['sha256'],'revoked','wulv','rollback test',self.now);self.assertEqual(registry.manifest(self.db,'wulv','FS',self.now)['experiences'],[])
 def test_review_projection_keeps_machine_scenario_not_raw_input(self):
  data=dict(workflow_version=VERSION,receipt_sha256='c'*64,write_performed=False,execution_authorized=False,source_kind='declared_hypothesis',scenario=evaluate(case(),'10'),raw_orders=[{'email':'private@example.invalid'}])
  # Only the unrelated private-data classifier is isolated here; projection and bounds are real.
  with patch.dict(sys.modules,report_delivery=SimpleNamespace(private_report=lambda s:'private@example' in s)):
   v=learning.review_evidence([dict(evidence_id='ev_flow',source=SOURCE,query={},data=data)])
  self.assertEqual(v['items'][0]['values']['pricing_workflow']['scenario']['basis'],'declared_hypothesis');self.assertNotIn('private@example',encoded(v))
 def test_changed_core_contract_blocks_old_candidate_publish(self):
  self.service.authorizer=lambda user:user=='wulv'
  with patch.dict(sys.modules,report_delivery=SimpleNamespace(private_report=lambda _:False),report_method=SimpleNamespace(HTML_DESIGN_MANIFEST_SHA256='b'*64)):
   base=registry.manifest(self.db,'wulv','FS',self.now);event=registry.enqueue(self.db,'wulv','FS',self.source,base['sha256'],'completed_conversation',{'evidence_refs':['ev_fixed'],'method_manifest_sha256':'b'*64,'business_baseline':{'version':'superseded','sha256':'f'*64}});attempt=registry.claim(self.db,'wulv','FS',event['id'])
   c=dict(kind='experience',lesson='先核口径，再比较。',applies_to='候选比较',evidence_refs=['ev_fixed'],counterexample='不同范围不能合并。',expires_at=(self.now+timedelta(days=30)).isoformat());v=registry.candidate(self.db,'wulv','FS',event['id'],attempt,c,self.now)
   self.db.commit();status,result=learning.handle(self.service,'wulv',dict(kind='hermes_learning',action='publish',id=v.get('id') or v['candidate'],expected_manifest=base['sha256'],reason='test'))
  self.assertEqual(status,409);self.assertEqual(result['error'],'experience_business_baseline_conflict');self.assertEqual(registry.manifest(self.db,'wulv','FS',self.now)['experiences'],[])

class Wiring(unittest.TestCase):
 def test_native_reader_accepts_paid_contract_and_rejects_completed_only_summary(self):
  tree=ast.parse((HERE/'source/fs_evidence.py').read_text('utf8'))
  ns=dict(datetime=datetime,timezone=timezone,authoritative_native_fields=lambda *args:{'orders':{'value':2}})
  exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='live_native_statistics'],type_ignores=[]),'native-contract-test','exec'),ns)
  for contract in ('admin-paid-order-labelled-supplement-v2','admin-main-order-labelled-supplement-v1'):
   read=lambda params:(200,dict(scopeContractId=contract,status='available',profile={},sources={}))
   if contract.endswith('v2'):
    value=ns['live_native_statistics'](read,{'profile':'FC27','start':'2026-10-27','end':'2026-10-27'})
    self.assertEqual(value['source_contract'],contract);self.assertEqual(value['authoritative_fields']['orders']['value'],2)
   else:
    with self.assertRaisesRegex(ValueError,'native_source_contract'):ns['live_native_statistics'](read,{})
 def test_archived_cost_tool_does_not_start_live_paid_read(self):
  tree=ast.parse((HERE/'source/fs_evidence.py').read_text('utf8'));calls=[];paid=[]
  ns={'AsyncRead':lambda reader:SimpleNamespace(get=lambda:paid.append('read') or {'status':'pending','reason':'source_read_running'})}
  exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='lazy_paid_capture'],type_ignores=[]),'lazy-paid-test','exec'),ns)
  def call(name,args):calls.append((name,args));return {'status':'partial','revenue_basis':'admin_order_cny','platform_unknown_orders':2}
  book=SimpleNamespace(call=call,data={'coverage':{'status':'not_loaded'}})
  ns['lazy_paid_capture'](book,None,{'enabled':True})
  v=book.call('fc.query_pricing_evidence',{'kind':'order_costs'})
  self.assertEqual(v['revenue_basis'],'admin_order_cny');self.assertEqual(v['platform_unknown_orders'],2);self.assertEqual(paid,[])
  self.assertEqual(book.call('fc.query_business',{})['status'],'pending');self.assertEqual(paid,['read']);self.assertEqual(len(calls),1)
 def test_all_callers_retain_original_tools_and_guards(self):
  for p in (HERE/'source').glob('*.py'):ast.parse(p.read_text('utf8'))
  text=(HERE/'source/research.py').read_text('utf8');self.assertIn("'fc.query_pricing_evidence','fc.run_pricing_workflow'",text)
  self.assertIn('workflow_schema()',text);self.assertIn("self.config.get('enabled') is True",text)
  self.assertIn("body['mode']=='pricing'",(HERE/'source/controller.py').read_text('utf8'))
  self.assertIn("if state=='completed' and task_id:",(HERE/'source/conversation_service.py').read_text('utf8'))
  self.assertIn("tasks.get(snapshot['task_id'],owner)",(HERE/'source/strategy_tools.py').read_text('utf8'))
  self.assertIn('business-baseline-20261021-v10',(HERE/'source/business-baseline.md').read_text('utf8'))

if __name__=='__main__':unittest.main()
