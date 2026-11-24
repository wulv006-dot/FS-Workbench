import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import black_friday_test_grant as grant


class TestGrant(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        self.address = 'tester@example.test'
        self.cfg = {'recipient_sha256': hashlib.sha256(self.address.encode()).hexdigest(),
                    'paid': 1, 'completed': 1, 'coupon_id': 7}
        patcher = patch.object(grant, 'entitlement', side_effect=lambda uid: self.cfg if uid == 11 else None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bridge = Mock()
        self.bridge.detail.return_value = dict(id=7, type=1, status=1, site_id=266, game_id=1327,
            mode_type=1, fetch_scene=4, time_effect=2, days=7, is_open=0, limit_qty=1, repeat_qty=1,
            goods_id=0, product_type=0, attain='0.00', reduce='2.00', scope_bindings='',
            title='FC27 Black Friday D4 Pilot - $2 OFF')

    def run_claim(self):
        return grant.issue(self.state,11,self.address,self.bridge)

    def test_only_confirmed_original_can_be_replayed(self):
        self.bridge.grant.return_value = {'state':'pending','job_id':'one'}
        self.bridge.reconcile.return_value = {'state':'confirmed','member_coupon_id':'81'}
        self.assertEqual(self.run_claim(), ('pending',None))
        self.assertEqual(self.run_claim(), ('confirmed','81'))
        self.assertEqual(self.run_claim(), ('confirmed','81'))
        self.bridge.grant.assert_called_once()
        self.bridge.reconcile.assert_called_once()

    def test_unknown_write_is_not_repeated(self):
        self.bridge.grant.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.run_claim()
        self.assertEqual(self.run_claim(), ('submitted', None))
        self.bridge.grant.assert_called_once()

    def test_scope_and_terms(self):
        for owner,email in [(12,self.address),(11,'else@example.test')]:
            with self.assertRaises(ValueError):
                grant.issue(self.state,owner,email,self.bridge)
        self.bridge.detail.return_value['days'] = 1
        with self.assertRaises(ValueError):
            self.run_claim()
        self.bridge.grant.assert_not_called()
