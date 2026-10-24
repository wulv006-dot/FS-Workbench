import unittest
from dataclasses import replace

from campaign_backend.core import ContractError, Money
from campaign_backend.attribution import (AppliedBenefit, BenefitRef, Binding, Order, OrderLine,
                                           OrderMapping, Refund, attribute, normalize_order)

START = '2026-10-01T00:00:00+00:00'
END = '2026-11-01T00:00:00+00:00'
PAID = '2026-10-24T10:00:00+00:00'
REF = BenefitRef('coupon', 'coupon-1', 'batch-1')
USE = AppliedBenefit(REF, PAID, 'r1')
BINDING = Binding('fc27-season2', 'b1', 'r1', '266', REF, START, END)


def order(**changes):
    return replace(Order('266', 'order-1', 'paid', PAID, Money('USD', 2, 13300), (USE,)), **changes)


class AttributionTests(unittest.TestCase):
    def test_paid_unfulfilled_without_browser_context_is_attributed(self):
        result = attribute([order()], [BINDING])
        self.assertEqual(result['global_totals'][0]['order_count'], 1)
        row = result['rows'][0]
        self.assertEqual(row['linked_paid_minor'], 13300)
        self.assertIsNone(row['allocated_paid_minor'])
        self.assertEqual(row['allocation_status'], 'missing')
        self.assertEqual(row['attribution_level'], 'activity_group')
        self.assertEqual(row['page_ids'], [])
        self.assertIsNone(result['global_totals'][0]['allocated_paid_minor'])
        self.assertEqual(result['global_totals'][0]['known_allocated_paid_minor'], 0)

    def test_general_coupon_wrong_batch_version_site_or_time_does_not_match(self):
        for use in (AppliedBenefit(BenefitRef('coupon', 'generic'), PAID),
                    AppliedBenefit(BenefitRef('coupon', 'coupon-1', 'other'), PAID),
                    AppliedBenefit(REF, PAID, 'r2'), AppliedBenefit(REF, END, 'r1')):
            self.assertEqual(attribute([order(benefits=(use,))], [BINDING])['rows'], [])
        self.assertEqual(attribute([order(site_id='99')], [BINDING])['rows'], [])

    def test_unpaid_cancelled_and_test_mode_are_excluded(self):
        for changes in ({'payment_state': 'unpaid'}, {'payment_state': 'cancelled'}, {'mode': 'preview'},
                        {'mode': 'integration_test'}):
            self.assertEqual(attribute([order(**changes)], [BINDING])['rows'], [])

    def test_mixed_order_uses_actual_line_paid_not_order_total_or_discount_twice(self):
        lines = (OrderLine('activity', (USE,), Money('USD', 2, 8550)),
                 OrderLine('normal', (), Money('USD', 2, 4750)))
        row = attribute([order(lines=lines)], [BINDING])['rows'][0]
        self.assertEqual(row['basket_scope'], 'mixed')
        self.assertEqual(row['allocated_paid_minor'], 8550)
        self.assertEqual(row['linked_paid_minor'], 13300)

    def test_known_mixed_lines_missing_allocation_are_explicit(self):
        row = attribute([order(lines=(OrderLine('a', (USE,)), OrderLine('other', ())))], [BINDING])['rows'][0]
        self.assertEqual(row['basket_scope'], 'mixed')
        self.assertEqual(row['allocation_status'], 'missing')
        self.assertIsNone(row['allocated_net_minor'])

    def test_all_lines_activity_still_requires_real_allocation(self):
        row = attribute([order(lines=(OrderLine('a', (USE,)),))], [BINDING])['rows'][0]
        self.assertEqual(row['basket_scope'], 'all')
        self.assertIsNone(row['allocated_paid_minor'])

    def test_multi_activity_and_duplicate_orders_global_dedup(self):
        ref2 = BenefitRef('campaign', 'rule-2')
        use2 = AppliedBenefit(ref2, PAID, 'r2')
        binding2 = Binding('limited', 'b2', 'r2', '266', ref2, START, END, 'limited-page')
        original = order(benefits=(USE, use2), lines=(OrderLine('same', (USE, use2), Money('USD', 2, 13300)),))
        result = attribute([original, original], [BINDING, binding2])
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['global_totals'][0]['order_count'], 1)
        self.assertEqual(result['global_totals'][0]['linked_paid_minor'], 13300)
        self.assertEqual(result['global_totals'][0]['allocated_paid_minor'], 13300)

    def test_conflicting_duplicate_order_fails_closed(self):
        with self.assertRaisesRegex(ContractError, 'CONFLICTING_DUPLICATE_FACT'):
            attribute([order(), order(paid=Money('USD', 2, 10))], [BINDING])

    def test_refund_stable_id_dedup_and_line_allocation(self):
        original = order(lines=(OrderLine('a', (USE,), Money('USD', 2, 13300)),))
        refund = Refund('266', 'refund-1', 'order-1', Money('USD', 2, 300), 'a')
        result = attribute([original], [BINDING], [refund, refund])
        self.assertEqual(result['rows'][0]['linked_net_minor'], 13000)
        self.assertEqual(result['rows'][0]['allocated_net_minor'], 13000)
        with self.assertRaisesRegex(ContractError, 'CONFLICTING_DUPLICATE_FACT'):
            attribute([original], [BINDING], [refund, replace(refund, amount=Money('USD', 2, 400))])

    def test_unallocated_refund_preserves_payment_and_unknown_activity_net(self):
        original = order(lines=(OrderLine('a', (USE,), Money('USD', 2, 13300)),))
        row = attribute([original], [BINDING], [Refund('266', 'r1', 'order-1', Money('USD', 2, 300))])['rows'][0]
        self.assertEqual(row['linked_paid_minor'], 13300)
        self.assertEqual(row['linked_net_minor'], 13000)
        self.assertIsNone(row['allocated_refund_minor'])
        self.assertIsNone(row['allocated_net_minor'])

    def test_refund_foreign_currency_and_excess_rejected(self):
        for amount in (Money('CNY', 2, 1), Money('USD', 2, 13301)):
            with self.assertRaises(ContractError):
                attribute([order()], [BINDING], [Refund('266', 'r1', 'order-1', amount)])

    def test_currencies_separate_and_scales_not_assumed_two(self):
        result = attribute([order(), order(order_no='jpy', paid=Money('JPY', 0, 123))], [BINDING])
        self.assertEqual({r['currency']: r['linked_paid_minor'] for r in result['global_totals']},
                         {'JPY': 123, 'USD': 13300})

    def test_shared_coupon_cannot_be_assigned_to_several_pages(self):
        with self.assertRaisesRegex(ContractError, 'AMBIGUOUS_BINDING'):
            attribute([order()], [replace(BINDING, page_id='weekly'), replace(BINDING, page_id='sbc')])

    def test_money_exact_precision_and_unknown_currency(self):
        self.assertEqual(Money.parse('85.50', 'USD', {'USD': 2}).minor, 8550)
        for amount, currency in (('1.001', 'USD'), (1.23, 'USD'), ('1', 'XYZ'), ('NaN', 'USD')):
            with self.assertRaises(ContractError):
                Money.parse(amount, currency, {'USD': 2})
        for amount in ('1e1000000', '1e-1000000', '92233720368547758.08'):
            with self.assertRaises(ContractError):
                Money.parse(amount, 'USD', {'USD': 2})
        self.assertEqual(Money.parse('92233720368547758.07', 'USD', {'USD': 2}).minor,
                         9223372036854775807)

    def test_explicit_enum_currency_amount_and_timezone_mapping(self):
        mapping = OrderMapping('fixture-only', dict(site_id='site', order_no='number',
            payment_state='payment', paid_at='at', paid='received', currency='ccy'),
            ((2, 'paid'), (0, 'unpaid')), {'USD': 2}, 'production')
        raw = dict(site=266, number='A', payment=2, at=PAID, received='85.50', ccy='USD')
        self.assertEqual(normalize_order(raw, mapping, benefits=(USE,)).paid.minor, 8550)
        for value in (True, '2', 99):
            with self.assertRaisesRegex(ContractError, 'SOURCE_ENUM_UNKNOWN'):
                normalize_order(dict(raw, payment=value), mapping)
        with self.assertRaisesRegex(ContractError, 'TIMEZONE_REQUIRED'):
            normalize_order(dict(raw, at='2026-10-24 10:00:00'), mapping)
        with self.assertRaises(ContractError):
            normalize_order(dict(raw, site=None), mapping)


if __name__ == '__main__':
    unittest.main()
