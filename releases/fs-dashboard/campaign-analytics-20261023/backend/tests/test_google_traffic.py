import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('google_traffic', Path(__file__).resolve().parents[1] / 'google_traffic.py')
google = importlib.util.module_from_spec(spec)
spec.loader.exec_module(google)


class Reader:
    def __init__(self, denied=False):
        self.calls = []
        self.denied = denied

    def request(self, source, url, body):
        self.calls.append((source, url, body))
        if self.denied:
            raise ValueError('HTTP_403')
        if source == 'ga4':
            return {'dimensionHeaders': body['dimensions'], 'metricHeaders': body['metrics'], 'metadata': {'timeZone': 'Asia/Shanghai'}}
        if source == 'ads' and 'FROM customer' in body['query']:
            return {'results': [{'customer': {'id': '1430398974', 'timeZone': 'Asia/Hong_Kong', 'currencyCode': 'USD'}}]}
        return {}


class GoogleTrafficTests(unittest.TestCase):
    def test_scope_filters_empty_and_native_timezones(self):
        for source, count in [('ga4', 7), ('gsc', 6), ('ads', 2)]:
            reader = Reader()
            value = google.collect({'source': source, 'from': '2026-10-26', 'to': '2026-10-30'}, reader)
            self.assertEqual(value['status'], 'no_rows')
            self.assertEqual(len(reader.calls), count)
            self.assertNotIn('metrics', value, 'no records are not a fabricated zero total')
            for _, _, body in reader.calls:
                if not (source == 'gsc' and 'dimensionFilterGroups' not in body or source == 'ads' and 'FROM customer' in body['query']):
                    self.assertIn('seasonal', str(body))
                if source == 'ga4':
                    self.assertIn('www.mmoexp.com', str(body))
                if source == 'ads':
                    self.assertNotIn('pageSize', body)
                    if 'FROM landing_page_view' in body['query']:
                        self.assertIn('LIMIT 1001', body['query'])

    def test_carnival_reports_filter_its_exact_page_on_all_three_sources(self):
        for source in ('ga4', 'gsc', 'ads'):
            with self.subTest(source=source):
                reader = Reader()
                value = google.collect({'activity': 'mmoexp-carnival', 'source': source,
                                        'from': '2026-11-19', 'to': '2026-11-19'}, reader)
                self.assertEqual(value['page'], 'https://www.mmoexp.com/events/Carnival.html')
                filters = [str(body) for _, _, body in reader.calls
                           if source == 'ga4' or 'dimensionFilterGroups' in body
                           or 'FROM landing_page_view' in body.get('query', '')]
                self.assertTrue(filters)
                self.assertTrue(all('/events/Carnival[.]html' in f and 'seasonal' not in f for f in filters))

    def test_permission_failure_stops_source_and_validation_precedes_io(self):
        reader = Reader(True)
        value = google.collect({'source': 'gsc', 'from': '2026-10-26', 'to': '2026-10-30'}, reader)
        self.assertEqual(value['status'], 'unavailable')
        self.assertEqual(value['failures'], {'total': 'HTTP_403'})
        self.assertEqual(len(reader.calls), 1)
        for change in [{'source': 'other'}, {'from': '2026-02-30'}, {'to': '2026-12-01'}, {'from': '2026-11-01'}, {'path': '/other'}]:
            request = {'source': 'gsc', 'from': '2026-10-26', 'to': '2026-10-30', **change}
            with self.assertRaises((ValueError, TypeError)):
                google.validate(request)

    def test_totals_not_reconstructed_from_top_rows_and_quality_retained(self):
        class Data(Reader):
            def request(self, source, url, body):
                if source == 'gsc':
                    return {'rows': [{'keys': ['fixture'] if body['dimensions'] else [], 'clicks': 3, 'impressions': 10, 'ctr': .3, 'position': 2}]}
                return {'dimensionHeaders': body['dimensions'], 'metricHeaders': body['metrics'], 'rowCount': 100,
                        'rows': [{'dimensionValues': [{'value': 'fixture'} for _ in body['dimensions']], 'metricValues': [{'value': '2'} for _ in body['metrics']]}],
                        'metadata': {'subjectToThresholding': True, 'timeZone': 'Asia/Shanghai'}}
        value = google.collect({'source': 'ga4', 'from': '2026-10-26', 'to': '2026-10-30'}, Data())
        self.assertTrue(value['reports']['daily']['truncated'])
        self.assertTrue(value['reports']['daily']['quality']['subjectToThresholding'])
        value = google.collect({'source': 'gsc', 'from': '2026-10-26', 'to': '2026-10-30'}, Data())
        self.assertFalse(value['reports']['total']['topRowsOnly'])
        self.assertTrue(value['reports']['query']['topRowsOnly'])


if __name__ == '__main__':
    unittest.main()
