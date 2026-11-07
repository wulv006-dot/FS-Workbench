import unittest
from unittest.mock import Mock
from collector_router import collect, CollectionError, fetch_remote_html


class RoutingTests(unittest.TestCase):
    def test_auto_uses_local_without_remote(self):
        local, remote = Mock(return_value=[{'url': 'a'}]), Mock()
        rows, meta = collect('mmoexp', 'auto', local, remote)
        self.assertEqual(meta['collector'], '187')
        self.assertFalse(meta['fallback'])
        remote.assert_not_called()

    def test_parse_failure_falls_back(self):
        local, remote = Mock(side_effect=ValueError('bad HTML')), Mock(return_value=[{'url': 'a'}])
        rows, meta = collect('mmoexp', 'auto', local, remote)
        self.assertEqual(meta['collector'], '183')
        self.assertTrue(meta['fallback'])
        self.assertEqual(meta['attempts'][0]['error'], 'invalid_response')

    def test_manual_183_never_local(self):
        local = Mock()
        collect('mmoexp', '183', local, lambda _: [{'url': 'a'}])
        local.assert_not_called()

    def test_manual_187_does_not_fallback(self):
        remote = Mock()
        with self.assertRaises(CollectionError) as caught:
            collect('mmoexp', '187', Mock(side_effect=TimeoutError()), remote)
        self.assertEqual(caught.exception.attempts[0]['error'], 'timeout')
        remote.assert_not_called()

    def test_empty_response_falls_back(self):
        rows, meta = collect('mmoexp', 'auto', lambda _: [], lambda _: [{'url': 'a'}])
        self.assertEqual(meta['collector'], '183')

    def test_both_fail_exposes_sanitized_codes(self):
        fail = Mock(side_effect=RuntimeError('SECRET'))
        with self.assertRaises(CollectionError) as caught:
            collect('mmoexp', 'auto', fail, fail)
        self.assertEqual(len(caught.exception.attempts), 2)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_root_and_arbitrary_source_rejected(self):
        for source, user in [('mmoexp', 'root'), ('http://localhost/', 'fc27-news-fetch')]:
            with self.assertRaises(ValueError):
                fetch_remote_html(source, user=user, key_path='unused', known_hosts='unused')


if __name__ == '__main__':
    unittest.main()
