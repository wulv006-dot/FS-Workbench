import datetime as dt, importlib.util, json, sqlite3, unittest
from pathlib import Path

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
c=module('collect_details');m=module('detail_model')

class DetailsTests(unittest.TestCase):
    def db(self):
        d=sqlite3.connect(':memory:');d.executescript(c.SCHEMA);self.addCleanup(d.close);return d
    def report(self,rows):return {'rows':rows,'quality':{},'timezone':'Asia/Shanghai','currency':'USD'}
    def test_idempotency_and_failed_empty_preserve(self):
        d=self.db();args=(d,'ga4','541418940','total','2026-09-21','2026-09-27');r=self.report([{'dimensions':{},'metrics':{'sessions':'12'}}])
        c.save(*args,r);c.save(*args,r);self.assertEqual(d.execute('SELECT COUNT(*) FROM detail_reports').fetchone()[0],1)
        c.save(*args,self.report([]));c.save(*args,error='HTTP_403');self.assertEqual(json.loads(d.execute('SELECT payload_json FROM detail_reports').fetchone()[0])['rows'][0]['metrics']['sessions'],'12')
    def test_nonfinite_rejected(self):
        for value in ['NaN','Infinity','1e100']:
            with self.assertRaises(ValueError):c.number(value)
    def test_week_users_not_sum_daily(self):
        d=self.db();dates=[(dt.date(2026,9,21)+dt.timedelta(days=i)).isoformat() for i in range(7)]
        c.save(d,'ga4','541418940','total',dates[0],dates[-1],self.report([{'dimensions':{},'metrics':{'activeUsers':'100','sessions':'200'}}]))
        c.save(d,'ga4','541418940','daily',dates[0],dates[-1],self.report([{'dimensions':{'date':v},'metrics':{'activeUsers':'30','sessions':'40'}} for v in dates]))
        v=m.build(d)['periods'][0]['sources']['ga4'];self.assertEqual(v['metrics']['activeUsers'],'100');self.assertEqual(v['coverage']['returned_days'],7)
    def test_partial_week_no_comparison(self):
        self.assertEqual(m.metric_change({'sessions':'20'},{'sessions':'10'},False),{})
        self.assertEqual(m.metric_change({'ctr':'.2'},{'ctr':'.1'},True)['ctr']['value'],'10.0')
    def test_fractional_conversions_and_zero_denominator(self):
        r=m.ads_sum([{'metrics':{'impressions':'10','clicks':'0','costMicros':'1000000','conversions':'0.25','conversionsValue':'2'}}]);self.assertEqual(r['conversions'],'0.25');self.assertIsNone(r['cpc']);self.assertEqual(r['cpa'],'4');self.assertEqual(r['platformRoas'],'2')
    def test_weighted_position_and_ctr(self):
        r=m.gsc_sum([{'metrics':{'clicks':'10','impressions':'100','position':'2'}},{'metrics':{'clicks':'10','impressions':'900','position':'10'}}]);self.assertEqual(r['position'],'9.2');self.assertEqual(r['ctr'],'0.02')
    def test_classification_priority_unmatched(self):
        self.assertEqual(m.query_category('mmoexp gold guide'),'brand');self.assertEqual(m.query_category('buy osrs gold'),'transaction');self.assertEqual(m.query_category('how to finish a quest'),'content');self.assertEqual(m.query_category('unmapped phrase'),'other')
    def test_duplicate_dimensions_rejected(self):
        d=self.db();r={'dimensions':{'date':'2026-09-21'},'metrics':{'sessions':'1'}};c.save(d,'ga4','541418940','daily','2026-09-21','2026-09-27',self.report([r,r]))
        with self.assertRaises(ValueError):m.build(d)
    def test_unselected_account_rejected(self):
        d=self.db();c.save(d,'ads','999','daily','2026-09-21','2026-09-27',self.report([{'dimensions':{},'metrics':{'clicks':'1'}}]))
        with self.assertRaises(ValueError):m.build(d)
    def test_rsorder_customer_ids_distinct(self):
        d=self.db()
        for customer in ['8154986819','3552474396']:
            c.save(d,'ads',customer,'daily','2026-09-21','2026-09-27',self.report([{'dimensions':{'customerId':customer,'date':'2026-09-21'},'metrics':{'impressions':'20','clicks':'2','costMicros':'1000000','conversions':'0.5','conversionsValue':'3'}}]))
        accounts=[a for a in m.build(d)['periods'][0]['adsAccounts'] if a['brand']=='rsorder'];self.assertEqual(len(accounts),2);self.assertEqual({a['customerId'] for a in accounts},{'8154986819','3552474396'})
    def test_ga_total_omitted_dimension_values(self):
        reader=c.Reader();reader.ga_compatibility={'total':True}
        reader.request=lambda *args,**kwargs:{'metadata':{'timeZone':'Asia/Shanghai','currencyCode':'USD'},'metricHeaders':[{'name':n} for n in c.GA_METRICS],'rows':[{'metricValues':[{'value':'1'} for n in c.GA_METRICS]}],'rowCount':1}
        value=reader.ga('total','2026-09-21','2026-09-27');self.assertEqual(value['rows'][0]['dimensions'],{});self.assertEqual(len(value['rows'][0]['metrics']),10)
    def test_missing_country_queries_not_zero(self):
        value=m.make_period('2026-09-21','2026-09-27',{})['sources']['gsc']['markets'][2]
        self.assertFalse(value['available']);self.assertIsNone(value['country_total']);self.assertTrue(all(v['metrics'] is None for v in value['categories']))
    def test_ads_campaign_pagination_and_fractional_values(self):
        reader=c.Reader();reader.metadata['8154986819']={'id':'8154986819'};calls=[]
        def query(*args):
            calls.append(args[-1].copy());return {'results':[{'segments':{'date':'2026-09-21'},'campaign':{'id':str(len(calls)),'name':'sample'},'metrics':{'conversions':'0.25'}}],**({'nextPageToken':'opaque-paging-fixture'} if len(calls)==1 else {})}
        reader.request=query;result=reader.ads('8154986819','campaign','2026-09-21','2026-09-27')
        self.assertEqual(len(result['rows']),2);self.assertEqual(calls[1]['pageToken'],'opaque-paging-fixture');self.assertEqual(result['rows'][0]['metrics']['conversions'],'0.25')
    def test_ads_five_returned_days_not_collection_gap(self):
        report={'start_date':'2026-09-21','end_date':'2026-09-27','quality':{'pagination_complete':True},'rows':[{'dimensions':{'date':'2026-09-'+str(d)},'metrics':{}} for d in range(21,26)]}
        value=m.ads_coverage(report,'2026-09-21','2026-09-27');self.assertTrue(value['query_range_complete']);self.assertEqual(value['returned_days'],5);self.assertEqual(value['missing_dates'],[]);self.assertEqual(value['no_metric_row_dates'],['2026-09-26','2026-09-27']);self.assertFalse(value['zero_rows_materialized']);self.assertEqual(len(report['rows']),5)
if __name__=='__main__':unittest.main()
