import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from concurrent.futures import Future
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[4]
SOURCE = Path(__file__).resolve().parents[1]/'source'
sys.path[:0] = [str(SOURCE), str(ROOT/'mmoexp_google_data/details')]
import traffic_contract as contract
import collect_details as collector
import detail_model as model
import report_tracks
import marketing_snapshot as marketing
import range_api
import action_ledger


class ContractTests(unittest.TestCase):
    def test_main_site_rejects_invalid_orders_without_relabelling_raw_total(self):
        for invalid in (True, ' ', None, 1.5, 'NaN'):
            main=contract.main_site_values({'dimensions':{'channels':[{'code':'www.mmoexp.com','orders':invalid,'revenueUsd':10}]}})
            self.assertIsNone(main['values']['orders'])
        main=contract.main_site_values({'dimensions':{'channels':[{'code':'www.mmoexp.com','orders':0,'revenueUsd':0}]}})
        self.assertEqual(main['values']['orders'],0)
        missing=contract.main_site_values({'orders':100,'revenueUsd':1000})
        self.assertEqual(missing['basis'],'main_website_row_unavailable')

    def test_admin_zero_and_missing(self):
        self.assertEqual(contract.source_value(0, 25), (0, 'Admin'))
        self.assertEqual(contract.source_value(None, 25), (25, 'Order'))
        self.assertEqual(contract.source_value(None, None), (None, None))

    def test_global_brand_precedes_content_classification(self):
        for label in ('google-FC27-PMAX-Coins-US', 'FC27-PMAX-Coins-US', ' GOOGLE-fc27-pmax-coins-us '):
            self.assertEqual(contract.campaign_scope(label)['campaign_scope'], 'global_brand')
            self.assertIsNone(contract.campaign_scope(label)['game_target'])
            self.assertIsNotNone(contract.content_match_basis(label))
        self.assertEqual(contract.campaign_scope('FC27-Search-Coins')['game_target'], 'FC27')
        for label in ('Madden Coins', 'FC26 Coins', 'FC270', 'unnamed-retired-series'):
            self.assertIsNone(contract.campaign_scope(label)['game_target'])

    def test_empty_source_natural_unmatched_ad_retained(self):
        self.assertFalse(contract.order_source(' ')['verified_seo'])
        self.assertEqual(contract.order_source(None)['category'], 'business_natural')
        value=contract.order_source('google-old-series')
        self.assertEqual(value['source_raw'], 'google-old-series')
        self.assertEqual(value['campaign_scope'], 'unmatched')

    def test_half_open_month_and_leap_boundary(self):
        self.assertEqual(contract.closed_range('2024-02-01', '2024-03-01'), ('2024-02-01','2024-02-29'))
        with self.assertRaises(ValueError): contract.closed_range('2026-10-17','2026-10-17')

    def test_revenue_contributions_reconcile_and_zero_missing(self):
        from decimal import Decimal
        value=contract.revenue_decomposition(100,1000,80,880)
        self.assertEqual(Decimal(value['order_contribution'])+Decimal(value['aov_contribution']),Decimal('-120'))
        self.assertEqual(contract.revenue_decomposition(0,0,10,100)['status'],'unavailable')
        for bad in ('NaN', 'Infinity', -1):
            with self.assertRaises(ValueError): contract.revenue_decomposition(bad,0,10,100)


class DataConsumerTests(unittest.TestCase):
    def account(self, count=15):
        lo=hi='2026-10-15';rows=[]
        for i in range(count):
            name='other-'+str(i)
            if i==0:name='FC27-PMAX-Coins-US'
            if i==count-1:name='FC27-exclusive-small'
            rows.append({'dimensions':{'date':lo,'customerId':'1430398974','campaignId':str(i+1),'campaignName':name},
                         'metrics':{'impressions':'100','clicks':'10','costMicros':str((count-i)*1000000),'conversions':'2','conversionsValue':'4','interactions':'20','conversionsFromInteractionsRate':'.1'}})
        report={'rows':rows,'start_date':lo,'end_date':hi,'quality':{'pagination_complete':True},'collected_at':'2026-10-16T00:10:00Z'}
        daily=copy.deepcopy(report);daily['rows']=[{'dimensions':{'date':lo},'metrics':{'impressions':str(count*100),'clicks':str(count*10),'costMicros':str(sum((count-i)*1000000 for i in range(count))),'conversions':str(count*2),'conversionsValue':str(count*4)}}]
        period=model.make_period(lo,hi,{('ads','1430398974','daily'):daily,('ads','1430398974','campaign'):report})
        return period,period['adsAccounts'][0]

    def projected(self,period):
        payload={'schemaVersion':1,'isMock':False,'data_generated_at':'2026-10-16T00:12:00Z','details':{'schemaVersion':1,'isMock':False,'periods':[period]}}
        return marketing.projection(payload,{'profile':'FC27','start':period['start'],'end':period['end']},'f'*64)

    def test_beyond_top12_reaches_real_hermes_consumer(self):
        period,account=self.account()
        self.assertEqual(len(account['campaigns']),12)
        self.assertEqual(len(account['calculation_campaigns']),15)
        view=report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]
        self.assertEqual(view['metrics']['cost'],'1')
        self.assertTrue(view['selection_complete'])
        self.assertEqual(len(view['global_brand_campaigns']),1)
        self.assertIsNone(view['fc_allocated_brand_cost'])
        self.assertEqual(view['global_brand_campaigns'][0]['metrics']['cost'],'15')

    def test_legacy_top_no_fc_is_not_zero(self):
        period,account=self.account();del account['calculation_campaigns'];del account['campaign_calculation_complete']
        value=report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]
        self.assertFalse(value['selection_complete']);self.assertIsNone(value['metrics']['cost'])

    def test_full_empty_selection_and_missing_source_differ(self):
        period,account=self.account()
        for row in account['calculation_campaigns']:row['campaignName']='other-'+row['campaignId']
        full=report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]
        self.assertTrue(full['selection_complete']);self.assertEqual(full['metrics']['cost'],'0')
        account['campaign_calculation_complete']=False
        missing=report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]
        self.assertFalse(missing['selection_complete']);self.assertIsNone(missing['metrics']['cost'])

    def test_native_cvr_not_click_ratio_or_average(self):
        row={'metrics':{'impressions':'100','clicks':'10','costMicros':'1000000','conversions':'2','conversionsValue':'5','interactions':'40','conversionsFromInteractionsRate':'.05'}}
        self.assertEqual(model.ads_sum([row])['nativeCvr'],'.05')
        self.assertIsNone(model.ads_sum([row,row])['nativeCvr'])
        del row['metrics']['interactions'];del row['metrics']['conversionsFromInteractionsRate']
        self.assertIsNone(model.ads_sum([row])['nativeCvr']);self.assertIsNone(model.ads_sum([row])['interactions'])

    def test_daily_range_not_reconstructed_as_week(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close);db.executescript(collector.SCHEMA)
        collector.save(db,'ga4','541418940','total','2026-10-15','2026-10-15',{'rows':[{'dimensions':{},'metrics':{'activeUsers':'14'}}]})
        value=model.build(db);self.assertEqual(value['periods'][0]['start'],'2026-10-15')
        self.assertEqual(value['business_contract']['scopeContractId'],'admin-main-order-labelled-supplement-v1')

    def test_exact_period_reader_and_pending_not_older_week(self):
        period,account=self.account();args={'profile':'FC27','start':period['start'],'end':period['end']}
        baseline={'schemaVersion':1,'isMock':False,'details':{'schemaVersion':1,'isMock':False,'periods':[]}}
        with tempfile.TemporaryDirectory() as folder, patch.object(marketing,'PUBLISHED',Path(folder)/'data.json'):
            marketing.PUBLISHED.write_text(json.dumps(baseline))
            reader=marketing.MarketingReader(exact_reader=lambda q:dict(status='available',period=period,generatedAt='2026-10-16T00:10:00Z'))
            self.assertEqual(reader(args)['query'],args)
            reader.exact_reader=lambda q:{'status':'pending'}
            self.assertEqual(reader(args)['status'],'pending')
            reader.exact_reader=lambda q:{'status':'busy'}
            self.assertEqual(reader(args)['status'],'busy')

    def test_ad_group_query_pages_and_deduplicates_by_group(self):
        reader=collector.Reader();reader.metadata['1430398974']={'id':'1430398974'};calls=[]
        def request(source,url,body):
            calls.append(dict(body));n=len(calls)
            row={'campaign':{'id':'1','name':'FC27 Search','advertisingChannelType':'SEARCH'},'adGroup':{'id':str(n),'name':'Group '+str(n),'status':'ENABLED'},'metrics':{'costMicros':'1000000'}}
            return {'results':[row],**({'nextPageToken':'next'} if n==1 else {})}
        reader.request=request
        value=reader.ads('1430398974','ad_group_total','2026-10-01','2026-10-15')
        self.assertEqual(len(value['rows']),2);self.assertEqual(calls[1]['pageToken'],'next')
        self.assertIn('FROM ad_group',calls[0]['query']);self.assertNotIn('SELECT segments.date',calls[0]['query'])
        self.assertNotIn('metrics.conversions_value_per_cost',calls[0]['query'])
        self.assertIn('derived',value['quality']['platform_roas_basis'])
        self.assertNotIn('date',value['rows'][0]['dimensions'])
        self.assertIsNone(value['rows'][0]['metrics']['conversionsFromInteractionsRate'])
        reader.request=lambda *args: {'results':[{'campaign':{'id':'1','name':'FC27','advertisingChannelType':'SEARCH'},'adGroup':{'id':'1','name':'a'}}]*2}
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ADS_DATE_ID'):reader.ads('1430398974','ad_group_total','2026-10-01','2026-10-15')
        reader.request=lambda *args: {'results':[{'campaign':{'id':'1','advertisingChannelType':'PERFORMANCE_MAX'},'adGroup':{'id':'1'}}]}
        with self.assertRaisesRegex(ValueError,'PMAX_AD_GROUP_UNEXPECTED'):reader.ads('1430398974','ad_group_total','2026-10-01','2026-10-15')

    def test_ad_groups_reach_hermes_without_double_counting_or_brand_leak(self):
        period,account=self.account();lo,hi=period['start'],period['end']
        campaigns=account['calculation_campaigns'];fc=next(r for r in campaigns if contract.campaign_scope(r['campaignName'])['game_target']=='FC27');brand=next(r for r in campaigns if contract.campaign_scope(r['campaignName'])['campaign_scope']=='global_brand')
        groups=[]
        for row in (fc,brand):
            for n in range(15):
                groups.append({'dimensions':{'customerId':'1430398974','campaignId':row['campaignId'],'campaignName':row['campaignName'],'channelType':'SEARCH','adGroupId':str(n+1),'adGroupName':'Group '+str(n),'adGroupStatus':'ENABLED'},'metrics':{'costMicros':'1000000','impressions':'10','clicks':'2','conversions':'1','conversionsValue':'3','interactions':'2','conversionsFromInteractionsRate':'.5'}})
        report={'rows':groups,'quality':{'pagination_complete':True},'start_date':lo,'end_date':hi}
        extra=model.make_period(lo,hi,{('ads','1430398974','ad_group_total'):report})['adsAccounts'][0]
        account['ad_groups']=extra['ad_groups']
        before=copy.deepcopy(account['metrics'])
        view=report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]
        self.assertEqual(len(view['ad_groups']['rows']),15);self.assertEqual(len(view['global_brand_ad_groups']),15)
        self.assertTrue(view['ad_groups']['calculation_complete']);self.assertEqual(account['metrics'],before)
        self.assertEqual(view['ad_groups']['rows'][0]['metrics']['nativeCvr'],'0.5')
        account['campaign_calculation_complete']=False
        self.assertFalse(report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]['ad_groups']['calculation_complete'])
        account['campaign_calculation_complete']=True
        account['ad_groups']['status']={'status':'failed','retained_previous':True}
        account['ad_groups']['calculation_complete']=False
        stale=report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]['ad_groups']
        self.assertFalse(stale['calculation_complete']);self.assertTrue(stale['status']['retained_previous']);self.assertEqual(len(stale['rows']),15)
        account.pop('ad_groups');missing=report_tracks.fc27_marketing_view(self.projected(period))['ads_accounts'][0]['ad_groups']
        self.assertFalse(missing['calculation_complete']);self.assertEqual(missing['status']['status'],'unknown')

    def test_total_ads_report_uses_native_unsegmented_query(self):
        reader=collector.Reader();reader.metadata['1430398974']={'id':'1430398974'};calls=[]
        def request(*args):
            calls.append(args[-1]['query']);return {'results':[{'metrics':{'conversions':'2','interactions':'40','conversionsFromInteractionsRate':'.05'}}]}
        reader.request=request
        value=reader.ads('1430398974','total','2026-10-15','2026-10-15')
        self.assertNotIn('SELECT segments.date',calls[0]);self.assertNotIn('ORDER BY segments.date',calls[0])
        self.assertEqual(value['rows'][0]['metrics']['conversionsFromInteractionsRate'],'0.05')

    def test_campaign_native_rate_across_multiple_days(self):
        period,account=self.account()
        totals=copy.deepcopy(account['calculation_campaigns'])
        report={'rows':[{'dimensions':{'customerId':r['customerId'],'campaignId':r['campaignId'],'campaignName':r['campaignName']},
                         'metrics':{'impressions':'100','clicks':'10','costMicros':str(int(float(r['metrics']['cost'])*1000000)),'conversions':'2','conversionsValue':'4','interactions':'20','conversionsFromInteractionsRate':'.1'}} for r in totals],
                'quality':{'pagination_complete':True},'collected_at':'2026-10-16T00:10:00Z'}
        value=model.make_period(period['start'],period['end'],{('ads','1430398974','campaign_total'):report})
        self.assertEqual(value['adsAccounts'][0]['calculation_campaigns'][-1]['metrics']['nativeCvr'],'.1')

    def test_failed_old_total_does_not_acquire_daily_freshness(self):
        def report(cost,at,failed=False):
            return {'rows':[{'dimensions':{'date':'2026-10-15'},'metrics':{'impressions':'100','clicks':'10','costMicros':cost,'conversions':'2','conversionsValue':'4'}}],
                    'quality':{'pagination_complete':True},'collected_at':at,'last_attempt':{'status':'failed' if failed else 'success'}}
        old=report('5000000','2026-10-15T00:00:00Z',True);daily=report('10000000','2026-10-16T00:10:00Z')
        value=model.make_period('2026-10-15','2026-10-15',{('ads','1430398974','total'):old,('ads','1430398974','daily'):daily})['adsAccounts'][0]
        self.assertEqual(value['metrics']['cost'],'10')
        self.assertEqual(value['contract']['collected_at'],daily['collected_at'])
        self.assertFalse(value['status']['retained_previous'])

    def test_exact_http_busy_is_retryable(self):
        import urllib.request
        opener=type('Busy',(),{'open':lambda *a,**k:(_ for _ in ()).throw(HTTPError('http://127.0.0.1',429,'busy',{},None))})()
        with patch.object(urllib.request,'build_opener',return_value=opener):
            self.assertEqual(marketing.MarketingReader(owner='wulv').exact({'start':'2026-10-15','end':'2026-10-15'})['status'],'busy')


class CacheTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        patcher=patch.object(range_api,'CACHE',Path(temp.name)/'ranges');patcher.start();self.addCleanup(patcher.stop)
        range_api.JOBS.clear();range_api.BUSY=None

    def test_success_cached_and_archived_without_replay(self):
        value={'schemaVersion':1,'status':'available','start':'2026-10-15','end':'2026-10-15','period':{'rule_version':contract.RULE_VERSION}}
        range_api.save_cache(value['start'],value['end'],value)
        self.assertEqual(range_api.query(value['start'],value['end'],submit=lambda *a:self.fail('replayed'))[0],200)
        value['generatedAt']='new';range_api.save_cache(value['start'],value['end'],value)
        self.assertEqual(len(list((range_api.CACHE/'versions').iterdir())),2)

    def test_failed_read_retries_after_short_backoff(self):
        results=[]
        def submit(*args):
            future=Future();future.set_result({'status':'unavailable'});results.append(future);return future
        with patch.object(range_api.time,'monotonic',return_value=100):range_api.query('2026-10-15','2026-10-15',submit)
        with patch.object(range_api.time,'monotonic',return_value=101):range_api.query('2026-10-15','2026-10-15',submit)
        with patch.object(range_api.time,'monotonic',return_value=132):range_api.query('2026-10-15','2026-10-15',submit)
        self.assertEqual(len(results),2)

    def test_cache_symlink_rejected(self):
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaises(ValueError):range_api.cached('2026-10-15','2026-10-15')

    def test_failed_refresh_retains_original_date_and_versions(self):
        value={'schemaVersion':1,'status':'available','start':'2026-10-15','end':'2026-10-15','generatedAt':'2026-10-16T00:10:00Z',
               'period':{'rule_version':contract.RULE_VERSION,'sources':{'ga4':{'metrics':{'sessions':10},'status':{'collected_at':'2026-10-16T00:10:00Z'},'contract':{'status':'success'}}}}}
        range_api.save_cache(value['start'],value['end'],value)
        retained=range_api.retained(value['start'],value['end'])
        self.assertEqual(retained['status'],'stale');self.assertEqual(retained['generatedAt'],value['generatedAt'])
        self.assertTrue(retained['period']['sources']['ga4']['status']['retained_previous'])
        self.assertEqual(len(list((range_api.CACHE/'versions').iterdir())),1)

    def test_partial_source_does_not_clear_other_successful_sources(self):
        period={'rule_version':contract.RULE_VERSION,'sources':{'ga4':{'metrics':{'sessions':10},'status':{},'contract':{'status':'success'}},'gsc':{'metrics':{'clicks':5}}}}
        value={'schemaVersion':1,'status':'available','start':'2026-10-15','end':'2026-10-15','period':period}
        range_api.save_cache(value['start'],value['end'],value)
        partial=copy.deepcopy(value);partial['status']='partial';partial['period']['sources']['ga4']['metrics']=None;partial['period']['sources']['gsc']['metrics']['clicks']=7
        result=range_api.save_cache(value['start'],value['end'],partial)
        self.assertEqual(result['period']['sources']['ga4']['metrics']['sessions'],10)
        self.assertTrue(result['period']['sources']['ga4']['status']['retained_previous'])
        self.assertEqual(result['period']['sources']['gsc']['metrics']['clicks'],7)


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.action={'id':'action-1','title':'核对落地页','metric':'同范围访问与成交','evidence_ids':['ev_'+'f'*24]}
        self.body={'kind':'hermes_action','id':'a'*32,'action':'action-1','request_id':'fixture_request_1','expected_version':0,'status':'approved','note':'负责人确认检查','review_at':''}
        self.now=datetime(2026,10,17,tzinfo=timezone.utc)

    def record(self,body=None):return action_ledger.record(self.db,'wulv',body or self.body,self.action,self.now)

    def test_idempotency_cas_and_execution_receipt(self):
        self.assertEqual(len(self.record()),1);self.assertEqual(len(self.record()),1)
        conflict=dict(self.body,note='changed')
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.record(conflict)
        executed=dict(self.body,request_id='fixture_request_2',expected_version=1,status='executed',note='人工已完成检查',review_at='2026-10-18T09:00:00+08:00')
        self.assertEqual(self.record(executed)[-1]['status'],'executed')
        self.assertEqual(self.record(executed)[-1]['version'],2)
        with self.assertRaisesRegex(ValueError,'version_conflict'):self.record(dict(executed,request_id='fixture_request_3',expected_version=1))

    def test_unexecuted_suggestion_cannot_be_ineffective(self):
        with self.assertRaisesRegex(ValueError,'transition'):self.record(dict(self.body,status='ineffective'))
        self.record()
        with self.assertRaisesRegex(ValueError,'review_required'):self.record(dict(self.body,expected_version=1,request_id='fixture_request_2',status='executed'))

    def test_action_source_cannot_silently_change_after_confirmation(self):
        self.record();self.action['title']='different action under same ID'
        with self.assertRaisesRegex(ValueError,'source_changed'):
            self.record(dict(self.body,expected_version=1,request_id='fixture_request_2',status='adjusted'))


if __name__=='__main__':unittest.main()
