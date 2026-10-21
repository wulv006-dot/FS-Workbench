import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import manual_captcha as module
import ast

class Manager:
    status = ''

    def __init__(self):
        self.calls = 0

    def request(self, path):
        self.calls += 1
        assert path.startswith('/api/common/captcha?')
        return (200, b'\x89PNG\r\n\x1a\nsynthetic')

class Tests(unittest.TestCase):

    def test_wait_no_repeat_then_consume_exact_human_value(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'ROOT', Path(directory)):
            if os.name == 'posix':
                os.chmod(directory, 448)
            manager = Manager()
            self.assertIsNone(module.take(manager))
            self.assertIsNone(module.take(manager))
            self.assertEqual(manager.calls, 1)
            expected = manager._manual_challenge['captcha_id']
            module.write(module.ROOT / 'input.json', {'captcha_id': expected, 'code': '1234'})
            self.assertEqual(module.take(manager), (expected, '1234'))
            self.assertFalse((module.ROOT / 'input.json').exists())
            self.assertEqual(json.loads((module.ROOT / 'challenge.json').read_text())['status'], 'CONSUMED')

    def test_wrong_id_and_expired_code_never_submit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'ROOT', Path(directory)):
            if os.name == 'posix':
                os.chmod(directory, 448)
            manager = Manager()
            module.take(manager)
            module.write(module.ROOT / 'input.json', {'captcha_id': 'wrong', 'code': '1234'})
            self.assertIsNone(module.take(manager))
            self.assertEqual(manager.status, 'manual_captcha_invalid')
            expected = manager._manual_challenge['captcha_id']
            manager._manual_challenge['created'] -= 301
            module.write(module.ROOT / 'input.json', {'captcha_id': expected, 'code': '1234'})
            self.assertIsNone(module.take(manager))
            self.assertEqual(manager.status, 'manual_captcha_expired')
            self.assertEqual(manager.calls, 1)
if __name__ == '__main__':
    unittest.main()
