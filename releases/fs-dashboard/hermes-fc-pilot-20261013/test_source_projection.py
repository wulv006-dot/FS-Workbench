from copy import deepcopy
import unittest
from source_projection import project_capture


def capture():
    windows = []
    refs = []
    for name, start, end in [('target', '2026-10-05', '2026-10-11'), ('previous', '2026-09-28', '2026-10-04')]:
        windows.append({'key': name, 'start': start, 'end': end, 'status': 'available', 'complete_days': True,
                        'main': {'orders': 10, 'revenue_usd': 100.5},
                        'dimensions': {'platform': [{'key': 'PS', 'orders': 10, 'revenue_usd': 100.5,
                                                      'customer': 'MUST_NOT_LEAVE_FS'}]}})
        refs.append({'ref': name+'.main', 'snapshot_id': 'fc-detail-fixture', 'captured_at': '2026-10-13T12:00:00+00:00'})
    return {'project': 'FC27', 'currency': 'USD', 'plan': {'in_progress': False},
            'snapshot_id': 'fc-detail-fixture', 'generated_at': '2026-10-13T12:10:00+00:00',
            'windows': windows, 'evidence': refs, 'raw_orders': ['MUST_NOT_LEAVE_FS']}


class ProjectionTests(unittest.TestCase):
    def test_projection_excludes_raw_data_and_uses_capture_time(self):
        result = project_capture(capture())
        self.assertNotIn('MUST_NOT_LEAVE_FS', str(result.windows))
        self.assertEqual(result.windows['target']['as_of'], '2026-10-13T12:00:00+00:00')
        self.assertEqual(result.windows['target']['revenue_usd'], '100.50')
        self.assertEqual(result.windows['target']['order_reference']['status'], 'unavailable')

    def test_partial_unknown_dimension_is_disclosed_without_changing_total(self):
        source = capture()
        source['windows'][0]['dimensions']['platform'].append({'key': 'unknown', 'orders': 2, 'revenue_usd': 10})
        result = project_capture(source).windows['target']
        self.assertIn('partial_source', result['warnings'])
        self.assertEqual(result['orders'], 10)
        self.assertEqual(len(result['breakdown']['platform']), 1)

    def test_reference_estimate_remains_separate_from_admin(self):
        refs = {'target': {'period': {'start': '2026-10-05', 'end': '2026-10-11'},
                          'source_system': 'Order', 'scope': 'FC27/all-sites',
                          'reference_margin_pct': '10.00', 'cost_coverage_pct': None}}
        result = project_capture(capture(), refs).windows['target']
        self.assertEqual(result['order_reference']['estimated_profit_usd'], '10.05')
        self.assertIn('order_scope_differs', result['warnings'])
        refs['target']['period']['end'] = '2026-10-10'
        with self.assertRaisesRegex(ValueError, 'reference_period_or_scope'): project_capture(capture(), refs)

    def test_incomplete_and_mixed_capture_denied(self):
        for mutator in (lambda s:s['windows'][0].update(status='missing'),
                        lambda s:s['plan'].update(in_progress=True),
                        lambda s:s['evidence'][0].update(snapshot_id='other'),
                        lambda s:s['windows'][0]['main'].update(revenue_usd=None)):
            source = capture(); mutator(source)
            with self.assertRaises(ValueError): project_capture(source)


if __name__ == '__main__': unittest.main()
