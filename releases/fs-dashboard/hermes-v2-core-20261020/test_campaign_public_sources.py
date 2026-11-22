from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import uuid
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'source'))

from test_campaign_recommendations import TaskStore
from campaign_public_sources import collect, PublicSources, validate_request


EA = 'https://www.ea.com/games/ea-sports-fc/fc-27/news/fc-27-bf-thunderstruck'
BIN = 'https://www.futbin.com/27/player/123/card'
STORE = 'https://www.mmoexp.com/events/Player-Trio.html'
AT = '2026-11-22T10:30:00+00:00'


class PublicSourceTests(unittest.TestCase):
    def test_outside_source_scheme_or_version_fails_before_fetch(self):
        for url in ('http://www.futbin.com/27/player/123/card',
                    'https://www.futbin.com/26/player/123/card',
                    'https://www.fut.gg@127.0.0.1/players/123/27-1/',
                    'https://www.ea.com:444/games/ea-sports-fc/fc-27/news/test',
                    'https://www.futbin.com/27/player/123/card?token=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_request({'purpose':'activity','urls':[url]})
        with self.assertRaises(ValueError):
            validate_request({'purpose':'pricing_display','urls':[EA]})

    def test_batch_receipt_contains_original_url_time_and_field_provenance(self):
        class Page:
            def __init__(self, url):
                self.body=b'fixture'
                self.url=url
                self.status=403 if url==BIN else 200
            def css(self, query):
                values={'h1 ::text':['Thunderstruck'], 'time::attr(datetime)':['2026-11-20']}
                return SimpleNamespace(getall=lambda:values.get(query,[]))
        result=collect({'purpose':'activity','urls':[EA,BIN]}, lambda url:Page(url), lambda:AT)
        news, blocked=result['sources']
        self.assertEqual(result['coverage'],'partial')
        self.assertEqual(news['url'],EA)
        self.assertEqual(news['fetched_at'],AT)
        self.assertEqual(news['fields']['title'],{'value':'Thunderstruck','selector':'h1 ::text'})
        self.assertEqual(blocked['status'],'source_blocked')
        self.assertEqual(blocked['http_status'],403)
        self.assertEqual(blocked['fields'],{})

    def test_public_price_corroboration_ignores_old_html_and_unavailable_quotes(self):
        import json
        url='https://www.mmoexp.com/events/api/campaign/config'
        product={'key':'live-ps','title':'Bruno Fernandes 90 Thunderstruck','platform':{'code':'ps'},'product_ref':{'model_id':'123'}}
        config={'release_id':'campaign-preview-54','pages':[{'page_id':'fc27-trio','active':True,'title':'Player Trio','product_keys':['live-ps']}],
                'products':[product],'fc_layout':{'trio':['model-266-1327-123']},
                'seasonal_model_contracts':{'123':{'verified':True,'combinations':[{'product_key':'live-ps','price':{
                   'source':'admin_current','currency':'USD','minor_unit_scale':2,'base_minor':4984,'expires_at':'2026-11-22T10:35:00+00:00'}}]}}}
        def capture(target):
            body=json.dumps(config).encode() if target==url else b'<h1>Old mock listing $999</h1>'
            return SimpleNamespace(url=target,status=200,body=body,css=lambda _:SimpleNamespace(getall=lambda:[]))
        result=collect({'purpose':'pricing_display','urls':[STORE]},capture,lambda:AT)
        fields=result['sources'][0]['fields']
        self.assertEqual(fields['publication']['value'],'campaign-preview-54')
        facts=fields['public_reference_prices']
        self.assertEqual(facts['source_url'],url)
        self.assertEqual(facts['value'][0]['base_minor'],4984)
        self.assertNotIn('display_price',fields)
        stale=collect({'purpose':'pricing_display','urls':[STORE]},capture,lambda:'2026-11-22T10:36:00+00:00')
        self.assertEqual(stale['coverage'],'partial')
        self.assertNotIn('public_reference_prices',stale['sources'][0]['fields'])

    def test_original_request_receipt_is_owner_scoped_and_does_not_fetch_twice(self):
        with TemporaryDirectory() as folder:
            tasks=TaskStore(Path(folder)/'tasks.sqlite3')
            calls=[]
            def worker(data):
                calls.append(data)
                return {'purpose':data['purpose'],'coverage':'unavailable','sources':[
                    {'url':STORE,'status':'source_blocked','http_status':403,'attempted_at':AT,'fields':{}}]}
            service=PublicSources(tasks,worker=worker,clock=lambda:datetime.fromisoformat(AT))
            request={'purpose':'pricing_display','urls':[STORE]}
            key=str(uuid.uuid4())
            result=service.submit(key,'alice',request)
            self.assertEqual(service.submit(key,'alice',request),result)
            self.assertEqual(service.lookup(key,'alice'),result)
            self.assertIsNone(service.lookup(key,'bob'))
            self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError):
                service.submit(key,'alice',{'purpose':'activity','urls':[EA]})
