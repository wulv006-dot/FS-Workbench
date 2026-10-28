"""admin_readback 的单元测试（unittest，与现有 CI 一致，无网络依赖）。"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'source'
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

try:                                          # 私库结构：source/fc_pricing_v3/
    from fc_pricing_v3.admin_readback import (
        PLATFORM_AID,
        matches_targets,
        read_admin_unit_prices,
    )
except ModuleNotFoundError:                   # 本地平铺结构
    from admin_readback import (  # type: ignore
        PLATFORM_AID,
        matches_targets,
        read_admin_unit_prices,
    )


class FakeSession:
    """按 aid 返回预设行；by_aid 里没有该 aid 表示查不到。"""

    def __init__(self, by_aid):
        self.by_aid = by_aid
        self.calls = []

    def get_admin(self, path, **params):
        filters = {}
        for key, value in params.items():
            if key.startswith('search[') and key.endswith('][field]'):
                index = key.split('[')[1].split(']')[0]
                filters[value] = params.get('search[%s][val]' % index)
        self.calls.append((path, dict(filters)))
        rows = self.by_aid.get(filters.get('aid'))
        if rows is None:
            return 200, {'code': 1, 'data': {'total': 0, 'list': []}}
        return 200, {'code': 1, 'data': {'total': len(rows), 'list': rows}}


class AdminReadback(unittest.TestCase):
    def test_reads_all_platforms_when_values_agree(self):
        session = FakeSession({
            '21589': [{'unit_price': '0.0746', 'price': '0', 'aid': '21589'}],
            '21587': [{'unit_price': '0.0738', 'price': '0', 'aid': '21587'}],
            '21585': [{'unit_price': '0.0738', 'price': '0', 'aid': '21585'}],
        })
        observed = read_admin_unit_prices(session)
        self.assertEqual(observed, {
            'PC': Decimal('0.0746'),
            'PS': Decimal('0.0738'),
            'XBOX': Decimal('0.0738'),
        })
        self.assertEqual(len(session.calls), 3)
        self.assertEqual({call[1]['aid'] for call in session.calls}, set(PLATFORM_AID.values()))

    def test_conflicting_rows_for_same_aid_are_skipped(self):
        session = FakeSession({
            '21589': [{'unit_price': '0.0746'}, {'unit_price': '0.0799'}],
            '21587': [{'unit_price': '0.0738'}],
            '21585': [{'unit_price': '0.0738'}],
        })
        observed = read_admin_unit_prices(session)
        self.assertNotIn('PC', observed)
        self.assertEqual(observed['PS'], Decimal('0.0738'))

    def test_non_numeric_price_is_ignored(self):
        session = FakeSession({
            '21589': [{'unit_price': 'abc'}],
            '21587': [{'unit_price': '0.0738'}],
            '21585': [{'unit_price': None}],
        })
        observed = read_admin_unit_prices(session)
        self.assertEqual(list(observed), ['PS'])

    def test_matches_targets_maps_per_k_to_per_100k(self):
        # Admin unit_price 是每 K，Order quote 是每 100K：0.0738 * 100 == 7.38
        observed = {'PC': Decimal('0.0746'), 'PS': Decimal('0.0738'), 'XBOX': Decimal('0.0738')}
        targets = [
            {'platform': 'PC', 'quote': '7.46'},
            {'platform': 'PS', 'quote': '7.38'},
            {'platform': 'XBOX', 'quote': '7.38'},
        ]
        self.assertTrue(matches_targets(observed, targets))

    def test_matches_targets_rejects_when_any_platform_differs(self):
        observed = {'PC': Decimal('0.0746'), 'PS': Decimal('0.0738'), 'XBOX': Decimal('0.0738')}
        targets = [{'platform': 'PC', 'quote': '7.99'}]
        self.assertFalse(matches_targets(observed, targets))

    def test_matches_targets_missing_platform_is_false(self):
        observed = {'PC': Decimal('0.0746')}
        targets = [{'platform': 'PC', 'quote': '7.46'}, {'platform': 'PS', 'quote': '7.38'}]
        self.assertFalse(matches_targets(observed, targets))

    def test_matches_targets_empty_is_false(self):
        self.assertFalse(matches_targets({'PC': Decimal('1')}, []))

    def test_readback_error_propagates(self):
        class Broken:
            def get_admin(self, path, **params):
                return 401, {'code': 401}

        with self.assertRaises(ValueError):
            read_admin_unit_prices(Broken())


if __name__ == '__main__':
    unittest.main()
