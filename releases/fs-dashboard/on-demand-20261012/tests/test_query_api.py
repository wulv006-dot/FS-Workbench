import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import query_api as api

TOKEN = 'fsq_'+'a'*43
PERIOD = {'start': '2026-10-08 00:00', 'end': '2026-10-09 00:00'}


def source(value):
    return {'value': value, 'status': 'available'}


def fixture():
    return {'period': PERIOD, 'primary': {'status': 'available', 'currency': 'USD', 'period': PERIOD,
        'capturedAt': '2026-10-09T01:00:00+00:00', 'metrics': {'profitMarginPct': source(22.16),
        'averageOrderUsd': source(68.8), 'fulfillmentRatePct': source(83.13)}},
        'supplement': {'status': 'available', 'period': PERIOD, 'capturedAt': '2026-10-09T01:00:01+00:00',
        'metrics': {'newCustomers': source(217), 'repeatRatePct': source(70)},
        'dimensions': {'channels': [{'name': 'www.mmoexp.com', 'orders': 573, 'revenueUsd': 40302.75},
                                    {'name': 'another-brand', 'orders': 999, 'revenueUsd': 999999}]}}}


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = {'id': 'test-fc', 'enabled': True, 'projects': ['FC27'], 'includeProfit': True,
            'expiresAtEpoch': time.time()+3600, 'tokenSha256': hashlib.sha256(TOKEN.encode()).hexdigest()}
        self.path = Path(self.tmp.name)/'clients.json'
        self.save()
        self.registry = patch.object(api, 'REGISTRY', self.path)
        self.registry.start(); self.addCleanup(self.registry.stop)
        api.STARTS.clear()
        self.data = {'catalogId':'catalog-0123456789abcdef','snapshotId': 'catalog-0123456789abcdef', 'profiles': {'FC27': fixture(), 'D4': fixture()},
                     'dashboard': {'profiles': {}}}
        self.body = {'status': 'available', 'query': {'profile': 'FC27', 'start': '2026-10-08', 'end': '2026-10-08'},
            'scopeContractId':api.POLICY,'baseSnapshotId': self.data['snapshotId'], 'generatedAt': '2026-10-09T01:00:00+00:00', 'profile': {**fixture(),'key':'FC27'}}

    def save(self):
        self.path.write_text(json.dumps({'clients': [self.client]}), encoding='utf-8')

    def call(self, path='/api/fs/v1/statistics', query='profile=FC27&start=2026-10-08&end=2026-10-08'):
        with patch.object(api, 'snapshot', return_value=self.data), patch.object(api, 'exact_range', return_value=(200, self.body)) as upstream:
            result = api.handle(path, query, 'Bearer '+TOKEN)
        return result, upstream

    def test_auth_revoke_expire(self):
        self.assertEqual(api.authenticate('Bearer '+TOKEN)['id'], 'test-fc')
        for header in ('', 'Bearer '+TOKEN+'x', 'Bearer fsq_'+'b'*43):
            with self.assertRaises(api.Rejected): api.authenticate(header)
        self.client['enabled'] = False; self.save()
        with self.assertRaises(api.Rejected): api.authenticate('Bearer '+TOKEN)
        self.client.update(enabled=True, expiresAtEpoch=1); self.save()
        with self.assertRaises(api.Rejected): api.authenticate('Bearer '+TOKEN)

    def test_project_authorization_before_upstream(self):
        with patch.object(api, 'snapshot') as read:
            with self.assertRaises(api.Rejected) as rejected:
                api.handle('/api/fs/v1/statistics', 'profile=D4&start=2026-10-08&end=2026-10-08', 'Bearer '+TOKEN)
            self.assertEqual(rejected.exception.status, 403)
            read.assert_not_called()

    def test_invalid_parameters(self):
        for query in ('profile=FC27&profile=D4&start=2026-10-08&end=2026-10-08',
                      'profile=FC27&start=2026-02-30&end=2026-10-08',
                      'profile=FC27&start=2025-01-01&end=2026-10-08',
                      'profile=FC27&start=2026-10-08&end=2026-10-07',
                      'profile=FC27&start=2026-10-08&end=2026-10-08&site=all'):
            with self.subTest(query=query), self.assertRaises(api.Rejected): api.params(query, self.client)

    def test_current_policy_and_no_raw_data(self):
        (status, result, _), upstream = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(result['metrics']['orders']['value'], 573)
        self.assertEqual(result['metrics']['revenueUsd']['value'], '40302.75')
        self.assertEqual(result['metrics']['estimatedProfitUsd']['value'], '8931.09')
        self.assertIn('其他站点', result['metrics']['newCustomers']['scope'])
        self.assertEqual(result['metrics']['profitMarginPct']['source'], 'Order')
        self.assertFalse(result['coverage']['partialLastDay'])
        self.assertNotIn('another-brand', json.dumps(result))
        self.assertNotIn('primary', result)
        upstream.assert_called_once()

    def test_profit_permission_and_project_list(self):
        self.client['includeProfit'] = False; self.save()
        result, _ = self.call()
        self.assertNotIn('profitMarginPct', result[1]['metrics'])
        self.assertNotIn('estimatedProfitUsd', result[1]['metrics'])
        result, upstream = self.call('/api/fs/v1/profiles', '')
        self.assertEqual([r['profile'] for r in result[1]['profiles']], ['FC27'])
        upstream.assert_not_called()

    def test_dy_all_current_and_future_projects(self):
        self.client.update(id='dy-all-projects', owner='DY', projects=['*']); self.save()
        result,_=self.call('/api/fs/v1/profiles','')
        self.assertEqual([x['profile'] for x in result[1]['profiles']],['FC27','D4'])
        self.data['profiles']['NEW_GAME']=fixture()
        result,_=self.call('/api/fs/v1/profiles','')
        self.assertIn('NEW_GAME',[x['profile'] for x in result[1]['profiles']])
        self.body['query']['profile']='NEW_GAME'; self.body['profile']['key']='NEW_GAME'
        result,upstream=self.call(query='profile=NEW_GAME&start=2026-10-08&end=2026-10-08')
        self.assertEqual(result[0],200);upstream.assert_called_once()
        with self.assertRaises(api.Rejected) as exc:
            self.call(query='profile=UNKNOWN&start=2026-10-08&end=2026-10-08')
        self.assertEqual(exc.exception.code,'project_unavailable')

    def test_only_exact_dy_wildcard_is_allowed(self):
        for projects,owner,ident in [(['*','FC27'],'DY','dy-all-projects'),(['*'],'other','dy-all-projects'),(['*'],'DY','other')]:
            self.client.update(projects=projects,owner=owner,id=ident);self.save()
            with self.assertRaises(api.Rejected) as exc:api.authenticate('Bearer '+TOKEN)
            self.assertEqual(exc.exception.status,503)

    def test_dy_all_profit_mask_and_revocation_still_apply(self):
        self.client.update(id='dy-all-projects',owner='DY',projects=['*'],includeProfit=False);self.save()
        result,_=self.call();self.assertNotIn('profitMarginPct',result[1]['metrics'])
        self.assertNotIn('estimatedProfitUsd',result[1]['metrics'])
        for state in [{'enabled':False},{'enabled':True,'expiresAtEpoch':1}]:
            self.client.update(state);self.save()
            with self.assertRaises(api.Rejected) as exc:self.call('/api/fs/v1/profiles','')
            self.assertEqual(exc.exception.status,401)

    def test_missing_zero_negative_rate(self):
        p = fixture(); p['supplement']['status'] = 'unavailable'
        self.assertIsNone(api.project_metrics(p, True)['revenueUsd']['value'])
        p = fixture(); p['primary']['metrics']['profitMarginPct'] = source(0)
        self.assertEqual(api.project_metrics(p, True)['estimatedProfitUsd']['value'], '0.00')
        p['primary']['metrics']['profitMarginPct'] = source(-1)
        self.assertEqual(api.project_metrics(p, True)['estimatedProfitUsd']['value'], '-403.03')

    def test_upstream_pending_and_mismatch(self):
        with patch.object(api, 'snapshot', return_value=self.data):
            for status in (202, 409, 422, 429, 503):
                with patch.object(api, 'exact_range', return_value=(status, {'secret': 'never_forward'})):
                    r = api.handle('/api/fs/v1/statistics', 'profile=FC27&start=2026-10-08&end=2026-10-08', 'Bearer '+TOKEN)
                    self.assertEqual(r[0], status); self.assertNotIn('secret', r[1])
        self.body['query']['profile'] = 'D4'
        with self.assertRaises(ValueError): self.call()

    def test_admin_remains_available_but_mismatched_order_cannot_estimate(self):
        p=fixture();p['primary']['status']='unavailable';p['primary']['period']={}
        result=api.project_metrics(p,True)
        self.assertEqual(result['orders']['value'],573)
        self.assertIsNone(result['estimatedProfitUsd']['value'])
        p=fixture();p['primary']['period']={'start':'2026-10-01 00:00','end':'2026-10-02 00:00'}
        result=api.project_metrics(p,True)
        self.assertEqual(result['revenueUsd']['value'],'40302.75')
        self.assertIsNone(result['profitMarginPct']['value'])

    def test_throttle(self):
        for _ in range(30): api.throttle(self.client)
        with self.assertRaises(api.Rejected) as exc: api.throttle(self.client)
        self.assertEqual(exc.exception.status, 429)

    def test_catalog_validation_does_not_read_old_files(self):
        data={**self.data,'schemaVersion':2}
        with patch.object(api,'upstream',return_value=(200,data)) as read,patch.object(Path,'read_bytes',side_effect=AssertionError('legacy_file')):
            self.assertEqual(api.snapshot()['catalogId'],data['catalogId'])
            read.assert_called_once_with({'mode':'catalog'})
        with patch.object(api,'upstream',return_value=(200,{'schemaVersion':2,'catalogId':'not-a-catalog'})):
            with self.assertRaises(ValueError):api.snapshot()

    def test_http_denies_credentials_and_writes(self):
        server=api.ThreadingHTTPServer(('127.0.0.1', 0), api.Handler)
        thread=threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for method, headers, expected in [('GET', {}, 401), ('POST', {'Authorization':'Bearer '+TOKEN}, 405),
                                               ('GET', {'X-Auth-User':'DY'}, 401)]:
                conn=http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                conn.request(method, '/api/fs/v1/profiles', headers=headers)
                response=conn.getresponse(); response.read(); conn.close()
                self.assertEqual(response.status, expected)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
