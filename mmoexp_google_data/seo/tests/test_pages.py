import datetime as dt
import tempfile
import unittest
from mmoexp_google_data.seo import pages, daily, store, snapshot
from test_daily_snapshot import NIGHT, Source


class Pages(unittest.TestCase):
    def test_only_approved_main_site_read_only_urls(self):
        self.assertEqual(pages.approved_url('FC27','https://www.mmoexp.com/Fc-27/Coins.html'),'https://www.mmoexp.com/Fc-27/Coins.html')
        for url in ('https://www.mmoexp.com/Fc-27/checkout','https://other.example/Fc-27/Coins.html','http://www.mmoexp.com/Fc-27/Coins.html','https://www.mmoexp.com/Fc-27/Coins.html?token=private','https://www.mmoexp.com/Wow/Gold.html'):
            with self.assertRaises(ValueError):pages.approved_url('FC27',url)

    def test_extracts_head_facts_without_retaining_html(self):
        parser=pages.HeadFacts();parser.feed('<html><head><title>Coins</title><meta name="robots" content="noindex"><link rel="canonical" href="https://www.mmoexp.com/Fc-27/Coins.html"></head><body><h1>FC27 Coins</h1></body></html>')
        self.assertEqual(parser.facts()['title'],'Coins')
        self.assertEqual(parser.facts()['h1'],'FC27 Coins')
        self.assertEqual(parser.facts()['robots'],'noindex')

    def test_today_observation_waits_until_next_night(self):
        clock=[NIGHT]
        def fetch(url,**kw):return dict(status_code=200,title='fixture page',content_hash='fixture')
        source=pages.PageSource({'FC27':['https://www.mmoexp.com/Fc-27/Coins.html']},fetch=fetch,clock=lambda:clock[0])
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            first=daily.run_daily(core,[Source(),source],clock=lambda:clock[0])
            self.assertEqual(snapshot.read(core.root,first['snapshot_id'],'pages','FC27')['rows'],[])
            clock[0]+=dt.timedelta(days=1)
            second=daily.run_daily(core,[Source(),source],clock=lambda:clock[0])
            result=snapshot.read(core.root,second['snapshot_id'],'pages','FC27')['rows']
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['source_date'],'2026-11-05')

    def test_daytime_cannot_fetch(self):
        def fetch(*a,**kw):raise AssertionError('daytime network')
        source=pages.PageSource({'FC27':['https://www.mmoexp.com/Fc-27/Coins.html']},fetch=fetch,clock=lambda:NIGHT+dt.timedelta(hours=8))
        with self.assertRaises(ValueError):list(source.pages('FC27','2026-11-05'))


if __name__=='__main__':unittest.main()
