"""Bounded display of already-authorized business results, without changing their values."""
from copy import deepcopy
import json
import unittest

from fs_mcp_connector.backend import BackendError
from fs_mcp_connector.catalog import ValidationError
from fs_mcp_connector.response_view import present, MAX_BYTES


class ResponseViewTests(unittest.TestCase):
    def result(self, data):
        return dict(operation='fixture.read', status_code=206, data=data,
                    provenance={'source': 'fixture', 'method': 'GET'})

    def test_small_response_is_preserved_exactly(self):
        result = self.result({'complete': False, 'coverage': {'received': 2}, 'rows': [1, 2]})
        self.assertIs(present(result), result)

    def test_large_nested_data_is_indexed_and_original_scope_is_retained(self):
        result = self.result({'profile': {'supplement': {'rows': [{'id': i, 'value': 'x' * 50} for i in range(744)]},
                                          'primary': {'value': 'p' * 10000}},
                              'coverage': {'complete': False}, 'query': {'start': '2026-10-01'},
                              'sources': {'Admin': 'live_non_snapshot'}, 'archive': {'id': 'fixture'}})
        before = deepcopy(result)
        indexed = present(result)
        self.assertEqual(indexed['status_code'], 206)
        self.assertEqual(indexed['provenance'], result['provenance'])
        self.assertEqual(indexed['response_view']['kind'], 'index')
        self.assertFalse(indexed['response_view']['value_complete'])
        self.assertIn('/profile', [row['data_path'] for row in indexed['data']['fields']])
        self.assertEqual(indexed['data_context']['']['coverage'], {'complete': False})
        self.assertEqual(indexed['data_context']['']['query'], result['data']['query'])
        self.assertEqual(indexed['data_context']['']['archive'], result['data']['archive'])
        nested = present(result, data_path='/profile/supplement')
        self.assertEqual(nested['data']['fields'][0]['data_path'], '/profile/supplement/rows')
        primary = present(result, data_path='/profile/primary')
        self.assertEqual(primary['data'], result['data']['profile']['primary'])
        self.assertEqual(result, before)
        for value in (indexed, nested, primary):
            self.assertLessEqual(len(json.dumps(value, ensure_ascii=False).encode()), MAX_BYTES)

    def test_array_pages_reassemble_all_744_rows_without_changing_business_coverage(self):
        rows = [{'order_no': 'ORDER-' + str(i), 'email': 'fixture@example.test', 'amount': i} for i in range(744)]
        result = self.result({'rows': rows, 'complete': False, 'next_cursor': 'upstream-cursor'})
        collected, offset = [], 0
        while offset is not None:
            page = present(result, data_path='/rows', offset=offset)
            self.assertEqual(page['response_view']['kind'], 'page')
            self.assertEqual(page['response_view']['total'], 744)
            self.assertEqual(page['data_context']['']['complete'], False)
            self.assertEqual(page['data_context']['']['next_cursor'], 'upstream-cursor')
            self.assertLessEqual(len(page['data']), 20)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), MAX_BYTES)
            collected.extend(page['data'])
            offset = page['response_view']['next_offset']
        self.assertEqual(collected, rows)
        self.assertEqual(present(result, data_path='/rows', offset=20, limit=3)['data'], rows[20:23])

    def test_oversized_array_item_can_be_expanded_by_pointer(self):
        result = self.result([{'nested': {'rows': ['x' * 100 for _ in range(200)]}}, {'id': 2}])
        indexed = present(result)
        self.assertEqual(indexed['response_view']['kind'], 'index')
        self.assertEqual(indexed['data']['fields'][0]['data_path'], '/0')
        page = present(result, data_path='/0/nested/rows')
        self.assertEqual(len(page['data']), 20)

    def test_channel_facts_selection_preserves_effective_scope_and_basis(self):
        context = {'requested_scope': {'site': 'all'}, 'effective_scope': {'site': '266'},
                   'coverage_scope': {'site': '266'}, 'source_timezone': 'Asia/Shanghai',
                   'time_basis': 'Admin paytime', 'order_profit_source': 'Order发货交易日',
                   'revisions': {'attribution': 'fixture'}, 'captured_at': '2026-11-17T00:00:00Z'}
        result = self.result({**context, 'channels': [{'sales': 123}]})
        selected = present(result, data_path='/channels')
        self.assertEqual(selected['data_context'][''], context)
        self.assertEqual(selected['data'], [{'sales': 123}])

    def test_sales_snapshot_continuation_is_distinct_from_display_paging(self):
        context = {'snapshot_sha256': 'f' * 64, 'next_offset': 100, 'complete': False,
                   'coverage': 'published_snapshot', 'meta': {'start': '2026-11-01'}}
        snapshot = self.result({**context, 'rows': [{'amount_usd': 5}]})
        page = present(snapshot, data_path='/rows')
        self.assertEqual(page['data_context'][''], context)
        self.assertTrue(page['response_view']['value_complete'])
        self.assertIsNone(page['response_view']['next_offset'])

    def test_live_order_rows_preserve_original_site_game_scope(self):
        context = {'scope': {'site_id': '266', 'game_id': '1'}, 'semantics': 'live_non_snapshot',
                   'period': {'start': '2026-11-01', 'end_exclusive': '2026-11-02'},
                   'next_cursor': 'original-cursor'}
        selected = present(self.result({**context, 'data': [{'order_id': '100'}]}), data_path='/data')
        self.assertEqual(selected['data_context'][''], context)

    def test_json_pointer_escaping_and_false_null_values_remain_exact(self):
        result = self.result({'a/b': {'~key': [False, None, 0, '']}})
        for index, expected in enumerate((False, None, 0, '')):
            value = present(result, data_path='/a~1b/~0key/' + str(index))['data']
            self.assertEqual(value, expected)
            self.assertIs(type(value), type(expected))
        with self.assertRaises(ValidationError):
            present(result, data_path='/missing')

    def test_invalid_pointer_and_array_ranges_do_not_become_empty_data(self):
        result = self.result({'rows': [1, 2], 'empty': [], 'scalar': 3})
        for path in ('rows', '/rows/-', '/rows/-1', '/rows/01', '/rows/2', '/bad~2escape'):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                present(result, data_path=path)
        for options in ({'offset': -1}, {'offset': 2}, {'offset': True}, {'limit': 0}, {'limit': 21}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                present(result, data_path='/rows', **options)
        with self.assertRaises(ValidationError):
            present(result, data_path='/scalar', offset=0)
        self.assertEqual(present(result, data_path='/empty', offset=0)['data'], [])

    def test_page_size_adapts_without_losing_rows_and_large_context_stays_readable(self):
        rows = [{'id': index, 'text': 'x' * 1500} for index in range(30)]
        result = self.result({'rows': rows, 'coverage': {'detail': 'c' * 4000}})
        collected, offset = [], 0
        while offset is not None:
            page = present(result, data_path='/rows', offset=offset)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), MAX_BYTES)
            self.assertIn('/coverage', [row['data_path'] for row in page['data_context_index']])
            collected.extend(page['data'])
            offset = page['response_view']['next_offset']
        self.assertEqual(collected, rows)
        self.assertEqual(present(result, data_path='/coverage')['data'], result['data']['coverage'])

    def test_oversized_scalar_is_explicit_error_not_truncated(self):
        result = self.result({'text': '文' * MAX_BYTES, 'next_cursor': 'original-cursor'})
        with self.assertRaises(BackendError) as raised:
            present(result, data_path='/text')
        self.assertEqual(raised.exception.code, 'response_too_large')
        self.assertEqual(raised.exception.display_result['data_context']['']['next_cursor'], 'original-cursor')
        self.assertEqual(len(result['data']['text']), MAX_BYTES)

    def test_selected_metrics_preserve_conflicting_ancestor_scopes_without_overwriting_status(self):
        result = self.result({'query': {'site': 'www.mmoexp.com'}, 'status': 'root-status',
                              'profile': {'supplement': {'normalisedScope': 'all-websites',
                                  'filters': {'site': ''}, 'currency': 'USD', 'system': 'Admin',
                                  'status': 'supplement-status', 'metrics': {'sales': 123}},
                                  'shipping': {'normalisedScope': 'www.mmoexp.com'}}})
        selected = present(result, data_path='/profile/supplement/metrics')
        self.assertEqual(selected['data'], {'sales': 123})
        self.assertEqual(selected['data_context']['']['query']['site'], 'www.mmoexp.com')
        self.assertEqual(selected['data_context']['']['status'], 'root-status')
        ancestor = selected['data_context']['/profile/supplement']
        self.assertEqual(ancestor['normalisedScope'], 'all-websites')
        self.assertEqual(ancestor['filters']['site'], '')
        self.assertEqual(ancestor['system'], 'Admin')
        self.assertEqual(ancestor['status'], 'supplement-status')


if __name__ == '__main__':
    unittest.main()
