import hashlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from orders import aggregate, amount_band, read_orders, review_category


def admin(order, usd, when):
    return dict(site_id=266, order_no=order, paytime=when, amount_usd_format=usd,
                paytype_display="applepay", country_code="GB",
                site={"full_title":"shop.test"}, status_format="已完成")


def es(order, buyer, new, when, product="货币(Gold)"):
    return {"订单号":hashlib.sha256(order.encode()).hexdigest(), "付款时间":when,
            "游戏":"FC 27", "buyer_id":buyer, "是否新客户":new, "产品类型":product, "折扣金额":"$2.00"}


def fact(rows=(), lines=(), complete=True):
    return dict(rows=rows, dataset={"rows":lines}, coverage={"complete":complete})


class OrdersTest(unittest.TestCase):
    def test_monthly_archive_keeps_all_site_days_and_explicit_main_site_subset(self):
        first, second, third = "2026-10-01", "2026-10-02", "2026-10-03"
        first_at, second_at = first+" 03:00:00", second+" 04:00:00"
        all_sites = fact([dict(admin("A", "15", first_at), site_id=510)], complete=False)
        all_sites["coverage"].update(publication_id="publication-pin", missing_days=[second,third], day_revisions={first:"full-day"})
        main = fact([admin("A", "99", first_at), dict(admin("B", "25", second_at), tracking={"customerType":"新客"})],
                    complete=False)
        main["coverage"].update(publication_id="publication-pin", missing_days=[third], day_revisions={first:"full-day",second:"main-day"})
        def fake_read(scope, *, publication_id):
            self.assertEqual(publication_id,"publication-pin")
            return {"all":all_sites,"266":main}[scope["site_id"]]
        # The legacy cache has an order number and site group, without site ID or category proof.
        cache = {second:{"orders":[dict(id="B",site_group="main",paid_at=second_at,
                                       amount_cents=2500,platform="PC",product="Coins"),
                                    dict(id="A",site_group="satellite",paid_at=first_at,
                                         amount_cents=1500,platform="PS",product="Coins")]}}
        with patch.dict(sys.modules, shared_es_facts=SimpleNamespace(read=fake_read,latest_publication=lambda:None)), \
             patch("orders.load_cache",return_value=cache), patch("orders.native_details",return_value={}):
            result = read_orders(first,third,game="FC27",publication_id="publication-pin")
        self.assertEqual(result["totals"],{"orders":2,"salesUsd":40.0})
        self.assertEqual(result["scope"]["site"],"all")
        self.assertEqual(result["scope"]["effectiveSite"],"mixed")
        site_coverage = result["scope"]["siteCoverageByGame"][0]
        self.assertEqual((site_coverage["allSiteDays"],site_coverage["mainSiteOnlyDays"],site_coverage["uncoveredDays"]),
                         ([first],[second],[third]))
        self.assertEqual(result["coverage"]["totals"]["status"],"partial")
        self.assertIn("266",result["coverage"]["platforms"]["reason"])
        self.assertEqual(result["platforms"][0],{"game":"FC27","platform":"PC","orders":1,"salesUsd":25.0})
        self.assertEqual(result["categories"],[{"game":"FC27","category":"unknown","orders":2,"salesUsd":40.0}])
        self.assertEqual(result["customerLifecycle"][0],{"game":"FC27","lifecycle":"new","orders":1,"salesUsd":25.0,"customers":None})
        self.assertEqual(result["coverage"]["spendBands"]["status"],"unavailable")
        self.assertIsNone(result["discount"]["discountPct"])

    def test_pinned_orders_reconcile_and_first_flag_counts_each_buyer_once(self):
        start, end = "2026-11-16", "2026-11-17"
        first, second = start+" 00:01:00", end+" 20:00:00"
        native = [admin("A", "$15.00", first), admin("B","$40.00",second),admin("C","$25.00",second)]
        lines = [es("A","ID-1","是",first), es("B","ID-1","否",second),es("C","ID-2","否",second)]
        proj = {(str(266),"A"):dict(platform="PS",purchase_k="100",regular_usd="$20.00"),
                (str(266),"B"):dict(platform="PS",purchase_k="500",regular_usd="$45.00")}
        result = aggregate(start,end,{"1327":fact(native,lines)},proj,{}, {})
        self.assertEqual(result["scope"]["games"],["FC27"])
        self.assertEqual(result["totals"],{"orders":3,"salesUsd":80.0})
        self.assertEqual([(x["lifecycle"],x["orders"],x["customers"]) for x in result["customerLifecycle"]],
                         [("new",1,1),("returning",2,1)])
        self.assertEqual([(x["band"],x["lifecycle"],x["customers"],x["salesUsd"]) for x in result["spendBands"]],
                         [("20–<40","returning",1,25.0),("40–<60","new",1,55.0)])
        self.assertEqual(sum(x["orders"] for x in result["orderAmountBands"]),3)
        self.assertEqual(result["discount"]["coveredOrders"],2)
        self.assertEqual(result["coverage"]["categories"]["status"],"partial")
        self.assertNotIn("ID-1",str(result))
        self.assertEqual(result["delivery"]["status"],"unavailable")

    def test_no_missing_or_cross_game_inputs_become_zeros(self):
        when = "2026-11-16 00:01:00"
        row = admin("A","",when)
        wrong_game = es("A","ID-1","是",when)
        result = aggregate("2026-11-16","2026-11-16",{"833":fact([row],[wrong_game])},{},{},{})
        self.assertEqual(result["totals"],{"orders":1,"salesUsd":None})
        self.assertEqual(result["customerLifecycle"][0]["lifecycle"],"unknown")
        self.assertEqual(result["scope"]["games"],["FC26"])
        self.assertEqual(result["fulfillment"]["status"],"unavailable")
        empty = aggregate("2026-11-16","2026-11-16",{"833":fact()},{},{},{})
        missing = aggregate("2026-11-16","2026-11-16",{"833":fact(complete=False)},{},{},{})
        self.assertEqual(empty["totals"],{"orders":0,"salesUsd":0.0})
        self.assertEqual(missing["totals"],{"orders":None,"salesUsd":None})
        self.assertEqual(amount_band(500),"≥500")

    def test_review_split_uses_proven_taxonomy_and_preserves_shared_top_priority(self):
        paths = {"9825":["2","9825"],"104":["5","104"],"3":["3"]}
        item = lambda cid:{"goods":{"cid":cid}}
        self.assertEqual(review_category("Other",[item("9825"),item("104")],paths),"Packs")
        self.assertEqual(review_category("Other",[item("104"),item("3")],paths),"Boosting")
        self.assertEqual(review_category("SBC",[item("9825")],paths),"SBC")
        self.assertEqual(review_category("Other",[item("3")],paths),"Other")
