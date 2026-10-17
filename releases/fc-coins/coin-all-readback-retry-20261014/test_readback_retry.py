"""Offline regressions for the bounded read-only ALL readback confirmation.

Standard library only, no network and no second process: the CI dispatcher runs
this in an interpreter whose sockets reject non-local addresses and whose
subprocess.Popen is replaced by a rejecting stub.
"""
from copy import deepcopy
from decimal import Decimal
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'source'))
import coin_all_sync_job as coins

PLATFORMS = ('PS', 'XBOX', 'PC')
EXECUTION_ID = '11111111-1111-4111-8111-111111111111'
POLICY = {'system_enabled': True, 'mode': 'auto', 'revision': 30, 'platforms': list(PLATFORMS)}
TIERS = [str((index + 1) * 100) for index in range(15)]
AIDS = {platform: coins.PRODUCTS[platform][2] for platform in PLATFORMS}
ALL_IDS = {platform: coins.PRODUCTS[platform][0] for platform in PLATFORMS}
SOURCE_IDS = {platform: coins.PRODUCTS[platform][1] for platform in PLATFORMS}

# Synthetic fixtures only: this repository keeps real price levels and job
# identifiers out of version control. The shapes match the live product rows
# (three sites, fifteen tiers, one all-site and one MMOEXP product per platform).
OLD_ALL = {'PS': '0.1400', 'XBOX': '0.1400', 'PC': '0.1050'}
NEW_MMOEXP = {'PS': '0.1200', 'XBOX': '0.1200', 'PC': '0.1050'}
OLD_ALL_THREE = {'PS': '0.1500', 'XBOX': '0.1460', 'PC': '0.1100'}


def make_row(product_id, site, aid, unit_price):
    unit = Decimal(str(unit_price))
    size = len(TIERS)
    return {'id': product_id, 'mid': 41217957, 'gid': 1327, 'cid': 9623,
            'site_id': site, 'aid': aid, 'unit': 'K', 'title': 'coins', 'status': 1,
            'unit_price': str(unit),
            'more': {'gold': list(TIERS),
                     'price': [str(unit * Decimal(tier)) for tier in TIERS],
                     'discount': ['100'] * size, 'give': ['0'] * size,
                     'delivery_time': ['1'] * size, 'hot': ['0'] * size}}


def build_rows(old_all, new_mmoexp):
    rows = {}
    for platform in PLATFORMS:
        rows[ALL_IDS[platform]] = make_row(ALL_IDS[platform], 0, AIDS[platform], old_all[platform])
        rows[SOURCE_IDS[platform]] = make_row(SOURCE_IDS[platform], 266, AIDS[platform], new_mmoexp[platform])
    return rows


class Backend:
    """Minimal goods.Goods backend: GET returns a row, POST replaces it."""

    def __init__(self, rows, stale_reads_after_post=0, flap_rows=None, reject_posts=False):
        self.token = 'offline-test-token'
        self.rows = deepcopy(rows)
        self.stale_reads_after_post = stale_reads_after_post
        self.flap_rows = {key: deepcopy(value) for key, value in (flap_rows or {}).items()}
        self.reject_posts = reject_posts
        self.gets = []
        self.posts = []
        self.stale_row = None
        self.remaining_stale = 0
        self.read_index = 0

    def request(self, path, data=None, token=None):
        if path == '/admin/index/index':
            return 200, json.dumps({'code': 1, 'data': {'adminInfo': {'username': 'chenchao'}}})
        product_id = int(path.rsplit('=', 1)[1])
        if data is not None:
            self.posts.append(product_id)
            if self.reject_posts:
                return 200, json.dumps({'code': 0, 'msg': 'rejected'})
            self.stale_row = deepcopy(self.rows[product_id])
            self.rows[product_id] = deepcopy(data)
            self.remaining_stale = self.stale_reads_after_post
            return 200, json.dumps({'code': 1, 'data': {'row': self.rows[product_id]}})
        self.gets.append(product_id)
        if product_id in self.flap_rows:
            row = self.flap_rows[product_id] if self.read_index % 2 == 0 else self.rows[product_id]
            self.read_index += 1
        elif self.remaining_stale > 0:
            self.remaining_stale -= 1
            row = self.stale_row
        else:
            row = self.rows[product_id]
        return 200, json.dumps({'code': 1, 'data': {'row': deepcopy(row)}})


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ReadbackRetryTests(unittest.TestCase):
    def setUp(self):
        # Never wait for real: the retry loop is bounded by rounds, not by wall time.
        pauser = patch.object(coins.time, 'sleep', lambda _: None)
        pauser.start()
        self.addCleanup(pauser.stop)
        # drive() imports the pre-write gate lazily; the module is not shipped here.
        gate = patch.dict(sys.modules, {'automation_policy': types.SimpleNamespace(
            hooks_before_write=lambda *args, **kwargs: None)})
        gate.start()
        self.addCleanup(gate.stop)

    # ---- drive(): the real dispatch path -------------------------------------

    def run_drive(self, backend, new_mmoexp):
        audit = {'execution_id': EXECUTION_ID, 'status': 'PARTIAL', 'stage': 'all_baseline_pending',
                 'sync_confirmed': True, 'automatic': True,
                 'automation_policy_revision': POLICY['revision'],
                 'after': {'rows': [{'platform': p, 'b2c': str(new_mmoexp[p])} for p in PLATFORMS]}}
        steps = coins.plan(backend, audit, POLICY)
        record = {'execution_id': EXECUTION_ID, 'status': 'preflight',
                  'steps': [{k: deepcopy(step[k]) for k in ('platform', 'product_id', 'source_product_id',
                                                            'before', 'source', 'payload', 'changed')}
                            | {'status': 'pending'} for step in steps]}
        self.audit, self.ledger = audit, record
        written = []
        self.result = coins.drive(backend, audit, POLICY, steps, record,
                                  lambda value: written.append(deepcopy(value)),
                                  lambda value: written.append(deepcopy(value)),
                                  lambda: POLICY)
        return self.result

    def test_transient_stale_first_read_confirms_without_a_second_post(self):
        backend = Backend(build_rows(OLD_ALL_THREE, NEW_MMOEXP), stale_reads_after_post=1)
        result = self.run_drive(backend, NEW_MMOEXP)
        self.assertEqual(result['status'], 'confirmed')
        # Exactly one POST per changed product, in PRODUCTS order, never repeated.
        self.assertEqual(backend.posts, [ALL_IDS[p] for p in PLATFORMS])
        for item in self.ledger['steps']:
            proof = item['dispatch_readback']
            self.assertEqual(proof['status'], 'confirmed')
            self.assertEqual(proof['price_posts_retried'], 0)
            self.assertTrue(proof['read_only'])
            self.assertEqual(len(proof['rounds']), 3)
            self.assertEqual([row['matched'] for row in proof['rounds']], [False, True, True])
            self.assertEqual(proof['rounds'][0]['unit_price'], OLD_ALL_THREE[item['platform']])
            self.assertEqual(proof['rounds'][1]['unit_price'], NEW_MMOEXP[item['platform']])
        self.assertEqual(self.audit['status'], 'CONFIRMED')
        self.assertEqual(self.audit['all_baseline']['status'], 'confirmed')

    def test_persistent_stale_read_stops_bounded_and_never_posts_the_next_product(self):
        backend = Backend(build_rows(OLD_ALL_THREE, NEW_MMOEXP), stale_reads_after_post=10 ** 6)
        with self.assertRaisesRegex(ValueError, 'coin_all_readback_mismatch'):
            self.run_drive(backend, NEW_MMOEXP)
        self.assertEqual(backend.posts, [ALL_IDS['PS']])
        self.assertEqual(self.ledger['status'], 'needs_reconcile')
        self.assertEqual(self.audit['all_baseline'], {'status': 'needs_reconcile'})
        proof = self.ledger['steps'][0]['dispatch_readback']
        self.assertEqual(proof['status'], 'stopped')
        self.assertEqual(proof['reason'], 'coin_all_readback_timeout')
        self.assertEqual(proof['price_posts_retried'], 0)
        self.assertTrue(2 <= len(proof['rounds']) <= 12)
        self.assertTrue(all(not row['matched'] for row in proof['rounds']))

    def test_unchanged_product_is_verified_once_and_never_posted(self):
        backend = Backend(build_rows(OLD_ALL, NEW_MMOEXP))
        result = self.run_drive(backend, NEW_MMOEXP)
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(backend.posts, [ALL_IDS['PS'], ALL_IDS['XBOX']])
        self.assertFalse(self.ledger['steps'][2]['changed'])
        self.assertNotIn('dispatch_readback', self.ledger['steps'][2])

    def test_changed_source_after_planning_still_stops_before_any_post(self):
        backend = Backend(build_rows(OLD_ALL_THREE, NEW_MMOEXP))
        audit = {'execution_id': EXECUTION_ID, 'status': 'PARTIAL', 'stage': 'all_baseline_pending',
                 'sync_confirmed': True, 'automatic': True,
                 'automation_policy_revision': POLICY['revision'],
                 'after': {'rows': [{'platform': p, 'b2c': str(NEW_MMOEXP[p])} for p in PLATFORMS]}}
        steps = coins.plan(backend, audit, POLICY)
        backend.rows[SOURCE_IDS['PS']] = make_row(SOURCE_IDS['PS'], 266, AIDS['PS'], '0.1350')
        record = {'execution_id': EXECUTION_ID, 'status': 'preflight',
                  'steps': [{k: deepcopy(step[k]) for k in ('platform', 'product_id', 'source_product_id',
                                                            'before', 'source', 'payload', 'changed')}
                            | {'status': 'pending'} for step in steps]}
        with self.assertRaisesRegex(ValueError, 'coin_source_or_before_changed'):
            coins.drive(backend, audit, POLICY, steps, record, lambda value: None,
                        lambda value: None, lambda: POLICY)
        self.assertEqual(backend.posts, [])

    def test_rejected_write_is_not_retried_or_masked(self):
        backend = Backend(build_rows(OLD_ALL_THREE, NEW_MMOEXP), reject_posts=True)
        with self.assertRaisesRegex(ValueError, 'coin_backend_request_rejected'):
            self.run_drive(backend, NEW_MMOEXP)
        self.assertEqual(backend.posts, [ALL_IDS['PS']])
        self.assertEqual(self.ledger['status'], 'needs_reconcile')

    # ---- verify_dispatch_readback(): the bounded read-only loop --------------

    def step_for(self, platform, old_all, new_mmoexp):
        before = make_row(ALL_IDS[platform], 0, AIDS[platform], old_all[platform])
        source = make_row(SOURCE_IDS[platform], 266, AIDS[platform], new_mmoexp[platform])
        payload = coins.editable(before)
        payload['unit_price'] = deepcopy(source['unit_price'])
        payload['more']['price'] = deepcopy(source['more']['price'])
        return {'platform': platform, 'product_id': ALL_IDS[platform],
                'source_product_id': SOURCE_IDS[platform], 'before': before,
                'source': source, 'payload': payload, 'changed': True}

    def test_helper_requires_two_stable_rounds_even_when_the_first_read_matches(self):
        backend = Backend(build_rows(NEW_MMOEXP, NEW_MMOEXP))
        step = self.step_for('PS', NEW_MMOEXP, NEW_MMOEXP)
        item, record = {}, {'steps': [{}]}
        clock = FakeClock()
        actual = coins.verify_dispatch_readback(backend, step, step['source'], item, record,
                                                lambda value: None, clock=clock, sleep=clock.sleep)
        self.assertEqual(actual['unit_price'], step['source']['unit_price'])
        self.assertEqual(backend.posts, [])
        self.assertEqual(len(item['dispatch_readback']['rounds']), 2)
        self.assertEqual(item['dispatch_readback']['status'], 'confirmed')

    def test_helper_never_posts_and_stays_bounded_when_the_row_flaps(self):
        backend = Backend(build_rows(NEW_MMOEXP, NEW_MMOEXP),
                          flap_rows={ALL_IDS['PS']: make_row(ALL_IDS['PS'], 0, AIDS['PS'],
                                                             OLD_ALL['PS'])})
        step = self.step_for('PS', OLD_ALL, NEW_MMOEXP)
        item, record = {}, {'steps': [{}]}
        clock = FakeClock()
        with self.assertRaisesRegex(ValueError, 'coin_all_readback_mismatch'):
            coins.verify_dispatch_readback(backend, step, step['source'], item, record,
                                           lambda value: None, clock=clock, sleep=clock.sleep)
        self.assertEqual(backend.posts, [])
        proof = item['dispatch_readback']
        self.assertEqual(proof['status'], 'stopped')
        self.assertEqual(proof['price_posts_retried'], 0)
        self.assertEqual(len(proof['rounds']), 12)
        self.assertTrue(clock.now <= coins.READBACK_STEP_SECONDS)
        self.assertEqual([row['matched'] for row in proof['rounds']][:4], [False, True, False, True])

    def test_helper_budget_is_capped_by_the_step_budget(self):
        backend = Backend(build_rows(NEW_MMOEXP, NEW_MMOEXP))
        step = self.step_for('PS', NEW_MMOEXP, NEW_MMOEXP)
        item, record = {}, {'steps': [{}]}
        clock = FakeClock()
        coins.verify_dispatch_readback(backend, step, step['source'], item, record, lambda value: None,
                                       max_seconds=10 ** 6, clock=clock, sleep=clock.sleep)
        self.assertEqual(item['dispatch_readback']['max_seconds'], coins.READBACK_STEP_SECONDS)
        self.assertLess(coins.READBACK_TOTAL_SECONDS, 60)

    def test_helper_with_no_budget_left_still_completes_the_minimum_proof(self):
        backend = Backend(build_rows(NEW_MMOEXP, NEW_MMOEXP))
        step = self.step_for('PS', NEW_MMOEXP, NEW_MMOEXP)
        item, record = {}, {'steps': [{}]}
        clock = FakeClock()
        coins.verify_dispatch_readback(backend, step, step['source'], item, record, lambda value: None,
                                       max_seconds=-5, clock=clock, sleep=clock.sleep)
        self.assertEqual(item['dispatch_readback']['max_seconds'], 0)
        self.assertEqual(len(item['dispatch_readback']['rounds']), 2)
        self.assertEqual(clock.now, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
