"""admin_readback 的单元测试（不依赖网络，用假 session）。"""
import os
import sys
from decimal import Decimal

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _cand in (_ROOT, os.path.join(_ROOT, 'source', 'fc_pricing_v3')):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)

from admin_readback import PLATFORM_AID, matches_targets, read_admin_unit_prices  # noqa: E402


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


def test_reads_all_platforms_when_values_agree():
    session = FakeSession({
        '21589': [{'unit_price': '0.0746', 'price': '0', 'aid': '21589'}],
        '21587': [{'unit_price': '0.0738', 'price': '0', 'aid': '21587'}],
        '21585': [{'unit_price': '0.0738', 'price': '0', 'aid': '21585'}],
    })
    observed = read_admin_unit_prices(session)
    assert observed == {
        'PC': Decimal('0.0746'),
        'PS': Decimal('0.0738'),
        'XBOX': Decimal('0.0738'),
    }
    assert len(session.calls) == 3
    assert {call[1]['aid'] for call in session.calls} == set(PLATFORM_AID.values())


def test_conflicting_rows_for_same_aid_are_skipped():
    session = FakeSession({
        '21589': [{'unit_price': '0.0746'}, {'unit_price': '0.0799'}],
        '21587': [{'unit_price': '0.0738'}],
        '21585': [{'unit_price': '0.0738'}],
    })
    observed = read_admin_unit_prices(session)
    assert 'PC' not in observed
    assert observed['PS'] == Decimal('0.0738')


def test_non_numeric_price_is_ignored():
    session = FakeSession({
        '21589': [{'unit_price': 'abc'}],
        '21587': [{'unit_price': '0.0738'}],
        '21585': [{'unit_price': None}],
    })
    observed = read_admin_unit_prices(session)
    assert list(observed) == ['PS']


def test_matches_targets_maps_per_k_to_per_100k():
    # Admin unit_price 是每 K，Order quote 是每 100K：0.0738 * 100 == 7.38
    observed = {'PC': Decimal('0.0746'), 'PS': Decimal('0.0738'), 'XBOX': Decimal('0.0738')}
    targets = [
        {'platform': 'PC', 'quote': '7.46'},
        {'platform': 'PS', 'quote': '7.38'},
        {'platform': 'XBOX', 'quote': '7.38'},
    ]
    assert matches_targets(observed, targets) is True


def test_matches_targets_rejects_when_any_platform_differs():
    observed = {'PC': Decimal('0.0746'), 'PS': Decimal('0.0738'), 'XBOX': Decimal('0.0738')}
    targets = [{'platform': 'PC', 'quote': '7.99'}]
    assert matches_targets(observed, targets) is False


def test_matches_targets_missing_platform_is_false():
    observed = {'PC': Decimal('0.0746')}
    targets = [{'platform': 'PC', 'quote': '7.46'}, {'platform': 'PS', 'quote': '7.38'}]
    assert matches_targets(observed, targets) is False


def test_matches_targets_empty_is_false():
    assert matches_targets({'PC': Decimal('1')}, []) is False


def test_readback_error_propagates():
    class Broken:
        def get_admin(self, path, **params):
            return 401, {'code': 401}

    with pytest.raises(ValueError):
        read_admin_unit_prices(Broken())
