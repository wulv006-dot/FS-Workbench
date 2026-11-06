"""Existing IDs must not hide later status corrections in the overlap window."""
import ast
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import history_db as HDB


TREE = ast.parse(Path(__file__).with_name('sales_collection.py').read_text(encoding='utf-8'))


def functions(names, scope):
    nodes = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<actual-sales-refresh>', 'exec'), scope)
    return scope


class Tests(unittest.TestCase):
    def refresh(self, deep):
        hdb = Mock()
        hdb.get_state.return_value = {'high_time': '2026-11-06 14:00:00'}
        hdb.count.return_value = 300
        hdb.load_orders.return_value = []
        fetch = Mock(return_value=[])
        scope = {'datetime': datetime, 'timedelta': timedelta, 'DEFAULT_START': '2026-09-17',
                 'DEEP_DAYS': 7, 'HDB': hdb, 'db': lambda: None,
                 '_deep_due': lambda *_: deep, '_today_str': lambda: '2026-11-06 14:00:00',
                 'fetch_orders_range': fetch}
        constant = next(n for n in TREE.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'ORDER_LOOKBACK_HOURS' for t in n.targets))
        exec(compile(ast.Module(body=[constant], type_ignores=[]), '<actual-lookback>', 'exec'), scope)
        functions({'fetch_orders', '_delta_lo', '_fmt'}, scope)
        with patch('builtins.print'):
            scope['fetch_orders'](None, '2026-09-17', '2026-11-06')
        return fetch.call_args

    def test_daily_refresh_reads_full_48_hours(self):
        call = self.refresh(False)
        self.assertEqual(call.args[1], '2026-11-04 14:00:00')
        self.assertEqual(len(call.args), 3)  # no known-ID stop set
        self.assertEqual(call.kwargs, {})

    def test_weekly_refresh_reads_full_seven_days(self):
        call = self.refresh(True)
        self.assertEqual(call.args[1], '2026-10-30 14:00:00')
        self.assertEqual(len(call.args), 3)

    def test_known_first_page_does_not_hide_completed_order_on_second_page(self):
        page = Mock(side_effect=[([{'id': 3}, {'id': 2}], 3),
                                 ([{'id': 1, 'status_format': '已完成'}], 3)])
        scope = {'PAGE_SIZE': 2, 'MAX_ORDER_PAGES': 10, '_order_page': page,
                 '_should_stop': HDB.should_stop}
        functions({'fetch_orders_range'}, scope)
        with patch('builtins.print'):
            rows = scope['fetch_orders_range'](None, 'start', 'end')
        self.assertEqual(rows[-1]['status_format'], '已完成')
        self.assertEqual(page.call_count, 2)


if __name__ == '__main__':
    unittest.main()
