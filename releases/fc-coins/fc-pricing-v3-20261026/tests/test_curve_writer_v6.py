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
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import coin_all_sync_job as writer
import reconcile_original
from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL, validate_curve_send, write_protocol
from fc_pricing_v3.financial import fingerprint
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


def setup_bundle(small='10', large='103', *, before_large='100', target_override=None):
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
    paths = dict(curve_key=key, paths=[quote('ordinary', key, regular_usd=large, net_receipt_usd=large)])
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
                      source_revisions=refs, recipient_goods={266: PRIMARY_ID})
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
        self.restore_linear = False
        self.projection_delayed = False

    def apply_recipient(self, goods_id=PRIMARY_ID):
        self.rows[goods_id]['unit_price'] = self.rows[ALL_ID]['unit_price']
        self.rows[goods_id]['more']['price'] = deepcopy(self.rows[ALL_ID]['more']['price'])

    def request(self, path, *, data, token):
        goods_id = int(path.split('=')[-1])
        if data is None:
            return 200, json.dumps(dict(code=1, data=dict(row=self.rows[goods_id])))
        self.posts.append((goods_id, deepcopy(data)))
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
        observe(dict(http_status=200, response_code=1, response_sha256='fixture',
                     path='synthetic-isolated-order-rate'))

    def projection(self):
        return dict(path='synthetic-isolated-order-rate', evidence_ref='synthetic-rate-contract',
                    read=lambda _: self.projection_rate, write=self.write_rate)


class CurveWriter(unittest.TestCase):
    def prepare(self, small='10', large='103', *, projection=True, propagate=True, before_large='100'):
        bundle, capability, before, recipient = setup_bundle(small, large, before_large=before_large)
        self.transport = Transport(before, recipient, propagate=propagate)
        if projection:
            capability['order_projection'] = self.transport.projection()
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
        self.prepare(small='12', projection=False)
        self.assertEqual(self.dispatch()['status'], 'PARTIAL')
        self.assertEqual(self.reconcile()['status'], 'PARTIAL')
        self.assertEqual(self.item['catalog']['status'], 'confirmed')
        self.assertEqual(self.item['propagation']['status'], 'confirmed')
        self.assertEqual(self.item['projection']['status'], 'unverified')
        self.assertEqual(len(self.transport.posts), 1)
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
