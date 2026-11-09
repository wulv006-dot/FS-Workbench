from copy import deepcopy
import json
import unittest

from fs_mcp_connector.backend import Backend, BackendError
from fs_mcp_connector.catalog import Catalog, CatalogPermissionError, ValidationError
from fs_mcp_connector.g2g import project
from fs_mcp_connector.portal import Principal


class G2GTests(unittest.TestCase):
    def setUp(self):
        self.allowed, self.calls = 200, []
        self.response = {}
        self.catalog = Catalog(lambda *args: self.allowed)
        def transport(*args):
            self.calls.append(args)
            return 200, json.dumps(self.response, ensure_ascii=False).encode()
        self.backend = Backend(self.catalog, 'https://fs.example', transport=transport)
        self.principal = Principal('alice', 'MMOEXP_AUTH=synthetic')

    def query(self, operation='g2g.state', arguments=None):
        return self.backend.query(self.principal, operation, arguments or {})

    def test_fixed_state_preserves_business_and_credential_health_without_exporting_credentials(self):
        self.response = dict(now=123, token=dict(ok=True, remaining=600),
            config={'利润率': .2, '汇率USDCNY': 7, 'shop': 'business-shop'},
            rows=[{'offer_id': 'offer-1', '当前价': 10, '目标价': 11, '放行': True}],
            summary={'下调': 1}, cost_at=100, cost_zones=80, cheapold_at=101, cheapold_zones=81,
            offers_at=102, plan_at=103, job={'running': False, 'phase': '完成', 'ok': True, 'summary': {'rows': 1}},
            logs=['[12:00:00] token 可用，剩余 600s'],
            writes=[dict(offer_id='offer-1', old_price=10, new_price=11, api_ok=1, verified=1, readback=11)],
            unapproved={'access_token': 'must-not-leak'})
        original = deepcopy(self.response)
        result = self.query()
        value = result['data']
        self.assertEqual(value['credential_status'], {'ok': True, 'remaining': 600})
        for key in ('rows', 'config', 'summary', 'writes', 'job', 'cost_at', 'plan_at'):
            self.assertEqual(value[key], self.response[key])
        self.assertNotIn('token', value)
        self.assertNotIn('must-not-leak', json.dumps(result))
        self.assertEqual(self.response, original)
        method, target, _, body, _ = self.calls[0]
        self.assertEqual((method, target, body), ('GET', '/g2g/api/state', None))

    def test_job_logs_keep_known_events_and_mark_untrusted_exception_details_withheld(self):
        self.response = dict(running=False, phase='失败(token)', ok=False, started=100, finished=120,
            summary=None, logs=['[12:00:00] 开始采集（只出建议单，不改任何价）',
                '[12:00:01] × 采集失败：bare-unrecognized-credential',
                '[12:00:02] Authorization=Bearer abcdefghijklmnopqrstuvwxyz0123456789'])
        value = self.query('g2g.job')['data']
        self.assertFalse(value['ok'])
        self.assertEqual(value['phase'], '失败(token)')
        self.assertEqual(len(value['logs']), 3)
        self.assertIn('开始采集', value['logs'][0])
        self.assertNotIn('bare-unrecognized-credential', json.dumps(value))
        self.assertNotIn('abcdefghijklmnopqrstuvwxyz0123456789', json.dumps(value))
        self.assertEqual(value['log_coverage']['withheld'], 2)
        self.assertFalse(value['log_coverage']['complete'])
        self.assertEqual(self.calls[0][1], '/g2g/api/job')

    def test_write_error_details_are_not_mistaken_for_verified_business_fields(self):
        self.response = dict(token={'ok': False, 'error': 'token 已过期（12 秒前）'}, logs=[],
            rows=[{'offer_id': 'offer-1', '说明': 'support owner@example.test'}],
            writes=[dict(api_ok=0, verified=0, old_price=10, new_price=11, detail='raw-opaque-sensitive-body')])
        value = self.query()['data']
        self.assertEqual(value['credential_status'], {'ok': False, 'reason': 'expired'})
        self.assertEqual(value['writes'][0]['verified'], 0)
        self.assertTrue(value['writes'][0]['detail_withheld'])
        self.assertNotIn('raw-opaque-sensitive-body', json.dumps(value))
        self.assertIn('owner@example.test', json.dumps(value))

    def test_actual_credential_shape_or_new_nested_secret_is_rejected(self):
        for token in ['opaque-secret', {'ok': True, 'remaining': 'opaque-secret'},
                      {'ok': True, 'remaining': 20, 'access_token': 'opaque-secret'}]:
            self.response = {'token': token, 'logs': []}
            with self.subTest(token=token), self.assertRaises(BackendError):
                self.query()
        self.response = {'token': {'ok': True, 'remaining': 20}, 'rows': [{'access_token': 'opaque-secret'}], 'logs': []}
        with self.assertRaises(BackendError):
            self.query()

    def test_fixed_input_and_current_permission_remain_required(self):
        with self.assertRaises(ValidationError):
            self.query(arguments={'url': 'https://other.example/api/execute'})
        self.allowed = 403
        with self.assertRaises(CatalogPermissionError):
            self.query()
        self.assertEqual(self.calls, [])

    def test_coverage_does_not_claim_csv_or_full_history(self):
        coverage = next(row for row in self.catalog.document['coverage'] if row['module'] == 'g2g')
        self.assertEqual(coverage['operations'], 2)
        self.assertEqual(coverage['status'], 'partially_mapped_not_live_verified')
        self.assertIn('CSV', coverage['reason'])
        self.assertIn('history', coverage['reason'])


if __name__ == '__main__':
    unittest.main()
