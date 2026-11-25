"""One Order session owner with an in-memory HTTP cookie jar."""
from functools import lru_cache
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import stat
import struct
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import (HTTPCookieProcessor, HTTPRedirectHandler,
                            ProxyHandler, Request, build_opener)

SOCKETS = ('/run/fs-order-session/session.sock',
           '/var/lib/fc27-cloud/browser/lootbar/fs-order-session.sock',
           '/opt/madden-workbench/.fs-order-session.sock',
           '/opt/d4follow/_p2pah_srv/.fs-order-session.sock')
ALLOWED_UIDS = {0, 994, 11027}

BASE = 'https://order.p2pah.cn'
PROBE_PATH = '/admin/index/index.html'
PRIVATE_CONFIG = '/opt/mlb-admin-write/_cred_order.json'
REQUIRED_COOKIES = {'PHPSESSID', 'user', 'admin_username'}
LOGIN_PATHS = {'/admin', '/admin/', '/login.html', '/admin/public/login.html'}
PASSWORD_INPUT = re.compile(r'<input[^>]+type\s*=\s*["\']?password', re.I)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def identity_ok(status, url, body):
    target = urlsplit(url)
    return (status == 200 and target.scheme == 'https'
            and target.hostname == 'order.p2pah.cn' and target.path == PROBE_PATH
            and bool(re.search(r'href=["\']/admin/public/logout\.html["\']', body, re.I))
            and not PASSWORD_INPUT.search(body))


def read_private_config():
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(PRIVATE_CONFIG, flags), encoding='utf-8') as source:
        metadata = os.fstat(source.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077):
            raise ValueError('order_private_config_permissions')
        config = json.load(source)
    username = config.get('P2PAH_ORDER_USERNAME')
    password = config.get('P2PAH_ORDER_PASSWORD')
    if not all(isinstance(value, str) and value for value in (username, password)):
        raise ValueError('order_private_config_invalid')
    return username, password


def ocr_attempts():
    return max(1, min(10, int(os.environ.get('FC27_OCR_ATTEMPTS', '5'))))


@lru_cache(maxsize=1)
def ocr_model():
    import ddddocr
    return ddddocr.DdddOcr(show_ad=False)


def recognize(png):
    try:
        from shared_backend_session.manual_captcha import CODE_RE, _clean
    except ModuleNotFoundError as error:
        if error.name != 'shared_backend_session':
            raise
        from manual_captcha import CODE_RE, _clean
    code = _clean(ocr_model().classification(png))
    return code if CODE_RE.fullmatch(code) else None


class Session:
    def __init__(self, probe=None):
        self.lock = threading.Lock()
        self.checked = 0
        self.result = self.failure('not_checked')
        self.probing = False
        self.probe_seconds = None
        self.login_attempts = 0
        self.login_blocked = None
        self.jar = CookieJar()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.jar))
        self.probe = probe or self.http_probe

    @staticmethod
    def failure(error):
        return {'ready': False, 'cookies': [], 'error': error}

    def request(self, path, deadline, form=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': BASE + '/admin'}
        data = None
        if form is not None:
            headers.update({'Origin': BASE, 'X-Requested-With': 'XMLHttpRequest'})
            data = urlencode(form).encode()
        req = Request(BASE + path, data=data, headers=headers)
        try:
            response = self.opener.open(req, timeout=min(8, remaining))
        except HTTPError as error:
            with error:
                return error.code, error.headers, b''
        with response:
            payload = response.read(1048577)
            if len(payload) > 1048576:
                raise ValueError('order_response_too_large')
            return response.status, response.headers, payload

    def check_identity(self, deadline):
        try:
            status, headers, payload = self.request(PROBE_PATH, deadline)
        except OSError:
            return 'order_probe_transport_unavailable'
        if status == 429 or status >= 500:
            return 'order_probe_transport_unavailable'
        body = payload.decode('utf-8', errors='replace')
        if identity_ok(status, BASE + PROBE_PATH, body):
            return 'valid'
        if status in (301, 302, 303, 307, 308):
            target = urlsplit(urljoin(BASE + PROBE_PATH, headers.get('Location', '')))
            if (target.scheme == 'https' and target.netloc == 'order.p2pah.cn'
                    and target.path in LOGIN_PATHS):
                return 'expired'
        if status == 200 and PASSWORD_INPUT.search(body):
            return 'expired'
        return 'order_identity_unverified'

    def cookie_rows(self):
        self.jar.clear_expired_cookies()
        return [
            {'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain,
             'path': cookie.path, 'secure': cookie.secure,
             'httpOnly': any(name.lower() == 'httponly' for name in cookie._rest)}
            for cookie in self.jar if cookie.domain.lstrip('.') == 'order.p2pah.cn'
        ]

    def renew(self, deadline):
        try:
            username, password = read_private_config()
            attempts = ocr_attempts()
        except (OSError, ValueError, TypeError, AttributeError):
            return 'order_private_config_unavailable'
        for _ in range(attempts):
            self.jar.clear()
            status, _, image = self.request(
                '/new_captcha.html?height=32&width=150&font_size=18', deadline)
            if (status != 200 or not image.startswith(b'\x89PNG\r\n\x1a\n')
                    or 'PHPSESSID' not in {row['name'] for row in self.cookie_rows()}):
                return 'order_captcha_unavailable'
            try:
                code = recognize(image)
            except Exception:
                return 'order_captcha_ocr_unavailable'
            if not code:
                continue
            form = {'username': username, 'password': password, 'captcha': code,
                    '_captcha_id': '', 'redirect': ''}
            self.login_attempts += 1
            try:
                status, _, payload = self.request('/admin/public/dologin.html', deadline, form)
                reply = json.loads(payload) if status == 200 else None
            except (OSError, ValueError):
                reply = None
            if not isinstance(reply, dict):
                self.login_blocked = 'order_login_outcome_unverified'
                return self.login_blocked
            if type(reply.get('code')) is int and reply['code'] == 1:
                return self.check_identity(deadline)
            message = reply.get('msg')
            if (not isinstance(message, str)
                    or not re.fullmatch(r'(?:图形)?验证码(?:输入)?(?:错误|不正确|不匹配|已过期)[。！!！]?', message.strip())):
                self.login_blocked = 'order_login_rejected'
                return self.login_blocked
        return 'order_captcha_attempts_exhausted'

    def http_probe(self):
        deadline = time.monotonic() + 33
        identity = self.check_identity(deadline)
        if identity == 'expired':
            identity = self.login_blocked or self.renew(deadline)
        if identity != 'valid':
            return self.failure('order_identity_unverified' if identity == 'expired' else identity)
        rows = self.cookie_rows()
        if not REQUIRED_COOKIES.issubset(row['name'] for row in rows if row['value']):
            return self.failure('order_session_cookies_missing')
        return {'ready': True, 'cookies': rows, 'error': None}



    def get(self):
        with self.lock:
            if not self.checked or time.monotonic() - self.checked >= 20:
                started = time.monotonic()
                self.probing = True
                try:
                    self.result = self.probe()
                except Exception:
                    self.result = self.failure('order_probe_unavailable')
                finally:
                    self.checked = time.monotonic()
                    self.probe_seconds = round(self.checked - started, 3)
                    self.probing = False
            return self.result

    def health(self):
        # Health never waits behind an upstream request; cookie issuance still uses get().
        age = time.monotonic() - self.checked if self.checked else None
        fresh = age is not None and age <= 45
        return {'service': 'fs-order-session', 'ready': fresh and self.result.get('ready') is True,
                'last_error': self.result.get('error') if fresh or age is None else 'order_probe_stale',
                'checking': self.probing, 'verified_age_seconds': round(age, 1) if age is not None else None,
                'probe_seconds': self.probe_seconds, 'probe_path': '/admin/index/index.html', 'login_attempts': self.login_attempts}


SESSION = Session()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in ALLOWED_UIDS or self.rfile.readline(64) != b'cookies\n':
            return
        self.wfile.write(json.dumps(SESSION.get()).encode() + b'\n')


class UnixServer(socketserver.ThreadingMixIn, getattr(socketserver, 'UnixStreamServer', socketserver.TCPServer)):
    daemon_threads = True


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/health':
            self.send_error(404)
            return
        result = SESSION.health()
        body = json.dumps(result).encode()
        self.send_response(200 if result.get('ready') else 503)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    servers = []
    try:
        def upkeep():
            while True:
                SESSION.get()
                time.sleep(5)
        threading.Thread(target=upkeep, daemon=True).start()
        Path('/run/fs-order-session').mkdir(mode=0o755, exist_ok=True)
        os.chmod('/run/fs-order-session', 0o755)
        for path in SOCKETS:
            if Path(path).exists():
                if not Path(path).is_socket():
                    raise RuntimeError('socket_path_occupied')
                Path(path).unlink()
            server = UnixServer(path, Handler)
            os.chown(path, 0, 11027)
            # SO_PEERCRED enforces the uid allowlist, including fc27api outside this group.
            os.chmod(path, 0o666)
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        ThreadingHTTPServer(('127.0.0.1', 8768), Health).serve_forever()
    finally:
        for server in servers:
            server.server_close()
            Path(server.server_address).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
