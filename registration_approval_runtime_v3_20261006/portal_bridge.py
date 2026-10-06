"""Explicit boot hook for native Handler. Import does not import/start the portal."""
import json
from pathlib import Path
import types
from urllib.parse import parse_qs, urlsplit
from runtime import build, core, HERE


class Bridge:
    def __init__(self, app, adapter, portal):
        self.app, self.adapter, self.portal = app, adapter, portal

    def legacy_logout(self, handler):
        """Confirmation only; the sole mutating logout is Origin+CSRF API logout."""
        if handler.command in ('GET', 'HEAD'):
            return handler._redirect(core.PREFIX + '/')
        handler.close_connection = True
        return handler._send(405, 'Use CSRF protected /__auth/access/api/logout')

    def verify(self, handler, group=''):
        try:
            cookies = self.portal.parse_cookies(handler.headers.get('Cookie', ''))
            code, headers = self.adapter.verify(cookies,
                handler.headers.get('X-Original-Method', 'GET'),
                handler.headers.get('X-Original-URI', '/'), group)
            return handler._send(code, 'OK' if code == 200 else 'access denied', headers=list(headers.items()))
        except Exception:
            return handler._send(503, 'verification unavailable')

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
            return handler._send(200, (HERE / 'web' / name).read_bytes(), mime,
                headers=[('X-Content-Type-Options', 'nosniff'), ('Content-Security-Policy',
                    "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")])
        if not path.startswith('/access/api/'):
            return handler._send(404, 'not found')
        try:
            length = int(handler.headers.get('Content-Length', '0'))
            if not 0 <= length <= 4096 or handler.headers.get('Transfer-Encoding'):
                return handler._send(400, 'invalid framing')
            cookies = self.portal.parse_cookies(handler.headers.get('Cookie', ''))
            code, result, headers = self.app.dispatch(handler.command,
                handler.path[len('/access'):], headers=dict(handler.headers), cookies=cookies,
                body=handler.rfile.read(length), client=handler.ip)
            output = []
            for key, value in headers.items():
                for item in value if isinstance(value, list) else [value]:
                    output.append((key, item))
            return handler._send(code, json.dumps(result, ensure_ascii=False),
                'application/json; charset=utf-8', headers=output)
        except Exception:
            return handler._send(503, 'access service unavailable')


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
