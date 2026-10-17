"""Exercise the real collector projection and range reader with synthetic aggregates."""
import ast
import copy
from datetime import date, datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAP = json.loads((ROOT / 'evidence/game-map.json').read_text(encoding='utf-8'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collector(path, directory):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    # Execute only unchanged projection functions and literal profile assignments.
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in
             ('collect', 'profile_record', 'dimensions') or isinstance(n, ast.Assign) and
             any(isinstance(t, ast.Name) and t.id == 'PROFILES' for t in n.targets)]
    requests = []

    def call(container, script, items, timeout):
        requests.extend((script, copy.deepcopy(item)) for item in items)
        if script not in ('primary_reader.py', 'supplement_reader.py'):
            return {}
        result = {}
        for item in items:
            period = {k: item[k] for k in ('start', 'end')}
            stamp = item['start'][:10] if item['key'].endswith(':history') else item['start'][:10] + ' 00:00'
            result[item['key']] = dict(status='available', period=period, capturedAt='2026-10-12T00:00:00Z',
                orders=2, revenueUsd=100, newCustomers=1, metrics={}, dimensions={}, charts=[],
                rows=[dict(date=stamp, orders=2, amount=100)])
        return result

    env = dict(Path=Path, date=date, datetime=datetime, timedelta=timedelta, json=json, hashlib=hashlib,
        WEB=Path(directory), SHANGHAI=timezone(timedelta(hours=8)), CONTRACT='unchanged',
        call=call, cycle_requests=lambda *a: [], cycle_analysis=lambda *a: {},
        fc_rows=lambda *a: [], product_requests=lambda *a: [], product_cycle=lambda *a: {},
        collect_profit_history=lambda *a: {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)
    return env, requests


class Games(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env, self.requests = collector(ROOT / 'source/collector.py', self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_ids_and_unique_categories(self):
        profiles = self.env['PROFILES']
        self.assertEqual(len(profiles), 17)
        self.assertEqual(len({p[0] for p in profiles}), 17)
        for row in MAP['profiles']:
            self.assertIn((row['key'], row['name'], row['orderGameId'], row['adminGameId'], row['group']), profiles)
        old, _ = collector(ROOT / 'baseline/collector.py', self.temp.name)
        self.assertEqual(profiles[:10], old['PROFILES'])

    def test_collect_emits_all_seven_boards_and_exact_filters(self):
        result = self.env['collect']()
        groups = {g['key']: g for g in result['dashboard']['groups']}
        self.assertEqual(groups['general']['profiles'], [r['key'] for r in MAP['profiles'] if r['group'] == 'general'])
        self.assertEqual(groups['rpg']['profiles'], ['POE2', 'D4', 'AION2', 'DARK_AND_DARKER', 'WOW_FOREVER'])
        self.assertEqual(groups['general']['label'], '综合游戏 · 全部状态')
        self.assertEqual(groups['rpg']['label'], 'RPG · 已完成')
        for row in MAP['profiles']:
            key = row['key']
            board = result['dashboard']['profiles'][key]
            self.assertTrue(board['series'])
            self.assertIn(key, result['profiles'])
            self.assertIn(key, result['requiredProfiles'])
            self.assertIn(key, result['rangeMeta'])
            self.assertEqual(board['filters']['game'], row['orderGameId'])
            self.assertEqual(board['filters']['order_status'], row['orderStatus'])
            for kind in ('today', 'history'):
                request = next(r for script, r in self.requests if script == 'primary_reader.py' and r['key'] == key + ':' + kind)
                self.assertEqual((request['gid'], request['status']), (row['orderGameId'], row['orderStatus']))
            request = next(r for script, r in self.requests if script == 'supplement_reader.py' and r['key'] == key + ':today')
            self.assertEqual((request['game'], request['status']), (row['adminGameId'], row['adminOrderStatus']))
        result.update(schemaVersion=2, snapshotId='20261012T000000Z-aaaaaaaaaaaaaaaa',
                      generatedAt=datetime.now(timezone.utc).isoformat(), generatedAtShanghai='2026-10-12 08:00')
        (ROOT / 'tests/synthetic-snapshot.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')

    def test_old_profile_results_and_collection_protection_unchanged(self):
        old, _ = collector(ROOT / 'baseline/collector.py', self.temp.name)
        before, after = old['collect'](), self.env['collect']()
        for key, *_ in old['PROFILES']:
            self.assertEqual(before['profiles'][key], after['profiles'][key])
            self.assertEqual(before['dashboard']['profiles'][key], after['dashboard']['profiles'][key])
            self.assertEqual(before['rangeMeta'][key], after['rangeMeta'][key])
        before_tree = ast.parse((ROOT / 'baseline/collector.py').read_text(encoding='utf-8'))
        after_tree = ast.parse((ROOT / 'source/collector.py').read_text(encoding='utf-8'))
        # Only game records and emitted groups may change; all other functions stay identical.
        for n in before_tree.body:
            if isinstance(n, ast.FunctionDef) and n.name != 'collect':
                other = next(x for x in after_tree.body if isinstance(x, ast.FunctionDef) and x.name == n.name)
                self.assertEqual(ast.dump(n), ast.dump(other))
        for name in ('SERVICE_BUDGET_SECONDS', 'PROFIT_PUBLISH_RESERVE_SECONDS', 'PROFIT_MIN_READ_SECONDS'):
            value = lambda tree: next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == name for t in n.targets))
            self.assertEqual(value(before_tree), value(after_tree))

    def test_summary_accepts_new_profiles_and_custom_day_hour_ranges(self):
        module = load(ROOT / 'baseline/live_summary.py', 'test_live_summary')
        profiles = {r[0]: r for r in self.env['PROFILES']}
        for row in MAP['profiles']:
            for grain, start, end in [('day', '2026-10-01', '2026-10-03'), ('hour', '2026-10-01 00:00', '2026-10-01 02:00')]:
                params = dict(mode='summary', profile=row['key'], start=start, end=end, grain=grain)
                q = module.query({k: [v] for k, v in params.items()}, profiles, datetime(2026, 10, 12, tzinfo=timezone.utc))
                self.assertEqual(q['profile'], row['key'])
                self.assertEqual(q['cacheSeconds'], 7200)
                self.assertEqual(q['contractId'], 'admin-main-order-labelled-supplement-v1')
        with self.assertRaises(ValueError):
            module.query(dict(mode=['summary'], profile=['UNKNOWN'], start=['2026-10-01'], end=['2026-10-03']), profiles)

    def test_admin_reader_retains_whitelist_and_completed_rpg_scope(self):
        # Load the real mapper, never invoke a private session or a network request.
        import sys
        sys.path.insert(0, str(ROOT / 'baseline'))
        admin = load(ROOT / 'source/admin_summary.py', 'test_admin_summary')
        old = load(ROOT / 'baseline/admin_summary.py', 'test_admin_summary_old')
        self.assertEqual({k: admin.GAMES[k] for k in old.GAMES}, old.GAMES)
        for row in MAP['profiles']:
            captured = []
            def request(endpoint, data):
                captured.append((endpoint, data))
                return 200, json.dumps({'code': 1, 'data': {}})
            result = admin.collect(request, row['adminGameId'], '2026-10-01 00:00', '2026-10-04 00:00')
            data = captured[0][1]
            self.assertEqual(data['game'], row['adminGameId'])
            self.assertEqual(data['order_status'], row['adminOrderStatus'])
            self.assertEqual(data['pay_status'], 1)
            self.assertEqual(data['site'], '')
            self.assertEqual(result['status'], 'available')
            self.assertIsNone(result['metrics']['newCustomers']['value'])
        for game in (0, 140, 675, 1331, 1353):
            with self.assertRaises(ValueError):
                admin.collect(lambda *a, **kw: self.fail('invalid game reached source'), game, '2026-10-01 00:00', '2026-10-04 00:00')


if __name__ == '__main__':
    unittest.main()
