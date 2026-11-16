import tempfile
import unittest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from match_rewards import RewardError, RewardStore, coupon_snapshot_fingerprint


FINGERPRINT = "a" * 64
RECIPIENT_HASH = "c" * 64


class MatchRewardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RewardStore(Path(self.tmp.name) / "rewards.sqlite3")
        self.store.configure_offer("test-2026", 1385, FINGERPRINT, 3, 2, enabled=True)

    def credit(self, member=10, source="site:fixture-1-member-10", points=3):
        return self.store.credit_site_points(member, source, points, now=100)

    def test_site_settlement_is_idempotent_and_conflicts_fail(self):
        self.assertTrue(self.credit())
        self.assertFalse(self.credit())
        with self.assertRaisesRegex(RewardError, "changed"):
            self.credit(points=4)
        with self.assertRaisesRegex(RewardError, "first-party"):
            self.credit(source="discord:leaderboard", points=3)
        self.assertEqual(self.store.balance(10), 3)

    def test_one_member_one_claim_and_unknown_result_never_resends(self):
        self.credit()
        claim = self.store.claim("test-2026", 10, now=200)
        self.assertEqual(self.store.balance(10), 0)
        self.assertEqual(self.store.claim("test-2026", 10)["claim_id"], claim["claim_id"])
        with self.assertRaisesRegex(RewardError, "changed"):
            self.store.begin_grant(claim["claim_id"], "b" * 64, RECIPIENT_HASH)
        dispatch = self.store.begin_grant(claim["claim_id"], FINGERPRINT,
                                          RECIPIENT_HASH, now=201)
        self.assertEqual(dispatch["site_member_id"], 10)
        self.assertEqual(dispatch["batch_no"], claim["batch_no"])
        self.assertEqual(self.store.grant_target(claim["claim_id"])["recipient_email_hash"],
                         RECIPIENT_HASH)
        self.store.record_grant_result(claim["claim_id"], "unknown", now=202)
        self.store.configure_offer("test-2026", 1385, FINGERPRINT, 3, 2, enabled=False)
        self.assertEqual(self.store.claim_status("test-2026", 10)["status"], "unknown")
        with self.assertRaisesRegex(RewardError, "not ready"):
            self.store.begin_grant(claim["claim_id"], FINGERPRINT, RECIPIENT_HASH)
        with self.assertRaisesRegex(RewardError, "unsubmitted"):
            self.store.void_before_grant(claim["claim_id"])
        self.assertEqual(self.store.claim_status("test-2026", 10)["status"], "unknown")
        self.assertEqual(self.store.balance(10), 0)

    def test_pending_job_reconciles_to_one_member_coupon(self):
        self.credit()
        claim = self.store.claim("test-2026", 10)
        self.store.begin_grant(claim["claim_id"], FINGERPRINT, RECIPIENT_HASH)
        with self.assertRaisesRegex(RewardError, "job ID"):
            self.store.record_grant_result(claim["claim_id"], "pending")
        self.store.record_grant_result(claim["claim_id"], "pending", job_id="job-1")
        with self.assertRaisesRegex(RewardError, "changed"):
            self.store.record_grant_result(claim["claim_id"], "confirmed", job_id="job-2",
                                           member_coupon_id="member-coupon-1")
        self.store.record_grant_result(claim["claim_id"], "confirmed",
                                       member_coupon_id="member-coupon-1")
        self.assertEqual(self.store.claim("test-2026", 10)["member_coupon_id"],
                         "member-coupon-1")
        with self.assertRaises(RewardError):
            self.store.record_grant_result(claim["claim_id"], "confirmed",
                                           member_coupon_id="member-coupon-2")

    def test_parallel_grant_starts_allow_one_admin_post(self):
        self.credit()
        claim = self.store.claim("test-2026", 10)

        def begin(_):
            try:
                return self.store.begin_grant(claim["claim_id"], FINGERPRINT,
                                              RECIPIENT_HASH)["batch_no"]
            except RewardError:
                return None

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(begin, range(2)))
        self.assertEqual(results.count(claim["batch_no"]), 1)
        self.assertEqual(results.count(None), 1)

    def test_unsubmitted_reservation_can_be_reused_without_new_batch(self):
        self.credit()
        first = self.store.claim("test-2026", 10)
        self.store.void_before_grant(first["claim_id"])
        self.assertEqual(self.store.balance(10), 3)
        again = self.store.claim("test-2026", 10)
        self.assertEqual(again["claim_id"], first["claim_id"])
        self.assertEqual(again["batch_no"], first["batch_no"])
        self.assertEqual(self.store.balance(10), 0)

    def test_parallel_claims_cannot_exceed_stock_or_points(self):
        self.store.configure_offer("test-2026", 1385, FINGERPRINT, 3, 2, enabled=True)
        for member in range(10, 18):
            self.credit(member, "site:result-{}".format(member))

        def claim(member):
            try:
                return self.store.claim("test-2026", member)["claim_id"]
            except RewardError:
                return None

        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(claim, range(10, 18)))
        self.assertEqual(sum(x is not None for x in results), 2)
        self.assertEqual(len(set(x for x in results if x)), 2)

    def test_offer_terms_cannot_change_after_creation(self):
        with self.assertRaisesRegex(RewardError, "cannot change"):
            self.store.configure_offer("test-2026", 9999, FINGERPRINT, 3, 2, enabled=True)
        self.store.configure_offer("test-2026", 1385, FINGERPRINT, 3, 2, enabled=False)
        self.credit()
        with self.assertRaisesRegex(RewardError, "unavailable"):
            self.store.claim("test-2026", 10)

    def test_coupon_snapshot_detects_price_and_scope_changes(self):
        row = dict(id=1385, fetch_scene=4, status=1, mode_type=1, attain="10.00",
                   reduce="0.50", limit_qty=1, repeat_qty=1, site_id=266,
                   game_id=1327, goods_id=None, scope_bindings=[])
        fingerprint = coupon_snapshot_fingerprint(row)
        self.assertEqual(fingerprint, coupon_snapshot_fingerprint(dict(reversed(list(row.items())))))
        self.assertNotEqual(fingerprint, coupon_snapshot_fingerprint({**row, "reduce": "1.00"}))
        self.assertNotEqual(fingerprint, coupon_snapshot_fingerprint({**row, "goods_id": 42}))

    def test_paused_offer_blocks_a_reserved_grant_but_keeps_status_visible(self):
        self.credit()
        claim = self.store.claim("test-2026", 10)
        self.store.configure_offer("test-2026", 1385, FINGERPRINT, 3, 2, enabled=False)
        with self.assertRaisesRegex(RewardError, "not ready"):
            self.store.begin_grant(claim["claim_id"], FINGERPRINT, RECIPIENT_HASH)
        self.assertEqual(self.store.claim_status("test-2026", 10)["status"], "reserved")

    def test_existing_ledger_gets_recipient_hash_column_without_losing_claims(self):
        path = Path(self.tmp.name) / "existing.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE reward_claims (
                claim_id TEXT PRIMARY KEY, offer_id TEXT, site_member_id INTEGER,
                batch_no TEXT, cost_points INTEGER, status TEXT, job_id TEXT,
                member_coupon_id TEXT, created_at INTEGER, updated_at INTEGER)""")
            db.execute("INSERT INTO reward_claims VALUES (?,?,?,?,?,?,?,?,?,?)",
                       ("claim-1", "pilot", 42, "batch-1", 3, "reserved", None, None, 1, 1))
        RewardStore(path)
        with sqlite3.connect(path) as db:
            self.assertIn("recipient_email_hash",
                          {row[1] for row in db.execute("PRAGMA table_info(reward_claims)")})
            self.assertEqual(db.execute("SELECT status FROM reward_claims").fetchone()[0],
                             "reserved")


if __name__ == "__main__":
    unittest.main()
