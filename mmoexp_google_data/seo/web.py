"""Loopback FS endpoint: existing session verification, frozen data, local controls."""
import argparse
import http.client
import json
import re
import sqlite3
import sys
import threading
from typing import NamedTuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .api import Service
from .ai_policy import Actor, PolicyStore
from .contracts import GAMES, game

PREFIX = '/dashboard/analytics/seo/api/v1/'


class Csv(NamedTuple):
    filename: str
    text: str


def verify(cookie, method, path):
    # Reuse FS cookie sanitization; its fixed users-page authorization is not reused.
    if '/opt/fs-hermes-fc' not in sys.path:
        sys.path.insert(0, '/opt/fs-hermes-fc')
    from admin_live_session import session_cookie
    cookie = session_cookie(cookie)
    if not cookie:
        return 401, None
    connection = http.client.HTTPConnection('127.0.0.1', 8895, timeout=3)
    try:
        connection.request('GET', '/verify?group=dashboard', headers={
            'Cookie': cookie, 'X-Original-Method': method, 'X-Original-URI': path})
        response = connection.getresponse()
        if response.status in (401, 403):
            return response.status, None
        users = [v for k,v in response.getheaders() if k.lower() == 'x-auth-user']
        if response.status != 200 or len(users) != 1 or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,128}', users[0]):
            return 503, None
        return 200, users[0]
    except (OSError, http.client.HTTPException):
        return 503, None
    finally:
        connection.close()


class LocalPolicy:
    def __init__(self, root):
        self.root = root

    def read(self):
        return PolicyStore(self.root).read()

    def update(self, *args):
        return PolicyStore(self.root).update(*args)


class Application:
    def __init__(self, root, control_root, authenticate=verify):
        self.service, self.authenticate = Service(root, LocalPolicy(control_root)), authenticate

    def handle(self, method, target, headers, body):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith(PREFIX):
            return 404, dict(error='NOT_FOUND')
        if method not in ('GET', 'PATCH'):
            return 405, dict(error='METHOD_NOT_ALLOWED')
        headers = {k.lower():v for k,v in headers.items()}
        try:
            query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8) if parsed.query else []
            if len(query) != len(dict(query)):
                raise ValueError('DUPLICATE_QUERY')
            host = headers.get('host','')
            same_origin = bool(re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?',host)) and headers.get('origin') == 'https://'+host
            if method == 'PATCH' and (not same_origin or headers.get('content-type','').split(';')[0] != 'application/json'):
                return 403, dict(error='CSRF_REQUIRED')
            status, subject = self.authenticate(headers.get('cookie'), method, parsed.path)
            if status != 200 or not subject:
                return status if status != 200 else 503, dict(error='FS_SESSION_REQUIRED')
            manage = method == 'PATCH'
            if method == 'GET' and parsed.path == PREFIX+'ai-policy':
                status, editor = self.authenticate(headers.get('cookie'), 'PATCH', parsed.path)
                manage = status == 200 and editor == subject
            actor = Actor(subject, GAMES, manage, False)
            internal = '/api/seo/v1/' + parsed.path[len(PREFIX):]
            export = re.fullmatch(r'/api/seo/v1/snapshots/(seo-\d{4}-\d{2}-\d{2})/export\.csv',internal)
            if method == 'GET' and export:
                if set(dict(query))!={'game'}:
                    raise ValueError('INVALID_EXPORT_QUERY')
                scope=game(dict(query)['game'])
                if scope not in actor.games:
                    return 403,dict(error='SEO_EXPORT_DENIED')
                return 200,Csv(export[1]+'-'+scope+'.csv',''.join(self.service.export(export[1],scope,actor)))
            if len(body) > 16384:
                raise ValueError('POLICY_BODY_TOO_LARGE')
            data = json.loads(body) if method == 'PATCH' else None
            return self.service.handle(method, internal, dict(query), actor, body=data, mutation_authorized=method == 'PATCH')
        except FileNotFoundError:
            return 410,dict(error='SNAPSHOT_EXPIRED')
        except (OSError, sqlite3.Error, ImportError):
            return 503, dict(error='SEO_LOCAL_COMPONENT_UNAVAILABLE')
        except (ValueError, TypeError, UnicodeError):
            return 422, dict(error='INVALID_SEO_REQUEST')


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def do_GET(self):
        self.respond()

    def do_PATCH(self):
        self.respond()

    def respond(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Transfer-Encoding') or not 0 <= length <= 16384:
                raise ValueError('INVALID_LENGTH')
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('INCOMPLETE_BODY')
            status, value = self.server.application.handle(self.command, self.path, self.headers, body)
        except (ValueError, OSError):
            status, value = 422, dict(error='INVALID_SEO_REQUEST')
        payload = ('\ufeff'+value.text).encode('utf-8') if isinstance(value,Csv) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/csv; charset=utf-8' if isinstance(value,Csv) else 'application/json; charset=utf-8')
        if isinstance(value,Csv):
            self.send_header('Content-Disposition','attachment; filename="'+value.filename+'"')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass  # Session cookies and query bodies never enter application logs.


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, application, readers):
        if type(port) is not int or not 1024 <= port <= 65535 or type(readers) is not int or not 1 <= readers <= 32:
            raise ValueError('SEO_WEB_LIMIT_INVALID')
        self.application, self.slots = application, threading.BoundedSemaphore(readers)
        super().__init__(('127.0.0.1', port), Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, *args):
        try:
            super().process_request_thread(*args)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    config = json.loads(Path(parser.parse_args().config).read_text(encoding='utf-8'))
    app = Application(config['data_root'], config['control_root'])
    with Server(config['web_port'], app, config['web_readers']) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
