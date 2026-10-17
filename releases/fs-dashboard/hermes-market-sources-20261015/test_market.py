from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
import sys
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

HERE = Path(__file__).resolve().parent
BASE = HERE/'deps' if (HERE/'deps').is_dir() else HERE.parent/'hermes-fc-pilot-20261013'
sys.path[:0] = [str(HERE/'source'), str(BASE)]

from market_snapshot import MarketReader, PLATFORMS, SOURCES
from research import ResearchBook, tool_schemas
from fs_evidence import SourcePins
from transport import Grants, Proxy, start_loopback
import market_snapshot_client

NOW = datetime(2026, 10, 15, 9, 10, tzinfo=timezone.utc)
STAMP = '2026-10-15T09:09:00+00:00'
RUN = '11111111-1111-1111-1111-111111111111'
URLS = dict(zip(SOURCES, ['https://www.lootbar.com/game-coins/fc27',
    'https://www.iggm.com/ea-sports-fc/fc-27-coins', 'https://www.u4gm.com/fc-27/coins', 'https://www.u7buy.com/fc27/coins']))


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root/'runs').mkdir(); (self.root/'monitor').mkdir()
        self.run = {'run_id': RUN, 'created_at': STAMP, 'status': 'ready_for_quote',
            'competitors': [dict(run_id=RUN, source=s, platform=p, status='valid', currency='USD',
                purchase_k='100', bonus_k='0', gross_usd='12', effective_usd_per_k='0.12',
                captured_at=STAMP, url=URLS[s], auth_state='logged_in' if s=='Lootbar' else 'public',
                coupon_excluded=False) for s in SOURCES for p in PLATFORMS],
            'costs': [dict(run_id=RUN, platform=p, status='valid', game='FC27', product='Game Coins',
                unit='CNY/K', cny_per_1k='0.56', genre='1', delivery_type='订单发货',
                trade_at='26-10-15 17:09:00', checked_at=STAMP, record_id='PRIVATE-ORDER',password='NEVER-EXPOSE') for p in PLATFORMS],
            'fx': {'status':'valid','cny_per_usd':'6.7253','published_at':'2026/10/15','checked_at':STAMP,
                   'url':'https://www.bankofchina.com/sourcedb/whpj/'}}
        self.own = {'currency':'USD','package_k':100,'collection_run_id':RUN,
            'rows':{p:dict(platform=p,status='ok',base_k='100',bonus_k='5',package_usd='12',checked_at=STAMP) for p in PLATFORMS}}
        self.reader = MarketReader(self.root, lambda: NOW); self.save()

    def save(self):
        (self.root/'runs'/f'{RUN}.json').write_text(json.dumps(self.run),encoding='utf-8')
        (self.root/'monitor/storefront.json').write_text(json.dumps(self.own),encoding='utf-8')

    def read(self):
        self.save(); return self.reader({'profile':'FC27'})

    def test_real_files_four_families_and_missing_not_zero(self):
        out=self.read();self.assertEqual(out['status'],'available')
        self.assertEqual((len(out['competitors']),len(out['costs']),len(out['storefront']['rows'])),(12,3,3))
        self.assertEqual(out['competitors'][0]['bonus_k'],'0')
        self.assertIsNone(out['competitors'][0]['mandatory_fees_usd'])
        self.assertFalse(out['can_recommend_price']);self.assertEqual(out['offer_completeness'],'partial')
        self.assertNotIn('PRIVATE-ORDER',json.dumps(out));self.assertNotIn('NEVER-EXPOSE',json.dumps(out))
        self.assertEqual(out['fx']['direction'],'CNY per USD')
        self.assertEqual(out['fx']['publication_time_status'],'not_provided')

    def test_closed_profile_and_no_path_url_or_refresh(self):
        for args in ({},{'profile':'FC26'},{'profile':'FC27','path':'/secret'},{'profile':'FC27','refresh':True},None):
            with self.subTest(args=args),self.assertRaises(ValueError):self.reader(args)

    def test_stale_and_future_are_not_available(self):
        for stamp in ['2026-10-15T00:00:00+00:00','2026-10-15T11:00:00+00:00']:
            with self.subTest(stamp=stamp):
                self.run['created_at']=stamp;self.assertEqual(self.read()['status'],'partial')

    def test_no_fallback_to_old_success_or_mtime(self):
        older=deepcopy(self.run);older['run_id']='22222222-2222-2222-2222-222222222222';older['created_at']='2026-10-15T09:08:00+00:00'
        path=self.root/'runs'/f"{older['run_id']}.json";path.write_text(json.dumps(older),encoding='utf-8');os.utime(path,(2100000000,2100000000))
        self.run['competitors']=[];out=self.read()
        self.assertEqual(out['collection_run_id'],RUN);self.assertEqual(out['status'],'partial')

    def test_duplicate_platform_and_conditional_offer_not_full(self):
        self.run['competitors'][0]['conditional']=True
        out=self.read();self.assertTrue(out['competitors'][0]['conditional']);self.assertFalse(out['competitors'][0]['complete_comparable_offer'])
        self.run['competitors'].append(self.run['competitors'][0]);self.assertEqual(self.read()['competitors'][0]['status'],'missing')

    def test_different_storefront_run_not_combined(self):
        self.own['collection_run_id']='different';out=self.read()
        self.assertEqual(out['status'],'partial');self.assertEqual(out['storefront']['rows'],[])

    def test_wrong_tier_currency_or_invalid_price_is_unusable(self):
        for key,value in [('purchase_k','1000'),('currency','EUR'),('gross_usd','NaN'),('gross_usd','Bearer secret'),('url','https://invalid/?password=secret')]:
            original=deepcopy(self.run['competitors'][0]);self.run['competitors'][0][key]=value
            out=self.read();self.assertEqual(out['competitors'][0]['status'],'unusable')
            self.assertNotIn('secret',json.dumps(out));self.run['competitors'][0]=original

    def test_cost_wrong_type_unit_scope_stale_or_foreign_run(self):
        for key,value in [('delivery_type','采购打款'),('delivery_type','销售补发'),('unit','USD/K'),('game','FC26'),('run_id','other'),('checked_at','2026-10-15T00:00:00+00:00'),('trade_at','26-10-01 12:00:00')]:
            original=deepcopy(self.run['costs'][0]);self.run['costs'][0][key]=value
            self.assertEqual(self.read()['costs'][0]['status'],'unusable');self.run['costs'][0]=original

    def test_absent_fx_not_zero_and_no_hidden_collection(self):
        self.run['fx']={};out=self.read();self.assertEqual(out['fx']['status'],'unusable')
        self.assertNotIn('cny_per_usd',out['fx']);self.assertFalse(out['collection_triggered']);self.assertFalse(out['business_writes'])

    def test_read_has_no_business_file_changes(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*.json')};self.reader({'profile':'FC27'})
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*.json')})

    def test_registered_schema_and_frozen_research_evidence(self):
        schema=[s for s in tool_schemas() if s['function']['name']=='mcp__fcro__fc_query_market_snapshot']
        self.assertEqual(len(schema),1);self.assertFalse(schema[0]['function']['parameters']['additionalProperties'])
        pins=SourcePins();data={'snapshot_id':'fc-detail-test','as_of':STAMP,'coverage':{},'orders':[],'backlog':[]}
        book=ResearchBook(data,{}, {},market=pins.wrap(self.reader,'market'))
        a=book.call('fc.query_market_snapshot',{'profile':'FC27'})
        self.run['costs'][0]['cny_per_1k']='9';self.save()
        b=book.call('fc.query_market_snapshot',{'profile':'FC27'})
        self.assertEqual(a['evidence_id'],b['evidence_id']);self.assertEqual(b['data']['costs'][0]['cny_per_1k'],'0.56')
        self.assertEqual(a['captured_at'],NOW.isoformat());self.assertTrue(a['snapshot_id'].startswith('src_'))

    def test_desktop_real_http_auth_and_closed_body(self):
        def no_gateway(grant):raise AssertionError('must not enter model gateway')
        proxy=Proxy(Grants(),no_gateway,market=self.reader,desktop_identity=lambda:'A'*43)
        server,thread=start_loopback(proxy,port=0)
        try:
            url='http://127.0.0.1:%s/fc/market-snapshot'%server.server_address[1]
            def call(token,args):return urlopen(Request(url,json.dumps(args).encode(),{'Authorization':'Bearer '+token}),timeout=5)
            with call('A'*43,{'profile':'FC27'}) as r:self.assertEqual(json.load(r)['collection_run_id'],RUN)
            for token,args in [('B'*43,{'profile':'FC27'}),('A'*43,{'profile':'FC27','refresh':True})]:
                with self.assertRaises(HTTPError) as e:call(token,args)
                self.assertIn(e.exception.code,(400,403));e.exception.close()
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_desktop_credential_never_uses_environment_http_proxy(self):
        with patch.dict(os.environ,{'http_proxy':'http://invalid.example:8080','https_proxy':'http://invalid.example:8080','no_proxy':''},clear=False):
            opener=market_snapshot_client.build_opener(market_snapshot_client.NoRedirect,market_snapshot_client.ProxyHandler({}))
            self.assertFalse(any(isinstance(h,market_snapshot_client.ProxyHandler) and h.proxies for h in opener.handlers))


if __name__=='__main__':unittest.main()
