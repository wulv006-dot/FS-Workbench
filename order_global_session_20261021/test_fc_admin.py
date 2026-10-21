import json
import unittest
from unittest.mock import MagicMock, patch
import fc_shared_admin as admin


class FCAdminTests(unittest.TestCase):
    def test_only_authorized_principals(self):
        config = {'P2PAH_API_BASE': 'https://admin-api.p2pah.cn',
                  'P2PAH_ALLOWED_USERNAMES': ['wulv', 'chenchao']}
        with patch('fc_shared_admin.Path.read_text', return_value=json.dumps(config)):
            self.assertEqual(admin.allowed_admin_usernames(), ['wulv', 'chenchao'])
            self.assertNotIn('unapproved', admin.allowed_admin_usernames())

    def test_ensure_only_reads_global_token(self):
        manager = admin.SessionManager({})
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"token":"synthetic-test-only"}'
        manager.opener = MagicMock()
        manager.opener.open.return_value = response
        with patch.dict('os.environ', {}, clear=True):
            self.assertTrue(manager.ensure())
        self.assertEqual(manager.opener.open.call_args.args[0], 'http://127.0.0.1:8767/session/admin-token')
        self.assertEqual(manager.opener.open.call_count, 1)

    def test_global_failure_drops_previous_token(self):
        manager = admin.SessionManager({})
        manager.token = 'synthetic-old-token'
        manager.opener = MagicMock()
        manager.opener.open.side_effect = OSError('synthetic transport failure')
        self.assertFalse(manager.ensure())
        self.assertIsNone(manager.token)

    def test_external_request_path_rejected(self):
        manager = admin.SessionManager({})
        with self.assertRaisesRegex(ValueError, 'shared_admin_path_invalid'):
            manager.request('https://example.test/')


if __name__ == '__main__':
    unittest.main()
