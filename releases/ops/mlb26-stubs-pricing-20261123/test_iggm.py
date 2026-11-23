from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from source.hourly import QuoteUnavailable
from source.iggm import authorized_iggm_reader, load_iggm_receipt
from source.quotes import EldoradoOffer


NOW = datetime(2026, 11, 23, 4, 10, tzinfo=timezone.utc)


class IggmReceiptTests(unittest.TestCase):
    def test_requires_an_in_stock_quantity_for_the_same_eldorado_offer(self):
        data = {
            "source": "IGGM",
            "product": "MLB26_STUBS",
            "currency": "USD",
            "offers": {"PS": [
                {"purchase_k": 100, "total_usd": "3.29", "observed_at": NOW.isoformat(), "reference": "quote-100"},
                {"purchase_k": 300, "total_usd": "9.87", "observed_at": NOW.isoformat(), "reference": "quote-300"},
            ]},
        }
        read = authorized_iggm_reader(data, now=NOW)
        eldorado = EldoradoOffer("PS seller", Decimal("0.038"), Decimal(300), Decimal(500))

        self.assertEqual(read("PS", eldorado).reference, "quote-300")
        self.assertEqual(read("PS", None).reference, "quote-100")
        with self.assertRaisesRegex(QuoteUnavailable, "iggm_platform_missing"):
            read("XBOX", None)

        data["offers"]["PS"] = data["offers"]["PS"][1:]
        self.assertEqual(read("PS", None).reference, "quote-300")

    def test_unreadable_receipt_is_a_source_failure(self):
        with TemporaryDirectory() as directory:
            read = load_iggm_receipt(Path(directory) / "missing.json")
            with self.assertRaisesRegex(QuoteUnavailable, "iggm_receipt_unreadable"):
                read("PS", None)
