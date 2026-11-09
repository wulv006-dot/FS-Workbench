import unittest

from fs_mcp_connector.redaction import redact
from fs_mcp_connector.accounts import project


class RedactionTests(unittest.TestCase):
    def test_credentials_in_free_text_are_removed_but_business_identity_is_retained(self):
        for secret in ('Authorization: Bearer SYNTHETIC_TOKEN_12345678901234567890',
                       'password: dummy123', '{"access_token":"SYNTHETIC_TOKEN"}',
                       'api_key=short-key', "'password': 'short value'", 'Authorization: Basic dXNlcjpwYXNz',
                       'Cookie: first=secret; second=another', '{"cookie":"short-secret"}',
                       '{"batoken":"short-secret"}', 'csrf=short-csrf'):
            text = '客户 owner@example.test UID 42 订单ORDER-123 '+secret
            with self.subTest(secret=secret):
                cleaned = redact(text)
                self.assertNotIn(secret, cleaned)
                self.assertNotIn(secret.split()[-1], cleaned)
                self.assertIn('owner@example.test UID 42 订单ORDER-123', cleaned)
                value = project({'entries': [{'note': text}]}, 'audit')
                self.assertEqual(value['entries'][0]['note'], cleaned)


if __name__ == '__main__':
    unittest.main()
