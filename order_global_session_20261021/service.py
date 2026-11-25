"""One Order session owner with an in-memory HTTP cookie jar."""
from collections import deque
from html.parser import HTMLParser
from http.client import HTTPException, HTTPResponse, HTTPSConnection, IncompleteRead
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BufferedReader, RawIOBase
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import (HTTPCookieProcessor, HTTPRedirectHandler, HTTPSHandler,
                            ProxyHandler, Request, build_opener)

SOCKETS = ('/run/fs-order-session/session.sock',
           '/var/lib/fc27-cloud/browser/lootbar/fs-order-session.sock',
           '/opt/madden-workbench/.fs-order-session.sock',
           '/opt/d4follow/_p2pah_srv/.fs-order-session.sock')
ALLOWED_UIDS = {0, 994, 11027}

BASE = 'https://order.p2pah.cn'
PROBE_PATH = '/admin/index/index.html'
PRIVATE_CONFIG = '/opt/mlb-admin-write/_cred_order.json'
# The live 187 session exports only PHPSESSID at path / and every consumer works
# with it; the authenticated page check is the identity proof.
REQUIRED_COOKIES = {'PHPSESSID'}
LOGIN_PATHS = {'/admin', '/admin/', '/login.html', '/admin/public/login.html'}
LOGIN_WINDOW = 300
# /admin/index/index.html is ~250 KB and takes 10-20 s to stream from 187.
PROBE_TIMEOUT = 90
# Login page redirects (~11 s), captcha, OCR, dologin and the identity check.
RENEW_TIMEOUT = 180
# While a probe runs, hand out the last ready result if it is this recent, so
# consumers never queue behind a slow Order page.
STALE_SERVE = 120
WAIT_TIMEOUT = 34
RESPONSE_LIMIT = 1048576
OCR_COMMAND = (sys.executable, str(Path(__file__).resolve()), '--recognize-captcha')
LOGIN_POST_PATH = '/admin/public/dologin.html'
CAPTCHA_PATH = '/new_captcha.html'
# Order rejects dologin as "非法登录!" unless this page was opened in the same session.
LOGIN_PAGE_PATH = '/login.html'
LOGIN_PAGE_HOPS = 4
# Order regularly needs 2-3 s per response and sometimes more; the total
# probe/renewal deadline still bounds the whole operation.
REQUEST_TIMEOUT = 15
LOGOUT_PATH = '/admin/public/logout.html'
CAPTCHA_CODE = re.compile(r'[0-9A-Za-z]{3,6}')


def log_event(event, **fields):
    # journald picks up stderr; never pass credentials, captcha codes or cookie values.
    try:
        print(json.dumps(dict(event=event, **fields), ensure_ascii=False), file=sys.stderr, flush=True)
    except Exception:
        pass


class RequestNotSent(TimeoutError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DeadlineReader(RawIOBase):
    def __init__(self, stream, deadline):
        super().__init__()
        self.stream = stream
        self.raw = stream.makefile('rb', buffering=0)
        self.deadline = deadline

    def makefile(self, mode):
        # HTTPResponse reads headers and chunk framing through the same buffer.
        return BufferedReader(self)

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        self.stream.settimeout(min(REQUEST_TIMEOUT, remaining))
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class OrderHTTPSConnection(HTTPSConnection):
    def __init__(self, host, request, **kwargs):
        super().__init__(host, **kwargs)
        self.deadline = request.deadline

    def connect(self):
        try:
            super().connect()
        except OSError as error:
            raise RequestNotSent('order_login_transport_unavailable') from error
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RequestNotSent('order_login_deadline')
        self.sock.settimeout(min(REQUEST_TIMEOUT, remaining))

    def response_class(self, stream, **kwargs):
        return HTTPResponse(DeadlineReader(stream, self.deadline), **kwargs)


class OrderHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        def connection(host, **kwargs):
            return OrderHTTPSConnection(host, req, **kwargs)

        return self.do_open(connection, req, context=self._context)


class OrderPage(HTMLParser):
    def __init__(self, body, url):
        super().__init__()
        self.url = url
        self.logout = False
        self.password = False
        self.login = False
        self.feed(body)

    def matches(self, value, path):
        if not value:
            return False
        try:
            target = urlsplit(urljoin(self.url, value))
        except ValueError:
            return False
        return target.scheme == 'https' and target.netloc == 'order.p2pah.cn' and target.path == path

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'a' and self.matches(attrs.get('href'), LOGOUT_PATH):
            self.logout = True
        elif tag == 'input' and (attrs.get('type') or '').lower() == 'password':
            self.password = True
        elif ((tag == 'form' and self.matches(attrs.get('action'), LOGIN_POST_PATH))
              or (tag == 'img' and self.matches(attrs.get('src'), CAPTCHA_PATH))):
            self.login = True


def page_identity(status, url, body):
    target = urlsplit(url)
    if (status != 200 or target.scheme != 'https'
            or target.netloc != 'order.p2pah.cn' or target.path != PROBE_PATH):
        return 'order_identity_unverified'
    page = OrderPage(body, url)
    if page.logout and not (page.password or page.login):
        return 'valid'
    if not page.logout and page.password and page.login:
        return 'expired'
    return 'order_identity_unverified'


def identity_ok(status, url, body):
    return page_identity(status, url, body) == 'valid'


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


def ocr_model():
    import ddddocr
    return ddddocr.DdddOcr(show_ad=False)


def recognize_in_worker(png):
    value = ocr_model().classification(png)
    code = re.sub(r'[^0-9A-Za-z]', '', value) if isinstance(value, str) else ''
    return code if CAPTCHA_CODE.fullmatch(code) else None


def recognize(png, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(OCR_COMMAND, 0)
    # subprocess.run kills and reaps a stalled native OCR worker on timeout.
    result = subprocess.run(OCR_COMMAND, input=png, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=True, timeout=remaining)
    code = result.stdout.decode('ascii').strip()
    return code if CAPTCHA_CODE.fullmatch(code) else None


class Session:
    def __init__(self, probe=None):
        self.lock = threading.Lock()
        self.checked = 0
        self.result = self.failure('not_checked')
        self.probing = False
        self.probe_seconds = None
        self.login_attempts = 0
        self.login_posts = deque()
        self.login_failures = 0
        self.login_retry_after = 0
        self.login_blocked = None
        self.jar = CookieJar()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), OrderHTTPSHandler(),
                                   HTTPCookieProcessor(self.jar))
        self.probe = probe or self.http_probe

    @staticmethod
    def failure(error):
        return {'ready': False, 'cookies': [], 'error': error}

    def request(self, path, deadline, form=None, referer='/admin'):
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': BASE + referer}
        data = None
        if form is not None:
            headers.update({'Origin': BASE, 'X-Requested-With': 'XMLHttpRequest'})
            data = urlencode(form).encode()
        req = Request(BASE + path, data=data, headers=headers)
        req.deadline = deadline
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RequestNotSent('order_login_deadline')
        post_maybe_sent = form is not None
        try:
            try:
                response = self.opener.open(req, timeout=min(REQUEST_TIMEOUT, remaining))
            except HTTPError as error:
                with error:
                    return error.code, error.headers, b''
            except URLError as error:
                if isinstance(error.reason, RequestNotSent):
                    post_maybe_sent = False
                    raise error.reason from error
                raise
            with response:
                expected = getattr(response, 'length', None)
                payload = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    chunk = response.read1(min(65536, RESPONSE_LIMIT + 1 - len(payload)))
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > RESPONSE_LIMIT:
                        raise ValueError('order_response_too_large')
                if expected is not None and len(payload) != expected:
                    raise IncompleteRead(b'', expected - len(payload))
                return response.status, response.headers, bytes(payload)
        finally:
            if post_maybe_sent:
                # Age the budget from completion so network delay cannot let an
                # attempt fall out of the window before its actual POST would.
                self.login_posts.append(time.monotonic())
                self.login_attempts += 1

    def check_identity(self, deadline):
        try:
            status, headers, payload = self.request(PROBE_PATH, deadline)
        except (OSError, HTTPException) as error:
            log_event('probe_transport', error=type(error).__name__)
            return 'order_probe_transport_unavailable'
        if status == 429 or status >= 500:
            return 'order_probe_transport_unavailable'
        body = payload.decode('utf-8', errors='replace')
        if status in (301, 302, 303, 307, 308):
            target = urlsplit(urljoin(BASE + PROBE_PATH, headers.get('Location', '')))
            if (target.scheme == 'https' and target.netloc == 'order.p2pah.cn'
                    and target.path in LOGIN_PATHS):
                return 'expired'
        return page_identity(status, BASE + PROBE_PATH, body)

    def open_login_page(self, deadline):
        # Without PHPSESSID Order answers /login.html -> / -> /login.html; follow
        # only same-site hops so the jar collects the session before the captcha.
        path = LOGIN_PAGE_PATH
        for _ in range(LOGIN_PAGE_HOPS):
            try:
                status, headers, page = self.request(path, deadline)
            except (OSError, HTTPException, ValueError):
                return False
            if status == 200:
                return path == LOGIN_PAGE_PATH and b'dologin' in page
            if status not in (301, 302, 303, 307, 308):
                return False
            target = urlsplit(urljoin(BASE + path, headers.get('Location', '')))
            if target.scheme != 'https' or target.netloc != 'order.p2pah.cn':
                return False
            path = target.path or '/'
        return False

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
            attempts = ocr_attempts()
            oldest = time.monotonic() - LOGIN_WINDOW
            while self.login_posts and self.login_posts[0] <= oldest:
                self.login_posts.popleft()
            remaining_posts = attempts - len(self.login_posts)
            if remaining_posts <= 0:
                return 'order_login_cooldown'
            username, password = read_private_config()
        except (OSError, ValueError, TypeError, AttributeError):
            return 'order_private_config_unavailable'
        for _ in range(attempts):
            if remaining_posts == 0:
                return 'order_login_cooldown'
            self.jar.clear()
            if not self.open_login_page(deadline):
                return 'order_login_page_unavailable'
            try:
                status, _, image = self.request(
                    CAPTCHA_PATH + '?height=32&width=150&font_size=18', deadline,
                    referer=LOGIN_PAGE_PATH)
            except (OSError, HTTPException, ValueError):
                return 'order_captcha_unavailable'
            if (status != 200 or not image.startswith(b'\x89PNG\r\n\x1a\n')
                    or 'PHPSESSID' not in {row['name'] for row in self.cookie_rows()}):
                return 'order_captcha_unavailable'
            try:
                code = recognize(image, deadline)
            except (OSError, subprocess.SubprocessError, UnicodeError):
                return 'order_captcha_ocr_unavailable'
            if not code:
                continue
            form = {'username': username, 'password': password, 'captcha': code,
                    '_captcha_id': '', 'redirect': ''}
            remaining_posts -= 1
            try:
                status, _, payload = self.request(LOGIN_POST_PATH, deadline, form,
                                                  referer=LOGIN_PAGE_PATH)
                reply = json.loads(payload) if status == 200 else None
            except RequestNotSent as error:
                return str(error)
            except (OSError, HTTPException, ValueError):
                reply = None
            if not isinstance(reply, dict):
                self.login_blocked = 'order_login_outcome_unverified'
                return self.login_blocked
            if type(reply.get('code')) is int and reply['code'] == 1:
                return self.check_identity(deadline)
            message = reply.get('msg')
            log_event('login_reply', code=reply.get('code'), msg=message if isinstance(message, str) else None)
            if (not isinstance(message, str)
                    or not re.fullmatch(r'(?:图形)?验证码(?:输入)?(?:错误|不正确|不匹配|已过期)[。！!！]?', message.strip())):
                self.login_blocked = 'order_login_rejected'
                return self.login_blocked
        return 'order_captcha_attempts_exhausted'

    def http_probe(self):
        deadline = time.monotonic() + PROBE_TIMEOUT
        identity = self.check_identity(deadline)
        if identity == 'expired':
            if self.login_blocked:
                identity = self.login_blocked
            elif time.monotonic() < self.login_retry_after:
                identity = 'order_login_cooldown'
            else:
                identity = self.renew(time.monotonic() + RENEW_TIMEOUT)
                if identity not in ('valid', 'order_login_cooldown'):
                    self.login_failures = min(self.login_failures + 1, 4)
                    backoff = min(LOGIN_WINDOW, 60 * 2 ** (self.login_failures - 1))
                    self.login_retry_after = time.monotonic() + backoff
        if identity != 'valid':
            reason = 'order_identity_unverified' if identity == 'expired' else identity
            log_event('probe_failed', reason=reason, login_attempts=self.login_attempts)
            return self.failure(reason)
        rows = self.cookie_rows()
        if not REQUIRED_COOKIES.issubset(row['name'] for row in rows if row['value']):
            return self.failure('order_session_cookies_missing')
        self.login_failures = 0
        self.login_retry_after = 0
        if self.login_blocked == 'order_login_outcome_unverified':
            self.login_blocked = None
        return {'ready': True, 'cookies': rows, 'error': None}


    def get(self, refresh=False):
        # Consumers take a recent ready result without waiting; the upkeep thread
        # (refresh=True) is the one that pays for slow Order probes.
        if (self.result.get('ready') is True and self.checked
                and time.monotonic() - self.checked <= STALE_SERVE
                and (self.probing or not refresh)):
            return self.result
        if not self.lock.acquire(timeout=WAIT_TIMEOUT):
            return self.failure('order_probe_wait_timeout')
        try:
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
        finally:
            self.lock.release()

    def health(self):
        # Health never waits behind an upstream request; cookie issuance still uses get().
        age = time.monotonic() - self.checked if self.checked else None
        fresh = age is not None and age <= STALE_SERVE + PROBE_TIMEOUT
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
                SESSION.get(refresh=True)
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
    if sys.argv[1:] == ['--recognize-captcha']:
        print(recognize_in_worker(sys.stdin.buffer.read()) or '')
    else:
        main()
