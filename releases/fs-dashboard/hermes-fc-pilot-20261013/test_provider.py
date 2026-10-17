import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import stat
import unittest
from unittest.mock import patch
from proxy_gateway import schemas


class Response:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,_):return json.dumps({'model':'deepseek-v4.1-flash','id':'fake_receipt'}).encode()


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.key=Path(self.tmp.name)/'fixture-key';self.key.write_text('sk-FIXTURE-NOT-REAL');self.key.chmod(0o600)
        module=type('DailyModule',(),{'MODEL':'deepseek-v4.1-flash','ENDPOINT':'https://fixture.invalid/v1/chat/completions','NoRedirect':__import__('urllib.request',fromlist=['HTTPRedirectHandler']).HTTPRedirectHandler})()
        self.modules=patch.dict('sys.modules',{'fc_daily_model':module});self.modules.start();self.addCleanup(self.modules.stop)
        path=Path(__file__).parent/'shared_candidate/ai_advisor_model.py'
        spec=importlib.util.spec_from_file_location('hermes_provider_candidate',path);self.provider=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.provider)
        self.sent=[]
        owner_uid=self.key.stat().st_uid
        self.uid=patch.object(os,'geteuid',return_value=owner_uid,create=True);self.uid.start();self.addCleanup(self.uid.stop)
        self.environment=patch.dict(os.environ,{'FS_DAILY_MODEL_KEY_FILE':str(self.key)});self.environment.start();self.addCleanup(self.environment.stop)
        if os.name=='nt':
            # NTFS cannot express the POSIX fixture mode checked by this Linux provider.
            info=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=owner_uid,st_size=self.key.stat().st_size)
            self.posix_fixture=patch.object(Path,'lstat',return_value=info);self.posix_fixture.start();self.addCleanup(self.posix_fixture.stop)

    def run_request(self,**kwargs):
        def open_request(request,timeout):
            self.sent.append(json.loads(request.data));return Response()
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=open_request
            return self.provider.request_model([{'role':'user','content':'fixture'}],{},lambda v,_:v,**kwargs)

    def test_legacy_consumers_keep_original_non_thinking_body(self):
        result=self.run_request();self.assertEqual(result['id'],'fake_receipt')
        self.assertFalse(self.sent[0]['enable_thinking']);self.assertNotIn('tools',self.sent[0]);self.assertNotIn('reasoning_effort',self.sent[0])

    def test_hermes_max_is_explicit_and_uses_exact_tools(self):
        result=self.run_request(tools=schemas(),reasoning_effort='max',max_tokens=393216)
        self.assertEqual(result['id'],'fake_receipt');self.assertTrue(self.sent[0]['enable_thinking'])
        self.assertEqual(self.sent[0]['reasoning_effort'],'max');self.assertEqual(self.sent[0]['tool_choice'],'auto')
        self.assertEqual(self.sent[0]['tools'],schemas())

    def test_hermes_long_thinking_timeout_and_safe_transport_diagnostics(self):
        observed=[]
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=lambda request,timeout:(observed.append(timeout) or Response())
            self.provider.request_model([],{},lambda v,_:v,tools=schemas(),reasoning_effort='max',timeout=600)
            self.assertEqual(self.provider.request_model([],{},lambda v,_:v,timeout=600),{'status':'configuration_invalid'})
        self.assertEqual(observed,[600])
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=TimeoutError('private network diagnostic')
            result=self.provider.request_model([],{},lambda v,_:v,tools=schemas(),reasoning_effort='max',timeout=600)
            legacy=self.provider.request_model([],{},lambda v,_:v)
        self.assertEqual(result['status'],'unknown_transport');self.assertEqual(result['transport_error_type'],'TimeoutError')
        self.assertEqual(result['timeout_seconds'],600);self.assertGreaterEqual(result['elapsed_seconds'],0)
        self.assertNotIn('private',str(result));self.assertEqual(legacy,{'status':'unknown_transport'})

    def test_unsupported_parameters_or_tools_never_send(self):
        for kwargs in ({'reasoning_effort':'max'},{'tools':schemas(),'reasoning_effort':'medium'},{'tools':[{'type':'invalid'}]},{'max_tokens':7000}):
            self.assertEqual(self.run_request(**kwargs)['status'],'configuration_invalid')
        self.assertEqual(self.sent,[])

    def test_chinese_hermes_payload_uses_exact_utf8_and_preserves_legacy_encoding(self):
        from proxy_gateway import request_body
        messages=[{'role':'user','content':'中文经营调查'*4500}]
        body=request_body({'messages':messages,'max_tokens':393216,'reasoning_effort':'max'},'deepseek-v4.1-flash')
        expected=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        self.assertLess(len(expected),96000);self.assertGreater(len(json.dumps(body).encode()),96000)
        sent=[]
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=lambda request,timeout:(sent.append(request.data) or Response())
            result=self.provider.request_model(messages,{},lambda v,_:v,tools=schemas(),reasoning_effort='max',max_tokens=393216)
        self.assertEqual(result['id'],'fake_receipt');self.assertEqual(len(sent[0]),len(expected))
        self.assertIn('中文经营调查'.encode(),sent[0]);self.assertEqual(json.loads(sent[0]),body)

    def test_tool_schema_framing_is_rejected_before_provider_reservation(self):
        from proxy_gateway import request_body
        from proxy_gateway import MAX_PROVIDER_WIRE_BYTES
        messages=[{'role':'user','content':'x'*(MAX_PROVIDER_WIRE_BYTES-2000)}]
        self.assertLess(len(json.dumps(messages).encode()),MAX_PROVIDER_WIRE_BYTES)
        with self.assertRaisesRegex(ValueError,'provider_payload_too_large'):
            request_body({'messages':messages,'max_tokens':393216,'reasoning_effort':'max'},'deepseek-v4.1-flash')

    def test_http_diagnostics_only_expose_status_for_hermes(self):
        from urllib.error import HTTPError
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError('https://fixture.invalid',400,'secret upstream body',{},None)
            legacy=self.provider.request_model([],{},lambda v,_:v)
            pilot=self.provider.request_model([],{},lambda v,_:v,tools=schemas(),reasoning_effort='max')
        self.assertEqual(legacy,{'status':'http_rejected'})
        self.assertEqual(pilot,{'status':'http_rejected','http_status':400})

    def test_large_hermes_input_does_not_change_legacy_input_limit(self):
        messages=[{'role':'user','content':'capacity fixture '*13000}]
        sent=[]
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=lambda request,timeout:(sent.append(request.data) or Response())
            legacy=self.provider.request_model(messages,{},lambda v,_:v)
            hermes=self.provider.request_model(messages,{},lambda v,_:v,tools=schemas(),reasoning_effort='max',max_tokens=393216)
        self.assertEqual(legacy,{'status':'input_too_large'})
        self.assertEqual(hermes['id'],'fake_receipt')
        self.assertEqual(len(sent),1)
        self.assertGreater(len(sent[0]),128000)
        self.assertEqual(json.loads(sent[0])['messages'],messages)

    def test_large_hermes_response_does_not_change_legacy_response_limit(self):
        raw=json.dumps({'model':'deepseek-v4.1-flash','id':'fake_receipt','fixture':'x'*130000}).encode()
        response=Response();response.read=lambda n:raw[:n]
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            legacy=self.provider.request_model([{'role':'user','content':'fixture'}],{},lambda v,_:v)
            hermes=self.provider.request_model([{'role':'user','content':'fixture'}],{},lambda v,_:v,tools=schemas(),reasoning_effort='max')
        self.assertEqual(legacy,{'status':'invalid_response'})
        self.assertEqual(hermes['id'],'fake_receipt')
        self.assertEqual(len(hermes['fixture']),130000)

    def test_unknown_approval_requires_private_exact_contract(self):
        from fs_inprocess import approved_unknowns
        root=Path(self.tmp.name);tasks=SimpleNamespace(path=str(root/'tasks.sqlite3'))
        self.assertEqual(approved_unknowns(tasks),{})
        path=root/'unknown-usage-approvals.json'
        item={'fingerprint':'a'*64,'reserved_upper_microcny':206294,'confirmation_reference':'user-reply-20261014','scope':'new_tasks_only'}
        path.write_text(json.dumps({'contract':'explicit-unknown-usage-acceptance-v1','approvals':[item]}));path.chmod(0o600)
        self.assertEqual(approved_unknowns(tasks),{'a'*64:206294})
        item['scope']='replay_old_task'
        path.write_text(json.dumps({'contract':'explicit-unknown-usage-acceptance-v1','approvals':[item]}))
        with self.assertRaisesRegex(ValueError,'unknown_approval_fields'):approved_unknowns(tasks)


if __name__=='__main__':unittest.main()
