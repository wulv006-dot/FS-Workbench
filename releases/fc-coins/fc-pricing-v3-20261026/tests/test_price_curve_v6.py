"""Synthetic native catalogue preservation; no live pricing or save claims."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3.price_curve import read_curve, curve_key


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


if __name__ == '__main__':
    unittest.main()
