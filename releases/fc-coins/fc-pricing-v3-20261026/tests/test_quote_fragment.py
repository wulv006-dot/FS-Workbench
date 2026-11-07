"""Original HTTP quote route returns a safe same-run fragment before the wire cap."""
import ast
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlencode,urlsplit
from urllib.request import Request,urlopen

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
import pricing_operations as tools


class QuoteFragment(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'quotes').mkdir()
        self.run='88aebd83-fa1e-5e83-b37e-02c37c8367da'
        self.quote=dict(run_id=self.run,evidence=dict(offers=[{'proof':'x'*1100000}],historical_orders=[{'private':True}],
            history_replay={'paths':['private-path'],'status':'available'}),edits={},result=dict(decision_receipt={'sha256':'a'*64,'proof':'y'*88000}))
        self.file=self.root/'quotes'/(self.run+'.json');self.file.write_text(json.dumps(self.quote))
        tree=ast.parse((SOURCE/'fc27_cloud_api.py').read_text('utf-8'))
        selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in (
            '_without_replay_paths','public_artifact','quote_fragment') or isinstance(n,ast.ClassDef) and n.name=='Handler']
        self.actors=[]
        namespace=dict(BaseHTTPRequestHandler=BaseHTTPRequestHandler,json=json,hashlib=hashlib,re=re,sqlite3=sqlite3,
            ROOT=self.root,urlsplit=urlsplit,parse_qs=parse_qs,valid_id=lambda v:bool(re.fullmatch('[a-f0-9-]{36}',v)),
            read_json=lambda p:json.loads(p.read_text()))
        exec(compile(ast.Module(body=selected,type_ignores=[]),'original-quote-http','exec'),namespace)
        handler=namespace['Handler'];actor=handler.actor
        def record_actor(instance):
            value=actor(instance);self.actors.append(value);return value
        handler.actor=record_actor
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
        self.origin='http://127.0.0.1:'+str(self.server.server_address[1])

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

    def get(self,suffix,owner='original-owner'):
        with urlopen(Request(self.origin+'/quotes/'+self.run+suffix,headers={'X-Authenticated-User':owner}),timeout=3) as response:
            return json.loads(response.read())

    def native_request(self,path,**kwargs):
        return Request(path.replace('http://127.0.0.1:8879',self.origin,1),**kwargs)

    def test_tool_reads_original_safe_fragment_before_native_one_mib_limit(self):
        before=self.file.read_bytes()
        with patch.object(tools,'Request',side_effect=self.native_request),patch.object(tools,'authorization',return_value=None):
            with self.assertRaisesRegex(ValueError,'pricing_native_reply_too_large'):
                tools.native('/quotes/'+self.run,'original-owner')
            result=tools.call(Mock(),'original-owner','turn','lease',dict(action='read_quote',run_id=self.run,path='/result/decision_receipt'))
        self.assertEqual(result['value'],self.quote['result']['decision_receipt'])
        self.assertEqual(result['run_id'],self.run);self.assertEqual(result['path'],'/result/decision_receipt')
        self.assertFalse(result['execution_authorized'])
        expected=hashlib.sha256(json.dumps(self.quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(result['original_quote_sha256'],expected)
        self.assertEqual(self.actors,['original-owner','original-owner'])
        self.assertEqual(self.file.read_bytes(),before)

    def test_large_fragment_still_obeys_original_native_limit(self):
        with patch.object(tools,'Request',side_effect=self.native_request),patch.object(tools,'authorization',return_value=None):
            with self.assertRaisesRegex(ValueError,'pricing_native_reply_too_large'):
                tools.call(Mock(),'original-owner','turn','lease',dict(action='read_quote',run_id=self.run,path='/evidence'))

    def test_existing_full_route_and_public_filter_are_preserved(self):
        full=self.get('');self.assertGreater(len(json.dumps(full)),1024*1024)
        self.assertNotIn('historical_orders',full['evidence'])
        for path,expected in [('/evidence/history_replay',{'status':'available'}),('/edits',{})]:
            result=self.get('?'+urlencode({'path':path}))
            self.assertEqual(result['value'],expected)
        for path in ('/evidence/historical_orders','/evidence/history_replay/paths'):
            with self.assertRaises(HTTPError) as failure:self.get('?'+urlencode({'path':path}))
            self.assertEqual(failure.exception.code,400)
            failure.exception.close()

    def test_invalid_or_ambiguous_fragment_is_explicit_400(self):
        for suffix in ('?path=/evidenceX','?path=/run_id','?path=result','?path=/result/missing',
                       '?path=/result&path=/evidence','?path=/result&extra=1','?path=', '?other=/result'):
            with self.subTest(suffix=suffix):
                with self.assertRaises(HTTPError) as failure:self.get(suffix)
                self.assertEqual(failure.exception.code,400)
                self.assertEqual(json.loads(failure.exception.read())['error'],'pricing_quote_path_invalid')
                failure.exception.close()
        with self.assertRaises(HTTPError) as failure:self.get('','')
        self.assertEqual(failure.exception.code,401)
        failure.exception.close()

    def test_json_pointer_lists_and_escaped_keys_still_use_public_projection(self):
        self.quote['edits']={'a/b':{'m~n':[{'value':7}]}}
        self.file.write_text(json.dumps(self.quote))
        result=self.get('?'+urlencode({'path':'/edits/a~1b/m~0n/0/value'}))
        self.assertEqual(result['value'],7)
        for path in ('/edits/a~1b/m~0n/-1','/edits/a~1b/m~0n/01','/edits/a~1b/m~0n/1','/edits/a~2b'):
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as failure:self.get('?'+urlencode({'path':path}))
                self.assertEqual(failure.exception.code,400);failure.exception.close()

    def test_tool_rejects_fragment_from_different_run_or_path(self):
        for changes in ({'run_id':'00000000-0000-4000-8000-000000000001'},{'path':'/edits'},
                        {'original_quote_sha256':'invalid'},{'execution_authorized':True}):
            reply=dict(run_id=self.run,path='/result/decision_receipt',value={},original_quote_sha256='a'*64,execution_authorized=False)
            reply.update(changes)
            with patch.object(tools,'authorization',return_value=None),self.assertRaisesRegex(ValueError,'pricing_quote_fragment_basis_changed'):
                tools.call(Mock(),'owner','turn','lease',dict(action='read_quote',run_id=self.run,path='/result/decision_receipt'),request=Mock(return_value=reply))


if __name__=='__main__':unittest.main()
