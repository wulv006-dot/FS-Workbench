import unittest
from datetime import datetime, timezone

from fc_collection.package_routes import collect_missing


class PackageRouting(unittest.TestCase):
    def test_direct_readers_share_the_origin_budget_with_each_other(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from fc_collection.coordinator import Coordinator
        from fc_collection.pilot import source_policy
        now = datetime.now(timezone.utc)
        with TemporaryDirectory() as tmp:
            ledger = Coordinator(Path(tmp) / 'collection.db')
            ledger.configure_source('IGGM', dict(source_policy(), mode='consume', origin='https://www.iggm.com'))
            with ledger.package_requests('IGGM', 'primary', 1, now):
                with self.assertRaisesRegex(ValueError, 'request_budget_unavailable'):
                    with ledger.package_requests('IGGM', 'concurrent', 1, now):
                        self.fail('concurrency limit')
            with ledger.package_requests('IGGM', 'readback', 1, now):
                pass
            with self.assertRaisesRegex(ValueError, 'request_budget_unavailable'):
                with ledger.package_requests('IGGM', 'excess', 1, now):
                    self.fail('origin budget')

    def test_local_worker_uses_its_own_ssh_config_and_returns_on_idle(self):
        from io import BytesIO
        from unittest.mock import patch
        from fc_collection.package_relay import local_once
        with patch('fc_collection.package_relay.subprocess.Popen') as launch:
            process = launch.return_value.__enter__.return_value
            process.stdout = BytesIO(b'{"status":"idle"}\n')
            local_once('worker-ssh-config')
        command = launch.call_args.args[0]
        self.assertEqual(command[:3], ['ssh', '-F', 'worker-ssh-config'])
        self.assertEqual(command[-1], 'fs-fc-iggm-readback')
        self.assertIn('StrictHostKeyChecking=yes', command)
        process.stdin.write.assert_not_called()

    def test_iggm_keeps_primary_and_supplement_and_tries_local_for_remaining_slots(self):
        now = datetime.now(timezone.utc)
        calls = []
        def read(node, request):
            calls.append((node, list(request['wanted'])))
            platform, quantity = request['wanted'][-1]
            if node == '183':
                raise ValueError('template_changed')
            offer = dict(source='IGGM', platform=platform, purchase_k=quantity, bonus_k='0',
                         regular_price='7', currency='USD', status='valid', conditional=False,
                         coupon_excluded=True, comparable=True, promotion_eligibility='all_customers',
                         delivery_method='comfort_trade', delivery_tier='standard',
                         captured_at=now.isoformat(), run_id='round')
            return dict(source='IGGM', run_id='round', offers=[offer], errors=[])
        rows, attempts = collect_missing('IGGM', 'round', [('PS','100'),('PC','1000')], read, lambda:now)
        self.assertEqual([node for node, _ in calls], ['187','183','local'])
        self.assertEqual(calls[1][1], [('PC','1000')])
        self.assertEqual(calls[2][1], [('PC','1000')])
        self.assertEqual([row['collection_node'] for row in rows], ['187','local'])
        self.assertEqual(len(attempts), 3)

    def test_rate_limit_is_saved_in_the_shared_ledger_for_the_following_round(self):
        from unittest.mock import patch
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from fc_collection.client import legacy_ready
        from fc_collection.coordinator import Coordinator
        from fc_collection.package_routes import record_restriction
        from fc_collection.pilot import source_policy
        with TemporaryDirectory() as tmp, patch('fc_collection.client.DATABASE', Path(tmp) / 'db.sqlite'):
            ledger = Coordinator(Path(tmp) / 'db.sqlite')
            policy = dict(source_policy(1), origin='https://www.iggm.com', mode='consume')
            ledger.configure_source('IGGM', policy)
            self.assertTrue(legacy_ready('IGGM', require_registered=True))
            request = dict(source='IGGM', run_id='round')
            record_restriction(request, dict(request, errors=['http_429'], retry_after_seconds=7200))
            self.assertFalse(legacy_ready('IGGM', require_registered=True))
            with ledger.transaction() as db:
                expiry = ledger._get(db, 'collection_sources', 'IGGM')['cooldown_until']
            self.assertGreater(expiry, datetime.now(timezone.utc).timestamp() + 7100)
