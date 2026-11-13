"""Exercise the existing FC preview route and the exact read-only Goods call."""
import ast
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit


SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3 import api, runtime
from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL
from fc_pricing_v3.ledger import Ledger
import fc_shared_admin


SNAPSHOT_ID = '00000000-0000-4000-8000-000000000088'
SNAPSHOT_TIME = '2026-11-12T12:00:00+00:00'
READ_TIME = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def preview_request(**fields):
    return dict(write_protocol=CURVE_WRITE_PROTOCOL, platform='PS', **fields)


def handler_post(path, payload, *, actor='wulv', origin='https://fs.local'):
    # Use the real Handler with the installed dependencies unrelated to this
    # route omitted, just as the existing cloud-handler fixtures do.
    tree = ast.parse((SOURCE / 'fc27_cloud_api.py').read_text(encoding='utf-8'))
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Handler')
    namespace = dict(BaseHTTPRequestHandler=object, WRITERS={'wulv'}, re=re, json=json, sqlite3=sqlite3,
                     QueueBusy=type('QueueBusy', (Exception,), {}), urlsplit=urlsplit)
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(SOURCE / 'fc27_cloud_api.py'), 'exec'), namespace)
    request = namespace['Handler']()
    encoded = json.dumps(payload).encode()
    request.path = '/pricing/v3/' + path
    request.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(encoded)),
                       'Host': 'fs.local', 'Origin': origin, 'X-Forwarded-Proto': 'https',
                       'X-Authenticated-User': actor}
    request.rfile = BytesIO(encoded)
    request.respond = Mock()
    request.do_POST()
    request.respond.assert_called_once()
    return request.respond.call_args.args


class CurvePreviewV6(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Path(directory.name)
        self.db = Ledger(self.store / 'control.sqlite3')
        self.snapshot = dict(snapshot_id=SNAPSHOT_ID, origin='live_collector', mode='production',
                             created_at=SNAPSHOT_TIME, evidence={'run_id': SNAPSHOT_ID,
                                                               'storefront': {'rows': {'PS': {'sku_id': '163329311'}}}})
        self.db.put('pricing_snapshots', SNAPSHOT_ID, self.snapshot)
        self.row = dict(id=163329311, mid=41217957, gid=1327, cid=9623, site_id=266, aid=21587,
                        title='coins', unit='K', status=1, unit_price='0.1', private_field='not in response',
                        more=dict(price=['10.00', '94.00'], gold=[100, 1000], give=[5, 25],
                                  discount=[100, 94], delivery_time=['1', '1'], hot=[0, 0]))
        self.manager = Mock(token=None)
        self.manager.request.return_value = (200, json.dumps(dict(code=1, data=dict(row=self.row))).encode())
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.object(api, 'STORE', self.store))
        patches.enter_context(patch.object(api, 'ledger', side_effect=AssertionError('writable ledger unavailable')))
        patches.enter_context(patch.object(runtime, 'clock', return_value=READ_TIME))
        patches.enter_context(patch.object(runtime, 'verify_quote', side_effect=AssertionError('legacy verifier invoked')))
        patches.enter_context(patch.object(fc_shared_admin, 'SessionManager', return_value=self.manager))

    def database_contents(self):
        with closing(self.db.connect()) as conn:
            return list(conn.iterdump())

    def test_existing_http_preview_reads_exact_saved_tiers_and_exposes_missing_proof(self):
        before = self.database_contents()
        status, response = handler_post('preview', preview_request(snapshot_id=SNAPSHOT_ID))
        self.assertEqual(status, 202)
        self.assertEqual(response['snapshot_id'], SNAPSHOT_ID)
        self.assertEqual(response['snapshot_captured_at'], SNAPSHOT_TIME)
        self.assertEqual(response['platform'], 'PS')
        self.assertEqual(response['status'], 'PROOF_INCOMPLETE')
        self.assertFalse(response['execution_authorized'])
        self.assertFalse(response['write_performed'])
        self.assertIsNone(response['decision']['selected'])
        self.assertCountEqual(response['decision']['gaps'], [
            'customer_checkout_unverified', 'offer_path_unverified', 'necessary_fee_unverified',
            'validation_domain_unverified', 'ordinary_delivery_cost_unverified', 'planning_baskets_unverified',
            'adopted_reference_curve_unavailable', 'comparison_episode_unavailable',
        ])
        current = response['current_catalogue']
        self.assertEqual(current['status'], 'saved_tier')
        self.assertEqual(current['captured_at'], READ_TIME.isoformat())
        self.assertRegex(current['response_sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(current['tiers'][1]['native_price_usd'], '94')
        self.assertEqual(current['quote_100k']['regular_usd'], '10')
        self.assertEqual(current['quote_100k']['promised_delivered_k'], '105')
        self.assertIsNone(current['quote_100k']['net_receipt_usd'])
        self.assertEqual(current['quote_100k']['proof_status'], 'PROOF_INCOMPLETE')
        self.assertNotIn('private_field', json.dumps(response))
        self.manager.ensure.assert_not_called()
        self.manager.request.assert_called_once_with('/admin/goods.Goods/edit?id=163329311', data=None, token=None)
        self.assertEqual(self.database_contents(), before)

    def test_unverified_readback_retains_explicit_platform_gap(self):
        self.row['aid'] = 21589
        self.manager.request.return_value = (200, json.dumps(dict(code=1, data=dict(row=self.row))).encode())
        result = api.post('preview', preview_request(), 'wulv')
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertEqual(result['snapshot_id'], SNAPSHOT_ID)
        self.assertIsNone(result['current_catalogue'])
        self.assertIn('current_catalogue_identity_mismatch', result['decision']['gaps'])
        self.assertIsNone(result['decision']['selected'])

    def test_rejects_client_proof_invalid_platform_and_other_routes_before_state_access(self):
        for route, payload, error in (
                ('preview', preview_request(evidence={'status': 'PROVEN'}), 'pricing_curve_preview_fields_invalid'),
                ('preview', dict(preview_request(), platform='console'), 'pricing_curve_preview_fields_invalid'),
                ('preview', dict(preview_request(), write_protocol='unknown'), 'pricing_curve_preview_fields_invalid'),
                ('preview', preview_request(snapshot_id=None), 'pricing_curve_preview_snapshot_id_invalid'),
                ('execute', preview_request(), 'pricing_curve_preview_route_required'),
                ('manual-previews', preview_request(), 'pricing_curve_preview_route_required'),
                ('evaluate', preview_request(), 'pricing_curve_preview_route_required')):
            with self.subTest(route=route, error=error):
                with patch.object(api.sqlite3, 'connect', side_effect=AssertionError('database accessed')):
                    self.assertEqual(handler_post(route, payload), (400, {'error': error}))
        self.manager.request.assert_not_called()

    def test_unknown_snapshot_and_wrong_goods_scope_do_not_trigger_a_catalogue_read(self):
        missing_id = '00000000-0000-4000-8000-000000000099'
        missing = api.post('preview', preview_request(snapshot_id=missing_id), 'wulv')
        self.assertEqual(missing['snapshot_id'], missing_id)
        self.assertEqual(missing['status'], 'PROOF_INCOMPLETE')
        self.assertIn('pricing_snapshot_unavailable', missing['decision']['gaps'])
        self.snapshot['evidence']['storefront']['rows']['PS']['sku_id'] = '163329277'
        self.db.put('pricing_snapshots', SNAPSHOT_ID, self.snapshot)
        wrong_goods = api.post('preview', preview_request(), 'wulv')
        self.assertEqual(wrong_goods['status'], 'PROOF_INCOMPLETE')
        self.assertIn('pricing_snapshot_goods_scope_unverified', wrong_goods['decision']['gaps'])
        self.assertIsNone(wrong_goods['current_catalogue'])
        self.manager.request.assert_not_called()

    def test_transport_failure_returns_proof_gap_without_using_a_fallback(self):
        self.manager.request.side_effect = TimeoutError()
        status, result = handler_post('preview', preview_request())
        self.assertEqual(status, 202)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIn('current_catalogue_readback_unavailable', result['decision']['gaps'])
        self.assertIsNone(result['current_catalogue'])
        self.manager.request.assert_called_once()

    def test_original_preview_retains_original_evaluator_and_response(self):
        evaluation = {'status': 'READY', 'selected': {'action': {'base_prices': {'PS': '10'}}}}
        with patch.object(api, 'ledger', return_value=self.db), patch.object(api, 'evaluate', return_value=evaluation) as evaluate:
            status, result = handler_post('preview', {'mode': 'daily'})
        evaluate.assert_called_once_with(self.snapshot['evidence'], 'daily', plan=None)
        self.assertEqual((status, result), (202, dict(results={'daily': evaluation}, execution_authorized=False,
                                                    write_performed=False, snapshot_id=SNAPSHOT_ID)))
        self.manager.request.assert_not_called()

    def test_original_authentication_and_same_origin_policy_remain_in_use(self):
        status, response = handler_post('preview', preview_request(), actor='observer')
        self.assertEqual((status, response), (403, {'error': 'write_role_required'}))
        status, response = handler_post('preview', preview_request(), origin='http://fs.local')
        self.assertEqual((status, response), (403, {'error': 'pricing_https_origin_required'}))
        self.manager.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
