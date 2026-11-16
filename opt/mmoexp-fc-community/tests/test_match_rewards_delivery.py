import tempfile
import unittest
from pathlib import Path

from match_rewards import RewardError, RewardStore, coupon_snapshot_fingerprint
from match_rewards_delivery import RewardDelivery, email_fingerprint


COUPON = dict(id=2001, fetch_scene=4, status=1, mode_type=1,
              attain="10.00", reduce="0.50", limit_qty=10, repeat_qty=1,
              site_id=266, game_id=1327)


class CouponFake:
    def __init__(self):
        self.row = dict(COUPON)
        self.grants = []
        self.jobs = []
        self.grant_result = {"state": "confirmed", "member_coupon_id": "9001"}
        self.job_result = {"state": "confirmed", "member_coupon_id": "9001"}

    def detail(self, coupon_id):
        return dict(self.row)

    def grant(self, coupon_id, email, batch_no):
        self.grants.append((coupon_id, email, batch_no))
        if isinstance(self.grant_result, Exception):
            raise self.grant_result
        return dict(self.grant_result)

    def reconcile(self, job_id, email, batch_no):
        self.jobs.append((job_id, email, batch_no))
        return dict(self.job_result)


class RewardDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RewardStore(Path(self.tmp.name) / "reward.sqlite3")
        self.store.configure_offer("pilot", COUPON["id"],
                                   coupon_snapshot_fingerprint(COUPON), 3, 2, enabled=True)
        self.store.credit_site_points(42, "site:test-fixture-42", 3)
        self.claim = self.store.claim("pilot", 42)
        self.adapter = CouponFake()
        self.member = dict(site_id=266, member_id=42,
                           email="Owner@Example.com", email_verified=True,
                           account_active=True)
        self.delivery = RewardDelivery(self.store, lambda _: self.member, self.adapter)

    def test_sends_once_to_verified_member_and_duplicate_returns_original(self):
        first = self.delivery.deliver(self.claim["claim_id"])
        second = self.delivery.deliver(self.claim["claim_id"])
        self.assertEqual(first["status"], "confirmed")
        self.assertEqual(second["member_coupon_id"], "9001")
        self.assertEqual(self.adapter.grants,
                         [(2001, "owner@example.com", self.claim["batch_no"])])
        self.assertEqual(first["recipient_email_hash"],
                         email_fingerprint("owner@example.com"))
        self.assertNotIn("owner@example.com", repr(first))

    def test_unverified_or_mismatched_member_cannot_start_grant(self):
        for change in (dict(email_verified=False), dict(member_id=43),
                       dict(site_id=999), dict(account_active=False)):
            self.member = {**self.member, **change}
            with self.assertRaisesRegex(RewardError, "Verified MMOEXP member"):
                self.delivery.deliver(self.claim["claim_id"])
        self.assertEqual(self.adapter.grants, [])
        self.assertEqual(self.store.grant_target(self.claim["claim_id"])["status"],
                         "reserved")

    def test_coupon_scope_or_terms_change_blocks_post(self):
        self.adapter.row["game_id"] = 999
        with self.assertRaisesRegex(RewardError, "FC27 coupon"):
            self.delivery.deliver(self.claim["claim_id"])
        self.adapter.row = {**COUPON, "reduce": "1.00"}
        with self.assertRaisesRegex(RewardError, "changed"):
            self.delivery.deliver(self.claim["claim_id"])
        self.assertEqual(self.adapter.grants, [])

    def test_timeout_freezes_original_claim_and_never_reposts(self):
        self.adapter.grant_result = TimeoutError("admin response unknown")
        self.assertEqual(self.delivery.deliver(self.claim["claim_id"])["status"],
                         "unknown")
        self.delivery.deliver(self.claim["claim_id"])
        self.assertEqual(len(self.adapter.grants), 1)
        self.assertEqual(self.store.balance(42), 0)

    def test_async_result_only_checks_original_job(self):
        self.adapter.grant_result = {"state": "pending", "job_id": "job-7"}
        self.assertEqual(self.delivery.deliver(self.claim["claim_id"])["status"],
                         "pending")
        self.assertEqual(self.delivery.reconcile(self.claim["claim_id"])["status"],
                         "confirmed")
        self.assertEqual(self.adapter.jobs,
                         [("job-7", "owner@example.com", self.claim["batch_no"])])
        self.assertEqual(len(self.adapter.grants), 1)

    def test_email_change_during_async_job_stops_automatic_reconciliation(self):
        self.adapter.grant_result = {"state": "pending", "job_id": "job-7"}
        self.delivery.deliver(self.claim["claim_id"])
        self.member = {**self.member, "email": "new@example.com"}
        self.assertEqual(self.delivery.reconcile(self.claim["claim_id"])["status"],
                         "unknown")
        self.assertEqual(self.adapter.jobs, [])
        self.assertEqual(len(self.adapter.grants), 1)


if __name__ == "__main__":
    unittest.main()
