import sys, types, unittest, tempfile, json, datetime, importlib.util
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'source'))
sys.path.insert(0, str(HERE))
login = types.ModuleType('p2pah_browser_login'); login.login = lambda *_: None
session = types.ModuleType('p2pah_session_service'); session.read_private_config = lambda: {}
try:
    import playwright.sync_api
except ImportError:
    package = types.ModuleType('playwright'); browser = types.ModuleType('playwright.sync_api')
    browser.TimeoutError = type('TimeoutError', (Exception,), {})
    browser.sync_playwright = lambda: None
    sys.modules['playwright'] = package; sys.modules['playwright.sync_api'] = browser
with patch.dict(sys.modules, {'p2pah_browser_login': login, 'p2pah_session_service': session}), \
     patch('zoneinfo.ZoneInfo', return_value=datetime.timezone(datetime.timedelta(hours=8))):
    import collect_p2pah_cost as c
import snapshot_layer as s

class CostTypeTest(unittest.TestCase):
    def row(self, platform='PS', record_id='1', kind=None, cost='0.58', minutes=0):
        trade = (datetime.datetime.now(c.SHANGHAI)-datetime.timedelta(minutes=minutes)).replace(tzinfo=None)
        return {'platform': platform, 'record_id': record_id, 'delivery_type': c.ORDER_DELIVERY if kind is None else kind,
                'cny_per_1k': cost, 'trade_at': trade.strftime('%y-%m-%d %H:%M:%S')}

    def ready(self, number=1):
        return {'login': False, 'page': str(number), 'game': '1322', 'product': '1', 'genre': '1',
                'typeHeader': '\u4ea4\u8d27\u7c7b\u578b', 'table': True, 'hasDataRows': True, 'empty': False, 'rows': []}

    def test_query_uses_order_delivery_on_every_page(self):
        for number in [1, 2, 15]:
            query = parse_qs(urlsplit(c.cost_url(number)).query)
            self.assertEqual(query['genre'], ['1']); self.assertEqual(query['page'], [str(number)])

    def test_payment_is_excluded_even_at_normal_price_and_delivery_high_price_is_valid(self):
        self.assertIsNone(c.valid_record(self.row(kind='\u91c7\u8d2d\u6253\u6b3e', cost='0.58')))
        self.assertEqual(c.valid_record(self.row(cost='58.5'))[1]['cny_per_1k'], '58.5')

    def test_known_non_cost_types_are_excluded(self):
        for kind in c.NON_COST_TYPES:
            self.assertIsNone(c.valid_record(self.row(kind=kind)))

    def test_missing_unknown_or_ambiguous_type_fails_closed(self):
        for kind in ['', 'unknown', c.ORDER_DELIVERY+'\n\u91c7\u8d2d\u6253\u6b3e']:
            with self.assertRaisesRegex(ValueError, '^cost_delivery_type_unverified$'):
                c.valid_record(self.row(kind=kind))
        row = self.row(); del row['delivery_type']
        with self.assertRaisesRegex(ValueError, 'cost_delivery_type_unverified'): c.valid_record(row)

    def test_returned_evidence_carries_business_type(self):
        record = c.valid_record(self.row())[1]
        self.assertEqual(record['delivery_type'], c.ORDER_DELIVERY); self.assertEqual(record['genre'], '1')

    def test_ignored_filter_cannot_be_accepted(self):
        for key, value in [('genre', '0'), ('typeHeader', 'other')]:
            data = {**self.ready(), key: value}
            page = types.SimpleNamespace(goto=lambda *a, **kw: None, evaluate=lambda *a: data, wait_for_timeout=lambda *_: None)
            with self.assertRaisesRegex(ValueError, 'filter_or_rows_unverified:1'): c.read_page(page, 1)

    def test_verified_requested_page_and_type_header_are_required(self):
        reads = iter([{**self.ready(2), 'page': '1'}, self.ready(2)])
        page = types.SimpleNamespace(goto=lambda *a, **kw: None, evaluate=lambda *a: next(reads), wait_for_timeout=lambda *_: None)
        self.assertEqual(c.read_page(page, 2)['page'], '2')

    def collect_pages(self, pages):
        tab = types.SimpleNamespace(close=lambda: None)
        context = types.SimpleNamespace(new_page=lambda: tab)
        browser = types.SimpleNamespace(contexts=[context])
        pw = types.SimpleNamespace(chromium=types.SimpleNamespace(connect_over_cdp=lambda *a, **kw: browser))
        manager = types.SimpleNamespace(__enter__=lambda *_: pw, __exit__=lambda *_: False)
        class Manager:
            def __enter__(self): return pw
            def __exit__(self, *a): return False
        def read(_tab, number, observations):
            data = pages[number-1]; observations.append({'requested_page': number, 'genre': '1'})
            return data
        with patch.object(c, 'sync_playwright', return_value=Manager()), patch.object(c, 'read_page', side_effect=read):
            return c.collect()

    def test_mixed_payment_and_delivery_across_pages_selects_latest_delivery(self):
        first = {**self.ready(), 'rows': [self.row(record_id='4487054', kind='\u91c7\u8d2d\u6253\u6b3e', cost='58.5'), self.row(record_id='2', minutes=3)]}
        second = {**self.ready(2), 'rows': [self.row(record_id='3', minutes=1), self.row('XBOX', '4'), self.row('PC', '5')]}
        empty = {**self.ready(3), 'hasDataRows': False, 'empty': True}
        result = self.collect_pages([first, second, empty])
        self.assertEqual(result['status'], 'valid'); self.assertEqual(result['costs'][0]['record_id'], '3')
        self.assertEqual(len(result['page_observations']), 3)

    def test_unknown_type_on_later_page_invalidates_whole_collection_without_old_cost(self):
        first = {**self.ready(), 'rows': [self.row(), self.row('XBOX', '2'), self.row('PC', '3')]}
        second = {**self.ready(2), 'rows': [self.row(record_id='4', kind='')]}
        with self.assertRaisesRegex(ValueError, 'cost_delivery_type_unverified'): self.collect_pages([first, second])

    def test_payment_only_does_not_fall_back_to_saved_cost(self):
        result = self.collect_pages([{**self.ready(), 'rows': [self.row(kind='\u91c7\u8d2d\u6253\u6b3e')]}, {**self.ready(2), 'hasDataRows': False, 'empty': True}])
        self.assertEqual(result['status'], 'incomplete'); self.assertTrue(all(r['status']=='missing' for r in result['costs']))

    def test_snapshot_rejects_old_untyped_or_wrong_typed_success(self):
        rows = [{**c.valid_record(self.row(platform, str(i+1)))[1], 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat()} for i, platform in enumerate(c.PLATFORMS)]
        self.assertEqual(len(s.cost_snapshots('run', {'status':'valid','costs':rows})), 3)
        for mutation in [{'delivery_type':'\u91c7\u8d2d\u6253\u6b3e'}, {'delivery_type':None}, {'genre':'0'}]:
            bad = [dict(row) for row in rows]; bad[0].update(mutation)
            with self.assertRaisesRegex(ValueError, 'cost_delivery_type_unverified'): s.cost_snapshots('run', {'status':'valid','costs':bad})

    def test_type_failure_keeps_previous_run_and_disables_quotes(self):
        report = {'source':'P2PAH','status':'missing','reason':'cost_delivery_type_unverified'}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'runs').mkdir(); old = root/'runs/old.json'; old.write_bytes(b'{"status":"old"}')
            result = types.SimpleNamespace(returncode=1, stdout=json.dumps(report).encode())
            with patch.object(s,'ROOT',root), patch.object(s.subprocess,'run',return_value=result), patch.object(s.os,'chown',create=True):
                summary, success = s.collect_once('00000000-0000-4000-8000-000000000001')
            self.assertFalse(success); self.assertIn('P2PAH:cost_delivery_type_unverified', summary['reason'])
            self.assertEqual(old.read_bytes(), b'{"status":"old"}')
            new = json.loads((root/'runs/00000000-0000-4000-8000-000000000001.json').read_text())
            self.assertEqual(new['quote_status'], 'NO_QUOTE'); self.assertTrue(all(r['status']=='missing' for r in new['costs']))

if __name__ == '__main__': unittest.main(verbosity=2)
