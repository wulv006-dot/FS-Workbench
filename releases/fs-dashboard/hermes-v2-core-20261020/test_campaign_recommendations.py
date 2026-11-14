from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util
import ast
import os
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'AGENTS.md').exists())
sys.path.insert(0,str(HERE/'source'))
if 'pilot' not in sys.modules:
 spec=importlib.util.spec_from_file_location('pilot',ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013/pilot.py')
 module=importlib.util.module_from_spec(spec);sys.modules['pilot']=module;spec.loader.exec_module(module)
from pilot import TaskStore
from campaign_recommendations import CampaignRecommendations, CampaignRecommendationScope, checked_input, output_schema, PROMPT

@contextmanager
def guard(*args):yield True

def legacy_input():
 return dict(source_revision='7',sbc_update=dict(id='update-7',observed_at='2026-11-09T09:00:00+00:00',expires_at=None,context='Synthetic update',sources=[]),
  pages=[dict(page_id=page,product_keys=['fc-player-ps'],**({'core_product_keys':[]} if page=='fc27-sbc' else {})) for page in ('fc27-trio','fc27-weekly','fc27-sbc')],
  catalog=[dict(key='fc-player-ps',title='Synthetic player',product_ref=dict(site_id='266',game_id='1327',goods_id='12'),platform=dict(code='ps',attribute_id='21587'),available=False,binding_state='unknown')])

def input_data():
 from test_campaign_weekly import pool_input
 value=pool_input();value['sbc_update']['id']='update-7'
 return value

def current_selection(value):
 from test_campaign_weekly import selection
 result=selection(value)
 if not value['sbc_update']['sources']:
  for row in result['recommendations']:row['evidence_indices']=[]
 return result

class CampaignTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.tasks=TaskStore(Path(self.tmp.name)/'tasks.sqlite3')
  self.pool=ThreadPoolExecutor(max_workers=2);self.addCleanup(self.pool.shutdown)
  self.host=SimpleNamespace(tasks=self.tasks,root=Path(self.tmp.name),pool=self.pool,authorizer=lambda owner:owner=='alice',lock=threading.RLock(),gateways={},tokens={},books={})
  self.auth=True;self.calls=0
  def execute(scope,request):
   scope.context('alice',scope.task_id,scope.lease);scope.mark_dispatch();self.calls+=1
   return current_selection(request)
  self.service=CampaignRecommendations(self.host,session_verify=lambda cookie,actor:self.auth and cookie=='private-session' and actor=='alice',admission=guard,execute=execute)
  self.body=dict(contract='campaign_recommendation_v1',operation_id=str(uuid.uuid4()),input=input_data())
 def finish(self):self.pool.shutdown(wait=True)
 def test_new_generation_requires_current_rules_before_admission_or_dispatch(self):
  self.body['input']=legacy_input()
  with self.assertRaisesRegex(ValueError,'campaign_input_fields'):self.service.submit(self.body,'alice','private-session')
  self.assertEqual(self.calls,0)
  with self.tasks.db() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM campaign_recommendations').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
 def test_legacy_original_id_same_hash_is_history_only_and_never_redispatched(self):
  from pilot import digest,encoded
  self.body['input']=legacy_input();operation_id=self.body['operation_id']
  for state in ('completed','unknown'):
   receipt=dict(status=state,operation_id=operation_id,historical=True)
   with self.tasks.db() as db:
    db.execute('INSERT OR REPLACE INTO campaign_recommendations VALUES(?,?,?,?,?,?,?,?,?,?)',('alice',operation_id,digest(self.body),encoded(self.body['input']),state,'historical-task','historical-run',None,encoded(receipt),1))
    before=dict(db.execute('SELECT * FROM campaign_recommendations').fetchone())
   self.assertEqual(self.service.submit(self.body,'alice','private-session'),receipt)
   self.assertEqual(self.service.lookup(operation_id,'alice','private-session'),receipt)
   changed=json.loads(json.dumps(self.body));changed['input']['source_revision']='8'
   with self.assertRaisesRegex(ValueError,'campaign_request_conflict'):self.service.submit(changed,'alice','private-session')
   with self.tasks.db() as db:self.assertEqual(dict(db.execute('SELECT * FROM campaign_recommendations').fetchone()),before)
  self.assertEqual(self.calls,0)
 def test_real_host_task_is_async_deduplicated_and_never_creates_report_or_worker_identity(self):
  result=self.service.submit(self.body,'alice','private-session');self.assertEqual(result['status'],'pending');self.finish()
  result=self.service.lookup(self.body['operation_id'],'alice','private-session');self.assertEqual(result['status'],'completed')
  self.assertEqual(self.service.submit(self.body,'alice','private-session')['status'],'completed');self.assertEqual(self.calls,1)
  task=self.tasks.get(result['receipt']['task_id'],'alice');self.assertIsNone(task['spec']['period']);self.assertEqual(task['spec']['task_type'],'campaign_recommendation_v1')
  self.assertTrue(task['run_id'].startswith('campaign_'));self.assertEqual(task['state'],'SUCCEEDED')
  self.assertNotIn('private-session',json.dumps(result));self.assertFalse((Path(self.tmp.name)/'admissions').exists())
 def test_changed_payload_or_expired_session_cannot_replay_or_read(self):
  self.service.submit(self.body,'alice','private-session');self.finish()
  self.body['input']['source_revision']='8'
  with self.assertRaisesRegex(ValueError,'campaign_request_conflict'):self.service.submit(self.body,'alice','private-session')
  self.auth=False
  with self.assertRaises(PermissionError):self.service.lookup(self.body['operation_id'],'alice','private-session')
 def test_concurrent_original_is_not_submitted_again(self):
  entered=threading.Event();release=threading.Event()
  def execute(scope,request):scope.mark_dispatch();self.calls+=1;entered.set();release.wait(2);raise ValueError('provider_outcome_unknown')
  self.service.execute=execute;self.service.submit(self.body,'alice','private-session');self.assertTrue(entered.wait(1))
  self.assertEqual(self.service.submit(self.body,'alice','private-session')['status'],'pending');self.assertEqual(self.calls,1)
  release.set();self.finish();self.assertEqual(self.service.lookup(self.body['operation_id'],'alice','private-session')['status'],'unknown')
  self.assertEqual(self.service.submit(self.body,'alice','private-session')['status'],'unknown');self.assertEqual(self.calls,1)
 def test_known_limit_rejection_is_not_dispatched_and_does_not_fail_other_tasks(self):
  def execute(scope,request):raise ValueError('daily_model_limit')
  self.service.execute=execute;self.service.submit(self.body,'alice','private-session');self.finish()
  result=self.service.lookup(self.body['operation_id'],'alice','private-session');self.assertEqual(result['status'],'unavailable');self.assertEqual(result['provider_outcome'],'not_dispatched');self.assertEqual(self.calls,0)
 def test_revocation_after_call_does_not_deliver_candidate(self):
  def execute(scope,request):scope.mark_dispatch();self.auth=False;return dict(model='gpt-6.1-sol',source_revision='7',sbc_update_id='update-7',recommendations=[])
  self.service.execute=execute;self.service.submit(self.body,'alice','private-session');self.finish();self.auth=True
  self.assertEqual(self.service.lookup(self.body['operation_id'],'alice','private-session')['status'],'unknown')
 def test_input_and_strict_schema_have_no_foreign_scope_or_empty_enums(self):
  value=checked_input(input_data());schema=output_schema(value)
  item=schema['properties']['recommendations']['items'];self.assertEqual(set(item['required']),set(item['properties']));self.assertEqual(item['properties']['core_product_key']['anyOf'][1],{'type':'null'});self.assertEqual(len(item['properties']['core_product_key']['anyOf'][0]['enum']),9)
  value['catalog'][0]['product_ref']['game_id']='999'
  with self.assertRaises(ValueError):checked_input(value)

 def test_weekly_generation_contract_uses_verified_core_count_without_model_alternatives(self):
  from test_campaign_weekly import pool_input,selection
  self.assertIn('2*N distinct',PROMPT);self.assertIn('exactly 2',PROMPT);self.assertIn('scout_top_keys',PROMPT);self.assertNotIn('2 alternatives',PROMPT)
  self.assertIn('complete Newest-tag pool',PROMPT);self.assertIn('External popularity is not our sales',PROMPT)
  from campaign_recommendations import checked_result
  for cores in (1,8,9):
   with self.subTest(cores=cores):
    value=pool_input(cores);schema=output_schema(checked_input(value))
    recommendations=schema['properties']['recommendations']
    self.assertEqual((recommendations['minItems'],recommendations['maxItems']),(6+2*cores,)*2)
    self.assertEqual(len(recommendations['items']['properties']['core_product_key']['anyOf'][0]['enum']),cores)
    result=current_selection(value)
    self.assertEqual(len(checked_result(result,value)['recommendations']),6+2*cores)
    result['recommendations'].pop()
    with self.assertRaisesRegex(ValueError,'campaign_weekly_selection'):checked_result(result,value)
  with self.assertRaisesRegex(ValueError,'campaign_input_fields'):checked_input(legacy_input())

 def test_weekly_input_requires_one_to_nine_distinct_cores_and_enough_companions(self):
  from test_campaign_weekly import pool_input
  for core_count in (0,10):
   value=pool_input();page=next(p for p in value['pages'] if p['page_id']=='fc27-sbc');page['core_product_keys']=page['product_keys'][:core_count]
   with self.assertRaisesRegex(ValueError,'campaign_sbc_core_count'):checked_input(value)
  value=pool_input();page=next(p for p in value['pages'] if p['page_id']=='fc27-sbc');page['product_keys'].pop()
  with self.assertRaisesRegex(ValueError,'campaign_sbc_pool_unavailable'):checked_input(value)
  value=pool_input();value['catalog'][0]['product_ref'].pop('model_id')
  with self.assertRaisesRegex(ValueError,'campaign_sbc_core_count'):checked_input(value)
  value=pool_input();value['catalog'][-1]['product_ref']['model_id']=value['catalog'][-2]['product_ref']['model_id']
  with self.assertRaisesRegex(ValueError,'campaign_sbc_pool_unavailable'):checked_input(value)

 def test_weekly_companions_are_unique_across_core_assignments_and_exclude_core_aliases(self):
  from test_campaign_weekly import pool_input,selection
  from campaign_recommendations import checked_result
  value=pool_input(8);result=current_selection(value)
  self.assertEqual(len(checked_result(result,value)['recommendations']),22)
  result['recommendations'][8]['product_key']=result['recommendations'][6]['product_key']
  with self.assertRaisesRegex(ValueError,'campaign_weekly_selection'):checked_result(result,value)
  result=current_selection(value)
  selected_key=result['recommendations'][6]['product_key']
  next(p for p in value['catalog'] if p['key']==selected_key)['product_ref']['model_id']=value['catalog'][0]['product_ref']['model_id']
  with self.assertRaisesRegex(ValueError,'campaign_weekly_selection'):checked_result(result,value)

 def test_paid_cardinality_and_page_pool_failures_retain_specific_safe_reason(self):
  from test_campaign_weekly import pool_input
  for failure,code in [('cardinality','campaign_weekly_selection'),('pool_mismatch','campaign_page_pool_mismatch')]:
   with self.subTest(failure=failure):
    # A fresh isolated fixture per case; the prior paid result is never replayed.
    other=CampaignTests();other.setUp()
    try:
     value=pool_input();value['sbc_update']['sources']=[dict(url='https://www.futbin.com/fixture',title='Fixture',observed_at=value['sbc_update']['observed_at'])];other.body['input']=value
     with other.pipeline(failure=failure):
      other.service.submit(other.body,'alice','private-session');other.finish();result=other.service.lookup(other.body['operation_id'],'alice','private-session')
      self.assertEqual(result['status'],'failed');self.assertEqual(result['diagnostic']['code'],code);self.assertEqual(result['receipt']['usage']['total_tokens'],9)
    finally:other.doCleanups()

 def test_actual_gateway_proxy_budget_and_openai_payload_preserve_original_lane_and_usage(self):
  with self.pipeline() as (provider,active):
   original=self.tasks.create('alice',dict(period=dict(start='2026-11-01',end_exclusive='2026-11-02',timezone='Asia/Shanghai'),snapshot_id='original',template_version='original',knowledge_version='original',budget_policy_id='original'))
   self.tasks.reserve_dispatch(original['id'],'alice','original-lease');self.tasks.bind_run(original['id'],'alice','original-lease','run_original')
   original=self.tasks.get(original['id'],'alice')
   self.service.submit(self.body,'alice','private-session');self.finish()
   result=self.service.lookup(self.body['operation_id'],'alice','private-session');self.assertEqual(result['status'],'completed')
   self.assertEqual(result['receipt']['usage']['total_tokens'],9);self.assertEqual(self.tasks.get(original['id'],'alice'),original)
   self.assertIn(('alice',result['receipt']['task_id']),active[0]);self.assertIn(('alice',original['id']),active[0])
   with self.host.daily.db() as db:rows=db.execute('SELECT state,content FROM model_calls').fetchall()
   self.assertEqual(len(rows),1);self.assertEqual(rows[0]['state'],'succeeded');self.assertEqual(json.loads(rows[0]['content'])['usage']['total_tokens'],9)
   self.assertEqual(len(provider),1);self.assertNotIn('tools',provider[0]);self.assertEqual(provider[0]['text']['format']['strict'],True)
   self.assertEqual(provider[0]['reasoning'],{'effort':'high'});self.assertEqual(provider[0]['max_output_tokens'],128000)

 def test_actual_unstarted_failure_is_not_billed_or_unknown_and_native_empty_tools_remain_rejected(self):
  with self.pipeline(failure='local') as (provider,active):
   self.service.submit(self.body,'alice','private-session');self.finish();result=self.service.lookup(self.body['operation_id'],'alice','private-session')
   self.assertEqual(result['status'],'unavailable');self.assertEqual(provider,[])
   with self.host.daily.db() as db:self.assertEqual(db.execute('SELECT state FROM model_calls').fetchone()[0],'not_dispatched')
   import openai_provider
   request=dict(model='gpt-6.1-sol',messages=[dict(role='user',content='test')],max_tokens=10,tools=[],stream=False,enable_thinking=True,reasoning_effort='high')
   with self.assertRaisesRegex(ValueError,'configuration_invalid'):openai_provider.prepare_request(request,[],native_chat=True)
   self.assertEqual(json.loads(openai_provider.prepare_request(request,[],campaign=True))['model'],'gpt-6.1-sol')

 def test_actual_unknown_retains_original_ledger_and_never_calls_twice(self):
  with self.pipeline(failure='transport') as (provider,active):
   self.service.submit(self.body,'alice','private-session');self.finish();self.assertEqual(self.service.lookup(self.body['operation_id'],'alice','private-session')['status'],'unknown')
   self.service.submit(self.body,'alice','private-session');self.assertEqual(len(provider),1)
   with self.host.daily.db() as db:self.assertEqual(db.execute('SELECT state FROM model_calls').fetchone()[0],'unknown')

 def test_actual_local_curl_rejection_preserves_attempt_marker_but_settles_only_own_call_not_dispatched(self):
  with self.pipeline(failure='local_parse') as (provider,active):
   self.service.submit(self.body,'alice','private-session');self.finish();result=self.service.lookup(self.body['operation_id'],'alice','private-session')
   self.assertEqual(result['status'],'unavailable');self.assertEqual(result['provider_outcome'],'not_dispatched');self.assertEqual(result['diagnostic']['curl_exit_code'],2)
   record=self.service._record(self.body['operation_id'],'alice');self.assertEqual(record['network_started'],1);self.assertEqual(self.tasks.get(record['task_id'],'alice')['state'],'FAILED')
   with self.host.daily.db() as db:row=db.execute('SELECT state,content FROM model_calls').fetchone()
   self.assertEqual(row['state'],'not_dispatched');self.assertEqual(json.loads(row['content'])['diagnostic']['provider_error_code'],'curl_option_invalid');self.assertEqual(len(provider),1)

 def test_actual_http_rejection_retains_safe_diagnostic_without_replay_or_body(self):
  with self.pipeline(failure='http') as (provider,active):
   self.service.submit(self.body,'alice','private-session');self.finish()
   self.assertEqual(self.service.lookup(self.body['operation_id'],'alice','private-session')['status'],'unknown')
   with self.host.daily.db() as db:content=json.loads(db.execute('SELECT content FROM model_calls').fetchone()[0])
   self.assertEqual(content['http_status'],400);self.assertEqual(content['curl_exit_code'],0);self.assertEqual(content['provider_http_request_id'],'req_fixture')
   self.assertEqual(content['provider_status'],'http_rejected');self.assertEqual(content['provider_error_code'],'invalid_json_schema');self.assertNotIn('private',json.dumps(content));self.assertEqual(len(provider),1)

 def test_paid_invalid_json_is_failed_with_real_usage_instead_of_unknown_or_unavailable(self):
  with self.pipeline(failure='json') as (provider,active):
   self.service.submit(self.body,'alice','private-session');self.finish();result=self.service.lookup(self.body['operation_id'],'alice','private-session')
   self.assertEqual(result['status'],'failed');self.assertEqual(result['provider_outcome'],'completed');self.assertEqual(result['receipt']['usage']['total_tokens'],9)
   self.assertEqual(result['operation_id'],self.body['operation_id']);self.assertNotIn('private',json.dumps(result))
   self.service.submit(self.body,'alice','private-session');self.assertEqual(len(provider),1)

 def test_actual_limit_is_checked_before_dispatch_and_does_not_change_original_usage(self):
  with self.pipeline() as (provider,active),patch.dict(os.environ,{'FS_MODEL_DAILY_LIMIT':'1'}):
   with self.host.daily.db() as db:db.execute("INSERT INTO model_calls VALUES('original',?,'succeeded','{}')",(datetime.now(timezone.utc).astimezone(__import__('pilot').SHANGHAI).date().isoformat(),))
   self.service.submit(self.body,'alice','private-session');self.finish();self.assertEqual(self.service.lookup(self.body['operation_id'],'alice','private-session')['status'],'unavailable');self.assertEqual(provider,[])
   with self.host.daily.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],1)

 def test_multiline_context_and_comparisons_remain_plain_text(self):
  value=input_data();value['sbc_update']['context']='Rating > 85\nMin 3 players\t< 5 leagues'
  self.assertEqual(checked_input(value)['sbc_update']['context'],value['sbc_update']['context'])

 def test_recovery_only_fences_campaign_task_and_never_changes_another_started_or_unknown_call(self):
  with self.pipeline() as (provider,active):
   self.service.submit(self.body,'alice','private-session');self.finish()
   record=self.service._record(self.body['operation_id'],'alice')
   with self.host.daily.db() as db:
    original=db.execute('SELECT * FROM hermes_reservations').fetchone()
    for name,state in [('original-report','started'),('original-pricing','unknown')]:
     db.execute('INSERT INTO model_calls VALUES(?,?,?,?)',(name,'2026-11-09',state,'{"original":true}'))
     db.execute('INSERT INTO hermes_reservations VALUES(?,?,?,?,?,?,?,?)',(name,'other',name,0,'hash',original['policy'],1,-1))
    db.execute("UPDATE model_calls SET state='started' WHERE fingerprint NOT IN ('original-report','original-pricing')")
   with self.tasks.db() as db:
    db.execute("UPDATE campaign_recommendations SET state='pending' WHERE task_id=?",(record['task_id'],))
    db.execute("UPDATE tasks SET state='RUNNING',lease=? WHERE id=?",(record['lease'],record['task_id']))
   restored=CampaignRecommendations(self.host,session_verify=self.service.verify,admission=guard,execute=self.service.execute)
   self.assertEqual(restored.lookup(self.body['operation_id'],'alice','private-session')['status'],'unknown')
   self.assertEqual(self.tasks.get(record['task_id'],'alice')['state'],'NEEDS_RECONCILE')
   with self.host.daily.db() as db:
    others=db.execute("SELECT fingerprint,state,content FROM model_calls WHERE fingerprint IN ('original-report','original-pricing') ORDER BY fingerprint").fetchall()
   self.assertEqual([(r['fingerprint'],r['state'],r['content']) for r in others],[('original-pricing','unknown','{"original":true}'),('original-report','started','{"original":true}')])
   restored._settle_interrupted(record['task_id'],False)
   with self.host.daily.db() as db:self.assertEqual(db.execute("SELECT state FROM model_calls WHERE fingerprint='original-report'").fetchone()[0],'started')

 def test_closed_original_executor_records_not_dispatched_instead_of_permanent_pending(self):
  self.pool.shutdown();result=self.service.submit(self.body,'alice','private-session')
  self.assertEqual(result['status'],'unavailable');self.assertEqual(result['provider_outcome'],'not_dispatched');self.assertEqual(self.calls,0)
  self.assertEqual(self.service.submit(self.body,'alice','private-session'),result)

 def test_range_optional_initialization_failure_preserves_health_and_original_routes(self):
  source=ROOT/'releases/fs-dashboard/management-november-20261103/source/range_api.py';tree=ast.parse(source.read_text('utf-8'))
  nodes=[]
  for index,node in enumerate(tree.body):
   if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CAMPAIGN_RECOMMENDATIONS' for t in node.targets):nodes=tree.body[index:index+3];break
  def broken(host):raise ValueError('damaged campaign record')
  env=dict(HERMES=object())
  with patch.dict(sys.modules,{'campaign_recommendations':SimpleNamespace(CampaignRecommendations=broken,handle=lambda *args:True)}):exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),env)
  self.assertIsNone(env['CAMPAIGN_RECOMMENDATIONS']);self.assertEqual(env['CAMPAIGN_RECOMMENDATIONS_ERROR'],'campaign_initialization_failed')
  cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Handler');fn=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='do_GET')
  env.update(urlsplit=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit,parse_qs=__import__('urllib.parse',fromlist=['parse_qs']).parse_qs,re=__import__('re'),CUSTOMER_TRACKING=None,USERS=object(),USERS_ERROR=None)
  unavailable=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='campaign_unavailable')
  exec(compile(ast.Module(body=[unavailable],type_ignores=[]),str(source),'exec'),env)
  exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),env)
  replies=[];handler=SimpleNamespace(path='/health',reply=lambda status,body:replies.append((status,body)))
  env['do_GET'](handler);self.assertEqual(replies[-1][0],200);self.assertTrue(replies[-1][1]['ok'])
  handler.path='/internal/hermes/campaign-recommendations?operation_id='+self.body['operation_id'];env['do_GET'](handler);self.assertEqual(replies[-1][1]['status'],'unavailable');self.assertEqual(replies[-1][1]['operation_id'],self.body['operation_id'])

 def test_real_session_verifier_does_not_trust_actor_headers_or_retired_sessions(self):
  import campaign_recommendations as campaign
  class Connection:
   def __init__(self,*args,**kwargs):pass
   def request(self,*args,**kwargs):self.headers=kwargs['headers']
   def getresponse(self):return self
   def read(self,*args):return b''
   def close(self):pass
   status=200
   def getheader(self,name):return {'X-Auth-User':'alice','X-Auth-Role':'admin'}[name]
  with patch.object(campaign,'HTTPConnection',Connection):
   self.assertTrue(campaign.session_verify('private-session','alice'));self.assertFalse(campaign.session_verify('private-session','bob'))
   Connection.status=401;self.assertFalse(campaign.session_verify('expired-session','alice'))

 def test_corrupt_campaign_mapping_cannot_fence_an_original_task(self):
  original=self.tasks.create('alice',dict(period=dict(start='2026-11-01',end_exclusive='2026-11-02',timezone='Asia/Shanghai'),snapshot_id='original',template_version='original',knowledge_version='original',budget_policy_id='original'))
  self.tasks.reserve_dispatch(original['id'],'alice','original-lease');self.tasks.bind_run(original['id'],'alice','original-lease','run_original');before=self.tasks.get(original['id'],'alice')
  with self.tasks.db() as db:db.execute("INSERT INTO campaign_recommendations VALUES(?,?,?,?,?,?,NULL,?,NULL,0)",('alice',self.body['operation_id'],'hash','{}','pending',original['id'],'original-lease'))
  with self.assertRaisesRegex(ValueError,'campaign_recovery_binding'):CampaignRecommendations(self.host,session_verify=self.service.verify,admission=guard)
  self.assertEqual(self.tasks.get(original['id'],'alice'),before)

 @contextmanager
 def pipeline(self,failure=None):
  """Actual changed factories/transport/ledger; only external provider and auth are doubles."""
  def load(name,path):
   spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
  def function(path,name,env):
   tree=ast.parse(path.read_text('utf-8'));node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
   exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),env);return env[name]
  channel=ROOT/'releases/fc-coins/fc-review-channel-20261026/source'
  pilot=ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013'
  original_path=list(sys.path);sys.path.extend([str(pilot),str(ROOT/'releases/fc-coins/fc-pricing-v2-20261022/source')])
  self.addCleanup(lambda:sys.path.__setitem__(slice(None),original_path))
  # These constants are irrelevant to the campaign empty-tool scope; original native tests own them.
  wire=SimpleNamespace(WIRE_TOOLS=('original_tool',),SEMANTIC_TOOLS=('original.tool',))
  with patch.dict(sys.modules,{'runs_contract':wire}):
   proxy=load('campaign_test_proxy',channel/'proxy_gateway.py')
   with patch.dict(sys.modules,{'proxy_gateway':proxy}):
    transport=load('campaign_test_transport',HERE/'source/transport.py')
    openai=load('campaign_test_openai',HERE/'source/openai_provider.py')
    daily_source=ROOT/'releases/fs-dashboard/hermes-admin-recovery-20261020/source/fc_daily.py'
    daily_env=dict(contextmanager=contextmanager,os=os,re=__import__('re'))
    slot=function(daily_source,'provider_slot',daily_env);limit=function(daily_source,'model_daily_limit',daily_env)
    active=function(channel/'fs_inprocess.py','active_model_tasks',{})
    factory=function(channel/'fs_inprocess.py','campaign_gateway',dict(datetime=datetime,timezone=timezone,UnifiedBudget=proxy.UnifiedBudget,ModelGateway=proxy.ModelGateway,conservative_input_bound=proxy.conservative_input_bound,active_model_tasks=active))
    root=Path(self.tmp.name)/'daily';root.mkdir();database=root/'daily.sqlite3'
    @contextmanager
    def db():
     connection=sqlite3.connect(database,timeout=5);connection.row_factory=sqlite3.Row
     try:
      with connection:yield connection
     finally:connection.close()
    with db() as connection:connection.execute('CREATE TABLE model_calls(fingerprint TEXT PRIMARY KEY,day TEXT,state TEXT,content TEXT)')
    self.host.daily=SimpleNamespace(root=root,db=db);self.host.grants=transport.Grants();self.host.proxy=transport.Proxy(self.host.grants,lambda grant:self.host.gateways[grant.task_id])
    self.service.execute=self.service._model;calls=[];liveness=[]
    def request(request,approved_tools,deadline=None,**options):
     if failure=='local':raise ValueError('configuration_missing')
     payload=json.loads(openai.prepare_request(request,approved_tools,campaign=options['campaign']));calls.append(payload);options['on_dispatch']();liveness.append(active(self.tasks))
     if failure=='transport':raise OSError('private provider diagnostic')
     if failure=='local_parse':
      proof=dict(network_started=False,curl_exit_code=2,provider_error_code='curl_option_invalid',transport_phase='local_validation');options['on_not_dispatched'](proof)
      return dict(proof,status='local_rejected')
     if failure=='http':return dict(status='http_rejected',http_status=400,curl_exit_code=0,provider_http_request_id='req_fixture',provider_error_code='invalid_json_schema')
     result=current_selection(json.loads(request['messages'][-1]['content']))
     if failure in ('cardinality','pool_mismatch'):
      from test_campaign_weekly import selection
      result=selection(json.loads(request['messages'][-1]['content']))
      if failure=='cardinality':result['recommendations'].pop()
      else:result['recommendations'][3]['product_key']='fc-core-ps'
     return dict(id='provider_fixture',model='gpt-6.1-sol',choices=[dict(message=dict(role='assistant',content='invalid JSON' if failure=='json' else json.dumps(result)),finish_reason='stop')],usage=dict(prompt_tokens=4,completion_tokens=5,total_tokens=9))
    with patch.dict(sys.modules,{'fs_inprocess':SimpleNamespace(campaign_gateway=factory),'fc_daily':SimpleNamespace(provider_slot=slot,model_daily_limit=limit),'openai_provider':openai}),patch.object(openai,'request_model',side_effect=request),patch.dict(os.environ,{'FS_MODEL_DAILY_LIMIT':'0'}):
     yield calls,liveness

if __name__=='__main__':unittest.main()
