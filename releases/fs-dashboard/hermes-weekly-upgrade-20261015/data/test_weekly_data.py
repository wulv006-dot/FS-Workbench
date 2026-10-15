from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INTEGRATION = ROOT/'hermes-fs-research-integration-20261015'
if not INTEGRATION.exists(): INTEGRATION = ROOT/'hermes_fs_research_integration_20261015'
MARKET = ROOT/'hermes-market-sources-20261015'
if not MARKET.exists(): MARKET = ROOT/'hermes_market_sources_20261015'
BASE = MARKET/'deps' if (MARKET/'deps').exists() else ROOT/'hermes-fc-pilot-20261013'
if not BASE.exists(): BASE = ROOT/'hermes_fc_pilot_20261013'
sys.path[:0] = [str(HERE), str(ROOT), str(INTEGRATION/'source'), str(MARKET/'source'), str(BASE)]
from marketing_snapshot import checked_query, projection, MarketingReader
from research import ResearchBook, tool_schemas, RESEARCH_NAMES
from fs_evidence import SourcePins

QUERY = {'profile': 'FC27', 'start': '2026-10-05', 'end': '2026-10-11'}
STAMP = '2026-10-14T16:59:00+00:00'


def fixture():
    current = {'start': QUERY['start'], 'end': QUERY['end'], 'sources': {}, 'adsAccounts': []}
    for source, resource, tz in [('ga4', '541418940', 'Asia/Shanghai'), ('gsc', 'sc-domain:mmoexp.com', 'America/Los_Angeles')]:
        m = {'sessions': '12', 'newUsers': '5'} if source == 'ga4' else {'clicks': '5', 'impressions': '15'}
        current['sources'][source] = {'resource': resource, 'timezone': tz, 'metrics': m,
            'status': {'status': 'failed', 'collected_at': STAMP, 'retained_previous': True, 'quality': {'active_metric_restrictions': ['private-untrusted-value']}},
            'coverage': {'returned_days': 7, 'requested_days': 7, 'complete_dates': True, 'missing_dates': []},
            'breakdowns': {'country': {'rows': [{'dimensions': {'country': 'United States', 'query': 'PRIVATE-SEARCH'}, 'metrics': m}], 'row_coverage': '0.5', 'returned_dimension_rows': 8,
                'status': {'status': 'success', 'collected_at': STAMP}}}}
    current['adsAccounts'] = [{'customerId': '1430398974', 'brand': 'mmoexp', 'currency': 'USD', 'timezone': 'Asia/Hong_Kong',
                              'metrics': {'cost': '12.45', 'conversions': '0.5'}, 'campaigns': [{'customerId': '1430398974', 'campaignId': '123', 'campaignName': 'Search US', 'channelType': 'SEARCH', 'currency': 'USD', 'timezone': 'Asia/Hong_Kong', 'metrics': {'cost': '12.45'}, 'raw_note': 'PRIVATE-CAMPAIGN'}], 'status': {'status': 'success'}},
                             {'customerId': '8154986819', 'brand': 'rsorder', 'metrics': {'cost': '9999'}}]
    return {'schemaVersion': 1, 'isMock': False, 'data_generated_at': STAMP,
            'raw_note': 'PRIVATE-CUSTOMER', 'details': {'schemaVersion': 1, 'isMock': False, 'periods': [current]}}


class WeeklyDataTests(unittest.TestCase):
    def project(self, model=None, query=None):
        return projection(model or fixture(), query or QUERY, 'a'*64)

    def test_exact_period_only_no_zero_fallback(self):
        value = self.project(query={**QUERY, 'start': '2026-10-01'})
        self.assertEqual(value['status'], 'not_available')
        self.assertEqual(value['sources'], {})
        self.assertEqual(value['available_periods'], [{'start': QUERY['start'], 'end': QUERY['end']}])

    def test_projection_strips_private_and_cross_brand_fields(self):
        result = self.project()
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('9999', json.dumps(result))
        self.assertEqual(result['ads_accounts'][0]['metrics']['conversions'], '0.5')
        self.assertEqual(result['ads_geography']['status'], 'not_available')
        self.assertIn('whole website', result['scope'])

    def test_missing_metric_and_country_not_zero(self):
        model = fixture()
        model['details']['periods'][0]['sources']['ga4']['breakdowns'] = {}
        result = self.project(model)
        self.assertIsNone(result['sources']['ga4']['metrics']['ecommercePurchases'])
        self.assertEqual(result['sources']['ga4']['country']['rows'], [])
        self.assertIsNone(result['sources']['ga4']['country']['row_coverage'])

    def test_retained_failure_and_privacy_flags_survive(self):
        value = self.project()['sources']['ga4']
        self.assertTrue(value['status']['retained_previous'])
        self.assertEqual(value['status']['status'], 'failed')
        self.assertTrue(value['status']['quality']['active_metric_restrictions'])
        self.assertEqual(value['coverage']['returned_days'], 7)

    def test_bad_scope_duplicate_and_input_denied(self):
        for change in ({'path': '/etc/secret'}, {'profile': 'FC26'}, {'end': '2026-09-30'}):
            with self.assertRaises((ValueError, TypeError)):
                checked_query({**QUERY, **change})
        model = fixture()
        model['details']['periods'].append(deepcopy(model['details']['periods'][0]))
        with self.assertRaises(ValueError): self.project(model)
        model = fixture()
        model['details']['periods'][0]['sources']['ga4']['resource'] = 'wrong'
        with self.assertRaises(ValueError): self.project(model)

    def test_country_contact_and_nonfinite_metric_rejected(self):
        model = fixture()
        row = model['details']['periods'][0]['sources']['ga4']['breakdowns']['country']['rows'][0]
        row['dimensions']['country'] = 'person@example.com'
        model['details']['periods'][0]['sources']['ga4']['metrics']['sessions'] = 'NaN'
        value = self.project(model)['sources']['ga4']
        self.assertIsNone(value['metrics']['sessions'])
        self.assertEqual(value['country']['rows'], [])
        self.assertEqual(value['country']['rejected_rows'], 1)

    def test_reader_fails_closed_and_never_accepts_model_path(self):
        with patch('marketing_snapshot.PUBLISHED', HERE/'NO-SUCH-SNAPSHOT'):
            self.assertEqual(MarketingReader()(QUERY)['status'], 'not_available')
        with self.assertRaises(ValueError): MarketingReader()({**QUERY, 'path': '/etc/passwd'})

    def test_tool_schema_catalog_and_first_reply_freeze(self):
        calls = []
        def reader(args): calls.append(args); return self.project()
        data = {'snapshot_id': 'fc-detail-synthetic', 'as_of': STAMP, 'coverage': {'period': QUERY}, 'orders': [], 'backlog': []}
        book = ResearchBook(data, {}, QUERY, marketing=SourcePins().wrap(reader, 'marketing'))
        a = book.call('fc.query_marketing_snapshot', QUERY)
        b = book.call('fc.query_marketing_snapshot', QUERY)
        self.assertEqual(a['evidence_id'], b['evidence_id'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(book.call('fc.get_data_catalog', {})['data']['marketing_snapshot']['status'], 'on_demand')
        self.assertEqual(len(tool_schemas()), len(RESEARCH_NAMES))
        schema = tool_schemas()[-1]['function']['parameters']
        self.assertFalse(schema['additionalProperties'])

    def test_existing_daily_sales_and_current_pool_use_distinct_populations(self):
        row = {'paid_at': '2026-10-06T12:00:00+08:00', 'site_group': 'main', 'amount_cents': 1234,
               'backlog': True, 'terminal': False, 'status': '问题单'}
        data = {'snapshot_id': 'fc-detail-synthetic', 'as_of': STAMP,
                'coverage': {'period': {'start': '2026-09-28', 'end': '2026-10-12'}, 'paid_complete': True, 'missing_days': [], 'backlog_status': 'available'},
                'orders': [row], 'backlog': [row, {**row, 'paid_at': '2026-09-01T12:00:00+08:00', 'amount_cents': 100}]}
        book = ResearchBook(data, {}, QUERY)
        sales = book.call('fc.query_business', {'start': QUERY['start'], 'end': QUERY['end'], 'group_by': ['day'], 'filters': {}, 'page': 1})['data']
        pool = book.call('fc.query_queue', {'group_by': [], 'filters': {}, 'page': 1})['data']
        self.assertEqual(sales['total']['orders'], 1)
        self.assertEqual(sales['groups'][0]['revenue_usd'], '12.34')
        self.assertEqual(pool['total']['orders'], 2)
        self.assertEqual(pool['total']['revenue_usd'], '13.34')
        self.assertEqual(pool['state_basis'], 'current_at_capture_not_historical_day_end')

    def test_problem_projection_never_returns_remark_content(self):
        from fs_evidence import problem_projection
        result = problem_projection({'contract': 'fc-order-problem-clues-v1', 'status': 'available', 'sampled': 1,
            'categories': {'credentials': 1}, 'samples': [{'ref': 'RAW-ID', 'platform': 'PS', 'category': 'credentials', 'content': 'PRIVATE-PASSWORD', 'requires_latest_state_review': True}]}, 'scope')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('RAW-ID', json.dumps(result))
        self.assertTrue(result['samples'][0]['requires_latest_state_review'])

    def test_factory_wires_source_and_checks_live_off_before_cache(self):
        from fs_evidence import build_book
        data = {'snapshot_id': 'fc-detail-synthetic', 'as_of': STAMP, 'coverage': {'period': QUERY}, 'orders': [], 'backlog': []}
        detail = SimpleNamespace(config={'enabled': True}, pool=None)
        history = SimpleNamespace(index={}, read=lambda q: {})
        readers = SimpleNamespace(admin_read=lambda q: None, order_read=lambda *a: None)
        with patch('fs_evidence.source_capture', return_value=(data, {})), patch('fs_evidence.load_bundle', return_value={}), \
             patch('fs_evidence.ReportHistory', return_value=history), patch('marketing_snapshot.MarketingReader', return_value=lambda q: self.project()), \
             patch.dict(sys.modules, {'admin_order_capabilities_20261014.fs_reader': readers}), \
             patch('admin_order_capabilities_20261014.provider.CapabilityProvider'):
            book = build_book(detail, None, lambda q: (200, {}), lambda: {}, QUERY['start'], QUERY['end'], '.', 'owner')
            self.assertEqual(book.call('fc.query_marketing_snapshot', QUERY)['data']['status'], 'partial')
            detail.config['enabled'] = False
            self.assertEqual(book.call('fc.query_marketing_snapshot', QUERY)['data']['reason'], 'fc_detail_disabled')

    def test_transport_wire_allowlist_reaches_registered_tool(self):
        from proxy_gateway import ScopedTools, schemas
        from runs_contract import WIRE_TOOLS
        data = {'snapshot_id': 'fc-detail-synthetic', 'as_of': STAMP, 'coverage': {'period': QUERY}, 'orders': [], 'backlog': []}
        book = ResearchBook(data, {}, QUERY, marketing=lambda q: self.project())
        tasks = SimpleNamespace(get=lambda *a: {'state': 'RUNNING', 'lease': 'synthetic', 'spec': {'snapshot_id': book.capture_id}})
        tool = ScopedTools(tasks, book, lambda: 0)
        result = tool.call('owner', 'task', 'synthetic', 'mcp__fcro__fc_query_marketing_snapshot', QUERY)
        self.assertEqual(result['data']['data']['contract'], 'fc-marketing-read-v1')
        self.assertIn('mcp__fcro__fc_query_marketing_snapshot', WIRE_TOOLS)
        self.assertEqual({s['function']['name'] for s in schemas()}, set(WIRE_TOOLS))

    def test_existing_source_medium_and_campaigns_are_labels_not_attribution(self):
        model = fixture()
        model['details']['periods'][0]['sources']['ga4']['breakdowns']['source_medium'] = {'rows': [
            {'dimensions': {'sessionSourceMedium': 'google / organic', 'raw_query': 'PRIVATE'}, 'metrics': {'sessions': '5', 'share': '0.4'}},
            {'dimensions': {'sessionSourceMedium': 'email@example.com'}, 'metrics': {'sessions': '7'}}]}
        result = self.project(model)
        table = result['sources']['ga4']['source_medium']
        self.assertEqual(table['rows'][0]['source_medium'], 'google / organic')
        self.assertEqual(table['rows'][0]['share'], '0.4')
        self.assertEqual(table['rejected_rows'], 1)
        campaign = result['ads_accounts'][0]['campaigns']['rows'][0]
        self.assertEqual(campaign['campaign_name'], 'Search US')
        self.assertIsNone(campaign['status'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_ads_metrics_none_and_cross_currency_campaign_not_zero(self):
        model = fixture()
        account = model['details']['periods'][0]['adsAccounts'][0]
        account['metrics'] = None
        account['campaigns'][0]['currency'] = 'CNY'
        result = self.project(model)['ads_accounts'][0]
        self.assertIsNone(result['metrics'])
        self.assertEqual(result['campaigns']['rows'], [])
        self.assertEqual(result['campaigns']['rejected_rows'], 1)

    def test_readonly_acceptance_output_has_only_counts_dates_and_totals(self):
        from check_marketing_readonly import summary
        value = summary(self.project())
        encoded = json.dumps(value)
        for label in ('Search US', 'United States', 'PRIVATE', 'campaign_name'):
            self.assertNotIn(label, encoded)
        self.assertEqual(value['ads_accounts'][0]['campaign_rows'], 1)
        self.assertEqual(value['sources']['ga4']['country']['projected_rows'], 1)
        self.assertEqual(value['ads_accounts'][0]['metrics']['cost'], '12.45')
        self.assertFalse(summary({'status': 'not_available'})['ads_geography_available'])


if __name__ == '__main__': unittest.main()
