"""FC consumer adapter for the existing 8767 owner; never performs login/refresh."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://admin.p2pah.cn/',
           'Origin': 'https://admin.p2pah.cn', 'Accept': 'application/json, text/plain, */*',
           'think-lang': 'zh-cn', 'server': '1'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_private_config():
    value = json.loads(Path('/run/secrets/fs-global-admin.json').read_text())
    if (value.get('P2PAH_API_BASE') != 'http://127.0.0.1:8911'
            or not isinstance(value.get('P2PAH_ALLOWED_USERNAMES'), list)
            or not value['P2PAH_ALLOWED_USERNAMES']
            or not all(isinstance(name, str) and name for name in value['P2PAH_ALLOWED_USERNAMES'])):
        raise ValueError('shared_admin_principal_config_invalid')
    return value


def allowed_admin_usernames():
    return read_private_config()['P2PAH_ALLOWED_USERNAMES']


class SessionManager:
    def __init__(self, config):
        self.config = config
        self.token = None
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def ensure(self):
        try:
            url = os.environ.get('FS_ADMIN_SESSION_URL', 'http://127.0.0.1:8767')
            if url not in ('http://127.0.0.1:8767', 'http://fc27-p2pah-session:8767'):
                raise ValueError()
            with self.opener.open(url + '/session/admin-token', timeout=8) as response:
                raw = response.read(16385)
                if len(raw) > 16384:
                    raise ValueError()
            token = json.loads(raw).get('token')
            if not isinstance(token, str) or not token or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise ValueError()
            self.token = token
            return True
        except (OSError, ValueError, TypeError, AttributeError):
            self.token = None
            return False

    def request(self, path, *, data=None, token=None):
        if not path.startswith('/admin/') or '://' in path:
            raise ValueError('shared_admin_path_invalid')
        headers = dict(HEADERS)
        if token:
            headers['batoken'] = token
        body = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(data).encode()
        request = Request(self.config['P2PAH_API_BASE'] + path, data=body, headers=headers,
                          method='POST' if data is not None else 'GET')
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()
