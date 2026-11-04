"""Desktop protocol projection over the original FS store; caller authenticates owner."""
import re
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import threading
import time
from datetime import datetime

SIGNING_CONTEXT = b'FS Desktop conversation RPC v1\n'


class DesktopMethodNotFound(ValueError):
    """A well-formed request names a method this FS adapter does not implement."""


def private_bytes(path, *, root_owned=False):
    path = Path(path)
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > 4096
                or (os.name == 'posix' and (stat.S_IMODE(metadata.st_mode) != 0o600
                    or (root_owned and metadata.st_uid != 0)))):
            raise PermissionError('desktop_private_file_boundary')
        return stream.read(4097)


class DesktopRPC:
    """The host alone maps a verified Desktop issuer to its configured FS principal."""
    def __init__(self, service, authorize, binding_path):
        self.adapter = ConversationDesktop(service)
        self.authorize, self.binding_path = authorize, Path(binding_path)
        self.nonces, self.lock = {}, threading.Lock()

    def call(self, raw, signature):
        if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
            raise ValueError('desktop_rpc_size')
        binding = json.loads(private_bytes(self.binding_path, root_owned=True))
        if set(binding) != {'principal', 'credential_file'} or not isinstance(binding['principal'], str):
            raise PermissionError('desktop_creator_binding')
        key = private_bytes(binding['credential_file']).strip()
        if len(key) < 16:
            raise PermissionError('desktop_credential_unavailable')
        expected = hmac.new(key, SIGNING_CONTEXT + raw, hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
            raise PermissionError('desktop_signature')
        request = json.loads(raw)
        if set(request) != {'at', 'nonce', 'method', 'params', 'request_id'}:
            raise ValueError('desktop_rpc_fields')
        now = time.time()
        if type(request['at']) is not int or abs(now - request['at']) > 30:
            raise PermissionError('desktop_rpc_expired')
        nonce = request['nonce']
        if not isinstance(nonce, str) or not re.fullmatch('[a-f0-9]{32}', nonce):
            raise PermissionError('desktop_rpc_nonce')
        with self.lock:
            self.nonces = {k: v for k, v in self.nonces.items() if now - v < 60}
            if nonce in self.nonces:
                raise PermissionError('desktop_rpc_replayed')
            if len(self.nonces) >= 2048:
                raise PermissionError('desktop_rpc_busy')
            self.nonces[nonce] = now
        owner = binding['principal']
        if self.authorize(owner) is not True:
            raise PermissionError('desktop_owner_revoked')
        return self.adapter.dispatch(owner, request['method'], request['params'],
                                     request_id=request['request_id'])

    def handle(self, handler):
        from conversation_http import respond
        try:
            if (handler.client_address[0] not in ('127.0.0.1', '::1')
                    or handler.headers.get('Transfer-Encoding')
                    or handler.headers.get('Content-Type') != 'application/json'):
                raise PermissionError('desktop_rpc_transport')
            size = int(handler.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                raise ValueError('desktop_rpc_size')
            handler.connection.settimeout(15)
            raw = handler.rfile.read(size)
            if len(raw) != size:
                raise ValueError('desktop_rpc_incomplete')
            result = self.call(raw, handler.headers.get('X-FS-Desktop-Signature'))
            respond(handler, 200, result)
        except DesktopMethodNotFound:
            respond(handler, 501, {'error': 'desktop_method_not_found'})
        except (PermissionError, FileNotFoundError):
            respond(handler, 403, {'error': 'desktop_access_denied'})
        except LookupError:
            respond(handler, 404, {'error': 'conversation_not_found'})
        except (ValueError, TypeError, KeyError):
            respond(handler, 422, {'error': 'desktop_invalid_request'})
        except RuntimeError:
            respond(handler, 409, {'error': 'desktop_original_state_requires_reconcile'})


class ConversationDesktop:
    def __init__(self, service):
        self.service = service

    def _setup_configuration(self):
        native = getattr(self.service, 'native', None)
        hermes = getattr(self.service, 'hermes', None)
        if (native is None or hermes is None or getattr(native, 'service', None) is not self.service
                or getattr(native, 'hermes', None) is not hermes
                or getattr(native, 'store', None) is not self.service.store):
            return False, 'fs_native_route_unavailable'
        try:
            from fs_inprocess import native_gateway
            from direct_provider import _load_key
            if not callable(native_gateway):
                return False, 'fs_native_route_unavailable'
            # The original FS reader validates its own secret in this process.
            # Do not retain, return, hash or log the value it returns.
            _load_key()
        except ValueError as error:
            reason = str(error)
            return False, reason if reason in ('configuration_missing', 'configuration_invalid') else 'configuration_invalid'
        except (ImportError, OSError, UnicodeError):
            return False, 'configuration_unavailable'
        return True, None

    @staticmethod
    def legacy_request_key(request_id, params, method):
        if isinstance(request_id, str) and re.fullmatch(r'r?[0-9]{1,20}', request_id):
            # Installed Desktop uses a counter RPC id, not modern submission_id.
            # Freeze the exact frame identity; reconnect/retry never mints a random task.
            identity = json.dumps([method, params.get('session_id'), request_id, params.get('text')],
                                  ensure_ascii=False).encode()
            return 'desktop_' + hashlib.sha256(identity).hexdigest()
        return request_id

    def _conversation(self, owner, session_id):
        if not isinstance(session_id, str):
            raise ValueError('desktop_session_required')
        with self.service.store.db() as db:
            row = db.execute('SELECT id FROM conversations WHERE session_id=? AND owner=?',
                             (session_id, owner)).fetchone()
            if row is None:
                raise LookupError('conversation_not_found')
            self.service.store._owned(db, owner, row['id'])
            return row['id']

    def _session_id(self, owner, cid):
        with self.service.store.db() as db:
            return self.service.store._owned(db, owner, cid)['session_id']

    def snapshot(self, owner, sid):
        cid = self._conversation(owner, sid)
        detail = self.service.detail(owner, cid)
        with self.service.store.db() as db:
            rows = {r['id']: r['rowid'] for r in db.execute(
                'SELECT rowid,id FROM turns WHERE conversation_id=?', (cid,))}
        messages = []
        for turn in detail['turns']:
            messages.append(dict(_row_id=rows[turn['turn_id']] * 2, role='user', content=turn['text']))
            if turn['reply']:
                messages.append(dict(_row_id=rows[turn['turn_id']] * 2 + 1,
                                     role='assistant', content=turn['reply']))
        running = any(t['state'] in ('queued', 'dispatching', 'running', 'stopping', 'dispatch_unknown')
                      for t in detail['turns'])
        info = dict(title=detail['title'], stored_session_id=sid, running=running,
                    source='api_server', conversation_id=cid)
        return dict(session_id=sid, session_key=sid, stored_session_id=sid, conversation_id=cid,
                    messages=messages, message_count=len(messages), info=info, running=running,
                    last_seq=detail['last_seq'], status='working' if running else 'idle')

    def dispatch(self, owner, method, params, *, request_id=None):
        # owner is supplied by the authenticated transport, never taken from params.
        self.service._admin(owner)
        if not isinstance(method, str) or not method:
            raise ValueError('desktop_method_invalid')
        if not isinstance(params, dict):
            raise ValueError('desktop_params')
        if any(k in params for k in ('owner', 'user', 'approved', 'authorization')):
            raise ValueError('desktop_client_identity_forbidden')
        if method in ('setup.status', 'setup.runtime_check'):
            configured, reason = self._setup_configuration()
            if method == 'setup.status':
                return dict(provider_configured=configured)
            if not configured:
                return dict(ok=False, error=reason)
            request = getattr(self.service, '_request', None)
            if not callable(request):
                return dict(ok=False, error='fs_runtime_state_unverified')
            try:
                code, capabilities = request('GET', '/v1/capabilities', timeout=5)
            except (OSError, ValueError, TypeError):
                return dict(ok=False, error='fs_runtime_state_unavailable')
            if code != 200 or not isinstance(capabilities, dict):
                return dict(ok=False, error='fs_runtime_state_unavailable')
            runtime = capabilities.get('runtime')
            native = capabilities.get('fs_native_chat')
            materials = capabilities.get('fs_materials')
            if (capabilities.get('object') != 'hermes.api_server.capabilities'
                    or not isinstance(runtime, dict) or runtime.get('mode') != 'server_agent'
                    or not isinstance(native, dict) or native.get('version') != 'native_chat_v1'
                    or any(native.get(key) is not True for key in
                           ('single_post', 'readonly_original_lookup', 'schema_relay'))
                    or not isinstance(materials, dict) or materials.get('verified_pin') is not True):
                return dict(ok=False, error='fs_runtime_capabilities_unverified')
            # Configuration parsed + authenticated original worker route available.
            # This does not perform or certify a provider/model invocation.
            return dict(ok=True)
        if method in ('ping', 'gateway.ping'):
            return {'pong': True}
        if method == 'session.list':
            sessions = []
            for row in self.service.listed(owner)['items']:
                sid = self._session_id(owner, row['conversation_id'])
                sessions.append(dict(id=sid, session_id=sid, stored_session_id=sid,
                    conversation_id=row['conversation_id'], title=row['title'],
                    source='api_server', updated_at=row['updated_at'],
                    last_active=datetime.fromisoformat(row['updated_at']).timestamp()))
            return {'sessions': sessions}
        if method == 'session.create':
            allowed = {'cols', 'source', 'fast', 'profile', 'cwd', 'cwd_explicit', 'reasoning_effort'}
            if set(params) - allowed:
                raise ValueError('desktop_create_params')
            if params.get('profile') not in (None, '', 'default'):
                raise ValueError('desktop_fs_profile')
            if params.get('source') not in (None, 'desktop'):
                raise ValueError('desktop_source')
            # UI layout/cwd describe the client. The original FS service selects its
            # owner profile/workspace and model; these never become execution options.
            cid = self.service.create(owner)['conversation_id']
            return self.snapshot(owner, self._session_id(owner, cid))
        if method in ('session.resume', 'session.activate', 'session.info', 'session.history'):
            return self.snapshot(owner, params.get('session_id'))
        if method == 'session.events':
            cid = self._conversation(owner, params.get('session_id'))
            after = params.get('after', 0)
            return {'events': self.service.events(owner, cid, after)}
        if method == 'prompt.submit':
            if set(params) not in ({'session_id', 'text'}, {'session_id', 'text', 'submission_id'}):
                raise ValueError('desktop_submit_params')
            # Official Desktop freezes submission_id before the first send/reconnect.
            request_id = (params['submission_id'] if 'submission_id' in params else
                          self.legacy_request_key(request_id, params, method))
            if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
                raise ValueError('desktop_request_id_required')
            cid = self._conversation(owner, params['session_id'])
            result = self.service.submit(owner, cid, params['text'], request_id)
            with self.service.store.db() as db:
                turn = db.execute('SELECT rowid,state FROM turns WHERE id=? AND conversation_id=?',
                                  (result['turn_id'], cid)).fetchone()
            state = turn['state']
            status = ('unknown' if state == 'dispatch_unknown' else
                      'terminal' if state in ('completed', 'failed', 'interrupted', 'cancelled') else 'queued')
            return dict(result, session_id=params['session_id'], submission_id=request_id,
                        status=status, user_row_id=turn['rowid'] * 2)
        if method == 'session.interrupt':
            cid = self._conversation(owner, params.get('session_id'))
            request_id = self.legacy_request_key(request_id, params, method)
            if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
                raise ValueError('desktop_request_id_required')
            detail = self.service.detail(owner, cid)
            active = [t for t in detail['turns'] if t['state'] in ('queued', 'running', 'stopping', 'dispatch_unknown')]
            if not active:
                return {'status': 'idle'}
            if not active[-1]['run_id']:
                raise RuntimeError('dispatch_unknown')
            return self.service.stop(owner, cid, active[-1]['run_id'], request_id)
        raise DesktopMethodNotFound('desktop_method_unsupported')
