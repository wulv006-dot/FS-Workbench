"""Restricted crawler destinations, including pinned public DNS and redirects."""
import http.client
import ipaddress
import socket
import ssl
import urllib.parse
import urllib.request

HOSTS = ('iggm.com', 'aoeah.com', 'u4gm.com')

def parsed_destination(url, hosts=HOSTS):
    if not isinstance(url, str) or not url or len(url) > 4096 or any(ord(c) <= 32 or c == '\\' for c in url):
        raise ValueError('INVALID_CRAWLER_URL')
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('https', 'http') or u.username is not None or u.password is not None or u.fragment:
        raise ValueError('INVALID_CRAWLER_URL')
    try:
        host = (u.hostname or '').encode('idna').decode('ascii').lower()
        port = u.port or (443 if u.scheme == 'https' else 80)
    except (UnicodeError, ValueError):
        raise ValueError('INVALID_CRAWLER_URL') from None
    if port != (443 if u.scheme == 'https' else 80) or not any(host == h or host.endswith('.' + h) for h in hosts):
        raise ValueError('CRAWLER_DESTINATION_NOT_ALLOWED')
    return u, host, port

def public_destination(url, hosts=HOSTS, resolver=None):
    u, host, port = parsed_destination(url, hosts)
    resolver = resolver or socket.getaddrinfo
    results = resolver(host, port, type=socket.SOCK_STREAM)
    addresses = []
    for family, _, _, _, address in results:
        ip = ipaddress.ip_address(address[0])
        check = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip
        if not check.is_global or check.is_multicast or check.is_reserved:
            raise ValueError('CRAWLER_ADDRESS_NOT_PUBLIC')
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise ValueError('CRAWLER_ADDRESS_NOT_PUBLIC')
        addresses.append(str(ip))
    if not addresses:
        raise ValueError('CRAWLER_DNS_EMPTY')
    return u, host, port, addresses[0]

def pinned_connection(url, timeout=30, resolver=None):
    u, host, port, address = public_destination(url, resolver=resolver)
    class PinnedHTTP(http.client.HTTPConnection):
        def connect(self):
            if self._tunnel_host:
                raise ValueError('CRAWLER_PROXY_NOT_ALLOWED')
            self.sock = socket.create_connection((address, port), self.timeout, self.source_address)
    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            if self._tunnel_host:
                raise ValueError('CRAWLER_PROXY_NOT_ALLOWED')
            sock = socket.create_connection((address, port), self.timeout, self.source_address)
            self.sock = self._context.wrap_socket(sock, server_hostname=host)
    cls = PinnedHTTPS if u.scheme == 'https' else PinnedHTTP
    kwargs = {'timeout': timeout}
    if u.scheme == 'https':
        kwargs['context'] = ssl.create_default_context()
    return cls(host, port, **kwargs)

class SafeHTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(lambda _host, **kw: pinned_connection(req.full_url, kw.get('timeout', 30)), req)

class SafeHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(lambda _host, **kw: pinned_connection(req.full_url, kw.get('timeout', 30)), req)

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed_destination(newurl)
        # DNS is revalidated and the resulting address pinned on each new connection.
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def safe_opener(cookiejar):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), SafeHTTP(), SafeHTTPS(),
        SafeRedirect(), urllib.request.HTTPCookieProcessor(cookiejar))
