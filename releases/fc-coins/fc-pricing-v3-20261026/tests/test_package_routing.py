import unittest
from datetime import datetime, timezone

from fc_collection.package_routes import collect_missing


class PackageRouting(unittest.TestCase):
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
