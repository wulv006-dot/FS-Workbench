"""IGGM's visible USD price must agree with its machine-readable attribute."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

try:
    import playwright.sync_api  # noqa: F401
except ModuleNotFoundError:
    package = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = None
    sys.modules["playwright"] = package
    sys.modules["playwright.sync_api"] = sync_api

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_competitor_browser import iggm_bonus_k, iggm_visible_price


class IGGMVisiblePriceTest(unittest.TestCase):
    def test_binary_float_tail_uses_confirmed_visible_price(self):
        self.assertEqual(
            iggm_visible_price({"display": "$ 14.68", "price": "14.680000000000001"}),
            "14.68",
        )

    def test_real_disagreement_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "iggm_display_attribute_mismatch"):
            iggm_visible_price({"display": "$ 14.68", "price": "14.69"})

    def test_non_usd_or_excess_display_precision_is_blocked(self):
        for display in ("¥ 14.68", "$ 14.680", "14.68", ""):
            with self.subTest(display=display):
                with self.assertRaisesRegex(ValueError, "iggm_display_price_invalid"):
                    iggm_visible_price({"display": display, "price": "14.68"})

    def test_visible_bonus_is_included_in_delivered_quantity(self):
        self.assertEqual(iggm_bonus_k({"label": "100 K\n+5 K"}), "5")
        self.assertEqual(iggm_bonus_k({"label": "100 K"}), "0")

    def test_ambiguous_package_label_is_blocked(self):
        for label in ("100 K +5 K new customers", "100 K +5%", "50 K +5 K", ""):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "iggm_package_label_invalid"):
                    iggm_bonus_k({"label": label})


if __name__ == "__main__":
    unittest.main()
