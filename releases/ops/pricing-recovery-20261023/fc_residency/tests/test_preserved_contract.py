import ast
import hashlib
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'baseline/lootbar_server_collector.py'
SOURCE = ROOT / 'source/lootbar_server_collector.py'


class PreservedContractTests(unittest.TestCase):
    def replace_once(self, source, added, original=''):
        self.assertEqual(source.count(added), 1, added)
        return source.replace(added, original, 1)

    def test_active_baseline_digest(self):
        self.assertEqual(hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
            '3c53cdad71fa9c77c1dc58e0d136026c62cb4e8a7151f3ac7a72ca733cf8d5ac')

    def test_other_functions_remain_identical_including_deadline(self):
        baseline = BASELINE.read_text(encoding='utf-8')
        source = SOURCE.read_text(encoding='utf-8')
        old = {n.name: n for n in ast.parse(baseline).body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        new = {n.name: n for n in ast.parse(source).body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual(set(new) - set(old), {'_park_product_page', '_collect_product_page',
                                              '_release_product_document', '_cdp_http'})
        metadata = ast.parse("if isinstance(snapshot.get('reconstruction'), dict):\n    result['reconstruction'] = snapshot['reconstruction']").body[0]
        additions = [node for node in new['_offer'].body if ast.dump(node) == ast.dump(metadata)]
        self.assertEqual(len(additions), 1)
        new['_offer'].body.remove(additions[0])
        offer = next(node.value for node in new['_offer'].body if isinstance(node, ast.Assign)
                     and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'result')
        quantity = next(index for index, key in enumerate(offer.keys) if key.value == 'base_k')
        self.assertEqual(ast.dump(offer.values[quantity]), ast.dump(ast.parse('str(snapshot["baseK"])', mode='eval').body))
        offer.values[quantity] = ast.Constant('100')
        snapshot = ast.get_source_segment(source, new['snapshot_error'])
        for added, original in (
            (', *, quantity=100', ''),
            ('_positive_decimal(snapshot.get("baseK")) != quantity',
             '_positive_decimal(snapshot.get("baseK")) != Decimal("100")'),
            ('return f"{quantity}K Safe Coins 商品规格未唯一核实"', 'return "100K Safe Coins 商品规格未唯一核实"'),
        ):
            snapshot = self.replace_once(snapshot, added, original)
        new['snapshot_error'] = ast.parse(snapshot).body[0]
        stable = ast.get_source_segment(source, new['_stable_offer'])
        for added, original in (
            (', quantity_offers=None', ''),
            ('    quantity_reads = []\n', ''),
            ('(_read_snapshot(page, reader_source) if quantity_offers is None else\n'
             '                    page.evaluate(f"() => ({reader_source})([1000, 2000, 5000])"))',
             '_read_snapshot(page, reader_source)'),
            ('            quantity_reads.clear()\n            time.sleep(0.4)', '            time.sleep(0.4)'),
            ('            quantity_reads.clear()\n            state =', '            state ='),
            ('            if quantity_offers is not None:\n'
             '                quantity_reads.append(last.pop("quantityOffers", {}))\n'
             '                quantity_reads = quantity_reads[-3:]\n', ''),
            ('                for quantity in (1000, 2000, 5000):\n'
             '                    observations = [read.get(str(quantity)) for read in quantity_reads]\n'
             '                    if (len(observations) == 3 and observations[0] == observations[1] == observations[2]\n'
             '                            and snapshot_error(observations[0], label, quantity=quantity) is None):\n'
             '                        quantity_offers.append(_offer(platform, observations[0]))\n', ''),
        ):
            stable = self.replace_once(stable, added, original)
        new['_stable_offer'] = ast.parse(stable).body[0]
        for name in sorted(old.keys() - {'_collect_attached', 'collect', 'main'}):
            with self.subTest(name=name):
                self.assertEqual(ast.dump(old[name]), ast.dump(new[name]))

        collect = ast.get_source_segment(source, new['collect'])
        collect = self.replace_once(collect, ', include_quantities=False')
        collect = self.replace_once(collect, '    deadline = time.monotonic() + COLLECT_TIMEOUT_SECONDS\n')
        collect = self.replace_once(collect, '            options = {"include_quantities": True} if include_quantities else {}\n')
        collect = self.replace_once(collect, '_collect_attached(single_ps=single_ps, deadline=deadline, **options)',
                                    '_collect_attached(single_ps=single_ps)')
        self.assertEqual(ast.dump(ast.parse(collect).body[0]), ast.dump(old['collect']))

    def test_offer_only_adds_verified_reconstruction_evidence(self):
        def offer(path):
            node = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                        if isinstance(n, ast.FunctionDef) and n.name == '_offer')
            namespace = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
            return namespace['_offer']
        old, new = offer(BASELINE), offer(SOURCE)
        raw = {'couponState':'excluded', 'baseK': 100, 'usdPrice':'10.00', 'bonusK':'5',
               'observedCouponPrice':'8.50', 'excludedCouponDiscount':'1.50'}
        self.assertEqual(new('PC', raw), old('PC', raw))
        evidence = {'method':'actual_discount', 'paid_usd':'8.50', 'discount_usd':'1.50'}
        self.assertEqual(new('PC', dict(raw, reconstruction=evidence)),
                         dict(old('PC', raw), reconstruction=evidence))
        self.assertEqual(new('PC', dict(raw, reconstruction='unverified')), old('PC', raw))

    def test_stable_native_quantity_keeps_default_100k_and_rejects_ambiguous_observations(self):
        from test_lootbar_server_collector import collector, snapshot

        label = 'PS4/5'
        ordinary = snapshot(label)
        page = Mock()
        outputs = [dict(ordinary, quantityOffers={
            '1000': snapshot(label, baseK=1000, price='100.00'),
            '2000': snapshot(label, baseK=2000, price=price),
            '5000': snapshot(label, baseK=1000, price='100.00'),
        }) for price in ('200.00', '210.00', '200.00')]
        page.evaluate.side_effect = outputs
        additions = []
        with patch.object(collector, 'emit'), patch.object(collector.time, 'sleep'), \
                patch.object(collector, '_read_snapshot', return_value=ordinary) as default_read:
            default = collector._stable_offer(page, 'reader', 'PS', label)
            self.assertEqual(default_read.call_count, 3)
            page.evaluate.assert_not_called()
            extended = collector._stable_offer(page, 'reader', 'PS', label, additions)
        self.assertEqual(default, extended)
        self.assertEqual((default[0]['base_k'], default[1]), ('100', 3))
        self.assertEqual(page.evaluate.call_count, 3)
        self.assertEqual([item['base_k'] for item in additions], ['1000'])
        self.assertIn('100K', collector.snapshot_error(snapshot(label, baseK=1000), label))

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
        actual = self.replace_once(actual, '    quantity_offers = [] if include_quantities else None\n')
        actual = self.replace_once(actual, '_stable_offer(original, reader_source, "PS", "PS4/5", quantity_offers)',
                                   '_stable_offer(original, reader_source, "PS", "PS4/5")')
        actual = self.replace_once(actual, '_stable_offer(original, reader_source, platform, label, quantity_offers)',
                                   '_stable_offer(original, reader_source, platform, label)')
        actual = self.replace_once(actual, '    result = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),\n'
                                   '              "offers": offers, "read_only": True}\n'
                                   '    if quantity_offers is not None:\n'
                                   '        result["quantity_offers"] = quantity_offers\n'
                                   '    return result',
                                   '    return {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),\n'
                                   '            "offers": offers, "read_only": True}')
        self.assertEqual(ast.dump(ast.parse('def contract():\n' + actual)),
                         ast.dump(ast.parse('def contract():\n' + expected)))


if __name__ == '__main__':
    unittest.main()
