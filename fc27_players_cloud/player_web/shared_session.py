"""Use the FS HMAC proxy (dc-proxy) instead of a logged-in admin session.

The 8767 admin-session container is retired. All admin traffic
goes through the primary HMAC signing proxy on 127.0.0.1:8912, so there is no
password step and no Google 2FA step. The browser still only receives a
connection status -- no credential ever reaches the client.

Rollback preserves the backed-up HMAC adapter and its read-only mount.
"""
from 球员维护工具.admin_client import AdminAuthError, AdminClient

DC_PROXY_BASE = 'http://127.0.0.1:8912'
DC_PROXY_TOKEN = 'dc-hmac-proxy'


def session_token():
    """Kept for callers that still import it; the HMAC channel needs no batoken."""
    raise AdminAuthError('FS_SHARED_SESSION_RETIRED')


def shared_client(settings):
    client = AdminClient(DC_PROXY_BASE, get_retries=0)
    client._token = DC_PROXY_TOKEN
    client.verify_identity()
    return client
