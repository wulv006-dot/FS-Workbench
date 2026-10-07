"""Explicit boot hook for native Handler. Import does not import/start the portal."""
import json
import time
from pathlib import Path
import types
from urllib.parse import parse_qs, urlsplit
from runtime import build, core, HERE


class Bridge:
    def __init__(self, app, adapter, portal):
        self.app, self.adapter, self.portal = app, adapter, portal

    @staticmethod
    def send(handler, code, body=b'', ctype='text/plain; charset=utf-8', headers=None):
        output = list(headers or [])
        if getattr(handler, 'close_connection', False) and not any(k.lower() == 'connection' for k, v in output):
            output.append(('Connection', 'close'))
        return handler._send(code, body, ctype, headers=output)

    def legacy_logout(self, handler):
        """Confirmation only; the sole mutating logout is Origin+CSRF API logout."""
        if handler.command in ('GET', 'HEAD'):
            return handler._redirect(core.PREFIX + '/')
        handler.close_connection = True
        # A refusal must not race closing TCP against the legitimate request
        # body. Drain only an unambiguous, bounded Content-Length; never use
        # the body for authentication or dispatch the historical logout.
        headers = getattr(handler, 'headers', {})
        lengths = headers.get_all('Content-Length', []) if hasattr(headers, 'get_all') else [headers.get('Content-Length', '0')]
        if not lengths:
            lengths = ['0']
        if headers.get('Transfer-Encoding') or len(lengths) != 1 or not str(lengths[0]).isascii() or not str(lengths[0]).isdecimal():
            return self.send(handler, 400, 'invalid framing')
        digits = str(lengths[0]).lstrip('0') or '0'
        if len(digits) > 4 or (len(digits) == 4 and digits > '4096'):
            return self.send(handler, 400, 'invalid framing')
        length = int(digits)
        if length:
            connection = handler.connection
            previous_timeout = connection.gettimeout()
            deadline = time.monotonic() + 1.0
            remaining = length
            complete = True
            try:
                while remaining:
                    budget = deadline - time.monotonic()
                    if budget <= 0:
                        raise TimeoutError('request body deadline')
                    connection.settimeout(budget)
                    chunk = handler.rfile.read1(remaining)
                    if not chunk:
                        raise ValueError('incomplete request body')
                    remaining -= len(chunk)
            except (OSError, ValueError):
                complete = False
            finally:
                connection.settimeout(previous_timeout)
            if not complete:
                return self.send(handler, 400, 'incomplete request body')
        return self.send(handler, 405, 'Use CSRF protected /__auth/access/api/logout')

    def verify(self, handler, group=''):
        try:
            cookies = self.portal.parse_cookies(handler.headers.get('Cookie', ''))
            code, headers = self.adapter.verify(cookies,
                handler.headers.get('X-Original-Method', 'GET'),
                handler.headers.get('X-Original-URI', '/'), group)
            return self.send(handler, code, 'OK' if code == 200 else 'access denied', headers=list(headers.items()))
        except Exception:
            return self.send(handler, 503, 'verification unavailable')

    def route(self, handler, old_route):
        if handler.command not in ('GET', 'HEAD'):
            # Rejected legacy writes/framing must not leave unread bodies on a
            # persistent connection to be parsed as another request.
            handler.close_connection = True
        parsed = urlsplit(handler.path)
        path = parsed.path
        # Current nginx strips /__auth/, public JS URLs keep that prefix.
        # Match the actual old _route rstrip('/') normalization ONLY for legacy
        # logout. Keep the fixed static/API path matching exact and unchanged.
        if (path.rstrip('/') or '/') == '/logout':
            return self.legacy_logout(handler)
        if path == '/status' and core.COOKIE in self.portal.parse_cookies(handler.headers.get('Cookie', '')):
            return handler._redirect(core.PREFIX + '/')
        if path == '/access':
            return handler._redirect(core.PREFIX + '/')
        if not path.startswith('/access/'):
            return old_route(handler)
        static = {'/access/': ('index.html', 'text/html; charset=utf-8'),
            '/access/app.js': ('app.js', 'text/javascript; charset=utf-8'),
            '/access/base.css': ('base.css', 'text/css; charset=utf-8'),
            '/access/access.css': ('access.css', 'text/css; charset=utf-8')}
        if path in static and handler.command in ('GET', 'HEAD'):
            name, mime = static[path]
            return self.send(handler, 200, (HERE / 'web' / name).read_bytes(), mime,
                headers=[('X-Content-Type-Options', 'nosniff'), ('Content-Security-Policy',
                    "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")])
        if not path.startswith('/access/api/'):
            return self.send(handler, 404, 'not found')
        try:
            length = int(handler.headers.get('Content-Length', '0'))
            if not 0 <= length <= 4096 or handler.headers.get('Transfer-Encoding'):
                return self.send(handler, 400, 'invalid framing')
            cookies = self.portal.parse_cookies(handler.headers.get('Cookie', ''))
            code, result, headers = self.app.dispatch(handler.command,
                handler.path[len('/access'):], headers=dict(handler.headers), cookies=cookies,
                body=handler.rfile.read(length), client=handler.ip)
            output = []
            for key, value in headers.items():
                for item in value if isinstance(value, list) else [value]:
                    output.append((key, item))
            return self.send(handler, code, json.dumps(result, ensure_ascii=False),
                'application/json; charset=utf-8', headers=output)
        except Exception:
            return self.send(handler, 503, 'access service unavailable')


def install(portal, origin, *, isolated=False):
    """Reviewed caller invokes once after native config checks, before listener.

    Must run under single writer release; no production caller is delivered here.
    Freeze function references before replacing the shared read_token global.
    """
    if hasattr(portal, '_registration_bridge'):
        raise ValueError('registration boot hook already installed')
    view = types.SimpleNamespace(**portal.__dict__)
    store, adapter, app = build(portal.CFG['data_dir'], view, origin, isolated=isolated)
    bridge = Bridge(app, adapter, view)
    old_route = portal.Handler._route
    portal.Handler._route = lambda handler: bridge.route(handler, old_route)
    portal.Handler._do_verify = lambda handler, group='': bridge.verify(handler, group)
    # Defense in depth for every old _route alias or any internal direct caller;
    # the historical cookie-clear/FC logout implementation is never reachable.
    portal.Handler._do_logout = lambda handler, next_q='': bridge.legacy_logout(handler)
    portal.read_token = adapter.ledger_read_token
    portal._registration_bridge = bridge
    return store, adapter, app
