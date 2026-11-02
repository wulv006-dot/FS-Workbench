from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW, context, coordinator, identity, observation


class PublicSource(unittest.TestCase):
    def test_malformed_public_JSON_produces_a_contract_error_not_daemon_crash(self):
        from fc_collection.public_sources import arab_adapter, arab_offers
        from types import SimpleNamespace
        for body in (b'[]', b'null', b'{"data":null}', b'{"data":{"total":null}}',
                     b'{"data":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'):
            transport = SimpleNamespace(get=lambda _, body=body: body, clock=lambda: NOW)
            with self.subTest(body=body[:20]), self.assertRaises(ValueError):
                arab_adapter(dict(requested_platforms=['PS', 'XBOX'], region_scope=[21]), transport)
        value = dict(platform='playstation', delivery='normal', quantity=100000, market='console', total=None)
        with self.assertRaises(ValueError):
            arab_offers(value, NOW)

    def test_registered_public_requests_keep_only_their_own_visitor_cookie(self):
        from http.client import HTTPMessage
        from types import SimpleNamespace
        from fc_collection.adapters import RestrictedHTTP
        from fc_collection.public_sources import REGISTRY
        calls = []
        class Response:
            status = 200
            def __init__(self):
                self.headers = HTTPMessage()
                self.headers['Set-Cookie'] = 'visitor=fixture; Path=/; Secure; HttpOnly'
                self.body = b'fixture'
            def getheader(self, key, default=None):
                return self.headers.get(key, default)
            def info(self):
                return self.headers
            def read1(self, _):
                body, self.body = self.body, b''
                return body
        class Connection:
            def __init__(self, *args):
                self.wire_socket = SimpleNamespace(settimeout=lambda _: None)
            def request(self, method, path, headers):
                calls.append((method, path, headers))
            def getresponse(self):
                return Response()
            def close(self):
                pass
            def abort(self):
                pass
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('fc_collection.adapters.PinnedHTTPS', Connection):
            http = RestrictedHTTP(REGISTRY)
            self.assertEqual(http.fetch('ArabUT', 'warm', 2), b'fixture')
            self.assertEqual(http.fetch('ArabUT', 'quote', 2), b'fixture')
        self.assertEqual(calls[0][1], '/?platform=playstation&delivery=normal&quantity=100000&currency=USD')
        self.assertEqual(calls[1][1], '/coins/quote?platform=playstation&delivery=normal&quantity=100000')
        self.assertEqual({k.lower(): v for k, v in calls[1][2].items()}['cookie'], 'visitor=fixture')
        self.assertNotIn('authorization', {k.lower() for k in calls[1][2]})

    def test_successful_request_completion_frees_slot_not_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            c = coordinator(Path(folder) / 'collection.sqlite3')
            task = c.claim_job(identity(), ['ItemD2R'], NOW)
            first = c.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
            c.complete_request(identity(), task['job_id'], 1, first['permit_id'], NOW)
            second = c.reserve_request(identity(), task['job_id'], 1, dict(count=5), NOW)
            self.assertNotEqual(first['permit_id'], second['permit_id'])
            c.complete_request(identity(), task['job_id'], 1, second['permit_id'], NOW)
            with self.assertRaisesRegex(ValueError, 'budget'):
                c.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)

    def test_other_node_cannot_finish_request_to_release_occupied_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            c = coordinator(Path(folder) / 'collection.sqlite3')
            task = c.claim_job(identity(), ['ItemD2R'], NOW)
            permit = c.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
            with self.assertRaises(ValueError):
                c.complete_request(identity('187'), task['job_id'], 1, permit['permit_id'], NOW)

    def test_official_arab_quote_preserves_USD_SAR_console_and_zero_PC(self):
        from fc_collection.public_sources import arab_offers
        value = dict(platform='playstation', delivery='normal', quantity=100000, market='console',
            total=dict(currency='SAR', amountHalalah=3750), displayTotal=dict(currency='USD', amountMinor=1000),
            priceVersion='fixture-version', pricedAt=NOW.isoformat())
        rows = arab_offers(value, NOW)
        self.assertEqual([r['platform'] for r in rows], ['PS', 'XBOX'])
        self.assertTrue(all(r['amount'] == '10' and r['settlement_currency'] == 'SAR'
                            and r['conversion_source'] == 'official_display_quote' for r in rows))
        for change in ({'market': 'pc'}, {'quantity': 100}, {'quantity': True}, {'delivery': 'express'},
                       {'displayTotal': dict(currency='SAR', amountMinor=1000)},
                       {'displayTotal': dict(currency='USD', amountMinor=True)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                arab_offers(dict(value, **change), NOW)

    def test_cross_currency_conversion_allowed_only_for_registered_arab_contract(self):
        from fc_collection.contracts import build_job, validate_observation, to_fc_quote_rows
        ctx = dict(context(), requested_platforms=['PS', 'XBOX'], region_scope=[21])
        task = build_job(dict(run_id='arab-run', created_at=NOW.isoformat()), 'ArabUT', ctx,
                         (NOW + timedelta(minutes=5)).isoformat())
        task.update(node_id='183', node_boot_id='boot-1', attempt_id='attempt-1', lease_epoch=1)
        body = observation(task)
        for row in body['offers']:
            row.update(region_id=21, settlement_currency='SAR', conversion_source='official_display_quote',
                       delivery_method='normal', price_basis='public_merchandise')
        validate_observation(body, task, NOW)
        result = to_fc_quote_rows([body], task, NOW)
        self.assertEqual(result['offers'][0]['settlement_currency'], 'SAR')
        self.assertEqual(result['offers'][0]['total_usd'], '10.00')
        invalid = deepcopy(body)
        invalid['offers'][0]['conversion_source'] = 'guessed_fx'
        with self.assertRaises(ValueError):
            validate_observation(invalid, task, NOW)

    def test_arab_version_matches_existing_natural_integer_receipts(self):
        from fc_collection.public_sources import arab_offers
        value = dict(platform='playstation', delivery='normal', quantity=100000, market='console',
            total=dict(currency='SAR', amountHalalah=3200), displayTotal=dict(currency='USD', amountMinor=853),
            priceVersion=2841, pricedAt='2026-11-02T11:09:20+00:00')
        rows = arab_offers(value, NOW)
        self.assertEqual([r['amount'] for r in rows], ['8.53', '8.53'])
        for version in (True, False, None, -1, 1.5, {}, [], ''):
            with self.subTest(version=version), self.assertRaises(ValueError):
                arab_offers(dict(value, priceVersion=version), NOW)
