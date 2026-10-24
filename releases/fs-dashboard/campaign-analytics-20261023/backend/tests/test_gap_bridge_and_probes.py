import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign_backend.catalog as catalog
from bridge import handle
from campaign_backend.adapters import AdminRead
from campaign_backend.core import ContractError
from campaign_backend.services import BackendServices
from probe_money_shape import observe
from probe_schema import schema


class Session:
    def __init__(self, rows):
        self.rows, self.calls = iter(rows), []

    def get_admin(self, route, **params):
        self.calls.append((route, params))
        rows = next(self.rows)
        return 200, dict(code=1, data=dict(list=rows, total=len(rows)))

    def close(self):
        pass


class BridgeAndProbeTests(unittest.TestCase):
    def test_benefit_catalog_filters_exact_or_global_scope_before_response(self):
        session = Session([[dict(id=1, status=1, site_id=0), dict(id=2, status=0, site_id=266)],
                           [dict(id=3, status=1, site_id=266)]])
        response = handle(dict(action='benefits_read', site_id='266'), lambda: AdminRead(session))
        self.assertEqual([row['scope_status'] for row in response['coupons']], ['global', 'exact_site'])
        self.assertEqual(session.calls[0][1]['search[0][val]'], '0,266')
        self.assertEqual(response['scope_status'], 'exact_or_global_scope_verified')
        session = Session([[dict(id=1, status=1, site_id=999)]])
        with self.assertRaisesRegex(ContractError, 'UPSTREAM_SCOPE_MISMATCH'):
            handle(dict(action='benefits_read', site_id='266'), lambda: AdminRead(session))

    def test_catalog_mapping_read_fixed_server_path_and_delayed_c_function(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog-mapping.json'
            path.write_text('{"schema_version":1}', encoding='utf-8')
            with patch.dict(os.environ, {'CAMPAIGN_CATALOG_MAPPING_PATH': str(path)}), patch.object(
                    catalog, 'read_reference_mapping', create=True, return_value={'safe': True}) as read:
                self.assertEqual(handle(dict(action='catalog_mapping_read', site_id='266', reference_key='abc')), {'safe': True})
                read.assert_called_once_with({'schema_version': 1}, 'abc')
                with self.assertRaises(ContractError):
                    handle(dict(action='catalog_mapping_read', site_id='266', path='/untrusted'))

    def test_analysis_summary_before_any_capture_does_not_create_persistent_state(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'not-yet-created'
            result = handle(dict(action='analysis_summary', site_id='266'), services=BackendServices(state, {}))
            self.assertEqual(result['status'], 'blocked')
            self.assertIsNone(result['verified_at'])
            self.assertEqual(result['totals'], [])
            self.assertFalse(state.exists())

    def test_probe_outputs_never_include_customer_order_or_money_values(self):
        rows = [dict(email='PRIVATE_CUSTOMER', order_no='PRIVATE_ORDER', currency_code='GBP',
            amount='12345.67', pay_money='GBP 22.11', pay_money_format='GBP22.11',
            pay_money_format2=['GBP', '22.11'], return_money='12.34', status=1,
            nested={'private@example.com': 'PRIVATE_DYNAMIC'})]
        first, second = observe(rows), schema(rows)
        encoded = json.dumps([first, second])
        for secret in ('PRIVATE', '12345.67', '22.11', '12.34', 'private@example.com'):
            self.assertNotIn(secret, encoded)
        self.assertEqual(first['sample_rows'], 1)
        self.assertEqual(first['decimal_parseable']['pay_money_format2[1]'], 1)
        self.assertEqual(first['pay_money_format2_currency_matches'], 1)
        self.assertIn('nested.<dynamic-key>', second['schema'])


if __name__ == '__main__':
    unittest.main()
