from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import multiprocessing
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
import customer_segments as segments


def _exit_before_live_replace(path, config):
    replace = os.replace

    def interrupt_live_replace(source, target):
        if target == path:
            os._exit(23)
        return replace(source, target)

    with patch.object(segments.os, "replace", side_effect=interrupt_live_replace):
        segments.write_config(path, config, expected_version=config["version"] - 1)


def _write_concurrently(path, points, start, results):
    config = {"version": 1, "stages": {"1327": points}, "tiers": {}}
    start.wait()
    try:
        segments.write_config(path, config, expected_version=0)
    except segments.ConfigVersionConflict:
        results.put(("conflict", config))
    else:
        results.put(("committed", config))


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

    def test_stage_crosses_shanghai_midnight_with_utc_inputs(self):
        last_paid = datetime(2026, 11, 8, 15, 59, 59, tzinfo=timezone.utc)
        for observed_at, expected in (
            (datetime(2026, 11, 21, 15, 59, 59, tzinfo=timezone.utc), "recent"),
            (datetime(2026, 11, 21, 16, tzinfo=timezone.utc), "silent"),
        ):
            with self.subTest(observed_at=observed_at):
                self.assertEqual(segments.stage(last_paid, observed_at, 1327, {"stages": {}}, True), expected)

    def test_stage_rejects_last_payment_on_a_later_shanghai_date(self):
        last_paid = "2026-11-08T16:00:00Z"
        for covered in (True, False):
            with self.subTest(covered=covered):
                with self.assertRaisesRegex(ValueError, "after observation date"):
                    segments.stage(last_paid, "2026-11-08", 1327, {"stages": {}}, covered)
        self.assertEqual(segments.stage(last_paid, "2026-11-09", 1327, {"stages": {}}, True), "recent")
        self.assertEqual(segments.stage(last_paid, "2026-11-09", 1327, {"stages": {}}, False), "unverified")

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


    def test_caller_excludes_unknown_orders_before_classifying_known_spend(self):
        config = {"tiers": {}}
        amounts = [Decimal("499.99"), None, Decimal("0.01")]
        subtotal = sum(amount for amount in amounts if amount is not None)
        self.assertEqual(segments.tier(subtotal, 1327, config), "high")
        with self.assertRaisesRegex(ValueError, "invalid USD amount"):
            segments.tier(None, 1327, config)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "segments.json"

    def _start_process(self, worker):
        worker.start()
        self.addCleanup(self._close_process, worker)

    @staticmethod
    def _close_process(worker):
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        worker.close()

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

    def test_active_version_zero_file_is_rejected(self):
        self.path.write_bytes(b'{"version":0,"stages":{},"tiers":{}}')
        with self.assertRaisesRegex(ValueError, "invalid config version"):
            segments.load_config(self.path)

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
        self.assertEqual(
            (self.path.parent / "history" / "0.json").read_bytes(),
            b'{"stages": {"1327": [14, 30, 60], "833": [14, 30, 90]}, "tiers": {}, "version": 0}\n',
        )

        segments.write_config(self.path, second, expected_version=1)
        self.assertEqual(segments.load_config(self.path), (second, 2, "file"))
        self.assertEqual((self.path.parent / "history" / "1.json").read_bytes(), original)

        with self.assertRaises(ValueError):
            segments.write_config(self.path, second, expected_version=1)
        with self.assertRaises(ValueError):
            segments.write_config(self.path, dict(second, version=4), expected_version=2)
        self.assertEqual(segments.load_config(self.path), (second, 2, "file"))
        self.assertFalse((self.path.parent / "history" / "2.json").exists())

    def test_process_exit_after_archive_keeps_previous_config_and_allows_retry(self):
        first = {"version": 1, "stages": {}, "tiers": {}}
        second = {"version": 2, "stages": {"1327": [9, 19, 39]}, "tiers": {}}
        segments.write_config(self.path, first, expected_version=0)
        original = self.path.read_bytes()

        context = multiprocessing.get_context("spawn")
        worker = context.Process(target=_exit_before_live_replace, args=(self.path, second))
        self._start_process(worker)
        worker.join(15)
        self.assertEqual(worker.exitcode, 23)
        self.assertEqual(segments.load_config(self.path), (first, 1, "file"))
        archive = self.path.parent / "history" / "1.json"
        self.assertEqual(archive.read_bytes(), original)

        segments.write_config(self.path, second, expected_version=1)
        self.assertEqual(segments.load_config(self.path), (second, 2, "file"))
        self.assertEqual(archive.read_bytes(), original)

    def test_failed_directory_sync_after_live_replace_reports_unknown_commit(self):
        segments.write_config(self.path, {"version": 1, "stages": {}, "tiers": {}}, expected_version=0)
        candidate = {
            "version": 2,
            "stages": {"1327": (9, 19, 39)},
            "tiers": {"1327": {"ultra": 1000, "high": Decimal("550.25")}},
        }
        readback = {
            "version": 2,
            "stages": {"1327": [9, 19, 39]},
            "tiers": {"1327": {"ultra": 1000, "high": "550.25"}},
        }
        sync_directory = segments._sync_directory
        failure = OSError("injected directory fsync failure")

        def fail_after_live_replace(directory):
            if directory == self.path.parent and segments.load_config(self.path)[1] == 2:
                raise failure
            sync_directory(directory)

        with patch.object(segments, "_sync_directory", side_effect=fail_after_live_replace):
            with self.assertRaises(RuntimeError) as caught:
                segments.write_config(self.path, candidate, expected_version=1)

        self.assertIsInstance(caught.exception, segments.ConfigCommitUnknown)
        self.assertEqual(caught.exception.version, 2)
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(segments.load_config(self.path), (readback, 2, "file"))

    def test_retry_syncs_parent_entries_after_interrupted_first_write(self):
        root = self.path.parent
        path = root / "new-parent" / "config" / self.path.name
        config = {"version": 1, "stages": {}, "tiers": {}}
        sync_directory = segments._sync_directory

        def interrupt_parent_sync(directory):
            if directory == root:
                raise OSError("injected parent fsync failure")
            sync_directory(directory)

        with patch.object(segments, "_sync_directory", side_effect=interrupt_parent_sync):
            with self.assertRaisesRegex(OSError, "injected parent fsync failure"):
                segments.write_config(path, config, expected_version=0)
        self.assertTrue(path.parent.is_dir())
        self.assertEqual(segments.load_config(path)[1:], (0, "default"))

        synced_before_commit = []

        def record_sync(directory):
            if not path.exists():
                synced_before_commit.append(directory)
            sync_directory(directory)

        with patch.object(segments, "_sync_directory", side_effect=record_sync):
            segments.write_config(path, config, expected_version=0)

        self.assertIn(root, synced_before_commit)
        self.assertIn(root / "new-parent", synced_before_commit)
        self.assertEqual(segments.load_config(path), (config, 1, "file"))

    def test_write_rejects_invalid_candidate_or_live_config(self):
        valid = {"version": 1, "stages": {}, "tiers": {}}
        with self.assertRaises(ValueError):
            segments.write_config(self.path, dict(valid, stages={"1327": [1, 1, 3]}), expected_version=0)
        self.assertFalse(self.path.exists())

        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            segments.write_config(self.path, valid, expected_version=0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{}")

    def test_independent_writers_only_commit_one_candidate_at_the_same_version(self):
        context = multiprocessing.get_context("spawn")
        start = context.Barrier(2, timeout=15)
        results = context.Queue()
        self.addCleanup(results.close)
        workers = [
            context.Process(target=_write_concurrently, args=(self.path, points, start, results))
            for points in ([10, 20, 40], [15, 30, 60])
        ]
        for worker in workers:
            self._start_process(worker)
        for worker in workers:
            worker.join(20)
            self.assertEqual(worker.exitcode, 0)

        outcomes = [results.get(timeout=5) for _ in workers]
        self.assertCountEqual([status for status, _ in outcomes], ["committed", "conflict"])
        winner = next(config for status, config in outcomes if status == "committed")
        self.assertEqual(segments.load_config(self.path), (winner, 1, "file"))


if __name__ == "__main__":
    unittest.main()
