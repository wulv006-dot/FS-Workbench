from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW, context, observation
from fc_collection.contracts import build_job, to_arab_status
from fc_collection.public_sources import arab_offers, arab_adapter, REGISTRY, VERSIONS
from fc_collection.adapters import SourceUnavailable


def native(platform='playstation'):
    return dict(platform=platform, market='pc' if platform == 'pc' else 'console',
        delivery=None if platform == 'pc' else 'normal', quantity=100000,
        total=dict(currency='SAR', amountHalalah=3550 if platform == 'pc' else 3200),
        displayTotal=dict(currency='USD', amountMinor=947 if platform == 'pc' else 853),
        priceVersion=3336, pricedAt=NOW.isoformat())


def task():
    return dict(build_job(dict(run_id='three-platform', created_at=NOW.isoformat()), 'ArabUT',
        dict(context(), requested_platforms=['PS', 'XBOX', 'PC'], region_scope=[21],
             adapter_version=VERSIONS['ArabUT'], total_request_budget=4),
        (NOW + timedelta(seconds=180)).isoformat()), attempt_id='attempt-1', lease_epoch=1,
        node_id='183', node_boot_id='boot-1')


class BidirectionalCollection(unittest.TestCase):
    def test_PC_is_independent_and_native_null_delivery_is_preserved(self):
        rows = arab_offers(native('pc'), NOW, platform='pc')
        self.assertEqual([r['platform'] for r in rows], ['PC'])
        self.assertEqual(rows[0]['amount'], '9.47')
        self.assertEqual(rows[0]['delivery_method'], 'standard')
        self.assertIsNone(rows[0]['source_metadata']['original_delivery'])
        for change in ({'platform':'playstation'}, {'market':'console'}, {'delivery':'normal'},
                       {'displayTotal':dict(currency='SAR', amountMinor=3550)}, {'bonus':5000}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                arab_offers(dict(native('pc'), **change), NOW, platform='pc')

    def collect(self, fail=None):
        calls=[]
        def get(template):
            calls.append(template)
            if template == fail: raise SourceUnavailable('http_503')
            return b'' if template.startswith('warm') else json.dumps(native('pc' if template=='quote_pc' else 'playstation')).encode()
        request=task()
        result=arab_adapter(request, SimpleNamespace(get=get, clock=lambda:NOW))
        body=observation(request)
        body.update(result, request_budget_used=len(calls))
        return to_arab_status([body], request, NOW), calls

    def test_official_English_quote_routes_and_all_platforms_survive_projection(self):
        self.assertEqual(REGISTRY['ArabUT']['quote']['path'], '/en/coins/quote')
        self.assertEqual(REGISTRY['ArabUT']['quote_pc']['query'], dict(platform='pc', quantity='100000'))
        result,calls=self.collect()
        self.assertEqual(calls,['warm','quote','quote_pc'])
        self.assertEqual(result['status'],'available')
        rows={r['platform']:r for r in result['offers']}
        self.assertEqual(set(rows),{'PS','XBOX','PC'})
        self.assertEqual(rows['PC']['total_usd'],'9.47')
        self.assertEqual(rows['PS']['total_usd'],'8.53')
        self.assertEqual(rows['PC']['reference_scope'],'global')
        self.assertEqual(rows['PC']['source_region_id'],21)
        self.assertEqual(rows['PC']['delivery'],'standard')
        self.assertIn('platform=pc',rows['PC']['url'])
        self.assertNotIn('delivery=normal',rows['PC']['url'])

    def test_one_platform_failure_keeps_other_quotes_and_reports_missing_reason(self):
        for failed, surviving, missing in [('quote_pc',{'PS','XBOX'},{'PC'}),('quote',{'PC'},{'PS','XBOX'})]:
            with self.subTest(failed=failed):
                result,_=self.collect(failed)
                self.assertEqual(result['status'],'partial')
                self.assertEqual({r['platform'] for r in result['offers']},surviving)
                self.assertEqual({r['platform'] for r in result['missing']},missing)
                self.assertTrue(all(r['reason']=='http_503' for r in result['missing']))

    def test_local_market_registry_uses_the_same_platform_contract(self):
        from fc_pricing_v3 import market_registry
        calls=[]
        class Response:
            def __init__(self, payload): self.payload=payload
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return self.payload
        def open_(request,**kwargs):
            calls.append(request.full_url)
            return Response(b'' if '/coins/quote' not in request.full_url else json.dumps(dict(data=native('pc' if 'platform=pc' in request.full_url else 'playstation'))).encode())
        with patch.object(market_registry,'build_opener',return_value=SimpleNamespace(open=open_)), \
                patch.object(market_registry, 'datetime', SimpleNamespace(now=lambda _: NOW)):
            result=market_registry.arab_normal()
        self.assertEqual({r['platform'] for r in result['offers']},{'PS','XBOX','PC'})
        self.assertTrue(all('/en/coins/quote?' in url for url in calls if 'coins/quote' in url))

    def test_closed_HTTP_failure_releases_only_slot_and_PC_remains_collectable(self):
        import tempfile
        from fc_collection.coordinator import Coordinator
        from fc_collection.worker import Worker
        from collection_cases import identity, policy
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            endpoint=Coordinator(root/'state.sqlite3')
            endpoint.configure_source('ArabUT', dict(policy(), origin='https://www.arab-ut.com',
                adapter_version=VERSIONS['ArabUT'], stable_seconds=0, max_requests=4))
            endpoint.register_node(identity(), ['ArabUT'], NOW)
            request=task()
            endpoint.enqueue({k:v for k,v in request.items() if k not in ('attempt_id','lease_epoch','node_id','node_boot_id')})
            def fetch(source, template, timeout):
                if template=='quote': raise SourceUnavailable('http_503')
                return b'' if template=='warm' else json.dumps(native('pc')).encode()
            self.assertEqual(Worker(endpoint,identity(),{'ArabUT':arab_adapter},root/'spool',fetch,clock=lambda:NOW).run_once()['status'],'accepted')
            accepted=endpoint.accepted(request['job_id'],NOW)
            with endpoint.transaction() as db:
                current=endpoint._get(db,'collection_jobs',request['job_id'])
                self.assertEqual(db.execute('SELECT SUM(count) FROM collection_permits').fetchone()[0],3)
            result=to_arab_status(accepted,current,NOW)
            self.assertEqual(result['status'],'partial')
            self.assertEqual([r['platform'] for r in result['offers']],['PC'])

    def test_transport_guard_failure_stops_the_remaining_platform_requests(self):
        calls=[]
        def get(template):
            calls.append(template)
            if template=='quote': raise ValueError('collection_routing_changed')
            return b''
        with self.assertRaisesRegex(ValueError,'collection_routing_changed'):
            arab_adapter(task(),SimpleNamespace(get=get,clock=lambda:NOW))
        self.assertEqual(calls,['warm','quote'])

    def test_PC_native_quote_timestamp_is_rechecked(self):
        for age in (901,-6):
            with self.subTest(age=age),self.assertRaisesRegex(ValueError,'observation_stale'):
                arab_offers(dict(native('pc'),pricedAt=(NOW-timedelta(seconds=age)).isoformat()),NOW,platform='pc')

    def test_local_HTTP_failure_preserves_other_platform_and_status_reason(self):
        from fc_pricing_v3 import market_registry
        from urllib.error import HTTPError
        for failed,remaining in [('platform=pc',{'PS','XBOX'}),('platform=playstation',{'PC'})]:
            class Response:
                def __init__(self,payload): self.payload=payload
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def read(self,*args): return self.payload
            def open_(request,**kwargs):
                if '/coins/quote' not in request.full_url:return Response(b'')
                if failed in request.full_url:raise HTTPError(request.full_url,503,'fixture',{},BytesIO(b''))
                return Response(json.dumps(native('pc' if 'platform=pc' in request.full_url else 'playstation')).encode())
            with self.subTest(failed=failed), patch.object(market_registry,'build_opener',return_value=SimpleNamespace(open=open_)), \
                    patch.object(market_registry,'datetime',SimpleNamespace(now=lambda _:NOW)):
                result=market_registry.arab_normal()
            self.assertEqual(result['status'],'partial')
            self.assertEqual({row['platform'] for row in result['offers']},remaining)
            self.assertTrue(all(row['reason']=='http_503' for row in result['missing']))
