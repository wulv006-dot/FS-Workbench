from datetime import date, timedelta
from concurrent.futures import Future
from importlib import import_module
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
api=import_module(HERE.name+".api")
from test_review import core
same_order=import_module(HERE.name+".same_order")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.params={"mode":["fc-project-review"],"profile":["FC27"],"start":["2026-11-16"],"end":["2026-11-16"]}
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        jobs=patch.object(api,"JOBS",{})
        jobs.start()
        self.addCleanup(jobs.stop)

    def test_intraday_archive_expires_at_midnight_even_when_recent(self):
        p=api.packet(core())
        with patch.object(api,"datetime",wraps=api.datetime) as clock:
            clock.now.return_value=api.datetime(2026,11,16,23,59,tzinfo=api.TZ)
            first=api.publish(p,self.root)
            self.assertEqual(self.get()[0],200)
            clock.now.return_value=api.datetime(2026,11,17,0,0,tzinfo=api.TZ)
            completed=Future()
            completed.set_result(first)
            api.JOBS[("FC27","2026-11-16","2026-11-16","reviewer")]=(completed,api.time.monotonic())
            with patch.object(api.POOL,"submit",return_value=Future()) as submit:
                self.assertEqual(self.get()[0],202)
                submit.assert_called_once()
            self.assertEqual(len(list((self.root/"FC27"/"versions").glob("*.json"))),1)

    def test_archive_compatibility_and_expiry(self):
        cases=[
            ({"archivedAt":"2026-11-16T23:59:00+08:00"}, {}, 202),
            ({"archivedAt":"2026-11-17T00:00:00+08:00"}, {}, 200),
            ({"archivedAt":"2026-11-16T16:00:00Z"}, {}, 200),
            ({"archivedAt":"2026-11-17T00:01:00+08:00"}, {"capturedAt":"2026-11-16T23:59:00+08:00"}, 202),
            ({"archivedAt":None}, {}, 202),
            ({"archivedAt":"invalid"}, {}, 202),
            ({}, {"captureStartedAt":"2026-11-16T23:59:00+08:00"}, 202),
            ({}, {"captureStartedAt":"2026-11-17T00:00:00+08:00"}, 200),
        ]
        with patch.object(api,"datetime",wraps=api.datetime) as clock:
            clock.now.return_value=api.datetime(2026,11,19,tzinfo=api.TZ)
            for metadata, fields, expected in cases:
                with self.subTest(metadata=metadata,fields=fields):
                    doc=api.publish({**api.packet(core()),**fields},self.root)
                    doc.update(metadata)
                    target=self.root/"FC27"/"2026-11-16_2026-11-16.json"
                    target.write_text(json.dumps(doc),encoding="utf-8")
                    os.utime(target,(0,0))
                    api.JOBS.clear()
                    with patch.object(api.POOL,"submit",return_value=Future()) as submit:
                        self.assertEqual(self.get()[0],expected)
                        self.assertEqual(submit.call_count,int(expected==202))
                        self.assertEqual(self.get(False)[0],403)

    def test_today_ttl_and_explicit_refresh(self):
        with patch.object(api,"datetime",wraps=api.datetime) as clock:
            clock.now.return_value=api.datetime(2026,11,16,12,tzinfo=api.TZ)
            api.publish(api.packet(core()),self.root)
            target=self.root/"FC27"/"2026-11-16_2026-11-16.json"
            with patch.object(api.POOL,"submit",return_value=Future()) as submit:
                self.assertEqual(self.get()[0],200)
                self.assertEqual(self.get(refresh=["true"])[0],202)
                api.JOBS.clear()
                os.utime(target,(0,0))
                self.assertEqual(self.get()[0],202)
                self.assertEqual(submit.call_count,2)

    def test_capture_started_before_midnight_remains_provisional(self):
        source=core()
        admin=source["admin"]
        admin.update(status="available",normalisedScope="all-websites",effective_scope=admin.pop("scope"))
        before=api.datetime(2026,11,16,23,59,tzinfo=api.TZ)
        after=api.datetime(2026,11,17,0,1,tzinfo=api.TZ)
        with patch.object(api,"datetime",wraps=api.datetime) as clock:
            clock.now.return_value=before
            def read(_get,game,start,end,mode,actor):
                clock.now.return_value=after
                return {"profile":{"supplement":admin}} if mode=="summary" else {"history":{"daily":[]}}
            with patch.object(api,"read_range",read),patch.object(api,"read_program",return_value={"discount":{}}) as program:
                p=api.capture("FC27",source["start"],source["end"],"operator",None,None,lambda _:True)
            self.assertEqual(p["captureStartedAt"],before.isoformat())
            self.assertEqual([call.args[1] for call in program.call_args_list],["orders.py"])
            first=api.publish(p,self.root)
            with patch.object(api.POOL,"submit",return_value=Future()):
                self.assertEqual(self.get()[0],202)
            api.JOBS.clear()
            def program(_python,script,*args):
                return {"orders.py":{"discount":{},"products":[{}]},"prices.py":{"tiers":[]},
                        "traffic.py":{"periods":{}},"fulfillment_completion_bridge.py":{
                            "start":source["start"],"end":source["end"]}}[script]
            with patch.object(api,"read_range",read),patch.object(api,"read_program",side_effect=program) as programs:
                closed=api.capture("FC27",source["start"],source["end"],"operator",None,None,lambda _:True)
            self.assertEqual([call.args[1] for call in programs.call_args_list],
                             ["orders.py","prices.py","traffic.py","fulfillment_completion_bridge.py"])
            second=api.publish(closed,self.root)
            self.assertEqual(self.get()[1]["revision"],second["revision"])
            retained=self.root/"FC27"/"versions"/(source["start"]+"_"+source["end"]+"_"+first["revision"]+".json")
            self.assertEqual(json.loads(retained.read_text(encoding="utf-8")),first)

    def get(self, permitted=True, **updates):
        return api.get({**self.params,**updates},"reviewer",None,None,lambda _:permitted,self.root)

    def test_completed_report_exposes_authorized_same_order_aggregate(self):
        source=core();admin=source["admin"]
        admin.update(status="available",normalisedScope="all-websites",effective_scope=admin.pop("scope"))
        def read(_get,game,start,end,mode,actor):
            return {"profile":{"supplement":admin}} if mode=="summary" else {"history":{"daily":[]}}
        def program(_python,script,*args):
            return {"orders.py":{"discount":{},"products":[{}]},"prices.py":{"tiers":[]},
                    "traffic.py":{"periods":{}},"fulfillment_completion_bridge.py":{
                        "start":source["start"],"end":source["end"]}}[script]
        fact=dict(status="partial",totals=dict(orders=2,salesUsd=12),coverage=dict(adminComplete=True))
        with patch.object(api,"datetime",wraps=api.datetime) as clock,patch.object(api,"read_range",read), \
             patch.object(api,"read_program",side_effect=program),patch.object(api,"same_order_review",return_value=fact) as same:
            clock.now.return_value=api.datetime(2026,11,19,tzinfo=api.TZ)
            result=api.capture("FC27",source["start"],source["end"],"operator",None,None,lambda _:True)
            self.assertEqual(result["sameOrder"],fact)
            same.assert_called_once_with("FC27",source["start"],source["end"])
            with self.assertRaises(PermissionError):
                api.capture("FC27",source["start"],source["end"],"operator",None,None,lambda _:False)
            self.assertEqual(same.call_count,1)

    def test_access_and_explicit_scope(self):
        self.assertEqual(self.get(False)[0],403)
        self.assertEqual(self.get(profile=["../all"])[0],422)
        self.assertEqual(self.get(site=["266"])[0],422)
        self.assertEqual(self.get(start=["2026-11-17"])[0],422)

    def test_same_order_view_uses_read_path_without_starting_review(self):
        with patch.object(api,"datetime",wraps=api.datetime) as clock, \
                patch.object(api.POOL,"submit") as submit, \
                patch.object(api,"same_order_review",return_value={"status":"partial"}) as fast:
            clock.now.return_value=api.datetime(2026,11,19,tzinfo=api.TZ)
            self.assertEqual(self.get(False,view=["same-order"])[0],403)
            self.assertEqual(self.get(view=["same-order"],refresh=["true"])[0],422)
            self.assertEqual(self.get(view=["same-order"],end=["2026-11-19"])[0],422)
            self.assertEqual(self.get(view=["same-order"]), (200,{"status":"partial"}))
            fast.assert_called_once_with("FC27","2026-11-16","2026-11-16")
            submit.assert_not_called()

    def test_same_order_uses_same_website_and_deduplicated_complete_delivery_window(self):
        source = HERE.parent / "dashboard-refresh-20261025/source"
        sys.path.insert(0, str(source))
        self.addCleanup(sys.path.remove, str(source))
        day, next_day = "2026-11-16", "2026-11-17"
        rows = []
        for order_no, site, usd, cny, status in (
                ("A", 266, "100", "700", "已完成"),
                ("A", 5, "50", "350", "已完成"),
                ("B", 266, "10", "70", "已完成"),
                ("C", 266, "22", "154", "待发货"),
                ("D", 266, "5", "35", "已退款·全部退款")):
            rows.append(dict(id=len(rows)+1, order_no=order_no, site_id=site, gid=1327, paytime=day+" 01:00:00",
                             pay_status=2 if order_no=="D" else 1, status_format=status,
                             amount_usd_format=usd, amount_rmb_format=cny,
                             site=dict(full_title=same_order.MAIN if site==266 else "www.other.example")))
        scope = dict(start=day,end=day,site_id="all",gid="1327")
        rows[0]["fc27_coins"] = {"platform":"PS","single_line_unit_purchase":True}
        rows[0].update(amount_usd_format="$100.00", amount_rmb_format="￥700.00", before_discount="130.00", currency_code="EUR")
        rows[1]["fc27_coins"] = {"platform":"XBOX","single_line_unit_purchase":True}
        rows[2]["fc27_coins"] = {"platform":"PC","single_line_unit_purchase":False}
        def read(query, *, native_only):
            self.assertEqual(query, scope)
            self.assertTrue(native_only)
            return dict(coverage=dict(admin_complete=True, missing_days=[], captured_at=next_day+"T09:00:00+08:00",
                                      publication_id="publication",source_revision="orders-v1"),
                        rows=rows)
        def delivery(identity, sn, trade, amount):
            return dict(delivery_id=str(identity),sn=sn,trade_at=trade,cost_total=amount,
                        source=same_order.MAIN,genre=1)
        def archive(path, period, generated, deliveries):
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(dict(contract="channel-order-deliveries-v1", complete=True,
                period=period, generatedAt=generated, rows=deliveries)), encoding="utf-8")
        archive(self.root/"delivery-days"/(day+".json"),dict(start=day,end=day),
                next_day+"T01:00:00+08:00",[
                    delivery(1,"A",day+" 03:00:00","420"),delivery(2,"B",day+" 03:00:00","0"),
                    delivery(3,"C",day+" 04:00:00","3"),delivery(4,"A",day+" 05:00:00","90")])
        rolling = self.root/"order-deliveries.json"
        archive(rolling,dict(start=day,end=next_day,since=day+" 04:00",until=next_day+" 08:00"),
                next_day+"T08:02:00+08:00",[delivery(1,"A",day+" 03:00:00","1"),
                    delivery(3,"C",day+" 04:00:00","3"),delivery(5,"A",next_day+" 02:00:00","150"),
                    delivery(6,"A",next_day+" 08:00:00","100")])
        def status_reader(query):
            self.assertEqual(query,scope)
            return ({(day,"A"):dict(id="1",paidAt=day+" 01:00:00",amountUsd="100",revision=1),
                     (day,"B"):dict(id="3",paidAt=day+" 01:00:00",amountUsd="10",revision=1)},
                    {day:dict(jobId="j",revision=1,observedAt=next_day+"T07:59:59+08:00")})
        def lookup():
            return same_order.same_order_review("FC27",day,day,read=read,status_reader=status_reader,cost_root=self.root,
                overrides=lambda doc:dict(doc,costOverrides={},testOrders={}))
        result = lookup()
        values = result["totals"]
        self.assertEqual(result["status"],"partial")
        self.assertEqual((values["salesUsd"],values["orders"]),(182,4))
        self.assertEqual((values["completedOrders"],values["coveredOrders"],values["missingCostOrders"],values["pendingOrders"]),(3,2,1,1))
        self.assertEqual((values["actualCostCny"],values["coveredSalesCny"],values["grossCny"]),(570,770,200))
        self.assertEqual((values["missingCostObservedSalesUsd"],values["missingCostObservedSalesCny"]),(50,350))
        self.assertAlmostEqual(values["grossMarginPct"],200/770*100,places=4)
        self.assertEqual(result["daily"][0],dict(date=day,**values))
        self.assertEqual([(r["siteId"],r["platform"],r["coveredOrders"]) for r in result["breakdown"]],
                         [("266","PS",1),("266","unknown",1),("5","unknown",0)])
        self.assertEqual(sum(r["orders"] for r in result["breakdown"]), values["orders"])
        self.assertNotIn('"order_no"',json.dumps(result))
        from channel_effects import profit_view
        # Compare the new aggregate to the existing completed-order accounting on
        # independently specified native sale/cost inputs, with one covered zero-cost order.
        legacy = []
        for sn, dollars, yuan, cost, state in (
                ("A",100,700,570,"已完成"),("B",10,70,0,"已完成"),
                ("C",22,154,None,"待发货"),("uncovered",50,350,None,"已完成")):
            legacy.append(dict(orderNo=sn, gid="1327", game="FC27", day=day, salesUsd=dollars,
                adminSaleCny=yuan, costCny=cost, status=state, payStatus="1", refunded=False,
                deliveryRows=2 if sn=="A" else 1 if sn=="B" else 0, coupons=[],
                codeKey="", conflict=False, attribution="无推广归属"))
        previous = profit_view(dict(period=dict(start=day,end=day), generatedAt=next_day+"T09:00:00+08:00",
            sources=dict(orders=dict(status="complete")), orders=legacy),{"gid":"1327"})["denominator"]
        self.assertEqual((values["grossCny"],values["actualCostCny"],values["coveredSalesCny"]),
                         (previous["profitCny"],previous["costCny"],previous["saleCny"]))
        self.assertAlmostEqual(values["grossMarginPct"],previous["margin"]*100,places=4)
        from order_delivery_index import sync
        index_revision=sync(self.root)
        indexed=lookup()
        self.assertEqual(indexed["totals"],result["totals"])
        self.assertEqual(indexed["daily"],result["daily"])
        self.assertEqual(indexed["breakdown"],result["breakdown"])
        self.assertTrue(all(item["indexRevision"]==index_revision for item in indexed["revisions"]["order"]))
        with patch.dict(sys.modules, {"order_delivery_index":SimpleNamespace(sync=sync)}):
            self.assertEqual(lookup(), result)
        rolling.unlink()
        missing = lookup()
        self.assertIsNone(missing["totals"]["actualCostCny"])
        self.assertEqual(missing["totals"]["missingCostOrders"],3)
        self.assertNotEqual(result["revision"],missing["revision"])

    def test_same_order_excludes_test_and_failed_validation_from_every_business_denominator(self):
        source = HERE.parent / "dashboard-refresh-20261025/source"
        sys.path.insert(0,str(source)); self.addCleanup(sys.path.remove,str(source))
        day = "2026-11-16"
        specifications = [("VALID",266,"100","700","已完成","PS"),
            ("TEST",266,"10","70","已完成","XBOX"),
            ("TEST",5,"10","70","已完成","PC"),
            ("FRAUD",266,"20","140","验证 · 未通过","PS"),
            ("ZERO",266,"5","35","已完成","PS"),
            ("PENDING",266,"8","56","发货中","PC")]
        rows=[dict(id=i,order_no=sn,site_id=site,gid=1327,paytime=day+" 01:00:00",pay_status="1",
                   status_format=status,amount_usd_format=usd,amount_rmb_format=cny,
                   site=dict(full_title=same_order.MAIN if site==266 else "www.other.example"),
                   fc27_coins=dict(platform=platform,single_line_unit_purchase=True))
              for i,(sn,site,usd,cny,status,platform) in enumerate(specifications,1)]
        read=lambda scope,**kwargs:dict(coverage=dict(admin_complete=True,missing_days=[],source_revision="v1"),rows=rows)
        overrides=lambda data:dict(data,costOverrides={"ZERO":dict(gid="1327",salesUsd="5",saleCny="35",productTitle="confirmed")},
                                  testOrders={"TEST":dict(gid="1327",salesUsd="10")})
        result=same_order.same_order_review("FC27",day,day,read=read,status_reader=lambda scope:({},{}),
                                           cost_root=self.root,overrides=overrides)
        totals=result["totals"]
        self.assertEqual(result["revisions"]["accountingRule"],same_order.ACCOUNTING_RULE)
        with patch.object(same_order,"ACCOUNTING_RULE","prior-accounting-rule"):
            prior=same_order.same_order_review("FC27",day,day,read=read,status_reader=lambda scope:({},{}),
                                              cost_root=self.root,overrides=overrides)
        self.assertNotEqual(result["revision"],prior["revision"])
        self.assertEqual((totals["orders"],totals["salesUsd"],totals["excludedOrders"]),(4,123,2))
        self.assertEqual((totals["completedOrders"],totals["coveredOrders"],totals["missingCostOrders"],totals["pendingOrders"]),(3,1,2,1))
        self.assertEqual((totals["actualCostCny"],totals["coveredSalesCny"],totals["grossCny"]),(0,35,35))
        from channel_effects import accounting_row, metrics
        existing = []
        rules = overrides(dict(sources={}))
        for raw in rows:
            main = raw["site_id"] == 266
            existing.append(accounting_row(dict(orderNo=raw["order_no"],gid="1327",game="FC27",status=raw["status_format"],
                refunded=False,salesUsd=float(raw["amount_usd_format"]),adminSaleCny=float(raw["amount_rmb_format"]),
                costCny=None,deliveryRows=0,codeKey="",attribution="",coupons=[],conflict=False),rules["costOverrides"] if main else {},rules["testOrders"] if main else {}))
        baseline = metrics(existing)
        self.assertEqual((totals["orders"],totals["salesUsd"],totals["completedOrders"],totals["coveredOrders"]),
                         (baseline["orders"],baseline["salesUsd"],baseline["completedOrders"],baseline["coveredOrders"]))
        self.assertEqual(result["daily"][0],dict(date=day,**totals))
        self.assertEqual(sum(r["orders"] for r in result["breakdown"]),4)
        self.assertEqual(sum(r["salesUsd"] for r in result["breakdown"]),123)
        satellite=next(r for r in result["breakdown"] if r["siteId"]=="5")
        self.assertEqual((satellite["orders"],satellite["salesUsd"]),(1,10))
        self.assertNotIn('"order_no"',json.dumps(result))

    def test_same_order_index_uses_only_verified_windows_and_main_site(self):
        source = HERE.parent / "dashboard-refresh-20261025/source"
        sys.path.insert(0, str(source))
        self.addCleanup(sys.path.remove, str(source))
        import order_delivery_index as index

        now=api.datetime(2026,11,19,tzinfo=api.TZ)
        rows=[dict(delivery_id="1",source=same_order.MAIN,sn="A",genre=1,
                   trade_at="2026-11-16 03:00:00",cost_total="12")]
        windows=[dict(source=same_order.MAIN,since="2026-11-16 00:00:00",until="2026-11-16 23:59:59",
                      capturedAt="2026-11-17T01:00:00+08:00",revision="capture")]
        calls=[]
        def read(keys,**kwargs):
            calls.append((keys,kwargs))
            return dict(status="available",rows=rows,revision="index-v1",generatedAt=windows[0]["capturedAt"],windows=windows)
        with patch.object(index, "read_orders", read):
            costs, intervals, revisions, invalid = same_order.delivery_evidence(["2026-11-16"],now,self.root,
                                                                                  {(same_order.MAIN,"A")})
        self.assertEqual(costs["A"],[("2026-11-16 03:00:00","12")])
        self.assertEqual(intervals,[("2026-11-16 00:00:00","2026-11-16 23:59:59")])
        self.assertEqual(revisions[0]["indexRevision"],"index-v1")
        self.assertEqual(invalid,[])
        self.assertEqual(calls[0][0],{(same_order.MAIN,"A")})
        self.assertEqual(calls[0][1]["root"],self.root)
        with patch.object(index, "read_orders", return_value={"status":"stale"}):
            costs, intervals, revisions, invalid = same_order.delivery_evidence(["2026-11-16"],now,self.root,
                                                                                  {(same_order.MAIN,"A")})
        self.assertEqual((costs,intervals,revisions,invalid),({},[],[],[]))

    def test_retained_revision_and_readback(self):
        p=api.packet(core())
        first=api.publish(p,self.root)
        self.assertEqual(self.get()[1]["revision"],first["revision"])
        second=api.publish(dict(p,coverage=["source corrected"]),self.root)
        self.assertNotEqual(first["revision"],second["revision"])
        self.assertEqual(len(list((self.root/"FC27"/"versions").glob("*.json"))),2)

    def test_source_shape_and_optional_gaps(self):
        source=core()
        admin=source["admin"]
        admin.update(status="available",normalisedScope="all-websites",effective_scope=admin.pop("scope"))
        def read(_get,game,start,end,mode,actor):
            return {"profile":{"supplement":admin}} if mode=="summary" else {"history":{"daily":[]}}
        with patch.object(api,"read_range",read),patch.object(api,"read_program",side_effect=RuntimeError("offline")),patch.object(api.subprocess,"run",side_effect=OSError):
            p=api.capture("FC27",source["start"],source["end"],"operator",None,None,lambda _:True)
        self.assertEqual(p["kpi"]["orders"],2)
        self.assertTrue(p["coverage"])

    def test_monthly_channel_reads_are_ordered_disjoint_and_recompute_shares(self):
        periods={"current":{"start":"2026-10-01","end":"2026-10-31"},
                 "previous":{"start":"2026-08-31","end":"2026-09-30"}}
        expected=[("2026-10-01","2026-10-28"),("2026-10-29","2026-10-31"),
                  ("2026-08-31","2026-09-27"),("2026-09-28","2026-09-30")]
        calls=[]

        def get(params,actor):
            self.assertEqual(actor,"reviewer")
            q={key:value[0] for key,value in params.items()}
            self.assertEqual(q.pop("mode"),"order-facts")
            calls.append((q["start"],q["end"]))
            tail=q["start"] in ("2026-10-29","2026-09-28")
            rows=[{"channel":"PPC","label":"PPC","orders":10 if tail else 5,
                   "admin_paid_usd":"20.50" if tail else "16.25","order_share":1 if tail else .2,
                   "conflict_orders":2 if tail else 1,"missing_admin_usd_orders":0}]
            if not tail:
                rows.append({**rows[0],"channel":"Direct","label":"Direct","orders":20,"admin_paid_usd":"99.59","order_share":.8})
            return 200, {"channels":rows,"effective_scope":dict(q,channel="all"),"status":"available",
                         "admin_complete":True,"coverage":{"missing_days":[]},
                         "snapshot_id":q["start"],"revisions":{"attribution":{"source_revision":q["end"]}}}

        with patch.object(api,"datetime",wraps=api.datetime) as clock:
            clock.now.return_value=api.datetime(2026,11,19,tzinfo=api.TZ)
            result=api.read_order_attribution(SimpleNamespace(get=get),"reviewer",periods)
        self.assertEqual(calls,expected)
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["current"],{"orders":35,"sales_usd":136.34,"missing_sales_orders":0})
        channel=next(r for r in result["channels"] if r["key"]=="PPC")
        self.assertEqual((channel["current"]["orders"],channel["current"]["sales_usd"],channel["current"]["conflict_orders"]),
                         (15,36.75,3))
        self.assertAlmostEqual(channel["current"]["order_share"],15/35)
        self.assertAlmostEqual(channel["current"]["sales_share"],36.75/136.34)
        self.assertEqual([r["attribution_revision"]["source_revision"] for r in result["coverage"]["current"]["segments"]],
                         ["2026-10-28","2026-10-31"])

    def test_partial_month_preserves_successful_segments_and_other_period(self):
        periods={"current":{"start":"2026-10-01","end":"2026-10-31"},
                 "previous":{"start":"2026-08-31","end":"2026-09-30"}}
        replies=[]

        def get(params,actor):
            q={key:value[0] for key,value in params.items() if key!="mode"}
            replies.append(q["start"])
            if q["start"]=="2026-10-29":
                raise OSError("one segment offline")
            if q["start"]=="2026-08-31":
                return 503, {"status":"source_failed"}
            return 200, {"channels":[{"channel":"PPC","label":"PPC","orders":4,"admin_paid_usd":"20.80",
                                     "order_share":1,"conflict_orders":0,"missing_admin_usd_orders":0}],
                         "effective_scope":dict(q,channel="all"),"status":"partial" if q["start"]=="2026-09-28" else "available",
                         "admin_complete":q["start"]!="2026-09-28",
                         "coverage":{"missing_days":["2026-09-29"] if q["start"]=="2026-09-28" else []}}

        with patch.object(api,"datetime",wraps=api.datetime) as clock:
            clock.now.return_value=api.datetime(2026,11,19,tzinfo=api.TZ)
            result=api.read_order_attribution(SimpleNamespace(get=get),"reviewer",periods)
        self.assertEqual(replies,["2026-10-01","2026-10-29","2026-08-31","2026-09-28"])
        self.assertEqual(result["status"],"partial")
        self.assertEqual(result["current"]["sales_usd"],20.8)
        self.assertEqual(result["previous"]["orders"],4)
        self.assertEqual(result["coverage"]["current"]["missing_days"],["2026-10-29","2026-10-30","2026-10-31"])
        self.assertEqual(result["coverage"]["current"]["segments"][1]["error"],"OSError")
        self.assertEqual(result["coverage"]["previous"]["segments"][0]["status_code"],503)
        self.assertIn("2026-09-29",result["coverage"]["previous"]["missing_days"])
