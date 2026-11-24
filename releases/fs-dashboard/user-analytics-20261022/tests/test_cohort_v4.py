import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'source'), str(ROOT.parent / 'customer-segments-20261124/source')]
from user_contract import stamp
from user_lifecycle import analyze_cohorts


def purchase(number, customer, paid, game='1327', amount='10'):
    return dict(order_key=str(number), customer_id=customer, paid_at=stamp(paid).isoformat(),
                gid=game, site='266', valid=True, body=json.dumps({'amount_usd': amount,
                'order_no_hash': hashlib.sha256(str(number).encode()).hexdigest()}))


def covering(start, end):
    return dict(site='266', state='complete', start=start, end=end)


class CohortWindows(unittest.TestCase):
    def test_inclusive_24h_exclusive_window_end_and_game_entry(self):
        orders = [
            purchase(1, 'exact', '2026-01-02T10:00:00'),
            purchase(2, 'exact', '2026-01-02T10:00:00'),
            purchase(3, 'exact', '2026-01-03T10:00:00', amount=None),
            purchase(4, 'exact', '2026-01-05T10:00:00', amount='7'),
            purchase(5, 'late', '2026-01-03T10:00:00'),
            purchase(6, 'late', '2026-01-05T10:00:00', amount='11'),
            purchase(7, 'unknown', '2026-01-03T10:00:00'),
            purchase(8, 'wrong-game', '2026-01-02T10:00:00', game='456'),
            purchase(9, 'wrong-game', '2026-01-03T10:00:00'),
        ]
        flags = {json.loads(o['body'])['order_no_hash']: 'new' for o in orders if o['customer_id'] != 'unknown'}
        query = dict(game='1327', cohort_start='2026-01', cohort_end='2026-01',
                     windows=[2, 3], return_after=2, return_within=4)
        result, members = analyze_cohorts(orders, [covering('2026-01-01', '2026-02-01')],
                                          query, stamp('2026-02-01'), flags)
        cohort = result['batches'][0]
        self.assertEqual(cohort['pending_classification'], 1)
        window = cohort['windows'][0]
        self.assertEqual((window['numerator'], window['denominator'], window['rate']), (1, 2, .5))
        self.assertEqual(window['repeat_amount'], {'known_usd': None, 'unknown_orders': 1})
        self.assertEqual(members[window['group']], {
            'exact': {'window_status': 'denominator', 'in_numerator': True},
            'late': {'window_status': 'denominator', 'in_numerator': False},
        })
        self.assertEqual(cohort['first_repeat']['counts'], [1, 1, 0])
        returned = cohort['silent_return']
        self.assertEqual((returned['numerator'], returned['denominator'], returned['return_amount']),
                         (1, 1, {'known_usd': '11', 'unknown_orders': 0}))


    def test_cutoff_and_coverage_buckets_are_disjoint_and_frozen(self):
        orders = [purchase(1, 'mature', '2026-01-01'), purchase(2, 'gap', '2026-01-09'),
                  purchase(3, 'observing', '2026-01-29'),
                  purchase(4, 'mature', '2026-01-02'),
                  purchase(5, 'observing', '2026-01-30')]
        flags = {json.loads(o['body'])['order_no_hash']: 'new' for o in orders}
        query = dict(game='all', cohort_start='2026-01', cohort_end='2026-01',
                     windows=[4], return_after=2, return_within=4)
        jobs = [covering('2026-01-01', '2026-01-10'), covering('2026-01-11', '2026-02-01')]
        result, members = analyze_cohorts(orders, jobs, query, stamp('2026-02-01'), flags)
        window = result['batches'][0]['windows'][0]
        self.assertEqual([window[k] for k in ('denominator', 'observing', 'coverage_gap')], [1, 1, 1])
        rows = members[window['group']]
        self.assertEqual(rows, {
            'mature': {'window_status': 'denominator', 'in_numerator': True},
            'gap': {'window_status': 'coverage_gap', 'in_numerator': False},
            'observing': {'window_status': 'observing', 'in_numerator': False},
        })
        for status in ('denominator', 'coverage_gap', 'observing'):
            self.assertEqual(sum(row['window_status'] == status for row in rows.values()), window[status])
        self.assertEqual(sum(row['in_numerator'] for row in rows.values()), window['numerator'])

    def test_partial_repeat_amount_cannot_supply_per_customer_amount(self):
        orders = [purchase(1, 'one', '2026-01-01'),
                  purchase(2, 'one', '2026-01-02', amount='17.25'),
                  purchase(3, 'one', '2026-01-03', amount=None)]
        flags = {json.loads(orders[0]['body'])['order_no_hash']: 'new'}
        query = dict(game='all', cohort_start='2026-01', cohort_end='2026-01',
                     windows=[4], return_after=2, return_within=4)
        result, _ = analyze_cohorts(orders, [covering('2026-01-01', '2026-02-01')],
                                    query, stamp('2026-02-01'), flags)
        window = result['batches'][0]['windows'][0]
        self.assertEqual(window['repeat_amount'], {'known_usd': '17.25', 'unknown_orders': 1})
        self.assertIsNone(window['repeat_per_customer_usd'])


class CustomerStages(unittest.TestCase):
    def test_stage_population_daily_returns_inflow_and_cross_game_use_game_thresholds(self):
        from user_lifecycle import analyze_stages
        orders = [
            purchase(1, 'wake', '2026-01-01'),
            purchase(2, 'wake', '2026-01-16'),
            purchase(3, 'lost', '2026-01-01'),
            purchase(4, 'lost', '2026-02-02'),
            purchase(5, 'shifted', '2026-01-01'),
            purchase(6, 'shifted', '2026-02-05', '456'),
            purchase(7, 'only-silent', '2026-01-25'),
            purchase(8, 'only-silent', '2026-02-05', '456'),
            purchase(9, 'outside', '2026-01-01'),
        ]
        jobs = [covering('2026-01-01', '2026-02-10')]
        cutoff = stamp('2026-02-10')
        config = {'version': 0, 'stages': {}, 'tiers': {}}
        filters = dict(start='2026-01-14', end_exclusive='2026-02-10', customer_type='all', repeat_status='all')
        game, groups, _ = analyze_stages(orders, jobs, dict(filters, game='1327'), cutoff, {}, config)
        self.assertEqual(groups['stage:silent'], {'wake', 'only-silent'})
        self.assertEqual(groups['stage:recent'], {'lost'})
        self.assertEqual(groups['entered:silent'], {'wake', 'lost', 'only-silent'})
        self.assertEqual(groups['entered:lost'], {'lost'})
        self.assertEqual(groups['return:silent_wakeup'], {'wake'})
        self.assertEqual(groups['return:lost_return'], {'lost'})
        self.assertIn(dict(date='2026-01-16', silent_wakeup=1, lost_return=0), game['daily_returns'])
        self.assertIn(dict(date='2026-02-02', silent_wakeup=0, lost_return=1), game['daily_returns'])
        all_games, groups, _ = analyze_stages(orders, jobs, dict(filters, game='all'), cutoff, {}, config)
        self.assertEqual(groups['flow:1327:456'], {'shifted'})
        self.assertEqual(all_games['cross_game_flow'], [dict(source='1327', destination='456', count=1,
                                                            group='flow:1327:456')])


class V4Snapshot(unittest.TestCase):
    def test_frozen_result_is_shared_and_a_retired_snapshot_cannot_be_reinterpreted(self):
        from unittest.mock import Mock
        from user_query import Service

        config = dict(sites={'266': {'label': 'MMOEXP'}}, projects={'1327': {'label': 'FC27'}},
                      history_backfill_start='2026-01-01', scope_version='s', identity_version='i')
        store = Mock(config=config)
        store.snapshot_public.return_value = ({}, {'contract_version': 'fs-users-v3-period-cohort'})
        grants = {'analyst'}
        service = Service(store, lambda user, query, private: user in grants and not private)
        self.addCleanup(service.v4.jobs.pool.shutdown)
        with self.assertRaisesRegex(ValueError, 'snapshot_version_retired'):
            service.v4.get({'snapshot_id': 'us_' + 'a' * 32}, 'analyst')
        grants.clear()
        with self.assertRaises(PermissionError):
            service.v4.get({'snapshot_id': 'us_' + 'a' * 32}, 'analyst')


    def test_page_connector_and_hermes_share_one_continuation(self):
        from threading import Event
        from unittest.mock import Mock, patch
        from user_http import get
        from user_query import Service

        service = Service(Mock(), lambda user, query, private: user == 'alice')
        ready = Event()
        calls = []

        def query(args, owner):
            if 'snapshot_id' not in args:
                calls.append((args, owner))
                self.assertTrue(ready.wait(5))
            return dict(snapshot_id='frozen', cohorts={'batches': []}, stages={'inflow': []}, query={})

        service.v4.jobs.query = query
        service.v4.read_context = Mock(return_value=(
            {'projects': {'456': {}, '552': {}}, 'history_backfill_start': '2026-01-01'},
            None, stamp('2026-02-01')))
        self.addCleanup(service.v4.jobs.pool.shutdown)
        self.addCleanup(ready.set)
        budgets = []
        with patch('user_summary_jobs.wait', side_effect=lambda futures, timeout: budgets.append(timeout)):
            code, page = get(service, '/users', {'action': ['summary'], 'game': ['all']}, 'alice')
            self.assertEqual(code, 202)
            code, connector = get(service, '/users', {'action': ['connector_summary']}, 'alice')
            self.assertEqual((code, connector['query_id']), (202, page['query_id']))
            code, hermes = get(service, '/users', {'action': ['tool'], 'game': ['all'], 'section': ['stages']}, 'alice')
            self.assertEqual((code, hermes['query_id']), (202, page['query_id']))
        self.assertEqual(budgets, [10])
        target = {'action': ['connector_section'], 'query_id': [page['query_id']], 'section': ['stages']}
        self.assertEqual(get(service, '/users', dict(target, game=['all']), 'alice')[0], 422)
        self.assertEqual(get(service, '/users', target, 'other')[0], 404)
        ready.set()
        service.v4.jobs.pool.shutdown()
        code, part = get(service, '/users', target, 'alice')
        self.assertEqual((code, part['snapshot_id'], part['stages']), (200, 'frozen', {'inflow': []}))
        self.assertNotIn('cohorts', part)
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0][0]['game'], calls[0][1]), ('all', 'alice'))


    @unittest.skipUnless(sys.platform != 'win32', 'requires POSIX private-store permissions')
    def test_reader_page_export_and_search_recheck_grant_on_same_frozen_snapshot(self):
        import tempfile
        from test_users import order
        from user_http import get, search
        from user_query import Service
        from user_store import Store

        config = json.loads((ROOT/'source/user_config.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'private', b'1'*32, config)
            now = stamp('2026-02-05T13:00:00')
            email = 'phase1-fixture@example.test'
            rows = [order(1, '2026-01-01', email=email), order(2, '2026-01-02', email=email)]
            store.replace_window('266', '2026-01-01', '2026-02-05', rows, now.isoformat())
            flag = hashlib.sha256(b'test-1').hexdigest()
            allowed = {'reader'}
            service = Service(store, lambda user, q, private: user in allowed and not private,
                              clock=lambda: now, customer_type_reader=lambda q: ({flag: 'new'}, {'status': 'complete'}),
                              permission_epoch=lambda user, q: 'fixture-user-policy')
            self.addCleanup(service.v4.jobs.pool.shutdown)
            query = {'cohort_start': '2026-01', 'cohort_end': '2026-01', 'windows': [2]}
            first = service.v4.query(query, 'reader')
            ident = first['snapshot_id']
            group = first['cohorts']['batches'][0]['windows'][0]['group']
            params = {'snapshot_id': [ident], 'group': [group]}
            status, page = get(service, '/users/private', params, 'reader')
            self.assertEqual((status, page['total'], page['rows'][0]['email']), (200, 1, email))
            self.assertEqual((page['rows'][0]['last_paid_at'], page['rows'][0]['stage']),
                             ('2026-01-02T00:00:00+08:00', 'silent'))
            code, export = get(service, '/users/private', dict(params, action=['export']), 'reader')
            self.assertEqual((code, export['exported_rows']), (200, 1))
            self.assertIn(email, export['csv'])
            self.assertIn('"已满窗（分母）","是"', export['csv'])
            self.assertEqual(get(service, '/users/private', dict(params, action=['connector_members']), 'reader')[0], 403)
            status, found = search(service, {'snapshot_id': ident, 'email': email}, 'reader')
            self.assertTrue(found['found'])
            self.assertEqual((status, len(found['orders'])), (200, 2))
            self.assertEqual([event['kind'] for event in found['timeline'] if event['kind'] != 'enter'],
                             ['first_order', 'repeat'])
            self.assertEqual(search(service, {'source':'connector', 'snapshot_id':ident, 'email':email}, 'reader')[0], 403)
            store.replace_window('266', '2026-01-01', '2026-02-05', [], now.isoformat())
            code, frozen = get(service, '/users/private', dict(params, action=['export']), 'reader')
            self.assertEqual((code, frozen['csv']), (200, export['csv']))
            allowed.clear()
            self.assertEqual(get(service, '/users/private', dict(params, action=['export']), 'reader')[0], 403)
            self.assertEqual(search(service, {'snapshot_id': ident, 'email': email}, 'reader')[0], 403)
