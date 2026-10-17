"""Exercise the actual controller route methods without starting services."""
import ast
import contextlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import types
import unittest

S=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(S))


class ControllerActions(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((S/'controller.py').read_text('utf8'))
        original=next(n for n in tree.body if isinstance(n,ast.ClassDef) and any(isinstance(m,ast.FunctionDef) and m.name=='_post' for m in n.body))
        methods=[m for m in original.body if isinstance(m,ast.FunctionDef) and m.name in ('_post','action_update','action_history')]
        node=ast.ClassDef(name='Controller',bases=[],keywords=[],body=methods,decorator_list=[])
        code=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
        namespace={'json':json,'re':re}
        exec(compile(code,'actual-controller-actions','exec'),namespace)
        self.service=namespace['Controller']()
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        @contextlib.contextmanager
        def database():
            with self.db:yield self.db
        self.service.tasks=types.SimpleNamespace(db=database)
        self.service.authorizer=lambda user:user=='wulv'
        self.job={'id':'a'*32,'state':'COMPLETED','owner':'wulv'}
        self.service.visible_job=lambda user,key:self.job if key==self.job['id'] and user=='wulv' else None
        self.service.report_actions=lambda job:[{'id':'action-1','title':'核查受影响落地页'}]
        self.service.clock=lambda:datetime(2026,10,17,tzinfo=timezone.utc)
        self.body={'kind':'hermes_action','id':self.job['id'],'action':'action-1','request_id':'controller_fixture_1','expected_version':0,'status':'approved','note':'人工确认','review_at':''}
        self.headers={'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'}

    def test_actual_post_requires_same_origin_and_admin(self):
        self.assertEqual(self.service._post(self.body,None,self.headers)[0],401)
        self.assertEqual(self.service._post(self.body,'wulv',{})[0],403)
        self.assertEqual(self.service._post(self.body,'viewer',self.headers)[0],403)
        code,result=self.service._post(self.body,'wulv',self.headers)
        self.assertEqual(code,200);self.assertFalse(result['business_execution'])
        self.assertEqual(result['items'][0]['actor'],'wulv')

    def test_invisible_report_and_unknown_action_do_not_write(self):
        self.assertEqual(self.service._post(dict(self.body,id='b'*32),'wulv',self.headers)[0],404)
        self.assertEqual(self.service._post(dict(self.body,action='action-2'),'wulv',self.headers)[0],404)
        self.assertEqual(self.service.action_history('wulv'),[])

    def test_actual_history_respects_current_visibility(self):
        self.service._post(self.body,'wulv',self.headers)
        self.assertEqual(len(self.service.action_history('wulv')),1)
        self.assertEqual(self.service.action_history('viewer'),[])
        self.service.visible_job=lambda *_:None
        self.assertEqual(self.service.action_history('wulv'),[])


if __name__=='__main__':unittest.main()
