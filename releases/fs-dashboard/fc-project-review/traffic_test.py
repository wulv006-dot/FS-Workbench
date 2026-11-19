from datetime import date
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from traffic import archived_day, channel_packet, channel_windows, search_packet


class TrafficTest(unittest.TestCase):
    def test_ads_uses_first_comparable_archive(self):
        day = "2026-11-09"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / (day + "_" + day)
            target.mkdir()
            period = {"start": day, "end": day}
            for label, captured in (
                ("later_same_day", "2026-11-10T22:00:00+08:00"),
                ("first", "2026-11-09T16:00:45+00:00"),
                ("before_close", "2026-11-09T23:55:00+08:00"),
                ("late_backfill", "2026-11-15T00:55:25+08:00"),
            ):
                with gzip.open(target / (label + ".json.gz"), "wt", encoding="utf-8") as stream:
                    json.dump({"sourceAt": captured, "value": dict(period, period=period)}, stream)
            self.assertEqual(archived_day(root, day)[1], "first.json.gz")

    def test_gsc_keeps_same_weekday_when_latest_date_missing(self):
        days = {"current": ["2026-11-16", "2026-11-17", "2026-11-18"],
                "previous": ["2026-11-09", "2026-11-10", "2026-11-11"]}
        metric = {"clicks": 5, "impressions": 10, "ctr": 0.5, "position": 3}
        calls = []

        class Reader:
            def request(self, source, url, body):
                calls.append(body)
                if body["dimensions"] == ["date"]:
                    return {"rows": [dict(metric, keys=[day]) for day in days["previous"] + days["current"][:2]]}
                return {"rows": [metric]} if body["dimensions"] == [] else {"rows": []}

        result = search_packet(Reader(), days)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["previous"]["compared_days"], days["previous"][:2])
        self.assertEqual(result["coverage"]["current"]["compared_days"], days["current"][:2])
        self.assertTrue(all(call["dataState"] == "final" for call in calls))
        self.assertEqual({call["endDate"] for call in calls[1:]}, {"2026-11-10", "2026-11-17"})

    def test_attribution_retention_boundary_keeps_the_in_range_days(self):
        period = {"start": "2025-11-11", "end": "2025-11-21"}
        self.assertEqual(list(channel_windows(period, date(2025, 11, 19))), [
            {"start": "2025-11-11", "end": "2025-11-18"},
            {"start": "2025-11-19", "end": "2025-11-21"},
        ])

    def test_unobserved_channel_stays_unknown(self):
        periods = {"current": {"start": "2026-11-16", "end": "2026-11-18"},
                   "previous": {"start": "2026-11-09", "end": "2026-11-11"}}

        def response(window, channel, unlinked):
            return {"status_code": 200, "response_view": {"value_complete": True},
                    "data_context": {"": {"effective_scope": dict(periods[window], gid="1327", site_id="all", status="all",
                                                               channel="all"), "coverage": {"unlinked_attribution_rows": unlinked}}},
                    "data": [{"channel": channel, "label": channel, "orders": 1, "admin_paid_usd": "1.10",
                              "order_share": 1, "conflict_orders": 0, "missing_admin_usd_orders": 0}]}

        output = channel_packet(periods, "all", {"current": response("current", "SEO", 0),
                                                  "previous": response("previous", "unknown", 1)})
        seo = next(row for row in output["channels"] if row["key"] == "SEO")
        self.assertEqual(output["status"], "partial")
        self.assertEqual(output["previous"]["sales_usd"], 1.10)
        self.assertIsNone(seo["previous"])


if __name__ == "__main__":
    unittest.main()
