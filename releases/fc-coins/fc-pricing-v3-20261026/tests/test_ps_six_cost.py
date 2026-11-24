"""Offline contracts for PS latest-six maximum and shared console costs."""
import importlib.util
import sys
import types
import unittest
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3.financial import common_cost


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SixCost(unittest.TestCase):
    def setUp(self):
        self.closed = 0
        tab = self.tab = types.SimpleNamespace()
        browser = types.SimpleNamespace(contexts=[types.SimpleNamespace(new_page=lambda: tab)])
        def close(page):
            self.closed += 1
        stubs = {
            'isolated_backend': types.SimpleNamespace(open_backend=lambda _: browser, close_backend=close),
            'fs_order_client': types.SimpleNamespace(apply=lambda _: None),
            'p2pah_session_service': types.SimpleNamespace(read_private_config=lambda: {}),
            'playwright.sync_api': types.SimpleNamespace(TimeoutError=TimeoutError, sync_playwright=lambda: nullcontext(None)),
            'fc27_quote_engine': types.SimpleNamespace(source_coverage=lambda _: None),
        }
        with patch.dict(sys.modules, stubs):
            try:
                self.collector = load('six_cost_collector', SOURCE/'collect_p2pah_cost.py')
            except __import__('zoneinfo').ZoneInfoNotFoundError:
                with patch('zoneinfo.ZoneInfo', lambda _: timezone(timedelta(hours=8))):
                    self.collector = load('six_cost_collector', SOURCE/'collect_p2pah_cost.py')
            self.snapshot = load('six_snapshot', SOURCE/'snapshot_layer.py')
        self.native_verifier = patch.object(self.collector, 'verified_delivery_cost',
            side_effect=lambda _, row, __, **kwargs: {k: v for k, v in row.items() if k != 'order_delivery'})
        self.native_verifier.start()
        self.addCleanup(self.native_verifier.stop)
        self.now = datetime.now(timezone(timedelta(hours=8))) - timedelta(minutes=1)
        self.rows = [self.raw(100+i, cost, i) for i, cost in enumerate(('.1','.2','.9','.4','.5','.6','99'))]
        self.rows += [self.raw(200, '888', 0, 'XBOX'), self.raw(300, '.77', 0, 'PC')]

    def raw(self, record_id, cost, age, platform='PS'):
        return dict(platform=platform, record_id=str(record_id), cny_per_1k=cost,
                    trade_at=(self.now-timedelta(minutes=age)).strftime('%Y-%m-%d %H:%M:%S'),
                    delivery_type='订单发货')

    def data(self, rows):
        return dict(rows=rows, hasDataRows=bool(rows), empty=not rows,deliveryRowCount=len(rows))

    def run_collect(self, pages=None, *, curve_v6=False):
        pages = pages or [self.rows, []]
        self.v6_windows = []
        def read(tab, number, observations=None, window=None):
            rows=pages[number-1] if number <= len(pages) else []
            if window and window.get('area') == '0':
                self.v6_windows.append(window)
            return self.data([row for row in rows if row['platform']=='PS']
                             if window and window.get('area', '21942') == '21942' else rows)
        with patch.object(self.collector, 'read_page', side_effect=read):
            return self.collector.collect(curve_v6=curve_v6)

    def test_latest_six_then_max_excludes_expensive_seventh_and_xbox(self):
        result = self.run_collect()
        self.assertEqual(result['status'], 'valid')
        ps, xbox, pc = result['costs']
        self.assertEqual([r['record_id'] for r in ps['sample_records']], ['100','101','102','103','104','105'])
        self.assertEqual((ps['record_id'], ps['cny_per_1k']), ('102','0.9'))
        self.assertEqual((xbox['record_id'], xbox['cny_per_1k'], xbox['source_platform']), ('102','0.9','PS'))
        self.assertEqual(xbox['observed_cost']['cny_per_1k'], '888')
        self.assertEqual((pc['record_id'], pc['cny_per_1k']), ('300','0.77'))
        normalized = self.snapshot.cost_snapshots('offline-run', result)
        cost, proof = common_cost(dict(costs={row['platform']:row for row in normalized}))
        self.assertEqual(cost, Decimal('.9'))
        self.assertEqual(proof['sample_size'], 6)
        self.assertEqual(len(proof['observations']), 6)
        self.assertEqual(self.closed, 1)

    def test_v6_retains_each_platforms_three_hour_deliveries_without_console_aliasing(self):
        rows = [self.raw(1000+index*100+i, '.4', i*2, platform)
                for index, platform in enumerate(('PS', 'XBOX', 'PC')) for i in range(7)]
        rows.sort(key=lambda row: row['trade_at'], reverse=True)
        result = self.run_collect([rows, []], curve_v6=True)
        self.assertTrue(self.v6_windows)
        self.assertEqual(self.v6_windows[0]['end'] - self.v6_windows[0]['start'], timedelta(hours=3))
        for cost in result['costs']:
            samples = cost['v6_delivery_samples']
            self.assertTrue(samples['window_complete'])
            self.assertFalse(samples['history_complete'])
            self.assertEqual(len(samples['records']), 7)
            self.assertEqual({row['platform'] for row in samples['records']}, {cost['platform']})

    def test_v6_retries_slow_order_detail_in_the_same_complete_window(self):
        self.native_verifier.stop()
        rows, details = [], {}
        for index, platform in enumerate(('PS', 'XBOX', 'PC')):
            for i in range(6):
                delivery_id, order_id = str(100+index*10+i), str(300+index*10+i)
                rows.append(dict(self.raw(delivery_id, '.4', i, platform),
                                 order_id=order_id, quantity='500', gift='0', cost_total='200'))
                details[order_id] = dict(complete=True,
                    goods=[dict(pid='9', gid='1322', cid='1', unit='K', qty='500', used='500')],
                    deliveries=[dict(id=delivery_id, pid='9', qty='500', gift='0', price='.4', total='200')])

        slow_order = '300'
        attempts, batches = [], []

        def read_order(order_id, timeout_ms):
            attempts.append([order_id, timeout_ms])
            if order_id == slow_order and timeout_ms == 8000:
                return {'timed_out': True}
            return details[order_id]

        def evaluate(expression, request):
            if expression == self.collector.READ_ORDER:
                return read_order(*request)
            batches.append(request)
            values = []
            for order_id in request:
                detail = read_order(order_id, 8000)
                values.append(read_order(order_id, 16000) if detail.get('timed_out') else detail)
            return values

        self.tab.evaluate = Mock(side_effect=evaluate)
        result = self.run_collect([rows, []], curve_v6=True)
        self.assertEqual([item[1] for item in attempts if item[0] == slow_order], [8000, 16000])
        self.assertEqual(len(attempts), 19)
        self.assertEqual([len(batch) for batch in batches], [2] * 9)
        self.assertEqual(self.closed, 1)
        for cost in result['costs']:
            samples = cost['v6_delivery_samples']
            self.assertTrue(samples['window_complete'])
            self.assertEqual(len(samples['records']), 6)
            self.assertEqual(Decimal(cost['cny_per_1k']), Decimal('.4'))

        # A single unverified order keeps only its own platform out of pricing.
        self.tab.evaluate = Mock(side_effect=lambda expression, request: [
            {'timed_out': True} if order_id == slow_order else details[order_id] for order_id in request])
        partial = self.snapshot.cost_snapshots(
            'offline', self.run_collect([rows, []], curve_v6=True), curve_v6=True)
        self.assertEqual([(row['platform'], row['status']) for row in partial],
                         [('PS', 'missing'), ('XBOX', 'valid'), ('PC', 'valid')])
        self.assertEqual(partial[0]['reason'], 'cost_order_detail_timeout')
        self.assertFalse(partial[0]['v6_delivery_samples']['window_complete'])
        self.assertEqual([len(row['v6_delivery_samples']['records']) for row in partial[1:]], [6, 6])
        self.assertEqual([order_id for call in self.tab.evaluate.call_args_list for order_id in call.args[1]
                          if str(order_id).startswith('30')], [slow_order])

        self.tab.evaluate = Mock(return_value=[None, None])
        with self.assertRaisesRegex(ValueError, 'cost_order_detail_unavailable'):
            self.run_collect([rows, []], curve_v6=True)
        self.assertEqual([call.args[1] for call in self.tab.evaluate.call_args_list],
                         [[slow_order, '310']])

        first_pair = [details[slow_order], details['310']]
        for response in (first_pair[:1], [first_pair[0], {'goods': [], 'complete': True}]):
            with self.subTest(response=response):
                self.tab.evaluate = Mock(return_value=response)
                with self.assertRaisesRegex(ValueError, 'cost_order_detail_response_unverified'):
                    self.run_collect([rows, []], curve_v6=True)
                self.assertEqual(self.tab.evaluate.call_count, 1)

        self.tab.evaluate = Mock(return_value=first_pair)
        with patch.object(self.collector, 'verified_delivery_cost', side_effect=ValueError('verification_failed')):
            with self.assertRaisesRegex(ValueError, 'verification_failed'):
                self.run_collect([rows, []], curve_v6=True)
        self.assertEqual(self.tab.evaluate.call_count, 1)

    def test_v6_pending_pairs_include_current_order_after_a_platform_times_out(self):
        deliveries = [(None, dict(platform=platform, order_delivery={'order_id': order}))
                      for order, platform in (('1', 'PS'), ('2', 'PS'), ('3', 'PS'), ('4', 'PS'),
                                              ('5', 'PC'), ('2', 'XBOX'), ('3', 'XBOX'), ('4', 'XBOX'))]
        detail = dict(complete=True, goods=[], deliveries=[])
        self.tab.evaluate = Mock(side_effect=lambda expression, pair: [
            {'timed_out': True} if order == '1' else detail for order in pair])
        timed_out = set()
        with patch.object(self.collector, 'verified_delivery_cost', return_value=None):
            evidence = list(self.collector.verified_v6_deliveries(self.tab, deliveries, {}, timed_out))
        self.assertEqual(timed_out, {'PS'})
        self.assertEqual([record['platform'] for record, _ in evidence], ['PC', 'XBOX', 'XBOX', 'XBOX'])
        self.assertEqual([call.args[1] for call in self.tab.evaluate.call_args_list],
                         [['1', '2'], ['5', '3'], ['4']])

    def test_sparse_ps_does_not_block_independent_v6_xbox_and_pc_costs(self):
        rows = [self.raw(1000+index*100+i, '.4', i, platform)
                for index, platform in enumerate(('PS', 'XBOX', 'PC')) for i in range(4 if platform == 'PS' else 6)]
        result = self.run_collect([rows, []], curve_v6=True)
        normalized = self.snapshot.cost_snapshots('offline', result, curve_v6=True)
        self.assertEqual([len(row['v6_delivery_samples']['records']) for row in normalized], [4, 6, 6])
        self.assertEqual(result['cost_protocol'], 'fc27_curve_v6')

    def test_v6_expands_again_when_an_outlier_leaves_only_five_valid_samples(self):
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost

        rows = [self.raw(1000+index*100+i, '.9' if platform == 'PS' and i == 5 else '.4', i, platform)
                for index, platform in enumerate(('PS', 'XBOX', 'PC')) for i in range(6)]
        older = self.raw(999, '.4', 240, 'PS')
        windows = []
        def read(tab, page, observations=None, window=None):
            hours = (window['end']-window['start']).total_seconds() / 3600
            windows.append(hours)
            return self.data(rows + ([older] if hours > 3 else []) if page == 1 else [])
        with patch.object(self.collector, 'read_page', side_effect=read):
            result = self.collector.collect(curve_v6=True, confirmed_costs={p: '.4' for p in ('PS', 'XBOX', 'PC')})
        ps = result['costs'][0]
        smoothed = smooth_delivery_cost(ps, 'PS', datetime.now(timezone.utc), '.4')
        self.assertEqual(smoothed['status'], 'valid')
        self.assertEqual(smoothed['selected_count'], 6)
        self.assertEqual(smoothed['cny_per_1k'], '0.4')
        self.assertIn(6, windows)

    def test_v6_reads_only_older_details_needed_by_each_platform(self):
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost
        rows = [self.raw(1100 + platform_index * 100 + i, '.4', i, platform)
                for platform_index, platform in enumerate(('PS', 'XBOX', 'PC'))
                for i in range(5 if platform == 'PC' else 7)]
        extras = [self.raw(10000, '.5', 240, 'PC'), self.raw(9999, '.6', 240, 'PC'),
                  self.raw(8001, '.9', 250, 'PC'), self.raw(8002, '.8', 240, 'PS'),
                  self.raw(8003, '.8', 240, 'XBOX')]
        rows.extend(extras)
        details = {}
        for row in rows:
            record_id = row['record_id']
            total = str(Decimal(row['cny_per_1k']) * 100)
            row.update(order_id=record_id, quantity='100', gift='0', cost_total=total)
            details[record_id] = dict(complete=True,
                goods=[dict(pid='9', gid='1322', cid='1', unit='K', qty='100', used='100')],
                deliveries=[dict(id=record_id, pid='9', qty='100', gift='0',
                                 price=row['cny_per_1k'], total=total)])
        self.native_verifier.stop()
        requests, windows = [], []

        def evaluate(_, ids):
            requests.extend(ids)
            return [details[order_id] for order_id in ids]

        def read(tab, page, observations=None, window=None):
            if page == 1:
                windows.append(window)
            return self.data([row for row in rows if window['start'] <=
                             datetime.fromisoformat(row['trade_at']).replace(tzinfo=self.collector.SHANGHAI)
                             <= window['end']] if page == 1 else [])

        self.tab.evaluate = evaluate
        with patch.object(self.collector, 'read_page', side_effect=read):
            result = self.collector.collect(curve_v6=True, confirmed_costs={p: '.4' for p in self.collector.PLATFORMS})
        self.assertEqual([w['end'] - w['start'] for w in windows],
                         [timedelta(hours=3), timedelta(hours=6)])
        self.assertEqual(windows[0]['end'], windows[1]['end'])
        self.assertEqual(len(requests), 20)
        self.assertEqual(set(requests) & {r['order_id'] for r in extras}, {'9999'})
        costs = [smooth_delivery_cost(row, row['platform'], datetime.now(timezone.utc), '.4')
                 for row in result['costs']]
        self.assertEqual([row['selected_count'] for row in costs], [7, 7, 6])
        self.assertEqual([row['cny_per_1k'] for row in costs], ['0.4'] * 3)
        self.assertEqual(costs[-1]['sample_records'][-1]['record_id'], '9999')
        self.assertEqual([row['v6_delivery_samples']['detail_scope']['older_detail_rows_not_checked']
                          for row in result['costs']], [1, 1, 2])

    def test_v6_full_expand_refreshes_amended_detail_and_checks_late_insert(self):
        rows = [self.raw(1000+index*100+i, '.4', i, platform)
                for index, platform in enumerate(('PS', 'XBOX', 'PC'))
                for i in range(5 if platform == 'PC' else 6)]
        late = self.raw(9999, '.5', 60)
        older = self.raw(9998, '.4', 240, 'PC')
        amended = dict(rows[0], cny_per_1k='.5')
        requests = []
        for row in rows + [late, older, amended]:
            row.update(order_id=row['record_id'], quantity='100', gift='0',
                       cost_total=str(Decimal(row['cny_per_1k']) * 100))
        windows = []

        def evaluate(_, ids):
            requests.extend(ids)
            current = rows if len(windows) == 1 else [amended, *rows[1:], late, older]
            lookup = {row['order_id']: row for row in current}
            return [dict(complete=True,
                goods=[dict(pid='9', gid='1322', cid='1', unit='K', qty='100', used='100')],
                deliveries=[dict(id=ident, pid='9', qty='100', gift='0',
                    price=lookup[ident]['cny_per_1k'], total=lookup[ident]['cost_total'])]) for ident in ids]

        def read(tab, page, observations=None, window=None):
            if page != 1:
                return self.data([])
            windows.append(window)
            return self.data(rows if len(windows) == 1 else [amended, *rows[1:], late, older])

        self.native_verifier.stop()
        self.tab.evaluate = evaluate
        with patch.object(self.collector, 'read_page', side_effect=read):
            result = self.collector.collect(curve_v6=True)
        self.assertEqual(requests.count('1000'), 2)
        self.assertEqual(requests.count('9999'), 1)
        self.assertEqual(requests.count('1100'), 1)
        samples = result['costs'][0]['v6_delivery_samples']['records']
        self.assertEqual({r['record_id']: r['cny_per_1k'] for r in samples}['1000'], '0.5')
        self.assertEqual(len(samples), 7)

    def test_mixed_k_and_million_deliveries_are_normalized_before_taking_max(self):
        self.native_verifier.stop()
        samples = [
            ('1545', '1545', '.400000', '618.00'), ('1.03', '1030', '390', '401.70'),
            ('500', '500', '.400000', '200.00'), ('1', '1000', '394', '394.00'),
            ('.16', '160', '370', '59.20'), ('.5', '500', '398', '199.00'),
            ('100', '100', '.45', '45.00'), ('100', '100', '.42', '42.00'),
        ]
        rows, details = [], {}
        for i, (quantity, ordered, cost, total) in enumerate(samples):
            did, order = str(300 + i), str(400 + i)
            rows.append(dict(self.raw(did, cost, i, {6: 'PC', 7: 'XBOX'}.get(i, 'PS')),
                             order_id=order, quantity=quantity, gift='0', cost_total=total,
                             supplier='FS OMS' if i in (0, 1, 3, 4, 5) else ''))
            details[order] = dict(complete=True,
                goods=[dict(pid='9', gid='1322', cid='1', unit='K', qty=ordered,
                            used=ordered if i in (1, 4, 5) else quantity)],
                deliveries=[dict(id=did, pid='9', qty=quantity, gift='0', price=cost, total=total)])
        self.tab.evaluate = lambda expression, request: details[request[0]]
        ps, xbox, pc = self.run_collect([rows, []])['costs']
        self.assertEqual(Decimal(ps['cny_per_1k']), Decimal('.4'))
        self.assertEqual(Decimal(xbox['observed_cost']['cny_per_1k']), Decimal('.42'))
        self.assertEqual(Decimal(pc['cny_per_1k']), Decimal('.45'))
        mixed = ps['sample_records'][-1]
        self.assertEqual(Decimal(mixed['cny_per_1k']), Decimal('.398'))
        self.assertEqual(Decimal(mixed['quantity_evidence']['delivered_k']), Decimal('500'))
        self.assertNotIn('order_delivery', mixed)

    def test_million_conversion_requires_complete_single_shipment_and_matching_cost(self):
        self.native_verifier.stop()
        raw = dict(self.raw(100, '398', 0), order_id='300', quantity='.5', gift='0', cost_total='199.00')
        _, row = self.collector.valid_record(raw)
        detail = dict(complete=False,
                      goods=[dict(pid='9', gid='1322', cid='1', unit='K', qty='500', used='.5')],
                      deliveries=[dict(id='100', pid='9', qty='.5', gift='0', price='398', total='199.00')])
        self.assertIsNone(self.collector.verified_delivery_cost(self.tab, row, {'300': detail}))
        detail['complete'] = True
        detail['goods'][0]['used'] = '500'
        detail['deliveries'].append(dict(detail['deliveries'][0], id='101'))
        self.assertIsNone(self.collector.verified_delivery_cost(self.tab, row, {'300': detail}))
        detail['deliveries'].pop()
        detail['deliveries'][0]['total'] = '198'
        self.assertIsNone(self.collector.verified_delivery_cost(self.tab, row, {'300': detail}))

    def test_balancing_delivery_does_not_make_mixed_unit_item_valid(self):
        self.native_verifier.stop()
        arrivals = [('4627030', '1.03', '398.000000', '409.94'),
                    ('4627034', '1028.97', '0.000010', '0.01')]
        detail = dict(complete=True,
            goods=[dict(pid='9', gid='1322', cid='1', unit='K', qty='1030', used='1030')],
            deliveries=[dict(id=did, pid='9', qty=qty, gift='0', price=cost, total=total)
                        for did, qty, cost, total in arrivals])
        for did, qty, cost, total in arrivals:
            with self.subTest(delivery=did):
                raw = dict(self.raw(did, cost, 0), order_id='300', quantity=qty, gift='0', cost_total=total)
                _, row = self.collector.valid_record(raw)
                self.assertIsNone(self.collector.verified_delivery_cost(self.tab, row, {'300': detail}))

    def test_order_detail_timeout_retries_the_same_record_once(self):
        self.native_verifier.stop()
        raw = dict(self.raw(100, '.4', 0), order_id='300', quantity='500', gift='0', cost_total='200')
        _, row = self.collector.valid_record(raw)
        detail = dict(complete=True,
            goods=[dict(pid='9', gid='1322', cid='1', unit='K', qty='500', used='500')],
            deliveries=[dict(id='100', pid='9', qty='500', gift='0', price='.4', total='200')])
        timeout = {'timed_out': True}
        self.tab.evaluate = Mock(side_effect=[timeout, detail])
        verified = self.collector.verified_delivery_cost(self.tab, row, {})
        self.assertEqual(Decimal(verified['cny_per_1k']), Decimal('.4'))
        self.assertEqual([call.args[1] for call in self.tab.evaluate.call_args_list], [['300', 8000], ['300', 8000]])

        self.tab.evaluate = Mock(return_value=timeout)
        cache = {}
        with self.assertRaisesRegex(ValueError, 'cost_order_detail_timeout'):
            self.collector.verified_delivery_cost(self.tab, row, cache)
        self.assertEqual(self.tab.evaluate.call_count, 2)
        self.assertEqual(cache, {})

    def test_duplicate_same_record_does_not_count_twice(self):
        result = self.run_collect([self.rows[:3], self.rows[:3]+self.rows[3:], []])
        self.assertEqual(len(result['costs'][0]['sample_records']), 6)

    def test_conflicting_duplicate_fails(self):
        with self.assertRaisesRegex(ValueError, 'cost_duplicate_record_conflict'):
            self.run_collect([self.rows, [dict(self.rows[0], cny_per_1k='999')], []])
        self.assertEqual(self.closed, 1)

    def test_five_unique_valid_ps_records_do_not_pass(self):
        with self.assertRaisesRegex(ValueError, 'ps_valid_delivery_sample_incomplete'):
            self.run_collect([self.rows[:5]*2+self.rows[7:], []])

    def test_non_order_delivery_and_invalid_unit_cost_are_not_samples(self):
        invalid = [dict(self.rows[0], record_id='500', delivery_type='采购打款'),
                   dict(self.rows[0], record_id='501', cny_per_1k='0'),
                   dict(self.rows[0], record_id='502', cny_per_1k='NaN')]
        result = self.run_collect([invalid+self.rows, []])
        self.assertNotIn('500', [row['record_id'] for row in result['costs'][0]['sample_records']])

    def test_same_trade_time_orders_by_numeric_id_before_taking_six(self):
        rows = [dict(self.rows[0], record_id=str(i), cny_per_1k=str(i)) for i in (2,9,10,20,50,100,101)]
        result = self.run_collect([rows+self.rows[7:], []])
        self.assertEqual([row['record_id'] for row in result['costs'][0]['sample_records']], ['101','100','50','20','10','9'])

    def test_original_fifteen_page_limit_requires_complete_narrow_rescan(self):
        calls = []
        def read(tab, number, observations=None, window=None):
            calls.append((number,window))
            if window is None:
                return self.data(self.rows)
            return self.data(self.rows[:6] if number == 1 else [])
        with patch.object(self.collector,'read_page',side_effect=read):
            result = self.collector.collect()
        self.assertEqual(len([call for call in calls if not call[1] or call[1].get('area') != '0']), 17)
        self.assertIsNotNone(calls[-1][1])
        self.assertTrue(result['costs'][0]['sample_boundary']['complete'])
        self.assertEqual(result['costs'][2]['cny_per_1k'], '0.77')

    def test_narrow_scan_page_limit_does_not_silently_use_six(self):
        def read(tab, number, observations=None, window=None):
            return self.data(self.rows if window is None else self.rows[:6])
        with patch.object(self.collector,'read_page',side_effect=read):
            with self.assertRaisesRegex(ValueError,'ps_valid_delivery_sample_page_limit'):
                self.collector.collect()

    def test_one_hour_window_expands_to_two_when_fewer_than_six(self):
        windows=[]
        def read(tab, number, observations=None, window=None):
            if window is None:
                return self.data(self.rows if number==1 else [])
            if number>1:
                return self.data([])
            hours=(window['end']-window['start']).total_seconds()/3600
            if window.get('area') != '0':
                windows.append(hours)
            return self.data(self.rows[:5] if hours==1 else self.rows[:6])
        with patch.object(self.collector,'read_page',side_effect=read):
            result=self.collector.collect()
        self.assertEqual(windows,[1,2])
        boundary=result['costs'][0]['sample_boundary']
        self.assertEqual((datetime.fromisoformat(boundary['end'])-datetime.fromisoformat(boundary['start'])).total_seconds(),7200)

    def test_two_hour_filter_must_match_returned_trades(self):
        def read(tab,number,observations=None,window=None):
            if window is None:
                return self.data(self.rows if number==1 else [])
            return self.data([self.raw(900,'.4',200)])
        with patch.object(self.collector,'read_page',side_effect=read):
            with self.assertRaisesRegex(ValueError,'cost_time_window_filter_unverified'):
                self.collector.collect()

    def empty_page(self, *, ready='complete'):
        return dict(login=False,ready=ready,page='1',game='1322',area='21942',product='1',genre='1',
                    typeHeader='交货类型',table=True,hasDataRows=False,empty=False,deliveryRowCount=0,rows=[],
                    start=self.now.strftime('%Y-%m-%d %H:%M'),end=(self.now+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'))

    def test_real_ps_page_reader_accepts_verified_zero_rows_without_empty_text(self):
        data=self.empty_page()
        page=types.SimpleNamespace(goto=lambda *a,**k:types.SimpleNamespace(status=200),evaluate=lambda _:data,
                                   wait_for_timeout=lambda _:self.fail('verified empty PS page should not wait'))
        window=dict(start=self.now,end=self.now+timedelta(hours=1))
        self.assertEqual(self.collector.read_page(page,1,[],window=window),data)

    def test_native_all_platform_window_keeps_area_separate_from_timestamps(self):
        data = dict(self.empty_page(), area='0')
        page = types.SimpleNamespace(goto=lambda *a, **k: types.SimpleNamespace(status=200),
            evaluate=lambda _: data, wait_for_timeout=lambda _: self.fail('complete native window'))
        window = dict(start=self.now, end=self.now+timedelta(hours=1), area='0')
        self.assertEqual(self.collector.read_page(page, 1, [], window=window), data)

    def test_native_all_platform_wait_returns_on_dom_ready_and_rechecks_window(self):
        window = dict(start=self.now, end=self.now + timedelta(hours=1), area='0')
        loading = dict(self.empty_page(ready='loading'), area='0')
        ready = dict(self.empty_page(ready='interactive'), area='0')
        for wait_error, expected in ((None, ready), (TimeoutError, ready)):
            with self.subTest(wait_error=wait_error):
                observed = []
                page = types.SimpleNamespace(goto=Mock(return_value=types.SimpleNamespace(status=200)),
                    evaluate=Mock(side_effect=[loading, expected]),
                    wait_for_function=Mock(side_effect=wait_error),
                    wait_for_timeout=Mock())
                self.assertEqual(self.collector.read_page(page, 1, observed, window=window), expected)
                self.assertEqual([row['observed']['ready'] for row in observed], ['interactive'])
                self.assertEqual(page.wait_for_function.call_count, 1)
                self.assertEqual(page.wait_for_function.call_args.kwargs['timeout'], 500)
                page.wait_for_timeout.assert_not_called()

        page.evaluate = Mock(side_effect=[loading, dict(ready, area='21942')])
        with self.assertRaisesRegex(self.collector.CostPageError, 'cost_ps_filter_unverified'):
            self.collector.read_page(page, 1, [], window=window)

    def test_native_all_platform_dom_wait_keeps_original_loading_budget(self):
        window = dict(start=self.now, end=self.now + timedelta(hours=1), area='0')
        page = types.SimpleNamespace(goto=Mock(return_value=types.SimpleNamespace(status=200)),
            evaluate=Mock(return_value=dict(self.empty_page(ready='loading'), area='0')),
            wait_for_function=Mock(side_effect=TimeoutError), wait_for_timeout=Mock())
        with self.assertRaisesRegex(self.collector.CostPageError, 'filter_or_rows_unverified:1'):
            self.collector.read_page(page, 1, [], window=window)
        self.assertEqual(page.wait_for_function.call_count, 40)
        self.assertTrue(all(call.kwargs['timeout'] == 500 for call in page.wait_for_function.call_args_list))
        self.assertEqual(page.goto.call_args.kwargs['timeout'], 35000)
        page.wait_for_timeout.assert_not_called()

    def test_ps_empty_page_waits_for_document_parsing_and_pc_gate_is_unchanged(self):
        values=iter([self.empty_page(ready='loading'),self.empty_page()]);waits=[]
        page=types.SimpleNamespace(goto=lambda *a,**k:types.SimpleNamespace(status=200),evaluate=lambda _:next(values),
                                   wait_for_timeout=waits.append)
        self.collector.read_page(page,1,[],window=dict(start=self.now,end=self.now+timedelta(hours=1)))
        self.assertEqual(waits,[500])
        page.evaluate=lambda _:self.empty_page()
        with self.assertRaisesRegex(self.collector.CostPageError,'filter_or_rows_unverified:1'):
            self.collector.read_page(page,1,[])

    def test_completely_empty_hour_expands_to_two_hours(self):
        windows=[]
        def read(tab,number,observations=None,window=None):
            if window is None:
                return self.data(self.rows if number==1 else [])
            hours=(window['end']-window['start']).total_seconds()/3600
            if number==1 and window.get('area') != '0':windows.append(hours)
            return self.data(self.rows[:6] if hours==2 and number==1 else [])
        with patch.object(self.collector,'read_page',side_effect=read):
            result=self.collector.collect()
        self.assertEqual(windows,[1,2])
        self.assertEqual(result['costs'][0]['record_id'],'102')

    def test_sample_exactly_at_window_end_is_accepted(self):
        result=self.run_collect()
        costs={row['platform']:row for row in result['costs']}
        boundary=dict(costs['PS']['sample_boundary'])
        boundary['end']=costs['PS']['sample_records'][0]['trade_at']
        for platform in ('PS','XBOX'):
            costs[platform]['sample_boundary']=boundary
        self.assertEqual(common_cost(dict(costs=costs))[0],Decimal('.9'))

    def test_financial_rejects_missing_incomplete_or_wrong_sample_boundary(self):
        result = self.run_collect()
        costs = {row['platform']:row for row in result['costs']}
        for boundary in (None, dict(complete=False), dict(complete=True,start='2026-01-01 00:00',end='2026-01-02 00:00'),
                         dict(complete=True,start='2026-01-02 00:00',end='2026-01-01 00:00')):
            bad = deepcopy(costs)
            bad['PS']['sample_boundary'] = boundary
            with self.assertRaisesRegex(ValueError,'pricing_console_cost_sample_boundary'):
                common_cost(dict(costs=bad))

    def test_old_payload_without_six_sample_contract_is_rejected(self):
        result = self.run_collect()
        for row in result['costs'][:2]:
            row.pop('sample_contract')
        with self.assertRaisesRegex(ValueError,'pricing_console_cost_sample_unverified'):
            self.snapshot.cost_snapshots('offline', result)

    def test_financial_rejects_xbox_override_or_tampered_sample(self):
        result = self.run_collect()
        costs = {row['platform']:row for row in result['costs']}
        bad = deepcopy(costs)
        bad['XBOX']['cny_per_1k'] = '888'
        with self.assertRaisesRegex(ValueError,'pricing_console_cost_selection_mismatch'):
            common_cost(dict(costs=bad))
        bad = deepcopy(costs)
        for platform in ('PS','XBOX'):
            bad[platform]['sample_records'][0]['record_id']='101'
        with self.assertRaisesRegex(ValueError,'pricing_console_cost_identity'):
            common_cost(dict(costs=bad))

    def test_financial_rejects_unsorted_sample_and_wrong_delivery_type(self):
        result = self.run_collect()
        costs = {row['platform']:row for row in result['costs']}
        bad = deepcopy(costs)
        bad['PS']['sample_records'] = list(reversed(bad['PS']['sample_records']))
        with self.assertRaisesRegex(ValueError,'pricing_console_cost_sample_order'):
            common_cost(dict(costs=bad))
        bad = deepcopy(costs)
        bad['PS']['sample_records'][0]['delivery_type']='采购打款'
        with self.assertRaisesRegex(ValueError,'pricing_console_cost_scope'):
            common_cost(dict(costs=bad))

    def test_missing_pc_stays_missing_and_does_not_copy_console(self):
        result = self.run_collect([self.rows[:7], []])
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['costs'][2]['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
