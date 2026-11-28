from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from source.hourly import QuoteUnavailable, preview_hour
from source.quotes import EldoradoOffer


def offer(seller, rate):
    return EldoradoOffer(seller, Decimal(rate), Decimal(300), Decimal(2000))


class HourlyPreviewTests(unittest.TestCase):
    def test_uses_183_only_for_the_failed_platform_and_reuses_the_receipt(self):
        calls = []

        def primary(platform):
            calls.append(("187", platform))
            if platform == "XBOX":
                raise QuoteUnavailable("browser_timeout")
            return offer("PS seller", "0.038")

        def backup(platform):
            calls.append(("183", platform))
            return offer("Xbox seller", "0.037")

        now = datetime(2026, 11, 23, 4, 10, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            first = preview_hour(Path(directory), primary, backup=backup, now=now)
            second = preview_hour(Path(directory), primary, backup=backup, now=now)

        self.assertEqual(calls, [("187", "PS"), ("187", "XBOX"), ("183", "XBOX")])
        self.assertEqual(first, second)
        self.assertEqual(first["quotes"]["XBOX"]["eldorado"]["node"], "183")
        self.assertEqual(first["quotes"]["XBOX"]["eldorado"]["attempts"][0]["reason"], "browser_timeout")
        self.assertEqual(first["targets"]["PS"], first["targets"]["SWITCH"])
        self.assertEqual(first["targets"]["XBOX"]["usd_per_k"], "0.037")
        self.assertEqual(first["status"], "preview_only")

    def test_explicit_source_access_denial_does_not_try_another_node(self):
        def primary(platform):
            if platform == "PS":
                raise QuoteUnavailable("http_403")
            return offer("Xbox seller", "0.037")

        def backup(platform):
            self.fail("An access denial must not change collection nodes")

        now = datetime(2026, 11, 23, 4, 10, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            result = preview_hour(Path(directory), primary, backup=backup, now=now)

        self.assertIsNone(result["targets"]["PS"])
        self.assertIsNone(result["targets"]["SWITCH"])
        self.assertEqual(result["quotes"]["PS"]["eldorado"]["attempts"],
                         [{"node": "187", "reason": "http_403"}])
