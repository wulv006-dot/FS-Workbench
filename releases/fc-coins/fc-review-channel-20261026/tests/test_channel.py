import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'source'
def functions(filename,names,env):
 tree=ast.parse((SOURCE/filename).read_text(encoding='utf-8'))
 nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
 assert {n.name for n in nodes}==set(names)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),filename,'exec'),env)
 return env

class Channels(unittest.TestCase):
 def setUp(self):
  self.env=functions('proxy_gateway.py',('validate_tool_call','require_reconciled_usage','safe_diagnostic'),
    dict(re=__import__('re'),json=json,SEMANTIC_TOOLS=('fc.read_skill','fs.pricing.control'),
         WIRE_TOOLS=('mcp__fcro__fc_read_skill','mcp__fcro__fs_pricing_control'),
         MAX_PROVIDER_WIRE_BYTES=10000000,transport_trace=lambda r:{}))
 def tool(self,name,args='{}'):
  return dict(id='call_test',type='function',function=dict(name=name,arguments=args))
 def test_wire_kept(self):
  call=self.tool('mcp__fcro__fc_read_skill');self.env['validate_tool_call'](call)
  self.assertEqual(call['function']['name'],'mcp__fcro__fc_read_skill')
 def test_exact_semantic_alias(self):
  for alias in ('fc.read_skill','fc_read_skill','fs.pricing.control','fs_pricing_control'):
   call=self.tool(alias);self.env['validate_tool_call'](call)
   self.assertIn(call['function']['name'],self.env['WIRE_TOOLS'])
 def test_unknown_tool_still_denied(self):
  for name in ('shell','mcp__fcro__shell','fs.pricing.control.evil','fc_read_skill;ls'):
   with self.assertRaisesRegex(ValueError,'tool_call_denied'):self.env['validate_tool_call'](self.tool(name))
 def test_args_and_fields_still_checked(self):
  for args in ('[]','invalid','"text"'):
   with self.assertRaises(ValueError):self.env['validate_tool_call'](self.tool('fc.read_skill',args))
  call=self.tool('fc.read_skill');call['function']['extra']='secret'
  with self.assertRaises(ValueError):self.env['validate_tool_call'](call)
 def row(self,state='started',task='report'):
  return dict(state=state,owner='wulv',task=task,fingerprint='f',microcny=-1)
 def test_active_other_lane_is_not_unknown(self):
  self.env['require_reconciled_usage']([self.row()],{},'wulv','pricing',True,active_tasks={('wulv','report')})
 def test_orphan_started_remains_blocked(self):
  with self.assertRaisesRegex(ValueError,'pilot_usage_hold'):
   self.env['require_reconciled_usage']([self.row()],{},'wulv','pricing',True)
 def test_same_task_not_replayed(self):
  with self.assertRaisesRegex(ValueError,'pilot_usage_hold'):
   self.env['require_reconciled_usage']([self.row(task='pricing')],{},'wulv','pricing',True,active_tasks={('wulv','pricing')})
 def test_invalid_previous_stays_failed(self):
  with self.assertRaisesRegex(ValueError,'invalid_previous_result'):
   self.env['require_reconciled_usage']([self.row('invalid_response','pricing')],{},'wulv','pricing',True)
 def test_diagnostic_keeps_name_without_arguments(self):
  response=dict(model='test',choices=[dict(message=dict(role='assistant',tool_calls=[self.tool('unknown_tool','{"password":"private"}')]))])
  result=self.env['safe_diagnostic'](response,{'model':'test'},'tool_call_denied')
  self.assertEqual(result['response_shape']['tool_shapes'][0]['tool_name'],'unknown_tool')
  self.assertNotIn('private',json.dumps(result));self.assertNotIn('password',json.dumps(result))
 def test_reserved_dispatch_is_independent(self):
  entered=threading.Event();release=threading.Event()
  with ThreadPoolExecutor(max_workers=4) as general,ThreadPoolExecutor(max_workers=1) as pricing:
   held=[general.submit(release.wait,2) for _ in range(4)]
   try:pricing.submit(entered.set).result(timeout=1);self.assertTrue(entered.is_set())
   finally:release.set()
 def test_lane_requires_server_grant(self):
  tree=ast.parse((SOURCE/'conversation_service.py').read_text(encoding='utf-8'))
  cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ConversationService')
  fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_pricing_lane')
  env=dict(datetime=datetime,timezone=timezone);exec(compile(ast.Module(body=[fn],type_ignores=[]),'lane','exec'),env)
  conn=sqlite3.connect(':memory:');conn.execute('create table pricing_grants(conversation,owner,mode,expires_at,source)')
  class Tasks:
   @contextmanager
   def db(self):yield conn
  service=type('S',(),dict(hermes=type('H',(),dict(tasks=Tasks()))()))()
  lane=lambda:env['_pricing_lane'](service,'wulv','id')
  self.assertFalse(lane())
  conn.execute('insert into pricing_grants values(?,?,?,?,?)',('id','wulv','automatic_review',(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'human_authorized_fc_coins_v2_20261022_nonoverridable_10pct'))
  self.assertTrue(lane())
  self.assertFalse(env['_pricing_lane'](service,'other','id'))
  conn.execute('update pricing_grants set expires_at=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),));self.assertFalse(lane())
  conn.close()
 def test_all_sources_python39_syntax(self):
  for path in SOURCE.glob('*.py'):ast.parse(path.read_text(encoding='utf-8'),feature_version=(3,9))

if __name__=='__main__':unittest.main()
