import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from match_rewards import RewardError
from match_rewards_delivery import RewardDelivery, WeeklyEmailDelivery
from verified_prize_claim import (COUPON_STOCK_CAP, DISCOUNT_PERCENT, GAME_ID, SITE_ID,
                                  VALID_DAYS_AFTER_CLAIM, WINNER_CAP,
                                  VerifiedPrizeClaims, validate_campaign_coupon)


COUPON = dict(id=2001, title="FC27 weekly reward", type=1,
              fetch_scene=4, status=1, mode_type=2, attain="0",
              reduce="92", max_reduce="0", limit_qty=30, repeat_qty=1,
              time_effect=2, days=7, site_id=266, game_id=1327, is_open=0)


class VerifiedPrizeClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VerifiedPrizeClaims(Path(self.tmp.name) / "weekly.sqlite3")

    def issue(self, number=1, week="2026-W47"):
        return self.store.issue(week, "unify-proof:{}".format(number),
                                "unify-player:{}".format(number), COUPON,
                                expires_at=500, now=100)

    def test_campaign_rule_is_explicit(self):
        self.assertEqual((DISCOUNT_PERCENT, VALID_DAYS_AFTER_CLAIM,
                          COUPON_STOCK_CAP, WINNER_CAP, SITE_ID, GAME_ID),
                         (8, 7, 30, 20, 266, 1327))
        self.assertEqual(len(validate_campaign_coupon(COUPON)), 64)
        for change in ({"reduce": "90"}, {"max_reduce": "50"},
                       {"days": 1}, {"game_id": 0}, {"limit_qty": 31},
                       {"status": 0}, {"attain": "10"}):
            with self.assertRaisesRegex(RewardError, "do not match"):
                validate_campaign_coupon({**COUPON, **change})

    def test_ticket_is_hashed_and_one_account_per_week(self):
        first = self.issue()
        self.assertNotIn(first["ticket"], Path(self.store.path).read_bytes().decode("latin1"))
        claimed = self.store.redeem(first["ticket"], "unify-player:1", 42, now=200)
        self.assertEqual(claimed["status"], "reserved")
        self.assertNotIn("ticket_hash", claimed)
        self.assertNotIn("subject_hash", claimed)
        self.assertEqual(self.store.redeem(first["ticket"], "unify-player:1", 42, now=201)["claim_id"],
                         claimed["claim_id"])
        with self.assertRaisesRegex(RewardError, "unavailable"):
            self.store.redeem(first["ticket"], "unify-player:1", 43, now=201)
        second = self.issue(2)
        with self.assertRaisesRegex(RewardError, "already claimed"):
            self.store.redeem(second["ticket"], "unify-player:2", 42, now=201)
        next_week = self.issue(3, week="2026-W48")
        self.assertEqual(self.store.redeem(next_week["ticket"], "unify-player:3", 42, now=201)["status"],
                         "reserved")

    def test_forwarded_ticket_cannot_be_redeemed_by_another_player(self):
        ticket = self.issue()
        with self.assertRaisesRegex(RewardError, "another player"):
            self.store.redeem(ticket["ticket"], "unify-player:2", 43, now=200)
        self.assertEqual(self.store.redeem(ticket["ticket"], "unify-player:1", 42,
                                           now=200)["status"], "reserved")
        with self.assertRaisesRegex(RewardError, "another player"):
            self.store.redeem(ticket["ticket"], "unify-player:2", 42, now=201)

    def test_private_claim_needs_only_the_authenticated_player(self):
        self.issue()
        with self.assertRaisesRegex(RewardError, "No verified reward"):
            self.store.redeem_for_player("2026-W47", "unify-player:2", 43, now=200)
        claim = self.store.redeem_for_player("2026-W47", "unify-player:1", 42,
                                             now=200)
        self.assertEqual(claim["status"], "reserved")
        self.assertEqual(self.store.redeem_for_player("2026-W47", "unify-player:1",
                                                       42, now=201)["claim_id"],
                         claim["claim_id"])
        with self.assertRaisesRegex(RewardError, "unavailable"):
            self.store.redeem_for_player("2026-W47", "unify-player:1", 43, now=201)

    def test_email_only_claim_is_one_account_per_week(self):
        self.issue(1)
        self.issue(2)
        claim = self.store.redeem_email_for_player("2026-W47", "unify-player:1",
                                                   " Player@Example.com ", now=200)
        self.assertEqual(claim["status"], "reserved")
        with self.assertRaisesRegex(RewardError, "already claimed"):
            self.store.redeem_email_for_player("2026-W47", "unify-player:2",
                                               "player@example.com", now=200)
        with self.assertRaisesRegex(RewardError, "unavailable"):
            self.store.redeem_email_for_player("2026-W47", "unify-player:1",
                                               "different@example.com", now=200)
        with self.assertRaisesRegex(RewardError, "No verified reward"):
            self.store.redeem_email_for_player("2026-W47", "unify-player:3",
                                               "other@example.com", now=200)
        self.assertEqual(self.store.redeem_email_for_player("2026-W47",
                         "unify-player:1", "player@example.com", now=201)["claim_id"],
                         claim["claim_id"])

    def test_email_only_delivery_confirms_once(self):
        self.issue()
        claim = self.store.redeem_email_for_player("2026-W47", "unify-player:1",
                                                   "player@example.com", now=200)

        class Adapter:
            grants = []

            def detail(self, _):
                return COUPON

            def grant(self, coupon_id, email, batch_no):
                self.grants.append((coupon_id, email, batch_no))
                return {"state": "confirmed", "member_coupon_id": "9001"}

        adapter = Adapter()
        delivery = WeeklyEmailDelivery(self.store, adapter)
        with self.assertRaisesRegex(RewardError, "email changed"):
            delivery.deliver(claim["claim_id"], "other@example.com")
        self.assertEqual(delivery.deliver(claim["claim_id"],
                                          "PLAYER@example.com")["status"], "confirmed")
        self.assertEqual(delivery.deliver(claim["claim_id"],
                                          "player@example.com")["status"], "confirmed")
        self.assertEqual(len(adapter.grants), 1)
        self.assertEqual(adapter.grants[0][1], "player@example.com")

    def test_email_only_pending_checks_original_job(self):
        self.issue()
        claim = self.store.redeem_email_for_player("2026-W47", "unify-player:1",
                                                   "player@example.com", now=200)

        class Adapter:
            grants = 0
            checks = 0

            def detail(self, _):
                return COUPON

            def grant(self, *_):
                self.grants += 1
                return {"state": "pending", "job_id": "job-1"}

            def reconcile(self, job_id, email, batch_no):
                self.checks += 1
                self_outer.assertEqual((job_id, email), ("job-1", "player@example.com"))
                return {"state": "confirmed", "member_coupon_id": "9001"}

        self_outer = self
        adapter = Adapter()
        delivery = WeeklyEmailDelivery(self.store, adapter)
        self.assertEqual(delivery.deliver(claim["claim_id"],
                                          "player@example.com")["status"], "pending")
        with self.assertRaisesRegex(RewardError, "email changed"):
            delivery.reconcile(claim["claim_id"], "other@example.com")
        self.assertEqual(delivery.reconcile(claim["claim_id"],
                                            "player@example.com")["status"], "confirmed")
        self.assertEqual((adapter.grants, adapter.checks), (1, 1))

    def test_evidence_and_weekly_limit_are_atomic(self):
        self.issue()
        with self.assertRaisesRegex(RewardError, "Player already"):
            self.issue()
        with self.assertRaisesRegex(RewardError, "Player already"):
            self.store.issue("2026-W47", "unify-proof:other", "unify-player:1",
                             COUPON, expires_at=500, now=100)
        for n in range(2, WINNER_CAP + 1):
            self.issue(n)
        with self.assertRaisesRegex(RewardError, "cap reached"):
            self.issue(WINNER_CAP + 1)

    def test_invalid_and_expired_ticket(self):
        with self.assertRaisesRegex(RewardError, "Invalid ticket"):
            self.store.redeem("wrong", "unify-player:1", 42, now=200)
        ticket = self.issue()
        with self.assertRaisesRegex(RewardError, "expired"):
            self.store.redeem(ticket["ticket"], "unify-player:1", 42, now=500)

    def test_parallel_claim_of_same_week_has_one_winner(self):
        tickets = [(self.issue(n)["ticket"], "unify-player:{}".format(n)) for n in (1, 2)]

        def redeem(item):
            try:
                return self.store.redeem(item[0], item[1], 42, now=200)["claim_id"]
            except RewardError:
                return None

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(redeem, tickets))
        self.assertEqual(sum(bool(x) for x in results), 1)

    def test_existing_delivery_sends_once_and_unknown_does_not_retry(self):
        coupon = dict(COUPON)
        issued = self.store.issue("2026-W47", "unify-proof:one",
                                  "unify-player:one", coupon,
                                  expires_at=500, now=100)
        claim = self.store.redeem(issued["ticket"], "unify-player:one", 42, now=200)

        class Adapter:
            grants = []

            def detail(self, _):
                return coupon

            def grant(self, coupon_id, email, batch_no):
                self.grants.append((coupon_id, email, batch_no))
                raise TimeoutError("unknown result")

        adapter = Adapter()
        member = dict(site_id=266, member_id=42, email="player@example.com",
                      email_verified=True, account_active=True)
        delivery = RewardDelivery(self.store, lambda _: member, adapter)
        self.assertEqual(delivery.deliver(claim["claim_id"])["status"], "unknown")
        self.assertEqual(delivery.deliver(claim["claim_id"])["status"], "unknown")
        self.assertEqual(len(adapter.grants), 1)

    def test_confirmed_delivery_does_not_send_again(self):
        issued = self.store.issue("2026-W47", "unify-proof:confirm",
                                  "unify-player:confirm", COUPON,
                                  expires_at=500, now=100)
        claim = self.store.redeem(issued["ticket"], "unify-player:confirm", 42, now=200)

        class Adapter:
            grants = 0

            def detail(self, _):
                return COUPON

            def grant(self, *_):
                self.grants += 1
                return {"state": "confirmed", "member_coupon_id": "9001"}

        adapter = Adapter()
        member = dict(site_id=266, member_id=42, email="player@example.com",
                      email_verified=True, account_active=True)
        delivery = RewardDelivery(self.store, lambda _: member, adapter)
        self.assertEqual(delivery.deliver(claim["claim_id"])["status"], "confirmed")
        self.assertEqual(delivery.deliver(claim["claim_id"])["status"], "confirmed")
        self.assertEqual(adapter.grants, 1)


if __name__ == "__main__":
    unittest.main()
