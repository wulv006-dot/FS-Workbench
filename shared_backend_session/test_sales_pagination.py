import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def collector(page):
    tree=ast.parse(Path(__file__).with_name('sales_collection.py').read_text(encoding='utf-8'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='fetch_deliveries_range')
    sleep=Mock()
    # 2026-10-29：翻页终止条件从「分页控件报的最大页码」改成「空页 / 整页已知」，
    # 所以这里注入等价语义（只有空页才停），单测关注的是重试与不返回半截数据。
    scope={'ORDER_GID':826,'GENRE_ORDER_SHIP':'1','MAX_DELIVERY_PAGES':400,
           '_should_stop':lambda batch,key,known: not batch,
           'time':SimpleNamespace(time=lambda:0,sleep=sleep),'_delivery_page':page}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<actual-delivery-range>','exec'),scope)
    return scope['fetch_deliveries_range'],sleep


class Tests(unittest.TestCase):
    def test_transient_global_unavailable_retries_same_page_without_duplicate_rows(self):
        page=Mock(side_effect=[([1],3),RuntimeError('global_order_unavailable'),([2],3),([3],3),([],3)])
        fetch,sleep=collector(page)
        with patch('builtins.print'):self.assertEqual(fetch(None,'start','end'),[1,2,3])
        self.assertEqual([c.args[1] for c in page.call_args_list],[1,2,2,3,4])
        sleep.assert_called_once_with(25)

    def test_persistent_failure_never_advances_or_returns_partial_rows(self):
        page=Mock(side_effect=[([1],3),RuntimeError('global_order_unavailable'),RuntimeError('global_order_unavailable'),RuntimeError('global_order_unavailable')])
        fetch,sleep=collector(page)
        with patch('builtins.print'),self.assertRaisesRegex(RuntimeError,'page=2; no_publish'):
            fetch(None,'start','end')
        self.assertEqual([c.args[1] for c in page.call_args_list],[1,2,2,2])
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[25,25])

    def test_first_page_failure_has_same_bounded_retry_and_preserves_page_count(self):
        page=Mock(side_effect=[OSError('synthetic'),OSError('synthetic'),([1],2),([2],2),([],2)])
        fetch,sleep=collector(page)
        with patch('builtins.print'):self.assertEqual(fetch(None,'start','end'),[1,2])
        self.assertEqual([c.args[1] for c in page.call_args_list],[1,1,1,2,3])
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[2,4])


if __name__=='__main__':unittest.main()
