"""Synthetic native catalogue preservation; no live pricing or save claims."""
from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3.price_curve import (
    EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, compile_curve, curve_key, quote_native, read_curve,
)


def goods():
    return dict(id=123, mid=41217957, gid=1327, cid=9623, site_id=266,
                aid=21587, unit='K', status=1, unit_price='0.08', discount='100',
                min_qty=1, title='coins', checked_at='old',
                more=dict(gold=['100', '1000', '2000'], give=['0', '30', '60'],
                          discount=['100', '98', '100'], price=['8', '75', '145'],
                          hot=[0, 1, 0], delivery_time=['1h', '2h', '2h']))


IDENTITY = {key: goods()[key] for key in
            ('id', 'mid', 'gid', 'cid', 'site_id', 'aid', 'unit', 'status')}
CONTRACT = dict(version='synthetic-v1', custom_quantity_status='unverified',
                region_projection_version='synthetic-region-v1', checked_at='old')


def read(row=None, contract=None):
    return read_curve(goods() if row is None else row, IDENTITY,
                      CONTRACT if contract is None else contract)


class NativeCurve(unittest.TestCase):
    def test_two_band_price_array_changes_only_selected_selling_prices(self):
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT
        from fc_pricing_v3.average_discount_v6 import forecast_quotes

        editor = dict(EDITOR_CONTRACT, price_edit_policy=TWO_BAND_PRICE_EDIT)
        row = catalogue()
        row.update(unit_price='0.0715')
        row['more']['price'] = ['0.71','3.57','7.15','57.20','71.50','107.25','143','357.50']
        original = read(row)
        result = compile_curve(original, {'anchor_prices_usd': {'1000': '74.99'}}, editor)
        expected = deepcopy(row)
        expected['more']['price'][4:] = [74.99, 112.48, 149.98, 374.95]
        expected['unit_price'] = 0.07499
        self.assertEqual(result['native_payload'], expected)
        with self.assertRaisesRegex(ValueError, 'editor_segment_anchor_invalid'):
            compile_curve(original, {'anchor_prices_usd': {'2000': '149.98'}}, editor)
        quotes = forecast_quotes(result, {Decimal(999), Decimal(1001)}, dict(revision='fixture',retained_ratio='1'))
        self.assertEqual(quotes['999']['promised_bonus_k'], '0')
        self.assertEqual(quotes['1001']['regular_usd'], '75.06')

    def test_two_band_small_edit_syncs_stale_unit_price_to_large_band(self):
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT

        editor = dict(EDITOR_CONTRACT, price_edit_policy=TWO_BAND_PRICE_EDIT)
        row = catalogue()
        row.update(unit_price='0.0839')
        row['more']['price'] = ['0.71','3.57','7.15','57.20','58.66','87.99','117.32','293.30']
        result = compile_curve(read(row), {'anchor_prices_usd': {'100': '5.70'}}, editor)
        self.assertEqual(result['unit_price_usd_per_k'], '0.05866')
        self.assertEqual(result['native_payload']['more']['price'][4:], ['58.66','87.99','117.32','293.30'])

    def test_forward_price_edit_accepts_native_derived_factor_above_direct_discount_limit(self):
        from fc_pricing_v3.price_curve import FORWARD_TIER_EDIT
        editor = dict(EDITOR_CONTRACT, price_edit_policy=FORWARD_TIER_EDIT)
        source = read(catalogue(), editor)
        candidate = compile_curve(source, {'anchor_prices_usd':{'100':'10.30','2000':'190'}}, editor)
        self.assertEqual(candidate['compilation_status'],'EDITOR_CANDIDATE')
        self.assertEqual(candidate['unit_price_usd_per_k'], source['unit_price_usd_per_k'])
        self.assertEqual([r['native_discount'] for r in candidate['tiers']], ['100','100','103','103','103','103','95','95'])
        self.assertEqual([r['native_price_usd'] for r in candidate['tiers']], ['1','5','10.3','82.4','103','154.5','190','475'])
        self.assertEqual(compile_editor({100:'10.30'})['compilation_status'],'PROOF_INCOMPLETE')

    def test_forward_native_controls_keep_prefix_and_replace_tail_until_next_control(self):
        from fc_pricing_v3.price_curve import FORWARD_TIER_EDIT
        editor = dict(EDITOR_CONTRACT, price_edit_policy=FORWARD_TIER_EDIT)
        source = catalogue()
        before = read(source, editor)
        one = compile_curve(before, {'anchor_prices_usd':{'100':'9.99'}}, editor)
        amounts = {tier['purchase_k']: tier['native_price_usd'] for tier in one['tiers']}
        self.assertEqual(amounts['100'], '9.99')
        self.assertEqual(amounts['5000'], '499.5')
        two = compile_curve(before, {'anchor_prices_usd':{'100':'9.99','2000':'190'}}, editor)
        amounts = {tier['purchase_k']: tier['native_price_usd'] for tier in two['tiers']}
        self.assertEqual((amounts['100'], amounts['2000'], amounts['5000']), ('9.99','190','475'))
        self.assertEqual(one['native_payload']['more']['give'], source['more']['give'])
        self.assertEqual(one['tiers'][0], before['tiers'][0])

    def test_native_tier_prices_survive(self):
        result = read()
        self.assertEqual([v['native_price_usd'] for v in result['tiers']], ['8', '75', '145'])
        self.assertEqual(result['tiers'][1]['native_discount'], '98')
        self.assertEqual(result['tiers'][1]['promised_bonus_k'], '30')
        self.assertEqual(result['quotation_status'], 'native_semantics_not_evaluated')

    def test_high_tier_change_changes_curve_key(self):
        row = goods()
        row['more']['price'][2] = '144'
        self.assertNotEqual(curve_key(read()), curve_key(read(row)))

    def test_same_curve_new_capture_is_nochange(self):
        row, contract = goods(), deepcopy(CONTRACT)
        row.update(checked_at='new', updated_at='new')
        contract['checked_at'] = 'new'
        self.assertEqual(curve_key(read()), curve_key(read(row, contract)))

    def test_existing_noneditable_server_metadata_does_not_change_key(self):
        row = goods()
        row.update(stat_sales=300, _capture_label='new', unavailable=None)
        self.assertEqual(curve_key(read()), curve_key(read(row)))
        self.assertEqual(read(row)['native_payload']['stat_sales'], 300)

    def test_nonprice_fields_unchanged_and_copy_isolated(self):
        row = goods()
        result = read(row)
        self.assertEqual(result['native_payload'], row)
        result['native_payload']['more']['hot'][0] = 1
        self.assertEqual(row['more']['hot'][0], 0)

    def test_json_more_and_decimal_format_same_key(self):
        row = goods()
        row['more']['price'][0] = '8.00'
        row['unit_price'] = '.0800'
        row['more'] = json.dumps(row['more'])
        self.assertEqual(curve_key(read()), curve_key(read(row)))
        self.assertIsInstance(read(row)['native_payload']['more'], str)

    def test_unknown_native_control_and_offer_version_change_key(self):
        row = goods()
        row['native_quantity_step'] = '0.5'
        self.assertNotEqual(curve_key(read()), curve_key(read(row)))
        contract = dict(CONTRACT, region_projection_version='v2')
        self.assertNotEqual(curve_key(read()), curve_key(read(contract=contract)))

    def test_decimal_reader_does_not_round_to_context_precision(self):
        row = goods()
        row['more']['price'][2] = '145.1234567890123456789012345678901'
        self.assertEqual(read(row)['tiers'][2]['native_price_usd'], row['more']['price'][2])

    def test_invalid_identity_arrays_and_numbers_rejected(self):
        cases = []
        row = goods(); row['site_id'] = 0; cases.append(row)
        row = goods(); row['more']['price'].pop(); cases.append(row)
        row = goods(); row['more']['gold'][1] = '100.0'; cases.append(row)
        for bad in ('NaN', 'Infinity', '-1', False, None):
            row = goods(); row['more']['price'][1] = bad; cases.append(row)
        for row in cases:
            with self.subTest(row=row), self.assertRaises(ValueError):
                read(row)


EDITOR_CONTRACT = dict(CONTRACT, editor_asset_sha256=EDITOR_ASSET_SHA256,
                       editor_handler_sha256=EDITOR_HANDLER_SHA256)


def catalogue():
    row = goods()
    row['unit_price'] = '0.1'
    row['more'] = dict(gold=[10, 50, 100, 800, 1000, 1500, 2000, 5000],
                       give=[0, 0, 0, 0, 30, 45, 60, 150],
                       discount=[100, 100, 100, 100, 95, 95, 90, 90],
                       price=[1, 5, 10, 80, 95, 142.5, 180, 450],
                       hot=[False] * 8, delivery_time=['2h'] * 8,
                       unknown_native_control={'x': [1]})
    return row


def compile_editor(anchors, row=None, contract=EDITOR_CONTRACT, **targets):
    return compile_curve(read(catalogue() if row is None else row, contract),
                         dict(anchor_prices_usd=anchors, **targets), contract)


class NativeEditorCompiler(unittest.TestCase):
    def test_small_segment_control_updates_below_100_and_preserves_large_tiers(self):
        row = catalogue()
        current = read(row, EDITOR_CONTRACT)
        compiled = compile_curve(current, {'anchor_prices_usd': {'100.0': '9'}}, EDITOR_CONTRACT)
        expected = deepcopy(row)
        expected['more']['discount'][:4] = [90] * 4
        expected['more']['price'][:4] = [.9, 4.5, 9, 72]
        self.assertEqual(compiled['native_payload'], expected)
        self.assertEqual(current['native_payload'], row)
        self.assertEqual(compiled['base_rate_usd_per_k'], '0.09')
        self.assertEqual(compiled['compilation_status'], 'EDITOR_CANDIDATE')
        self.assertEqual(compiled['quotation_status'], 'native_semantics_not_evaluated')
        self.assertIn('admin_save', compiled['unverified_domains'])
        self.assertIn('custom_quantity', compiled['unverified_domains'])
        self.assertEqual(compiled['discount_changes'][0],
                         dict(purchase_k='10', before='100', after='90', source='segment_anchor'))

    def test_high_tier_change_keeps_base_and_changes_curve_key(self):
        current = read(catalogue(), EDITOR_CONTRACT)
        compiled = compile_editor({1000: '96'})
        self.assertEqual(compiled['base_rate_usd_per_k'], '0.1')
        self.assertEqual(compiled['native_payload']['more']['price'],
                         [1, 5, 10, 80, 96, 144, 192, 480])
        self.assertNotEqual(curve_key(compiled), curve_key(current))

    def test_explicit_third_segment_and_low_to_high_application(self):
        row = catalogue()
        row['more'] = json.dumps(row['more'])
        compiled = compile_editor({2000: '184', 1000: '96', 100: '9'}, row=row)
        more = json.loads(compiled['native_payload']['more'])
        self.assertEqual(more['price'], [.9, 4.5, 9, 72, 96, 144, 184, 460])
        self.assertEqual(more['discount'], [90, 90, 90, 90, 96, 96, 92, 92])
        self.assertEqual(more['give'], [0, 0, 0, 0, 30, 45, 60, 150])

    def test_explicit_base_changes_unselected_discounts_to_keep_saved_prices(self):
        compiled = compile_editor({100: '11'}, unit_price_usd_per_k='0.125')
        self.assertEqual(compiled['native_payload']['more']['price'],
                         [1.1, 5.5, 11, 88, 95, 142.5, 180, 450])
        self.assertEqual(compiled['unit_price_usd_per_k'], '0.125')
        self.assertEqual(compiled['base_rate_usd_per_k'], '0.11')
        self.assertIn(dict(purchase_k='1000', before='95', after='76',
                           source='preserve_saved_tier_price'), compiled['discount_changes'])

    def test_binary64_tofixed_uses_the_exact_binary_value(self):
        row = catalogue()
        row['unit_price'] = '0.01005'
        compiled = compile_editor({100: '1.00', 1000: '10.05'}, row=row)
        # In JS (.01005 * 100).toFixed(2) is '1.00'.
        self.assertEqual(compiled['native_payload']['more']['price'][2], 1.0)
        # The inverse rounds to 99.50 and remains exactly at the requested cent.
        self.assertEqual(compiled['native_payload']['more']['discount'][2], 99.5)

    def test_saved_price_at_binary_rounding_edge_can_retain_100_percent(self):
        row = catalogue()
        row['unit_price'] = '0.01005'
        row['more']['price'][:4] = [.1, .5, 1, 8.04]
        compiled = compile_editor({1000: '10.05'}, row=row)
        self.assertEqual(compiled['native_payload']['more']['price'][:4], [.1, .5, 1, 8.04])
        self.assertEqual(compiled['native_payload']['more']['discount'][:4], [100] * 4)

    def test_native_rounding_must_express_exact_anchor(self):
        for price in ('95.001', '100.06'):
            with self.subTest(price=price):
                compiled = compile_editor({1000: price})
                self.assertEqual(compiled['compilation_status'], 'PROOF_INCOMPLETE')
                self.assertNotIn('native_payload', compiled)
        compiled = compile_editor({1000: '499.99'}, unit_price_usd_per_k='0.5')
        self.assertEqual(compiled['gaps'][0]['code'], 'editor_anchor_not_expressible')

    def test_unselected_native_price_drift_is_a_gap(self):
        row = catalogue()
        row['more']['price'][-1] = 449.99
        compiled = compile_editor({100: '9'}, row=row)
        self.assertEqual(compiled['compilation_status'], 'PROOF_INCOMPLETE')
        self.assertEqual(compiled['gaps'], [dict(code='editor_untouched_tier_not_expressible',
                                                purchase_k='5000', required_usd='449.99')])

    def test_restore_unselected_price_using_supported_equivalent_discount(self):
        row = catalogue()
        row['more']['discount'][4] = 95.0001
        compiled = compile_editor({100: '9'}, row=row)
        self.assertEqual(compiled['native_payload']['more']['price'][4], 95)
        self.assertIn(dict(purchase_k='1000', before='95.0001', after='95',
                           source='preserve_saved_tier_price'), compiled['discount_changes'])

    def test_compiler_requires_matching_editor_evidence_and_catalogue_order(self):
        mismatched = dict(EDITOR_CONTRACT, editor_handler_sha256='other')
        compiled = compile_editor({100: '9'}, contract=mismatched)
        self.assertEqual(compiled['gaps'][0]['code'], 'editor_contract_evidence_missing_or_mismatched')
        compiled = compile_curve(read(catalogue(), mismatched), {'anchor_prices_usd': {100: 9}},
                                 EDITOR_CONTRACT)
        self.assertEqual(compiled['gaps'][0]['code'], 'editor_contract_evidence_missing_or_mismatched')
        row = catalogue()
        row['more']['gold'][:2] = [50, 10]
        compiled = compile_editor({100: '9'}, row=row)
        self.assertEqual(compiled['gaps'][0]['code'], 'editor_native_order_not_ascending')

    def test_missing_native_anchor_reports_gap(self):
        row = catalogue()
        row['more']['gold'][2] = 101
        compiled = compile_editor({100: '9'}, row=row)
        self.assertEqual(compiled['gaps'], [dict(code='editor_segment_anchor_missing', anchor_k='100')])

    def test_empty_edit_retains_exact_saved_payload_and_key(self):
        row = catalogue()
        row['more']['price'][-1] = 449.99
        compiled = compile_editor({}, row=row)
        self.assertEqual(compiled['native_payload'], row)
        self.assertEqual(curve_key(compiled), curve_key(read(row, EDITOR_CONTRACT)))


class NativeCatalogueQuote(unittest.TestCase):
    def quote(self, curve=None, **context):
        row = read() if curve is None else curve
        return quote_native(row, dict({'purchase_k': '1000', 'multiplier': 1,
                                       'site_id': '266', 'currency': 'USD'}, **context))

    def test_exact_saved_tier_uses_native_price_without_reapplying_discount(self):
        row = goods()
        row['discount'] = '90'
        curve = read(row)
        curve['tiers'][1]['native_price_usd'] = '101'
        result = self.quote(curve, purchase_k=Decimal('1000.00'))
        self.assertEqual(result['catalogue_status'], 'saved_tier')
        self.assertEqual(result['regular_usd'], '75')
        self.assertEqual(result['purchase_k'], '1000')
        self.assertEqual(result['promised_bonus_k'], '30')
        self.assertEqual(result['promised_delivered_k'], '1030')
        self.assertEqual(result['native_tier_or_rule'], 'goods.more.price[1]')
        self.assertEqual(result['rounding_contract'], 'admin_saved_tier_amount_as_read')
        self.assertEqual(result['curve_key'], curve_key(curve))
        self.assertEqual(result['proof_status'], 'PROOF_INCOMPLETE')
        self.assertIsNone(result['net_receipt_usd'])
        self.assertIsNone(result['known_fee_usd'])
        self.assertIsNone(result['offer_version'])
        self.assertEqual(result['fee_status'], 'unknown')
        self.assertIn('offer_path_unverified', result['gaps'])

    def test_historical_promised_quantity_must_match_saved_tier(self):
        matched = self.quote(promised_bonus_k='30.0')
        self.assertEqual(matched['regular_usd'], '75')
        for bonus, gap in ((0, 'catalogue_bonus_mismatch'), (None, 'native_quote_bonus_invalid')):
            with self.subTest(bonus=bonus):
                result = self.quote(promised_bonus_k=bonus)
                self.assertEqual(result['catalogue_status'], 'unavailable')
                self.assertIn(gap, result['gaps'])
                self.assertIsNone(result['regular_usd'])

    def test_custom_amount_and_multiplier_do_not_fall_back_to_editor_arithmetic(self):
        for quantity in (1, 999, 1001, 1700, '1000.1'):
            with self.subTest(quantity=quantity):
                result = self.quote(purchase_k=quantity)
                self.assertEqual(result['gaps'], ['custom_quantity_unverified'])
                self.assertIsNone(result['regular_usd'])
                self.assertIsNone(result['promised_bonus_k'])
        result = self.quote(multiplier=2)
        self.assertEqual(result['gaps'], ['cart_multiplier_unverified'])
        self.assertIsNone(result['regular_usd'])
        self.assertIsNone(result['promised_delivered_k'])
        for multiplier in (0, True, '1', None):
            self.assertEqual(self.quote(multiplier=multiplier)['gaps'],
                             ['native_quote_multiplier_invalid'])

    def test_site_currency_and_region_scope_are_explicit(self):
        for context, gap in (({'site_id': 0}, 'catalogue_site_mismatch'),
                             ({'currency': 'GBP'}, 'currency_projection_unverified'),
                             ({'region_id': 10}, 'regional_projection_unverified')):
            with self.subTest(context=context):
                result = self.quote(**context)
                self.assertEqual(result['gaps'], [gap])
                self.assertIsNone(result['regular_usd'])
        row = goods()
        row['site_id'] = 0
        all_curve = read_curve(row, dict(IDENTITY, site_id=0), CONTRACT)
        self.assertEqual(self.quote(all_curve)['gaps'], ['catalogue_site_mismatch'])
        self.assertEqual(self.quote(all_curve, site_id=0)['catalogue_status'], 'saved_tier')

    def test_editor_candidate_stays_explicitly_distinct_after_reader_round_trip(self):
        candidate = compile_editor({1000: '96'})
        self.assertEqual(self.quote(candidate)['catalogue_status'], 'editor_candidate_tier')
        re_read = read_curve(candidate['native_payload'], candidate['identity'], candidate['native_contract'])
        result = self.quote(re_read)
        self.assertEqual(result['catalogue_status'], 'editor_candidate_tier')
        self.assertEqual(result['regular_usd'], '96')
        self.assertEqual(result['proof_status'], 'PROOF_INCOMPLETE')

    def test_promised_delivery_addition_does_not_truncate_reader_precision(self):
        row = goods()
        row['more']['give'][1] = '30.1234567890123456789012345678901234'
        with localcontext() as context:
            context.prec = 5
            result = self.quote(read(row))
        self.assertEqual(result['promised_delivered_k'], '1030.1234567890123456789012345678901234')


if __name__ == '__main__':
    unittest.main()
