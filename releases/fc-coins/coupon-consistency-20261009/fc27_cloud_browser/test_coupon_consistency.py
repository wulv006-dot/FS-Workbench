"""Snapshot gate: cross-platform coupon consistency.

Covers the 2026-10-09 rule change in snapshot_layer.lootbar_snapshots():
the gate used to require `coupon_excluded is True` on EVERY platform (so a
site-side coupon withdrawal latched the whole pipeline). It now requires the
three platforms to AGREE on the coupon state -- which is the invariant that
actually keeps the platforms comparable.

Critical: a MIXED state must still fail closed. That is the case that would
produce a wrong quote.
"""
import importlib.util
import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone

def _locate_module():
    """Find snapshot_layer.py regardless of layout.

    Two layouts exist: the original scratch layout (test in tests/, module in
    ../candidate/) and the release layout (test and module side by side in
    fc27_cloud_browser/). Same directory wins; sibling candidate/ is the
    fallback.
    """
    here = pathlib.Path(__file__).resolve().parent
    for candidate in (here / "snapshot_layer.py",
                      here.parent / "candidate" / "snapshot_layer.py"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("snapshot_layer.py not found next to the test or in ../candidate/")


MODULE = _locate_module()

# snapshot_layer imports fc27_quote_engine.source_coverage at module scope, but
# lootbar_snapshots() never calls it. Stub the module so this unit test stays a
# pure test of the gate (the real engine is exercised on the server).
_quote_engine = type(sys)("fc27_quote_engine")
_quote_engine.source_coverage = lambda snapshots: {"ready": False}
sys.modules.setdefault("fc27_quote_engine", _quote_engine)

spec = importlib.util.spec_from_file_location("snapshot_layer", MODULE)
snapshot_layer = importlib.util.module_from_spec(spec)
sys.modules["snapshot_layer"] = snapshot_layer
spec.loader.exec_module(snapshot_layer)

PLATFORMS = ("PS", "XBOX", "PC")
RUN_ID = "11111111-2222-3333-4444-555555555555"


def offer(platform, coupon_excluded, usd="14.76", base_k="100", bonus_k="5"):
    row = {
        "platform": platform, "base_k": base_k, "usd_price": usd,
        "bonus_k": bonus_k, "coupon_excluded": coupon_excluded,
        "price_basis": "券前原价（已排除账号新客券）" if coupon_excluded else "当前无券商品价",
    }
    if coupon_excluded:
        row["observed_coupon_price"] = "13.29"
        row["excluded_coupon_discount"] = "1.47"
    return row


def events(offers, checked_at=None, stage="complete", read_only=True, ps_restored=True):
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    seq = [{"at": checked_at, "stage": "cdp_connected"}]
    if ps_restored:
        seq.append({"at": checked_at, "stage": "ps_restored"})
    seq.append({"at": checked_at, "stage": stage, "checked_at": checked_at,
                "offers": offers, "read_only": read_only})
    return seq


def all_offers(coupon_excluded):
    return {p: offer(p, coupon_excluded) for p in PLATFORMS}


class CouponConsistencyGate(unittest.TestCase):
    # ---- the two states that must now pass -------------------------------

    def test_all_platforms_with_coupon_passes(self):
        rows = snapshot_layer.lootbar_snapshots(RUN_ID, events(all_offers(True)))
        self.assertEqual([r["platform"] for r in rows], list(PLATFORMS))
        for row in rows:
            self.assertIs(row["coupon_excluded"], True)
            self.assertEqual(row["status"], "valid")

    def test_all_platforms_without_coupon_passes(self):
        """The 2026-10-09 case: LootBar withdrew the coupon on all platforms."""
        rows = snapshot_layer.lootbar_snapshots(RUN_ID, events(all_offers(False)))
        self.assertEqual([r["platform"] for r in rows], list(PLATFORMS))
        for row in rows:
            self.assertIs(row["coupon_excluded"], False)
            self.assertEqual(row["status"], "valid")
            # no-coupon rows must NOT fabricate coupon fields
            self.assertNotIn("observed_coupon_price", row)

    def test_coupon_state_is_carried_through_not_hardcoded(self):
        """The reported state must be the observed one, never forced to True."""
        without = snapshot_layer.lootbar_snapshots(RUN_ID, events(all_offers(False)))
        self.assertTrue(all(r["coupon_excluded"] is False for r in without))
        with_coupon = snapshot_layer.lootbar_snapshots(RUN_ID, events(all_offers(True)))
        self.assertTrue(all(r["coupon_excluded"] is True for r in with_coupon))

    # ---- the mixed states that must STILL fail closed ---------------------

    def test_two_with_one_without_is_rejected(self):
        """PS keeps the coupon, XBOX/PC lose it -> incomparable -> reject."""
        offers = all_offers(True)
        offers["XBOX"] = offer("XBOX", False)
        offers["PC"] = offer("PC", False)
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        self.assertEqual(str(ctx.exception), "platform_or_coupon_mismatch")

    def test_one_with_two_without_is_rejected(self):
        offers = all_offers(False)
        offers["PS"] = offer("PS", True)
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        self.assertEqual(str(ctx.exception), "platform_or_coupon_mismatch")

    def test_non_boolean_coupon_flag_is_rejected(self):
        """Three identical non-bool values must not slip through as 'agreed'."""
        for bogus in ("true", "True", 1, 0, None):
            with self.subTest(bogus=bogus):
                offers = {p: offer(p, bogus) for p in PLATFORMS}
                with self.assertRaises(ValueError) as ctx:
                    snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
                self.assertEqual(str(ctx.exception), "platform_or_coupon_mismatch")

    def test_missing_coupon_key_is_rejected(self):
        offers = all_offers(True)
        del offers["PC"]["coupon_excluded"]
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        self.assertEqual(str(ctx.exception), "platform_or_coupon_mismatch")

    # ---- pre-existing gates must be untouched ----------------------------

    def test_platform_label_drift_is_rejected(self):
        offers = all_offers(True)
        offers["PC"]["platform"] = "PS"
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        self.assertEqual(str(ctx.exception), "platform_or_coupon_mismatch")

    def test_unexpected_package_size_is_rejected(self):
        offers = all_offers(False)
        offers["PC"]["base_k"] = "50"
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        self.assertEqual(str(ctx.exception), "unexpected_package_size")

    def test_missing_platform_is_rejected(self):
        offers = all_offers(True)
        del offers["XBOX"]
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        self.assertEqual(str(ctx.exception), "platform_coverage_incomplete")

    def test_stale_capture_is_rejected(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=4000)).isoformat()
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(all_offers(False), checked_at=old))
        self.assertEqual(str(ctx.exception), "stale_capture")

    def test_collector_incomplete_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(all_offers(False), ps_restored=False))
        self.assertEqual(str(ctx.exception), "collector_incomplete")

    def test_invalid_bonus_is_rejected(self):
        offers = all_offers(False)
        offers["PS"]["bonus_k"] = "-1"
        with self.assertRaises(ValueError) as ctx:
            snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        self.assertEqual(str(ctx.exception), "invalid_bonus")

    # ---- arithmetic still correct in the new basis -----------------------

    def test_effective_price_math_unchanged_without_coupon(self):
        offers = all_offers(False)
        offers["PC"]["usd_price"] = "13.02"
        rows = snapshot_layer.lootbar_snapshots(RUN_ID, events(offers))
        pc = next(r for r in rows if r["platform"] == "PC")
        # 13.02 / (100 + 5) = 0.124
        self.assertEqual(pc["effective_usd_per_k"], "0.124")

    def test_run_id_is_stamped_on_every_row(self):
        rows = snapshot_layer.lootbar_snapshots(RUN_ID, events(all_offers(False)))
        self.assertTrue(all(r["run_id"] == RUN_ID for r in rows))
        self.assertTrue(all(r["source"] == "Lootbar" for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
