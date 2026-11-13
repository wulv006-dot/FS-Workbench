from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_curve_price_windows_v6 import curve
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.price_curve import curve_key, read_curve


def operation(ident='op', high='75'):
    actual = curve(high)
    target = deepcopy(actual)
    target['native_payload'].update(id=163329309, site_id=0)
    target['identity'].update(id='163329309', site_id='0')
    target = read_curve(target['native_payload'], target['identity'], target['native_contract'])
    mapping = dict(target_curve_key=curve_key(target), actual_site266_curve_key=curve_key(actual),
                   basis='full_prices_and_tier_specs_readback')
    action = dict(base_prices={'PS': '10'}, region_coefficients={}, curves={'PS': target})
    result = dict(operation_id=ident, platform='PS', target_curve_key=curve_key(target),
                  actual_site266_curve=actual, actual_site266_curve_key=curve_key(actual),
                  catalog=dict(status='confirmed'),
                  propagation=dict(status='confirmed', curve_mapping=mapping),
                  projection=dict(status='not_required'))
    return dict(operation_id=ident, resources=['base:PS'], bundle=dict(write_protocol='fc27_curve_v6',
                assignment_id=ident, action=action, affected_platforms=['PS'], mutable_resources=['base:PS']),
                readback=dict(status='CONFIRMED', execution_id=ident, write_protocol='fc27_curve_v6',
                              curve_results={'PS': result}))


class CurveWindowReceipts(unittest.TestCase):
    def test_freezes_primary_readback_and_preserves_all_decision_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'test.db')
            op = operation()
            with patch('fc_pricing_v3.ledger.clock', return_value=datetime(2026, 10, 26, tzinfo=timezone.utc)), db.transaction() as conn:
                db.record_price_window(op, conn)
            window = db.get('actual_price_windows', 'op')
            actual = window['action']['curves']['PS']
            self.assertEqual(actual['identity']['site_id'], '266')
            self.assertEqual(window['decision_curve_keys']['PS'], curve_key(op['bundle']['action']['curves']['PS']))
            self.assertNotEqual(window['decision_curve_keys']['PS'], curve_key(actual))
            self.assertEqual(window['curve_confirmations']['PS']['operation_id'], 'op')
            from test_curve_price_windows_v6 import fixture
            from fc_pricing_v3.business_source import bind_price_windows
            now, order, _ = fixture()
            result = bind_price_windows([order], [window], now)
            outcome = result['actual_outcomes'][0]
            self.assertEqual(outcome['curve_key'], curve_key(actual))
            self.assertEqual(outcome['decision_curve_key'], window['decision_curve_keys']['PS'])

    def test_incomplete_or_wrong_mapping_does_not_create_or_close_window(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'test.db')
            first = operation('first')
            with db.transaction() as conn:
                db.record_price_window(first, conn)
            for change in ('missing', 'projection', 'target', 'mapping', 'operation'):
                with self.subTest(change=change):
                    bad = operation('bad', '78')
                    result = bad['readback']['curve_results']['PS']
                    if change == 'missing': bad.pop('readback')
                    elif change == 'projection': result['projection']['status'] = 'unverified'
                    elif change == 'target': result['target_curve_key'] = 'other'
                    elif change == 'mapping': result['propagation']['curve_mapping']['actual_site266_curve_key'] = 'other'
                    else: bad['readback']['execution_id'] = 'other'
                    with self.assertRaises(ValueError), db.transaction() as conn:
                        db.record_price_window(bad, conn)
                    self.assertIsNone(db.get('actual_price_windows', 'bad'))
                    self.assertNotIn('closed_at', db.get('actual_price_windows', 'first'))

    def test_same_scalar_different_curve_opens_new_window(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'test.db')
            for op in (operation('first'), operation('later', '78')):
                with db.transaction() as conn:
                    db.record_price_window(op, conn, no_change=True)
            self.assertIsNotNone(db.get('actual_price_windows', 'later'))
            self.assertIn('closed_at', db.get('actual_price_windows', 'first'))

    def test_full_same_curve_continues_original_window(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'test.db')
            for op in (operation('first'), operation('later')):
                with db.transaction() as conn:
                    db.record_price_window(op, conn, no_change=True)
            self.assertIsNone(db.get('actual_price_windows', 'later'))
            self.assertEqual(db.get('actual_price_windows', 'first')['continuations'][0]['operation_id'], 'later')


if __name__ == '__main__':
    unittest.main()
