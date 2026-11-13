"""Use private source outputs to test payment-window cost diagnostics without live reads."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT.parents[1] / 'fs-dashboard'
sys.path[:0] = [str(ROOT / 'source'), str(DASHBOARD / 'dashboard-refresh-20261025/source'),
                str(DASHBOARD / 'cache-archive-retention-20261025/source')]
from fc_pricing_v3 import business_source
from fc_pricing_v3.cost_inputs_v6 import BOC_URL, estimate_historical_cost
from order_facts_source import project_order_facts


CUT = datetime.fromisoformat('2026-11-13T00:00:00+08:00')
AS_OF = CUT + timedelta(minutes=30)
LAYER = dict(platform='PS', quantity_bucket='large', offer_version='offer-1', fulfilment_contract='normal')
SCOPE = dict(site_id='266', gid='1327', start='2026-11-06', end='2026-11-12')


def rows_for(offsets, *, quantity='1000K Coins + 30K Free x1 = $50'):
    for index, hours in enumerate(offsets):
        yield (f'private-order-{index}', CUT - timedelta(hours=hours), quantity)


def attachment(orders, *, observed=AS_OF, cost=None):
    selected, traces = {}, {}
    period = business_source.historical_period('7d', now=observed)['period']
    for identity, paid, quantity in orders:
        date = paid.strftime('%Y-%m-%d %H:%M:%S')
        selected[identity] = (dict(paidAt=date, salesUsd='50', status='已完成', coupons=[],
                                   costCny=cost, deliveryRows=1), {'discount_usd': '0'})
        traces[identity] = dict(aid='21587', before_discount='50', amount_usd_format='50',
                                amount_rmb_format='350', discount='100', points='0',
                                content=f'<span class="item">{quantity}</span>')
    provenance = dict(period=period, status='complete', canonical_archive_sha256='archive-revision',
                      ES_source_sha256='ES-revision', ES_complete=True, missing_product_identity=0)
    with patch.object(business_source, '_historical_provider_now', return_value=observed), \
         patch.object(business_source, '_period_population', return_value=(selected, provenance)), \
         patch.object(business_source, '_live_traces', return_value=(traces, {}, {})), \
         patch.object(business_source, 'historical_mix', return_value={'sha256': 'mix-revision'}):
        return business_source.collect_historical_attachment('7d', None, None)


def facts(orders, *, complete=False, captured=AS_OF, generated=None, cost='350',
          shipment_complete=True, site='266', cost_revision='cost-revision',
          cost_period=None):
    admins, deliveries, completed = [], [], []
    source = 'www.mmoexp.com' if site == '266' else 'www.rsorder.com'
    for i, (identity, paid, _) in enumerate(orders):
        admins.append(dict(site_id=site, order_no=identity, site={'full_title': source}, gid='1327',
                           paytime=paid.strftime('%Y-%m-%d %H:%M:%S'), pay_status='1', status_format='已完成'))
        deliveries.append(dict(source=source, sn=identity, delivery_id=str(i), genre='1',
                               cost_total=cost, qty='1100', quantity_unit='K',
                               trade_at=(paid + timedelta(minutes=10)).isoformat()))
        completed.append((site, identity))
    proof = dict(source_revision='Admin-revision', captured_at=captured.isoformat(), admin_complete=True,
                 cost=dict(source_revision=cost_revision, generated_at=(generated or captured).isoformat(),
                           order_cost_complete=complete, shipment_window_complete=shipment_complete,
                           period=SCOPE if cost_period is None else cost_period))
    # Expose actual_cost_cny in the fact to verify that it still requires envelope proof.
    return project_order_facts(admins, None, deliveries, scope=dict(SCOPE, site_id=site), source_coverage=proof,
                               complete_cost_orders=completed)


def fx(at=AS_OF, **overrides):
    return dict(dict(status='valid', cny_per_usd='7', checked_at=at.isoformat(),
                     published_at=at.strftime('%Y/%m/%d'), url=BOC_URL), **overrides)


def run(attachments, *, revisions=(), rate=None, as_of=AS_OF, basis='PURCHASE_K', matches=None):
    if matches is None:
        matches = {row['order_key']: dict(layer=LAYER, order_revision=row['source_sha256'],
                    available_at=row['available_at'], evidence_ref='verified-layer')
                   for item in reversed(attachments) for row in item['historical_orders']}
    return estimate_historical_cost(attachments, LAYER, basis, as_of=as_of, paid_cutoff=CUT,
                                    layer_matches=matches, fact_revisions=revisions, fx=rate)


class CostInputs(unittest.TestCase):
    def test_attachment_amount_is_cny_observation_and_never_rewrites_actuals(self):
        orders = list(rows_for([1]))
        original = attachment(orders, cost='70')
        before = deepcopy(original)
        result = run([original])
        self.assertEqual(original, before)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertEqual(result['time_basis'], 'payment_cohort')
        self.assertIn('procurement_time_unverified', result['gaps'])
        self.assertIn('forecast_fx_unavailable_as_of', result['gaps'])
        self.assertEqual(result['selected_window']['known_partial_cost_cny'], Decimal('70'))
        self.assertEqual(result['diagnostic_estimate']['incomplete_cost_orders'], 1)
        self.assertIsNone(result['diagnostic_estimate']['expected_unit_usd'])

    def test_d2_same_private_order_is_joined_without_counting_source_amount_twice(self):
        orders = list(rows_for([1]))
        original = attachment(orders, cost='100')
        data = facts(orders, cost='140')
        result = run([original], revisions=[data], rate=fx())
        self.assertEqual(result['selected_window']['known_cost_cny'], Decimal('140'))
        self.assertEqual(result['diagnostic_estimate']['known_partial_usd'], Decimal('20'))
        self.assertEqual(result['selected_window']['complete_comparable_orders'], 0)
        self.assertIn('order_cost_completeness_unverified', result['gaps'])
        self.assertNotIn(orders[0][0], str(result))
        result = run([original], revisions=[facts(orders, site='320')], rate=fx())
        self.assertEqual(result['selected_window']['known_partial_cost_cny'], Decimal('100'))

    def test_window_widens_only_when_complete_comparable_samples_are_short(self):
        for recent_count, expected in [(9, 168), (10, 72)]:
            with self.subTest(recent=recent_count):
                orders = list(rows_for([1] * recent_count + [72, 90, 168, 169]))
                # Unknown denominator does not count as a complete comparable sample.
                orders[0] = (*orders[0][:2], 'not a native quantity')
                if recent_count == 10:
                    orders.append(('extra-recent', CUT - timedelta(hours=2), '1000K Coins x1 = $50'))
                value = run([attachment(orders)], revisions=[facts(orders, complete=True)], rate=fx())
                self.assertEqual(value['window_hours'], expected)
                self.assertEqual(value['recent_72h']['complete_comparable_orders'],
                                 recent_count if expected == 168 else recent_count + 1)
                self.assertEqual(value['diagnostic_estimate']['unknown_quantity_orders'], 1)
                self.assertEqual(value['diagnostic_estimate']['unallocated_known_cost_usd'], Decimal('50'))
                self.assertEqual(value['diagnostic_estimate']['expected_unit_usd'], Decimal('.05'))

    def test_recent_threshold_and_window_start_are_inclusive(self):
        orders = list(rows_for([1] * 9 + [72, 90]))
        result = run([attachment(orders)], revisions=[facts(orders, complete=True)], rate=fx())
        self.assertEqual(result['window_hours'], 72)
        self.assertEqual(result['selected_window']['complete_comparable_orders'], 10)
        self.assertEqual(result['selected_window']['paid_by_beijing_day'], {'2026-11-10': 1, '2026-11-12': 9})
        self.assertEqual(result['diagnostic_estimate']['expected_unit_usd'], Decimal('.05'))

    def test_replay_excludes_future_cost_revision_and_future_fx(self):
        orders = list(rows_for([1]))
        visible = attachment(orders, cost='70')
        late = AS_OF + timedelta(minutes=15)
        future = attachment(orders, observed=late, cost='140')
        original_facts = facts(orders, cost='70', cost_revision='original-cost')
        revised_facts = facts(orders, complete=True, cost='140', captured=late, cost_revision='revised-cost')
        replay = run([visible, future], revisions=[revised_facts, original_facts], rate=fx(late))
        self.assertEqual(replay['attachment_revision'], visible['source_sha256'])
        self.assertEqual(replay['order_cost_source']['source_revision'], 'original-cost')
        self.assertEqual(replay['selected_window']['known_partial_cost_cny'], Decimal('70'))
        self.assertIsNone(replay['forecast_fx'])
        refreshed = run([future, visible], revisions=[original_facts, revised_facts], as_of=late, rate=fx(late),
                        matches={row['order_key']: dict(layer=LAYER, order_revision=row['source_sha256'],
                                 available_at=row['available_at'], evidence_ref='verified-layer')
                                 for row in future['historical_orders']})
        self.assertEqual(refreshed['attachment_revision'], future['source_sha256'])
        self.assertEqual(refreshed['selected_window']['complete_comparable_orders'], 1)
        self.assertEqual(refreshed['diagnostic_estimate']['expected_unit_usd'], Decimal('.02'))

    def test_actual_shipped_quantity_cannot_change_promised_denominator(self):
        orders = list(rows_for([1, 2]))
        result = run([attachment(orders)], revisions=[facts(orders[:1], complete=True)], rate=fx(),
                     basis='PROMISED_DELIVERED_K')
        estimate = result['diagnostic_estimate']
        self.assertEqual(estimate['known_quantity_k'], Decimal(2060))
        self.assertEqual(estimate['alpha'], Decimal('.5'))
        self.assertEqual(estimate['expected_unit_usd'] * Decimal(1030), Decimal('50'))
        self.assertIsNone(estimate['safe_unit_usd'])

    def test_complete_claim_requires_trade_in_source_cost_scope(self):
        orders = list(rows_for([1]))
        original = attachment(orders)
        narrow = dict(start='2026-11-12', end='2026-11-12', until='2026-11-12 23:09')
        result = run([original], revisions=[facts(orders, complete=True, cost_period=narrow)], rate=fx())
        self.assertEqual(result['selected_window']['complete_comparable_orders'], 0)
        self.assertEqual(result['selected_window']['known_partial_cost_cny'], Decimal('350'))

    def test_no_delivery_records_remains_unknown_even_when_d2_observed_sum_is_zero(self):
        orders = list(rows_for([1]))
        source = facts(orders, cost=None)
        self.assertEqual(source['orders'][0]['observed_cost_cny'], '0')
        result = run([attachment(orders)], revisions=[source], rate=fx())
        self.assertIsNone(result['selected_window']['known_partial_cost_cny'])
        self.assertEqual(result['diagnostic_estimate']['incomplete_cost_orders'], 1)

    def test_consumes_existing_archived_boc_evidence_schema(self):
        recorded = json.loads((ROOT / 'tests/fixtures/d8-lowest-anchor.json').read_text(encoding='utf-8'))
        rate = recorded['evidence']['fx']
        captured = datetime.fromisoformat(rate['checked_at'])
        value = estimate_historical_cost([], LAYER, 'PURCHASE_K', as_of=captured, layer_matches={}, fx=rate)
        self.assertEqual(value['forecast_fx']['cny_per_usd'], rate['cny_per_usd'])
        self.assertEqual(value['forecast_fx']['available_at'], captured.isoformat())

    def test_unmapped_layer_and_wrong_fx_stay_unavailable(self):
        orders = list(rows_for([1]))
        original = attachment(orders, cost='350')
        cases = [fx(AS_OF - timedelta(minutes=61)), fx(url='wrong'), fx(published_at='2026/11/14')]
        for rate in cases:
            with self.subTest(rate=rate):
                result = run([original], rate=rate, matches={})
                self.assertIn('cost_layer_unverified', result['gaps'])
                self.assertIn('forecast_fx_unavailable_as_of', result['gaps'])
                self.assertEqual(result['selected_window']['orders_with_known_cny'], 0)


if __name__ == '__main__':
    unittest.main()
