"""Synthetic native catalogue preservation; no live pricing or save claims."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3.price_curve import (
    EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, compile_curve, curve_key, read_curve,
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


if __name__ == '__main__':
    unittest.main()
