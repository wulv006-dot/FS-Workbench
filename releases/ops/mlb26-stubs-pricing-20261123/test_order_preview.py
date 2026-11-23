from copy import deepcopy
import unittest

from source.order_preview import order_readback_preview


ORDER = {
    "ok": True, "gid": 922, "b2c_unit": "USD/1K", "rows": [
        {"id": "701", "gid": 922, "area": "PS 5", "b2c": "0.025"},
        {"id": "702", "gid": 922, "area": "XBOX", "b2c": "0.025"},
        {"id": "703", "gid": 922, "area": "Switch", "b2c": "0.025"},
    ],
}
TARGETS = {
    "PS": {"usd_per_k": "0.038", "source": "Eldorado"},
    "XBOX": None,
    "SWITCH": {"usd_per_k": "0.038", "source": "Eldorado"},
}


class OrderReadbackTests(unittest.TestCase):
    def test_only_preview_verified_mlb_stubs_rows(self):
        result = order_readback_preview(ORDER, TARGETS)

        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["source_timestamp_status"], "unknown")

        stale = deepcopy(ORDER)
        stale["fetched_at"] = "2023-01-01T00:00:00+00:00"
        self.assertEqual(order_readback_preview(stale, TARGETS)["source_timestamp_status"], "outside_hour")
        self.assertEqual(result["rows"]["PS"]["before_usd_per_k"], "0.025")
        self.assertEqual(result["rows"]["PS"]["supplier_settlement_usd_per_k"], "0.02850")
        self.assertEqual(result["rows"]["SWITCH"]["row_id"], "703")
        self.assertIsNone(result["rows"]["XBOX"]["target_usd_per_k"])

        wrong = deepcopy(ORDER)
        wrong["rows"][2]["gid"] = 927
        with self.assertRaisesRegex(ValueError, "mlb_order_scope_mismatch"):
            order_readback_preview(wrong, TARGETS)
