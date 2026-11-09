import base64
import asyncio
import hashlib
import json
import re
from pathlib import Path
import tempfile
import socket
import threading
import time
import unittest
from unittest.mock import patch
import httpx
from urllib.parse import parse_qs, urlencode, urlsplit

from starlette.testclient import TestClient
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata
from mcp.client.streamable_http import streamablehttp_client
import uvicorn

from fs_mcp_connector.auth import AuthStore
from fs_mcp_connector.portal import PortalError, Principal
from fs_mcp_connector.server import create_app


ORIGIN = 'https://fs.example'
ISSUER = ORIGIN + '/connector'
RESOURCE = ISSUER + '/mcp'
VERIFIER = 'a' * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b'=').decode()


class Portal:
    status = 200

    def verify(self, cookie, path, method='GET'):
        if self.status != 200:
            raise PortalError(self.status)
        if path != '/dashboard/' or cookie not in ('MMOEXP_AUTH=alice', 'FS_ACCESS_CANDIDATE=alice'):
            raise PortalError(401)
        return Principal('alice', cookie)


class Data:
    def list(self, principal, module=None):
        return {'operations': [{'name': 'fixture.summary'}], 'subject': principal.subject, 'module': module}

    def query(self, principal, operation, arguments):
        return {'status_code': 206, 'data': {'status': 'partial', 'complete': False}, 'subject': principal.subject}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.portal = Portal()
        self.store = AuthStore(Path(self.temp.name) / 'oauth.db', RESOURCE, self.portal)
        self.backend = Data()
        self.client = TestClient(create_app(store=self.store, portal=self.portal, catalog=Data(),
            backend=self.backend, issuer=ISSUER, resource_url=RESOURCE), base_url=ORIGIN)
        self.client.__enter__()
        response = self.client.post('/connector/oauth/register', json={
            'redirect_uris': ['https://client.example/callback'], 'client_name': 'Fixture'})
        self.assertEqual(response.status_code, 201)
        self.cid = response.json()['client_id']
        self.params = dict(client_id=self.cid, redirect_uri='https://client.example/callback',
            resource=RESOURCE, code_challenge=CHALLENGE, code_challenge_method='S256',
            response_type='code', state='original-state', scope='fs.read')

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def approve(self, cookie_name='MMOEXP_AUTH'):
        self.client.cookies.set(cookie_name, 'alice')
        self.client.cookies.set('unrelated_session', 'must-not-forward')
        response = self.client.get('/connector/oauth/authorize', params=self.params)
        self.assertEqual(response.status_code, 200, response.text)
        form = {key: re.search(f'name="{key}" value="([^"]+)"', response.text)[1]
                for key in ('pending_id', 'csrf_token')}
        form['decision'] = 'approve'
        response = self.client.post('/connector/oauth/authorize', data=form,
            headers={'Origin': ORIGIN}, follow_redirects=False)
        self.assertEqual(response.status_code, 302, response.text)
        query = parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(query['state'], ['original-state'])
        response = self.client.post('/connector/oauth/token', data=dict(grant_type='authorization_code',
            client_id=self.cid, redirect_uri=self.params['redirect_uri'], resource=RESOURCE,
            code=query['code'][0], code_verifier=VERIFIER))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def rpc(self, token, method, params=None):
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': method}
        if params is not None:
            payload['params'] = params
        return self.client.post('/connector/mcp', json=payload, headers={
            'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'})

    def test_oauth_and_sdk_tools_use_authenticated_identity(self):
        tokens = self.approve()
        response = self.rpc(tokens['access_token'], 'initialize', {
            'protocolVersion': '2025-11-25', 'capabilities': {},
            'clientInfo': {'name': 'fixture', 'version': '1'}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('serverInfo', response.json()['result'])
        response = self.rpc(tokens['access_token'], 'tools/list')
        self.assertEqual(len(response.json()['result']['tools']), 2)
        response = self.rpc(tokens['access_token'], 'tools/call', {
            'name': 'fs_query_data', 'arguments': {'operation': 'fixture.summary', 'arguments': {}}})
        result = response.json()['result']
        self.assertFalse(result['isError'])
        self.assertFalse(result['structuredContent']['data']['complete'])
        self.assertEqual(result['structuredContent']['subject'], 'alice')
        self.assertNotIn('MMOEXP_AUTH', response.text)
        response = self.rpc(tokens['access_token'], 'tools/call', {
            'name': 'fs_list_data_sources', 'arguments': {'subject': 'admin'}})
        self.assertTrue(response.json()['result']['isError'])

    def test_registered_member_cookie_supported(self):
        self.assertIn('access_token', self.approve('FS_ACCESS_CANDIDATE'))

    def test_data_display_selection_follows_original_backend_read_without_forwarding_display_fields(self):
        tokens = self.approve()
        queried = {'operation': 'fixture.summary', 'status_code': 206,
                   'provenance': {'source': 'fixture'},
                   'data': {'rows': list(range(50)), 'complete': False, 'next_cursor': 'original-cursor'}}
        with patch.object(self.backend, 'query', return_value=queried) as query:
            response = self.rpc(tokens['access_token'], 'tools/call', {
                'name': 'fs_query_data', 'arguments': {'operation': 'fixture.summary',
                    'arguments': {'original': 'query'}, 'data_path': '/rows', 'offset': 20, 'limit': 3}})
        result = response.json()['result']
        self.assertFalse(result['isError'])
        self.assertEqual(result['structuredContent']['data'], [20, 21, 22])
        self.assertEqual(result['structuredContent']['response_view']['next_offset'], 23)
        self.assertEqual(result['structuredContent']['data_context']['']['next_cursor'], 'original-cursor')
        query.assert_called_once_with(Principal('alice', 'MMOEXP_AUTH=alice'), 'fixture.summary', {'original': 'query'})

    def test_data_display_never_runs_before_backend_authorization_or_exposes_outside_data(self):
        tokens = self.approve()
        request = {'name': 'fs_query_data', 'arguments': {'operation': 'fixture.summary',
                   'arguments': {}, 'data_path': '/provenance'}}
        with patch.object(self.backend, 'query', side_effect=PermissionError()), patch(
                'fs_mcp_connector.server.present', side_effect=AssertionError('must not display denied data')) as display:
            response = self.rpc(tokens['access_token'], 'tools/call', request)
        display.assert_not_called()
        result = response.json()['result']
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent']['error'], 'permission_denied')
        response = self.rpc(tokens['access_token'], 'tools/call', request)
        self.assertEqual(response.json()['result']['structuredContent']['error'], 'invalid_arguments')

    def test_oversized_text_error_preserves_original_cursor_and_source(self):
        tokens = self.approve()
        queried = {'operation': 'fixture.summary', 'status_code': 206, 'provenance': {'source': 'fixture'},
                   'data': {'text': 'x' * 20000, 'next_cursor': 'original-cursor'}}
        with patch.object(self.backend, 'query', return_value=queried):
            response = self.rpc(tokens['access_token'], 'tools/call', {
                'name': 'fs_query_data', 'arguments': {'operation': 'fixture.summary',
                    'arguments': {}, 'data_path': '/text'}})
        result = response.json()['result']
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent']['error'], 'response_too_large')
        self.assertEqual(result['structuredContent']['data_context']['']['next_cursor'], 'original-cursor')
        self.assertEqual(result['structuredContent']['provenance'], queried['provenance'])

    def test_catalog_module_detail_argument_uses_the_authenticated_identity(self):
        tokens = self.approve()
        response = self.rpc(tokens['access_token'], 'tools/call', {
            'name': 'fs_list_data_sources', 'arguments': {'module': 'user-analytics'}})
        result = response.json()['result']
        self.assertFalse(result['isError'])
        self.assertEqual(result['structuredContent']['module'], 'user-analytics')
        self.assertEqual(result['structuredContent']['subject'], 'alice')
        for arguments in ({'module': ''}, {'module': 1}, {'module': None},
                          {'module': 'user-analytics', 'subject': 'admin'}):
            with self.subTest(arguments=arguments):
                response = self.rpc(tokens['access_token'], 'tools/call', {
                    'name': 'fs_list_data_sources', 'arguments': arguments})
                self.assertTrue(response.json()['result']['isError'])

    def test_default_code_only_registration_does_not_issue_refresh(self):
        self.assertNotIn('refresh_token', self.approve())

    def test_installed_codex_native_dcr_metadata_is_accepted(self):
        payload = dict(application_type='native', client_name='Codex',
            redirect_uris=['http://127.0.0.1:1455/callback'],
            grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
            scope='fs.read', token_endpoint_auth_method='none')
        response = self.client.post('/connector/oauth/register', json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        registered = response.json()
        self.assertEqual(registered['redirect_uris'], payload['redirect_uris'])
        self.assertEqual(registered['grant_types'], payload['grant_types'])
        self.assertEqual(registered['token_endpoint_auth_method'], 'none')
        self.assertNotIn('client_secret', registered)

    def test_dcr_application_type_keeps_core_registration_checks(self):
        payload = dict(application_type='native', client_name='Codex',
            redirect_uris=['http://127.0.0.1:1455/callback'],
            grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
            scope='fs.read', token_endpoint_auth_method='none')
        for change in ({'application_type': 'unknown'}, {'application_type': []},
                {'application_type': None}, {'scope': 'fs.write'}, {'grant_types': ['refresh_token']},
                {'redirect_uris': ['http://remote.example/callback']},
                {'token_endpoint_auth_method': 'client_secret_basic'}, {'unexpected': 'metadata'}):
            with self.subTest(change=change):
                response = self.client.post('/connector/oauth/register', json=dict(payload, **change))
                self.assertEqual(response.status_code, 400)

    def test_duplicate_json_oauth_parameter_rejected(self):
        response = self.client.post('/connector/oauth/register',
            content='{"redirect_uris":["https://client.example/callback"],"client_name":"one","client_name":"two"}',
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_codex_identical_resource_query_reaches_real_consent(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        query = list(self.params.items()) + [('resource', RESOURCE)]
        response = self.client.get('/connector/oauth/authorize?' + urlencode(query))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('name="pending_id"', response.text)
        with self.store._db(write=False) as db:
            saved = db.execute('SELECT params FROM pending').fetchone()[0]
        self.assertEqual(__import__('json').loads(saved)['resource'], RESOURCE)

    def test_identical_resource_token_form_preserves_binding(self):
        code = self.store.issue_code(self.cid, self.params['redirect_uri'], RESOURCE, CHALLENGE,
            Principal('alice', 'MMOEXP_AUTH=alice'))
        fields = [('grant_type', 'authorization_code'), ('client_id', self.cid), ('code', code),
            ('redirect_uri', self.params['redirect_uri']), ('resource', RESOURCE),
            ('code_verifier', VERIFIER), ('resource', RESOURCE)]
        response = self.client.post('/connector/oauth/token', content=urlencode(fields),
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('access_token', response.json())

    def test_distinct_resources_and_other_duplicate_query_keys_rejected(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        for field, value in [('resource', RESOURCE + '/other'), ('client_id', self.cid),
                ('state', self.params['state'])]:
            with self.subTest(field=field):
                response = self.client.get('/connector/oauth/authorize?' +
                    urlencode(list(self.params.items()) + [(field, value)]))
                self.assertEqual(response.status_code, 400)
        with self.store._db(write=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pending').fetchone()[0], 0)

    def test_ambiguous_form_and_duplicate_json_resource_do_not_consume_code(self):
        for mode in ('distinct_resource', 'duplicate_client_id', 'duplicate_json_resource'):
            with self.subTest(mode=mode):
                code = self.store.issue_code(self.cid, self.params['redirect_uri'], RESOURCE, CHALLENGE,
                    Principal('alice', 'MMOEXP_AUTH=alice'))
                params = dict(grant_type='authorization_code', client_id=self.cid, code=code,
                    redirect_uri=self.params['redirect_uri'], resource=RESOURCE, code_verifier=VERIFIER)
                if mode == 'duplicate_json_resource':
                    raw = __import__('json').dumps(params)[:-1] + ',"resource":"' + RESOURCE + '"}'
                    headers = {'Content-Type': 'application/json'}
                else:
                    extra = ('resource', RESOURCE + '/other') if mode == 'distinct_resource' else ('client_id', self.cid)
                    raw = urlencode(list(params.items()) + [extra])
                    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
                response = self.client.post('/connector/oauth/token', content=raw, headers=headers)
                self.assertEqual(response.status_code, 400)
                self.assertIn('access_token', self.store.exchange_code(code, self.cid,
                    self.params['redirect_uri'], RESOURCE, VERIFIER))

    def test_chatgpt_locale_hint_reaches_consent_without_changing_authorization(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        response = self.client.get('/connector/oauth/authorize', params=dict(self.params, ui_locales='zh-CN en-US'))
        self.assertEqual(response.status_code, 200)
        with self.store._db(write=False) as db:
            saved = json.loads(db.execute('SELECT params FROM pending').fetchone()[0])
        self.assertEqual(saved, self.params)

    def test_locale_hint_also_preserves_original_login_request_contract(self):
        response = self.client.get('/connector/oauth/authorize', params=dict(self.params, ui_locales='zh-CN'),
            follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.store._db(write=False) as db:
            saved = json.loads(db.execute('SELECT params FROM login_requests').fetchone()[0])
        self.assertEqual(saved, self.params)

    def test_invalid_or_repeated_locale_hint_never_creates_pending(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        for hint in ('', 'a' * 129, 'zh-CN\n', '<script>', 'zh_CN'):
            with self.subTest(hint=hint):
                response = self.client.get('/connector/oauth/authorize', params=dict(self.params, ui_locales=hint))
                self.assertEqual(response.status_code, 400)
        response = self.client.get('/connector/oauth/authorize?' + urlencode(
            list(self.params.items()) + [('ui_locales', 'zh-CN'), ('ui_locales', 'zh-CN')]))
        self.assertEqual(response.status_code, 400)
        with self.store._db(write=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pending').fetchone()[0], 0)

    def test_long_oauth_request_survives_existing_login_next_limit(self):
        params = dict(self.params, state='s' * 1800)
        response = self.client.get('/connector/oauth/authorize', params=params, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        next_path = parse_qs(urlsplit(response.headers['location']).query)['next'][0]
        self.assertLessEqual(len(next_path), 512)
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        consent = self.client.get(next_path)
        self.assertEqual(consent.status_code, 200)
        form = {key: re.search(f'name="{key}" value="([^"]+)"', consent.text)[1]
                for key in ('pending_id', 'csrf_token')}
        form['decision'] = 'deny'
        response = self.client.post('/connector/oauth/authorize', data=form,
            headers={'Origin': ORIGIN}, follow_redirects=False)
        self.assertEqual(parse_qs(urlsplit(response.headers['location']).query)['state'], ['s'*1800])
        self.assertEqual(self.client.get(next_path).status_code, 400)

    def test_registration_grant_order_and_invalid_types(self):
        base = {'redirect_uris': ['https://client.example/callback']}
        response = self.client.post('/connector/oauth/register', json=dict(base,
            grant_types=['refresh_token', 'authorization_code']))
        self.assertEqual(response.status_code, 201)
        for grants in ('authorization_code', [[], 'refresh_token'],
                       ['authorization_code', 'client_credentials']):
            response = self.client.post('/connector/oauth/register', json=dict(base, grant_types=grants))
            self.assertEqual(response.status_code, 400)

    def test_missing_login_redirect_and_invalid_client(self):
        response = self.client.get('/connector/oauth/authorize', params=self.params, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['location'].startswith('/__auth/login?'))
        response = self.client.post('/connector/oauth/token', json={'grant_type': 'authorization_code',
            'client_id': [], 'code': 'x', 'redirect_uri': 'x', 'resource': RESOURCE, 'code_verifier': VERIFIER})
        self.assertEqual(response.status_code, 400)

    def test_authentication_outage_is_not_bad_token(self):
        tokens = self.approve()
        self.portal.status = 503
        self.assertEqual(self.rpc(tokens['access_token'], 'tools/list').status_code, 503)

    def test_challenge_and_metadata(self):
        response = self.client.post('/connector/mcp', json={})
        self.assertEqual(response.status_code, 401)
        self.assertIn('/.well-known/oauth-protected-resource/connector/mcp', response.headers['www-authenticate'])
        metadata = self.client.get('/.well-known/oauth-authorization-server/connector').json()
        self.assertEqual(metadata['code_challenge_methods_supported'], ['S256'])

    def test_cross_origin_consent_rejected(self):
        response = self.client.post('/connector/oauth/authorize', data={'decision': 'approve'},
            headers={'Origin': 'https://attacker.example'})
        self.assertEqual(response.status_code, 403)

    def test_null_and_missing_origin_do_not_consume_consent(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        consent = self.client.get('/connector/oauth/authorize', params=self.params)
        form = {key: re.search(f'name="{key}" value="([^"]+)"', consent.text)[1]
                for key in ('pending_id', 'csrf_token')}
        form['decision'] = 'approve'
        for headers in ({'Origin': 'null'}, {}):
            with self.subTest(headers=headers):
                response = self.client.post('/connector/oauth/authorize', data=form,
                    headers=headers, follow_redirects=False)
                self.assertEqual(response.status_code, 403)
        response = self.client.post('/connector/oauth/authorize', data=form,
            headers={'Origin': ORIGIN}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_consent_csp_allows_only_selected_registered_callback_origin(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        redirects = ['https://client.example/callback?hint=fixture', 'http://127.0.0.1:32123/callback',
            'https://host.example;script-src/return', 'https://*.example/return']
        client = self.store.register_client(redirects)
        expected = ['https://client.example', 'http://127.0.0.1:32123',
            'https://host.example%3Bscript-src', 'https://%2A.example']
        for target, source in zip(redirects, expected):
            with self.subTest(target=target):
                response = self.client.get('/connector/oauth/authorize', params=dict(
                    self.params, client_id=client['client_id'], redirect_uri=target))
                self.assertEqual(response.status_code, 200)
                policy = response.headers['content-security-policy']
                directives = dict(part.strip().split(' ', 1) for part in policy.split(';'))
                self.assertEqual(directives['form-action'], "'self' " + source)
                self.assertEqual(directives['script-src'], "'self'")
                self.assertNotIn('hint=', policy)
        response = self.client.get('/connector/oauth/authorize', params=dict(self.params,
            client_id=client['client_id'], redirect_uri='https://unregistered.example/callback'))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('unregistered.example', response.headers['content-security-policy'])

    def test_non_string_json_consent_is_rejected_without_consuming_request(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        response = self.client.get('/connector/oauth/authorize', params=self.params)
        form = {key: re.search(f'name="{key}" value="([^"]+)"', response.text)[1]
                for key in ('pending_id', 'csrf_token')}
        form['decision'] = 'approve'
        for key in form:
            response = self.client.post('/connector/oauth/authorize', json={**form, key: []},
                headers={'Origin': ORIGIN}, follow_redirects=False)
            self.assertEqual(response.status_code, 400)
        response = self.client.post('/connector/oauth/authorize', data=form,
            headers={'Origin': ORIGIN}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_browser_consent_uses_exact_fs_assets_and_existing_form_contract(self):
        self.client.cookies.set('MMOEXP_AUTH', 'alice')
        response = self.client.get('/connector/oauth/authorize', params=self.params)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['content-type'])
        self.assertEqual(response.headers['referrer-policy'], 'same-origin')
        self.assertIn('alice', response.text)
        self.assertIn('Fixture', response.text)
        self.assertIn('原有 private 权限', response.text)
        self.assertIn('<details', response.text)
        policy=response.headers['content-security-policy']
        self.assertIn("default-src 'none'", policy)
        self.assertIn("style-src 'self'", policy)
        self.assertIn("script-src 'self'", policy)
        self.assertNotIn('unsafe-inline', policy)
        root=Path(__file__).resolve().parents[2]
        assets={'fs-tokens.css':root/'ui-system/tokens/fs-tokens.css',
                'fs-ui.css':root/'ui-system/components/fs-ui.css',
                'fs-theme.js':root/'ui-system/adapters/fs-theme.js',
                'consent.css':root/'fs_mcp_connector/consent.css'}
        for name, original in assets.items():
            with self.subTest(asset=name):
                self.assertIn('/connector/assets/'+name,response.text)
                asset=self.client.get('/connector/assets/'+name)
                self.assertEqual(asset.status_code,200)
                self.assertEqual(asset.content,original.read_bytes())
                self.assertEqual(asset.headers['x-content-type-options'],'nosniff')
                self.assertIn('text/javascript' if name.endswith('.js') else 'text/css',asset.headers['content-type'])
        self.assertEqual(self.client.get('/connector/assets/server.py').status_code,404)
        self.assertEqual(self.client.get('/connector/assets/../../auth.py').status_code,404)
        self.assertEqual(self.client.post('/connector/assets/consent.css').status_code,405)

    def test_browser_authorize_errors_are_readable_but_token_errors_stay_json(self):
        for response,status in (
            (self.client.get('/connector/oauth/authorize'),400),
            (self.client.post('/connector/oauth/authorize',data={'decision':'approve'},
                headers={'Origin':'https://attacker.example'}),403),
            (self.client.post('/connector/oauth/authorize',data={'pending_id':'missing','csrf_token':'missing','decision':'approve'},
                headers={'Origin':ORIGIN}),401),
        ):
            with self.subTest(status=status):
                self.assertEqual(response.status_code,status)
                self.assertIn('text/html',response.headers['content-type'])
                self.assertIn('重新',response.text)
                self.assertNotIn('invalid_request',response.text)
                self.assertNotIn('Traceback',response.text)
        token=self.client.post('/connector/oauth/token',data={'grant_type':'invalid'})
        self.assertEqual(token.status_code,400)
        self.assertIn('application/json',token.headers['content-type'])
        self.assertEqual(token.json()['error'],'unsupported_grant_type')
        registration=self.client.post('/connector/oauth/register',json={})
        self.assertIn('application/json',registration.headers['content-type'])

    def test_browser_portal_failure_uses_error_page_without_internal_codes(self):
        self.client.cookies.set('MMOEXP_AUTH','alice')
        self.portal.status=503
        response=self.client.get('/connector/oauth/authorize',params=self.params)
        self.assertEqual(response.status_code,503)
        self.assertIn('text/html',response.headers['content-type'])
        self.assertIn('稍后',response.text)
        self.assertNotIn('temporarily_unavailable',response.text)
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_revocation(self):
        tokens = self.approve()
        self.client.post('/connector/oauth/revoke', data={'token': tokens['access_token'], 'client_id': self.cid})
        self.assertEqual(self.rpc(tokens['access_token'], 'tools/list').status_code, 401)

    def test_oversized_mcp_request_rejected(self):
        tokens = self.approve()
        response = self.client.post('/connector/mcp', content=b' ' * 65537,
            headers={'Authorization': 'Bearer '+tokens['access_token'], 'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 413)

    def test_real_sdk_client_over_loopback_http(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        resource = origin + '/connector/mcp'
        store = AuthStore(Path(self.temp.name)/'http.db', resource, self.portal)
        cid = store.register_client(['http://127.0.0.1:8234/callback'])['client_id']
        code = store.issue_code(cid, 'http://127.0.0.1:8234/callback', resource, CHALLENGE,
                                Principal('alice', 'MMOEXP_AUTH=alice'))
        tokens = store.exchange_code(code, cid, 'http://127.0.0.1:8234/callback', resource, VERIFIER)
        app = create_app(store=store, portal=self.portal, catalog=Data(), backend=Data(),
                         issuer=origin+'/connector', resource_url=resource)
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic()+5
            while not server.started and thread.is_alive() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(server.started)
            async def run():
                async with streamablehttp_client(resource, headers={'Authorization': 'Bearer '+tokens['access_token']}) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        self.assertEqual(len(result.tools), 2)
                        result = await session.call_tool('fs_list_data_sources', {})
                        self.assertFalse(result.isError)
                        self.assertEqual(result.structuredContent['subject'], 'alice')
            asyncio.run(asyncio.wait_for(run(), timeout=10))
        finally:
            server.should_exit = True
            thread.join(5)
            listener.close()
        self.assertFalse(thread.is_alive())

    def test_official_sdk_discovers_registers_and_authorizes(self):
        class Storage:
            tokens = client = None
            async def get_tokens(self): return self.tokens
            async def set_tokens(self, value): self.tokens = value
            async def get_client_info(self): return self.client
            async def set_client_info(self, value): self.client = value
        async def run():
            app = create_app(store=self.store, portal=self.portal, catalog=Data(), backend=Data(),
                             issuer=ISSUER, resource_url=RESOURCE)
            transport = httpx.ASGITransport(app=app)
            callback = []
            async def browser(url):
                async with httpx.AsyncClient(transport=transport, base_url=ORIGIN,
                        cookies={'MMOEXP_AUTH': 'alice'}, follow_redirects=False) as client:
                    consent = await client.get(url)
                    self.assertEqual(consent.status_code, 200, consent.text)
                    form = {key: re.search(f'name="{key}" value="([^"]+)"', consent.text)[1]
                            for key in ('pending_id', 'csrf_token')}
                    response = await client.post('/connector/oauth/authorize', data=dict(form, decision='approve'),
                                                 headers={'Origin': ORIGIN})
                    result = parse_qs(urlsplit(response.headers['location']).query)
                    callback.extend([result['code'][0], result.get('state', [None])[0]])
            async def receive_callback(): return tuple(callback)
            storage = Storage()
            auth = OAuthClientProvider(RESOURCE, OAuthClientMetadata(
                redirect_uris=['http://127.0.0.1:8234/callback'], token_endpoint_auth_method='none',
                grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
                client_name='SDK integration fixture'), storage, browser, receive_callback)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, auth=auth) as client:
                    response = await client.post(RESOURCE, headers={'Accept': 'application/json, text/event-stream'},
                        json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                            'protocolVersion': '2025-11-25', 'capabilities': {},
                            'clientInfo': {'name': 'fixture', 'version': '1'}}})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn('serverInfo', response.json()['result'])
                    self.assertIsNotNone(storage.tokens.refresh_token)
                    self.assertIsNotNone(storage.client.client_id)
        asyncio.run(asyncio.wait_for(run(), 10))
