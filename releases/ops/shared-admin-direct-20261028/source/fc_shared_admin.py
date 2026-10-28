"""Existing shared Admin interface, transported only through the DC HMAC proxy."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://admin.p2pah.cn/',
           'Origin': 'https://admin.p2pah.cn', 'Accept': 'application/json, text/plain, */*',
           'think-lang': 'zh-cn', 'server': '1'}
API_BASES = ('http://127.0.0.1:8912', 'http://127.0.0.1:8911',
             'http://172.20.0.1:8913')
ADMIN_USERS = ('wulvapi', 'chenchaoapi')
LEGACY_API_BASE = 'https://admin-api.p2pah.cn'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_base(config):
    supplied = config.get('P2PAH_API_BASE')
    if isinstance(supplied, str):supplied = supplied.rstrip('/')
    if supplied in API_BASES:return supplied
    if supplied not in (None, '', LEGACY_API_BASE):
        raise ValueError('shared_admin_api_base_invalid')
    # Existing bridge launchers mount this one file and do not provide a new config.
    default = API_BASES[2] if Path('/.dockerenv').is_file() else API_BASES[0]
    base = os.environ.get('FS_ADMIN_API_BASE', default).rstrip('/')
    if base not in API_BASES:raise ValueError('shared_admin_api_base_invalid')
    return base


def read_private_config():
    return {'P2PAH_API_BASE': api_base({}), 'P2PAH_ALLOWED_USERNAMES': list(ADMIN_USERS)}


def allowed_admin_usernames():
    return list(ADMIN_USERS)


class SessionManager:
    def __init__(self, config):
        self.config = dict(config, P2PAH_API_BASE=api_base(config))
        self.token = None
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def ensure(self):
        try:
            status, raw = self._request('/admin/index/index', timeout=8)
            result = json.loads(raw)
            identity = (result.get('data') or {}).get('adminInfo') or {}
            if (status != 200 or result.get('code') != 1
                    or identity.get('username') not in ADMIN_USERS):
                raise ValueError('shared_admin_identity_invalid')
            self.token = 'dc-hmac-proxy'
            return True
        except (OSError, ValueError, TypeError, AttributeError):
            self.token = None
            return False

    def request(self, path, *, data=None, token=None):
        return self._request(path, data=data, timeout=15)

    def _request(self, path, *, data=None, timeout):
        normal = path.split('?', 1)[0].rstrip('/').lower().replace('.', '/')
        if (not path.startswith('/admin/') or '://' in path
                or normal == '/admin/index/login'):
            raise ValueError('shared_admin_path_invalid')
        headers = dict(HEADERS)
        body = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(data).encode()
        request = Request(self.config['P2PAH_API_BASE'] + path, data=body, headers=headers,
                          method='POST' if data is not None else 'GET')
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()
