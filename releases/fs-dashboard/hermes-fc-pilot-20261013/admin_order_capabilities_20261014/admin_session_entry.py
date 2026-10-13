"""Bind to the already-running authorized SessionManager, without new login.

This is deliberately an injected in-process adapter. Constructing a fresh
SessionManager leaves token=None and would force a new login; do not do that.
The owner must wire this function at the reconciled session-service source.
"""
from .capabilities import collect_admin, checked_query, result


def collect_with_manager(manager, query, config, now=None):
    q = checked_query(query, config, now)
    if not config.get('enabled'):
        return result(q, 'not_available', reason='fc_detail_disabled')
    with manager.lock:
        if not manager.identity_ok(manager.token):
            return result(q, 'not_available', reason='existing_auth_unavailable')
        return collect_admin(lambda path, body:manager.request(path, data=body, token=manager.token), query, config, now)
