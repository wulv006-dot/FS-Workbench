import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError

PACKAGE=Path(__file__).resolve().parents[1]
ROOT=PACKAGE.parents[2]
spec=importlib.util.spec_from_file_location('shared_admin_direct_test',PACKAGE/'source/fc_shared_admin.py')
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)

def reply(value,status=200):
    response=io.BytesIO(json.dumps(value).encode());response.status=status
    return response

def identity(username='wulvapi',code=1):
    return {'code':code,'data':{'adminInfo':{'username':username,'super':False}}}

class SharedAdminTests(unittest.TestCase):
    def setUp(self):
        factory=patch.object(admin,'build_opener',return_value=Mock())
        factory.start();self.addCleanup(factory.stop)

    def manager(self,config=None):
        with patch.object(admin.Path,'is_file',return_value=False),patch.dict(os.environ,{},clear=True):
            return admin.SessionManager({} if config is None else config)

    def test_empty_and_original_https_constructs_normalize_on_host_and_bridge(self):
        for container,expected in ((False,admin.API_BASES[0]),(True,admin.API_BASES[2])):
            for config in ({},{'P2PAH_API_BASE':admin.LEGACY_API_BASE}):
                original=dict(config)
                with self.subTest(container=container,config=config),patch.object(admin.Path,'is_file',return_value=container),patch.dict(os.environ,{'FS_ADMIN_SESSION_URL':'http://fc27-p2pah-session:8767'},clear=True):
                    self.assertEqual(admin.SessionManager(config).config['P2PAH_API_BASE'],expected)
                    self.assertEqual(admin.read_private_config()['P2PAH_API_BASE'],expected)
                self.assertEqual(config,original)

    def test_explicit_proxy_bases_and_api_accounts_only_no_secret_file(self):
        for base in admin.API_BASES:
            self.assertEqual(self.manager({'P2PAH_API_BASE':base}).config['P2PAH_API_BASE'],base)
            with patch.dict(os.environ,{'FS_ADMIN_API_BASE':base},clear=True),patch.object(admin.Path,'read_text',side_effect=AssertionError('secret_file_read')):
                self.assertEqual(admin.read_private_config()['P2PAH_API_BASE'],base)
                self.assertEqual(admin.allowed_admin_usernames(),['wulvapi','chenchaoapi'])
        for value in ('http://127.0.0.1:8767','http://fc27-p2pah-session:8767','https://example.invalid'):
            with self.assertRaises(ValueError):self.manager({'P2PAH_API_BASE':value})
        with patch.dict(os.environ,{'FS_ADMIN_API_BASE':admin.LEGACY_API_BASE},clear=True):
            with self.assertRaises(ValueError):admin.read_private_config()

    def test_original_ensure_budget_and_real_account_identity(self):
        for username,code,status,expected in (('wulvapi',1,200,True),('chenchaoapi',1,200,True),('wulv',1,200,False),('root',1,200,False),('wulvapi',401,200,False),('wulvapi',1,403,False)):
            with self.subTest(username=username,code=code,status=status):
                manager=self.manager();manager.token='old-value';manager.opener=Mock()
                manager.opener.open.return_value=reply(identity(username,code),status)
                self.assertEqual(manager.ensure(),expected)
                call=manager.opener.open.call_args
                self.assertEqual(call.args[0].full_url,admin.API_BASES[0]+'/admin/index/index')
                self.assertEqual(call.kwargs,{'timeout':8});manager.opener.open.assert_called_once()
                self.assertEqual(manager.token,'dc-hmac-proxy' if expected else None)

    def test_post_wire_and_read_body_preserve_contract_no_token_no_retry(self):
        manager=self.manager();manager.opener=Mock();manager.opener.open.return_value=reply({'code':1})
        payload={'type':'all','file':''}
        status,body=manager.request('/admin/tools.Caches/clear?server=1',data=payload,token='old-value')
        request=manager.opener.open.call_args.args[0]
        self.assertEqual((status,json.loads(body)),(200,{'code':1}))
        self.assertEqual(request.get_method(),'POST');self.assertEqual(json.loads(request.data),payload)
        self.assertEqual(manager.opener.open.call_args.kwargs,{'timeout':15})
        self.assertFalse({'batoken','cookie','authorization'} & {key.lower() for key in request.headers})
        manager.opener.open.assert_called_once()
        manager.opener.open.reset_mock();manager.opener.open.side_effect=TimeoutError('unknown')
        with self.assertRaises(TimeoutError):manager.request('/admin/tools.Caches/clear',data=payload)
        manager.opener.open.assert_called_once()

    def test_unavailable_identity_drops_old_marker_without_retry(self):
        manager=self.manager();manager.token='old-value';manager.opener=Mock()
        manager.opener.open.side_effect=TimeoutError('unavailable')
        self.assertFalse(manager.ensure());self.assertIsNone(manager.token)
        manager.opener.open.assert_called_once()
        self.assertEqual(manager.opener.open.call_args.kwargs,{'timeout':8})

    def test_http_denial_preserved_and_redirect_login_captcha_rejected(self):
        manager=self.manager();manager.opener=Mock()
        error=HTTPError('http://local/admin',403,'denied',{},io.BytesIO(b'{"code":401}'))
        manager.opener.open.side_effect=error
        self.assertEqual(manager.request('/admin/index/index'),(403,b'{"code":401}'));error.close()
        for path in ('https://admin-api.p2pah.cn/admin/index/index','/admin/index/login','/admin/index.Login?x=1','/api/common/captcha'):
            with self.assertRaises(ValueError):manager.request(path)
        self.assertIsNone(admin.NoRedirect().redirect_request(None,None,302,'',{},'https://example.invalid'))

    def real_cache_module(self):
        path=ROOT/'opt/d4follow/_p2pah_srv/admin_cache_local.py'
        self.assertEqual(hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'857b9dcad7378903476e00e5406bb3bc6df774306148658ba5105d0864c8150d')
        spec=importlib.util.spec_from_file_location('actual_d4_admin_cache',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,fc_shared_admin=admin):spec.loader.exec_module(module)
        return module

    def test_actual_d4_cache_client_keeps_empty_and_https_interface(self):
        caller=self.real_cache_module();opener=Mock()
        opener.open.side_effect=[reply(identity()),reply({'code':1})]
        with patch.object(admin,'build_opener',return_value=opener),patch.object(admin.Path,'is_file',return_value=True),patch.dict(os.environ,{},clear=True):
            status,body=caller.clear_cache('all')
        self.assertEqual((status,json.loads(body)),(200,{'code':1}))
        calls=opener.open.call_args_list;self.assertEqual(len(calls),2)
        self.assertEqual([call.args[0].get_method() for call in calls],['GET','POST'])
        self.assertTrue(all(call.args[0].full_url.startswith(admin.API_BASES[2]+'/admin/') for call in calls))
        self.assertEqual([call.kwargs['timeout'] for call in calls],[8,15])

    def test_actual_d4_unknown_stays_unknown_without_second_send(self):
        caller=self.real_cache_module();opener=Mock()
        opener.open.side_effect=[reply(identity()),OSError('unknown')]
        with patch.object(admin,'build_opener',return_value=opener),patch.object(admin.Path,'is_file',return_value=False),patch.dict(os.environ,{},clear=True):
            status,body=caller.clear_cache('all')
        self.assertEqual((status,body),(0,'admin_clear_outcome_unknown:OSError'))
        self.assertEqual(opener.open.call_count,2)

    def test_actual_launch_mounts_work_with_direct_bridge_default_reader_unchanged(self):
        fixture=json.loads((PACKAGE/'tests/fixtures/actual-d4-callers.json').read_text('utf-8'))
        self.assertEqual(len(fixture['commands']),2)
        for record in fixture['commands']:
            command=eval(compile(ast.parse(record['expression'],mode='eval'),'actual-d4-command','eval'),{'DOCKER':'docker','SRV':'/opt/d4follow/_p2pah_srv','IMAGE':'rpg-image','jid':'same-job','kind':'writegold'})
            self.assertEqual(command[command.index('--network')+1],'fc27-cloud-net')
            self.assertIn('type=bind,src=/opt/fs-order-session/fc_shared_admin.py,dst=/srv/fc_shared_admin.py,readonly',command)
            self.assertIn('/srv/srv_run.py',command)
            with patch.object(admin.Path,'is_file',return_value=True),patch.dict(os.environ,{'FS_ADMIN_SESSION_URL':'http://fc27-p2pah-session:8767'},clear=True):
                self.assertEqual(admin.SessionManager({}).config['P2PAH_API_BASE'],admin.API_BASES[2])
        reader=ast.parse(fixture['reader_class']).body[0]
        self.assertEqual(reader.bases[0].attr,'Session')
        self.assertEqual({node.name for node in reader.body if isinstance(node,ast.FunctionDef)},{'__init__','write_rows','set_gold_cost'})

if __name__=='__main__':unittest.main()
