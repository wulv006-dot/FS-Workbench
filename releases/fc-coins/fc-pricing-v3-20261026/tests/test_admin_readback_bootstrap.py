"""PR #589：``_admin_observed_prices`` 必须自举共享 Admin 通道。

背景（2026-10-28 生产实测）
--------------------------
``#588`` 上线后 reconcile 仍然收不了尾，账本里留下：
``order_close={"action":"keep","reason":"admin_unit_price_mismatch",
"detail":"admin_readback_unavailable:ModuleNotFoundError"}``。
根因是该函数直接 ``from channel_source import pages``，
而 ``channel_source`` / ``p2pah_auth`` 都不在 ``/opt/fc27-cloud-browser`` 下
（分别位于 ``/opt/fs-hermes-fc`` 与 ``/opt/sales-dashboard/collector``）。
条件 2 恒为空 ⇒ 已写成功且 ``sync_message`` 齐全的操作被判 ``keep``。

既有 ``test_order_close_runtime`` 把该函数整体 mock 掉，
所以 CI 抓不到 I/O 边界上的这个问题 —— 本文件专门锁住自举四步：
    sys.path += /opt/fs-hermes-fc -> COLLECTOR
    admin_token_from_service() -> bind_admin_token()
    read_admin_unit_prices(session, pages=<channel_source.pages>)
    session.close()
"""
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3 import admin_readback, runtime  # noqa: E402

SHARED_SOURCE_ROOT = '/opt/fs-hermes-fc'
COLLECTOR_ROOT = '/opt/sales-dashboard/collector'
EVENTS = []


class _FakeSession:
    def __init__(self):
        EVENTS.append('new')

    def bind_admin_token(self, token):
        EVENTS.append(('bind', token))

    def close(self):
        EVENTS.append('close')


class AdminObservedPricesBootstrap(unittest.TestCase):
    def setUp(self):
        EVENTS.clear()
        self._mods = {k: sys.modules.get(k) for k in ('channel_source', 'p2pah_auth')}
        self._path = list(sys.path)
        self._reader = admin_readback.read_admin_unit_prices

    def tearDown(self):
        for name, mod in self._mods.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        sys.path[:] = self._path
        admin_readback.read_admin_unit_prices = self._reader

    def _install(self, token='svc-token', observed=None, raises=None):
        calls = {}
        seen_pages = {}

        def pages(session, path, filters=None, **kwargs):
            calls.setdefault('paths', []).append(path)
            return [{'unit_price': '0.0746'}]

        sys.modules['channel_source'] = types.SimpleNamespace(pages=pages, COLLECTOR=COLLECTOR_ROOT)
        sys.modules['p2pah_auth'] = types.SimpleNamespace(
            Session=_FakeSession,
            admin_token_from_service=lambda: (token, 'ok'))

        def fake_reader(session, *, gid=None, mid=None, site_id=None,
                        platform_aid=None, pages=None):
            seen_pages['reader'] = pages
            if raises is not None:
                raise raises
            return observed if observed is not None else {'PC': Decimal('0.0746')}

        admin_readback.read_admin_unit_prices = fake_reader
        return calls, seen_pages

    def test_injects_shared_source_and_collector_paths(self):
        self._install()
        runtime._admin_observed_prices()
        self.assertIn(SHARED_SOURCE_ROOT, sys.path)
        self.assertIn(COLLECTOR_ROOT, sys.path)

    def test_binds_service_token_and_closes_session(self):
        self._install(token='svc-token')
        runtime._admin_observed_prices()
        self.assertEqual(EVENTS, ['new', ('bind', 'svc-token'), 'close'])

    def test_passes_channel_source_pages_into_reader(self):
        calls, seen = self._install()
        runtime._admin_observed_prices()
        self.assertIsNotNone(seen['reader'])
        self.assertIs(seen['reader'], sys.modules['channel_source'].pages)

    def test_returns_reader_observation(self):
        self._install(observed={'PC': Decimal('0.0746'), 'PS': Decimal('0.0738')})
        self.assertEqual(runtime._admin_observed_prices(),
                         {'PC': Decimal('0.0746'), 'PS': Decimal('0.0738')})

    def test_missing_token_raises_without_binding(self):
        self._install(token=None)
        with self.assertRaises(ValueError) as ctx:
            runtime._admin_observed_prices()
        self.assertIn('pricing_admin_readback_token_unavailable', str(ctx.exception))
        self.assertEqual(EVENTS, ['new', 'close'])
        self.assertNotIn(('bind', None), EVENTS)

    def test_session_closed_when_reader_raises(self):
        self._install(raises=RuntimeError('boom'))
        with self.assertRaises(RuntimeError):
            runtime._admin_observed_prices()
        self.assertEqual(EVENTS[-1], 'close')


if __name__ == '__main__':
    unittest.main()

