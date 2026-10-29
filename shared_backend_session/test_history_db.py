# -*- coding: utf-8 -*-
"""history_db 离线回归：幂等、回填、区间读、水位（不联网）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history_db as HDB  # noqa: E402


def _order(i, paytime="2026-10-28 10:00:00"):
    return {"id": i, "order_no": "A%d" % i, "gid": 891, "site_id": 266, "uid": 7,
            "paytime": paytime, "pay_status": 1, "status": 2, "amount": "12.30",
            "discount_code": "X"}


def _delivery(i, trade_at="2026-10-28 11:00:00"):
    return {"delivery_id": str(i), "order_no": "A%d" % i, "genre": "订单发货",
            "trade_at": trade_at, "cost_total": "9.90", "sale_total": "12.30"}


class HistoryDBTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = HDB.open_db(str(Path(self.tmp.name) / "t.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_upsert_is_idempotent(self):
        self.assertEqual(HDB.upsert_orders(self.conn, [_order(1), _order(2)]), 2)
        HDB.upsert_orders(self.conn, [_order(1), _order(2)])
        self.assertEqual(HDB.count(self.conn, "orders"), 2)

    def test_import_json_from_legacy_dump(self):
        p = Path(self.tmp.name) / "orders.json"
        p.write_text(json.dumps([_order(3), _order(4)], ensure_ascii=False), encoding="utf-8")
        self.assertEqual(HDB.import_json(self.conn, p, "orders"), 2)
        self.assertEqual(HDB.count(self.conn, "orders"), 2)

    def test_load_range_and_dedup(self):
        HDB.upsert_orders(self.conn, [_order(1, "2026-10-27 09:00:00"),
                                      _order(2, "2026-10-28 09:00:00")])
        got = HDB.load_orders(self.conn, "2026-10-28", "2026-10-28")
        self.assertEqual([r["id"] for r in got], [2])

    def test_watermark_takes_max(self):
        rows = [_order(5, "2026-10-28 08:00:00"), _order(9, "2026-10-28 12:00:00")]
        HDB.upsert_orders(self.conn, rows)
        HDB.bump_watermark(self.conn, "orders", rows)
        st = HDB.get_state(self.conn, "orders")
        self.assertEqual(st["high_id"], 9)
        self.assertEqual(st["high_time"], "2026-10-28 12:00:00")

    def test_delivery_primary_key_idempotent(self):
        HDB.upsert_deliveries(self.conn, [_delivery(1), _delivery(1)], gid=826)
        self.assertEqual(HDB.count(self.conn, "deliveries"), 1)

    def test_existing_ids(self):
        HDB.upsert_deliveries(self.conn, [_delivery(1), _delivery(2)])
        self.assertEqual(HDB.existing_delivery_ids(self.conn, ["1", "2", "3"]), {"1", "2"})

    def test_time_normalisation(self):
        # 2 位年
        self.assertEqual(HDB._dt("26-09-29 22:32:39"), "2026-09-29 22:32:39")
        # 改过的发货时间：后面带「改 + 新时间」，只能取开头那个
        self.assertEqual(HDB._dt("26-10-29 14:08:41                改 26-10-29 14:09:49"),
                         "2026-10-29 14:08:41")
        # 4 位年原样
        self.assertEqual(HDB._dt("2026-10-29 16:26:45"), "2026-10-29 16:26:45")
        # 解析不了 → None（不能把脏字符串塞进水位，否则排序全乱）
        self.assertIsNone(HDB._dt("暂无"))


if __name__ == "__main__":
    unittest.main()
