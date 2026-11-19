"""The planning-basket timestamp fast path preserves the original parser."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from fc_pricing_v3 import planning_baskets_v6 as baskets
from fc_pricing_v3.financial import instant

class PlanningTimestampTest(unittest.TestCase):
    def test_original_and_fast_paths_accept_and_reject_the_same_times(self):
        values = ["2026-11-19T14:38:32.220076+00:00", "2026-11-19T22:38:32+08:00",
                  "2026-11-19T14:38:32Z", "2026-11-19 22:38:32", "26-11-19 22:38:32",
                  " 2026-11-19T14:38:32+00:00 ", "2026-11-19", "not a date", None,
                  "2026-99-01T00:00:00+08:00", datetime(2026,11,19,tzinfo=timezone(timedelta(hours=8)))]
        for value in values:
            try: expected = instant(value)
            except ValueError: expected = None
            with self.subTest(value=value):
                actual = baskets._instant(value)
                self.assertEqual(actual, expected)
                if actual is not None:
                    self.assertEqual(actual.isoformat(), expected.isoformat())

    def test_complete_proof_is_byte_equivalent(self):
        from fc_pricing_v3 import runtime
        from fc_pricing_v3.average_discount_v6 import average_discount
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, fx, rows_for
        from test_curve_strategy_v6 import fixture
        curve, _, _ = fixture()
        source = attachment(list(rows_for([48] * 64)))
        source["historical_orders_coverage"].update(shared_publication_id="pin", shared_source_revision="source", paid_window_start=(CUT-timedelta(days=8)).isoformat())
        for row in source["historical_orders"]:
            row.update(single_line_unit_purchase=True, merchandise_before_discount_usd="100", actual_es_discount_usd="0")
        cost = smooth_delivery_cost(dict(platform="PS", checked_at=AS_OF.isoformat(), v6_delivery_samples=dict(window_complete=True, history_complete=True,
            records=[dict(platform="PS", status="valid", record_id=str(i), trade_at=(AS_OF-timedelta(minutes=i)).isoformat(), cny_per_1k=".4") for i in range(6)])), "PS", AS_OF, ".4")
        def proof():
            return runtime._average_discount_proof_input(curve,"PS",source,source,CUT.isoformat(),AS_OF,
                average=average_discount(source,"PS",CUT),route={"propagation_revision":"directory"},facts=None,fx=fx(),current_cost=cost)
        optimized = proof()
        def previous(value):
            try: return instant(value)
            except ValueError: return None
        with patch.object(baskets, "_instant", previous): original = proof()
        self.assertEqual(optimized, original)

if __name__ == "__main__": unittest.main()
