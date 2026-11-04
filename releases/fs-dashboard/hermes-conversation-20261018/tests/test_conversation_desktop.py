"""Desktop projection must use the existing owner-scoped FS conversation store."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
import asyncio
import ast
import json
import hashlib
import hmac
import time
import uuid
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from conversation_store import ConversationStore
from conversation_desktop import ConversationDesktop, DesktopRPC, SIGNING_CONTEXT
from desktop_fs_gateway import DesktopFSGateway, SignedHostClient


class DesktopProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConversationStore(Path(self.temp.name) / 'conversations')
        self.original = self.store.create('alice')
        self.other = self.store.create('bob')
        self.calls = []
        def submit(owner, cid, text, request_id):
            self.calls.append((owner, cid, text, request_id))
            return self.store.reserve_turn(owner, cid, text, request_id)
        self.service = SimpleNamespace(store=self.store, _admin=lambda owner: self.check(owner),
            listed=self.store.listed, detail=self.store.detail, events=self.store.events,
            create=lambda owner: self.store.create(owner), submit=submit)
        self.adapter = ConversationDesktop(self.service)

    def check(self, owner):
        if owner != 'alice':
            raise PermissionError('revoked')

    def test_fs_created_session_is_listed_and_resumed_without_copy(self):
        result = self.adapter.dispatch('alice', 'session.list', {})
        self.assertEqual([r['id'] for r in result['sessions']], [self.original['session_id']])
        snap = self.adapter.dispatch('alice', 'session.resume', {'session_id': self.original['session_id']})
        self.assertEqual(snap['conversation_id'], self.original['conversation_id'])
        self.assertEqual(snap['stored_session_id'], self.original['session_id'])
        self.assertEqual(list(Path(self.temp.name).rglob('desktop*.db')), [])

    def test_other_owner_session_is_not_resolvable(self):
        with self.assertRaises(LookupError):
            self.adapter.dispatch('alice', 'session.resume', {'session_id': self.other['session_id']})

    def test_prompt_keeps_original_session_and_transport_request_id(self):
        params = dict(session_id=self.original['session_id'], text='connection probe')
        first = self.adapter.dispatch('alice', 'prompt.submit', params, request_id='desktop_probe_001')
        second = self.adapter.dispatch('alice', 'prompt.submit', params, request_id='desktop_probe_001')
        self.assertEqual(first['turn_id'], second['turn_id'])
        self.assertEqual(first['session_id'], self.original['session_id'])
        self.assertEqual(first['submission_id'], 'desktop_probe_001')
        self.assertEqual(first['status'], 'queued')
        self.assertGreater(first['user_row_id'], 0)
        self.assertEqual(self.calls[0], ('alice', self.original['conversation_id'], 'connection probe', 'desktop_probe_001'))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM turns').fetchone()[0], 1)

    def test_client_owner_and_missing_submit_request_are_rejected(self):
        params = dict(session_id=self.original['session_id'], text='probe')
        with self.assertRaises(ValueError):
            self.adapter.dispatch('alice', 'prompt.submit', dict(params, owner='bob'), request_id='desktop_probe_001')
        with self.assertRaises(ValueError):
            self.adapter.dispatch('alice', 'prompt.submit', params)
        self.assertEqual(self.calls, [])

    def test_revocation_is_checked_on_every_read(self):
        self.adapter.dispatch('alice', 'session.list', {})
        self.service._admin = lambda owner: (_ for _ in ()).throw(PermissionError('revoked'))
        with self.assertRaises(PermissionError):
            self.adapter.dispatch('alice', 'session.resume', {'session_id': self.original['session_id']})

    def test_stable_official_submission_id_is_preserved(self):
        params = dict(session_id=self.original['session_id'], text='probe', submission_id='desktop_submit_001')
        self.adapter.dispatch('alice', 'prompt.submit', params)
        self.assertEqual(self.calls[0][-1], 'desktop_submit_001')

    def test_installed_legacy_numeric_rpc_id_has_stable_fs_request_key(self):
        params = dict(session_id=self.original['session_id'], text='legacy probe')
        first = self.adapter.dispatch('alice', 'prompt.submit', params, request_id='1')
        second = self.adapter.dispatch('alice', 'prompt.submit', params, request_id='1')
        self.assertEqual(first['turn_id'], second['turn_id'])
        self.assertEqual(self.calls[0][-1], self.calls[1][-1])
        self.assertTrue(first['submission_id'].startswith('desktop_'))
        identity = json.dumps(['prompt.submit', self.original['session_id'], '1', 'legacy probe'],
                              ensure_ascii=False).encode()
        self.assertEqual(first['submission_id'], 'desktop_' + hashlib.sha256(identity).hexdigest())

    def test_actual_desktop_create_params_keep_host_identity_and_workspace(self):
        snap = self.adapter.dispatch('alice', 'session.create', dict(
            cols=96, source='desktop', fast=False, profile='default', cwd='/profile',
            cwd_explicit=False, reasoning_effort='high'))
        self.assertTrue(snap['session_id'].startswith('hc_'))
        with self.store.db() as db:
            row = self.store._owned(db, 'alice', snap['conversation_id'])
            self.assertEqual(row['owner'], 'alice')
        with self.assertRaises(ValueError):
            self.adapter.dispatch('alice', 'session.create', {'model': 'unhandled-manual-selection'})

    def test_events_reconnect_and_stop_use_original_run(self):
        cid = self.original['conversation_id']
        turn = self.store.reserve_turn('alice', cid, 'probe', 'desktop_probe_001')
        run = 'run_' + 'a' * 32
        self.store.bind_run('alice', cid, turn['turn_id'], run)
        self.store.append_event('alice', cid, run, 0, {'event': 'message.delta', 'delta': 'probe'})
        params = dict(session_id=self.original['session_id'])
        events = self.adapter.dispatch('alice', 'session.events', params)['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(self.adapter.dispatch('alice', 'session.events', dict(params, after=events[0]['seq']))['events'], [])
        stopped = []
        self.service.stop = lambda *args: stopped.append(args) or {'ok': True}
        self.adapter.dispatch('alice', 'session.interrupt', params, request_id='desktop_stop_001')
        self.assertEqual(stopped, [('alice', cid, run, 'desktop_stop_001')])


class DesktopWireTests(unittest.IsolatedAsyncioTestCase):
    setUp = DesktopProjectionTests.setUp
    check = DesktopProjectionTests.check

    async def test_existing_shared_backend_is_preserved_and_fs_is_authenticated(self):
        delegated = []
        async def original(*args): delegated.append(args[0]['path'])
        async def rpc(method, params, **kw): return self.adapter.dispatch('alice', method, params, **kw)
        gateway = DesktopFSGateway(original, rpc, lambda scope: False)
        sent = []
        async def send(value): sent.append(value)
        async def receive(): return {'type': 'http.request', 'body': b''}
        await gateway({'type': 'http', 'path': '/api/sessions', 'method': 'GET'}, receive, send)
        await gateway({'type': 'websocket', 'path': '/api/ws'}, receive, send)
        self.assertEqual(delegated, ['/api/sessions', '/api/ws'])
        await gateway({'type': 'http', 'path': '/fs/api/sessions', 'method': 'GET'}, receive, send)
        self.assertEqual(sent[0]['status'], 401)

    async def test_same_fs_session_events_reach_desktop_and_reply_is_original_turn(self):
        async def rpc(method, params, **kw): return self.adapter.dispatch('alice', method, params, **kw)
        gateway = DesktopFSGateway(None, rpc, lambda scope: True)
        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
        await incoming.put({'type': 'websocket.connect'})
        async def send(value): await outgoing.put(value)
        async def receive(): return await incoming.get()
        task = asyncio.create_task(gateway({'type': 'websocket', 'path': '/fs/api/ws'}, receive, send))
        async def response(rid):
            while True:
                frame = await asyncio.wait_for(outgoing.get(), 3)
                if frame['type'] != 'websocket.send': continue
                value = json.loads(frame['text'])
                if value.get('id') == rid: return value
        sid = self.original['session_id']
        await incoming.put(dict(type='websocket.receive', text=json.dumps(dict(
            jsonrpc='2.0', id='resume_001', method='session.resume', params={'session_id': sid}))))
        result = await response('resume_001')
        self.assertEqual(result['result']['conversation_id'], self.original['conversation_id'])
        turn = self.store.reserve_turn('alice', self.original['conversation_id'], 'FS probe', 'server_probe_001')
        run = 'run_' + 'b' * 32
        self.store.bind_run('alice', self.original['conversation_id'], turn['turn_id'], run)
        self.store.append_event('alice', self.original['conversation_id'], run, 0,
                                {'event': 'run.completed', 'output': 'FS no-business probe'})
        self.store.set_state('alice', self.original['conversation_id'], turn['turn_id'], 'completed')
        while True:
            frame = await asyncio.wait_for(outgoing.get(), 3)
            if frame['type'] != 'websocket.send': continue
            value = json.loads(frame['text'])
            if value.get('params', {}).get('type') == 'message.complete':
                self.assertEqual(value['params']['session_id'], sid)
                self.assertEqual(value['params']['payload']['text'], 'FS no-business probe')
                break
        await incoming.put(dict(type='websocket.receive', text=json.dumps(dict(
            jsonrpc='2.0', id='reply_001', method='prompt.submit', params=dict(
                session_id=sid, text='Desktop reply probe', submission_id='desktop_reply_001')))))
        reply = await response('reply_001')
        self.assertIn('turn_id', reply['result'])
        self.assertEqual(self.calls[-1][:3], ('alice', self.original['conversation_id'], 'Desktop reply probe'))
        await incoming.put({'type': 'websocket.disconnect'})
        await asyncio.wait_for(task, 3)

    async def test_host_poll_failure_closes_socket_without_resubmitting(self):
        async def rpc(method, params, **kwargs):
            if method == 'session.events':
                raise RuntimeError('synthetic host disconnect')
            return self.adapter.dispatch('alice', method, params, **kwargs)
        gateway = DesktopFSGateway(None, rpc, lambda scope: True)
        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
        await incoming.put({'type': 'websocket.connect'})
        await incoming.put(dict(type='websocket.receive', text=json.dumps(dict(
            jsonrpc='2.0', id='resume_001', method='session.resume',
            params=dict(session_id=self.original['session_id'])))))
        task = asyncio.create_task(gateway({'type': 'websocket', 'path': '/fs/api/ws'}, incoming.get, outgoing.put))
        try:
            while True:
                frame = await asyncio.wait_for(outgoing.get(), 2)
                if frame['type'] == 'websocket.close':
                    self.assertEqual(frame['code'], 1011)
                    break
            self.assertEqual(self.calls, [])
        finally:
            await incoming.put({'type': 'websocket.disconnect'})
            await asyncio.wait_for(task, 2)


class CreatorBindingTests(unittest.TestCase):
    setUp = DesktopProjectionTests.setUp
    check = DesktopProjectionTests.check
    def test_original_credential_signs_without_export_and_host_binds_owner(self):
        folder = Path(self.temp.name)
        credential = folder / 'original-desktop-token'
        credential.write_text('synthetic-existing-credential')
        credential.chmod(0o600)
        binding = folder / 'creator.json'
        binding.write_text(json.dumps(dict(principal='alice', credential_file=str(credential))))
        binding.chmod(0o600)
        # Final OS owner metadata is a fixture; file bytes/HMAC/auth/store are real.
        if os.name == 'posix':
            original_fstat = os.fstat
            inode = binding.stat().st_ino
            def fstat(fd):
                value = original_fstat(fd)
                if value.st_ino == inode:
                    return SimpleNamespace(st_mode=value.st_mode, st_nlink=value.st_nlink,
                                           st_size=value.st_size, st_uid=0)
                return value
            fixture = patch('conversation_desktop.os.fstat', fstat)
            fixture.start()
            self.addCleanup(fixture.stop)
        server = DesktopRPC(self.service, lambda owner: owner == 'alice', binding)
        def signed(method='session.list', params=None):
            raw = json.dumps(dict(at=int(time.time()), nonce=uuid.uuid4().hex,
                method=method, params=params or {}, request_id='desktop_wire_001')).encode()
            return raw, hmac.new(credential.read_bytes(), SIGNING_CONTEXT + raw, hashlib.sha256).hexdigest()
        raw, signature = signed()
        self.assertEqual(server.call(raw, signature)['sessions'][0]['id'], self.original['session_id'])
        with self.assertRaises(PermissionError): server.call(raw, signature)
        raw, signature = signed()
        with self.assertRaises(PermissionError): server.call(raw + b' ', signature)
        raw, signature = signed(params={'owner': 'bob'})
        with self.assertRaises(ValueError): server.call(raw, signature)
        server.authorize = lambda owner: 1
        raw, signature = signed()
        with self.assertRaises(PermissionError): server.call(raw, signature)
        server.authorize = lambda owner: False
        raw, signature = signed()
        with self.assertRaises(PermissionError): server.call(raw, signature)

        server.authorize = lambda owner: owner == 'alice'
        source = Path(__file__).resolve().parents[4] / 'releases/fs-dashboard/management-november-20261103/source/range_api.py'
        tree = ast.parse(source.read_text('utf-8'))
        handler_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        method = next(n for n in handler_class.body if isinstance(n, ast.FunctionDef) and n.name == 'do_POST')
        from urllib.parse import urlsplit
        from conversation_http import PREFIX, respond
        namespace = dict(urlsplit=urlsplit, CONVERSATION_PREFIX=PREFIX, DESKTOP_RPC=server,
                         conversation_respond=respond)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        class Handler(BaseHTTPRequestHandler):
            do_POST = namespace['do_POST']
            def log_message(self, *args): pass
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            client = SignedHostClient(credential.read_bytes(),
                'http://127.0.0.1:%d/internal/hermes/desktop' % http.server_port)
            result = asyncio.run(client('session.list', {}))
            self.assertEqual(result['sessions'][0]['id'], self.original['session_id'])
            with self.assertRaises(PermissionError):
                asyncio.run(SignedHostClient(b'wrong', client.endpoint)('session.list', {}))
        finally:
            http.shutdown()
            http.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
