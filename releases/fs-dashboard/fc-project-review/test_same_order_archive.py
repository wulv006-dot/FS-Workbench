from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib import import_module
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_review import core


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
api = import_module(HERE.name + ".api")
same_order = import_module(HERE.name + ".same_order")


class SameOrderArchiveTests(unittest.TestCase):
    def setUp(self):
        area = TemporaryDirectory()
        self.addCleanup(area.cleanup)
        self.root = Path(area.name)
        source_path = str(HERE.parent / "dashboard-refresh-20261025/source")
        sys.path.insert(0, source_path)
        self.addCleanup(sys.path.remove, source_path)
        self.day = "2026-11-16"
        self.params = dict(mode=["fc-project-review"], profile=["FC27"], start=[self.day], end=[self.day])
        self.upstream = Mock(side_effect=AssertionError("unexpected upstream request"))

    def get(self):
        return api.get(self.params, "reviewer", self.upstream, None, lambda _: True, self.root)

    def test_closed_packet_recovers_published_payment_completion_and_delivery(self):
        orders, receipts, rows = {}, {}, []
        coverage = dict(admin_complete=False, missing_days=[self.day])
        published = SimpleNamespace(
            read=lambda scope, native_only: dict(coverage=coverage, rows=rows),
            read_main_paid_status=lambda scope: (dict(orders), dict(receipts)),
        )
        now = datetime(2026, 11, 19, tzinfo=api.TZ)
        def read_same_order(game, start, end):
            return same_order.same_order_review(game, start, end, cost_root=self.root,
                overrides=lambda config: dict(config, costOverrides={}, testOrders={}))

        with patch.object(api, "datetime", wraps=datetime) as api_clock, \
                patch.object(same_order, "datetime", wraps=datetime) as source_clock, \
                patch.object(api, "same_order_review", side_effect=read_same_order), \
                patch.dict(sys.modules, shared_es_facts=published), patch.object(api.POOL, "submit") as submit:
            api_clock.now.return_value = source_clock.now.return_value = now
            packet = api.packet(core())
            packet["coverage"].append(same_order.UNAVAILABLE_NOTE)
            packet["sameOrder"] = read_same_order("FC27", self.day, self.day)
            first = api.publish(packet, self.root)
            self.assertEqual(first["packets"][0]["sameOrder"]["status"], "unavailable")

            coverage.update(admin_complete=True, missing_days=[], source_revision="pay-v1",
                            captured_at="2026-11-17T09:00:00+08:00")
            rows.append(dict(id=1, gid=1327, site_id=266, order_no="TEST-ORDER", pay_status=1,
                paytime=self.day + " 01:00:00", status_format="已完成", amount_usd_format="100",
                amount_rmb_format="700", site=dict(full_title=same_order.MAIN)))
            status, paid = self.get()
            self.assertEqual((status, paid["packets"][0]["sameOrder"]["totals"]["salesUsd"]), (200, 100))
            self.assertNotEqual(paid["revision"], first["revision"])

            orders[self.day, "TEST-ORDER"] = dict(id="1", paidAt=self.day + " 01:00:00", amountUsd="100", revision=1)
            receipts[self.day] = dict(jobId="receipt", revision=1, observedAt="2026-11-17T08:00:00+08:00")
            status, completed = self.get()
            completed_facts = completed["packets"][0]["sameOrder"]
            self.assertEqual((status, completed_facts["status"]), (200, "partial"))
            self.assertEqual(completed_facts["coverage"]["missingCompletedStatusDays"], [])
            self.assertNotEqual(completed["revision"], paid["revision"])

            delivery = dict(delivery_id="1", sn="TEST-ORDER", trade_at=self.day + " 05:00:00",
                            cost_total="400", source=same_order.MAIN, genre=1)
            period = dict(start=self.day, end="2026-11-17", since=self.day + " 00:00:00", until="2026-11-17 08:00:00")
            delivery_path = self.root / "order-deliveries.json"
            def publish_delivery(rows, *, bounds=period, stamp="2026-11-17T09:00:00+08:00"):
                delivery_path.write_text(json.dumps(dict(contract="channel-order-deliveries-v1",
                    complete=True, period=bounds, generatedAt=stamp, rows=rows)), encoding="utf-8")

            publish_delivery([delivery])
            live_status, live = api.get({**self.params, "view": ["same-order"]}, "reviewer", self.upstream,
                                        None, lambda _: True, self.root)
            self.assertEqual((live_status, live["status"], live["totals"]["actualCostCny"]), (200, "complete", 400))
            status, updated = self.get()
            self.assertEqual(status, 200)
            persisted = updated["packets"][0]
            self.assertEqual(persisted["sameOrder"]["status"], "complete")
            self.assertEqual(persisted["sameOrder"]["totals"]["actualCostCny"], 400)
            self.assertNotEqual(updated["revision"], first["revision"])
            self.assertEqual(persisted["coverage"], [note for note in packet["coverage"]
                                                    if note != same_order.UNAVAILABLE_NOTE])
            self.assertEqual({key: value for key, value in persisted.items() if key not in ("sameOrder", "coverage")},
                             {key: value for key, value in packet.items() if key not in ("sameOrder", "coverage")})
            version_path = self.root / "FC27" / "versions" / (f"{self.day}_{self.day}_{first['revision']}.json")
            self.assertEqual(json.loads(version_path.read_text(encoding="utf-8")), first)
            status, historical = api.get({**self.params, "revision": [first["revision"]]}, "reviewer",
                                         self.upstream, None, lambda _: True, self.root)
            self.assertEqual((status, historical), (200, first))

            # Republished inputs with the same scoped facts keep the archive revision.
            pointer = self.root / "FC27" / f"{self.day}_{self.day}.json"
            modified = pointer.stat().st_mtime_ns
            coverage.update(publication_id="new-unrelated-publication", captured_at="2026-11-18T09:00:00+08:00")
            publish_delivery([delivery], stamp="2026-11-17T10:00:00+08:00")
            self.assertEqual(self.get()[1]["revision"], updated["revision"])
            self.assertEqual(pointer.stat().st_mtime_ns, modified)

            # A narrow fallback cannot establish the earlier shipment is gone.
            narrow = dict(period, since=self.day + " 06:00:00")
            publish_delivery([], bounds=narrow)
            self.assertEqual(self.get()[1]["revision"], updated["revision"])
            # Losing the completion observation likewise does not revoke earlier evidence.
            receipt = receipts.pop(self.day)
            self.assertEqual(self.get()[1]["revision"], updated["revision"])
            receipts[self.day] = receipt

            publish_delivery([delivery], stamp="2026-11-17T11:00:00+08:00")
            with self.subTest("older Admin snapshot"):
                coverage["captured_at"] = "2026-11-17T00:45:00Z"
                rows[0]["amount_usd_format"] = "90"
                self.assertEqual(self.get()[1]["revision"], updated["revision"])
            coverage["captured_at"] = "2026-11-18T09:00:00+08:00"
            rows[0]["amount_usd_format"] = "100"
            api.publish(persisted, self.root)

            with self.subTest("advanced completion receipt without matching delivery cutoff"):
                receipts[self.day] = dict(receipt, revision=2, observedAt="2026-11-17T10:00:00+08:00")
                self.assertEqual(self.get()[1]["revision"], updated["revision"])

            receipts[self.day] = receipt

            with self.subTest("same completion receipt without reconstructable witness"):
                witness = orders.pop((self.day, "TEST-ORDER"))
                self.assertEqual(self.get()[1]["revision"], updated["revision"])
            orders[self.day, "TEST-ORDER"] = witness
            api.publish(persisted, self.root)

            # An authoritative replacement of the same trade window can revoke evidence.
            publish_delivery([], stamp="2026-11-17T11:00:00+08:00")
            status, corrected = self.get()
            self.assertEqual((status, corrected["packets"][0]["sameOrder"]["totals"]["coveredOrders"]), (200, 0))
            self.assertNotEqual(corrected["revision"], updated["revision"])

            with self.subTest("delivery coverage catches up to the newer completion receipt"):
                receipts[self.day] = dict(receipt, revision=2, observedAt="2026-11-17T10:00:00+08:00")
                extended = dict(period, until="2026-11-17 10:00:00")
                publish_delivery([dict(delivery, cost_total="410")], bounds=extended,
                                 stamp="2026-11-17T11:30:00+08:00")
                status, revised = self.get()
                self.assertEqual((status, revised["packets"][0]["sameOrder"]["totals"]["actualCostCny"]), (200, 410))

            with self.subTest("new publication confirms the order no longer completed"):
                coverage["captured_at"] = "2026-11-18T10:00:00+08:00"
                receipts[self.day] = dict(receipt, revision=3, observedAt="2026-11-17T12:00:00+08:00")
                rows[0]["status_format"] = "待发货"
                del orders[self.day, "TEST-ORDER"]
                status, removed = self.get()
                self.assertEqual((status, removed["packets"][0]["sameOrder"]["totals"]["completedOrders"]), (200, 0))

            submit.assert_not_called()
            self.upstream.assert_not_called()

    def test_closed_packet_preserves_indexed_trade_evidence_from_fallback(self):
        window_start = self.day + " 00:00:00"
        receipt_at = "2026-11-17T08:00:00+08:00"
        window_end = "2026-11-17 08:00:00"

        def facts(start, captured_at, cost, index=None):
            witness = dict(start=start, end=window_end, capturedAt=captured_at, revision="trade-capture")
            if index is not None:
                witness["indexRevision"] = index
            return dict(status="partial", totals=dict(coveredOrders=1, actualCostCny=cost),
                revisions=dict(completedStatus={self.day: dict(observedAt=receipt_at)}, order=[witness]),
                coverage=dict(missingDays=[], invalidCostFiles=[], costWindows=[[start, window_end]]))

        indexed = facts(window_start, "2026-11-17T10:00:00+08:00", 400, index="corrected-index")
        with patch.object(api, "datetime", wraps=datetime) as clock, \
                patch.object(api, "same_order_review") as read, patch.object(api.POOL, "submit") as submit:
            clock.now.return_value = datetime(2026, 11, 19, tzinfo=api.TZ)
            original = api.publish(dict(api.packet(core()), sameOrder=indexed), self.root)
            fallbacks = {
                "narrower time range covers a different order": facts(self.day + " 06:00:00",
                    "2026-11-17T11:00:00+08:00", 250),
                "older raw capture covers the same window": facts(window_start, "2026-11-17T09:00:00+08:00", 450),
                "same-time raw capture cannot replace indexed authority": facts(window_start,
                    "2026-11-17T10:00:00+08:00", 600),
            }
            for reason, fresh in fallbacks.items():
                with self.subTest(reason=reason):
                    api.publish(original["packets"][0], self.root)
                    read.return_value = fresh
                    status, selected = self.get()
                    self.assertEqual((status, selected["revision"]), (200, original["revision"]))

            corrected = facts(window_start, "2026-11-17T11:00:00+08:00", 300, index="newer-index")
            witness = corrected["revisions"]["order"][0]
            corrected["revisions"]["order"] = [dict(witness, start="2026-11-17 00:00:00"),
                dict(witness, end="2026-11-16 23:59:59")]
            read.return_value = corrected
            status, selected = self.get()
            self.assertEqual((status, selected["packets"][0]["sameOrder"]["totals"]["actualCostCny"]), (200, 300))
            submit.assert_not_called()

    def test_older_same_order_read_cannot_overwrite_concurrent_publish(self):
        read_started, continue_read = Event(), Event()
        pending = dict(status="partial", totals=dict(coveredOrders=0, pendingOrders=1),
            revisions=dict(completedStatus={}), coverage=dict(missingDays=[], invalidCostFiles=[]))

        def slow_read(*args):
            read_started.set()
            self.assertTrue(continue_read.wait(5))
            return pending

        now = datetime(2026, 11, 19, tzinfo=api.TZ)
        with patch.object(api, "datetime", wraps=datetime) as clock, \
                patch.object(api, "same_order_review", side_effect=slow_read), ThreadPoolExecutor(1) as workers:
            clock.now.return_value = now
            packet = api.packet(core())
            first = api.publish(packet, self.root)
            request = workers.submit(self.get)
            try:
                self.assertTrue(read_started.wait(5))
                concurrent = api.publish(dict(packet, sameOrder=dict(status="complete",
                    totals=dict(coveredOrders=1, pendingOrders=0))), self.root)
            finally:
                continue_read.set()
            status, result = request.result(timeout=5)
            self.assertEqual((status, result["revision"]), (200, concurrent["revision"]))
            self.assertNotEqual(first["revision"], concurrent["revision"])
            versions = self.root / "FC27" / "versions"
            self.assertEqual(len(list(versions.glob("*.json"))), 2)
            self.assertEqual(json.loads((versions.parent / f"{self.day}_{self.day}.json").read_text(encoding="utf-8")),
                             concurrent)


if __name__ == "__main__":
    unittest.main()
