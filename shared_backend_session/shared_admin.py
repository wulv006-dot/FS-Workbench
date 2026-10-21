"""Read the existing owner session; never log in, refresh, cache, or log tokens."""
import json
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def admin_token_from_service(timeout=8.0):
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        request = Request('http://127.0.0.1:8767/session/admin-token',
                          headers={'Accept': 'application/json'})
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(16385)
            if response.status != 200 or len(raw) > 16384:
                raise ValueError('invalid_response')
        value = json.loads(raw)
        token = value.get('token') if isinstance(value, dict) else None
        if (not isinstance(token, str) or not token or len(token) > 8192
                or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise ValueError('invalid_token')
        return token, None
    except (OSError, ValueError, TypeError):
        return None, 'shared_admin_unavailable'
