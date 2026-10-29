import ast,importlib.util,json,re,sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
SOURCE=Path(__file__).resolve().parents[1]/'source';sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import runtime,selective_sources
from fixtures import NOW


def function(name,file,scope):
    node=next(n for n in ast.parse((SOURCE/file).read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),file,'exec'),scope)
    return scope[name]


class OptionalCollection(unittest.TestCase):
    def test_worker_collects_item_even_when_loot_or_hard_snapshot_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runs').mkdir();ident='original'
            (root/'runs/original.json').write_text(json.dumps(dict(run_id=ident,status='incomplete')))
            reference=dict(status='blocked',run_id=ident,offers=[],reason='itemd2r_cloudflare_403',http_status=403)
            scope=dict(ROOT=root,APP=Path('/fixture'),local_collection=SimpleNamespace(pin=lambda _:dict(mode='server')),save_job=Mock(),run=Mock(return_value=(1,dict(status='incomplete',reason='P2PAH:missing'))),collect_reference_market=Mock(return_value=reference),atomic_json=Mock(),os=SimpleNamespace(chown=Mock(),chmod=Mock()),json=json)
            collect=function('collect_quote','fc27_cloud_worker.py',scope)
            job=dict(job_id=ident)
            with patch.object(runtime,'ledger'),patch.object(runtime,'collection_scope',return_value=dict(active_mode='revenue_sprint',scope={})),self.assertRaisesRegex(ValueError,'collection_incomplete'):
                collect(job)
            scope['collect_reference_market'].assert_called_once_with(ident)
            self.assertEqual(scope['atomic_json'].call_args.args[1]['reference_competitors'],reference)
            self.assertEqual(job['error_detail'],'P2PAH:missing')
            self.assertEqual(scope['run'].call_count,1,'hard snapshot failure still prevents quote/writer')

    def test_worker_preserves_safe_source_failure_without_inventing_403(self):
        scope=dict(re=re,datetime=datetime,timezone=timezone)
        collect=function('collect_reference_market','fc27_cloud_worker.py',scope)
        for error,expected in [(ValueError('itemd2r_cloudflare_403'),'itemd2r_cloudflare_403'),(ValueError('itemd2r_http_403'),'itemd2r_http_403'),(TimeoutError(),'TimeoutError')]:
            with self.subTest(expected=expected),patch.dict(sys.modules,{'itemd2r_reader':SimpleNamespace(public_read=Mock(side_effect=error))}):
                result=collect('same-run')
            self.assertEqual(result['reason'],expected);self.assertEqual(result['offers'],[])
            self.assertEqual(result.get('http_status'),403 if expected=='itemd2r_cloudflare_403' else None)

    def test_snapshot_missing_loot_is_optional_but_cost_and_fx_remain_hard(self):
        with patch.dict(sys.modules,{'fc27_quote_engine':SimpleNamespace(source_coverage=lambda _:None)}):
            spec=importlib.util.spec_from_file_location('optional_snapshot',SOURCE/'snapshot_layer.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for hard_failure in (None,'cost','fx'):
            processes=[SimpleNamespace(returncode=1,stdout=b''),SimpleNamespace(returncode=int(hard_failure=='cost'),stdout=b''),SimpleNamespace(returncode=int(hard_failure=='fx'),stdout=b'')]
            with self.subTest(hard_failure=hard_failure),tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),patch.object(module.subprocess,'run',side_effect=processes),patch.object(module,'collector_failure',return_value='TimeoutExpired'),patch.object(module,'cost_snapshots',return_value=[dict(status='valid',platform=p) for p in module.PLATFORMS]),patch.object(module,'newest_evidence',side_effect=lambda pattern,*args:dict(status='valid',checked_at=NOW.isoformat(),cny_per_usd='7')),patch.object(module,'atomic_json') as save,patch.object(module.os,'chown',create=True),patch.object(module.os,'chmod'):
                summary,ready=module.collect_once('00000000-0000-4000-8000-000000000099')
            self.assertEqual(ready,hard_failure is None)
            self.assertIn('Lootbar:TimeoutExpired',summary['source_warnings'])
            if ready:self.assertEqual(summary['status'],'ready_for_quote')

    def test_source_coverage_invalid_time_run_and_platform_never_fill_gap(self):
        plan=selective_sources.source_plan('daily',dict(platforms=['PC']))
        base=dict(platform='PC',source='Lootbar',run_id='same',status='valid',currency='USD',purchase_k='100',gross_usd='10',captured_at=NOW.isoformat())
        for update in (dict(run_id='old'),dict(captured_at=(NOW-timedelta(seconds=901)).isoformat()),dict(platform='PS'),dict(gross_usd='NaN'),dict(purchase_k='bad')):
            with self.subTest(update=update):
                coverage=selective_sources.planned_source_coverage(dict(run_id='same',competitors=[dict(base,**update)]),plan,NOW)
                self.assertTrue(coverage['ready'])
                self.assertIn(dict(platform='PC',source='Lootbar'),coverage['optional_missing'])

    def test_stale_loot_does_not_invalidate_fresh_same_run_item(self):
        scope=dict(PLATFORMS=('PS','XBOX','PC'))
        ref=function('reference_context','server_quote_job.py',scope)
        offers=[dict(source='ItemD2R',platform=p,run_id='same',url='https://www.itemd2r.com/ea-sports-fc/fc-27-coins',status='valid',currency='USD',conditional=False,comparable=True,purchase_k='100',bonus_k='0',gross_usd='10',captured_at=NOW.isoformat()) for p in scope['PLATFORMS']]
        loot=dict(offers[0],source='Lootbar',captured_at=(NOW-timedelta(seconds=901)).isoformat())
        snapshot=dict(run_id='same',competitors=[loot],reference_competitors=dict(status='captured',run_id='same',offers=offers))
        self.assertEqual(ref(snapshot,NOW)['status'],'available')
        snapshot['reference_competitors']['run_id']='old'
        self.assertEqual(ref(snapshot,NOW)['offers'],[])
        self.assertEqual(ref(snapshot,NOW)['reason'],'itemd2r_reference_run_or_coverage')


if __name__=='__main__':unittest.main()
