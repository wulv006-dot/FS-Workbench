"""Registered GET templates only; DNS is checked and the connection pins that address."""
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import http.cookiejar
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlencode, urljoin, urlsplit, parse_qsl
from urllib.request import Request

from .contracts import SOURCES, integer, label, ARAB_WARM_PATHS


class SourceUnavailable(ValueError):
    def __init__(self, reason, retry_after_seconds=0):
        super().__init__(reason)
        self.retry_after_seconds = retry_after_seconds


class WarmLanguageRedirect(SourceUnavailable):
    def __init__(self, template_id):
        if template_id not in ARAB_WARM_PATHS or template_id == 'warm':
            raise ValueError('warm_language_template_invalid')
        super().__init__('warm_language_redirect')
        self.template_id = template_id


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = address
        self.end = time.monotonic() + timeout
        self.wire_socket = None

    def abort(self):
        if self.wire_socket is not None:
            try:
                self.wire_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.wire_socket.close()

    def connect(self):
        if time.monotonic() >= self.end:
            raise SourceUnavailable('request_timeout')
        sock = socket.socket(socket.AF_INET6 if ':' in self.address[0] else socket.AF_INET, socket.SOCK_STREAM)
        self.wire_socket = sock
        sock.settimeout(max(.001, self.end - time.monotonic()))
        try:
            sock.connect(self.address)
            sock.settimeout(max(.001, self.end - time.monotonic()))
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            self.wire_socket = self.sock
        except BaseException:
            sock.close()
            raise


class RestrictedHTTP:
    def __init__(self, registry):
        if not isinstance(registry, dict) or not registry or set(registry) - SOURCES:
            raise ValueError('source_registry_invalid')
        self.registry = deepcopy(registry)
        self.cookies = http.cookiejar.CookieJar()
        for source, templates in self.registry.items():
            if not isinstance(templates, dict) or not templates:
                raise ValueError('template_registry_invalid')
            for template, item in templates.items():
                label(template)
                if not isinstance(item, dict) or set(item) - {'query'} != {'host', 'path', 'max_bytes'}:
                    raise ValueError('template_invalid')
                if (not isinstance(item['host'], str) or not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,63}', item['host'])
                        or item['host'].endswith(('.localhost', '.local', '.internal'))
                        or not isinstance(item['path'], str) or not re.fullmatch(r'/[A-Za-z0-9/_-]*', item['path'])
                        or '//' in item['path'] or len(item['path']) > 500):
                    raise ValueError('template_endpoint_invalid')
                if 'query' in item:
                    query = dict(platform='playstation', delivery='normal', quantity='100000')
                    if (source != 'ArabUT' or item['host'] != 'www.arab-ut.com'
                            or not ((template in ARAB_WARM_PATHS and item['path'] == ARAB_WARM_PATHS[template] and item['query'] == dict(query, currency='USD'))
                                    or (template == 'quote' and item['path'] == '/coins/quote' and item['query'] == query))):
                        raise ValueError('template_query_invalid')
                integer(item['max_bytes'], 1, 2097153)

    def fetch(self, source_id, template_id, timeout):
        if source_id not in self.registry or template_id not in self.registry[source_id]:
            raise ValueError('template_not_registered')
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 300:
            raise ValueError('request_timeout_invalid')
        item = self.registry[source_id][template_id]
        end = time.monotonic() + timeout
        resolved = queue.Queue(maxsize=1)
        def resolve():
            try:
                value = socket.getaddrinfo(item['host'], 443, type=socket.SOCK_STREAM)
            except OSError:
                value = []
            resolved.put(value)
        threading.Thread(target=resolve, daemon=True).start()
        try:
            addresses = resolved.get(timeout=timeout)
        except queue.Empty:
            raise SourceUnavailable('dns_unavailable') from None
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('destination_not_public')
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise SourceUnavailable('request_timeout')
        connection = PinnedHTTPS(item['host'], addresses[0][4][:2], remaining)
        timer = threading.Timer(remaining, connection.abort)
        timer.daemon = True
        timer.start()
        response = None
        try:
            path = item['path'] + ('?' + urlencode(item['query']) if item.get('query') else '')
            accept = ('text/html' if template_id in ARAB_WARM_PATHS else 'application/json') if source_id == 'ArabUT' else 'application/json,text/html'
            request = Request('https://' + item['host'] + path,
                              headers={'Accept': accept, 'User-Agent': 'Mozilla/5.0'})
            if source_id == 'ArabUT':
                self.cookies.add_cookie_header(request)
                if template_id == 'quote':
                    request.add_header('Referer', 'https://www.arab-ut.com/?' + urlencode(self.registry['ArabUT']['warm']['query']))
            if len(request.get_header('Cookie', '')) > 4096:
                raise SourceUnavailable('visitor_cookie_limit')
            connection.request('GET', path, headers=dict(request.header_items()))
            response = connection.getresponse()
            if time.monotonic() >= end:
                raise SourceUnavailable('request_timeout')
            if response.status in (401, 403, 429):
                retry = response.getheader('Retry-After', '')
                seconds = int(retry) if retry.isdigit() else 0
                if retry and not retry.isdigit():
                    try:
                        seconds = max(0, int((parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()))
                    except (ValueError, TypeError, OverflowError):
                        seconds = 0
                raise SourceUnavailable('http_' + str(response.status), min(seconds, 31536000))
            if 300 <= response.status < 400:
                location = response.getheader('Location', '')
                allowed = False
                language_template = None
                if (source_id == 'ArabUT' and template_id in ARAB_WARM_PATHS and response.status in (302, 303)
                        and location and len(location) <= 2048 and all(ord(c) >= 32 for c in location)):
                    try:
                        target = urlsplit(urljoin('https://' + item['host'] + path, location))
                        query = parse_qsl(target.query, keep_blank_values=True, strict_parsing=True) if target.query else []
                        language_template = next((name for name,path in ARAB_WARM_PATHS.items()
                                                  if name != 'warm' and path == target.path), None)
                        allowed = (target.scheme == 'https' and target.hostname == item['host']
                            and target.port in (None, 443) and target.username is None and target.password is None
                            and (target.path in ('', '/') or language_template is not None
                                 and (template_id == 'warm' or target.path.rstrip('/') == item['path'].rstrip('/')))
                            and not target.fragment and len(dict(query)) == len(query)
                            and all(item['query'].get(key) == value for key, value in query))
                    except ValueError:
                        pass
                if not allowed:
                    raise SourceUnavailable('redirect_denied')
                self.cookies.extract_cookies(response, request)
                if len(self.cookies) > 32:
                    raise SourceUnavailable('visitor_cookie_limit')
                if template_id == 'warm' and language_template:
                    raise WarmLanguageRedirect(language_template)
                # Warm body is unused; retain selection cookies, never fetch the redirect target.
                return b''
            if response.status != 200:
                raise SourceUnavailable('http_' + str(response.status))
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise SourceUnavailable('content_encoding_denied')
            if source_id == 'ArabUT':
                self.cookies.extract_cookies(response, request)
                if len(self.cookies) > 32:
                    raise SourceUnavailable('visitor_cookie_limit')
            body = bytearray()
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise SourceUnavailable('request_timeout')
                connection.wire_socket.settimeout(remaining)
                chunk = response.read1(min(16384, item['max_bytes'] + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > item['max_bytes']:
                    raise SourceUnavailable('response_too_large')
            if any(marker in bytes(body).lower() for marker in (b'cf-chl-', b'challenge-platform', b'g-recaptcha')):
                raise SourceUnavailable('challenge')
            return bytes(body)
        except ssl.SSLCertVerificationError:
            raise SourceUnavailable('tls_validation_failed') from None
        finally:
            timer.cancel()
            try:
                if response is not None:
                    response.close()
            finally:
                connection.close()
