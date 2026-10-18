"""Use the unchanged pilot dispatch contract with the new research/continuation."""
import ast
import importlib
from dataclasses import dataclass
import hashlib
from pathlib import Path
import secrets
import sys
import threading
import time
from types import SimpleNamespace, MethodType
import unittest
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
PILOT=SOURCE.parents[1]/'hermes-fc-pilot-20261013'
TRANSPORT=SOURCE.parents[1]/'hermes-learning-loop-20261016/source/transport.py'
sys.path.insert(0,str(SOURCE));sys.path.append(str(PILOT))
sys.path.append(str(SOURCE.parents[1]/'admin-data-tools-20261018/candidate/hermes'))


class ToolChainTests(unittest.TestCase):
    def test_wire_allowlist_scope_research_and_frozen_continuation(self):
        research=importlib.import_module('research')
        runs=importlib.import_module('runs_contract')
        with patch.dict(sys.modules,{'skill_bundle':SimpleNamespace(load_bundle=lambda root:{})}):
            continuation=importlib.import_module('continuation')
        wire='mcp__fcro__fc_query_cohort_observation'
        self.assertIn(wire,runs.WIRE_TOOLS)
        schemas=research.tool_schemas()
        self.assertIn(wire,[s['function']['name'] for s in schemas])
        schema=next(s for s in schemas if s['function']['name']==wire)
        self.assertEqual(schema['function']['parameters']['properties']['action']['enum'],['read'])
        calls=[]
        def adapter(query):calls.append(query);return {'status':'available','members':2,'windows':[],'captured_at':'2026-10-18T00:00:00+00:00'}
        book=research.ResearchBook({'snapshot_id':'fc-detail-test','as_of':'2026-10-18T00:00:00+00:00'},{},{'start':'2026-10-01','end':'2026-10-01'},cohort_observation=adapter)
        # Execute the existing runtime's exact ScopedTools.call method against this book.
        tree=ast.parse((PILOT/'proxy_gateway.py').read_text('utf-8'))
        schemas_method=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='schemas')
        schema_ns={'WIRE_TOOLS':runs.WIRE_TOOLS,'TOOLS':importlib.import_module('pilot').TOOLS}
        exec(compile(ast.Module(body=[schemas_method],type_ignores=[]),'<runtime schemas>','exec'),schema_ns)
        wire_names=[s['function']['name'] for s in schema_ns['schemas']()]
        self.assertEqual(set(wire_names),set(runs.WIRE_TOOLS))
        self.assertEqual(len(wire_names),len(set(wire_names)))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ScopedTools')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='call')
        context_method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='context')
        ns={'WIRE_TOOLS':runs.WIRE_TOOLS,'SEMANTIC_TOOLS':runs.SEMANTIC_TOOLS}
        exec(compile(ast.Module(body=[method,context_method],type_ignores=[]),'<runtime scope call>','exec'),ns)
        scope=SimpleNamespace(book=book,deadline=None,tasks=SimpleNamespace(get=lambda task,owner:{'state':'RUNNING','lease':'lease','spec':{'snapshot_id':'fc-detail-test'}}))
        scope.context=MethodType(ns['context'],scope);scope.call=MethodType(ns['call'],scope)
        query={'profile':'FC27','start':'2026-10-01','end':'2026-10-01'}
        # Real grant resolution and transport dispatch delegate through real scope checks.
        self.assertEqual(hashlib.sha256(TRANSPORT.read_bytes()).hexdigest(),'1609bd2275d0add327c622f40b0d5ed663bdee77e48f6bf787d8d7e19207cc7c')
        transport=ast.parse(TRANSPORT.read_text('utf-8'))
        grant_nodes=[n for n in transport.body if isinstance(n,ast.ClassDef) and n.name in ('Grant','Grants')]
        proxy=next(n for n in transport.body if isinstance(n,ast.ClassDef) and n.name=='Proxy')
        dispatch=next(n for n in proxy.body if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
        transport_ns={'dataclass':dataclass,'hashlib':hashlib,'secrets':secrets,'threading':threading,'time':time}
        exec(compile(ast.Module(body=grant_nodes+[dispatch],type_ignores=[]),'<runtime grant and dispatch>','exec'),transport_ns)
        grants=transport_ns['Grants']();token=grants.mint('owner','task','lease')
        proxy_object=SimpleNamespace(grants=grants,gateway_for=lambda grant:SimpleNamespace(scope=scope))
        result=transport_ns['dispatch'](proxy_object,'POST','/fc/tools/call',token,{'name':wire,'arguments':query})
        self.assertEqual(result['data']['data']['members'],2)
        with self.assertRaises(PermissionError):transport_ns['dispatch'](proxy_object,'POST','/fc/tools/call','invalid',{'name':wire,'arguments':query})
        with self.assertRaises(PermissionError):ns['call'](scope,'owner','task','wrong-lease',wire,query)
        with self.assertRaises(PermissionError):book.call('fc.query_cohort_observation',dict(query,action='create'))
        task={'request_id':'req','end':'2026-10-01','spec':{'snapshot_id':'fc-detail-test','period':{'start':'2026-10-01'}}}
        frozen=continuation.FrozenEvidenceBook(task,book.evidence,{})
        cached=frozen.call('fc.query_cohort_observation',query)
        self.assertEqual(cached['data']['members'],2)
        self.assertEqual(len(calls),1)
        self.assertEqual(continuation.evidence_tool(cached),'fc.query_cohort_observation')
        with self.assertRaises(PermissionError):frozen.call('fc.query_cohort_observation',dict(query,action='create'))


if __name__=='__main__':unittest.main()
