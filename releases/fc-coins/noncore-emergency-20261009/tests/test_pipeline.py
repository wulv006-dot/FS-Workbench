"""Isolated source-policy, cross-language and write-boundary acceptance."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

HERE = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(HERE / 'source'), str(ROOT / 'fc27_cloud_browser'), '/opt/fc27-cloud-browser']
import fc27_quote_engine as engine
import snapshot_layer as snapshots
import server_quote_job as quotes
import automation_policy as policy


def fixture(missing=(), own='30.00'):
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    run_id = str(uuid.uuid4())
    competitors = []
    costs = []
    storefront = {'source': 'https://www.mmoexp.com/Fc-27/Coins.html', 'currency': 'USD',
                  'collection_run_id': run_id, 'status': 'ok', 'package_k': 100, 'rows': {}}
    for p in engine.PLATFORMS:
        for site, price in {'Lootbar': '20.00', 'U4GM': '18.00', 'IGGM': '19.00', 'U7Buy': '19.50'}.items():
            row = {'run_id': run_id, 'platform': p, 'source': site, 'status': 'missing', 'reason': 'http_blocked'}
            if site not in missing:
                row.update(status='valid', currency='USD', gross_usd=price, purchase_k='100', bonus_k='0',
                           captured_at=stamp, comparable=True, url='https://' + site.lower() + '.example/item',
                           effective_usd_per_k=str(Decimal(price) / 100))
            competitors.append(row)
        costs.append({'run_id': run_id, 'platform': p, 'status': 'valid', 'game': 'FC27',
                      'product': 'Game Coins', 'unit': 'CNY/K', 'record_id': '12345',
                      'checked_at': stamp, 'trade_at': stamp, 'cny_per_1k': '0.5'})
        storefront['rows'][p] = {'platform': p, 'status': 'ok', 'sku_id': '12345', 'base_k': '100',
                                 'bonus_k': '5', 'package_usd': own, 'checked_at': stamp,
                                 'usd_per_k': str((Decimal(own) / 105).quantize(Decimal('0.000001')))}
    return {'run_id': run_id, 'created_at': stamp, 'status': 'ready_for_quote',
            'competitors': competitors, 'costs': costs, 'storefront': storefront,
            'fx': {'status': 'valid', 'checked_at': stamp, 'cny_per_usd': '5'}}


def configured():
    return {**policy.initial_policy(), 'system_enabled': True, 'mode': 'auto', 'revision': 29}


def quote(snapshot):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'runs').mkdir()
        (root / 'runs' / (snapshot['run_id'] + '.json')).write_text(json.dumps(snapshot), encoding='utf8')
        with patch.object(quotes, 'ROOT', root), patch.object(quotes, 'load_policy', return_value=configured()):
            return quotes._quote_for_run(snapshot['run_id'], persist=False, expected_revision=29)


def js_preview(value):
    code = "const L=require(process.argv[1]);let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>{console.log(JSON.stringify(L.buildPreview(JSON.parse(s))));});"
    # Keep browser-style real clock checks in the independent JS implementation.
    result = subprocess.run(['node', '-e', code, str(HERE / 'source/repricing_logic.js')],
                            input=json.dumps(value), capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr)
    return json.loads(result.stdout)


class Pipeline(unittest.TestCase):
    def collect_isolated(self, unavailable):
        source = fixture()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'evidence').mkdir()
            def run(args, **kwargs):
                name = Path(args[0]).name; site = args[1] if len(args)>1 else None
                calls.append(site or name)
                prefix = {'collect_lootbar.sh':'lootbar', 'collect_p2pah_cost.sh':'p2pah-cost',
                          'collect_fx.sh':'fx'}.get(name, site)
                path = root/'evidence'/(prefix+'-'+str(uuid.uuid4())+'.json')
                if prefix=='lootbar':
                    if 'Lootbar' in unavailable:
                        payload = {'stage':'failed','reason':'platform_timeout:XBOX'}
                        code = 1
                    else:
                        payload = {'stage':'complete','read_only':True,'checked_at':source['created_at'],
                                   'offers':{p:{'platform':p,'coupon_excluded':True,'usd_price':'20.00',
                                                'base_k':'100','bonus_k':'0'} for p in engine.PLATFORMS}}
                        code = 0
                    path = path.with_suffix('.jsonl')
                    path.write_text(json.dumps({'stage':'ps_restored'})+'\n'+json.dumps(payload), encoding='utf8')
                else:
                    code = int(prefix in unavailable)
                    if prefix=='p2pah-cost':
                        payload = {'status':'valid','costs':[dict(c, genre='1', delivery_type='订单发货') for c in source['costs']]}
                    elif prefix=='fx': payload = source['fx']
                    elif code: payload = {'source':site,'status':'missing','reason':'http_blocked'}
                    else: payload = {'source':site,'status':'valid','offers':[c for c in source['competitors'] if c['source']==site]}
                    path.write_text(json.dumps(payload), encoding='utf8')
                return types.SimpleNamespace(returncode=code, stdout=b'', stderr=b'')
            # Only filesystem ownership is platform-specific; all source parsers run unchanged.
            with patch.object(snapshots, 'ROOT', root), patch.object(snapshots.subprocess, 'run', side_effect=run), \
                    patch.object(snapshots.os, 'chown', create=True):
                summary, ready = snapshots.collect_once()
            saved = json.loads((root/'runs'/(summary['run_id']+'.json')).read_text())
            return saved, ready, calls

    def test_actual_collectors_normalize_missing_and_still_recheck_all_sources(self):
        for unavailable in (('IGGM',), ('U4GM', 'IGGM')):
            saved, ready, calls = self.collect_isolated(unavailable)
            self.assertTrue(ready)
            self.assertEqual(set(saved['source_coverage']['unavailable_sources']), set(unavailable))
            self.assertTrue(all(site in calls for site in ('IGGM','U4GM','U7Buy')))
            for row in saved['competitors']:
                if row['source'] in unavailable:
                    self.assertEqual(row['status'], 'missing')
                    self.assertNotIn('gross_usd', row)
                    self.assertIn('http_blocked', row['reason'])
        recovered, ready, _ = self.collect_isolated(())
        self.assertTrue(ready)
        self.assertEqual(recovered['source_coverage']['unavailable_sources'], [])

    def test_actual_collector_core_failure_not_degraded(self):
        saved, ready, _ = self.collect_isolated(('Lootbar',))
        self.assertFalse(ready)
        self.assertEqual(saved['quote_status'], 'NO_QUOTE')

    def test_all_tiers_normal_match_original(self):
        spec = importlib.util.spec_from_file_location('original_engine', HERE / 'tests/legacy_engine.py')
        original = importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
        for own in ('30.00', '16.00', '14.00', '12.00'):
            with self.subTest(own=own):
                value = quote(fixture(own=own))
                actual = copy.deepcopy(value['result'])
                for row in actual['rows']:
                    row.pop('unavailable_sources'); row.pop('reference_sources')
                self.assertEqual(actual, original.calculate(value['evidence'], value['edits']))

    def test_each_reference_and_tiers_match_js_and_write_gate(self):
        for missing in ((), ('IGGM',), ('U4GM',), ('U7Buy',), ('U4GM', 'IGGM')):
            for own in ('30.00', '16.00', '14.00', '12.00'):
                with self.subTest(missing=missing, own=own):
                    value = quote(fixture(missing, own))
                    preview = js_preview(value)
                    self.assertEqual([r['proposal'] for r in value['result']['rows']],
                                     [r['quote'] for r in preview['targets']])
                    self.assertEqual(policy.check_write(configured(), value, list(engine.PLATFORMS), automatic=True), [])
                    for row in value['result']['rows']:
                        self.assertEqual(row['unavailable_sources'], list(missing))
                        self.assertTrue(row['reference_sources'])

    def test_missing_core_or_all_references_rejected(self):
        for missing in (('Lootbar',), ('U4GM', 'IGGM', 'U7Buy')):
            with self.assertRaises(ValueError): quote(fixture(missing))

    def test_snapshot_corruption_not_missing(self):
        mutations = [lambda s: s['competitors'].append(s['competitors'][0]),
                     lambda s: s['competitors'][1].update(status='unknown'),
                     lambda s: s['competitors'][1].update(run_id=str(uuid.uuid4())),
                     lambda s: s['competitors'][1].update(currency='CNY'),
                     lambda s: s['competitors'][1].update(captured_at=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()),
                     lambda s: s['competitors'][1].update(captured_at=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()),
                     lambda s: s['competitors'][1].update(gross_usd='NaN'),
                     lambda s: s['competitors'][1].update(comparable=False),
                     lambda s: s['costs'][0].update(status='missing'),
                     lambda s: s['fx'].update(status='missing'),
                     lambda s: s['storefront'].update(collection_run_id=str(uuid.uuid4()))]
        for mutate in mutations:
            source = fixture(('IGGM',)); mutate(source)
            with self.assertRaises((ValueError, ArithmeticError)): quote(source)

    def test_u7_fallback_validation(self):
        for fields in ({'comparable': False}, {'gross_usd': '19.501'}, {'purchase_k': '99'}, {'bonus_k': '101'}):
            source = fixture(('U4GM', 'IGGM'))
            source['competitors'][3].update(fields)
            with self.assertRaises((ValueError, ArithmeticError)): quote(source)

    def test_coverage_duplicate_missing_and_invalid_status(self):
        source = fixture(('IGGM',))['competitors']
        self.assertTrue(engine.source_coverage(source)['ready'])
        for bad in (source[:-1], source + [source[0]], [dict(r, status='unknown') for r in source]):
            with self.assertRaises(ValueError): engine.source_coverage(bad)

    def test_policy_rejects_tampered_price_and_revision(self):
        value = quote(fixture(('U4GM', 'IGGM')))
        value['result']['rows'][0].update(proposal='0.1949', target_page_usd='19.49')
        with self.assertRaisesRegex(ValueError, 'automatic_tier_rule'): policy.check_write(configured(), value, ['PS'], automatic=True)
        value = quote(fixture(('IGGM',))); value['automation_policy_revision'] = 28
        with self.assertRaisesRegex(ValueError, 'changed_since_quote'): policy.check_write(configured(), value, ['PS'], automatic=True)

    def test_original_writer_rejects_tampered_approved_preview(self):
        browser = types.ModuleType('playwright.sync_api'); browser.sync_playwright = lambda: None
        mirror = types.ModuleType('coin_all_sync_job'); mirror.mirror_confirmed = lambda *a: None
        with patch.dict(sys.modules, {'playwright.sync_api': browser, 'coin_all_sync_job': mirror}):
            spec = importlib.util.spec_from_file_location('original_writer', HERE/'tests/legacy_price_writer.py')
            writer = importlib.util.module_from_spec(spec); spec.loader.exec_module(writer)
        value = quote(fixture(('U4GM','IGGM')))
        preview = js_preview(value)
        page = types.SimpleNamespace(evaluate=lambda script, payload: js_preview(payload))
        writer.revalidate_evidence(page, value, preview)
        preview['targets'][0]['quote'] = '0.1949'
        with self.assertRaisesRegex(ValueError, 'preview_evidence_changed'):
            writer.revalidate_evidence(page, value, preview)

    def test_legacy_missing_still_blocks(self):
        value = quote(fixture(('IGGM',)))['evidence']; value.pop('game')
        self.assertIsNone(engine.calculate(value)['rows'][0]['proposal'])

    def test_latest_api_returns_new_degraded_not_older_full(self):
        import fc27_cloud_api as api
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'runs').mkdir(); (root/'quotes').mkdir()
            old, new = fixture(), fixture(('IGGM',))
            for source in (old, new):
                (root/'runs'/(source['run_id']+'.json')).write_text(json.dumps(source), encoding='utf8')
            import os
            os.utime(root/'runs'/(old['run_id']+'.json'), (100, 100))
            with patch.object(api, 'ROOT', root):
                attempt, selected = api.latest_complete_collection()
            self.assertEqual(selected['run_id'], new['run_id'])
            self.assertEqual(selected['unavailable_sources'], ['IGGM'])
            self.assertEqual(len(selected['competitors']), 9)
            self.assertTrue(all(r['status']=='valid' for r in selected['competitors']))


if __name__ == '__main__': unittest.main()
