from decimal import Decimal
import unittest

from source.pricing import PlatformQuotes, plan_prices


class PricingTests(unittest.TestCase):
    def test_platforms_follow_the_cheaper_source_and_switch_uses_playstation(self):
        decisions = plan_prices(
            playstation=PlatformQuotes(eldorado=Decimal("0.031"), iggm=Decimal("0.035")),
            xbox=PlatformQuotes(eldorado=Decimal("0.030"), iggm=Decimal("0.050")),
        )

        self.assertEqual(
            {platform: (decision.usd_per_k, decision.source)
             for platform, decision in decisions.items()},
            {
                "PS": (Decimal("0.028"), "IGGM"),
                "XBOX": (Decimal("0.030"), "Eldorado"),
                "SWITCH": (Decimal("0.028"), "IGGM"),
            },
        )

    def test_single_source_is_used_for_each_platform(self):
        decisions = plan_prices(
            playstation=PlatformQuotes(iggm=Decimal("0.035")),
            xbox=PlatformQuotes(eldorado=Decimal("0.030")),
        )

        self.assertEqual(decisions["PS"].usd_per_k, Decimal("0.028"))
        self.assertEqual(decisions["SWITCH"].usd_per_k, Decimal("0.028"))
        self.assertEqual(decisions["XBOX"].usd_per_k, Decimal("0.030"))

    def test_both_quotes_missing_on_playstation_also_leaves_switch_without_a_target(self):
        decisions = plan_prices(
            playstation=PlatformQuotes(),
            xbox=PlatformQuotes(eldorado=Decimal("0.030")),
        )

        self.assertIsNone(decisions["PS"])
        self.assertIsNone(decisions["SWITCH"])
        self.assertEqual(decisions["XBOX"].usd_per_k, Decimal("0.030"))
