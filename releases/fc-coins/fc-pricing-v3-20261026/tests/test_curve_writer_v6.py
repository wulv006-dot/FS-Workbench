"""The original writer protocol exercised with a synthetic Admin and Order."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from urllib.parse import parse_qs
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import coin_all_sync_job as writer
import reconcile_original
from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL, validate_curve_send, write_protocol
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.order_projection_v6 import ORIGIN, OrderProjection
from fc_pricing_v3.price_curve import IDENTITY_FIELDS, curve_key, read_curve
from fc_pricing_v3.pricing_proof_v6 import validate_curve
from test_pricing_proof_v6 import basket, quote


OPERATION = '00000000-0000-4000-8000-000000000080'
PLATFORM = 'PS'
ALL_ID, PRIMARY_ID, AID = writer.PRODUCTS[PLATFORM]
NOW = datetime.now(timezone.utc)


def goods(goods_id, site, small='10', large='100'):
    return dict(id=goods_id, site_id=site, aid=AID, cid=9623, mid=41217957, gid=1327,
                unit='K', title='coins', status=1, unit_price=str(Decimal(small) / 100),
                keywords='exact title', more=dict(gold=['100', '1000'], give=['0', '30'],
                                                  price=[small, large], discount=['100', '100'],
                                                  delivery_time=['10', '10'], hot=['0', '1']))


def saved(row, origin=None):
    contract = dict(version='fixture-contract')
    if origin:
        contract['catalogue_origin'] = origin
    return read_curve(row, {key: row[key] for key in IDENTITY_FIELDS}, contract)


def setup_bundle(small='10', large='103', *, before_large='100', target_override=None, cost_evidence=None):
    before = goods(ALL_ID, 0, large=before_large)
    after = goods(ALL_ID, 0, small, large)
    if target_override:
        target_override(after)
    target = saved(after, 'editor_candidate')
    key = curve_key(target)
    refs = dict(quantity='fixture-quantity', offers='fixture-offers',
                fulfilment='fixture-fulfilment', propagation='fixture-propagation')
    domain = dict(curve_key=key, platform=PLATFORM, version='fixture-domain',
                  coverage_status='complete', coverage_gaps=[], source_revisions=refs,
                  site_paths={'266': ['ordinary']})
    paths = dict(curve_key=key, paths=[quote('ordinary', key, regular_usd=large, net_receipt_usd=large,
                                            **(cost_evidence or {}))])
    baskets = dict(main=basket('closed_bjt_7d', [('ordinary', '50')]),
                   recent=basket('latest_24h', [('ordinary', '30')]))
    proof = validate_curve(target, baskets, paths, domain)
    bundle = dict(write_protocol=CURVE_WRITE_PROTOCOL, decision_bundle_id=OPERATION,
                  plan_id='plan', revision=4, engine_generation='generation', snapshot_id='run',
                  valid_until=(NOW + timedelta(hours=4)).isoformat(),
                  mutable_resources=['base:PS'], affected_platforms=[PLATFORM],
                  before_action=dict(curves={PLATFORM: saved(before)}),
                  action=dict(curves={PLATFORM: target}), curve_proofs={PLATFORM: proof})
    bundle['sha256'] = fingerprint(bundle)
    capability = dict(evidence_ref='synthetic-catalog-save', domain_version=domain['version'],
                      source_revisions=refs, recipient_goods={266: PRIMARY_ID},
                      catalogue_status='verified', order_projection_status='verified')
    return bundle, capability, before, goods(PRIMARY_ID, 266, large=before_large)


class Transport:
    token = 'fixture'

    def __init__(self, before, recipient, *, propagate=True):
        self.rows = {ALL_ID: deepcopy(before), PRIMARY_ID: deepcopy(recipient)}
        self.propagate = propagate
        self.posts = []
        self.projection_writes = []
        self.projection_rate = before['unit_price']
        self.response_lost = False
        self.rejection_code = None
        self.restore_linear = False
        self.projection_delayed = False
        self.projection_response_lost = False

    def apply_recipient(self, goods_id=PRIMARY_ID):
        self.rows[goods_id]['unit_price'] = self.rows[ALL_ID]['unit_price']
        self.rows[goods_id]['more']['price'] = deepcopy(self.rows[ALL_ID]['more']['price'])
        self.rows[goods_id]['more']['discount'] = deepcopy(self.rows[ALL_ID]['more']['discount'])

    def request(self, path, *, data, token):
        goods_id = int(path.split('=')[-1])
        if data is None:
            return 200, json.dumps(dict(code=1, data=dict(row=self.rows[goods_id])))
        self.posts.append((goods_id, deepcopy(data)))
        if self.rejection_code is not None:
            return 200, json.dumps(dict(code=self.rejection_code, msg='fixture denial'))
        self.rows[goods_id] = deepcopy(data)
        if self.propagate:
            self.apply_recipient()
        if self.response_lost:
            raise TimeoutError
        return 200, json.dumps(dict(code=1, data={}))

    def write_rate(self, platform, before, target, observe):
        self.projection_writes.append((platform, before, target))
        if Decimal(self.projection_rate) != Decimal(before):
            raise ValueError('projection CAS mismatch')
        if not self.projection_delayed:
            self.projection_rate = target
        if self.restore_linear:
            self.rows[ALL_ID]['more']['price'][1] = '120'
            self.apply_recipient()
        if self.projection_response_lost:
            raise TimeoutError
        observe(dict(http_status=200, response_code=1, response_sha256='fixture',
                     path='synthetic-isolated-order-rate'))

    def projection(self):
        def prepare(platform, before, target):
            if Decimal(self.projection_rate) != Decimal(before):
                raise ValueError('pricing_curve_order_before_rate_changed')
            return lambda observe: self.write_rate(platform, before, target, observe)

        return dict(path='synthetic-isolated-order-rate', evidence_ref='synthetic-rate-contract',
                    read=lambda _: self.projection_rate, prepare=prepare)


class AdminRejectionReceipt(unittest.TestCase):
    def test_sanitizes_rejection_message_without_copying_response_data(self):
        manager = Mock(token='fixture')
        observer = Mock()
        for message, expected in (('折扣字段不符合限制', '折扣字段不符合限制'),
                                  ('order 1234567890 not allowed', 'order [redacted] not allowed'),
                                  ('authorization=example-value', None)):
            manager.request.return_value = 200, json.dumps(dict(code=0, msg=message, data={'private': 'omit'}))
            with self.assertRaisesRegex(ValueError, 'coin_backend_request_rejected'):
                writer.api(manager, f'/admin/goods.Goods/edit?id={ALL_ID}', {}, observer)
            receipt, = observer.call_args.args
            self.assertEqual(receipt.get('response_message'), expected)
            self.assertEqual(len(receipt['response_message_sha256']), 64)
            self.assertNotIn('data', receipt)


class OrderProjectionTransport(unittest.TestCase):
    @staticmethod
    def response(body, status=200):
        response = Mock(status=status)
        response.read.return_value = body
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    @staticmethod
    def page(path='/game/admin_game_price/itemEdit'):
        return f'''<select id="lot-game"><option value="1322" selected>FC27</option></select>
<table><tr data-id="21942" data-url="{path}"><td title="1322">FC 27</td>
<td data-type="title"><span>PS</span><input value="PS"></td>
<td class="toggle-input" data-type="b2c" data-refresh="0" data-callback="showprice">
<span>0.08</span><input type="text" value="0.08">
</td></tr></table>'''.encode()

    def test_posts_exact_order_item_and_accepts_only_the_native_business_receipt(self):
        opener = Mock()
        opener.open.side_effect = [self.response(self.page()), self.response(b'{"code":1}')]
        projection = OrderProjection(opener)
        observer = Mock()
        send = projection.prepare('PS', '0.0800', '0.0798')
        self.assertEqual(opener.open.call_count, 1)
        send(observer)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.full_url, ORIGIN + '/game/admin_game_price/itemEdit?ids=21942')
        self.assertEqual(parse_qs(request.data.decode()), {'data_type': ['b2c'], 'data_val': ['0.0798']})
        self.assertEqual(observer.call_args.args[0]['response_code'], 1)

    def test_rejects_changed_order_endpoint_and_mismatched_rate_before_post(self):
        opener = Mock()
        opener.open.side_effect = [self.response(self.page('/game/admin_game_price/saveprice.html')),
                                   self.response(self.page())]
        projection = OrderProjection(opener)
        with self.assertRaisesRegex(ValueError, 'order_row_scope_changed'):
            projection.prepare('PS', '0.08', '0.0798')
        with self.assertRaisesRegex(ValueError, 'order_before_rate_changed'):
            projection.prepare('PS', '0.078', '0.0798')
        self.assertEqual([call.args[0].get_method() for call in opener.open.call_args_list], ['GET', 'GET'])

    def test_missing_business_success_after_dispatch_is_not_retried(self):
        opener = Mock()
        opener.open.side_effect = [self.response(self.page()), self.response(b'{"code":0}')]
        projection = OrderProjection(opener)
        observer = Mock()
        with self.assertRaisesRegex(ValueError, 'order_item_edit_rejected'):
            projection.prepare('PS', '0.08', '0.0798')(observer)
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(observer.call_args.args[0]['response_code'], 0)


class CurveWriter(unittest.TestCase):
    def prepare(self, small='10', large='103', *, projection=True, propagate=True, before_large='100',
                extra_recipients=None):
        bundle, capability, before, recipient = setup_bundle(small, large, before_large=before_large)
        self.transport = Transport(before, recipient, propagate=propagate)
        if projection:
            capability['order_projection'] = self.transport.projection()
        for site, row in (extra_recipients or {}).items():
            capability['recipient_goods'][site] = row['id']
            self.transport.rows[row['id']] = row
        self.capabilities = {PLATFORM: capability}
        self.item = dict(writer.curve_catalog_plan(bundle, PLATFORM, capability), operation_id=OPERATION)
        self.bundle = bundle
        self.audit = dict(execution_id=OPERATION, write_protocol=CURVE_WRITE_PROTOCOL, status='RUNNING',
                          sync_confirmed=False, changed=[], pricing_decision_receipt=bundle,
                          curve_results={PLATFORM: self.item})
        self.saved = Mock()

    def dispatch(self, before_send=lambda _: None):
        return writer.drive_curve_catalog(self.transport, self.audit, self.saved,
                                          before_send, self.capabilities)

    def reconcile(self):
        return writer.reconcile_curve_catalog(self.transport, self.audit, self.saved, self.capabilities)

    def test_high_tier_only_confirms_full_prices_and_never_projects_order_rate(self):
        self.prepare()
        self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.transport.projection_writes, [])
        self.assertEqual(self.item['projection']['status'], 'not_required')
        actual = self.item['actual_site266_curve']
        self.assertEqual(actual['identity']['site_id'], '266')
        self.assertNotIn('catalogue_origin', actual['native_contract'])
        self.assertEqual(actual['tiers'][1]['native_price_usd'], '103')
        mapping = self.item['propagation']['curve_mapping']
        self.assertEqual(mapping['actual_site266_curve_key'], curve_key(actual))
        self.assertNotEqual(mapping['actual_site266_curve_key'], mapping['target_curve_key'])

    def test_two_band_writer_accepts_primary_complete_table_without_post_save_all_read(self):
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT

        self.prepare(extra_recipients={575: goods(999, 575)})
        target = self.bundle['action']['curves'][PLATFORM]
        target['native_contract']['price_edit_policy'] = TWO_BAND_PRICE_EDIT
        self.item = dict(writer.curve_catalog_plan(self.bundle, PLATFORM, self.capabilities[PLATFORM]), operation_id=OPERATION)
        self.audit['curve_results'][PLATFORM] = self.item
        original = self.transport.request
        post_write_reads = []

        def request(path, *, data, token):
            if data is None and self.transport.posts:
                post_write_reads.append(int(path.split('=')[-1]))
                if not path.endswith('=' + str(PRIMARY_ID)):
                    raise AssertionError('only the primary storefront is used for post-save verification')
            return original(path, data=data, token=token)

        with patch.object(self.transport, 'request', side_effect=request):
            result = self.dispatch()
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertEqual(post_write_reads, [PRIMARY_ID])
        self.assertEqual(self.item['catalog']['confirmation_basis'], 'original_admin_save_receipt')
        self.assertEqual(self.item['projection']['status'], 'not_required')
        self.assertEqual(writer.protected(self.item['target']), writer.protected(self.item['before']))
        self.assertEqual(self.transport.projection_writes, [])

    def test_two_band_main_full_table_drift_keeps_original_partial(self):
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT

        self.prepare(propagate=False)
        self.bundle['action']['curves'][PLATFORM]['native_contract']['price_edit_policy'] = TWO_BAND_PRICE_EDIT
        self.item = dict(writer.curve_catalog_plan(self.bundle, PLATFORM, self.capabilities[PLATFORM]), operation_id=OPERATION)
        self.audit['curve_results'][PLATFORM] = self.item
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.item['propagation']['reason'], 'pricing_curve_recipient_readback_mismatch:266')
        self.transport.apply_recipient()
        self.assertEqual(self.reconcile()['status'], 'CONFIRMED')
        self.assertEqual(len(self.transport.posts), 1)

    def test_two_band_100k_change_has_no_order_io_and_keeps_the_full_admin_target(self):
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT

        for small, before_large, large in (('8.62', '81.60', '86.12'), ('8.35', '86.00', '86.00')):
            with self.subTest(small=small, large=large):
                def admin_target(row):
                    row['unit_price'] = '0.10'

                bundle, capability, before, recipient = setup_bundle(
                    small=small, large=large, before_large=before_large, target_override=admin_target,
                    cost_evidence=dict(expected_cost_usd='60', safe_cost_usd='61', stress_cost_usd='62'))
                bundle['action']['curves'][PLATFORM]['native_contract']['price_edit_policy'] = TWO_BAND_PRICE_EDIT
                capability.pop('order_projection_status')
                self.transport = Transport(before, recipient)
                self.capabilities = {PLATFORM: capability}
                self.item = dict(writer.curve_catalog_plan(bundle, PLATFORM, capability), operation_id=OPERATION)
                self.audit = dict(execution_id=OPERATION, write_protocol=CURVE_WRITE_PROTOCOL,
                                  curve_results={PLATFORM: self.item})
                self.saved = Mock()
                order_read = Mock(side_effect=AssertionError('two-band writer must not read a scalar Order rate'))
                order_prepare = Mock(side_effect=AssertionError('two-band writer must not prepare an Order POST'))
                capability['order_projection'] = dict(read=order_read, prepare=order_prepare)
                self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
                self.assertEqual(self.reconcile()['status'], 'CONFIRMED')
                order_read.assert_not_called()
                order_prepare.assert_not_called()
                self.assertEqual(self.item['projection'], {'status': 'not_required'})
                self.assertEqual(len(self.transport.posts), 1)
                for row in self.transport.rows.values():
                    self.assertEqual(row['more']['price'], [small, large])
                    self.assertEqual(row['more']['give'], ['0', '30'])
                    self.assertEqual(row['unit_price'], '0.10')

    def _modern_preflight(self, *, extra=16):
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT
        satellites = {1000 + i: goods(900000 + i, 1000 + i) for i in range(extra)}
        self.prepare(extra_recipients=satellites)
        self.item['native_contract']['price_edit_policy'] = TWO_BAND_PRICE_EDIT
        self.item['catalogue_status'] = 'native_route_ready'
        self.item['primary_before_hash'] = fingerprint(writer.editable(self.transport.rows[PRIMARY_ID]))

    def test_modern_preflight_reads_only_required_sites_and_all(self):
        self._modern_preflight()
        original = writer.read_row
        observed = []
        def read(manager, platform, site, *args, **kwargs):
            observed.append((site, bool(self.transport.posts)))
            return original(manager, platform, site, *args, **kwargs)
        with patch.object(writer, 'read_row', side_effect=read):
            self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual([site for site, after in observed if not after], [266, 0])
        self.assertEqual([site for site, after in observed if after], [266])
        self.assertEqual(set(self.item['recipients_before']), {'266'})
        self.assertEqual(self.item['propagation']['site_outcomes'], {'266': 'target_observed'})
        self.assertEqual(len(self.transport.posts), 1)

    def test_modern_preflight_keeps_an_explicit_additional_required_site(self):
        self._modern_preflight(extra=1)
        self.item['required_recipient_sites'].append('1000')
        apply_recipient = self.transport.apply_recipient
        def propagate():
            apply_recipient()
            apply_recipient(900000)
        self.transport.apply_recipient = propagate
        original = writer.read_row
        seen = []
        def read(manager, platform, site, *args, **kwargs):
            if not self.transport.posts: seen.append(site)
            return original(manager, platform, site, *args, **kwargs)
        with patch.object(writer, 'read_row', side_effect=read):
            self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(seen, [266, 1000, 0])
        self.assertEqual(set(self.item['recipients_before']), {'266', '1000'})
        self.assertEqual(self.item['propagation']['site_outcomes'], {'266': 'target_observed', '1000': 'target_observed'})

    def test_additional_required_site_must_be_read_back_before_confirmation(self):
        self._modern_preflight(extra=1)
        self.item['required_recipient_sites'].append('1000')
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.item['propagation']['site_outcomes'], {'266': 'target_observed', '1000': 'target_mismatch'})
        self.assertEqual(len(self.transport.posts), 1)

    def test_legacy_or_missing_required_scope_preserves_full_preflight(self):
        for scenario in ('legacy', 'missing'):
            with self.subTest(scenario=scenario):
                self._modern_preflight(extra=2)
                if scenario == 'legacy': self.item['catalogue_status'] = 'verified'
                else: self.item.pop('required_recipient_sites')
                original = writer.read_row
                seen = []
                def read(manager, platform, site, *args, **kwargs):
                    if not self.transport.posts: seen.append(site)
                    return original(manager, platform, site, *args, **kwargs)
                with patch.object(writer, 'read_row', side_effect=read): self.dispatch()
                self.assertEqual(seen, [266, 1000, 1001, 0])

    def test_invalid_explicit_required_scope_refuses_before_any_post(self):
        for scope in ([], ['1000'], ['266', 'not-present'], ['266', '266']):
            with self.subTest(scope=scope):
                self._modern_preflight(extra=1); self.item['required_recipient_sites'] = scope
                self.assertEqual(self.dispatch()['status'], 'NOT_SENT')
                self.assertEqual(self.item['last_error'], 'pricing_curve_required_recipient_scope_invalid')
                self.assertEqual(self.transport.posts, [])

    def test_required_main_timeout_rechecks_before_send_once(self):
        self._modern_preflight(extra=0)
        original = writer.read_row
        attempts = []; fences = []
        def read(manager, platform, site, *args, **kwargs):
            attempts.append((site, bool(self.transport.posts)))
            if site == 266 and sum(x == (266, False) for x in attempts) == 1:
                raise TimeoutError()
            return original(manager, platform, site, *args, **kwargs)
        def fence(_): fences.append('send_intent' in self.item['catalog'])
        with patch.object(writer, 'read_row', side_effect=read):
            result = self.dispatch(before_send=fence)
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertEqual(attempts, [(266, False), (266, False), (0, False), (266, True)])
        self.assertEqual(fences, [False, True])
        self.assertEqual(len(self.transport.posts), 1)

    def test_all_timeout_revalidates_required_main_before_retry(self):
        self._modern_preflight(extra=0)
        original = writer.read_row; seen = []
        def read(manager, platform, site, *args, **kwargs):
            if not self.transport.posts:
                seen.append(site)
                if site == 0 and seen.count(0) == 1: raise TimeoutError()
            return original(manager, platform, site, *args, **kwargs)
        with patch.object(writer, 'read_row', side_effect=read):
            self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(seen, [266, 0, 266, 0])
        self.assertEqual(len(self.transport.posts), 1)

    def test_timeout_reread_refuses_changed_main_or_expired_authorization(self):
        for failure in ('changed_main', 'authorization'):
            with self.subTest(failure=failure):
                self._modern_preflight(extra=0);original=writer.read_row;seen=[]
                def read(manager, platform, site, *args, **kwargs):
                    seen.append(site)
                    if site == 0 and seen.count(0) == 1:
                        if failure == 'changed_main': self.transport.rows[PRIMARY_ID]['more']['price'][0] = '11'
                        raise TimeoutError()
                    return original(manager, platform, site, *args, **kwargs)
                def fence(_):
                    if failure == 'authorization': raise ValueError('authorization_changed')
                with patch.object(writer, 'read_row', side_effect=read):
                    self.assertEqual(self.dispatch(before_send=fence)['status'], 'NOT_SENT')
                self.assertEqual(self.transport.posts, [])
                self.assertNotIn('send_intent', self.item['catalog'])

    def test_second_timeout_or_non_timeout_never_retries_again(self):
        for error in (TimeoutError(), PermissionError(), ValueError('identity_invalid')):
            with self.subTest(error=type(error).__name__):
                self._modern_preflight(extra=0);seen=[]
                def read(manager, platform, site, *args, **kwargs):
                    seen.append(site)
                    raise error
                with patch.object(writer, 'read_row', side_effect=read):
                    self.assertEqual(self.dispatch()['status'], 'NOT_SENT')
                self.assertEqual(len(seen), 2 if isinstance(error, TimeoutError) else 1)
                self.assertEqual(self.transport.posts, [])
                self.assertNotIn('send_intent', self.item['catalog'])

    def test_optional_timeout_keeps_original_no_retry_behavior(self):
        self._modern_preflight(extra=1)
        self.item['catalogue_status'] = 'verified'
        original = writer.read_row; preflight = []
        def read(manager, platform, site, *args, **kwargs):
            if not self.transport.posts:
                preflight.append(site)
                if site == 1000: raise TimeoutError()
            return original(manager, platform, site, *args, **kwargs)
        with patch.object(writer, 'read_row', side_effect=read):
            self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(preflight, [266, 1000, 0])
        self.assertEqual(len(self.transport.posts), 1)

    def test_one_retry_budget_is_shared_across_original_operation(self):
        self._modern_preflight(extra=0)
        second = deepcopy(self.item)
        self.audit['curve_results'] = {'first': self.item, 'second': second}
        original = writer.read_row; attempts = []
        def read(manager, platform, site, *args, **kwargs):
            attempts.append(site)
            if site == 266 and attempts.count(266) in (1, 3): raise TimeoutError()
            return original(manager, platform, site, *args, **kwargs)
        def fence(_):
            if 'send_intent' in self.item['catalog']: raise ValueError('policy_changed')
        with patch.object(writer, 'read_row', side_effect=read):
            self.assertEqual(self.dispatch(before_send=fence)['status'], 'NOT_SENT')
        self.assertEqual(attempts, [266, 266, 0, 266])
        self.assertEqual(self.transport.posts, [])
        self.assertEqual(second['last_error'], 'TimeoutError')

    def test_existing_send_intent_never_starts_preflight_or_resends(self):
        self._modern_preflight(extra=0)
        self.item['catalog']['send_intent'] = {'original': True}
        with patch.object(writer, 'read_row') as read:
            with self.assertRaisesRegex(ValueError, 'pricing_curve_catalog_already_dispatched'):
                self.dispatch()
        read.assert_not_called()
        self.assertEqual(self.transport.posts, [])

    def test_python39_and_wrapped_timeouts_retry_only_required_get_once(self):
        from socket import timeout as socket_timeout
        from urllib.error import URLError
        factories = (lambda: TimeoutError(), lambda: socket_timeout(),
                     lambda: URLError(TimeoutError()), lambda: URLError(socket_timeout()))
        for factory in factories:
            with self.subTest(error=type(factory()).__name__):
                self._modern_preflight(extra=0); original=writer.read_row; seen=[]
                def read(manager, platform, site, *args, **kwargs):
                    if not self.transport.posts:
                        seen.append(site)
                        if len(seen)==1: raise factory()
                    return original(manager, platform, site, *args, **kwargs)
                with patch.object(writer, 'read_row', side_effect=read):
                    self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
                self.assertEqual(seen, [266, 266, 0])
                self.assertEqual(len(self.transport.posts), 1)

    def test_http_or_non_timeout_url_error_is_not_retried(self):
        from socket import timeout as socket_timeout
        from urllib.error import HTTPError, URLError
        errors = (URLError(ConnectionRefusedError()), HTTPError('http://fixture/', 503, socket_timeout(), {}, None))
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self._modern_preflight(extra=0); seen=[]
                def read(manager, platform, site, *args, **kwargs):
                    seen.append(site); raise error
                with patch.object(writer, 'read_row', side_effect=read):
                    self.assertEqual(self.dispatch()['status'], 'NOT_SENT')
                self.assertEqual(seen, [266])
                self.assertEqual(self.transport.posts, [])

    def test_wrapped_post_timeout_stays_unknown_without_resend(self):
        from socket import timeout as socket_timeout
        from urllib.error import URLError
        self._modern_preflight(extra=0); original=self.transport.request
        def request(path, *, data, token):
            if data is not None:
                self.transport.posts.append((path, data))
                raise URLError(socket_timeout())
            return original(path, data=data, token=token)
        self.transport.request = request
        self.assertEqual(self.dispatch()['status'], 'UNKNOWN')
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.item['catalog']['status'], 'unknown')

    def test_original_writer_receipt_freezes_actual_site266_in_window(self):
        from fc_pricing_v3.ledger import confirmed_curve_window

        self.prepare()
        receipt = self.dispatch()
        action, evidence = confirmed_curve_window(dict(bundle=self.bundle, readback=receipt,
                                                       operation_id=OPERATION))
        actual = self.item['actual_site266_curve']
        self.assertEqual(action['curves'][PLATFORM], actual)
        self.assertEqual(evidence['decision_curve_keys'][PLATFORM], self.item['target_curve_key'])
        self.assertEqual(evidence['curve_confirmations'][PLATFORM]['actual_site266_curve_key'], curve_key(actual))

    def test_100k_and_high_tier_change_make_one_isolated_order_projection(self):
        self.prepare(small='12')
        self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(len(self.transport.projection_writes), 1)
        self.assertEqual(self.item['projection']['readback_rate'], '0.12')
        for row in self.transport.rows.values():
            self.assertEqual(row['more']['price'], ['12', '103'])
        self.assertEqual(self.reconcile()['status'], 'CONFIRMED')
        self.assertEqual(len(self.transport.projection_writes), 1)

    def test_unverified_order_path_keeps_confirmed_catalog_without_order_write(self):
        # The transport is unavailable during reconciliation of a previously sent catalog.
        self.prepare(small='12', propagate=False)
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.transport.apply_recipient()
        self.capabilities[PLATFORM].pop('order_projection')
        self.assertEqual(self.reconcile()['status'], 'PARTIAL')
        self.assertEqual(self.item['catalog']['status'], 'confirmed')
        self.assertEqual(self.item['propagation']['status'], 'confirmed')
        self.assertEqual(self.item['projection']['status'], 'unverified')
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.transport.projection_writes, [])

    def test_missing_order_projection_blocks_new_plan_before_catalog(self):
        bundle, capability, *_ = setup_bundle(small='12')
        with self.assertRaisesRegex(ValueError, 'order_projection_unverified'):
            writer.curve_catalog_plan(bundle, PLATFORM, capability)

    def test_order_drift_blocks_catalog_before_any_dispatch(self):
        self.prepare(small='12')
        self.transport.projection_rate = '0.09'
        self.assertEqual(self.dispatch()['status'], 'NOT_SENT')
        self.assertEqual(self.item['last_error'], 'pricing_curve_order_before_rate_changed')
        self.assertEqual(self.transport.posts, [])
        self.assertEqual(self.transport.projection_writes, [])

    def test_recipient_late_with_receipt_reconciles_original_without_writes(self):
        self.prepare(propagate=False)
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.item['catalog']['status'], 'confirmed')
        self.assertEqual(self.item['propagation']['status'], 'readback_pending')
        self.transport.apply_recipient()
        self.assertEqual(self.reconcile()['status'], 'CONFIRMED')
        self.assertEqual(self.reconcile()['status'], 'CONFIRMED')
        self.assertEqual(len(self.transport.posts), 1)

    def test_timeout_late_state_without_receipt_stays_unknown_on_original_id(self):
        self.prepare(propagate=False)
        self.transport.response_lost = True
        self.assertEqual(self.dispatch()['status'], 'UNKNOWN')
        self.transport.apply_recipient()
        self.assertEqual(self.reconcile()['status'], 'UNKNOWN')
        self.assertEqual(self.item['catalog']['reason'], 'pricing_curve_original_receipt_unavailable')
        self.assertEqual(self.item['observed_rows']['0']['more']['price'], ['10', '103'])
        self.assertNotIn('actual_site266_curve', self.item)
        self.assertEqual(len(self.transport.posts), 1)

    def test_projection_delayed_recovery_is_get_only(self):
        self.prepare(small='12')
        self.transport.projection_delayed = True
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.item['projection']['status'], 'readback_pending')
        self.transport.projection_rate = '0.12'
        self.assertEqual(self.reconcile()['status'], 'CONFIRMED')
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(len(self.transport.projection_writes), 1)

    def test_wrong_full_tier_and_non_price_drift_never_confirm_propagation(self):
        self.prepare(propagate=False)
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        recipient = self.transport.rows[PRIMARY_ID]
        self.transport.apply_recipient()
        recipient['more']['give'][1] = '29'
        self.assertEqual(self.reconcile()['status'], 'PARTIAL')
        self.assertNotIn('actual_site266_curve', self.item)
        recipient['more']['give'][1] = '30'
        self.transport.rows[ALL_ID]['more']['price'][1] = '100'
        self.assertEqual(self.reconcile()['status'], 'PARTIAL')
        self.assertEqual(self.item['catalog']['status'], 'readback_pending')

    def test_projection_that_flattens_curve_fails_full_readback(self):
        self.prepare(small='12')
        self.transport.restore_linear = True
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.item['catalog']['status'], 'readback_pending')

    def test_projection_timeout_still_rechecks_admin_and_never_reposts(self):
        self.prepare(small='12')
        self.transport.restore_linear = True
        self.transport.projection_response_lost = True
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.item['projection']['status'], 'unknown')
        self.assertEqual(self.item['catalog']['status'], 'readback_pending')
        self.assertEqual(self.reconcile()['status'], 'PARTIAL')
        self.assertEqual(len(self.transport.projection_writes), 1)
        self.assertEqual(len(self.transport.posts), 1)

    def test_current_before_cas_and_late_revision_fence_prevent_dispatch(self):
        self.prepare()
        self.transport.rows[ALL_ID]['more']['price'][1] = '101'
        self.assertEqual(self.dispatch()['status'], 'NOT_SENT')
        self.assertEqual(self.item['last_error'], 'pricing_curve_before_hash_changed')
        self.assertFalse(self.audit['business_dispatch_started'])
        self.prepare()
        self.assertEqual(self.dispatch(Mock(side_effect=ValueError('retired generation')))['status'], 'NOT_SENT')
        self.assertFalse(self.audit['business_dispatch_started'])
        self.assertEqual(self.transport.posts, [])

    def test_recipient_gift_drift_refuses_before_any_write(self):
        self.prepare()
        self.transport.rows[PRIMARY_ID]['more']['give'][1] = '300'
        self.assertEqual(self.dispatch()['status'], 'NOT_SENT')
        self.assertEqual(self.audit['status'], 'FAILED_BEFORE_WRITE')
        self.assertFalse(self.audit['business_dispatch_started'])
        self.assertEqual(self.item['last_error'], 'pricing_curve_recipient_specs_changed:266')
        self.assertNotIn('send_intent', self.item['catalog'])
        self.assertNotIn('actual_site266_curve', self.item)
        self.assertEqual(self.transport.posts, [])
        self.assertEqual(self.transport.projection_writes, [])
        self.assertEqual(self.transport.rows[PRIMARY_ID]['more']['price'], ['10', '100'])

    def test_restore_prior_curve_is_new_price_only_target_with_current_proof(self):
        self.prepare(large='103', before_large='107')
        self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        posted = self.transport.posts[0][1]
        self.assertEqual(posted['more']['price'], ['10', '103'])
        self.assertEqual(posted['more']['give'], ['0', '30'])
        self.assertEqual(posted['more']['discount'], ['100', '100'])

    def test_offer_changes_invalid_proof_and_unproven_save_do_not_make_write_plan(self):
        bundle, capability, *_ = setup_bundle(
            target_override=lambda row: row['more']['discount'].__setitem__(1, '91'))
        with self.assertRaisesRegex(ValueError, 'non_price_field_changed'):
            writer.curve_catalog_plan(bundle, PLATFORM, capability)
        bundle, capability, *_ = setup_bundle()
        with self.assertRaisesRegex(ValueError, 'catalog_save_unverified'):
            writer.curve_catalog_plan(bundle, PLATFORM, None)
        bundle['curve_proofs'][PLATFORM]['status'] = 'PROOF_INCOMPLETE'
        with self.assertRaisesRegex(ValueError, 'financial_proof_invalid'):
            writer.curve_catalog_plan(bundle, PLATFORM, capability)

    def test_native_price_factor_change_must_match_the_editor_amount(self):
        def tier_factor(row):
            row['more']['discount'][1] = '97'

        bundle, capability, before, recipient = setup_bundle(large='97', target_override=tier_factor)
        capability['tier_price_factors'] = True
        self.transport = Transport(before, recipient)
        self.capabilities = {PLATFORM: capability}
        self.item = dict(writer.curve_catalog_plan(bundle, PLATFORM, capability), operation_id=OPERATION)
        self.audit = dict(execution_id=OPERATION, write_protocol=CURVE_WRITE_PROTOCOL,
                          curve_results={PLATFORM: self.item})
        self.saved = Mock()
        self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(self.transport.posts[0][1]['more']['discount'], ['100', '97'])
        self.assertEqual(self.transport.rows[PRIMARY_ID]['more']['give'], recipient['more']['give'])
        self.assertEqual(self.item['actual_site266_curve']['tiers'][1]['native_discount'], '97')
        bundle, capability, *_ = setup_bundle(large='96', target_override=tier_factor)
        capability['tier_price_factors'] = True
        with self.assertRaisesRegex(ValueError, 'native_tier_factor_mismatch'):
            writer.curve_catalog_plan(bundle, PLATFORM, capability)

    def test_native_price_derived_markup_requires_exact_editor_contract_and_price(self):
        from fc_pricing_v3.price_curve import FORWARD_TIER_EDIT
        from test_price_curve_v6 import EDITOR_CONTRACT

        def set_markup(row):
            row['more']['discount'][1] = '103'

        for handler in (EDITOR_CONTRACT['editor_handler_sha256'], 'wrong-handler'):
            with self.subTest(handler=handler):
                bundle, capability, *_ = setup_bundle(large='103', target_override=set_markup)
                target = bundle['action']['curves'][PLATFORM]
                target['native_contract'].update(EDITOR_CONTRACT, price_edit_policy=FORWARD_TIER_EDIT,
                                                 editor_handler_sha256=handler)
                capability['tier_price_factors'] = True
                if handler == 'wrong-handler':
                    with self.assertRaisesRegex(ValueError,'native_tier_factor_mismatch'):
                        writer.curve_catalog_plan(bundle, PLATFORM, capability)
                else:
                    proof = bundle['curve_proofs'][PLATFORM]
                    revised_key = curve_key(target)
                    domain = dict(curve_key=revised_key, platform=PLATFORM, version='fixture-domain',
                        coverage_status='complete', coverage_gaps=[], source_revisions=capability['source_revisions'],
                        site_paths={'266':['ordinary']})
                    bundle['curve_proofs'][PLATFORM] = validate_curve(target,
                        dict(main=basket('closed_bjt_7d',[('ordinary','50')]),recent=basket('latest_24h',[('ordinary','30')])),
                        dict(curve_key=revised_key,paths=[quote('ordinary',revised_key,regular_usd='103',net_receipt_usd='103')]), domain)
                    item = writer.curve_catalog_plan(bundle, PLATFORM, capability)
                    self.assertEqual(item['target']['more']['discount'][1], '103')

    def test_main_site_financial_proof_accepts_other_inheriting_catalogue_rows(self):
        satellite = goods(999, 575)
        satellite['more']['give'][1] = '35'
        self.prepare(extra_recipients={575: satellite})
        self.assertEqual(self.item['required_recipient_sites'], ['266'])
        self.assertEqual(self.item['recipient_goods'], {'266': PRIMARY_ID, '575': 999})
        self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(self.item['propagation']['site_outcomes'],
                         {'266': 'target_observed', '575': 'unchanged'})
        self.assertIn('575', self.item['propagation']['actual_hashes'])

    def test_unknown_satellite_readback_does_not_block_mmoexp(self):
        self.prepare(extra_recipients={575: goods(999, 575)})
        native = self.transport.request

        def unavailable(path, **kwargs):
            if path.endswith('=999'):
                raise TimeoutError
            return native(path, **kwargs)

        self.transport.request = unavailable
        self.assertEqual(self.dispatch()['status'], 'CONFIRMED')
        self.assertEqual(self.item['propagation']['site_outcomes']['575'], 'readback_unavailable')
        self.assertNotIn('575', self.item['propagation']['actual_hashes'])

    def test_observed_satellite_non_price_drift_preserves_original_for_reconciliation(self):
        self.prepare(extra_recipients={575: goods(999, 575)})
        native = self.transport.request

        def unexpected_change(path, **kwargs):
            result = native(path, **kwargs)
            if kwargs['data'] is not None:
                self.transport.rows[999]['more']['give'][1] = '999'
            return result

        self.transport.request = unexpected_change
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.item['propagation']['site_outcomes']['575'], 'protected_fields_changed')
        self.assertEqual(len(self.transport.posts), 1)

    def test_same_run_native_directory_opens_route_and_completion_still_needs_original_readback(self):
        self.run_native_route_confirmation()

    def test_high_tier_write_reports_preexisting_order_mismatch_without_projection(self):
        from fc_pricing_v3.ledger import confirmed_curve_window

        result = self.run_native_route_confirmation(order_rate='0.09')
        projection = result['curve_results'][PLATFORM]['projection']
        self.assertEqual(projection['status'], 'unchanged_mismatch')
        self.assertEqual(projection['reason'], 'pricing_curve_order_preexisting_rate_mismatch')
        self.assertEqual(projection['readback_rate'], '0.09')
        self.assertEqual(Decimal(projection['expected_rate']), Decimal('0.10'))
        action, _ = confirmed_curve_window(dict(operation_id=OPERATION, readback=dict(
            result, write_protocol=CURVE_WRITE_PROTOCOL), bundle=self.bundle))
        self.assertEqual(action['curves'][PLATFORM]['tiers'][1]['native_price_usd'], '103')

    def run_native_route_confirmation(self, *, order_rate=None):
        native = writer.curve_writer_capabilities()[PLATFORM]
        self.assertEqual(native['order_projection']['path'], '/game/admin_game_price/itemEdit?ids=21942')
        self.assertEqual(native['catalogue_status'], 'native_route_directory_unavailable')
        self.assertEqual(native['order_projection_status'], 'native_route_ready')
        bundle, _, *_ = setup_bundle()
        with self.assertRaisesRegex(ValueError, 'catalog_save_unverified'):
            writer.curve_catalog_plan(bundle, PLATFORM, native)
        self.prepare(propagate=False)
        if order_rate is not None:
            self.transport.projection_rate = order_rate
        original = self.transport.request
        rows = [self.transport.rows[ALL_ID], self.transport.rows[PRIMARY_ID]]

        def request(path, **kwargs):
            if path.startswith('/admin/goods.Goods/index?'):
                return 200, json.dumps(dict(code=1, data=dict(total=len(rows), list=rows)))
            return original(path, **kwargs)

        self.transport.request = request
        routes = writer.read_curve_routes(self.transport)
        self.assertEqual(routes[PLATFORM]['recipient_goods'], {'266': PRIMARY_ID})
        capability = writer.curve_writer_capabilities(routes)[PLATFORM]
        self.assertEqual(capability['catalogue_status'], 'native_route_ready')
        with self.assertRaisesRegex(ValueError, 'native_evidence_mismatch'):
            writer.curve_catalog_plan(self.bundle, PLATFORM, capability)
        proof = self.bundle['curve_proofs'][PLATFORM]
        proof['scope']['source_revisions']['propagation'] = routes[PLATFORM]['propagation_revision']
        proof['proof_hash'] = fingerprint({key: value for key, value in proof.items() if key != 'proof_hash'})
        self.bundle['curve_primary_before_hashes'] = {
            PLATFORM: fingerprint(writer.editable(self.transport.rows[PRIMARY_ID]))}
        capability['order_projection'] = self.transport.projection()
        self.capabilities = {PLATFORM: capability}
        self.audit['curve_results'][PLATFORM] = dict(writer.curve_catalog_plan(self.bundle, PLATFORM, capability),
                                                    operation_id=OPERATION)
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.transport.projection_writes, [])
        self.transport.apply_recipient()
        result = writer.reconcile_curve_catalog(self.transport, self.audit, self.saved, self.capabilities)
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertFalse(result['curve_results'][PLATFORM]['projection']['write_performed'])
        self.assertEqual(len(self.transport.posts), 1)
        return result

    def test_legacy_protocol_cannot_take_curve_request(self):
        self.prepare()
        self.assertEqual(write_protocol(self.bundle), CURVE_WRITE_PROTOCOL)
        self.assertIsNone(write_protocol(dict(action={'base_prices': {'PS': '10'}})))
        del self.bundle['write_protocol']
        with self.assertRaisesRegex(ValueError, 'write_protocol_invalid'):
            write_protocol(self.bundle)

    def test_empty_receipt_scope_cannot_confirm(self):
        self.prepare()
        self.audit['curve_results'] = {}
        with self.assertRaisesRegex(ValueError, 'original_scope_missing'):
            writer.curve_result(self.audit, self.saved)

    def test_original_reconciler_uses_v6_path_and_never_calls_old_order_reader(self):
        self.prepare(propagate=False)
        self.dispatch()
        self.transport.apply_recipient()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'executions').mkdir()
            self.audit.update(preview_id='preview', actor='wulv', selected=[PLATFORM],
                              automation_policy_revision=4)
            (root/'executions'/(OPERATION+'.json')).write_text(json.dumps(self.audit))
            request = dict(execution_id=OPERATION, v3_operation_id=OPERATION, preview_id='preview',
                           write_protocol=CURVE_WRITE_PROTOCOL, actor='wulv',
                           platforms=[PLATFORM], policy_revision=4)
            order = Mock(side_effect=AssertionError('legacy Order reader must not run'))
            with patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities), \
                 patch.object(writer.os, 'chown', getattr(writer.os, 'chown', Mock()), create=True):
                result = reconcile_original.reconcile(request, root, order, lambda: self.transport)
            self.assertEqual(result['status'], 'CONFIRMED')
            self.assertEqual(result['execution_id'], OPERATION)
            self.assertEqual(len(self.transport.posts), 1)
            order.assert_not_called()

    def test_send_fence_reads_real_original_plan_revision_lease_and_generation(self):
        self.prepare()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'v3').mkdir()
            (root/'config').mkdir()
            control = root/'config/v3-control.json'
            control.write_text(json.dumps(dict(enabled=True, generation='generation')))
            with closing(sqlite3.connect(root/'v3/control.sqlite3')) as conn:
                for table in ('operations', 'pricing_plans', 'metadata'):
                    conn.execute('CREATE TABLE ' + table + ' (id TEXT PRIMARY KEY, body TEXT)')
                conn.executescript('CREATE TABLE plan_ownership(resource, plan_id, revision, generation);'
                                   'CREATE TABLE resource_leases(resource, operation_id);')
                plan = dict(plan_id='plan', generation='generation', revision=4, state='ACTIVE')
                operation = dict(operation_id=OPERATION, bundle=self.bundle, generation='generation',
                                 plan_id='plan', revision=4, status='DISPATCHED',
                                 dispatch_context=dict(selected=[PLATFORM]),
                                 steps=[dict(kind='base', state='DISPATCHED', dispatched_at=NOW.isoformat())])
                conn.execute('INSERT INTO operations VALUES (?,?)', (OPERATION, json.dumps(operation)))
                conn.execute('INSERT INTO pricing_plans VALUES (?,?)', ('plan', json.dumps(plan)))
                conn.execute('INSERT INTO metadata VALUES (?,?)', ('generation', '{"id":"generation"}'))
                conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)', ('base:PS', 'plan', 4, 'generation'))
                conn.execute('INSERT INTO resource_leases VALUES (?,?)', ('base:PS', OPERATION))
                conn.commit()
                validate_curve_send(root, self.bundle, PLATFORM)
                conn.execute('UPDATE resource_leases SET operation_id=?', ('new-operation',))
                conn.commit()
                with self.assertRaisesRegex(ValueError, 'resource_fence_changed'):
                    validate_curve_send(root, self.bundle, PLATFORM)
                control.write_text(json.dumps(dict(enabled=True, generation='new-generation')))
                with self.assertRaisesRegex(ValueError, 'generation_retired'):
                    validate_curve_send(root, self.bundle, PLATFORM)


if __name__ == '__main__':
    unittest.main()
