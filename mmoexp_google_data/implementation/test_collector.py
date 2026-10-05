import copy,datetime as dt,json,sqlite3,unittest
from pathlib import Path
import collector
ROOT=Path(__file__).resolve().parent.parent

class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((ROOT/'preparation/config.example.json').read_text(encoding='utf-8'))
        self.db=sqlite3.connect(':memory:');self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript((ROOT/'preparation/schema.sql').read_text(encoding='utf-8'))
        self.date='2026-09-29'
    def tearDown(self):self.db.close()
    def fixture(self,source):return json.loads((Path(__file__).parent/'fixtures'/f'{source}.json').read_text(encoding='utf-8'))
    def test_known_ids_and_missing_advertiser(self):
        p=collector.plans(self.config,self.date)
        self.assertEqual([v['source'] for v in p],['ga4','gsc'])
        self.assertIn('541418940',p[0]['url']);self.assertIn('sc-domain%3Ammoexp.com',p[1]['url'])
    def test_manager_is_not_advertiser(self):
        self.config['ads']['customer_ids']=['6039826478']
        with self.assertRaisesRegex(ValueError,'ADVERTISER_ID_REQUIRED'):collector.plans(self.config,self.date)
    def test_decimal_ads_and_read_request(self):
        self.config['ads']['customer_ids']=['1234567890'] # test-only advertiser, never contacted
        plan=collector.plans(self.config,self.date)[2]
        self.assertIn('SELECT ',plan['body']['query']);self.assertNotIn('developer-token',plan.get('headers',{}))
        data=collector.normalise(plan,self.fixture('ads'),self.date,self.config)
        self.assertEqual(dict(data[0])['conversions'],'2.5')
        self.assertEqual(dict(data[0])['costMicros'],'30000000')
    def test_pagination_error_retains_valid_slice(self):
        plan=collector.plans(self.config,self.date)[0];payload=self.fixture('ga4')
        collector.ingest(self.db,plan,self.date,collector.normalise(plan,payload,self.date,self.config),is_mock=True)
        old=self.db.execute('SELECT metric_name,metric_value FROM metric_rows ORDER BY metric_name').fetchall()
        payload['rowCount']=2
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_GA4_PAGINATION'):collector.normalise(plan,payload,self.date,self.config)
        collector.error_run(self.db,plan,self.date,'INCOMPLETE_GA4_PAGINATION',True)
        self.assertEqual(old,self.db.execute('SELECT metric_name,metric_value FROM metric_rows ORDER BY metric_name').fetchall())
        state=collector.snapshot(self.db,True)
        self.assertEqual(state['lastAttempts']['ga4:541418940']['status'],'failed')
    def test_transactional_replay_replaces_entire_slice(self):
        plan=collector.plans(self.config,self.date)[0]
        normal=collector.normalise(plan,self.fixture('ga4'),self.date,self.config)
        collector.ingest(self.db,plan,self.date,normal,is_mock=True)
        collector.ingest(self.db,plan,self.date,normal,is_mock=True)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM metric_rows').fetchone()[0],4)
        revised=([('sessions','101')],normal[1],normal[2],normal[3])
        collector.ingest(self.db,plan,self.date,revised,is_mock=True)
        self.assertEqual(self.db.execute('SELECT metric_name,metric_value FROM metric_rows').fetchall(),[('sessions','101')])
    def test_empty_response_retains_previous_data_without_completeness_claim(self):
        plan=collector.plans(self.config,self.date)[1]
        normalized=collector.normalise(plan,self.fixture('gsc'),self.date,self.config)
        collector.ingest(self.db,plan,self.date,normalized,is_mock=True)
        collector.ingest(self.db,plan,self.date,([],normalized[1],normalized[2],normalized[3]),is_mock=True)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM metric_rows').fetchone()[0],4)
        latest=collector.snapshot(self.db,True)['lastAttempts']['gsc:sc-domain:mmoexp.com']
        self.assertEqual(latest['status'],'empty');self.assertIsNone(latest['verifiedThrough'])
    def test_previous_days_use_source_timezone(self):
        import server_run_daily
        now=dt.datetime(2026,9,30,2,0,tzinfo=dt.timezone.utc)
        self.assertEqual(server_run_daily.previous_source_day(now,'Asia/Shanghai'),'2026-09-29')
        self.assertEqual(server_run_daily.previous_source_day(now,'America/Los_Angeles'),'2026-09-28')

if __name__=='__main__':unittest.main()
