import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import evolutions as e

MODEL = {'id': 1, 'gid': 1327, 'cid': 10399, 'title': 'Test evolution',
         'unit': '10000', 'status': 1, 'sku_switch': 0, 'attr_switch': 0}
PRODUCTS = [dict(MODEL, id=10+i, mid=1, aid=aid, sid=7645, site_id=0, top_cid=2,
                 price=1.49, unit_price=1.49, discount=100, num=1,
                 more={'extend': [{'key': 'zh_title', 'value': 'preserved'}]})
            for i, aid in enumerate(e.PLATFORMS)]
RATES = {'PS': '0.0987', 'XBOX': '0.0987', 'PC': '0.0819'}


class FakeBackend:
    def __init__(self):
        self.models = [copy.deepcopy(MODEL)]
        self.products = copy.deepcopy(PRODUCTS)
        self.writes = []
        self.unknown = False
        self.cache = 0

    def catalog(self):
        return copy.deepcopy(self.models), copy.deepcopy(self.products)

    def rates(self):
        return RATES.copy()

    def row(self, kind, identity):
        rows = self.models if kind == 'GoodsMould' else self.products
        return copy.deepcopy(next(r for r in rows if r['id'] == identity))

    def write(self, row, price):
        self.writes.append(row['id'])
        if self.unknown:
            raise TimeoutError()
        actual = next(r for r in self.products if r['id'] == row['id'])
        actual['price'] = float(price)
        actual['unit_price'] = float(e.Decimal(price)*100/e.Decimal(str(actual['discount'])))

    def clear_cache(self):
        self.cache += 1


class PricingTests(unittest.TestCase):
    def test_formula_and_rounding(self):
        self.assertEqual(e.target('10000', RATES['PS'], '1.1'), '1.09')
        self.assertEqual(e.target('10000', RATES['PC'], '1.1'), '0.90')
        self.assertEqual(e.target('25000', RATES['PS'], '1.1'), '2.71')
        self.assertEqual(e.target('20000', RATES['PC'], '1.1'), '1.80')
        self.assertEqual(e.target('10000', RATES['PS'], '1.1', '8.25'), '8.25')

    def test_reject_nonfinite_zero_negative(self):
        for value in ('NaN', 'Infinity', '-1', '0', '', None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                e.target(value, '0.1', '1.1')
        with self.assertRaises(ValueError):
            e.target('1', '.001', '1')

    def test_exact_scope(self):
        e.product_identity(PRODUCTS[0], MODEL)
        for key, value in [('mid', 99), ('gid', 1322), ('cid', 9627), ('site_id', 10),
                           ('aid', 99), ('sid', 99), ('title', 'Other'), ('sku_switch', 1), ('num', 2)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                e.product_identity(dict(PRODUCTS[0], **{key: value}), MODEL)

    def test_strict_boolean_cas_and_overrides(self):
        cfg = copy.deepcopy(e.DEFAULT)
        for body in ({'automatic': 'false'}, {'overrides': {'99': {}}}, {'premium': 'NaN'},
                     {'overrides': {'1': {'coins': '1.5'}}}, {'overrides': {'1': {'prices': {'PS': 0}}}}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                e.validate_config(cfg, dict(body, expected_revision=1), {'1'})
        with self.assertRaises(ValueError):
            e.validate_config(cfg, {'expected_revision': 0}, {'1'})
        out = e.validate_config(cfg, {'expected_revision': 1, 'overrides': {'1': {'coins': '25000', 'prices': {'PC': '3.19'}}}}, {'1'})
        self.assertEqual(out['overrides']['1']['prices']['PC'], '3.19')

    def test_incomplete_platforms_and_missing_coins(self):
        rows = e.plan([MODEL], PRODUCTS[:2], RATES, e.DEFAULT)
        self.assertTrue(all(r['error'] for r in rows))
        rows = e.plan([dict(MODEL, unit='')], PRODUCTS, RATES, e.DEFAULT)
        self.assertTrue(all(r['error'] for r in rows))

    def test_role_boundary(self):
        self.assertFalse(e.authorized({}))
        self.assertTrue(e.authorized({'X-Evo-User': 'member', 'X-Evo-Role': 'readonly'}))
        self.assertFalse(e.authorized({'X-Evo-User': 'member', 'X-Evo-Role': 'readonly'}, True))
        self.assertTrue(e.authorized({'X-Evo-User': 'wulv', 'X-Evo-Role': 'admin'}, True))

    def test_complete_payload_preserves_discount_and_content(self):
        backend = object.__new__(e.Backend)
        backend.admin = Mock()
        backend.admin.request.return_value = (200, b'{"code":1}')
        row = dict(PRODUCTS[0], discount=80)
        payload = backend.write(row, '1.09')
        self.assertEqual(payload['unit_price'], 1.3625)
        self.assertEqual(payload['price'], 1.09)
        for key in set(row) - {'price', 'unit_price'}:
            self.assertEqual(row[key], payload[key])
        backend.admin.request.assert_called_once()

    def test_rates_no_fallback_foreign_game_duplicate(self):
        backend = object.__new__(e.Backend)
        backend.price_reader = Mock()
        valid = [{'area': p, 'gid': 1322, 'b2c': v} for p, v in RATES.items()]
        for rows in [valid[:2], valid+[valid[0]], [dict(r, gid=922) for r in valid]]:
            backend.price_reader.fetch_rows.return_value = {'ok': True, 'rows': rows}
            with self.assertRaises(ValueError):
                backend.rates()

    def test_cache_retry_only_explicit_rate_limit(self):
        backend = object.__new__(e.Backend)
        backend.admin = Mock()
        backend.admin.request.side_effect = [(200, json.dumps({'code':0,'msg':'操作过于频繁'})), (200, json.dumps({'code':1}))]
        with patch.object(e.time, 'sleep') as sleep:
            backend.clear_cache()
        sleep.assert_called_once_with(31)
        self.assertEqual(backend.admin.request.call_count, 2)
        backend.admin.request.reset_mock()
        backend.admin.request.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            backend.clear_cache()
        self.assertEqual(backend.admin.request.call_count, 1)


class AdminSessionTests(unittest.TestCase):
    def backend(self, *, status=200, payload=None):
        backend=object.__new__(e.Backend)
        backend.admin=Mock()
        backend.admin.ensure.return_value=True
        backend.admin.request.return_value=(status,json.dumps(payload if payload is not None else {'code':1,'data':{'row':{'id':1}}}).encode())
        backend.query=lambda params:urlencode([('search[0][field]',params['search'][0]['field']),('search[0][val]',params['search'][0]['val'])])
        return backend

    def test_constructor_uses_formal_session_not_legacy_auth(self):
        session=Mock();query=Mock(return_value='query');reader=Mock()
        old_client=Mock(side_effect=AssertionError('legacy AdminApiClient must not be used'))
        formal=SimpleNamespace(SessionManager=Mock(return_value=session),read_private_config=Mock(return_value={'P2PAH_API_BASE':'http://127.0.0.1:8912'}))
        with patch.dict(sys.modules,{'fc_shared_admin':formal,'admin_api_client':SimpleNamespace(AdminApiClient=old_client,build_query=query),'p2pah_price':reader}):
            backend=e.Backend()
        self.assertIs(backend.admin,session)
        self.assertIs(backend.query,query)
        self.assertIs(backend.price_reader,reader)
        formal.SessionManager.assert_called_once_with({'P2PAH_API_BASE':'http://127.0.0.1:8912'})
        old_client.assert_not_called()

    def test_get_preserves_nested_query_and_verifies_identity(self):
        backend=self.backend()
        value=backend.get('/admin/goods.Goods/index',{'search':[{'field':'gid','val':'1327'}]})
        self.assertEqual(value,{'row':{'id':1}})
        backend.admin.ensure.assert_called_once_with()
        path=backend.admin.request.call_args.args[0]
        self.assertEqual(parse_qs(path.split('?',1)[1]),{'search[0][field]':['gid'],'search[0][val]':['1327']})
        self.assertIsNone(backend.admin.request.call_args.kwargs['data'])

    def test_identity_failure_never_dispatches_catalog_or_write(self):
        backend=self.backend();backend.admin.ensure.return_value=False
        with self.assertRaisesRegex(ValueError,'Admin identity'):
            backend.get('/admin/goods.Goods/index',{})
        backend.admin.request.assert_not_called()

    def test_http_or_business_failure_is_not_success_and_never_retries(self):
        for status,payload in [(403,{'code':1,'data':{}}),(500,{'code':1}),(200,{'code':302}),(200,{'code':0})]:
            backend=self.backend(status=status,payload=payload)
            with self.subTest(status=status,payload=payload),self.assertRaises(ValueError):
                backend.write(PRODUCTS[0],'1.09')
            backend.admin.request.assert_called_once()

    def test_write_timeout_remains_single_dispatch(self):
        backend=self.backend();backend.admin.request.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):backend.write(PRODUCTS[0],'1.09')
        backend.admin.request.assert_called_once()

    def test_invalid_json_does_not_echo_upstream_secrets(self):
        backend=self.backend();backend.admin.request.return_value=(200,b'private-token-invalid-json')
        with self.assertRaisesRegex(ValueError,'Admin JSON') as error:backend.get('/admin/goods.Goods/index',{})
        self.assertNotIn('private-token',str(error.exception))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend()
        self.store = e.Store(self.temp.name, self.backend)
        self.job = {'id': str(uuid.uuid4()), 'action': 'apply', 'actor': 'wulv',
                    'at': e.time.time(), 'status': 'running', 'results': []}
        self.store.data['job'] = self.job

    def tearDown(self):
        self.store.guard.close()
        self.temp.cleanup()

    def run_job(self):
        self.store.run(self.job)

    def test_confirmed_write_readback_and_unchanged(self):
        self.run_job()
        self.assertEqual(self.job['status'], 'completed')
        self.assertEqual(len(self.backend.writes), 3)
        self.assertEqual(self.backend.cache, 1)
        self.assertFalse(self.store.data['blocked'])
        self.run_job()
        self.assertEqual(len(self.backend.writes), 3)

    def test_unknown_stops_batch_and_blocks_replay(self):
        self.backend.unknown = True
        self.run_job()
        self.assertEqual(self.backend.writes, [10])
        self.assertEqual(self.job['status'], 'needs_review')
        self.assertTrue(self.store.data['blocked'])
        with self.assertRaises(ValueError):
            self.store.start('apply', str(uuid.uuid4()), 'wulv', 1)
        with self.assertRaises(ValueError):
            self.store.reconcile()
        self.assertEqual(self.backend.writes, [10])

    def test_unknown_reconcile_is_read_only(self):
        self.backend.unknown = True
        self.run_job()
        self.backend.products[0].update(price=1.09, unit_price=1.09)
        self.store.reconcile()
        self.assertFalse(self.store.data['blocked'])
        self.assertEqual(self.backend.writes, [10])

    def test_restart_keeps_unknown_and_interruption(self):
        self.backend.unknown = True
        self.run_job()
        self.store.guard.close()
        self.store = e.Store(self.temp.name, self.backend)
        self.assertTrue(self.store.data['blocked'])

    def test_models_changed_between_preview_and_write(self):
        original = self.backend.row
        self.backend.row = lambda kind, identity: dict(original(kind, identity), unit='25000') if kind == 'GoodsMould' else original(kind, identity)
        self.run_job()
        self.assertEqual(self.job['status'], 'failed')
        self.assertEqual(self.backend.writes, [])

    def test_product_changed_between_preview_and_write(self):
        original = self.backend.row
        self.backend.row = lambda kind, identity: dict(original(kind, identity), discount=80) if kind == 'Goods' else original(kind, identity)
        self.run_job()
        self.assertEqual(self.job['status'], 'failed')
        self.assertEqual(self.backend.writes, [])

    def test_readback_mismatch_blocks_remaining(self):
        original = self.backend.write
        def bad_write(row, price):
            original(row, price)
            self.backend.products[0]['price'] = 3
        self.backend.write = bad_write
        self.run_job()
        self.assertEqual(len(self.backend.writes), 1)
        self.assertTrue(self.store.data['blocked'])

    def test_readonly_refresh_never_writes(self):
        self.job['action'] = 'refresh'
        self.run_job()
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(len(self.store.state()['rows']), 3)

    def prepare_historical_unknown_refresh(self):
        self.backend.unknown = True
        self.run_job()
        original_id = self.job['id']
        operation = next(self.store.operations.glob('*.json'))
        original = json.loads(operation.read_text())
        self.store.data['config'].update(automatic=True, revision=4)
        self.store.data['next_auto_at'] = 12345
        self.job = {'id': str(uuid.uuid4()), 'action': 'refresh', 'actor': 'wulv',
                    'at': e.time.time(), 'status': 'running', 'results': []}
        self.store.data['job'] = self.job
        return operation, original, original_id

    def test_fresh_admin_state_covers_history_without_confirming_old_write(self):
        operation, original, original_id = self.prepare_historical_unknown_refresh()
        self.run_job()
        self.assertEqual(self.job['status'], 'completed')
        self.assertEqual(len(self.store.state()['rows']), 3)
        saved = json.loads(operation.read_text())
        coverage = saved.pop('current_state_coverage')
        self.assertEqual(saved, original)
        self.assertEqual(saved['status'], 'unknown')
        self.assertNotIn('after', saved)
        self.assertEqual(saved['job_id'], original_id)
        self.assertEqual(coverage['refresh_job_id'], self.job['id'])
        self.assertEqual(coverage['source'], 'admin_goods_catalog')
        self.assertEqual(coverage['product']['id'], 10)
        self.assertEqual(coverage['product']['aid'], PRODUCTS[0]['aid'])
        self.assertEqual(coverage['product']['site_id'], 0)
        self.assertEqual(coverage['product']['price'], 1.49)
        self.assertNotEqual(str(coverage['product']['price']), original['target'])
        self.assertGreaterEqual(coverage['observed_at'], coverage['read_started_at'])
        self.assertEqual(self.backend.writes, [10])
        self.assertEqual(self.backend.cache, 0)
        self.assertFalse(self.store.data['blocked'])
        self.assertTrue(self.store.data['config']['automatic'])
        self.assertEqual(self.store.data['config']['revision'], 4)
        self.assertEqual(self.store.data['next_auto_at'], 12345)
        self.store.guard.close()
        with patch.object(e.time, 'time', return_value=e.time.time() + 86400):
            self.store = e.Store(self.temp.name, self.backend)
            self.assertTrue(self.store.state()['stale'])
        self.assertFalse(self.store.data['blocked'])
        old_job = json.loads((self.store.jobs / (original_id + '.json')).read_text())
        self.assertEqual(old_job['status'], 'needs_review')
        self.assertEqual(old_job['results'][0]['action'], 'unknown')

    def test_missing_admin_product_keeps_history_blocked(self):
        operation, original, _ = self.prepare_historical_unknown_refresh()
        self.backend.products = self.backend.products[1:]
        self.run_job()
        self.assertTrue(self.store.data['blocked'])
        self.assertEqual(json.loads(operation.read_text()), original)
        self.assertEqual(self.job['status'], 'needs_review')
        self.assertEqual(self.backend.writes, [10])

    def test_inflight_original_job_is_not_covered_by_preview(self):
        operation, original, original_id = self.prepare_historical_unknown_refresh()
        path = self.store.jobs / (original_id + '.json')
        old = json.loads(path.read_text()); old['status'] = 'running'
        e.save(path, old)
        self.run_job()
        self.assertTrue(self.store.data['blocked'])
        self.assertEqual(json.loads(operation.read_text()), original)
        self.assertEqual(self.backend.writes, [10])

    def test_different_platform_cannot_cover_history(self):
        operation, original, _ = self.prepare_historical_unknown_refresh()
        self.backend.products[0]['aid'] = PRODUCTS[1]['aid']
        self.run_job()
        self.assertTrue(self.store.data['blocked'])
        self.assertEqual(json.loads(operation.read_text()), original)

    def test_missing_admin_unit_price_cannot_cover_history(self):
        operation, original, _ = self.prepare_historical_unknown_refresh()
        del self.backend.products[0]['unit_price']
        self.run_job()
        self.assertTrue(self.store.data['blocked'])
        self.assertEqual(json.loads(operation.read_text()), original)

    def test_new_unknown_after_historical_coverage_still_blocks(self):
        operation, _, _ = self.prepare_historical_unknown_refresh()
        self.run_job()
        self.assertFalse(self.store.data['blocked'])
        covered_bytes = operation.read_bytes()
        self.job = {'id': str(uuid.uuid4()), 'action': 'apply', 'actor': 'wulv',
                    'at': e.time.time(), 'status': 'running', 'results': []}
        self.store.data['job'] = self.job
        self.run_job()
        self.assertTrue(self.store.data['blocked'])
        self.assertEqual(self.job['status'], 'needs_review')
        self.assertEqual(operation.read_bytes(), covered_bytes)
        self.assertEqual(len(list(self.store.operations.glob('*.json'))), 2)

    def test_stale_catalog_read_does_not_create_coverage(self):
        operation, original, _ = self.prepare_historical_unknown_refresh()
        now = e.time.time()
        with patch.object(e.time, 'time', return_value=now + 301):
            self.store.cover_historical_state(self.job, self.backend.models,
                                             self.backend.products, now, now + 301)
        self.assertTrue(self.store.data['blocked'])
        self.assertEqual(json.loads(operation.read_text()), original)

    def test_failed_refresh_cannot_cover_history(self):
        operation, original, _ = self.prepare_historical_unknown_refresh()
        self.backend.rates = Mock(side_effect=ValueError('Order unavailable'))
        self.run_job()
        self.assertEqual(self.job['status'], 'failed')
        self.assertTrue(self.store.data['blocked'])
        self.assertEqual(json.loads(operation.read_text()), original)

    def test_disabled_item_is_skipped(self):
        self.store.data['config']['overrides']['1'] = {'enabled': False}
        self.run_job()
        self.assertEqual(self.backend.writes, [])

    def test_auto_off_and_cas_stop(self):
        self.job['actor'] = 'system-automation'
        self.run_job()
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.job['status'], 'failed')

    def test_config_can_turn_off_during_job(self):
        self.store.configure({'expected_revision': 1, 'automatic': False})
        self.assertEqual(self.store.data['config']['revision'], 2)
        with self.assertRaises(ValueError):
            self.store.configure({'expected_revision': 2, 'premium': '1.2'})

    def test_request_id_is_persistent(self):
        self.run_job()
        old_id = self.job['id']
        self.store.data['job'] = None
        self.store.data['history'] = []
        previous = self.store.start('apply', old_id, 'wulv', 1)
        self.assertEqual(previous['status'], 'completed')
        self.assertEqual(len(self.backend.writes), 3)

    def test_cache_failure_remains_pending(self):
        self.backend.clear_cache = Mock(side_effect=RuntimeError())
        self.run_job()
        self.assertEqual(self.job['status'], 'failed')
        self.assertTrue(self.store.data['cache_pending'])
        self.backend.clear_cache = Mock()
        self.run_job()
        self.assertFalse(self.store.data['cache_pending'])
        self.assertEqual(len(self.backend.writes), 3)

    def test_cache_only_reconcile_never_rewrites_products(self):
        self.store.data['cache_pending'] = True
        self.store.reconcile()
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.backend.cache, 1)
        self.assertFalse(self.store.data['cache_pending'])

    def test_enabling_auto_is_due_and_refresh_does_not_postpone(self):
        self.job['status'] = 'completed'
        self.store.configure({'expected_revision': 1, 'automatic': True})
        due = self.store.data['next_auto_at']
        self.assertLessEqual(due, e.time.time())
        self.job['action'] = 'refresh'
        self.run_job()
        self.assertEqual(self.store.data['next_auto_at'], due)

    def test_completed_apply_sets_next_automatic_time(self):
        self.run_job()
        self.assertAlmostEqual(self.store.data['next_auto_at'] - self.job['finished_at'], 7200)

    def test_invalid_item_does_not_stop_valid_items(self):
        self.backend.models[0]['unit'] = ''
        self.backend.models.append(dict(MODEL, id=2, title='Second evolution'))
        self.backend.products.extend([dict(r, id=r['id']+10, mid=2, title='Second evolution') for r in PRODUCTS])
        self.run_job()
        self.assertEqual(self.backend.writes, [20,21,22])
        self.assertEqual(self.job['status'], 'partial')
        self.assertEqual(sum(r['action']=='skipped_invalid' for r in self.job['results']), 3)
        self.assertFalse(self.store.data['blocked'])


if __name__ == '__main__':
    unittest.main()
