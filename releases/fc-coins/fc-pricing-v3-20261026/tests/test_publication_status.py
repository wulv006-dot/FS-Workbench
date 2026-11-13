"""A V3 public-confirmed write must supersede the previous Order audit."""
import ast
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from test_price_curve_v6 import CONTRACT, IDENTITY, goods
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT, curve_key, read_curve


SOURCE = Path(__file__).resolve().parents[1] / 'source/fc27_cloud_api.py'
functions = [node for node in ast.parse(SOURCE.read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name in
             ('admin_curve_publication', 'publication_view', 'legacy_publication_view')]
NOW = datetime(2026, 11, 13, 16, 8, tzinfo=timezone.utc)
SITE = 'https://www.mmoexp.com/Fc-27/Coins.html'
PRODUCTS = {'PS': (163329311, 21587), 'XBOX': (163329277, 21585), 'PC': (163329345, 21589)}


def load_view(root, valid_id=lambda value: False):
    namespace = dict(ROOT=root, datetime=datetime, timezone=timezone, timedelta=timedelta,
                     sqlite3=sqlite3, closing=closing, json=json, Decimal=Decimal, ROUND_HALF_UP=ROUND_HALF_UP,
                     InvalidOperation=InvalidOperation, valid_id=valid_id,
                     read_json=lambda path: json.loads(path.read_text(encoding='utf-8')))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


def curve_operation(ident, platforms, when, *, revision=4, status='COMPLETED'):
    action, results = {}, {}
    contract = dict(CONTRACT, price_edit_policy=TWO_BAND_PRICE_EDIT)
    for platform, price in platforms.items():
        sku, aid = PRODUCTS[platform]
        row = dict(goods(), id=sku, aid=aid)
        row['more']['price'][0] = price
        actual = read_curve(row, dict(IDENTITY, id=sku, aid=aid), contract)
        target = read_curve(dict(row, id=sku-2, site_id=0),
                            dict(IDENTITY, id=sku-2, aid=aid, site_id=0), contract)
        action[platform] = target
        mapping = dict(target_curve_key=curve_key(target), actual_site266_curve_key=curve_key(actual),
                       basis='full_prices_and_tier_specs_readback')
        results[platform] = dict(operation_id=ident, platform=platform, target_curve_key=curve_key(target),
            actual_site266_curve=actual, actual_site266_curve_key=curve_key(actual),
            catalog={'status': 'confirmed'}, projection={'status': 'not_required'},
            propagation=dict(status='confirmed', confirmed_at=when.isoformat(), curve_mapping=mapping))
    return dict(operation_id=ident, status=status, plan_id='p', revision=revision, generation='g',
        completed_at=(when+timedelta(seconds=2)).isoformat(),
        bundle=dict(write_protocol='fc27_curve_v6', affected_platforms=list(platforms), action={'curves': action}),
        readback=dict(write_protocol='fc27_curve_v6', status='CONFIRMED', execution_id=ident, curve_results=results))


class PublicationStatusTest(unittest.TestCase):
    def test_latest_v3_public_confirmation_is_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'executions').mkdir()
            (root / 'previews').mkdir()
            old, new = '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002'
            for ident, when, status, console in ((old, '2026-10-29T14:00:00+00:00', 'CONFIRMED', '0.0715'),
                                                 (new, '2026-10-29T15:00:00+00:00', 'PUBLIC_CONFIRMED', '0.0782')):
                audit = {'execution_id': ident, 'created_at': when, 'status': status, 'sync_confirmed': True,
                         'after': {'exchangeRate': '1', 'rows': [{'platform': platform, 'id': platform,
                                                                  'costPrice': '1', 'lirunlv': '20',
                                                                  'b2c': console if platform != 'PC' else '0.0831'}
                                            for platform in ('PS', 'XBOX', 'PC')]}}
                (root/'executions'/f'{ident}.json').write_text(json.dumps(audit), encoding='utf-8')
            namespace = load_view(root, lambda value: value in {old, new})
            storefront = {'rows': {platform: {'status': 'ok', 'package_usd': price,
                                              'checked_at': '2026-10-29T15:01:00+00:00'}
                                    for platform, price in (('PS', '7.82'), ('XBOX', '7.82'), ('PC', '8.31'))}}
            result = namespace['publication_view'](storefront)
            self.assertEqual((result['status'], result['execution_id']), ('matched', new))
            self.assertEqual([row['status'] for row in result['platforms']], ['matched'] * 3)
            preview_id = '00000000-0000-4000-8000-000000000003'
            namespace['valid_id'] = lambda value: value in {old, new, preview_id}
            preview = {'preview_id': preview_id, 'run_id': preview_id,
                       'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'review_only',
                       'backend_before': dict(audit['after'], gameId='1322', isRoute=True, login=False,
                                              allServerChecked=False, selectedWebsites=0, b2cSelected=True,
                                              origin='https://order.p2pah.cn')}
            (root/'previews'/f'{preview_id}.json').write_text(json.dumps(preview), encoding='utf-8')
            observed = namespace['publication_view'](storefront)
            self.assertEqual((observed['status'], observed['execution_id']), ('matched', new))
            self.assertEqual(observed['basis'], 'confirmed_write_and_matching_backend_preview')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def owned_ledger(self):
        ledger = Ledger(self.root / 'v3/control.sqlite3')
        resources = ['base:' + p for p in PRODUCTS]
        ledger.put('pricing_plans', 'p', dict(plan_id='p', revision=4, generation='g', resources=resources,
                                            state='ACTIVE', write_protocol='fc27_curve_v6'))
        with ledger.transaction() as db:
            db.executemany('INSERT INTO plan_ownership VALUES (?, ?, ?, ?)',
                           [(resource, 'p', 4, 'g') for resource in resources])
        return ledger

    def storefront(self, checked_at, **prices):
        return dict(source=SITE, currency='USD',
                    rows={p: dict(status='ok', platform=p, base_k='100', bonus_k='0',
                                  checked_at=checked_at.isoformat(), sku_id=str(PRODUCTS[p][0]), package_usd=price)
                          for p, price in prices.items()})

    def test_v6_freshness_is_relative_to_each_original_confirmation(self):
        ledger = self.owned_ledger()
        for op in (curve_operation('first', {'PS':'8.62','PC':'8.6'}, NOW-timedelta(minutes=90)),
                   curve_operation('second', {'XBOX':'8.34','PC':'8.6'}, NOW-timedelta(minutes=29)),
                   curve_operation('previous_revision', {'PS':'7.99'}, NOW-timedelta(minutes=8), revision=3),
                   curve_operation('unknown', {'PS':'9.5'}, NOW-timedelta(minutes=5), status='UNKNOWN')):
            ledger.put('operations', op['operation_id'], op)
        storefront = self.storefront(NOW-timedelta(minutes=30), PS='8.62', XBOX='8.10', PC='8.6')
        view = load_view(self.root)['publication_view']
        result = view(storefront, v3_enabled=True, now=NOW)
        self.assertEqual(result['basis'], 'confirmed_admin_site266_curve')
        self.assertEqual(result['status'], 'not_checked_after_write')
        self.assertEqual([(r['platform'],r['execution_id'],r['status']) for r in result['platforms']],
            [('PS','first','matched'), ('XBOX','second','not_checked_after_write'), ('PC','second','not_checked_after_write')])
        self.assertEqual(result['platforms'][1]['backend_page_usd'], '8.34')
        fresh = self.storefront(NOW-timedelta(minutes=5), PS='8.62', XBOX='8.10', PC='8.6')
        result = view(fresh, v3_enabled=True, now=NOW)
        self.assertEqual([r['status'] for r in result['platforms']], ['matched','mismatch','matched'])

    def test_v6_missing_mismapped_and_stale_evidence_remain_pending(self):
        ledger = self.owned_ledger()
        bad = curve_operation('bad', {'PS':'8.62'}, NOW-timedelta(minutes=79))
        bad['readback']['curve_results']['PS']['propagation']['curve_mapping']['basis'] = 'incomplete'
        valid = curve_operation('valid', {'PS':'8.62','XBOX':'8.34','PC':'8.6'}, NOW-timedelta(minutes=90))
        for op in (valid, bad):
            ledger.put('operations', op['operation_id'], op)
        storefront = self.storefront(NOW-timedelta(minutes=76), PS='8.62', XBOX='8.10', PC='8.6')
        storefront['rows']['PC']['sku_id'] = '163329343'  # ALL, not the main-site SKU.
        view = load_view(self.root)['publication_view']
        result = view(storefront, v3_enabled=True, now=NOW)
        self.assertEqual([r['status'] for r in result['platforms']],
                         ['backend_confirmation_pending','stale_or_clock_invalid','unavailable'])
        storefront['rows']['XBOX'].pop('package_usd')
        result = view(storefront, v3_enabled=True, now=NOW)
        self.assertEqual(result['platforms'][1]['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
