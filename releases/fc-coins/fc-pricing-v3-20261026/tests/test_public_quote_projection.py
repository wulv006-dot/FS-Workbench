"""The authenticated quote read must stay small without changing its signed original."""
import ast
import hashlib
import json
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'source' / 'fc27_cloud_api.py'
module = ast.parse(SOURCE.read_text(encoding='utf-8'))
functions = [node for node in module.body if isinstance(node, ast.FunctionDef)
             and node.name in {'_without_replay_paths', 'public_artifact'}]
namespace = {'hashlib': hashlib, 'json': json}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), namespace)


class PublicQuoteProjectionTest(unittest.TestCase):
    def test_large_private_history_is_absent_and_original_sha_is_stable(self):
        orders = [{'order_key': str(i), 'paid_usd': '63.25', 'cost_cny': '123.45',
                   'available_at': '2026-10-26T11:45:00Z'} for i in range(2352)]
        paths = [{'date': str(i), 'ratio': '.9171307150403613875'} for i in range(2352)]
        quote = {'run_id': 'a' * 36, 'result': {'candidates': [{'action': {'base_prices': {'PS': '9.99'}}}]},
                 'evidence': {'historical_orders': orders,
                              'historical_orders_coverage': {'count': 2352},
                              'history_replay': {'paths': paths, 'region_layers': {'39': {'paths': paths}}},
                              'region_rules': [{'history': {'replay_paths': paths, 'source_sha256': 'b' * 64}}],
                              'regional_controls': [{'history': {'replay_paths': paths, 'coverage': 2352}}]}}
        expected = hashlib.sha256(json.dumps(quote, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        projected = namespace['public_artifact'](quote, include_quote_sha=True)
        self.assertEqual(projected['original_quote_sha256'], expected)
        self.assertEqual(projected['result'], quote['result'])
        self.assertEqual(projected['evidence']['historical_orders_coverage']['count'], 2352)
        self.assertNotIn('historical_orders', projected['evidence'])
        self.assertNotIn('paths', projected['evidence']['history_replay'])
        self.assertNotIn('paths', projected['evidence']['history_replay']['region_layers']['39'])
        self.assertNotIn('replay_paths', projected['evidence']['region_rules'][0]['history'])
        self.assertNotIn('replay_paths', projected['evidence']['regional_controls'][0]['history'])
        self.assertLess(len(json.dumps(projected).encode()), 1_000_000)
        self.assertEqual(len(quote['evidence']['historical_orders']), 2352)


if __name__ == '__main__':
    unittest.main()
