import ast,copy,hashlib,json,sqlite3,sys,tempfile,types,unittest,textwrap
import io
from urllib.error import HTTPError
from urllib.request import Request
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'baseline')]
import business_context as bc
from report_semantics import declared_comparison
from boss_projection import action_schedule
from report_tracks import request_report_kind

def calculation_module():
 from decimal import Decimal,ROUND_HALF_UP
 import re
 tree=ast.parse((ROOT/'source/research.py').read_text('utf8'))
 nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('decimal','resolve','rounded','calculation','ResearchBook')]
 scope=dict(Decimal=Decimal,ROUND_HALF_UP=ROUND_HALF_UP,re=re)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-research-calculation','exec'),scope)
 return types.SimpleNamespace(**scope)

class WorkerCalculationErrors(unittest.TestCase):
 def function(self,opener):
  source=ast.parse((ROOT/'source/hermes_worker.py').read_text('utf8'))
  function=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='call_tool')
  scope={'json':json,'HTTPError':HTTPError,'Request':Request,'build_opener':lambda *_:opener,'NoRedirect':object,
         'admission':lambda _:dict(token='fixture'),'PROXY':'http://fixture','MAX_PROVIDER_WIRE_BYTES':1024}
  exec(compile(ast.Module(body=[function],type_ignores=[]),'<worker-call-tool>','exec'),scope)
  return scope['call_tool']
 def failing(self,status=400,code='evidence_path',body=None):
  def fail(*_,**__):raise HTTPError('http://fixture',status,'fixture',{},io.BytesIO(body if body is not None else json.dumps({'error':code}).encode()))
  return types.SimpleNamespace(open=fail)
 def test_calculation_validation_error_is_visible_not_a_result(self):
  for code in ('evidence_path','calculation_operand_mismatch'):
   value=json.loads(self.function(self.failing(code=code))('fc.calculate',{}))
   self.assertEqual(value['code'],code);self.assertFalse(value['calculationPerformed']);self.assertNotIn('value',value);self.assertIn('/data/',value['help'])
 def test_registered_calculation_wire_name_uses_validation_feedback(self):
  value=json.loads(self.function(self.failing())('mcp__fcro__fc_calculate',{}))
  self.assertEqual(value['code'],'evidence_path');self.assertFalse(value['calculationPerformed'])
  with self.assertRaises(HTTPError):self.function(self.failing())('mcp__fcro__fc_query_business',{})
 def test_structured_calculation_error_is_handled_without_hiding_unknown_errors(self):
  body=json.dumps({'error':{'code':'evidence_path','type':'invalid_request_error','message':'invalid calculation arguments'}}).encode()
  value=json.loads(self.function(self.failing(body=body))('mcp__fcro__fc_calculate',{}))
  self.assertEqual(value['code'],'evidence_path');self.assertFalse(value['calculationPerformed'])
  for error in ({'message':'private unknown detail'},{'code':['evidence_path']},{'code':'unknown_internal'}):
   with self.assertRaises(HTTPError):self.function(self.failing(body=json.dumps({'error':error}).encode()))('fc.calculate',{})
 def test_real_loopback_bad_path_feedback_then_valid_bound_calculation(self):
  import http.server,threading
  from urllib.request import build_opener
  research=calculation_module()
  tree=ast.parse((ROOT/'source/transport.py').read_text('utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='start_loopback')
  ns=dict(BaseHTTPRequestHandler=http.server.BaseHTTPRequestHandler,ThreadingHTTPServer=http.server.ThreadingHTTPServer,threading=threading,json=json,encoded=json.dumps,MAX_PROVIDER_WIRE_BYTES=100000,SAFE_MODEL_ERRORS=frozenset())
  for node in tree.body:
   if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SAFE_CALCULATION_ERRORS' for t in node.targets):exec(compile(ast.Module(body=[node],type_ignores=[]),'safe-calculation-codes','exec'),ns)
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-loopback','exec'),ns)
  book=research.ResearchBook.__new__(research.ResearchBook);book.evidence={'ev_fixture':{'data':{'before':'120','after':'100'}}};book.register=lambda name,args,value,source:value
  def dispatch(method,path,token,body):return book.research('fc.calculate',body['arguments'])
  server,thread=ns['start_loopback'](types.SimpleNamespace(dispatch=dispatch),port=0)
  try:
   call=self.function(build_opener());call.__globals__['PROXY']='http://127.0.0.1:'+str(server.server_port)
   args={'operation':'difference','values':['120','100'],'evidence_ids':['ev_fixture'],'value_paths':[{'evidence_id':'ev_fixture','path':'data.before'},{'evidence_id':'ev_fixture','path':'data.after'}],'assumptions':['','']}
   out=json.loads(call('mcp__fcro__fc_calculate',args));self.assertEqual(out['code'],'evidence_path');self.assertFalse(out['calculationPerformed'])
   args['value_paths'][0]['path']='/data/before';args['value_paths'][1]['path']='/data/after'
   out=json.loads(call('mcp__fcro__fc_calculate',args));self.assertEqual(out['result']['delta'],'-20.00');self.assertEqual(out['basis'],'evidence_bound_calculation')
  finally:server.shutdown();server.server_close();thread.join(2)
 def test_auth_other_tools_and_unknown_errors_still_raise(self):
  for name,status,code in [('fc.calculate',403,'forbidden'),('fc.query_business',400,'evidence_path'),('fc.calculate',400,'unknown_internal')]:
   with self.assertRaises(HTTPError):self.function(self.failing(status,code))(name,{})
 def test_error_body_is_bounded_and_not_echoed(self):
  with self.assertRaisesRegex(ValueError,'tool_response_size'):self.function(self.failing(body=b'x'*1025))('fc.calculate',{})
  with self.assertRaises(HTTPError):self.function(self.failing(body=b'<html>error</html>'))('fc.calculate',{})
 def test_successful_response_is_unchanged(self):
  opener=types.SimpleNamespace(open=lambda *_,**__:io.BytesIO(b'{"status":"available","value":"12.34"}'))
  value=json.loads(self.function(opener)('fc.calculate',{}));self.assertEqual(value,{'status':'available','value':'12.34'})


class Learning(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.fs=self.root/'fs';self.fs.mkdir();self.profile=self.root/'profile';self.profile.mkdir();self.skills=self.profile/'skills';self.skills.mkdir()
  (self.fs/'desktop-business-context.md').write_text('已确认规则：先给判断，再给行动。',encoding='utf8')
  (self.profile/'memories').mkdir();(self.profile/'memories/MEMORY.md').write_text('业务记忆：参考利润不是结算利润。',encoding='utf8')
  (self.profile/'memories/USER.md').write_text('经营方法：前日和同星期分别比较。',encoding='utf8')
  self.skill={'version':'test-v1','sha256':'a'*64,'text':'方法'}
 def freeze(self,mode='daily'):
  return bc.freeze_learning(self.fs,self.skill,{},mode,skill_root=self.skills,profile_root=self.profile)
 def test_native_and_desktop_business_reach_frozen_input(self):
  v=self.freeze()
  for needle in ['参考利润不是结算利润','先给判断','前日和同星期']:self.assertIn(needle,v['text'])
  self.assertEqual(bc.loaded_learning(self.fs,v['version']),v)
 def test_current_corrections_follow_preserved_historical_methods(self):
  p=self.skills/bc.FILES[0];p.parent.mkdir(parents=True);p.write_text('旧方法样例仍保留。',encoding='utf8')
  before=p.read_bytes();value=self.freeze()
  self.assertEqual(value['files'][-1]['path'],'runtime/learning-loop.md')
  self.assertGreater(value['text'].rindex('<owner_learning_document path="runtime/learning-loop.md"'),value['text'].index('旧方法样例仍保留。'))
  self.assertEqual(p.read_bytes(),before);self.assertIn('明确修订优先',value['text'])
 def test_update_auto_publishes_next_version_and_preserves_old(self):
  a=self.freeze();p=self.profile/'memories/MEMORY.md';p.write_text('修订规则：新闻使用中文经营摘要。',encoding='utf8');b=self.freeze()
  self.assertNotEqual(a['version'],b['version']);self.assertEqual(a,bc.loaded_learning(self.fs,a['version']))
  self.assertIn('中文经营摘要',bc.loaded_learning(self.fs,b['version'])['text'])
 def test_unchanged_inputs_reuse_version(self):self.assertEqual(self.freeze()['version'],self.freeze()['version'])
 def test_html_reports_do_not_load_unrequested_document_generators_or_style_samples(self):
  for name in ('ops-report-brief/templates/brief-skeleton.html','ops-report-brief/templates/brief-skeleton.css','reviewed-business-20261015/pptx-generator/SKILL.md','reviewed-business-20261015/minimax-xlsx/SKILL.md'):
   p=self.skills/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('unrequested-format-fixture',encoding='utf8')
  value=self.freeze();self.assertNotIn('unrequested-format-fixture',value['text'])
  self.assertIn('ops-report-brief/SKILL.md',bc.FILES)
  self.assertIn('ops-report-brief/ops-report-family/SKILL.md',bc.FILES)
 def test_method_and_effort_change_identity(self):
  a=self.freeze();self.skill['sha256']='b'*64;b=self.freeze();self.assertNotEqual(a['version'],b['version'])
  self.assertNotEqual(b['version'],self.freeze('pricing')['version'])
 def test_tampered_snapshot_rejected(self):
  a=self.freeze();p=self.fs/'knowledge'/(a['version']+'.json');v=json.loads(p.read_text('utf8'));v['text']='changed';p.write_text(json.dumps(v),encoding='utf8')
  with self.assertRaisesRegex(ValueError,'knowledge_changed'):bc.loaded_learning(self.fs,a['version'])
 def test_native_files_never_written(self):
  before={p:p.read_bytes() for p in self.profile.rglob('*') if p.is_file()};self.freeze();self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))
 def test_final_wire_rejects_omitted_memory_and_does_not_count_user_quotes(self):
  v=self.freeze()
  for messages in ([{'role':'system','content':'no memory'}],[{'role':'user','content':v['text']}]):
   with self.assertRaisesRegex(ValueError,'effective_business_memory_missing'):bc.effective_learning(v,messages)
  self.assertTrue(bc.effective_learning(v,[{'role':'system','content':'prefix\n'+v['text']}])['knowledge_present'])
 def test_bad_mode_preserves_validation(self):
  if sys.platform=='win32':return
  p=self.profile/'memories/MEMORY.md';p.chmod(0o666)
  with self.assertRaisesRegex(ValueError,'owner_or_mode'):self.freeze()
 def test_missing_required_business_memory_does_not_claim_loaded(self):
  (self.fs/'desktop-business-context.md').unlink()
  for p in (self.profile/'memories').iterdir():p.unlink()
  with self.assertRaisesRegex(ValueError,'business_knowledge_missing'):self.freeze()
 def test_all_report_modes_load_business_rules(self):
  for mode in ('daily','investigation','kpi','pricing'):self.assertIn('参考利润',self.freeze(mode)['text'])


class Comparisons(unittest.TestCase):
 def test_actual_runs_input_receives_concrete_delivery_requirements(self):
  from datetime import date,timedelta
  s=(ROOT/'source/controller.py').read_text('utf8')
  start=s.index("            admission={'session_id'")
  stop=s.index('            from background import task_context',start)
  ns={'prepared':None,'body':{'start':'2026-11-01','end':'2026-11-01','question':'请以昨天为主对照','mode':'daily'},'session_id':'fixture','token':'fixture','effort':'high','item_gateway':types.SimpleNamespace(budget=types.SimpleNamespace(policy={'model':'fixture'})),'book':types.SimpleNamespace(capture_id='fixture',skills={}), 'knowledge':dict(version='v',identity={},files=[],memory_path='frozen',native_skip_reason='isolated'),'desktop_context':'frozen memory','management':None,'FORMAT':'existing format','date':date,'timedelta':timedelta,'encoded':lambda x:json.dumps(x,ensure_ascii=False)}
  ns['request_report_kind']=request_report_kind
  exec(textwrap.dedent(s[start:stop]),ns)
  request={'body':{'input':'original spec','session_id':'fixture'}};ns['request']=request;ns['digest']=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()
  a=s.index("            request['body']['input']+=");b=s.index("            path=self.run_root/'admissions'",a)
  exec(textwrap.dedent(s[a:b]),ns)
  text=request['body']['input']
  self.assertTrue(text.startswith('original spec'));self.assertIn('请以昨天为主对照',text)
  self.assertIn('主对照：2026-10-25 至 2026-10-25',text)
  self.assertIn('原问题明确覆盖默认窗时按原意',text)
  for heading in ('销售与订单结论','平台与商品结论','客户、支付与未完成订单结论','利润与成本结论','游戏与市场情报结论'):self.assertIn('### '+heading,text)
  self.assertIn('逐篇整理几条中文简介',text);self.assertNotIn('frozen memory',text)
  self.assertEqual(request['payload_sha256'],ns['digest'](request['body']))
 def test_global_field_rule_reaches_every_actual_task_mode(self):
  from datetime import date,timedelta
  s=(ROOT/'source/controller.py').read_text('utf8')
  start=s.index("            admission={'session_id'")
  stop=s.index('            from background import task_context',start)
  for mode,management in [('daily',None),('investigation',None),('pricing',None),('kpi',{'prompt':'management context'})]:
   ns={'prepared':None,'body':{'start':'2026-11-01','end':'2026-11-01','question':'请以昨天为主对照','mode':mode},'session_id':'fixture','token':'fixture','effort':'high','item_gateway':types.SimpleNamespace(budget=types.SimpleNamespace(policy={'model':'fixture'})),'book':types.SimpleNamespace(capture_id='fixture',skills={}), 'knowledge':dict(version='v',identity={},files=[],memory_path='frozen',native_skip_reason='isolated'),'desktop_context':'frozen memory','management':management,'FORMAT':'existing format','date':date,'timedelta':timedelta,'encoded':lambda x:json.dumps(x,ensure_ascii=False)}
   ns['request_report_kind']=request_report_kind
   exec(textwrap.dedent(s[start:stop]),ns)
   text=ns['admission']['prompt']
   self.assertIn('全局数据规则',text);self.assertIn('不再提出先确认参考率是否可信',text)
   self.assertIn('默认无视统计口径',text)
 def compare(self,text,**extra):return declared_comparison(dict(period={'start':'2026-10-15','end':'2026-10-15'},research_text=text,**extra))
 def test_primary_single_day_and_auxiliary(self):
  self.assertEqual(self.compare('对照：2026-10-14（前日，主对照）；同星期 2026-10-08')[0],('2026-10-14','2026-10-14'))
 def test_single_day(self):self.assertEqual(self.compare('对照期：10-08')[0],('2026-10-08','2026-10-08'))
 def test_inline_primary_declaration_in_preamble(self):
  self.assertEqual(self.compare('范围与口径：业务日10-15；主对照为2026-10-08 至 2026-10-08；前日辅助2026-10-14。\n## 关键判断\n主对照仅作举例：2026-10-01。')[0],('2026-10-08','2026-10-08'))
 def test_explicit_window_wins(self):self.assertEqual(self.compare('对照：待定',comparison_period={'start':'2026-10-08','end':'2026-10-08'})[0][0],'2026-10-08')
 def test_conflicting_windows_not_guessed(self):self.assertTrue(self.compare('对照：2026-10-08\n对照：2026-10-14')[2])
 def test_invalid_date_not_silently_defaulted(self):self.assertTrue(self.compare('对照：2026-10-99')[2])
 def test_full_range(self):self.assertEqual(self.compare('对照期：2026-10-01 至 2026-10-07')[0],('2026-10-01','2026-10-07'))
 def test_multiple_review_dates_and_past_dates(self):
  x=action_schedule({'source_first_check':'10-16 立即','when':'10-19、10-26'},'2026-10-16T00:00:00Z')
  self.assertEqual(x['first_check'],'2026-10-16');self.assertEqual(x['review_at'],'2026-10-19 / 2026-10-26')
  self.assertEqual(action_schedule({'source_first_check':'10-14','when':'10-15'},'2026-10-16T00:00:00Z')['first_check'],'2026-10-14')
 def test_unknown_dates_not_invented(self):self.assertEqual(action_schedule({'when':'待定'},'2026-10-16T00:00:00Z')['review_at'],'待安排')


class Reuse(unittest.TestCase):
 def test_reuse_including_preparing_requires_same_frozen_version(self):
  source=(ROOT/'source/controller.py').read_text('utf8');tree=ast.parse(source)
  method=next(n for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='HermesService' for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='matching_report')
  ns={'load_bundle':lambda root:{'version':'v1'},'json':json};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'matching_report','exec'),ns)
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  db.executescript('CREATE TABLE requests(id,owner,body,state,task_id);CREATE TABLE tasks(id,spec);CREATE TABLE report_trash(id);CREATE TABLE request_knowledge(id,version);')
  b={'start':'2026-10-15','end':'2026-10-15','mode':'daily','question':'日报'}
  db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',('a','wulv',json.dumps(b),'PREPARING',None));db.execute('INSERT INTO request_knowledge VALUES(?,?)',('a','v1'))
  fake=types.SimpleNamespace(source_root='.',authorizer=lambda u:True,get_job=lambda u,k:{'id':k})
  self.assertIsNone(ns['matching_report'](fake,db,b,'wulv','v2'))
  self.assertTrue(ns['matching_report'](fake,db,b,'wulv','v1')['reused'])
 def test_old_request_id_checked_before_freeze_and_never_replayed(self):
  s=(ROOT/'source/controller.py').read_text('utf8');a=s.index('            old=db.execute');b=s.index('            knowledge=freeze_learning',a)
  self.assertIn('return 200,self.get_job(user,key)',s[a:b]);self.assertIn('idempotency_conflict',s[a:b])
 def test_runtime_receipt_keeps_learning_identity(self):
  s=(ROOT/'source/controller.py').read_text('utf8')
  self.assertIn('desktop_business_sha256=desktop_sha,learning=',s)
  self.assertIn("effective_input=runtime.get('fs_effective_input')",s)
 def test_failed_projection_returns_verified_readable_original(self):
  tree=ast.parse((ROOT/'source/controller.py').read_text('utf8'))
  method=next(n for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='HermesService' for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='get')
  def read(root,task,kind):
   if kind=='boss':raise ValueError('conversion_failed')
   return {'content':'<html><body>完整原研究</body></html>','sha256':'original','filename':'original.html','mime':'text/html'}
  ns={'read_file':read,'re':__import__('re')};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'artifact_get','exec'),ns)
  fake=types.SimpleNamespace(root='.',visible_job=lambda user,key:{'state':'COMPLETED','task_id':'a'*32})
  status,value=ns['get'](fake,{'mode':['hermes'],'id':['a'*32],'artifact':['boss']},'wulv')
  self.assertEqual(status,200);self.assertIn('完整原研究',value['content']);self.assertIn('转换失败',value['content'])
  self.assertEqual(hashlib.sha256(value['content'].encode()).hexdigest(),value['sha256'])
 def test_guards_and_canonical_wire_assembly_remain(self):
  s=(ROOT/'source/hermes_worker.py').read_text('utf8')
  for item in ('unexpected_runtime_tools','context_window_configuration_mismatch','skip_memory=True','effective_business_memory_missing','build_system_prompt'):self.assertIn(item,s)
  s=(ROOT/'source/transport.py').read_text('utf8')
  self.assertLess(s.index('effective_learning(learning,messages)'),s.index('turn = self._turn'))

if __name__=='__main__':unittest.main()
