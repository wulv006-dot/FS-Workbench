"""Pre-collection references keep the existing confirmed-receipt semantics."""
from copy import deepcopy
from contextlib import closing
import json
from datetime import datetime, timezone
from pathlib import Path
import sys, tempfile, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from fc_pricing_v3 import runtime
from fc_pricing_v3.ledger import Ledger, confirmed_curve_window
from test_curve_writer_v6 import CurveWriter

class ConfirmedCostReferences(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Ledger(Path(self.tmp.name) / "ledger.sqlite3")
        fixture = CurveWriter()
        fixture.prepare()
        receipt = fixture.dispatch()
        self.assertEqual(receipt["status"], "CONFIRMED")
        self.base = dict(operation_id="original", status="COMPLETED", bundle=fixture.bundle, readback=receipt)
        self.base["readback"]["execution_id"] = "original"
        self.base["readback"]["curve_results"]["PS"]["operation_id"] = "original"
        confirmed_curve_window(self.base)

    def add(self, key, *, status="COMPLETED", selected=None, snapshot_cost=None, valid=True):
        op = deepcopy(self.base)
        op["operation_id"] = key; op["status"] = status
        op["readback"]["execution_id"] = key
        op["readback"]["curve_results"]["PS"]["operation_id"] = key
        op["bundle"]["snapshot_id"] = "snapshot-" + key
        op["bundle"]["curve_selection"] = {"PS": {"confirmed_cost_cny_per_k": selected}}
        if not valid: op["readback"]["curve_results"]["PS"]["propagation"]["status"] = "unconfirmed"
        self.db.put("pricing_snapshots", "snapshot-" + key, {"evidence": {"costs": {"PS": {"cny_per_1k": snapshot_cost}}}})
        self.db.put("operations", key, op)

    def compare(self):
        now = datetime.now(timezone.utc)
        def old_reference(platform):
            with closing(self.db.connect()) as conn:
                for raw, in conn.execute("SELECT body FROM operations ORDER BY rowid DESC"):
                    op = json.loads(raw)
                    if (op.get("status") not in ("COMPLETED", "NO_CHANGE")
                            or platform not in (op.get("bundle", {}).get("action", {}).get("curves") or {})):
                        continue
                    try: confirmed_curve_window(op)
                    except ValueError: continue
                    snapshot = self.db.get("pricing_snapshots", op["bundle"]["snapshot_id"], conn) or {}
                    cost = (snapshot.get("evidence", {}).get("costs") or {}).get(platform) or {}
                    selected = (op["bundle"].get("curve_selection") or {}).get(platform) or {}
                    return selected.get("confirmed_cost_cny_per_k") or cost.get("cny_per_1k")
            return None
        expected = {p: old_reference(p) for p in ("PS", "XBOX", "PC")}
        result = runtime._confirmed_cost_references(self.db)
        self.assertEqual(result, expected)
        self.assertEqual({p: runtime._curve_insurance_context(self.db,p,{},now)["confirmed_cost_cny_per_k"]
                          for p in expected}, expected)
        return result

    def test_latest_valid_confirmed_receipt_and_snapshot_fallback(self):
        self.add("old", selected="0.40", snapshot_cost="0.45")
        self.add("incomplete", selected="9", valid=False)
        self.add("failed", status="FAILED", selected="8")
        self.assertEqual(self.compare(), {"PS":"0.40", "XBOX":None, "PC":None})
        self.add("new", status="NO_CHANGE", selected=None, snapshot_cost="0.39")
        self.assertEqual(self.compare()["PS"], "0.39")
        self.add("latest", selected="0.37", snapshot_cost="0.38")
        self.assertEqual(self.compare()["PS"], "0.37")

    def test_latest_valid_missing_reference_does_not_use_older_value(self):
        self.add("old", selected="0.40")
        self.add("latest", selected=None, snapshot_cost=None)
        self.assertIsNone(self.compare()["PS"])

    def test_three_platform_original_receipts_in_one_operation(self):
        from unittest.mock import patch
        import test_curve_writer_v6 as fixture_module
        bundle = deepcopy(self.base["bundle"])
        receipt = deepcopy(self.base["readback"])
        bundle["snapshot_id"] = "multi-snapshot"
        bundle["affected_platforms"] = ["PS", "XBOX", "PC"]
        bundle["curve_selection"] = {"PS": {"confirmed_cost_cny_per_k": "0.40"}}
        for platform in ("XBOX", "PC"):
            all_id, primary_id, aid = fixture_module.writer.PRODUCTS[platform]
            with patch.multiple(fixture_module, PLATFORM=platform, ALL_ID=all_id, PRIMARY_ID=primary_id, AID=aid):
                fixture = fixture_module.CurveWriter(); fixture.prepare()
                fixture.transport.apply_recipient = lambda: fixture_module.Transport.apply_recipient(fixture.transport, primary_id)
                part = fixture.dispatch()
            bundle["action"]["curves"][platform] = deepcopy(fixture.bundle["action"]["curves"][platform])
            receipt["curve_results"][platform] = deepcopy(part["curve_results"][platform])
            receipt["curve_results"][platform]["operation_id"] = "original"
            bundle["curve_selection"][platform] = {"confirmed_cost_cny_per_k": ".33" if platform == "XBOX" else None}
        op = dict(operation_id="original", status="COMPLETED", bundle=bundle, readback=receipt)
        confirmed_curve_window(op)
        self.db.put("pricing_snapshots", "multi-snapshot", {"evidence": {"costs": {"PC": {"cny_per_1k": ".31"}}}})
        self.db.put("operations", "multi", op)
        self.assertEqual(self.compare(), {"PS":"0.40", "XBOX":".33", "PC":".31"})

    def test_reference_reader_does_not_read_unrelated_insurance_tables(self):
        self.add("only", selected="0.40")
        queries=[]; original=self.db.connect
        def traced():
            conn=original(); conn.set_trace_callback(queries.append); return conn
        self.db.connect=traced
        self.assertEqual(runtime._confirmed_cost_references(self.db)["PS"], "0.40")
        text=" ".join(queries).lower()
        self.assertIn("begin",text)
        self.assertNotIn("strategy_decisions",text)
        self.assertNotIn("actual_price_windows",text)

if __name__ == "__main__": unittest.main()
