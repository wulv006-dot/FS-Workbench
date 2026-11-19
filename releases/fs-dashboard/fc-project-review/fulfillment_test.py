from datetime import date, datetime
import unittest

from fulfillment import CN, evidence, queue_summary, summarize

DAY = date(2026, 11, 16)


def detail():
    def shipment(i, quantity, gift, minute):
        stamp = datetime(2026, 11, 16, 8, minute, tzinfo=CN)
        return {"id": i, "pid": "99", "qty": quantity, "gift": gift, "status": int(i) % 2,
                "timestamp": int(stamp.timestamp())}

    return {
        "eventCount": 4,
        "events": [
            {"id": "4", "time": "26-11-16 08:21:00", "status": "3"},
            {"id": "3", "time": "26-11-16 08:15:00", "status": "2"},
            {"id": "2", "time": "26-11-16 08:10:00", "status": "6"},
            {"id": "1", "time": "26-11-16 08:01:00", "status": "1"},
        ],
        "goods": [{"gid": "1322", "cid": "1", "unit": "K", "pid": "99", "base": "1000", "qty": "1030", "used": "1030"}],
        "deliveryCount": 2,
        "deliveries": [shipment("1", "400", "0", 7), shipment("2", "600", "30", 20)],
    }


class FulfillmentTest(unittest.TestCase):
    def test_issue_is_historical_and_last_matching_shipment_times_completion(self):
        result, sample = evidence(detail(), {"platform": "PC", "had_issue": True}, DAY, DAY)
        self.assertEqual(result, "timed")
        self.assertEqual(sample, {"platform": "PC", "band": "atLeast1000", "status": "problem", "minutes": 19, "opened_date": "2026-11-16", "problem_minutes": 10})
        self.assertEqual(summarize([sample])[0]["p90Minutes"], 19)
        daily = summarize([sample], by_day=True)[0]
        self.assertEqual((daily["date"], daily["meanMinutes"], daily["problemToCompleteMinutes"]["meanMinutes"]), ("2026-11-16",19,10))

    def test_no_quantity_match_does_not_record_duration(self):
        raw = detail()
        raw["deliveries"][1]["qty"] = "6"
        result, sample = evidence(raw, {"platform": "PS", "had_issue": True}, DAY, DAY)
        self.assertEqual(result, "delivery_quantity_not_reconciled")
        self.assertIsNone(sample["minutes"])

    def test_problem_flag_conflict_and_outside_queue(self):
        row = {"platform": "XBOX", "had_issue": False}
        result, sample = evidence(detail(), row, DAY, DAY)
        self.assertEqual(result, "issue_flag_log_conflict")
        self.assertEqual(sample["status"], "unknown")
        result, sample = evidence(detail(), row, date(2026, 11, 17), date(2026, 11, 18))
        self.assertEqual(result, "queue_entry_outside_requested_period")
        self.assertIsNone(sample)


    def test_full_queue_keeps_open_and_canceled_in_denominator(self):
        rows = [{"id": "1", "merchant": "www.mmoexp.com SN1000", "platform": "PC", "status": "已完成", "had_issue": False},
                {"id": "2", "merchant": "www.mmoexp.com SN2000", "platform": "PC", "status": "交易中", "had_issue": False},
                {"id": "3", "merchant": "www.mmoexp.com SN3000", "platform": "PC", "status": "已取消", "had_issue": True}]
        linked = {"SN1000": {"platform": "PC", "purchase_k": "1000"},
                  "SN2000": {"platform": "PC", "purchase_k": "1000"}}
        result = queue_summary(rows, linked, True)
        self.assertEqual(result["totals"]["completionRate"], 1 / 3)
        self.assertEqual(result["totals"]["open"], 1)
        self.assertEqual(result["totals"]["canceled"], 1)
        self.assertEqual(result["coverage"]["quantityLinked"], 2)
        self.assertIsNone(queue_summary(rows, linked, False)["totals"]["completionRate"])


if __name__ == "__main__":
    unittest.main()
