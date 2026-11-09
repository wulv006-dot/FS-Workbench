from copy import deepcopy
import unittest
import json

from fs_mcp_connector.gallery import GalleryError, project_gallery_state
from fs_mcp_connector.backend import Backend
from fs_mcp_connector.catalog import Catalog, CatalogPermissionError, ValidationError
from fs_mcp_connector.portal import Principal


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            'config': {'revision': 3, 'settings': {'enabled': True, 'interval_minutes': 60,
                'margin_percent': '20', 'cny_per_usd': '7.12',
                'tiers': [{'label': 'tier', 'cost_cny': '123.45', 'coins_k': '100', 'bonus_min_k': '5', 'bonus_max_k': '5'}]},
                'source': {'file_name': 'business.xlsx', 'sheet': 'pricing', 'sha256': 'a'*64,
                           'imported_date': '2026-11-09', 'scope': 'all'}, 'actor': 'alice'},
            'latest': {'checked_at': '2026-11-09T01:00:00Z', 'scope': 'all', 'revision': 3,
                'rates': {'PS': {'package_usd': '12.34', 'base_k': '100', 'bonus_k': '5', 'usd_per_k': '0.1175238',
                    'sku_id': '42', 'checked_at': '2026-11-09T01:00:00Z', 'source': 'storefront', 'status': 'valid'}},
                'quote': {'prices': {'your': {'PS': '1.25'}, 'provided': {'PS': '2.50'}},
                    'details': [{'label': 'tier', 'service_usd': '1.25', 'platforms': {'PS': {'your': '1.25', 'provided': '2.50', 'coins_usd': '1.25'}}}],
                    'levels': '1-10', 'business_hash': 'b'*64},
                'targets': [{'package': 'your', 'platform': 'PS', 'product_id': 1, 'model_id': 2,
                    'site_id': 266, 'title': 'Gallery', 'levels': '1-10', 'prices': '1.25', 'hours': '1'}],
                'plan': [{'package': 'your', 'platform': 'PS', 'product_id': 1, 'before': '1.20',
                    'after': '1.25', 'hours': '1', 'protected_hash': 'c'*64, 'keyword_before': 'previous', 'changed': True}],
                'applied_at': None},
            'jobs': [{'id': 'a'*32, 'kind': 'collect', 'actor': 'alice', 'revision': 3, 'scope': 'all',
                'created_at': '2026-11-09T01:00:00Z', 'status': 'done', 'finished_at': '2026-11-09T01:00:01Z'}],
            'blocked': False, 'writer': True, 'server_time': '2026-11-09T01:00:02Z',
            'schedule': {'last_start_epoch': 1.5, 'last_start_at': '2026-11-09T01:00:00Z'},
        }

    def test_audited_business_state_is_preserved_without_recalculating(self):
        before=deepcopy(self.state)
        self.assertEqual(project_gallery_state(self.state),self.state)
        self.assertEqual(self.state,before)
        self.assertEqual(project_gallery_state(self.state)['latest']['rates']['PS']['usd_per_k'],'0.1175238')

    def test_unknown_config_job_logs_and_nested_credentials_are_excluded(self):
        self.state['config']['settings']['token']='private'
        self.state['config']['credentials']={'password':'private'}
        self.state['latest']['rates']['PS']['cookie']='private'
        self.state['latest']['quote']['details'][0]['platforms']['PS']['authorization']='private'
        self.state['jobs'][0].update(settings={'password':'private'},stdout='private',error='private',
            view=deepcopy(self.state['latest']),steps=[{**self.state['latest']['plan'][0],'status':'done','stderr':'private'}])
        result=project_gallery_state(self.state)
        self.assertNotIn('private',str(result))
        self.assertIn('view',result['jobs'][0])
        self.assertEqual(result['jobs'][0]['steps'][0]['status'],'done')

    def test_known_free_text_uses_original_document_redaction(self):
        self.state['config']['actor']='owner@example.test'
        self.state['latest']['targets'][0]['title']='https://host.test/?token=private-value'
        result=project_gallery_state(self.state)
        self.assertIn('owner@example.test',str(result))
        self.assertNotIn('private-value',str(result))

    def test_missing_fields_are_not_zero_filled_and_bad_shapes_raise(self):
        self.assertEqual(project_gallery_state({'latest': {}, 'blocked': None}),{'latest': {}, 'blocked': None})
        for value in ([], {'config': []}, {'jobs': {}}, {'latest': {'rates': {'PS': []}}},
                      {'latest': {'targets': [{'title': {'token':'private'}}]}}):
            with self.subTest(value=value),self.assertRaises(GalleryError):
                project_gallery_state(value)

    def test_registered_gateway_read_retains_user_and_rechecks_access(self):
        calls, allowed = [], [200]
        catalog = Catalog(lambda *_: allowed[0])
        def transport(*args):
            calls.append(args)
            return 200, json.dumps(self.state).encode()
        backend = Backend(catalog, 'https://fs.example', transport=transport)
        principal = Principal('alice', 'MMOEXP_AUTH=synthetic')
        self.assertEqual(backend.query(principal, 'gallery.state', {})['data'], self.state)
        self.assertEqual(calls[0][:2], ('GET', '/tools/fc27-gallery/api/state'))
        self.assertEqual(calls[0][2]['Cookie'], principal.session_cookie)
        with self.assertRaises(ValidationError):
            backend.query(principal, 'gallery.state', {'owner': 'admin'})
        allowed[0] = 403
        with self.assertRaises(CatalogPermissionError):
            backend.query(principal, 'gallery.state', {})
        self.assertEqual(len(calls), 1)


if __name__=='__main__':
    unittest.main()
