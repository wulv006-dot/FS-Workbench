"""Use the FS service session in memory; browsers receive only connection status."""
import json
import socket
from urllib.parse import urlsplit

from 球员维护工具.admin_client import AdminAuthError, AdminClient

SOCKET = '/run/fs-player-session/session.sock'


def session_token():
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(SOCKET)
            connection.sendall(b'session\n')
            with connection.makefile('rb') as stream:
                raw = stream.readline(16385)
        if len(raw) > 16384:
            raise ValueError('oversized_session')
        token = json.loads(raw).get('token')
        if not isinstance(token, str) or not token or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError('invalid_session')
        return token
    except (OSError, ValueError, TypeError, AttributeError):
        raise AdminAuthError('FS_SHARED_SESSION_UNAVAILABLE') from None


def shared_client(settings):
    client = AdminClient(settings.admin_api_base_url, get_retries=0)
    opener = client._opener

    def open_shared(request, *, timeout):
        url = urlsplit(request.full_url)
        if (url.scheme, url.netloc) != ('https', 'admin-api.p2pah.cn'):
            raise AdminAuthError('SHARED_SESSION_TARGET_DENIED')
        if not client.authenticated:
            raise AdminAuthError('AUTH_REQUIRED')
        request.add_header('User-Agent', 'Mozilla/5.0')
        request.add_header('Referer', 'https://admin.p2pah.cn/')
        request.add_header('Origin', 'https://admin.p2pah.cn')
        request.add_header('server', '1')
        request.add_header('batoken', session_token())
        return opener(request, timeout=timeout)

    client._opener = open_shared
    client._token = 'fs-shared-session'
    client.verify_identity()
    return client
