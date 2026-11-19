import json
import sqlite3
import unittest
from datetime import date
from unittest.mock import patch
from prices import confirmed
from review import packet, read_node


def core():
    return dict(game="FC27",start="2026-11-16",end="2026-11-16",scope="all",admin={
        "filters":{"game":"1327","site":"","pay_status":1,"date":["2026-11-16 00:00","2026-11-17 00:00"]},
        "scope":{"site":"all","country_code":"all"}, "rows":[{"date":"2026-11-16","amount":6,"orders":2}],
        "metrics":{k:{"value":v,"status":"available"} for k,v in {"revenueUsd":6,"orders":2,"newCustomers":1,"payingCustomers":2}.items()}
    },shipping=[])


class ReviewTests(unittest.TestCase):
    def test_totals_and_gaps(self):
        source = core()
        p = packet(source)
        self.assertEqual((p["kpi"]["newPct"],p["kpi"]["aov"]),(50,3))
        self.assertIsNone(p["kpi"]["profitCny"])
        source["admin"]["rows"] = []
        self.assertIsNone(packet(source)["daily"][0]["salesUsd"])
        source["admin"]["filters"]["site"] = "266"
        with self.assertRaises(ValueError):
            packet(source)

    def test_shipping_rate_and_real_zero(self):
        source = core()
        source["shipping"] = [dict(date="2026-11-16",scope=dict(sites="all-websites",orderGameId="1322",orderProductType="-1"),
                                   status="available",sourceContract="order-shipping-v1",salesCny=80,costCny=80,profitCny=0)]
        result = packet(source)
        self.assertEqual((result["kpi"]["marginPct"], result["daily"][0]["costPct"]), (0,100))

    def test_paging(self):
        pages = [{"status_code":200,"data":[1],"response_view":{"kind":"page","offset":0,"next_offset":1,"total":2}},
                 {"status_code":200,"data":[2],"response_view":{"kind":"page","offset":1,"next_offset":None,"total":2}}]
        with patch("review.rpc",side_effect=pages):
            self.assertEqual(read_node({"operation":"test","data_path":"/rows"}),[1,2])
        pages[1]["response_view"]["total"]=3
        with patch("review.rpc",side_effect=pages), self.assertRaises(ValueError):
            read_node({"operation":"test","data_path":"/rows"})

    def test_prices_use_readback_local_date_and_dedup(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE actual_price_windows(body); CREATE TABLE operations(id,body);")
        proof = {"PS":{"basis":"full_prices_and_tier_specs_readback","operation_id":"a"}}
        raw = json.dumps(dict(opened_at="2026-11-15T18:00:00+00:00",curve_confirmations=proof))
        db.executemany("INSERT INTO actual_price_windows VALUES (?)",[(raw,),(raw,)])
        curve = dict(identity={"site_id":"266"},tiers=[dict(purchase_k="100",native_price_usd="7.99")])
        op = dict(readback={"curve_results":{"PS":{"actual_site266_curve":curve}}})
        db.execute("INSERT INTO operations VALUES (?,?)",("a",json.dumps(op)))
        rows = confirmed(db,date(2026,11,16),date(2026,11,16))
        self.assertEqual((rows[0]["medianUsd"],rows[0]["observations"]),(7.99,1))
