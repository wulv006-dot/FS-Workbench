"""Contracts for additional original FS reads, without production requests."""
import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from fs_mcp_connector.backend import Backend, BackendError
from fs_mcp_connector.catalog import Catalog, CatalogPermissionError, ValidationError, validate
from fs_mcp_connector.portal import Principal


class ExtendedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(lambda *_: 200)
        self.principal = Principal('alice', 'MMOEXP_AUTH=fixture')
        self.calls = []
        def transport(*args):
            self.calls.append(args)
            return 200, b'{"status":"partial","next_cursor":100,"complete":false}'
        self.backend = Backend(self.catalog, 'https://fs.example', transport=transport)

    def test_every_declared_source_exists_and_schema_is_closed(self):
        root = Path(__file__).resolve().parents[2]
        for row in self.catalog.operations.values():
            with self.subTest(operation=row['name']):
                self.assertFalse(row['input_schema']['additionalProperties'])
                self.assertFalse(set(row['fixed']) & set(row['input_schema']['properties']))
                self.assertEqual(set(row['path_parameters']), set(__import__('re').findall(r'\{([^}]+)\}', row['path'])))
                self.assertTrue(set(row['path_parameters']) <= set(row['input_schema']['required']))
                for source in row['provenance']['source'].split('; '):
                    self.assertTrue((root/source).is_file(), source)
                if row.get('adapter') == 'knowledge':
                    self.assertIn('knowledge_catalog.py', row['provenance']['source'])
                    self.assertEqual(row['permission_path'], '/dashboard/fs-home/brain/')
                else:
                    self.assertTrue(row['provenance']['route_config'].startswith('/etc/nginx/'))
                self.assertIn('not_verified', row['provenance']['mapping_status'])

    def test_unmapped_scope_stays_visible_and_none_is_claimed_complete(self):
        coverage = self.catalog.list(self.principal)['coverage']
        self.assertEqual(len(coverage), 36)
        self.assertTrue(all(row['status'].startswith(('partially_mapped', 'not_yet_mapped')) for row in coverage))
        for row in coverage:
            self.assertEqual(row['operations'], sum(op['module'] == row['module']
                for op in self.catalog.operations.values()))
        self.assertTrue(any(row['module'] == 'knowledge' and row['operations'] == 2 for row in coverage))
        self.assertTrue(all('verified' not in row['status'] or 'not_live_verified' in row['status'] for row in coverage))

    def test_google_reads_reuse_original_hosts_and_preserve_source_status(self):
        for operation, source in [('campaigns.ads', 'ads'), ('campaigns.ga4', 'ga4'), ('campaigns.gsc', 'gsc')]:
            with self.subTest(operation=operation):
                out = self.backend.query(self.principal, operation, {'from': '2026-10-01', 'to': '2026-10-07'})
                method, target, headers, body, limits = self.calls[-1]
                self.assertEqual(method, 'GET')
                self.assertEqual(urlsplit(target).path, '/dashboard/analytics/campaigns/analytics/api/google-traffic')
                self.assertEqual(parse_qs(urlsplit(target).query)['source'], [source])
                self.assertFalse(out['data']['complete'])
                self.assertEqual(limits['response_bytes'], 250000)
                self.assertNotIn('Authorization', headers)

    def test_original_pagination_limits_and_schema_reject_overrides(self):
        for name, argument, maximum in [('mlb.tasks', 'limit', 300), ('rpg.history', None, None),
                                         ('madden.activity', 'limit', 500), ('deployment.log', 'limit', 500)]:
            if argument is None:
                continue
            schema = self.catalog.operation(name)['input_schema']
            validate({argument: maximum}, schema)
            for value in (0, maximum+1, True, '1'):
                with self.subTest(operation=name, value=value), self.assertRaises(ValidationError):
                    validate({argument: value}, schema)
        for name in ('marketing.range', 'campaigns.ads', 'nba.read', 'coins.monitor'):
            with self.subTest(operation=name), self.assertRaises(ValidationError):
                validate({'url': 'https://other.example', 'owner': 'administrator'}, self.catalog.operation(name)['input_schema'])

    def test_record_ids_cannot_be_paths(self):
        cases = [('mlb.task', 'task_id'), ('coins.snapshots', 'record_id'), ('madden.audits', 'record_id'), ('rpg.history', 'item_key'), ('ops.job', 'job_id')]
        for operation, key in cases:
            for value in ('../secret', '/etc/private', 'https://host/x', 'x?owner=admin', 'x%2fsecret'):
                with self.subTest(operation=operation, value=value), self.assertRaises(ValidationError):
                    self.backend.query(self.principal, operation, {key: value})
        self.assertFalse(self.calls)

    def test_remote_ops_contract_uses_fixed_gateway_and_original_hex_id(self):
        record = 'a'*32
        self.backend.query(self.principal, 'ops.job', {'job_id': record})
        self.assertEqual(self.calls[-1][1], '/s/wulv/fc27-ops/api/jobs/'+record)
        self.assertEqual(self.catalog.operation('ops.job')['provenance']['deployed_source_sha256'],
                         '8b2ca1b97274dbc480da5afe8e2d2c15dd4cd6c16205e2935b1986d2630f8ebf')
        for invalid in ('A'*32, 'a'*31, 'a'*33):
            with self.subTest(record=invalid), self.assertRaises(ValidationError):
                self.backend.query(self.principal, 'ops.job', {'job_id': invalid})

    def test_remote_state_projections_are_fixed_and_leave_unknown_fields_unavailable(self):
        expected = {'sales.status': ['running', 'elapsed', 'generated_at', 'orders']}
        fixture = {'rows': [{'model_id': 1, 'target': '1.25'}], 'version': 'fixture', 'stale': True,
                   'writable': False, 'running': False, 'elapsed': 3, 'generated_at': None, 'orders': 12,
                   'config': {'cookie': 'private'}, 'log_tail': 'private log', 'detail': 'private detail'}
        self.backend.transport = lambda *_: (200, json.dumps(fixture).encode())
        for operation, fields in expected.items():
            with self.subTest(operation=operation):
                row = self.catalog.operation(operation)
                self.assertEqual(row['response_fields'], fields)
                self.assertEqual(row['input_schema']['properties'], {})
                result = self.backend.query(self.principal, operation, {})
                self.assertEqual(set(result['data']), set(fields))
                self.assertEqual(result['provenance']['response_fields'], fields)
                self.assertNotIn('private', json.dumps(result))
                with self.assertRaises(ValidationError):
                    self.backend.query(self.principal, operation, {'response_fields': ['config']})
        self.backend.transport = lambda *_: (200, b'[]')
        with self.assertRaises(BackendError):
            self.backend.query(self.principal, 'sales.status', {})

    def test_actual_template_and_tracking_request_contracts(self):
        report = self.catalog.operation('campaigns.report')['input_schema']
        for template in ('commerce', 'prediction', 'reward'):
            validate({'activity': 'all', 'from': '2026-10-01', 'to': '2026-10-02', 'template': template}, report)
        with self.assertRaises(ValidationError):
            validate({'activity': 'all', 'from': '2026-10-01', 'to': '2026-10-02', 'template': 'standard'}, report)
        self.backend.query(self.principal, 'customer_tracking.request', {'request_id': 'a'*32})
        query = parse_qs(urlsplit(self.calls[-1][1]).query)
        self.assertEqual(query['view'], ['request'])
        self.assertEqual(query['structure'], ['customer_tracking'])

    def test_no_credential_bootstrap_or_business_action_is_registered(self):
        forbidden = ('/api/bootstrap', '/api/agent-config', '/api/local/pull', '/api/center', '/api/config', '/api/collect', '/api/apply', '/api/token')
        for row in self.catalog.operations.values():
            with self.subTest(operation=row['name']):
                self.assertFalse(any(row['path'].endswith(path) for path in forbidden))
                self.assertNotEqual(row['name'], 'coins.activity')
                if row['name'] in ('customer_tracking.detail', 'customer_tracking.candidates'):
                    self.assertEqual(row['fixed']['stored_only'], '1')
                self.assertNotIn(row['name'], ('players.bootstrap', 'tasks.session'))
                self.assertNotIn(row['name'], ('conversations.material', 'conversations.material_result'))

    def test_hermes_report_reads_are_outside_current_data_scope(self):
        for view in ('list', 'detail', 'thread', 'actions', 'evidence', 'artifact'):
            with self.subTest(view=view), self.assertRaises(ValidationError) as caught:
                self.backend.query(self.principal, 'reports.'+view, {})
            self.assertEqual(caught.exception.code, 'unknown_operation')
        self.assertFalse(self.calls)

    def test_existing_static_documents_use_fixed_routes_and_table_projection(self):
        self.backend.transport = lambda *args: (200, b'<title>Historical FC26</title><table><tr><th>Item</th><th>Count</th></tr><tr><td>Fixture</td><td>3</td></tr></table><script>private</script>')
        for operation, path in [('docs.handbook', '/docs/'), ('odds.reference', '/s/wulv/fc-odds/')]:
            with self.subTest(operation=operation):
                value = self.backend.query(self.principal, operation, {})
                self.assertEqual(value['provenance']['path'], path)
                self.assertEqual(value['data']['blocks'][1], {'type': 'table_row', 'text': 'Fixture | 3'})
                self.assertNotIn('private', str(value))
                with self.assertRaises(ValidationError):
                    self.backend.query(self.principal, operation, {'path': '/private/'})

    def test_tracking_reads_force_stored_only_and_preserve_identity(self):
        def transport(*args):
            self.calls.append(args)
            return 200, b'{"stored_only":true,"refreshed":false,"complete":false,"items":[{"candidate_id":"fixture","email":"private@example.test","uid":42,"order_no":"order-123"}],"orders":[{"email":"private@example.test","uid":42,"order_no":"order-123"}]}'
        self.backend.transport = transport
        for view, arguments in [('candidates', {'day': '2026-11-08'}), ('detail', {'id': 'a'*32})]:
            value = self.backend.query(self.principal, 'customer_tracking.'+view, arguments)
            params = parse_qs(urlsplit(self.calls[-1][1]).query)
            self.assertEqual(params['stored_only'], ['1'])
            self.assertEqual(params['view'], [view])
            self.assertFalse(value['data']['refreshed'])
            self.assertFalse(value['data']['complete'])
            rows = value['data']['items' if view == 'candidates' else 'orders']
            self.assertEqual(rows[0]['email'], 'private@example.test')
            self.assertEqual(rows[0]['uid'], 42)
            self.assertEqual(rows[0]['order_no'], 'order-123')
            with self.assertRaises(ValidationError):
                self.backend.query(self.principal, 'customer_tracking.'+view, {**arguments, 'stored_only': '0'})

    def test_order_facts_uses_original_route_and_preserves_contract_metadata(self):
        payload = dict(status='partial', totals={'orders':3,'procurement_gross_cny':None},
            channels=[{'channel':'unknown','orders':3}], coverage={'unlinked_admin_rows':1},
            revisions={'attribution':{'publication_id':'uw_fixed','data_revision':'2460'},
                       'cost':{'source_revision':'cost-r2','period':{'start':'2026-11-10'},'order_cost_complete':False}},
            requested_scope={'site_id':'266'}, effective_scope={'site_id':'266'}, readonly=True,
            snapshot_id='snap', dimensions={'country':[], 'device':[]}, order_profit_source='Order原生利润',
            trend=[{'day':'2026-11-10','order_profit_rate':None}], breakdown={'denominator_orders':3})
        def transport(*args):
            self.calls.append(args)
            return 200,json.dumps(dict(payload,aggregate_csv='unneeded', detail_csv='private',
                 orders=[{'order_no':'private'}])).encode()
        self.backend.transport=transport
        args=dict(start='2026-11-10',end='2026-11-11',site_id='266',gid='1327',channel='pending_classification',
                  status='valid',country='US',payment='PayPal',project='分销',code='fixture-code',
                  coupon_template='7',coupon_batch='fixture-batch',q='fixture')
        value=self.backend.query(self.principal,'channels.facts',args)
        self.assertEqual(value['data'],payload)
        self.assertEqual(urlsplit(self.calls[-1][1]).path,'/dashboard/channel-effects/data.json')
        self.assertEqual(parse_qs(urlsplit(self.calls[-1][1]).query),
            {k:[v] for k,v in dict(args,mode='order-facts').items()})
        for extra in ({'mode':'profit'},{'complete_cost_orders':'all'},{'customer_email':'a@example.test'},
                      {'site_id':'0'},{'channel':'google'},{'source_revision':'invented'},
                      {'detail_page':'1'},{'detail_export':'1'},{'snapshot_id':'snap'},
                      {'coupon_template':'invalid'},{'status':'paid'},{'q':'a@example.test'}):
            with self.subTest(extra=extra),self.assertRaises(ValidationError):
                self.backend.query(self.principal,'channels.facts',{**args,**extra})

    def test_order_facts_uses_the_original_channel_grant_before_upstream(self):
        denied=Catalog(lambda *_:403)
        connector=Backend(denied,'https://fs.example',transport=self.backend.transport)
        with self.assertRaises(CatalogPermissionError) as caught:
            connector.query(self.principal,'channels.facts',dict(start='2026-11-10',end='2026-11-11'))
        self.assertEqual(caught.exception.status_code,403)
        self.assertEqual(self.calls,[])

    def test_summary_country_minute_and_order_facts_pending_are_not_dropped(self):
        query=dict(profile='FC27',start='2026-11-10 09:01',end='2026-11-10 09:31',grain='minute',country_code='US')
        self.backend.query(self.principal,'business.summary',query)
        self.assertEqual(parse_qs(urlsplit(self.calls[-1][1]).query)['country_code'],['US'])
        with self.assertRaises(ValidationError):
            self.backend.query(self.principal,'business.summary',{**query,'country_code':'us'})
        self.backend.transport=lambda *args:(202,b'{"status":"pending","retryAfter":3}')
        value=self.backend.query(self.principal,'channels.facts',dict(start='2026-11-10',end='2026-11-11'))
        self.assertEqual(value['status_code'],202);self.assertEqual(value['data']['status'],'pending')

    def test_hermes_conversations_are_outside_current_data_scope(self):
        for view in ('list', 'detail', 'files', 'pricing_review', 'material_metadata'):
            with self.subTest(view=view), self.assertRaises(ValidationError) as caught:
                self.backend.query(self.principal, 'conversations.'+view, {'conversation_id': 'a'*32})
            self.assertEqual(caught.exception.code, 'unknown_operation')
        self.assertFalse(self.calls)


if __name__ == '__main__':
    unittest.main()
