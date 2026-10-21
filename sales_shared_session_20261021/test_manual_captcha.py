import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import manual_captcha as module
import ast
from prepare_manual_session import patch as patch_session


class Manager:
    status = ''
    def __init__(self):self.calls=0
    def request(self, path):
        self.calls+=1
        assert path.startswith('/api/common/captcha?')
        return 200, b'\x89PNG\r\n\x1a\nsynthetic'


class Tests(unittest.TestCase):
    def test_transform_retains_refresh_and_2fa_while_login_waits_for_human(self):
        source = '''import time
class SessionManager:
    def refresh(self): return 'keep refresh'
    def _finish_google_login(self): return 'keep google'
    def login(self):
        for attempt in range(3):
            self.login_attempts += 1
            captcha_id = 'synthetic'
            status, png = self.request('/captcha')
            if status != 200: continue
            code = self.ocr.classification(png)
            if not code: continue
            return self.submit(captcha_id, code)
def main():
    if manager.status == 'google_code_required':
        delay = 30
    else:
        delay = 60
    time.sleep(delay)
'''
        candidate=patch_session(source)
        before,after=ast.parse(source),ast.parse(candidate)
        before_methods={n.name:ast.dump(n) for n in before.body[1].body}
        after_methods={n.name:ast.dump(n) for n in after.body[1].body}
        for name in ['refresh','_finish_google_login']:
            self.assertEqual(before_methods[name],after_methods[name])
        self.assertNotIn('classification',candidate)
        namespace={};exec(candidate,namespace)
        manager=namespace['SessionManager']();manager.login_attempts=0
        manager.submit=lambda *args: args
        with patch.object(module,'take',return_value=None):
            self.assertFalse(manager.login())
            self.assertEqual(manager.login_attempts,0)
        with patch.object(module,'take',return_value=('synthetic','1234')):
            self.assertEqual(manager.login(),('synthetic','1234'))
            self.assertEqual(manager.login_attempts,1)

    def test_wait_no_repeat_then_consume_exact_human_value(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module,'ROOT',Path(directory)):
            if os.name=='posix':os.chmod(directory,0o700)
            manager=Manager()
            self.assertIsNone(module.take(manager))
            self.assertIsNone(module.take(manager))
            self.assertEqual(manager.calls,1)
            expected=manager._manual_challenge['captcha_id']
            module.write(module.ROOT/'input.json',{'captcha_id':expected,'code':'1234'})
            self.assertEqual(module.take(manager),(expected,'1234'))
            self.assertFalse((module.ROOT/'input.json').exists())
            self.assertEqual(json.loads((module.ROOT/'challenge.json').read_text())['status'],'CONSUMED')

    def test_wrong_id_and_expired_code_never_submit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module,'ROOT',Path(directory)):
            if os.name=='posix':os.chmod(directory,0o700)
            manager=Manager();module.take(manager)
            module.write(module.ROOT/'input.json',{'captcha_id':'wrong','code':'1234'})
            self.assertIsNone(module.take(manager))
            self.assertEqual(manager.status,'manual_captcha_invalid')
            expected=manager._manual_challenge['captcha_id']
            manager._manual_challenge['created']-=301
            module.write(module.ROOT/'input.json',{'captcha_id':expected,'code':'1234'})
            self.assertIsNone(module.take(manager))
            self.assertEqual(manager.status,'manual_captcha_expired')
            self.assertEqual(manager.calls,1)


if __name__=='__main__':unittest.main()
