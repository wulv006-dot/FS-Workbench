"""An FS connection namespace beside the unchanged official Desktop backend."""
import asyncio
import json
import hashlib
import hmac
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from conversation_desktop import SIGNING_CONTEXT, DesktopMethodNotFound


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class SignedHostClient:
    def __init__(self, key, endpoint='http://127.0.0.1:8931/internal/hermes/desktop'):
        self.key, self.endpoint = key, endpoint

    async def __call__(self, method, params, *, request_id=None):
        raw = json.dumps(dict(at=int(time.time()), nonce=uuid.uuid4().hex, method=method,
                              params=params, request_id=request_id), ensure_ascii=False).encode()
        signature = hmac.new(self.key, SIGNING_CONTEXT + raw, hashlib.sha256).hexdigest()
        def call():
            request = Request(self.endpoint, data=raw,
                              headers={'Content-Type': 'application/json', 'X-FS-Desktop-Signature': signature})
            try:
                with build_opener(NoRedirect()).open(request, timeout=20) as response:
                    data = response.read(16 * 1024 * 1024 + 1)
                    if len(data) > 16 * 1024 * 1024:
                        raise ValueError('desktop_rpc_response_size')
                    return json.loads(data)
            except HTTPError as error:
                if error.code == 501:
                    try:
                        error_body = error.read(1025)
                        missing = len(error_body) <= 1024 and json.loads(error_body) == {'error': 'desktop_method_not_found'}
                    except (OSError, ValueError):
                        missing = False
                    if missing:
                        raise DesktopMethodNotFound('desktop_method_unsupported') from None
                if error.code in (401, 403):
                    raise PermissionError('desktop_owner_unavailable') from None
                if error.code == 404:
                    raise LookupError('desktop_session_not_found') from None
                raise RuntimeError('desktop_rpc_rejected') from None
            except OSError:
                raise RuntimeError('desktop_rpc_outcome_unknown') from None
        return await asyncio.to_thread(call)


def install_fs_desktop(server):
    """Called by the existing /desktop/serve.py after official server import."""
    from starlette.requests import HTTPConnection
    original = server.app
    def authenticate(scope):
        # This dedicated creator connection currently uses the original shared-token gate.
        # Never silently grant FS access through an unrelated OAuth/host principal.
        if getattr(original.state, 'auth_required', False):
            return False
        request = HTTPConnection(dict(scope, app=original))
        if server._has_valid_session_token(request):
            return True
        if scope['type'] != 'websocket' or scope.get('path') != '/fs/api/ws':
            return False
        # Official query-token auth is download-only; this FS socket uses the
        # same existing credential without changing the official route allowlist.
        token = request.query_params.get('token', '')
        return bool(token) and hmac.compare_digest(token.encode(), server._SESSION_TOKEN.encode())
    server.app = DesktopFSGateway(original, SignedHostClient(server._SESSION_TOKEN.encode()), authenticate)


class DesktopFSGateway:
    def __init__(self, original, rpc, authenticate):
        self.original, self.rpc, self.authenticate = original, rpc, authenticate

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if not path.startswith('/fs/api/'):
            return await self.original(scope, receive, send)
        if self.authenticate(scope) is not True:
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 4401})
            else:
                await self.reply(send, 401, {'error': 'login_required'})
            return
        path = path[3:]
        if scope['type'] == 'websocket' and path == '/api/ws':
            return await self.websocket(receive, send)
        if scope['type'] != 'http' or scope['method'] != 'GET':
            return await self.reply(send, 405, {'error': 'method_not_allowed'})
        try:
            if path in ('/api/status', '/api/health'):
                await self.rpc('ping', {})
                result = dict(gateway_running=True, gateway_state='running', auth_required=False,
                              profiles=['default'], fs_conversation_namespace=True)
            elif path == '/api/profiles':
                result = {'profiles': [dict(name='default', is_default=True, display_name='FS Hermes')]}
            elif path in ('/api/sessions', '/api/profiles/sessions', '/api/sessions/all'):
                result = await self.rpc('session.list', {})
                result.update(total=len(result['sessions']), has_more=False, offset=0)
            elif path.startswith('/api/sessions/'):
                sid = path.split('/')[3]
                result = await self.rpc('session.resume', {'session_id': sid})
                result.update(total=result['message_count'], has_more=False, offset=0)
            else:
                return await self.reply(send, 404, {'error': 'not_found'})
            return await self.reply(send, 200, result)
        except PermissionError:
            return await self.reply(send, 403, {'error': 'access_denied'})
        except LookupError:
            return await self.reply(send, 404, {'error': 'session_not_found'})

    @staticmethod
    async def reply(send, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        await send(dict(type='http.response.start', status=status, headers=[
            (b'content-type', b'application/json'), (b'cache-control', b'no-store')]))
        await send(dict(type='http.response.body', body=raw))

    async def websocket(self, receive, send):
        if (await receive())['type'] != 'websocket.connect':
            return
        await send({'type': 'websocket.accept'})
        lock = asyncio.Lock()
        async def emit(value):
            async with lock:
                await send(dict(type='websocket.send', text=json.dumps(value, ensure_ascii=False)))
        async def event(kind, sid, payload):
            params = dict(type=kind, payload=payload)
            if sid:
                params['session_id'] = sid
            await emit(dict(jsonrpc='2.0', method='event', params=params))
        cursors = {}
        async def follow():
            while True:
                for sid, cursor in list(cursors.items()):
                    try:
                        rows = (await self.rpc('session.events', dict(session_id=sid, after=cursor)))['events']
                        for row in rows:
                            kind, payload = row['type'], row['payload']
                            if kind == 'message.delta':
                                await event('message.delta', sid, dict(text=payload.get('delta', '')))
                            elif kind == 'run.completed':
                                await event('message.complete', sid, dict(text=payload.get('output', ''), status='completed'))
                            elif kind in ('run.failed', 'run.interrupted'):
                                await event('status.update', sid, dict(kind='error', text=kind))
                            cursors[sid] = row['seq']
                            await event('sessions.changed', None, {})
                    except PermissionError:
                        await send({'type': 'websocket.close', 'code': 4403})
                        return
                    except RuntimeError:
                        await event('status.update', sid, dict(kind='error', text='FS 消息连接中断，请重连恢复。'))
                        await send({'type': 'websocket.close', 'code': 1011})
                        return
                await asyncio.sleep(0.5)
        await event('gateway.ready', None, dict(change_events=True, heartbeat=True))
        follower = asyncio.create_task(follow())
        try:
            while True:
                frame = await receive()
                if frame['type'] == 'websocket.disconnect':
                    break
                if frame['type'] != 'websocket.receive':
                    continue
                rid = None
                try:
                    request = json.loads(frame.get('text', ''))
                    rid, method = request['id'], request['method']
                    params = request.get('params', {})
                    if (request.get('jsonrpc') != '2.0' or not isinstance(params, dict)
                            or not isinstance(method, str) or not method):
                        raise ValueError('invalid_rpc')
                    if method == 'gateway.capabilities':
                        result = {'per_session_exclusive_submit': True, 'submission_id': True}
                    elif method == 'client.capabilities':
                        result = {'server_requests': []}
                    else:
                        result = await self.rpc(method, params, request_id=str(rid))
                    if method in ('session.resume', 'session.create', 'session.activate'):
                        cursors[result['session_id']] = result['last_seq']
                    await emit(dict(jsonrpc='2.0', id=rid, result=result))
                except DesktopMethodNotFound:
                    await emit(dict(jsonrpc='2.0', id=rid, error=dict(code=-32601, message='Method not found')))
                except (PermissionError, LookupError, ValueError, RuntimeError) as error:
                    await emit(dict(jsonrpc='2.0', id=rid, error=dict(
                        code=4030 if isinstance(error, PermissionError) else 4000,
                        message='FS conversation request rejected')))
        finally:
            follower.cancel()
            await asyncio.gather(follower, return_exceptions=True)
