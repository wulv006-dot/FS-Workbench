import ast
import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'baseline/lootbar_server_collector.py'
SOURCE = ROOT / 'source/lootbar_server_collector.py'


class PreservedContractTests(unittest.TestCase):
    def test_active_baseline_digest(self):
        self.assertEqual(hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
            '3c53cdad71fa9c77c1dc58e0d136026c62cb4e8a7151f3ac7a72ca733cf8d5ac')

    def test_other_functions_remain_identical_including_deadline(self):
        old = {n.name: n for n in ast.parse(BASELINE.read_text(encoding='utf-8')).body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        new = {n.name: n for n in ast.parse(SOURCE.read_text(encoding='utf-8')).body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual(set(new) - set(old), {'_park_product_page', '_collect_product_page',
                                              '_release_product_document', '_cdp_http'})
        metadata = ast.parse("if isinstance(snapshot.get('reconstruction'), dict):\n    result['reconstruction'] = snapshot['reconstruction']").body[0]
        additions = [node for node in new['_offer'].body if ast.dump(node) == ast.dump(metadata)]
        self.assertEqual(len(additions), 1)
        new['_offer'].body.remove(additions[0])
        for name in old.keys() - {'_collect_attached', 'collect', 'main'}:
            with self.subTest(name=name):
                self.assertEqual(ast.dump(old[name]), ast.dump(new[name]))

        source = SOURCE.read_text(encoding='utf-8')
        collect = ast.get_source_segment(source, new['collect'])
        collect = collect.replace('    deadline = time.monotonic() + COLLECT_TIMEOUT_SECONDS\n', '', 1)
        collect = collect.replace('_collect_attached(single_ps=single_ps, deadline=deadline)',
                                  '_collect_attached(single_ps=single_ps)', 1)
        self.assertEqual(ast.dump(ast.parse(collect).body[0]), ast.dump(old['collect']))

    def test_offer_only_adds_verified_reconstruction_evidence(self):
        def offer(path):
            node = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                        if isinstance(n, ast.FunctionDef) and n.name == '_offer')
            namespace = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
            return namespace['_offer']
        old, new = offer(BASELINE), offer(SOURCE)
        raw = {'couponState':'excluded', 'usdPrice':'10.00', 'bonusK':'5',
               'observedCouponPrice':'8.50', 'excludedCouponDiscount':'1.50'}
        self.assertEqual(new('PC', raw), old('PC', raw))
        evidence = {'method':'actual_discount', 'paid_usd':'8.50', 'discount_usd':'1.50'}
        self.assertEqual(new('PC', dict(raw, reconstruction=evidence)),
                         dict(old('PC', raw), reconstruction=evidence))
        self.assertEqual(new('PC', dict(raw, reconstruction='unverified')), old('PC', raw))

    def test_moved_read_logic_keeps_original_checks_and_ps_restore(self):
        old = BASELINE.read_text(encoding='utf-8')
        start = old.index('        if not single_ps:\n            # Bound the lifetime')
        end = old.index('\n\n\ndef collect(', start)
        expected = '\n'.join(line[4:] if line.startswith('    ') else line
                             for line in old[start:end].splitlines())
        new = SOURCE.read_text(encoding='utf-8')
        start = new.index('    if not single_ps or woke:\n        # Bound the lifetime')
        end = new.index('\n\n\ndef collect(', start)
        actual = new[start:end]
        actual = actual.replace('if not single_ps or woke:', 'if not single_ps:', 1)
        actual = actual.replace('response = (original.goto(BASE_URL, wait_until="domcontentloaded", timeout=12000) if woke\n                        else original.reload(wait_until="domcontentloaded", timeout=12000))',
                                'response = original.reload(wait_until="domcontentloaded", timeout=12000)', 1)
        actual = actual.replace('range(31 if not single_ps or woke else 1)',
                                'range(31 if not single_ps else 1)', 1)
        actual = actual.replace('if (not single_ps or woke) and attempt < 30:',
                                'if not single_ps and attempt < 30:', 1)
        self.assertEqual(ast.dump(ast.parse('def contract():\n' + actual)),
                         ast.dump(ast.parse('def contract():\n' + expected)))


if __name__ == '__main__':
    unittest.main()
