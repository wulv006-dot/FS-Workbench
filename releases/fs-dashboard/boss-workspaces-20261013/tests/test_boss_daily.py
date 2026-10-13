"""Daily lifecycle tests with fake sources/provider and real temporary files/locks."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import boss_daily as daily


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'
        self.at = datetime(2026, 10, 13, 9, 40, tzinfo=daily.SHANGHAI)
        self.calls = {'source': 0, 'provider': 0, 'ledger': 0}
        self.batch = {'status': 'available', 'documents': [{'source_url': 'https://example.com/news'}],
                      'projects': [{'key': 'FC27', 'orders': 5}]}
        self.result = {'status': 'succeeded', 'model': 'fake-model', 'receipt': 'fake-receipt', 'tokens': 5, 'events': []}
        def collect(at, **kwargs):
            self.calls['source'] += 1
            self.assertEqual(at.tzinfo, daily.SHANGHAI)
            return copy.deepcopy(self.batch)
        def snapshot(batch, result, previous):
            return {'facts': batch, 'ai': result, 'status': 'available'}
        module = types.SimpleNamespace(collect=collect, messages=lambda batch: [{'role': 'user', 'content': '{}'}],
                                       validate_response=lambda raw, batch: raw, build_snapshot=snapshot)
        self.modules = {kind: module for kind in daily.SCHEDULES}
        def provider(messages, projected, validator, **kwargs):
            self.calls['provider'] += 1
            self.provider_kwargs = kwargs
            return validator(copy.deepcopy(self.result), projected)
        def ledger(projected, callback):
            self.calls['ledger'] += 1
            saved = list((self.root / 'journal').rglob('*.json'))
            pending = [json.loads(path.read_bytes()) for path in saved if json.loads(path.read_bytes())['phase'] == 'model_pending']
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]['source_sha256'], daily.digest(daily.encoded(projected)))
            self.assertEqual(pending[0]['projected'], projected)
            return callback(projected)
        self.runner = daily.DailyRunner(self.root, clock=lambda: self.at, modules=self.modules,
                                       model_runner=ledger, provider=provider, wait=lambda seconds: None)

    def test_inspect_is_read_only_and_schedules_are_shanghai(self):
        result = self.runner.inspect()
        self.assertTrue(result['read_only'])
        self.assertFalse(self.root.exists())
        self.assertEqual(result['workspaces']['game-monitor']['schedule'], '09:00 Asia/Shanghai')
        self.assertEqual(result['workspaces']['management']['schedule'], '09:30 Asia/Shanghai')
        self.assertEqual(self.calls, {'source': 0, 'provider': 0, 'ledger': 0})

    def test_success_same_day_readback_history_and_private_projection(self):
        first = self.runner.run('game-monitor', 'scheduled')
        second = self.runner.run('game-monitor', 'manual')
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'succeeded')
        self.assertTrue(first['publication_matches_journal'])
        self.assertNotIn('projected', first)
        self.assertEqual(self.calls, {'source': 1, 'provider': 1, 'ledger': 1})
        self.assertEqual(self.provider_kwargs, {'max_tokens': 6000, 'timeout': 120})
        self.assertEqual(len(list((self.root / 'history/game-monitor').glob('*.json'))), 1)
        self.assertEqual(json.loads((self.root / 'public/game-monitor.status.json').read_bytes()), first)

    def test_management_uses_separate_day_and_smaller_output_budget(self):
        first = self.runner.run('game-monitor', 'manual')
        second = self.runner.run('management', 'scheduled')
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(self.provider_kwargs, {'max_tokens': 5000, 'timeout': 120})
        self.assertEqual(self.calls['provider'], 2)

    def test_unknown_not_reposted_and_old_game_snapshot_preserved(self):
        self.runner.run('game-monitor', 'manual')
        old = (self.root / 'public/game-monitor.json').read_bytes()
        self.at += timedelta(days=1)
        self.result = {'status': 'unknown_transport'}
        first = self.runner.run('game-monitor', 'scheduled')
        again = self.runner.run('game-monitor', 'manual')
        self.assertEqual(first, again)
        self.assertEqual(first['status'], 'model_failed')
        self.assertEqual(first['ai_status'], 'unknown_transport')
        self.assertEqual(self.calls['provider'], 2)
        self.assertEqual((self.root / 'public/game-monitor.json').read_bytes(), old)

    def test_management_model_failure_publishes_facts_not_ai_success(self):
        self.result = {'status': 'unknown_previous_attempt'}
        result = self.runner.run('management', 'scheduled')
        public = json.loads((self.root / 'public/management.json').read_bytes())
        self.assertEqual(result['status'], 'facts_only')
        self.assertEqual(public['facts']['projects'][0]['orders'], 5)
        self.assertEqual(public['ai']['status'], 'unknown_previous_attempt')
        self.runner.run('management', 'manual')
        self.assertEqual(self.calls['provider'], 1)

    def test_source_failure_does_not_overwrite_last_success_or_leak_exception(self):
        self.runner.run('management', 'manual')
        old = (self.root / 'public/management.json').read_bytes()
        self.at += timedelta(days=1)
        def failed(*args, **kwargs): raise OSError('sk-do-not-log-this-secret')
        self.modules['management'].collect = failed
        result = self.runner.run('management', 'scheduled')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual((self.root / 'public/management.json').read_bytes(), old)
        self.assertNotIn('sk-do-not-log', daily.encoded(result).decode())
        self.assertEqual(self.calls['provider'], 1)

    def test_source_unavailable_and_month_first_skip_model(self):
        for status in ('unavailable', 'target_period_expired', 'no_complete_days'):
            self.batch['status'] = status
            result = self.runner.run('management', 'scheduled')
            self.assertEqual(result['status'], 'source_unavailable')
            self.assertEqual(result['fact_status'], status)
            self.at += timedelta(days=1)
        self.assertEqual(self.calls['provider'], 0)
        self.assertFalse((self.root / 'public/management.json').exists())

    def test_shanghai_date_and_persistent_catchup_are_once_after_due(self):
        self.at = datetime(2026, 10, 12, 23, 30, tzinfo=timezone.utc)
        result = self.runner.run('game-monitor', 'scheduled')
        self.assertEqual(result['day'], '2026-10-13')
        self.assertEqual(result['status'], 'not_due')
        self.assertFalse(self.root.exists())
        self.at = datetime(2026, 10, 13, 6, tzinfo=timezone.utc)
        first = self.runner.run('game-monitor', 'scheduled')
        self.assertEqual(first['day'], '2026-10-13')
        self.runner.run('game-monitor', 'scheduled')
        self.assertEqual(self.calls['provider'], 1)

    def test_busy_lock_does_not_collect_or_create_journal(self):
        self.runner.prepare('game-monitor')
        paths = self.runner.paths('game-monitor', '2026-10-13')
        with daily.file_lock(paths['lock']):
            result = self.runner.run('game-monitor', 'manual')
        self.assertEqual(result['status'], 'busy')
        self.assertFalse(paths['journal'].exists())
        self.assertEqual(self.calls['source'], 0)

    def test_shared_model_busy_does_not_call_provider(self):
        self.runner.model_runner = lambda projected, callback: {'status': 'model_busy'}
        result = self.runner.run('game-monitor', 'scheduled')
        self.assertEqual(result['ai_status'], 'model_busy')
        self.runner.run('game-monitor', 'manual')
        self.assertEqual(self.calls['provider'], 0)

    def test_interrupted_model_pending_is_unknown_without_new_request(self):
        def interrupted(projected, callback): raise KeyboardInterrupt()
        self.runner.model_runner = interrupted
        with self.assertRaises(KeyboardInterrupt):
            self.runner.run('game-monitor', 'manual')
        result = self.runner.run('game-monitor', 'manual')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['phase'], 'model_pending')
        self.assertEqual(self.calls['source'], 1)
        self.assertEqual(self.calls['provider'], 0)

    def test_busy_then_success_reuses_projection_and_only_sends_once(self):
        attempts, waits = [], []
        normal = self.runner.model_runner
        def ledger(projected, callback):
            attempts.append(copy.deepcopy(projected))
            return {'status': 'model_busy'} if len(attempts) == 1 else normal(projected, callback)
        self.runner.model_runner = ledger
        self.runner.wait = waits.append
        result = self.runner.run('game-monitor', 'scheduled')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(waits, [20])
        self.assertEqual(self.calls['provider'], 1)
        self.assertEqual(self.calls['source'], 1)
        self.assertEqual(self.runner.run('game-monitor', 'manual')['run_id'], result['run_id'])
        self.assertEqual(len(attempts), 2)

    def test_busy_with_receipt_is_never_retried(self):
        attempts = []
        def ledger(projected, callback):
            attempts.append(projected)
            return {'status': 'model_busy', 'receipt': 'existing-request'}
        self.runner.model_runner = ledger
        self.runner.wait = lambda seconds: self.fail('receipt must forbid retry')
        self.runner.run('game-monitor', 'scheduled')
        self.assertEqual(len(attempts), 1)

    def test_failed_atomic_publish_preserves_old_public_and_does_not_retry(self):
        self.runner.run('management', 'manual')
        old = (self.root / 'public/management.json').read_bytes()
        self.at += timedelta(days=1)
        original = daily.atomic
        def failed(path, data, mode):
            if path == self.root / 'public/management.json': raise OSError('injected rename failure')
            return original(path, data, mode)
        with patch.object(daily, 'atomic', failed):
            result = self.runner.run('management', 'scheduled')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual((self.root / 'public/management.json').read_bytes(), old)
        self.runner.run('management', 'manual')
        self.assertEqual(self.calls['provider'], 2)

    def test_peer_public_change_prevents_old_writer_overwrite(self):
        original = self.runner.provider
        def peer(*args, **kwargs):
            (self.root / 'public/management.json').write_text('{"peer":true}', 'utf-8')
            return original(*args, **kwargs)
        self.runner.provider = peer
        result = self.runner.run('management', 'manual')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(json.loads((self.root / 'public/management.json').read_bytes()), {'peer': True})

    def test_publish_pending_never_claims_success(self):
        original = daily.atomic
        def interrupted(path, data, mode):
            if path == self.root / 'public/management.json': raise KeyboardInterrupt()
            return original(path, data, mode)
        with patch.object(daily, 'atomic', interrupted), self.assertRaises(KeyboardInterrupt):
            self.runner.run('management', 'manual')
        result = self.runner.run('management', 'manual')
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['phase'], 'publish_pending')
        self.assertFalse(result['publication_matches_journal'])
        self.assertEqual(self.calls['provider'], 1)

    def test_loopback_reader_rejects_arbitrary_targets_and_actions(self):
        for path in ('https://example.com/range?mode=catalog',
                     '/dashboard/fs-home/range.json?mode=delete',
                     '/dashboard/fs-home/range.json?mode=catalog&action=write',
                     '/dashboard/fs-home/range.json?mode=catalog&mode=summary',
                     '/dashboard/fs-home/range.json?mode=summary&profile=FC27&start=bad&end=2026-10-13'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                daily.read_summary(path)

    def test_loopback_reader_fixed_identity_and_request_timeout(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{"schemaVersion":2}'
        def opened(request, timeout):
            self.assertEqual(request.full_url, 'http://127.0.0.1:8931/range?mode=catalog')
            self.assertEqual(request.get_header('X-auth-user'), 'wulv')
            self.assertEqual(timeout, 20)
            return Response()
        with patch.object(daily.urllib.request, 'build_opener', return_value=types.SimpleNamespace(open=opened)):
            self.assertEqual(daily.read_summary('/dashboard/fs-home/range.json?mode=catalog'), {'http_status': 200, 'body': {'schemaVersion': 2}})

    def test_units_are_two_persistent_timers_with_ten_minute_oneshots(self):
        for kind, hour in [('game-monitor', '09:00:00'), ('management', '09:30:00')]:
            timer = (ROOT / 'deploy' / ('fs-boss-' + kind + '.timer')).read_text('utf-8')
            service = (ROOT / 'deploy' / ('fs-boss-' + kind + '.service')).read_text('utf-8')
            self.assertIn('OnCalendar=*-*-* ' + hour + '\n', timer)
            self.assertNotIn('StateDirectory', service)
            self.assertIn('Persistent=true', timer)
            self.assertIn('Type=oneshot', service)
            self.assertIn('TimeoutStartSec=600', service)
            self.assertIn('ExecStart=/opt/python39/bin/python3 ', service)
            self.assertIn('--kind ' + kind + ' --trigger scheduled', service)
            self.assertNotIn('Restart=', service)
        source = (ROOT / 'backend/boss_daily.py').read_text('utf-8')
        for forbidden in ('.start()', '.tick()', '.enqueue('): self.assertNotIn(forbidden, source)

    def test_actual_game_and_management_modules_with_fake_provider(self):
        import test_game_intelligence as game_fixture
        import management_daily_test as management_fixture
        self.runner.modules = {'game-monitor': game_fixture.g, 'management': management_fixture.m}
        self.runner.reader = management_fixture.reader
        seen = []
        def provider(messages, projected, validator, **kwargs):
            seen.append(kwargs)
            if 'documents' in projected:
                raw = game_fixture.envelope([game_fixture.event(projected)])
            else:
                raw = game_fixture.envelope([])
                raw['choices'][0]['message']['content'] = json.dumps({
                    'summary': '优先核对缺失经营来源，再结合现有进度讨论目标。',
                    'projects': [{'key': p['key'], 'advice': '结合来源覆盖核对经营进度。'} for p in projected['projects']]})
            return validator(raw, projected)
        self.runner.provider = provider
        self.runner.model_runner = lambda projected, callback: callback(projected)
        with patch.object(game_fixture.g, 'collect', return_value=game_fixture.batch()):
            game = self.runner.run('game-monitor', 'manual')
        management = self.runner.run('management', 'manual')
        self.assertEqual(game['status'], 'succeeded')
        self.assertEqual(management['status'], 'succeeded')
        self.assertEqual([item['max_tokens'] for item in seen], [6000, 5000])
        self.assertTrue(all(item['timeout'] == 120 for item in seen))
        snapshot = json.loads((self.root / 'public/management.json').read_bytes())
        self.assertEqual(snapshot['advice']['status'], 'succeeded')
        self.assertEqual(snapshot['projects'][0]['actuals']['revenue_usd'], 1200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
