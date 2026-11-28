from decimal import Decimal
import unittest

from source.eldorado import collect_eldorado
from source.quotes import EldoradoOffer, parse_eldorado


class EldoradoQuoteTests(unittest.TestCase):
    def test_uses_the_current_recommended_seller_and_keeps_its_minimum_order(self):
        data = {
            "usd": True,
            "devices": ["PlayStation"],
            "seller": "TDDA",
            "offer": (
                "TDDA\n4.9\n1570 reviews\nIn stock\n843,333 K\n"
                "Min. qty.\n200 K\nDelivery time\n55 min - 1 h\nCurrent offer\n$0.028 / K"
            ),
        }

        self.assertEqual(
            parse_eldorado(data, "PlayStation"),
            EldoradoOffer("TDDA", Decimal("0.028"), Decimal("200"), Decimal("843333")),
        )

    def test_http_success_with_a_browser_challenge_is_an_access_failure(self):
        class Response:
            status = 200

        class ChallengePage:
            def goto(self, *args, **kwargs):
                return Response()

            def evaluate(self, script):
                return True

        with self.assertRaisesRegex(ValueError, "eldorado_challenge"):
            collect_eldorado(ChallengePage(), "PS")
