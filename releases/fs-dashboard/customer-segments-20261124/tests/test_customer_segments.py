from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
import customer_segments as segments


class SegmentationTests(unittest.TestCase):
    def test_fc27_stage_boundaries(self):
        observation = date(2026, 11, 23)
        for days, expected in (
            (0, "recent"),
            (13, "recent"),
            (14, "silent"),
            (29, "silent"),
            (30, "lost"),
            (59, "lost"),
            (60, "long_lost"),
        ):
            with self.subTest(days=days):
                last_paid = (observation - timedelta(days=days)).isoformat() + "T23:59:59"
                self.assertEqual(segments.stage(last_paid, observation, 1327, {"stages": {}}, True), expected)


    def test_stage_uses_shanghai_calendar_dates(self):
        last_paid = datetime(2026, 11, 8, 16, tzinfo=timezone.utc)
        self.assertEqual(segments.stage(last_paid, "2026-11-22", 1327, {"stages": {}}, True), "recent")
        self.assertEqual(segments.stage("2026-11-08T16:00:00Z", date(2026, 11, 23), 1327, {"stages": {}}, True), "silent")

    def test_stage_with_incomplete_coverage_is_unverified(self):
        self.assertEqual(segments.stage(None, date(2026, 11, 23), 1327, {"stages": {}}, False), "unverified")

    def test_all_scope_always_uses_common_thresholds(self):
        config = {"stages": {"1327": [1, 2, 3], "456": [7, 14, 30]}}
        self.assertEqual(segments.thresholds("all", config), (30, 60, 90))
        self.assertEqual(segments.stage("2026-10-24T23:59:59", date(2026, 11, 23), "all", config, True), "silent")
        self.assertEqual(segments.thresholds(1327, config), (1, 2, 3))
        self.assertEqual(segments.thresholds("456", config), (7, 14, 30))

    def test_defaults_follow_current_project_policies(self):
        config = {"stages": {}}
        self.assertEqual(segments.thresholds("833", config), (14, 30, 90))
        self.assertEqual(segments.thresholds(456, config), (30, 60, 90))
        self.assertEqual(segments.thresholds(552, config), (30, 60, 90))

    def test_repeat_requires_24_elapsed_hours(self):
        first = "2026-11-22T23:30:00+08:00"
        self.assertFalse(segments.is_repeat(first, first))
        self.assertFalse(segments.is_repeat(first, "2026-11-23T15:29:59Z"))
        self.assertTrue(segments.is_repeat(first, datetime(2026, 11, 23, 15, 30, tzinfo=timezone.utc)))

    def test_tier_thresholds_use_decimal_spend(self):
        config = {"tiers": {}}
        for amount, expected in (
            ("499.99", None),
            ("500", "high"),
            ("999.99", "high"),
            ("999.999999999999999999", "high"),
            ("1000", "ultra"),
        ):
            with self.subTest(amount=amount):
                self.assertEqual(segments.tier(Decimal(amount), 1327, config), expected)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "segments.json"

    def test_missing_file_returns_fresh_defaults(self):
        config, version, source = segments.load_config(self.path)
        self.assertEqual((version, source), (0, "default"))
        self.assertEqual(segments.thresholds(1327, config), (14, 30, 60))
        self.assertEqual(segments.tier("500", 1327, config), "high")
        config["stages"]["1327"][0] = 1
        self.assertEqual(segments.thresholds(1327, segments.load_config(self.path)[0]), (14, 30, 60))
        self.assertFalse(self.path.exists())

    def test_file_overrides_only_configured_games_and_keeps_precise_amounts(self):
        self.path.write_text(
            '{"version":4,"stages":{"1327":[10,20,40]},'
            '"tiers":{"1327":{"ultra":1000.000000000000000001,"high":600.25}}}',
            encoding="utf-8",
        )
        config, version, source = segments.load_config(self.path)
        self.assertEqual((version, source), (4, "file"))
        self.assertEqual(segments.thresholds(1327, config), (10, 20, 40))
        self.assertEqual(segments.thresholds(833, config), (14, 30, 90))
        self.assertEqual(segments.tier("600.24", 1327, config), None)
        self.assertEqual(segments.tier("600.25", 1327, config), "high")
        self.assertEqual(segments.tier("1000", 1327, config), "high")
        self.assertEqual(segments.tier("1000.000000000000000001", 1327, config), "ultra")
        self.assertEqual(segments.tier("500", 833, config), "high")

    def test_invalid_file_fails_without_falling_back(self):
        for payload in (
            "{",
            '{"version":true,"stages":{},"tiers":{}}',
            '{"version":-1,"stages":{},"tiers":{}}',
            '{"version":1,"stages":{},"tiers":{},"source":"file"}',
            '{"version":1,"version":2,"stages":{},"tiers":{}}',
            '{"version":1,"stages":{}}',
            '{"version":1,"stages":{"all":[1,2,3]},"tiers":{}}',
            '{"version":1,"stages":{"1327":[0,2,3]},"tiers":{}}',
            '{"version":1,"stages":{"1327":[1,3,3]},"tiers":{}}',
            '{"version":1,"stages":{"1327":[1.0,2,3]},"tiers":{}}',
            '{"version":1,"stages":{"1327":[true,2,3]},"tiers":{}}',
            '{"version":1,"stages":{},"tiers":{"1327":{"ultra":10,"high":-1}}}',
            '{"version":1,"stages":{},"tiers":{"1327":{"ultra":10,"high":10}}}',
            '{"version":1,"stages":{},"tiers":{"1327":{"ultra":NaN,"high":5}}}',
            '{"version":1,"stages":{},"tiers":{"1327":{"ultra":10,"high":5,"low":0}}}',
        ):
            with self.subTest(payload=payload):
                self.path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ValueError):
                    segments.load_config(self.path)


    def test_write_increments_version_and_archives_previous_file(self):
        first = {"version": 1, "stages": {"1327": [10, 20, 40]}, "tiers": {}}
        second = {"version": 2, "stages": {}, "tiers": {"1327": {"ultra": 1200, "high": "550.25"}}}
        segments.write_config(self.path, first, expected_version=0)
        original = self.path.read_bytes()
        self.assertEqual(segments.load_config(self.path), (first, 1, "file"))
        self.assertFalse((self.path.parent / "history" / "0.json").exists())

        segments.write_config(self.path, second, expected_version=1)
        self.assertEqual(segments.load_config(self.path), (second, 2, "file"))
        self.assertEqual((self.path.parent / "history" / "1.json").read_bytes(), original)

        with self.assertRaises(ValueError):
            segments.write_config(self.path, second, expected_version=1)
        with self.assertRaises(ValueError):
            segments.write_config(self.path, dict(second, version=4), expected_version=2)
        self.assertEqual(segments.load_config(self.path), (second, 2, "file"))
        self.assertFalse((self.path.parent / "history" / "2.json").exists())

    def test_replace_failure_leaves_previous_config_readable_and_can_retry(self):
        first = {"version": 1, "stages": {}, "tiers": {}}
        second = {"version": 2, "stages": {"1327": [9, 19, 39]}, "tiers": {}}
        segments.write_config(self.path, first, expected_version=0)
        original = self.path.read_bytes()
        replace = os.replace

        def fail_live_replace(source, target):
            if target == self.path:
                self.assertEqual(self.path.read_bytes(), original)
                raise OSError("injected replacement failure")
            return replace(source, target)

        with patch.object(segments.os, "replace", side_effect=fail_live_replace):
            with self.assertRaisesRegex(OSError, "injected replacement failure"):
                segments.write_config(self.path, second, expected_version=1)
        self.assertEqual(segments.load_config(self.path), (first, 1, "file"))

        segments.write_config(self.path, second, expected_version=1)
        self.assertEqual(segments.load_config(self.path), (second, 2, "file"))
        self.assertEqual((self.path.parent / "history" / "1.json").read_bytes(), original)

    def test_write_rejects_invalid_candidate_or_live_config(self):
        valid = {"version": 1, "stages": {}, "tiers": {}}
        with self.assertRaises(ValueError):
            segments.write_config(self.path, dict(valid, stages={"1327": [1, 1, 3]}), expected_version=0)
        self.assertFalse(self.path.exists())

        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            segments.write_config(self.path, valid, expected_version=0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{}")

    def test_concurrent_writers_cannot_both_commit_the_same_version(self):
        start = Barrier(2, timeout=5)

        def save(points):
            config = {"version": 1, "stages": {"1327": points}, "tiers": {}}
            start.wait()
            try:
                segments.write_config(self.path, config, expected_version=0)
            except segments.ConfigVersionConflict:
                return None
            return config

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ([10, 20, 40], [15, 30, 60])))
        self.assertEqual(results.count(None), 1)
        winner = next(config for config in results if config is not None)
        self.assertEqual(segments.load_config(self.path), (winner, 1, "file"))


if __name__ == "__main__":
    unittest.main()
