import ast,importlib.util,json,re,sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
SOURCE=Path(__file__).resolve().parents[1]/'source';sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import runtime,selective_sources,engine,monitoring,api
from fc_pricing_v3.ledger import Ledger
import itemd2r_reader as reader
from test_dual20_sprint import source
from fixtures import NOW


def function(name,file,scope):
    node=next(n for n in ast.parse((SOURCE/file).read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),file,'exec'),scope)
    return scope[name]


class OptionalCollection(unittest.TestCase):
    def test_partial_reader_through_worker_quote_api_and_monitor_keeps_each_platform(self):
        page=Mock();page.url=reader.URL;page.goto.return_value=SimpleNamespace(status=200,headers={});page.title.return_value='FC 27 Coins'
        selected={'device':None}
        def locator(selector):
            loc=Mock()
            if selector=='.platform-list li':
                def filtered(*,has_text):
                    item=Mock()
                    item.click.side_effect=lambda **kw:selected.update(device=next(device for _,device,label in reader.DEVICES if has_text.fullmatch(label)))
                    return item
                loc.filter.side_effect=filtered
            return loc
        page.locator.side_effect=locator
        def current(_):
            return dict(device=selected['device'],quantity='100000',tier='100000',tier_label='100 K',delivered='100',method='ai-automatic',
                method_selected=True,usd=True,busy=False,price='invalid' if selected['device']=='1' else '8.00',total='8.00',unit='.00008',fee='0')
        page.evaluate.side_effect=current
        with patch.object(reader,'datetime',SimpleNamespace(now=lambda _:NOW)):
            collected=reader.collect(SimpleNamespace(new_page=lambda:page))
        self.assertEqual([r['status'] for r in collected],['valid','valid','missing'])
        self.assertEqual(collected[2]['reason'],'itemd2r_price_invalid:PC')
        page.close.assert_called_once()
        payload=dict(source='ItemD2R',status='partial',offers=collected)
        collect=function('collect_reference_market','fc_pricing_v3/observations.py',dict(re=re,datetime=datetime,timezone=timezone))
        with patch.object(reader.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(payload))):
            raw=collect('same-run')
        ref=function('reference_context','server_quote_job.py',dict(PLATFORMS=engine.PLATFORMS,re=re))
        context=ref(dict(run_id='same-run',competitors=[],reference_competitors=raw),NOW)
        self.assertEqual(context['status'],'partial')
        self.assertEqual([r['platform'] for r in context['offers']],['PS','XBOX'])
        self.assertEqual(context['missing'],[dict(platform='PC',source='ItemD2R',reason='itemd2r_price_invalid:PC')])
        data=source();data['run_id']='same-run';data['reference_market']=context
        result=engine.evaluate(data,'revenue_sprint',now=NOW)
        self.assertEqual(result['selected']['market_comparison']['console']['anchors']['PS']['source'],'ItemD2R')
        self.assertEqual(result['selected']['market_comparison']['console']['anchors']['XBOX']['source'],'ItemD2R')
        self.assertEqual(result['selected']['market_comparison']['pc']['anchors']['PC']['source'],'Lootbar')
        plan=selective_sources.source_plan('revenue_sprint')
        coverage=selective_sources.planned_source_coverage(dict(run_id='same-run',competitors=[]),plan,NOW,reference_market=context)
        self.assertNotIn(dict(platform='PS',source='ItemD2R'),coverage['optional_missing'])
        self.assertEqual(coverage['reference_sources']['PS'],['ItemD2R'])
        self.assertEqual(coverage['reference_sources']['PC'],[])
        self.assertIn(dict(platform='PC',source='ItemD2R',reason='itemd2r_price_invalid:PC'),coverage['gaps'])
        receipt=dict(plan_id='p',snapshot_id='same-run',snapshot_sha256=engine.fingerprint(data),financial_proof=result['selected']['financial_proof'])
        snapshot=dict(snapshot_id='same-run',origin='live_collector',mode='production',created_at=NOW.isoformat(),evidence=data,result=dict(decision_receipt=receipt))
        monitored=monitoring.source_coverage([snapshot],[dict(plan_id='p',mode='revenue_sprint',resources=['base:console','base:pc'])],NOW)
        self.assertEqual(monitored['status'],'verified',monitored)
        self.assertEqual(monitored['plans'][0]['competitive_sources']['PS']['missing'],[])
        self.assertIn(dict(platform='PC',source='ItemD2R',reason='itemd2r_price_invalid:PC'),monitored['plans'][0]['competitive_sources']['PC']['missing'])
        with tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            root=Path(folder);db=Ledger(root/'control.db')
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):runtime.calculate(data)
            with patch.object(api,'ledger',return_value=db):market=api.read('market')
        self.assertEqual(market['reference']['offers'],context['offers'])
        self.assertEqual(market['reference']['missing'],context['missing'])

    def test_partial_reference_rejects_bad_single_row_without_losing_other_platforms(self):
        ref=function('reference_context','server_quote_job.py',dict(PLATFORMS=engine.PLATFORMS,re=re))
        base=dict(source='ItemD2R',run_id='same',url=reader.URL,status='valid',currency='USD',conditional=False,comparable=True,purchase_k='100',bonus_k='0',gross_usd='8',captured_at=NOW.isoformat())
        for update in (dict(run_id='old'),dict(currency='EUR'),dict(gross_usd='0'),dict(purchase_k='5'),dict(captured_at=(NOW-timedelta(seconds=901)).isoformat())):
            rows=[dict(base,platform='PS'),dict(base,platform='XBOX'),dict(base,platform='PC',**update)]
            with self.subTest(update=update):
                result=ref(dict(run_id='same',competitors=[],reference_competitors=dict(status='captured',run_id='same',offers=rows)),NOW)
                self.assertEqual([r['platform'] for r in result['offers']],['PS','XBOX'])
                self.assertEqual(result['missing'][0]['platform'],'PC')
        rows=[dict(base,platform='PS'),dict(base,platform='XBOX',captured_at=(NOW-timedelta(seconds=301)).isoformat())]
        result=ref(dict(run_id='same',competitors=[],reference_competitors=dict(status='captured',run_id='same',offers=rows)),NOW)
        self.assertEqual(result['offers'],[])
        self.assertEqual(result['reason'],'itemd2r_reference_capture_span_over_300_seconds')

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
        collect=function('collect_reference_market','fc_pricing_v3/observations.py',scope)
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
