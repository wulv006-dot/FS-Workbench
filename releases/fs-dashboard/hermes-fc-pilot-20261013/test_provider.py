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
        result=self.run_request(tools=schemas(),reasoning_effort='max',max_tokens=16384)
        self.assertEqual(result['id'],'fake_receipt');self.assertTrue(self.sent[0]['enable_thinking'])
        self.assertEqual(self.sent[0]['reasoning_effort'],'max');self.assertEqual(self.sent[0]['tool_choice'],'auto')
        self.assertEqual(self.sent[0]['tools'],schemas())

    def test_unsupported_parameters_or_tools_never_send(self):
        for kwargs in ({'reasoning_effort':'max'},{'tools':schemas(),'reasoning_effort':'medium'},{'tools':[]},{'max_tokens':7000}):
            self.assertEqual(self.run_request(**kwargs)['status'],'configuration_invalid')
        self.assertEqual(self.sent,[])


if __name__=='__main__':unittest.main()
