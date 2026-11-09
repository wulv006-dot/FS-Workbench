"""Forward allowlisted queries through the original authenticated HTTPS entry."""
from datetime import date, datetime, timedelta
import http.client
import json
import re
import socket
from time import monotonic
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from .catalog import ValidationError, permit
from .redaction import redact_data


class BackendError(RuntimeError):
    def __init__(self, code, status_code=503, retry_after=None):
        self.code, self.status_code = code, status_code
        self.retry_after = retry_after
        super().__init__(code)


def _secret_fields(value):
    if isinstance(value, dict):
        forbidden = {'token', 'access_token', 'refresh_token', 'id_token', 'api_key', 'apikey', 'secret', 'client_secret', 'password', 'password_hash', 'passwordhash', 'passwd', 'cookie', 'session_cookie', 'authorization', 'private_key', 'csrf', 'csrf_token'}
        return any(key.lower().replace('-', '_') in forbidden or _secret_fields(child) for key, child in value.items())
    return isinstance(value, list) and any(_secret_fields(child) for child in value)


class Backend:
    def __init__(self, catalog, base_url, authorize=None, transport=None, knowledge=None, players=None):
        parsed = urlsplit(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('fixed_https_origin_required')
        self.catalog, self.base_url = catalog, base_url.rstrip('/')
        self.authorize = authorize or catalog.authorize
        self.transport = transport or self._request
        self.knowledge = knowledge
        self.players = players

    def _request(self, method, target, headers, body, limits):
        origin = urlsplit(self.base_url)
        deadline = monotonic() + limits['timeout_seconds']
        connection = http.client.HTTPSConnection(origin.hostname, origin.port or 443, timeout=limits['timeout_seconds'])
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                raise BackendError('upstream_redirect_rejected', 502)
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise BackendError('unsupported_response_encoding', 502)
            size = response.getheader('Content-Length')
            if size is not None and (not size.isdigit() or int(size) > limits['response_bytes']):
                raise BackendError('upstream_response_too_large', 502)
            chunks, received = [], 0
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise BackendError('upstream_timeout', 504)
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, limits['response_bytes'] + 1 - received))
                received += len(chunk)
                if received > limits['response_bytes']:
                    raise BackendError('upstream_response_too_large', 502)
                if not chunk:
                    break
                chunks.append(chunk)
            return response.status, b''.join(chunks)
        except (TimeoutError, socket.timeout):
            raise BackendError('upstream_timeout', 504) from None
        except (OSError, http.client.HTTPException):
            raise BackendError('upstream_unavailable') from None
        finally:
            connection.close()

    def query(self, principal, operation, arguments):
        row = self.catalog.operation(operation)
        from .catalog import validate
        validate(arguments, row['input_schema'])
        if row['method'] == 'GET' and any(isinstance(value, str) and
                re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', value) for value in arguments.values()):
            raise ValidationError('email_requires_private_post')
        if row.get('adapter') == 'players':
            if self.players is None:
                raise BackendError('players_adapter_not_configured', 503)
            value = self.players.query(principal, operation, arguments)
            return {'operation': operation, **value,
                    'provenance': {**row['provenance'], **value['provenance']}}
        if row.get('adapter') == 'knowledge':
            if self.knowledge is None:
                raise BackendError('published_knowledge_not_configured', 503)
            if operation == 'knowledge.index':
                value = self.knowledge.index(principal, **arguments)
            elif operation == 'knowledge.read':
                value = self.knowledge.read(principal, **arguments)
            else:
                raise BackendError('unknown_knowledge_operation', 503)
            if _secret_fields(value):
                raise BackendError('credential_material_in_response', 502)
            return {'operation': operation, 'status_code': 200, 'data': redact_data(value),
                    'provenance': row['provenance']}
        parameters = {**row.get('fixed', {}), **arguments}
        if row.get('response_adapter') == 'sales':
            parameters = {}
        path = row['path']
        for key in row.get('path_parameters', []):
            path = path.replace('{' + key + '}', str(parameters.pop(key)))
        if not path.startswith('/') or path.startswith('//') or re.search(r'[\\\r\n?#]', path) or any(part in ('.', '..') for part in path.split('/')):
            raise ValidationError('invalid_path_parameter')
        permit(self.authorize, principal, path, row['method'])
        cookie = principal.session_cookie
        if not isinstance(cookie, str) or not cookie or '\r' in cookie or '\n' in cookie or len(cookie) > 8192:
            raise BackendError('invalid_saved_session', 401)
        if row.get('date_contract') == 'live_orders':
            try:
                start, end = date.fromisoformat(arguments['start']), date.fromisoformat(arguments['end_exclusive'])
                today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
                if not 1 <= (end-start).days <= 28 or start < today-timedelta(days=365) or end > today+timedelta(days=1):
                    raise ValueError()
            except ValueError:
                raise ValidationError('invalid_live_query') from None
        headers = {'Cookie': cookie, 'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        body = None
        if row['method'] == 'POST':
            body = json.dumps(parameters, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
            headers.update({'Content-Type': 'application/json', 'Origin': self.base_url, 'Sec-Fetch-Site': 'same-origin'})
            target = path
        else:
            target = path + ('?' + urlencode(parameters) if parameters else '')
        if len(body or target.encode()) > row['limits']['request_bytes']:
            raise ValidationError('request_too_large')
        try:
            status, raw = self.transport(row['method'], target, headers, body, row['limits'])
        except BackendError:
            raise
        except Exception:
            raise BackendError('upstream_unavailable') from None
        if len(raw) > row['limits']['response_bytes']:
            raise BackendError('upstream_response_too_large', 502)
        if not 200 <= status < 300:
            code, retry = 'upstream_rejected', None
            try:
                detail = json.loads(raw)
                if isinstance(detail, dict):
                    candidate = detail.get('error')
                    if isinstance(candidate, str) and re.fullmatch('[a-z][a-z0-9_]{0,79}', candidate):
                        code = candidate
                    value = detail.get('retryAfter')
                    if type(value) in (int, float) and 0 <= value <= 86400:
                        retry = value
            except (ValueError, UnicodeError):
                pass  # Only structured error codes are returned; raw failure bodies may contain secrets.
            raise BackendError(code, status if 400 <= status <= 599 else 502, retry)
        try:
            if row.get('response_format') == 'html_text':
                from .documents import parse_handbook
                value = parse_handbook(raw)
            else:
                value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise BackendError('invalid_upstream_document' if row.get('response_format') == 'html_text'
                               else 'invalid_upstream_json', 502) from None
        fields = row.get('response_fields')
        if fields is not None:
            if not isinstance(value, dict):
                raise BackendError('unexpected_upstream_shape', 502)
            value = {key: value[key] for key in fields if key in value}
        if row.get('response_adapter') == 'g2g':
            from .g2g import project
            value = project(value)
        if row.get('response_adapter') == 'accounts':
            from .accounts import project
            value = project(value, row.get('response_view', 'overview'))
        if row.get('response_adapter') == 'gallery':
            from .gallery import project_gallery_state
            value = project_gallery_state(value)
        if row.get('response_adapter') == 'sales':
            from .sales import project
            value = project(value, raw, arguments)
        if row.get('response_adapter') == 'evolutions':
            from .evolutions import project
            value = project(value)
        if row.get('response_adapter') == 'tracking':
            from .tracking import project
            value = project(value, row['fixed']['view'])
        if _secret_fields(value):
            raise BackendError('credential_material_in_response', 502)
        permit(self.authorize, principal, path, row['method'])
        return {'operation': operation, 'status_code': status, 'data': redact_data(value),
                'provenance': {**row['provenance'], 'path': path, 'method': row['method'],
                               **({'response_fields': fields} if fields is not None else {})}}
