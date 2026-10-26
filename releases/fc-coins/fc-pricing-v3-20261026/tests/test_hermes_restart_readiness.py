"""V3 release keeps the original Hermes fence and verifies a slow cold start."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
sys.path.insert(0, str(DEPLOY))
import fc_v3_release_adapter as adapter  # noqa: E402


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.body[:limit]


class HermesRestartReadinessTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        key_path = Path(self.temporary.name) / 'api-key'
        key_path.write_text('test-key', encoding='ascii')
        self.base = types.SimpleNamespace(
            HERMES_WORKER_SCOPE='worker',DEEP_SCOPE='range', rooted=lambda _root, _path: key_path,
            no_target_link=lambda _path: None)
        self.fence = types.SimpleNamespace(root=Path(self.temporary.name))
        self.manifest = {'scope': 'worker'}

    def test_specific_timeout_waits_for_same_authenticated_capabilities(self):
        original = mock.Mock(side_effect=ValueError('Hermes worker health failed'))
        with mock.patch.object(adapter.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), \
                mock.patch.object(adapter.time, 'sleep'), \
                mock.patch.object(adapter.urllib.request, 'urlopen', side_effect=[
                    OSError('cold start'), Response(json.dumps({'tools': []}).encode())]) as http:
            adapter.restart_with_hermes_readiness(self.base, original, self.manifest, self.fence)
        self.assertEqual(http.call_count, 2)
        request = http.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8941/v1/capabilities')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')

    def test_malformed_capabilities_fails_without_releasing_fence(self):
        original = mock.Mock(side_effect=ValueError('Hermes worker health failed'))
        with mock.patch.object(adapter.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), \
                mock.patch.object(adapter.urllib.request, 'urlopen', return_value=Response(b'[]')):
            with self.assertRaisesRegex(ValueError, 'Hermes capabilities contract'):
                adapter.restart_with_hermes_readiness(self.base, original, self.manifest, self.fence)

    def test_other_restart_error_is_not_swallowed(self):
        original = mock.Mock(side_effect=ValueError('admission rejected'))
        with mock.patch.object(adapter.urllib.request, 'urlopen') as http:
            with self.assertRaisesRegex(ValueError, 'admission rejected'):
                adapter.restart_with_hermes_readiness(self.base, original, self.manifest, self.fence)
        http.assert_not_called()

    def test_missing_fence_cannot_extend_original_timeout(self):
        original = mock.Mock(side_effect=ValueError('Hermes worker health failed'))
        with mock.patch.object(adapter.urllib.request, 'urlopen') as http:
            with self.assertRaisesRegex(ValueError, '^Hermes worker health failed$'):
                adapter.restart_with_hermes_readiness(self.base, original, self.manifest, None)
        http.assert_not_called()

    def test_readiness_deadline_is_bounded_from_original_restart(self):
        original = mock.Mock(side_effect=ValueError('Hermes worker health failed'))
        with mock.patch.object(adapter.time, 'monotonic', side_effect=[0, 60]), \
                mock.patch.object(adapter.urllib.request, 'urlopen') as http:
            with self.assertRaisesRegex(ValueError, 'after 60s'):
                adapter.restart_with_hermes_readiness(self.base, original, self.manifest, self.fence)
        http.assert_not_called()

    def test_range_cold_start_requires_original_ok_true_health(self):
        original=mock.Mock(side_effect=ValueError('range health failed'))
        with mock.patch.object(adapter.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)),mock.patch.object(adapter.time,'sleep'),mock.patch.object(adapter.urllib.request,'urlopen',side_effect=[OSError('starting'),Response(b'{"ok":true}')]) as http:
            adapter.restart_with_hermes_readiness(self.base,original,{'scope':'range'},None)
        self.assertEqual(http.call_count,2)
        self.assertEqual(http.call_args.args[0].full_url,'http://127.0.0.1:8931/health')

    def test_range_response_without_ok_true_cannot_pass(self):
        original=mock.Mock(side_effect=ValueError('range health failed'))
        with mock.patch.object(adapter.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)),mock.patch.object(adapter.urllib.request,'urlopen',return_value=Response(b'{"ok":false}')):
            with self.assertRaisesRegex(ValueError,'range health contract'):
                adapter.restart_with_hermes_readiness(self.base,original,{'scope':'range'},None)

    def test_range_health_wait_is_bounded(self):
        original=mock.Mock(side_effect=ValueError('range health failed'))
        with mock.patch.object(adapter.time,'monotonic',side_effect=[0,60]),mock.patch.object(adapter.urllib.request,'urlopen') as http:
            with self.assertRaisesRegex(ValueError,'range health failed after 60s'):
                adapter.restart_with_hermes_readiness(self.base,original,{'scope':'range'},None)
        http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
