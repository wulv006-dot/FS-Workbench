"""Fictional native aggregates: a website filter must reach the source and cache identity."""
from datetime import datetime
import copy,sys,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'tests/fixtures')]
import site_summary
from live_summary import query,key_of,SHANGHAI
from daily_archive import summary_key

PROFILE=('FC27','FC 27','1322','1327','sports')
PERIOD=dict(start='2026-10-23 00:00',end='2026-10-24 00:00')

class SiteFilters(unittest.TestCase):
    def make(self,**overrides):
        self.session=Mock();self.session.token='fixture';self.response=Mock(status_code=200,content=b'fixture')
        self.raw=dict(total=2,amount=100,chart_sales_arr=dict(date=['2026-10-23'],n=[2],amount=[100]))
        self.response.json.return_value=dict(code=1,data=self.raw)
        self.session.admin.request.return_value=self.response
        self.auth=types.SimpleNamespace(Session=lambda:self.session,admin_token_from_service=lambda:('fixture',None),ADMIN_API='https://fixture.test')
        self.mapped=dict(metrics={'orders':dict(value=2,status='available'),'newCustomers':dict(value=1,status='available')},dimensions={'channels':[dict(name='www.mmoexp.com',orders=2,revenueUsd=100)]})
        self.fields=types.SimpleNamespace(extract=lambda raw:copy.deepcopy(self.mapped))
        return dict(profile='FC27',profit_site='main',admin_site='266',period=PERIOD,**overrides)

    def run_read(self,q,definition=PROFILE):
        with patch.dict(sys.modules,{'p2pah_auth':self.auth,'supplement_fields':self.fields}):return site_summary.collect(q,definition)

    def test_main_native_site_and_registered_game_status_and_hourly_rows(self):
        for group,status in [('sports',''),('rpg','')]:
            q=self.make();definition=(*PROFILE[:4],group);result=self.run_read(q,definition)
            args=self.session.admin.request.call_args
            self.assertEqual(args.args,('POST','https://fixture.test'+site_summary.ENDPOINT))
            payload=args.kwargs['json'];self.assertEqual((payload['site'],payload['game'],payload['order_status']),(266,'1327',status))
            self.assertEqual(payload['pay_status'],1);self.assertFalse(args.kwargs['allow_redirects'])
            self.assertEqual(result['normalisedScope'],'main-website');self.assertEqual(result['metrics']['newCustomers']['scope'],'MMOEXP')
            self.assertEqual(result['rows'],[dict(date='2026-10-23 00:00',orders=2,amount=100.0)])
            self.session.bind_admin_token.assert_called_once_with('fixture');self.session.close.assert_called_once()

    def test_wrong_or_unproved_nonzero_website_never_becomes_main(self):
        for channels in ([],[dict(name='www.rsorders.com')],[dict(name='www.mmoexp.com'),dict(name='www.rsorders.com')]):
            q=self.make();self.mapped['dimensions']['channels']=channels
            with self.assertRaisesRegex(ValueError,'filter_not_applied'):self.run_read(q)
            self.session.close.assert_called_once()

    def test_all_site_paid_orders_and_native_trend_share_totals(self):
        import json
        self.make()
        with patch.dict(sys.modules,{'supplement_fields':self.fields}):
            import admin_summary
        read=Mock(return_value=(200,json.dumps(dict(code=1,data=self.raw))))
        result=admin_summary.collect(read,'891',PERIOD['start'],PERIOD['end'])
        self.assertTrue(all(value=='' for value in admin_summary.GAMES.values()))
        self.assertEqual(set(admin_summary.GAMES),{'','552','456','891','1327','1329','1309','927','1307','833','506','1333','925','589','1367','897','859'})
        filters=read.call_args.kwargs['data']
        self.assertEqual((filters['game'],filters['site'],filters['pay_status'],filters['order_status']),('891','',1,''))
        self.assertTrue(result['labelsVerified']);self.assertEqual(result['currency'],'USD')
        self.assertEqual(result['rows'],[dict(date='2026-10-23 00:00',orders=2,amount=100.0)])
        self.raw['chart_sales_arr']['date']=['upstream unknown label']
        read.return_value=(200,json.dumps(dict(code=1,data=self.raw)))
        result=admin_summary.collect(read,'891',PERIOD['start'],PERIOD['end'])
        self.assertEqual(result['metrics']['orders']['value'],2)
        self.assertFalse(result['labelsVerified']);self.assertEqual(result['rows'],[])

    def test_paid_cohort_cache_does_not_reuse_completed_only_archive(self):
        args=dict(mode=['summary'],profile=['FC27'],start=['2026-10-23'],end=['2026-10-23'])
        paid=query(args,{'FC27':PROFILE},datetime(2026,10,25,12,tzinfo=SHANGHAI))
        old=dict(paid,contractId='admin-main-order-labelled-supplement-v1')
        self.assertNotEqual(key_of(paid),key_of(old))
        self.assertNotEqual(summary_key(paid),summary_key(old))

    def test_native_callers_use_paid_admin_and_keep_order_completion_reference(self):
        import ast
        definitions=[('AION2','Aion 2',826,891,'rpg'),PROFILE]
        tree=ast.parse((ROOT/'source/collector.py').read_text(encoding='utf-8'))
        collect=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='collect')
        loop=next(n for n in collect.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='PROFILES')
        values=dict(PROFILES=definitions,order=[],admin=[],start=PERIOD['start'],cutoff=PERIOD['end'],history='2026-09-01 00:00')
        exec(compile(ast.Module(body=[loop],type_ignores=[]),'collector-requests','exec'),values)
        self.assertEqual([r['status'] for r in values['admin']],['',''])
        self.assertEqual([r['status'] for r in values['order']],['3','3','',''])
        tree=ast.parse((ROOT/'source/range_api.py').read_text(encoding='utf-8'))
        capture=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_capture')
        assignments=[n for n in ast.walk(capture) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('admin','order') for t in n.targets)]
        for definition in definitions:
            values=dict(gid=definition[2],game=definition[3],group=definition[4],period=PERIOD)
            exec(compile(ast.Module(body=assignments,type_ignores=[]),'range-requests','exec'),values)
            self.assertEqual(values['admin']['status'],'')
            self.assertEqual(values['order']['status'],'3' if definition[4]=='rpg' else '')

    def test_rpg_native_job_id_isolated_without_changing_non_rpg_cache_query(self):
        import ast,re
        from datetime import date,timedelta
        tree=ast.parse((ROOT/'source/range_api.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='query')
        definitions={'AION2':('AION2','Aion 2',826,891,'rpg'),'FC27':PROFILE}
        namespace=dict(PROFILE_MAP=definitions,datetime=datetime,date=date,timedelta=timedelta,SHANGHAI=SHANGHAI,re=re)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'range-query','exec'),namespace)
        metadata=dict(catalogId='fixture',snapshotId='fixture')
        def selection(profile):return namespace['query']({k:[v] for k,v in dict(profile=profile,start='2026-10-23',end='2026-10-23',snapshotId='fixture').items()},metadata)
        rpg=selection('AION2');self.assertEqual(rpg['adminCohort'],'paid-all-status-v2')
        self.assertNotIn('adminCohort',selection('FC27'))

    def test_zero_and_permission_failure_and_missing_session(self):
        q=self.make();self.raw.update(total='0',amount='0',chart_sales_arr=dict(date=[],n=[],amount=[]));self.mapped['dimensions']['channels']=[]
        self.assertEqual(self.run_read(q)['rows'],[])
        q=self.make();self.response.status_code=403
        with self.assertRaises(PermissionError):self.run_read(q)
        self.session.close.assert_called_once()
        q=self.make();self.auth.admin_token_from_service=lambda:(None,'shared_admin_unavailable')
        with self.assertRaises(OSError):self.run_read(q)
        self.session.admin.request.assert_not_called();self.session.close.assert_called_once()

    def test_website_identity_splits_main_all_and_legacy_archives(self):
        args=dict(mode=['summary'],profile=['FC27'],start=['2026-10-23'],end=['2026-10-23'],profit_basis=['actual'])
        profiles={'FC27':PROFILE};now=datetime(2026,10,25,12,tzinfo=SHANGHAI)
        main=query({**args,'profit_site':['main']},profiles,now);all_sites=query({**args,'profit_site':['all']},profiles,now)
        self.assertEqual(main['admin_site'],'266');self.assertEqual(all_sites['admin_site'],'all')
        self.assertEqual(main['site'],'www.mmoexp.com');self.assertEqual(all_sites['site'],'all-websites')
        self.assertNotEqual(key_of(main),key_of(all_sites));legacy={k:v for k,v in main.items() if k!='admin_site'}
        self.assertNotEqual(summary_key(main),summary_key(legacy));self.assertNotEqual(summary_key(main),summary_key(all_sites))
        omitted=query(args,profiles,now)
        self.assertNotIn('admin_site',omitted)
        self.assertEqual(summary_key(omitted),summary_key(legacy))

    def test_actual_profit_keeps_its_original_site_cache_identity(self):
        from actual_profit import selection,CONTRACT
        profiles={'FC27':PROFILE}
        for site in ('main','all'):
            args=dict(mode=['actual-profit'],profile=['FC27'],start=['2026-10-23'],end=['2026-10-23'],profit_site=[site])
            actual=selection(args,profiles)
            old=query({**args,'mode':['summary']},profiles)
            old.pop('admin_site',None);old['site']='www.mmoexp.com';old['cacheSeconds']=7200
            self.assertNotIn('admin_site',actual);self.assertEqual(actual['contractId'],CONTRACT)
            self.assertEqual({k:v for k,v in actual.items() if k!='contractId'},{k:v for k,v in old.items() if k!='contractId'})
            self.assertEqual(actual['profit_site'],site)

    def test_bridge_uses_direct_admin_even_with_retired_channel_setting(self):
        import summary_bridge
        q=self.make();factory=Mock()
        with patch.object(summary_bridge,'SummaryCache',factory):summary_bridge.build({'FC27':PROFILE},Mock(),Mock(),Path('/unused'))
        admin=factory.call_args.args[0]
        with patch.object(site_summary,'collect',return_value={'fixture':'main'}) as read:
            self.assertEqual(admin(q),{'fixture':'main'});read.assert_called_once_with(q,PROFILE)
        read=Mock(return_value={'fixture':'all'})
        with patch.dict(sys.modules,{'admin_summary':types.SimpleNamespace(collect=read)}),patch.dict('os.environ',{'FS_SUMMARY_ADMIN_CHANNEL':'session'}):
            self.assertEqual(admin({**q,'profit_site':'all','admin_site':'all'}),{'fixture':'all'})
            self.assertEqual(admin({k:v for k,v in q.items() if k!='admin_site'}),{'fixture':'all'})
            self.assertEqual(read.call_args.args,(summary_bridge.dc_request,'1327',PERIOD['start'],PERIOD['end']))

if __name__=='__main__':unittest.main()
