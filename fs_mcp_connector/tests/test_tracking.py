from copy import deepcopy
import json
import unittest

from fs_mcp_connector.tracking import project, TrackingError


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.order = {'candidate_id': 'b'*32, 'order_no': 'FIXTURE-ORDER-1',
            'email': 'fixture@example.test', 'uid': 0, 'site_id': 266, 'gid': 1327,
            'paid_at': '2026-11-09T01:00:00Z', 'pay_status': 1, 'order_usd': '600.10',
            'discount_usd': None, 'payment': {'amount': '500', 'currency': 'EUR'},
            'es_identity': {'buyer_id': 'fixture-buyer', 'status': 'verified', 'source': 'ES'}}

    def test_authorized_customer_identifiers_and_original_amounts_survive_all_views(self):
        detail = {'status': 'active', 'tracking_id': 'a'*32, 'email': 'fixture@example.test',
            'uid': 0, 'orders': [self.order], 'history_coverage': {'complete': False,
                'source_total': 20, 'received': 1, 'pages': [{'page': 1, 'rows': 1, 'source_total': 20}]},
            'stored_only': True, 'refreshed': False, 'first_paid_at': None,
            'stage_markers': [{'days': 7, 'date': None, 'reached': None}]}
        before = deepcopy(detail)
        self.assertEqual(project(detail, 'detail'), detail)
        self.assertEqual(detail, before)
        candidate = {'status': 'partial', 'items': [self.order], 'day': '2026-11-09',
            'coverage': {'es': {'file_set_complete': False, 'read_files': 1},
                         'criteria': {'identity_verified': 1, 'excluded': {'criteria_not_met': 2}}}}
        self.assertEqual(project(candidate, 'candidates'), candidate)
        tracked = {'status': 'available', 'items': [{key: detail[key] for key in ('tracking_id', 'email', 'uid')}]}
        self.assertEqual(project(tracked, 'tracked'), tracked)

    def test_credentials_and_unknown_admin_objects_are_removed_at_every_level(self):
        row = deepcopy(self.order)
        row.update(cookie='credential', admin_raw={'authorization': 'credential'})
        row['payment']['token'] = 'credential'
        row['es_identity']['password'] = 'credential'
        result = project({'status': 'available', 'items': [row],
            'coverage': {'complete': False, 'token': 'credential'}, 'csrf': 'credential'}, 'candidates')
        self.assertNotIn('credential', json.dumps(result))
        self.assertEqual(result['items'][0]['email'], self.order['email'])
        self.assertEqual(result['items'][0]['uid'], 0)

    def test_pending_failed_unavailable_and_null_coverage_remain_distinct(self):
        for status in ('pending', 'failed', 'unavailable', 'partial'):
            value = {'status': status, 'items': [], 'reason': 'scan_source_unavailable',
                'retry_after': None, 'retryable': False, 'stored_only': True, 'refreshed': False}
            self.assertEqual(project(value, 'candidates'), value)
        self.assertEqual(project({'history_coverage': None, 'orders': [self.order]}, 'detail'),
                         {'history_coverage': None, 'orders': [self.order]})

    def test_config_and_original_request_recovery_are_fixed_business_projection(self):
        config = {'profile': 'FC27', 'product_types': ['Coins', 'Items'], 'version': 1,
                  'customer_flags': ['new', 'old'], 'enabled': True}
        self.assertEqual(project(config, 'config'), config)
        receipt = {'status': 'available', 'action': 'scan', 'result': {'status': 'pending',
            'request_id': 'a'*32, 'permission_recovery': {'actor': 'admin',
                'prior_failure': {'state': 'failed', 'reason': 'es_export_permission_denied'},
                'proof': {'receipt_sha256': 'b'*64, 'query': {'profile': 'ALL',
                    'start': '2026-11-08', 'end': '2026-11-08'}}}}}
        self.assertEqual(project(receipt, 'request'), receipt)
        receipt['result']['permission_recovery']['proof']['token'] = 'credential'
        self.assertNotIn('credential', json.dumps(project(receipt, 'request')))
        pool = {'status': 'available', 'action': 'generate_pool', 'result': {
            'request_id': 'a'*32, 'created_at': '2026-11-09T01:00:00Z', 'state': 'completed',
            'conversation_id': 'b'*32, 'turn_id': 'c'*32, 'artifact_id': 'd'*32, 'customer_count': 3}}
        self.assertEqual(project(pool, 'request'), pool)

    def test_known_strings_remove_credentials_without_removing_email(self):
        value = project({'reason': 'fixture@example.test https://host.test/?token=credential'}, 'request')
        self.assertIn('fixture@example.test', value['reason'])
        self.assertNotIn('credential', value['reason'])

    def test_unknown_views_and_bad_nested_shapes_fail_without_empty_success(self):
        for value, view in (({}, 'unknown'), ([], 'detail'), ({'orders': {}}, 'detail'),
                            ({'items': [{'uid': {'token': 'x'}}]}, 'tracked'),
                            ({'coverage': 'broken'}, 'candidates')):
            with self.assertRaises(TrackingError): project(value, view)


if __name__ == '__main__':
    unittest.main()
