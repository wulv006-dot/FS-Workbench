"""Registered GET templates only; DNS is checked and the connection pins that address."""
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time

from .contracts import SOURCES, integer, label


class SourceUnavailable(ValueError):
    def __init__(self, reason, retry_after_seconds=0):
        super().__init__(reason)
        self.retry_after_seconds = retry_after_seconds


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
        for templates in self.registry.values():
            if not isinstance(templates, dict) or not templates:
                raise ValueError('template_registry_invalid')
            for template, item in templates.items():
                label(template)
                if not isinstance(item, dict) or set(item) != {'host', 'path', 'max_bytes'}:
                    raise ValueError('template_invalid')
                if (not isinstance(item['host'], str) or not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,63}', item['host'])
                        or item['host'].endswith(('.localhost', '.local', '.internal'))
                        or not isinstance(item['path'], str) or not re.fullmatch(r'/[A-Za-z0-9/_-]*', item['path'])
                        or '//' in item['path'] or len(item['path']) > 500):
                    raise ValueError('template_endpoint_invalid')
                integer(item['max_bytes'], 1, 1048576)

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
        try:
            connection.request('GET', item['path'], headers={'Accept': 'application/json,text/html',
                                                           'User-Agent': 'FS-FC-Collector/1'})
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
                raise SourceUnavailable('redirect_denied')
            if response.status != 200:
                raise SourceUnavailable('http_' + str(response.status))
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise SourceUnavailable('content_encoding_denied')
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
        finally:
            timer.cancel()
            connection.close()
