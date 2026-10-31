"""Frozen synthetic B2 cases; no raw customer identity or external calls."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent / "source"))
from b2_customer_followup import Observation, assess


class B2Contracts(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 31, 10, tzinfo=timezone.utc)
        self.anchor = self.now - timedelta(days=5)
        self.o = Observation("e1", "synthetic_admin", "v1", self.now, True, True,
                             first_paid_at=self.now-timedelta(days=20), latest_paid_at=self.anchor)

    def check(self, observation=None, **changes):
        args = dict(now=self.now, observation_anchor=self.anchor,
                    recheck_at=self.now+timedelta(days=1))
        args.update(changes)
        return assess(observation or self.o, **args)

    def test_partial_identity_and_refund_need_evidence(self):
        for change in (dict(complete=False), dict(identity_verified=False),
                       dict(missing=("cost",)), dict(refund_review_needed=True)):
            self.assertEqual(self.check(replace(self.o, **change))["state"], "needs_evidence")

    def test_due_without_new_purchase(self):
        value = self.check(recheck_at=self.now)
        self.assertEqual(value["state"], "review_due")
        self.assertEqual(value["options"][0]["action"], "no_intervention")
        self.assertFalse(value["business_write_performed"])

    def test_same_evidence_suppressed_until_due(self):
        self.assertEqual(self.check(previous_evidence_ref="e1")["state"], "waiting")
        self.assertEqual(self.check(previous_evidence_ref="e1", recheck_at=self.now)["state"], "review_due")

    def test_stale_cutoff_requires_refresh(self):
        stale = replace(self.o, as_of=self.now-timedelta(hours=2))
        self.assertEqual(self.check(stale, recheck_at=self.now)["state"], "refresh_required")

    def test_sparse_history_does_not_invent_cadence(self):
        self.assertEqual(self.check()["reason"], "purchase_cadence_not_established")

    def test_supplied_cadence_changes_conclusion(self):
        self.assertEqual(self.check(expected_next_purchase_at=self.now+timedelta(days=4))["state"], "waiting")
        self.assertEqual(self.check(expected_next_purchase_at=self.now-timedelta(days=1))["state"], "investigate")

    def test_cadence_trigger_does_not_require_new_evidence_id(self):
        self.assertEqual(self.check(previous_evidence_ref="e1", expected_next_purchase_at=self.now)["state"], "investigate")

    def test_purchase_observation_does_not_claim_effect(self):
        value = self.check(replace(self.o, latest_paid_at=self.now))
        self.assertEqual(value["state"], "purchase_observed")
        self.assertNotIn("incremental_revenue", value)

    def test_stopped_goal_stays_stopped(self):
        self.assertEqual(self.check(goal_active=False)["state"], "stopped")

    def test_maturity_uses_source_cutoff_not_current_time(self):
        o = replace(self.o, first_paid_at=self.now-timedelta(days=7),
                    latest_paid_at=self.now-timedelta(days=7), as_of=self.now-timedelta(days=1))
        self.assertFalse(self.check(o)["maturity"]["7"])
        self.assertEqual(self.check(replace(o, complete=False))["maturity"]["7"], None)

    def test_missing_or_corrected_first_payment_does_not_publish_maturity(self):
        old = replace(self.o, first_paid_at=self.now-timedelta(days=35))
        for change in (dict(missing=("first_paid_history",)), dict(refund_review_needed=True)):
            with self.subTest(change=change):
                value = self.check(replace(old, **change))
                self.assertEqual(value["state"], "needs_evidence")
                self.assertEqual(value["maturity"], {"7": None, "14": None, "30": None})

    def test_earlier_purchase_does_not_suppress_due_recheck(self):
        old = replace(self.o, latest_paid_at=self.now-timedelta(days=4),
                      as_of=self.now-timedelta(days=2))
        value = self.check(old, previous_evidence_ref="e1", recheck_at=self.now)
        self.assertEqual(value["state"], "refresh_required")
        self.assertTrue(value["purchase_since_anchor"])
        fresh = self.check(replace(old, as_of=self.now), previous_evidence_ref="e1", recheck_at=self.now)
        self.assertEqual(fresh["state"], "review_due")
        self.assertTrue(fresh["purchase_since_anchor"])

    def test_earlier_purchase_does_not_suppress_cadence_trigger(self):
        old = replace(self.o, latest_paid_at=self.now-timedelta(days=4),
                      as_of=self.now-timedelta(days=2))
        value = self.check(old, previous_evidence_ref="e1", expected_next_purchase_at=self.now)
        self.assertEqual(value["state"], "refresh_required")
        fresh = self.check(replace(old, as_of=self.now), previous_evidence_ref="e1",
                           expected_next_purchase_at=self.now)
        self.assertEqual(fresh["state"], "investigate")
        self.assertTrue(fresh["purchase_since_anchor"])

    def test_future_naive_and_inverted_history_rejected(self):
        for o in (replace(self.o, as_of=self.now+timedelta(seconds=1)),
                  replace(self.o, as_of=self.now.replace(tzinfo=None)),
                  replace(self.o, first_paid_at=self.now),
                  replace(self.o, latest_paid_at=self.now+timedelta(seconds=1))):
            with self.assertRaises(ValueError):
                self.check(o)


if __name__ == "__main__":
    unittest.main()
