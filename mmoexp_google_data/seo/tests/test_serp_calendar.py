import datetime as dt
import json
import tempfile
import unittest
from unittest.mock import Mock

from mmoexp_google_data.seo import daily, snapshot, store
from test_daily_snapshot import NIGHT, Source


class SerpCalendar(unittest.TestCase):
    def condition(self):
        return dict(keyword='fc27 coins',country='US',language='en',device='desktop',depth=10)

    def test_organic_positions_exclude_ads_and_unrelated_game_paths(self):
        from mmoexp_google_data.seo.serp import parse_results
        response=dict(organic=[dict(link='https://other.example/a',global_rank=2),dict(link='https://www.mmoexp.com/Fc-27/Coins.html',global_rank=4)],top_ads=[dict(link='https://www.iggm.com/',global_rank=1)])
        rows=parse_results(response,self.condition(),{'MMOEXP':['https://www.mmoexp.com/Fc-27/'],'IGGM':['https://www.iggm.com/']})
        self.assertEqual(rows[0]['rank'],2)
        self.assertEqual(rows[1]['status'],'insufficient_depth')
        self.assertIsNone(rows[1]['rank'])
        self.assertEqual(rows[1]['effective_depth'],2)
        rows=parse_results(dict(organic=[dict(link='https://other.example/'+str(n)) for n in range(10)]),self.condition(),{'MMOEXP':['https://www.mmoexp.com/Fc-27/']})
        self.assertEqual(rows[0]['status'],'not_found')
        self.assertIsNone(rows[0]['rank'])

    def test_mismatched_query_and_invalid_organic_fail(self):
        from mmoexp_google_data.seo.serp import parse_results
        for response in [dict(organic=[],general=dict(query='different')),dict(organic=[dict(link='javascript:alert(1)')]),dict(organic=[],general=dict(country_code='DE'))]:
            with self.assertRaises(ValueError):parse_results(response,self.condition(),{'MMOEXP':['https://www.mmoexp.com/Fc-27/']})

    def test_serp_uses_one_request_for_all_brands_and_waits_until_next_day(self):
        from mmoexp_google_data.seo.serp import SerpSource
        now=[NIGHT]
        request=Mock(return_value=dict(organic=[dict(link='https://www.mmoexp.com/Fc-27/Coins.html')]))
        config=dict(enabled=True,projects={'FC27':dict(conditions=[self.condition()],brands={'MMOEXP':['https://www.mmoexp.com/Fc-27/'],'IGGM':['https://www.iggm.com/']})})
        source=SerpSource(config,request,clock=lambda:now[0])
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            first=daily.run_daily(core,[Source(),source],clock=lambda:now[0])
            self.assertEqual(snapshot.read(core.root,first['snapshot_id'],'markets','FC27')['rows'],[])
            self.assertEqual(request.call_count,1)
            now[0]+=dt.timedelta(days=1)
            second=daily.run_daily(core,[Source(),source],clock=lambda:now[0])
            rows=snapshot.read(core.root,second['snapshot_id'],'markets','FC27')['rows']
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['source_date'],'2026-11-05')
        source=SerpSource(config,request,clock=lambda:NIGHT+dt.timedelta(hours=8))
        with self.assertRaises(ValueError):list(source.pages('FC27','2026-11-05'))
        self.assertEqual(request.call_count,2)

    def test_unknown_paid_submission_is_not_replayed(self):
        from mmoexp_google_data.seo.serp import BrightDataTransport
        config=dict(zone='existing-zone',api_key_env='EXISTING_KEY',authorization=dict(reference='test-grant',valid_until='2026-11-06',request_allowance=20))
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            post=Mock(side_effect=TimeoutError('secret must not leak'))
            transport=BrightDataTransport(core,config,dict(connect_seconds=5,idle_seconds=10,response_emergency_bytes=100000),key_loader=lambda name:'secret',post=post,clock=lambda:NIGHT)
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'SUBMISSION_UNKNOWN'):transport(self.condition(),'FC27','2026-11-05')
            self.assertEqual(post.call_count,1)
            with core.db() as db:self.assertEqual(db.execute('SELECT state FROM provider_requests').fetchone()[0],'unknown')

    def test_calendar_preserves_upstream_date_and_never_infers_event_date(self):
        from mmoexp_google_data.seo.calendar import CalendarSource
        doc=dict(schema_version=1,status='succeeded',version='existing',collected_at='2026-10-30T16:15:00+00:00',stale_after='2026-11-07T07:00:00+08:00',events=[dict(game_key='diablo4',event_id='real-id',title='Official notice',source_url='https://store.steampowered.com/news/app/2344520/view/1',published_at='2026-09-15T22:00:09+00:00',event_date=None,evidence='Season is live')])
        source=CalendarSource(dict(bindings={'D4':dict(game_key='diablo4',hosts=['store.steampowered.com'])}),read=lambda:doc,clock=lambda:NIGHT)
        row=list(source.pages('D4','2026-11-05'))[0]['rows'][0]
        self.assertIsNone(row['event_date'])
        self.assertEqual(row['upstream_observed_at'],doc['collected_at'])
        self.assertEqual(row['observed_at'],NIGHT.isoformat())
        self.assertEqual(list(source.pages('WOW_FOREVER','2026-11-05'))[0]['status'],'not_configured')
        doc['events'][0]['game_key']='wow-classic-20'
        self.assertEqual(list(source.pages('D4','2026-11-05'))[0]['rows'],[])

    def test_user_calendar_retains_all_dates_without_claiming_official_verification(self):
        from mmoexp_google_data.seo.calendar import CalendarSource
        source=CalendarSource(dict(include_fc27_user_plan=True),read=Mock(side_effect=AssertionError('manual plan must not require collector')),clock=lambda:NIGHT)
        rows=list(source.pages('FC27','2026-11-05'))[0]['rows']
        self.assertEqual(len(rows),18)
        self.assertTrue(all(row['verification']=='user_provided' and row['upstream_observed_at'] is None for row in rows))
        self.assertEqual(rows[0]['event_date'],'2026-09-25')
        self.assertEqual(rows[0]['event_end_date'],'2026-10-09')

    def test_grant_required_completed_response_reused_and_allowance_respected(self):
        from mmoexp_google_data.seo.serp import BrightDataTransport
        limits=dict(connect_seconds=5,idle_seconds=10,response_emergency_bytes=100000)
        config=dict(zone='existing',api_key_env='KEY',authorization=dict(reference='grant',valid_until='2026-11-30',request_allowance=1))
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp);post=Mock(return_value=(dict(organic=[]),'provider-id'))
            bad=BrightDataTransport(core,dict(config,authorization={}),limits,key_loader=lambda _: 'secret',post=post,clock=lambda:NIGHT)
            with self.assertRaisesRegex(ValueError,'AUTHORIZATION_REQUIRED'):bad(self.condition(),'FC27','2026-11-05')
            self.assertEqual(post.call_count,0)
            transport=BrightDataTransport(core,config,limits,key_loader=lambda _:'secret',post=post,clock=lambda:NIGHT)
            self.assertEqual(transport(self.condition(),'FC27','2026-11-05'),transport(self.condition(),'D4','2026-11-05'))
            self.assertEqual(post.call_count,1)
            with self.assertRaisesRegex(ValueError,'ALLOWANCE_EXHAUSTED'):transport(dict(self.condition(),keyword='new term'),'FC27','2026-11-05')
            self.assertEqual(post.call_count,1)

    def test_monthly_free_grant_renews_without_replaying_previous_day(self):
        from mmoexp_google_data.seo.serp import BrightDataTransport
        now=[NIGHT];post=Mock(return_value=(dict(organic=[]),None))
        config=dict(zone='existing',api_key_env='KEY',authorization=dict(reference='free-only',renewal='monthly_free_credits',request_allowance=1))
        with tempfile.TemporaryDirectory() as tmp:
            transport=BrightDataTransport(store.Store(tmp),config,dict(connect_seconds=5,idle_seconds=10,response_emergency_bytes=100000),key_loader=lambda _:'secret',post=post,clock=lambda:now[0])
            transport(self.condition(),'FC27','2026-11-05')
            now[0]=dt.datetime(2026,11,30,19,20,tzinfo=dt.timezone.utc)
            transport(self.condition(),'FC27','2026-12-01')
            self.assertEqual(post.call_count,2)

    def test_invalid_optional_source_never_blocks_base(self):
        from mmoexp_google_data.seo.serp import SerpSource
        request=Mock(side_effect=AssertionError('must not call'))
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            result=daily.run_daily(core,[Source(),SerpSource(True,request,clock=lambda:NIGHT)],clock=lambda:NIGHT)
            self.assertEqual(result['status'],'published')
            self.assertEqual(request.call_count,0)

    def test_cleanup_preserves_active_grant_usage(self):
        from mmoexp_google_data.seo.retention import cleanup_owned_data
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            with core.db() as db:
                for key,end in [('active','2026-11-30'),('expired','2026-09-30')]:
                    db.execute('INSERT INTO provider_requests VALUES (?,?,?,?,?,?,?,?,?)',(key,key,'2026-09-01','completed',None,'{}',None,end,'2026-09-01T00:00:00Z'))
            cleanup_owned_data(core,dt.date(2026,11,5))
            with core.db() as db:self.assertEqual([r[0] for r in db.execute('SELECT request_key FROM provider_requests')],['active'])

    def test_partial_observation_is_kept_for_next_day_when_resource_guard_stops(self):
        class Points:
            name='serp';timezone='Asia/Shanghai';is_observation=True
            def __init__(self):self.calls=0
            def pages(self,scope,day,cursor=0):
                for i in range(cursor,3):
                    self.calls+=1
                    yield dict(rows=[dict(key=str(i),rank=1,status='found',observed_at=NIGHT.isoformat())],next_cursor=i+1 if i<2 else None,source_timezone=self.timezone,status='available',quality=dict(sample_kind='point_observation'))
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            core.ingest_page('gsc','FC27','2026-11-04',dict(rows=[dict(key='base',metrics=dict(clicks='1',impressions='2',position='1'))],next_cursor=None,source_timezone='America/Los_Angeles',status='available',quality={}),NIGHT.isoformat())
            source=Points();checks=[0]
            def admit():checks[0]+=1;return checks[0]<=2
            self.assertEqual(daily.run_daily(core,[source],clock=lambda:NIGHT,admit=admit)['status'],'published')
            self.assertEqual(source.calls,1)
            result=daily.run_daily(core,[],clock=lambda:NIGHT+dt.timedelta(days=1))
            self.assertEqual(len(snapshot.read(core.root,result['snapshot_id'],'markets','FC27')['rows']),1)

    def test_official_reader_failure_isolated_and_announcement_date_not_event_date(self):
        from mmoexp_google_data.seo.calendar import CalendarSource
        doc=dict(document_id='official-id',game_keys=['diablo4'],title='Official update',text='Official source text',source_url='https://store.steampowered.com/news/app/2344520/view/2',published_at='2026-11-04T00:00:00Z')
        source=CalendarSource(dict(bindings={'D4':dict(game_key='diablo4',hosts=['store.steampowered.com'],official_feeds=['steam-2344520'])}),read=Mock(side_effect=OSError()),official=Mock(return_value=[doc]),clock=lambda:NIGHT)
        page=list(source.pages('D4','2026-11-05'))[0]
        self.assertEqual(page['rows'][0]['verification'],'official_source')
        self.assertIsNone(page['rows'][0]['event_date'])
        self.assertEqual(page['status'],'partial')


if __name__=='__main__':unittest.main()
