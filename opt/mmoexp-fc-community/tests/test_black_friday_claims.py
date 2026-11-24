import hashlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from black_friday_claims import Campaign, ClaimConflict


class CampaignFlow(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        self.coupons = {'one': 11, 'two': 22, 'bonus': 33}
        self.addresses = ['new@example.test', 'return@example.test', 'five@example.test']
        self.histories = dict(zip(self.addresses, [
            SimpleNamespace(member_id=41, paid=0, completed=0),
            SimpleNamespace(member_id=42, paid=5, completed=4),
            SimpleNamespace(member_id=43, paid=5, completed=5),
        ]))
        self.lookup = Mock(side_effect=self.histories.__getitem__)
        self.bridge = Mock()
        self.bridge.detail.side_effect = self.coupon_detail
        self.bridge.grant.side_effect = self.grant
        self.campaign = Campaign(self.state, self.coupons, self.lookup, self.bridge)

    @staticmethod
    def coupon_detail(coupon_id):
        mode, value = {11: (1, 1), 22: (1, 2), 33: (2, 85)}[coupon_id]
        return dict(id=coupon_id, type=1, status=1, site_id=266, game_id=1327,
                    mode_type=mode, fetch_scene=4, time_effect=2, days=7, is_open=0,
                    repeat_qty=1, goods_id=0, product_type=0, attain=0, max_reduce=0,
                    reduce=value, scope_bindings='')

    @staticmethod
    def grant(coupon_id, email, batch):
        return {'state': 'confirmed', 'member_coupon_id': str(1000 + coupon_id)}

    def test_three_tiers_use_the_same_delivery_path(self):
        for discord_id, email, expected in zip((51, 52, 53), self.addresses,
                [('one', ('1011',)), ('two', ('1022',)), ('bonus', ('1022', '1033'))]):
            with self.subTest(expected=expected):
                receipt = self.campaign.claim(discord_id, email)
                self.assertEqual((receipt.tier, receipt.receipts), expected)
                self.assertTrue(receipt.complete)

    def test_old_twenty_percent_bonus_is_rejected_before_shipping_any_coupon(self):
        self.bridge.detail.side_effect = lambda coupon: (
            dict(self.coupon_detail(coupon), reduce=80) if coupon == 33 else self.coupon_detail(coupon))
        with self.assertRaisesRegex(ValueError, 'coupon terms'):
            self.campaign.claim(53, self.addresses[2])
        self.bridge.grant.assert_not_called()

    def test_repeat_does_not_post_and_both_identities_are_unique(self):
        email, other = self.addresses[:2]
        first = self.campaign.claim(51, email)
        replay = self.campaign.claim(51, email.upper())
        self.assertEqual(first.receipts, replay.receipts)
        self.assertTrue(replay.replay)
        self.histories['alias@example.test'] = self.histories[email]
        for discord_id, address in [(51, other), (52, email), (52, 'alias@example.test')]:
            with self.assertRaises(ClaimConflict):
                self.campaign.claim(discord_id, address)
        self.bridge.grant.assert_called_once()

    def test_no_order_email_can_claim_once_without_an_admin_member_lookup(self):
        email, other = self.addresses[:2]
        self.histories[email] = SimpleNamespace(member_id=None, paid=0, completed=0)
        receipt = self.campaign.claim(51, email)
        self.assertEqual((receipt.tier, receipt.receipts), ('one', ('1011',)))
        self.assertTrue(self.campaign.claim(51, email.upper()).replay)
        for discord_id, address in [(52, email), (51, other)]:
            with self.assertRaises(ClaimConflict):
                self.campaign.claim(discord_id, address)
        self.histories[other] = SimpleNamespace(member_id=None, paid=0, completed=0)
        self.assertTrue(self.campaign.claim(52, other).complete)
        self.assertEqual(self.bridge.grant.call_count, 2)

    def test_old_claims_table_keeps_its_existing_delivery(self):
        receipt = self.campaign.claim(52, self.addresses[1])
        with sqlite3.connect(self.campaign.path) as db:
            db.execute('''CREATE TABLE old_claims (
                discord_id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL UNIQUE,
                email_hash TEXT NOT NULL UNIQUE, tier TEXT NOT NULL)''')
            db.execute('INSERT INTO old_claims SELECT * FROM claims')
            db.execute('DROP TABLE claims')
            db.execute('ALTER TABLE old_claims RENAME TO claims')
        campaign = Campaign(self.state, self.coupons, self.lookup, self.bridge)
        self.assertEqual(campaign.claim(52, self.addresses[1]).receipts, receipt.receipts)
        self.bridge.grant.assert_called_once()

    def test_concurrent_claim_sends_only_once(self):
        with ThreadPoolExecutor(4) as pool:
            receipts = list(pool.map(lambda _: self.campaign.claim(51, self.addresses[0]), range(8)))
        self.assertTrue(any(receipt.complete for receipt in receipts))
        self.bridge.grant.assert_called_once()

    def test_pending_bonus_reads_original_job_without_repeating_base(self):
        bonus_address = self.addresses[2]
        self.bridge.grant.side_effect = lambda coupon, email, batch: (
            self.grant(coupon, email, batch) if coupon == 22 else {'state': 'pending', 'job_id': 'original'})
        self.bridge.reconcile.return_value = {'state': 'confirmed', 'member_coupon_id': '1033'}
        first = self.campaign.claim(53, bonus_address)
        self.assertEqual(first.receipts, ('1022',))
        self.assertFalse(first.complete)
        second = self.campaign.claim(53, bonus_address, resume_only=True)
        self.assertEqual(second.receipts, ('1022', '1033'))
        self.assertTrue(second.complete)
        self.assertEqual(self.bridge.grant.call_count, 2)
        self.bridge.reconcile.assert_called_once()
        self.assertEqual(self.bridge.reconcile.call_args.args[0], 'original')

    def test_closed_receipt_check_cannot_create_fresh_claim(self):
        with self.assertRaises(ClaimConflict):
            self.campaign.claim(53, self.addresses[2], resume_only=True)
        self.lookup.assert_not_called()
        self.bridge.grant.assert_not_called()

    def test_admin_refusal_stays_terminal_without_a_second_post(self):
        self.bridge.grant.side_effect = None
        self.bridge.grant.return_value = {'state': 'rejected'}
        for _ in range(2):
            self.assertTrue(self.campaign.claim(51, self.addresses[0]).rejected)
        self.bridge.grant.assert_called_once()

    def test_indeterminate_submit_is_never_reposted(self):
        self.bridge.grant.side_effect = TimeoutError
        for _ in range(2):
            self.assertFalse(self.campaign.claim(53, self.addresses[2]).complete)
        self.bridge.grant.assert_called_once()

    def test_legacy_real_receipt_also_blocks_another_member_or_discord(self):
        digest = hashlib.sha256(self.addresses[1].encode()).hexdigest()
        legacy = dict(discord_id=51, member_id=42, recipient_sha256=digest, coupon_id=91)
        legacy_batch = 'FC27R_' + hashlib.sha256(('BF26-D4-single:' + digest).encode()).hexdigest()[:32].upper()
        with sqlite3.connect(self.state / 'real-grant.sqlite3') as db:
            db.execute('CREATE TABLE grants (batch, coupon, status, job, receipt)')
            db.execute('INSERT INTO grants VALUES (?,91,\'confirmed\',NULL,\'98765\')', (legacy_batch,))
        campaign = Campaign(self.state, self.coupons, self.lookup, self.bridge, legacy=legacy)
        self.assertEqual(campaign.claim(51, self.addresses[1]).receipts, ('98765',))
        with self.assertRaises(ClaimConflict):
            campaign.claim(52, self.addresses[1])
        self.bridge.grant.assert_not_called()
