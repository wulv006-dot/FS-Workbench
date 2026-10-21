import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import manual_captcha as module

PNG = b'\x89PNG\r\n\x1a\nsynthetic-offline-only'
ROOT = Path(__file__).resolve().parent


def manager(results=('1234',)):
    item = Mock()
    item.status = ''
    item.ocr.classification.side_effect = list(results)
    item.request.return_value = (200, PNG)
    return item


class Tests(unittest.TestCase):
    def setUp(self):
        sleeper = patch.object(module.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_ocr_success_returns_matching_challenge_without_inbox_or_login(self):
        item = manager(('1 2 3 4',))
        challenge, code = module.take(item)
        item.request.assert_called_once()
        query = parse_qs(urlsplit(item.request.call_args.args[0]).query)
        self.assertEqual((challenge, code), (query['id'][0], '1234'))
        self.assertEqual(query['server'], ['1'])
        item.ocr.classification.assert_called_once_with(PNG)
        self.assertEqual(item.status, 'captcha_solved')
        item.login.assert_not_called()

    def test_unreadable_ocr_gets_a_new_image_and_returns_its_id(self):
        item = manager(('unreadable', '654321'))
        challenge, code = module.take(item)
        ids = [parse_qs(urlsplit(call.args[0]).query)['id'][0]
               for call in item.request.call_args_list]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual((challenge, code), (ids[1], '654321'))

    def test_unreadable_ocr_stops_at_attempt_limit_without_login(self):
        item = manager(('bad',) * 3)
        with patch.object(module, 'MAX_ATTEMPTS', 3):
            self.assertIsNone(module.take(item))
        self.assertEqual(item.request.call_count, 3)
        self.assertEqual(item.ocr.classification.call_count, 3)
        self.assertEqual(item.status, 'captcha_ocr_failed:captcha_unreadable')
        item.login.assert_not_called()

    def test_transport_and_ocr_errors_are_bounded(self):
        item = manager((ValueError('synthetic-engine-error'), '1234'))
        item.request.side_effect = [OSError('synthetic-network-error'), (200, PNG), (200, PNG)]
        with patch.object(module, 'MAX_ATTEMPTS', 3):
            self.assertEqual(module.take(item)[1], '1234')
        self.assertEqual(item.request.call_count, 3)
        self.assertEqual(item.ocr.classification.call_count, 2)

    def test_invalid_http_or_image_never_reaches_ocr(self):
        for response in ((503, PNG), (200, b'not-png'),
                         (200, PNG + b'x' * 1048576), (200, 'not-bytes')):
            with self.subTest(response_status=response[0], image_type=type(response[1]).__name__):
                item = manager()
                item.request.return_value = response
                with patch.object(module, 'MAX_ATTEMPTS', 1):
                    self.assertIsNone(module.take(item))
                item.ocr.classification.assert_not_called()
                item.login.assert_not_called()

    def test_invalid_ocr_type_or_digit_length_never_returns_a_code(self):
        for value in (None, 1234, '123', '1234567'):
            with self.subTest(value=value):
                item = manager((value,))
                with patch.object(module, 'MAX_ATTEMPTS', 1):
                    self.assertIsNone(module.take(item))
                self.assertTrue(item.status.startswith('captcha_ocr_failed:'))

    def test_source_matches_observed_production_and_retired_publisher_is_absent(self):
        manifest = json.loads((ROOT / 'OCR-SOURCE.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256((ROOT / 'manual_captcha.py').read_bytes()).hexdigest(),
                         manifest['sha256'])
        self.assertFalse((ROOT.parent / 'admin_session_continuity_20261021' / 'deploy.py').exists())


if __name__ == '__main__':
    unittest.main()
