import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location('shared_sbc_admin_test', ROOT / 'sbc_admin.py')
sbc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sbc
spec.loader.exec_module(sbc)


class Tests(unittest.TestCase):
    def test_sbc_reads_current_global_token_and_fails_closed(self):
        client=sbc.AdminClient(get_retries=0)
        with patch.object(sbc,'_fs_shared_admin_token',return_value='synthetic-first'):
            self.assertTrue(client.authenticated)
        with patch.object(sbc,'_fs_shared_admin_token',return_value='synthetic-next'):
            with patch.object(client,'_opener',side_effect=RuntimeError('stop-before-network')) as opener:
                with self.assertRaisesRegex(RuntimeError,'stop-before-network'):
                    client.whoami()
                self.assertIn('synthetic-next',opener.call_args.args[0].headers.values())
        with patch.object(sbc,'_fs_shared_admin_token',side_effect=RuntimeError('unavailable')):
            self.assertFalse(client.authenticated)
            with self.assertRaises(sbc.AdminAuthError):client.whoami()
        self.assertFalse(hasattr(client,'login'))
        self.assertFalse(hasattr(client,'fetch_captcha'))
        self.assertFalse(hasattr(client,'export_auth'))
        for path in ['/admin/index/login','/admin/index/loginGoogle','/api/common/refreshToken']:
            with self.assertRaisesRegex(sbc.AdminAuthError,'FS_SHARED_AUTH_ONLY'):
                client._bytes('POST',path,auth=False)

    def test_upload_signing_secret_is_private_and_loaded_only_for_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            secret=Path(directory)/'key';secret.write_text('synthetic-signing-value',encoding='utf-8')
            os.chmod(secret,0o600)
            with patch('pathlib.Path',return_value=secret):
                self.assertEqual(sbc._upload_secret(),'synthetic-signing-value')
                if os.name=='posix':
                    os.chmod(secret,0o644)
                    with self.assertRaisesRegex(sbc.AdminAuthError,'permissions'):sbc._upload_secret()
            self.assertNotIn('UPLOAD_AUTH_SECRET',(ROOT/'sbc_admin.py').read_text(encoding='utf-8'))

    def test_sales_bootstrap_has_no_local_login_or_session_cache(self):
        source=(ROOT/'sales_auth.py').read_text(encoding='utf-8');tree=ast.parse(source)
        functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        self.assertFalse(set(functions)&{'admin_login','order_login','credentials','_ocr','_load_state','_save_state'})
        bootstrap=functions['bootstrap']
        # Execute the actual bootstrap with synthetic transports; importing requests is unnecessary.
        bootstrap.args.defaults=[]
        session=Mock();scope={'Session':Mock(return_value=session),'admin_token_from_service':lambda:('synthetic',None),'_global_order':Mock()}
        exec(compile(ast.Module(body=[bootstrap],type_ignores=[]),'<sales-bootstrap>','exec'),scope)
        self.assertIs(scope['bootstrap'](False),session)
        scope['_global_order'].fill_jar.assert_called_once_with(session.order.cookies)
        session.bind_admin_token.assert_called_once_with('synthetic')
        session.close.assert_not_called()
        scope['admin_token_from_service']=lambda:(None,'unavailable')
        with self.assertRaisesRegex(RuntimeError,'shared_admin_unavailable'):scope['bootstrap'](False)
        session.close.assert_called_once()


if __name__=='__main__':unittest.main()
