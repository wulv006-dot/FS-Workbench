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
        for group,status in [('sports',''),('rpg','101')]:
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
        from actual_profit import selection
        profiles={'FC27':PROFILE}
        for site in ('main','all'):
            args=dict(mode=['actual-profit'],profile=['FC27'],start=['2026-10-23'],end=['2026-10-23'],profit_site=[site])
            actual=selection(args,profiles)
            old=query({**args,'mode':['summary']},profiles)
            old.pop('admin_site',None);old['site']='www.mmoexp.com'
            self.assertNotIn('admin_site',actual);self.assertEqual(key_of(actual),key_of(old))
            self.assertEqual(actual['profit_site'],site)

    def test_bridge_reuses_old_all_endpoint_and_new_filtered_main(self):
        import summary_bridge
        q=self.make();factory=Mock()
        with patch.object(summary_bridge,'SummaryCache',factory):summary_bridge.build({'FC27':PROFILE},Mock(),Mock(),Path('/unused'))
        admin=factory.call_args.args[0]
        with patch.object(site_summary,'collect',return_value={'fixture':'main'}) as read:
            self.assertEqual(admin(q),{'fixture':'main'});read.assert_called_once_with(q,PROFILE)
        with patch.object(summary_bridge.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=b'{"code":200,"body":{"fixture":"all"}}')) as call:
            self.assertEqual(admin({**q,'profit_site':'all','admin_site':'all'}),{'fixture':'all'})
            self.assertEqual(admin({k:v for k,v in q.items() if k!='admin_site'}),{'fixture':'all'})
            self.assertIn('/business/summary?',call.call_args.kwargs['input'].decode())

if __name__=='__main__':unittest.main()
