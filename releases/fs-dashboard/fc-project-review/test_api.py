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

    def test_access_and_explicit_scope(self):
        self.assertEqual(self.get(False)[0],403)
        self.assertEqual(self.get(profile=["../all"])[0],422)
        self.assertEqual(self.get(site=["266"])[0],422)
        self.assertEqual(self.get(start=["2026-11-17"])[0],422)

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
