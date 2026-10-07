"""Offline checks only: no backend requests, real jobs or price writes."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
APP = REPO / 'fc27_cloud_browser'
sys.path[:0] = [str(HERE / 'source'), str(APP), str(REPO)]
import automation_tick as tick
import fc27_cloud_api as api

sys.modules['p2pah_session_service'] = types.SimpleNamespace(
    HEADERS={}, SessionManager=object, read_private_config=lambda: {})
spec = importlib.util.spec_from_file_location('rule_sync', HERE / 'source/player_sync_job.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

JID = 'cfaa3004-fcbe-5885-b9cf-52a76fbdf050'
CID = '9e7cd384-894e-48ca-89c8-4348863a5633'


class RuleTest(unittest.TestCase):
    def test_exact_six_sources_match_manifest(self):
        import hashlib
        manifest = json.loads((HERE / 'SOURCE-MANIFEST.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['files']), 6)
        for row in manifest['files']:
            data = (REPO / row['path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])
            self.assertEqual(len(data), row['bytes'])


    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('jobs', 'queue', 'player-sync'):
            (self.root / name).mkdir()
        for module in (tick, api):
            patcher = patch.object(module, 'ROOT', self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        policy = patch.object(tick, 'load_player_sync_policy', return_value={'enabled': True, 'revision': 8})
        policy.start()
        self.addCleanup(policy.stop)
        self.job = {'job_id': JID, 'kind': 'player_sync', 'status': 'failed',
                    'error': 'player_sync_not_confirmed', 'error_detail': 'player_sample_readback_timeout',
                    'created_at': '2026-10-07T11:11:01+00:00',
                    'request': {'coin_execution_id': CID, 'config_revision': 8}}
        self.ledger = {'job_id': JID, 'coin_execution_id': CID, 'mode': 'category_all',
                       'status': 'needs_reconcile', 'stage': 'stopped',
                       'error': 'player_sample_readback_timeout', 'completed_at': '2026-10-07T11:14:20+00:00'}
        self.save()

    def save(self):
        (self.root / 'jobs' / (JID + '.json')).write_text(json.dumps(self.job))
        (self.root / 'player-sync' / (JID + '.json')).write_text(json.dumps(self.ledger))

    def test_old_price_check_waived_without_mutating_history(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*.json')}
        self.assertEqual(tick.player_sync_gate(), 'ready')
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.json')})
        view = api.player_sync_view({'enabled': True, 'revision': 8})
        self.assertEqual(view['price_verification'], 'disabled')
        self.assertTrue(view['price_verification_waived'])
        self.assertEqual(view['last_job']['status'], 'failed')

    def test_unknown_or_rejected_write_still_blocks(self):
        for reason in ('TimeoutError', 'backend_response_invalid', 'backend_request_rejected'):
            self.job['error_detail'] = self.ledger['error'] = reason
            self.save()
            self.assertEqual(tick.player_sync_gate(), 'needs_reconcile')

    def test_missing_or_wrong_ledger_not_waived(self):
        self.ledger['coin_execution_id'] = 'other'
        self.save()
        self.assertEqual(tick.player_sync_gate(), 'needs_reconcile')
        (self.root / 'player-sync' / (JID + '.json')).unlink()
        self.assertEqual(tick.player_sync_gate(), 'needs_reconcile')

    def test_queued_or_running_still_blocks_concurrent_write(self):
        for state in ('queued', 'running'):
            self.job['status'] = state
            self.save()
            self.assertEqual(tick.player_sync_gate(), 'in_progress')

    def test_missing_followup_still_blocks(self):
        coin = {'kind': 'auto_cycle', 'status': 'ready', 'result': {'status': 'confirmed'},
                'player_sync_intent': {'enabled': True, 'revision': 8},
                'player_sync': {'status': 'enqueue_failed'}}
        (self.root / 'jobs/coin.json').write_text(json.dumps(coin))
        self.assertEqual(tick.player_sync_gate(), 'needs_reconcile')

    def test_deferred_coin_cycle_resumes_but_real_failure_does_not(self):
        now = datetime.now(timezone.utc)
        policy = {'system_enabled': True, 'mode': 'auto', 'platforms': ['PS'],
                  'revision': 28, 'interval_minutes': 120}
        last = {'status': 'ready', 'created_at': now.isoformat(), 'completed_at': now.isoformat(),
                'request': {'policy_revision': 28}, 'result': {'status': 'deferred_player_sync'}}
        self.assertEqual(tick.due(policy, last, now), 'due')
        last['status'] = 'failed'
        with patch.object(tick, 'retry_plan', return_value=None):
            self.assertEqual(tick.due(policy, last, now), 'paused_after_failure')

    def bulk(self, *, failure=None, dry=False):
        request = self.root / 'request.json'
        execution = self.root / 'execution.json'
        policy = self.root / 'policy.json'
        request.write_text(json.dumps({'job_id': JID, 'coin_execution_id': CID,
                                      'config_revision': 8, 'dry_run': dry}))
        execution.write_text(json.dumps({'execution_id': CID, 'status': 'CONFIRMED',
                                        'automatic': True, 'after': {'rows': [
                                            {'platform': x, 'b2c': '0.1'} for x in ('PS', 'XBOX', 'PC')]}}))
        policy.write_text(json.dumps({'enabled': True, 'revision': 8}))
        manager = types.SimpleNamespace(ensure=lambda: True)
        out = io.StringIO()
        with (patch.object(sync, 'ROOT', self.root), patch.object(sync, 'REQUEST', request),
              patch.object(sync, 'EXECUTION', execution), patch.object(sync, 'POLICY', policy),
              patch.object(sync, 'SessionManager', return_value=manager),
              patch.object(sync, 'read_private_config', return_value={}),
              patch.object(sync, 'api', return_value={'adminInfo': {'username': 'chenchao'}}),
              patch.object(sync, 'list_models', return_value=[{'id': 44007921}]),
              patch.object(sync, 'category_samples', side_effect=AssertionError('sample selection retired')),
              patch.object(sync, 'products', side_effect=AssertionError('player price GET forbidden')),
              patch.object(sync, 'public_formula_status', side_effect=AssertionError('price verification forbidden')),
              patch.object(sync, 'recalculate_category', side_effect=failure) as post,
              redirect_stdout(out)):
            try:
                sync.bulk_main()
            except SystemExit as exc:
                self.assertEqual(exc.code, 2)
            return post.call_count, json.loads(out.getvalue().splitlines()[-1])

    def test_wiki_card_without_price_no_longer_blocks_category_call(self):
        count, result = self.bulk()
        self.assertEqual(count, 1)
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['price_verification'], 'disabled')
        self.assertEqual(result['category_response'], 'accepted')
        ledger = json.loads((self.root / (JID + '.json')).read_text())
        self.assertEqual(ledger['sample_count'], 0)
        with self.assertRaisesRegex(ValueError, 'already_started'):
            self.bulk()

    def test_dry_run_does_not_post(self):
        count, result = self.bulk(dry=True)
        self.assertEqual((count, result['status']), (0, 'preflight_ready'))
        self.assertFalse((self.root / (JID + '.json')).exists())

    def test_category_timeout_retains_unknown_write_protection(self):
        count, result = self.bulk(failure=TimeoutError())
        self.assertEqual((count, result['status']), (1, 'needs_reconcile'))
        self.assertEqual(result['reason'], 'TimeoutError')
        ledger = json.loads((self.root / (JID + '.json')).read_text())
        self.assertEqual(ledger['status'], 'needs_reconcile')
        self.assertNotIn('category_response', ledger)


if __name__ == '__main__':
    unittest.main(verbosity=2)
