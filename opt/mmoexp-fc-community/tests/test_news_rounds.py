import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

from news_feed import NewsStore, publish_pending, parse_ea_listing, enqueue_article, collect_cycle, validate_config

CHANNEL = '123456789012345678'

def row(n, source='mmoexp', date=100):
    url = ('https://www.mmoexp.com/News/fc-27-test-%s.html' if source == 'mmoexp' else
           'https://www.ea.com/games/ea-sports-fc/fc-27/news/fc27-test-%s') % n
    return dict(url=url, title='FC27 news '+str(n), summary='Summary', published_at=date,
                published_date='Nov 8, 2026', cover_url='', kind=source)

class RoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'news.db'; self.store=NewsStore(self.path)

    def test_manual_event_publishes_repeatedly_even_with_automatic_news_off(self):
        url = 'https://www.mmoexp.com/events/Sbc-Companions.html'
        for _ in range(2):
            self.store.enqueue_article(url, title='Mbappe POTM', summary='YOUR SBC STAR.')
        calls = []
        async def send(item, channel):
            calls.append(item)
            return str(len(calls))
        self.assertEqual(asyncio.run(publish_pending(self.store, CHANNEL, send, limit=100,
                                                    auto_enabled=False, ea_enabled=False)), 2)
        self.assertEqual([item['url'] for item in calls], [url, url])
        self.assertTrue(all(item['delivery_mode']=='manual' for item in calls))
        self.assertTrue(all(item['status']=='published' for item in self.store.items()))

    def test_event_urls_are_manual_only_and_keep_official_origin_validation(self):
        url = 'https://www.mmoexp.com/events/Sbc-Companions.html'
        with self.assertRaises(ValueError):
            self.store.ingest([dict(row(1), url=url)])
        for invalid in ('https://evil.example/events/Sbc-Companions.html',
                        'https://www.mmoexp.com.evil.example/events/Sbc-Companions.html',
                        'http://www.mmoexp.com/events/Sbc-Companions.html',
                        'https://www.mmoexp.com/events/Sbc-Companions.html?next=https://evil.example',
                        'https://www.mmoexp.com/events/Sbc-Companions.html#fragment',
                        'https://www.mmoexp.com/events/%2e%2e/admin.html',
                        'https://www.mmoexp.com/admin/user/member'):
            with self.subTest(url=invalid), self.assertRaises(ValueError):
                self.store.enqueue_article(invalid)

    def test_ea_switch_is_optional_boolean_and_old_config_keeps_behavior(self):
        config = dict(guild_id=1, channel_id=CHANNEL, enabled=True, poll_seconds=21600)
        self.assertEqual(validate_config(config, 1), config)
        self.assertFalse(validate_config(dict(config, ea_enabled=False), 1)['ea_enabled'])
        for invalid in (0, 1, 'false', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_config(dict(config, ea_enabled=invalid), 1)

    def test_ea_off_skips_collection_without_disabling_mmoexp(self):
        def collect(source, *args):
            return [row(1, source)], {'collector': '187'}
        with patch('collector_router.collect', side_effect=collect) as mocked:
            result = collect_cycle(self.store, dict(poll_seconds=21600, ea_enabled=False), now=100)
        self.assertEqual([call.args[0] for call in mocked.call_args_list], ['mmoexp'])
        self.assertEqual(set(result), {'mmoexp'})
        self.assertEqual([item['kind'] for item in self.store.items()], ['mmoexp'])

    def test_ea_off_holds_queued_auto_but_manual_and_mmoexp_continue(self):
        b = self.store.begin_cycle(21600, now=100)
        self.store.ingest([row(1, 'ea')], 100, batch_id=b)
        self.store.ingest([row(1)], 100, batch_id=b)
        self.store.finish_cycle(b, {}, 100)
        self.store.enqueue_article(row(2, 'ea')['url'], title='Manual EA')
        calls = []
        async def send(item, channel):
            calls.append(item)
            return str(len(calls))
        self.assertEqual(asyncio.run(publish_pending(self.store, CHANNEL, send, limit=100,
                                                    ea_enabled=False)), 2)
        self.assertEqual([(v['kind'], v['delivery_mode']) for v in calls],
                         [('ea', 'manual'), ('mmoexp', 'auto')])
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT claimed FROM news_batches WHERE id=?", (b,)).fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT status FROM news_items WHERE kind='ea' AND delivery_mode='auto'").fetchone()[0], 'pending')
        self.assertEqual(asyncio.run(publish_pending(NewsStore(self.path), CHANNEL, send,
                                                    ea_enabled=True)), 1)
        self.assertEqual(calls[-1]['kind'], 'ea')

    def test_six_budget_priority_restart_and_next_round(self):
        b=self.store.begin_cycle(21600, now=100)
        self.store.ingest([row('seed')],100,batch_id=b)
        self.store.ingest([row('seed','ea')],100,batch_id=b)
        self.store.finish_cycle(b, {}, now=100)
        calls=[]
        async def send(item, channel): calls.append(item); return str(len(calls))
        asyncio.run(publish_pending(self.store,CHANNEL,send,limit=100))
        b=self.store.begin_cycle(21600,now=21700)
        self.store.ingest([row(i,date=100+i) for i in range(10)],21700,batch_id=b)
        self.store.ingest([row(i,'ea',100+i) for i in range(4)],21700,batch_id=b)
        self.store.finish_cycle(b, {}, now=21700)
        calls.clear()
        asyncio.run(publish_pending(self.store,CHANNEL,send,limit=100))
        self.assertEqual(len(calls),6)
        self.assertEqual([v['kind'] for v in calls],['ea']*4+['mmoexp']*2)
        self.assertEqual([v['published_at'] for v in calls[:4]],[103,102,101,100])
        restarted=NewsStore(self.path)
        self.assertIsNone(restarted.begin_cycle(21600,now=21701))
        asyncio.run(publish_pending(restarted,CHANNEL,send,limit=100))
        self.assertEqual(len(calls),6)
        b=restarted.begin_cycle(21600,now=43300); restarted.finish_cycle(b,{},now=43300)
        asyncio.run(publish_pending(restarted,CHANNEL,send,limit=100))
        self.assertEqual(len(calls),12)

    def test_manual_repeat_is_unlimited_even_auto_disabled(self):
        for _ in range(8): enqueue_article(self.path,row(1)['url'],title='Manual')
        for _ in range(8): self.store.enqueue_x('https://x.com/test/status/123')
        calls=[]
        async def send(item, channel): calls.append(item); return str(len(calls))
        asyncio.run(publish_pending(self.store,CHANNEL,send,limit=100,auto_enabled=False))
        self.assertEqual(len(calls),16)
        self.assertEqual(len({v['external_id'] for v in calls}),16)

    def test_ea_season_filter_and_featured(self):
        article=dict(title='FC 27 News',summary='Example',slug='fc27-example',publishingDate='2026-11-06T18:00:00.000Z',linkedTo=[{'slug':'fc-27'}])
        old=dict(article,title='EA SPORTS FC 26 Apple TV',slug='fc26-apple')
        html='<script id="__NEXT_DATA__" type="application/json">'+json.dumps({'props':{'pageProps':{'initialNewsData':{'featured':article,'items':[article,old]}}}})+'</script>'
        rows=parse_ea_listing(html)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['kind'],'ea')

    def test_auto_dedup_after_manual_and_concurrent_claim(self):
        self.store.ingest([row(1)])
        self.store.enqueue_article(row(1)['url'],title='Manual')
        manual=self.store.claim(CHANNEL)
        self.assertEqual(manual['delivery_mode'],'manual')
        self.store.complete(manual['id'],'published','111')
        self.assertIsNone(self.store.claim(CHANNEL))
        self.assertEqual(self.store.items()[-1]['status'],'duplicate')
        for _ in range(10): self.store.enqueue_article(row(1)['url'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims=list(pool.map(lambda _: self.store.claim(CHANNEL), range(12)))
        ids=[v['id'] for v in claims if v]
        self.assertEqual(len(ids),10)
        self.assertEqual(len(set(ids)),10)

    def test_collection_failure_records_state_and_restart_does_not_retry_round(self):
        config={'poll_seconds':21600,'collector':'auto'}
        from collector_router import CollectionError
        with patch('collector_router.collect',side_effect=CollectionError([{'collector':'187','ok':False,'error':'timeout'}])) as collect:
            result=collect_cycle(self.store,config,now=100)
            self.assertTrue(all(not v['ok'] for v in result.values()))
            self.assertIsNone(collect_cycle(NewsStore(self.path),config,now=101))
            self.assertEqual(collect.call_count,2)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT value FROM news_meta WHERE key='last_poll_error'").fetchone()[0],'all_sources_failed')

    def test_no_auto_send_until_both_sources_ingested_and_repeated_ingest_is_unique(self):
        b=self.store.begin_cycle(21600,now=100)
        self.store.ingest([row(1)],100,batch_id=b)
        self.assertIsNone(self.store.claim(CHANNEL))
        self.store.ingest([row(1)],100,batch_id=b)
        self.store.ingest([row(2,'ea')],100,batch_id=b)
        self.store.finish_cycle(b,{},100)
        self.assertEqual(self.store.claim(CHANNEL)['kind'],'ea')
        self.assertEqual(self.store.claim(CHANNEL)['kind'],'mmoexp')
        self.assertIsNone(self.store.claim(CHANNEL))
        self.assertEqual(len(self.store.items()),2)

    def test_concurrent_auto_claims_share_one_six_attempt_budget(self):
        b=self.store.begin_cycle(21600,now=100)
        self.store.ingest([row('seed')],100,batch_id=b)
        self.store.ingest([row(i,date=101) for i in range(12)],101,batch_id=b)
        self.store.finish_cycle(b,{},101)
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed=list(pool.map(lambda _: self.store.claim(CHANNEL),range(20)))
        ids=[v['id'] for v in claimed if v]
        self.assertEqual(len(ids),6)
        self.assertEqual(len(set(ids)),6)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT claimed FROM news_batches WHERE id=?',(b,)).fetchone()[0],6)

if __name__=='__main__': unittest.main()
