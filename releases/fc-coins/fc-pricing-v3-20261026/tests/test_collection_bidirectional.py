from copy import deepcopy
from datetime import timedelta
from http.client import HTTPMessage
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW, context, identity, observation, policy
from fc_collection.contracts import build_job, to_arab_status
from fc_collection.public_sources import arab_offers, arab_adapter, REGISTRY, VERSIONS
from fc_collection.adapters import ArabNormalDeliveryUnavailable, SourceUnavailable


def native(platform='playstation'):
    return dict(platform=platform, market='pc' if platform == 'pc' else 'console',
        delivery=None if platform == 'pc' else 'normal', quantity=100000,
        total=dict(currency='SAR', amountHalalah=3550 if platform == 'pc' else 3200),
        displayTotal=dict(currency='USD', amountMinor=947 if platform == 'pc' else 853),
        priceVersion=3336, pricedAt=NOW.isoformat())


def task(*, request_budget=4):
    return dict(build_job(dict(run_id='three-platform', created_at=NOW.isoformat()), 'ArabUT',
        dict(context(), requested_platforms=['PS', 'XBOX', 'PC'], region_scope=[21],
             adapter_version=VERSIONS['ArabUT'], total_request_budget=request_budget),
        (NOW + timedelta(seconds=180)).isoformat()), attempt_id='attempt-1', lease_epoch=1,
        node_id='183', node_boot_id='boot-1')


class BidirectionalCollection(unittest.TestCase):
    def test_console_delivery_rejection_releases_the_permit_for_fast_and_independent_pc(self):
        from fc_collection.adapters import RestrictedHTTP, WarmLanguageRedirect
        from fc_collection.coordinator import Coordinator
        from fc_collection.worker import BudgetedTransport, collect_job

        with tempfile.TemporaryDirectory() as temp:
            coordinator = Coordinator(Path(temp) / 'collection.sqlite3')
            coordinator.configure_source('ArabUT', dict(policy(), origin='https://www.arab-ut.com',
                adapter_version=VERSIONS['ArabUT'], max_requests=8))
            coordinator.register_node(identity(), ['ArabUT'], NOW - timedelta(seconds=6))
            job = task(request_budget=8)
            for key in ('attempt_id', 'lease_epoch', 'node_id', 'node_boot_id'):
                del job[key]
            coordinator.enqueue(job)
            claimed = coordinator.claim_job(identity(), ['ArabUT'], NOW)
            http = RestrictedHTTP(REGISTRY)
            calls = []

            def fetch(source, template, timeout):
                calls.append(template)
                if template == 'warm':
                    raise WarmLanguageRedirect('warm_en')
                if template == 'warm_en':
                    return b''
                if template == 'quote':
                    with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                            patch('fc_collection.adapters.PinnedHTTPS') as pinned:
                        response = Mock(status=422)
                        response.getheader.side_effect = lambda key, default=None: default
                        response.info.return_value = HTTPMessage()
                        response.read1.side_effect = [json.dumps({'errors': {'delivery': [
                            'This delivery speed is not available right now. Choose fast delivery.',
                        ]}}).encode(), b'']
                        pinned.return_value.getresponse.return_value = response
                        return http.fetch(source, template, timeout)
                offer = native('pc' if template == 'quote_pc' else 'playstation')
                if template == 'quote_fast':
                    offer['delivery'] = 'fast'
                return json.dumps(offer).encode()

            transport = BudgetedTransport(coordinator, identity(), claimed, fetch, lambda: NOW)
            body = collect_job(claimed, arab_adapter, transport, lambda: NOW)
            self.assertEqual(body['status'], 'ok')
            self.assertEqual(calls, ['warm', 'warm_en', 'quote', 'quote_fast', 'quote_pc'])
            self.assertEqual(body['request_budget_used'], 5)
            self.assertEqual(coordinator.submit_observation(identity(), body, NOW)['status'], 'accepted')

    def test_quantity_table_uses_one_lease_request_and_preserves_native_money_and_delivery(self):
        from fc_collection.adapters import RestrictedHTTP
        from fc_collection.contracts import ARAB_TABLE_SCOPE
        from fc_collection.worker import collect_job
        html = b'''<table aria-labelledby="coins-prices-console" class="coins-prices__table">
        <tr><th>Amount</th><th>Normal<small>2 hours</small></th><th>Fast<small>45 min</small></th></tr>
        <tr><th>100K</th><td>USD&nbsp;8.96</td><td>USD&nbsp;9.57</td></tr>
        <tr><th>1M</th><td>USD&nbsp;70.53</td><td>USD&nbsp;76.19</td></tr>
        <tr><th>2M</th><td>USD&nbsp;142.45</td><td>USD&nbsp;169.20</td></tr>
        <tr><th>5M</th><td>&mdash;</td><td>USD&nbsp;424.99</td></tr></table>
        <table aria-labelledby="coins-prices-pc" class="coins-prices__table coins-prices__table--single">
        <tr><th>Amount</th><th>Price</th></tr><tr><th>100K</th><td>USD&nbsp;11.63</td></tr>
        <tr><th>1M</th><td>USD&nbsp;94.83</td></tr><tr><th>2M</th><td>USD&nbsp;211.97</td></tr>
        <tr><th>5M</th><td>USD&nbsp;536.21</td></tr></table>'''
        scope = dict(context(),requested_platforms=['PS','XBOX','PC'],region_scope=[21],
                     quantity_scope=ARAB_TABLE_SCOPE,currency='native',adapter_version=VERSIONS['ArabUT'],
                     total_request_budget=1,total_attempt_limit=1)
        request=build_job(dict(run_id='quantity-market',created_at=NOW.isoformat()),'ArabUT',
                          scope,(NOW+timedelta(seconds=60)).isoformat())
        request.update(attempt_id='attempt-1',lease_epoch=1,node_id='183',node_boot_id='boot-1')
        calls=[]
        def get(template):
            calls.append(template)
            return html
        body=collect_job(request,arab_adapter,SimpleNamespace(get=get,clock=lambda:NOW,used=1),lambda:NOW)
        self.assertEqual(calls,['prices_table'])
        result=to_arab_status([body],request,NOW)
        self.assertEqual(result['offers'],[])
        rows={(row['platform'],row['purchase_k'],row['delivery_tier']):row for row in result['quantity_offers']}
        self.assertEqual(len(rows),18)
        self.assertNotIn(('PS','5000','normal'),rows)
        self.assertEqual(rows[('PS','5000','fast')]['regular_price'],'424.99')
        self.assertEqual(rows[('XBOX','5000','fast')]['regular_price'],'424.99')
        self.assertEqual(rows[('PC','5000','standard')]['original_amount_minor'],53621)
        self.assertIsNone(rows[('PC','5000','standard')]['bonus_k'])
        self.assertFalse(rows[('PC','5000','standard')]['comparable'])
        self.assertIn('prices_table',RestrictedHTTP(REGISTRY).registry['ArabUT'])
        for forged in (dict(REGISTRY['ArabUT']['prices_table'],path='/coins/prices'),
                       dict(REGISTRY['ArabUT']['prices_table'],query={'currency':'SAR'})):
            with self.assertRaisesRegex(ValueError,'arab_prices_table_endpoint_invalid'):
                RestrictedHTTP({'ArabUT':{'prices_table':forged}})
        with self.assertRaisesRegex(ValueError,'arab_price_table_scope_invalid'):
            build_job(dict(run_id='quantity-market',created_at=NOW.isoformat()),'ArabUT',
                      dict(scope,total_request_budget=2),(NOW+timedelta(seconds=60)).isoformat())

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

    def test_official_fast_quote_survives_signed_projection_when_normal_is_unavailable(self):
        calls = []
        def get(template):
            calls.append(template)
            if template == 'quote':
                raise ArabNormalDeliveryUnavailable()
            if template == 'warm':
                return b''
            value = native('pc' if template == 'quote_pc' else 'playstation')
            if template == 'quote_fast':
                value.update(delivery='fast', total=dict(currency='SAR', amountHalalah=2880),
                             displayTotal=dict(currency='USD', amountMinor=768))
            return json.dumps(dict(data=value)).encode()
        request = task()
        result = arab_adapter(request, SimpleNamespace(get=get, clock=lambda: NOW))
        body = observation(request)
        body.update(result, request_budget_used=len(calls))
        projected = to_arab_status([body], request, NOW)
        self.assertEqual(calls, ['warm', 'quote', 'quote_fast', 'quote_pc'])
        self.assertEqual(projected['status'], 'available')
        rows = {row['platform']: row for row in projected['offers']}
        for platform in ('PS', 'XBOX'):
            self.assertEqual(rows[platform]['total_usd'], '7.68')
            self.assertEqual(rows[platform]['delivery'], 'fast')
            self.assertEqual(rows[platform]['original_delivery'], 'fast')
            self.assertIn('delivery=fast', rows[platform]['url'])
        self.assertEqual(rows['PC']['total_usd'], '9.47')
        self.assertEqual(rows['PC']['delivery'], 'standard')
        self.assertIsNone(rows['PC']['original_delivery'])

        from fc_pricing_v3.competitor_offers import LEGACY_POLICY as POLICY
        from fc_pricing_v3.selective_sources import planned_source_coverage, source_plan
        plan = source_plan('smart', dict(competitor_policy=POLICY))
        coverage = planned_source_coverage(dict(run_id='three-platform', competitor_offers=[],
            arab_ut_status=projected), plan, NOW)
        self.assertEqual({(row['platform'], row['delivery_method'], row['regular_price'])
                          for row in coverage['normalized_offers']},
                         {('PS', 'fast', '7.68'), ('XBOX', 'fast', '7.68'), ('PC', 'standard', '9.47')})

        body['offers'][0]['source_metadata']['original_delivery'] = 'normal'
        with self.assertRaisesRegex(ValueError, 'source_metadata_invalid'):
            to_arab_status([body], request, NOW)

    def test_local_market_retries_only_verified_normal_delivery_rejection(self):
        from contextlib import nullcontext
        from urllib.error import HTTPError
        from fc_pricing_v3 import market_registry
        unavailable = b'{"errors":{"delivery":["This delivery speed is not available right now. Choose fast delivery."]}}'
        for error_body, fast_quote in ((unavailable, True), (b'{"errors":{"quantity":["Invalid"]}}', False)):
            calls = []
            def open_quote(request, **kwargs):
                url = request.full_url
                calls.append(url)
                if '/coins/quote' not in url:
                    return nullcontext(BytesIO(b''))
                if 'delivery=normal' in url:
                    raise HTTPError(url, 422, 'fixture', {}, BytesIO(error_body))
                data = native('pc' if 'platform=pc' in url else 'playstation')
                if 'delivery=fast' in url:
                    data['delivery'] = 'fast'
                return nullcontext(BytesIO(json.dumps(dict(data=data)).encode()))
            with self.subTest(fast_quote=fast_quote), \
                    patch.object(market_registry,'build_opener',return_value=SimpleNamespace(open=open_quote)), \
                    patch.object(market_registry,'datetime',SimpleNamespace(now=lambda _:NOW)):
                rows = {row['platform']: row['delivery'] for row in market_registry.arab_normal()['offers']}
            self.assertEqual(rows, dict(PS='fast', XBOX='fast', PC='standard') if fast_quote else dict(PC='standard'))
            self.assertEqual(sum('delivery=fast' in url for url in calls), int(fast_quote))

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
