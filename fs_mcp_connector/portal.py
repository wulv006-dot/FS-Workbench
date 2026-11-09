"""Verify real FS sessions against the existing, server-configured IAM portal."""
from dataclasses import dataclass, field
import http.client
import ipaddress
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Principal:
    subject: str
    session_cookie: str = field(repr=False)


class PortalError(Exception):
    def __init__(self, status=503):
        self.status = status
        super().__init__('FS authorization unavailable' if status == 503 else 'FS access denied')


class Portal:
    def __init__(self, base_url, timeout=5):
        if (not isinstance(base_url, str) or not base_url or len(base_url) > 2048
                or any(ord(c) < 33 or ord(c) > 126 for c in base_url)
                or any(c in base_url for c in ('?', '#', '\\'))):
            raise ValueError('portal must be an HTTP loopback origin')
        parts = urlsplit(base_url)
        try:
            loopback = parts.hostname == 'localhost' or ipaddress.ip_address(parts.hostname).is_loopback
        except ValueError:
            loopback = False
        if (parts.scheme != 'http' or not loopback or parts.username is not None or parts.password is not None
                or parts.port == 0
                or parts.path not in ('', '/') or parts.query or parts.fragment):
            raise ValueError('portal must be an HTTP loopback origin')
        self.host, self.port, self.timeout = parts.hostname, parts.port or 80, timeout

    def verify(self, cookie, resource_path, method='GET'):
        if (not isinstance(cookie, str) or not cookie or len(cookie) > 8192
                or any(ord(c) < 32 or ord(c) > 126 for c in cookie)
                or not isinstance(resource_path, str) or not resource_path.startswith('/')
                or resource_path.startswith('//') or len(resource_path) > 8192
                or any(ord(c) < 32 or ord(c) > 126 for c in resource_path)
                or '\\' in resource_path or '#' in resource_path
                or method not in ('GET', 'HEAD', 'POST')):
            raise PortalError(401)
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request('GET', '/verify?group=dashboard', headers={
                'Cookie': cookie, 'X-Original-URI': resource_path, 'X-Original-Method': method})
            response = conn.getresponse()
            users = [v for k, v in response.getheaders() if k.lower() == 'x-auth-user']
            if response.status != 200:
                raise PortalError(response.status if response.status in (401, 403) else 503)
            if (len(users) != 1 or not users[0] or len(users[0]) > 128
                    or any(ord(c) < 33 or ord(c) > 126 for c in users[0])):
                raise PortalError(503)
            return Principal(users[0], cookie)
        except (OSError, http.client.HTTPException, ValueError):
            raise PortalError(503) from None
        finally:
            conn.close()
