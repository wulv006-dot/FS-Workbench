"""Trusted-consumer functions, pure and not installed into a live service.

Headers passed here MUST be overwritten by nginx auth_request variables; direct
client headers are not proof. Caller integration and nginx tests remain mandatory.
"""
import re
import types
import uuid
import http.client
from urllib.parse import urlsplit
from runtime import core


def canonical_subject(subject):
    if not isinstance(subject, str): raise core.Denied(403, 'invalid subject')
    if subject.startswith('reg:'):
        try:
            value = uuid.UUID(subject[4:])
        except ValueError:
            raise core.Denied(403, 'invalid registered subject') from None
        if subject != 'reg:' + str(value): raise core.Denied(403, 'noncanonical subject')
        return True
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{1,59}', subject):
        raise core.Denied(403, 'invalid native subject')
    return False


def taskboard_member(conn, subject, verified_role, original_member_state, policy):
    registered = canonical_subject(subject)
    if registered:
        if verified_role != 'readonly': raise core.Denied(403, 'registered role conflict')
        return 'viewer', True
    wanted = 'admin' if subject in policy.ADMINS else 'readonly'
    if verified_role != wanted: raise core.Denied(403, 'native role conflict')
    # Rebind exact current native member_state, preserving members/editor semantics
    # for existing native accounts. New registration never writes members table.
    fn = types.FunctionType(original_member_state.__code__,
        dict(original_member_state.__globals__, GUARD_ADMINS=policy.ADMINS),
        argdefs=original_member_state.__defaults__)
    return fn(conn, subject)


def fc_identity(verify_status, verified_headers, policy):
    """Replace gate's three-name test using the actual portal verify response."""
    if verify_status != 200: return None, False
    subject = verified_headers.get('X-Auth-User')
    role = verified_headers.get('X-Auth-Role')
    try:
        registered = canonical_subject(subject)
    except core.Denied:
        return None, False
    if registered: return (subject, False) if role == 'readonly' else (None, False)
    wanted = 'admin' if subject in policy.ADMINS else 'readonly'
    if role != wanted: return None, False
    return subject, wanted == 'admin'


def install_taskboard(board, policy):
    """For the CAS-patched actual Handler caller, before the listener only."""
    if hasattr(board, '_registration_member'): raise ValueError('consumer already installed')
    original = board.member_state
    def member(conn, user, role):
        try: return taskboard_member(conn, user, role, original, policy)
        except core.Denied as exc:
            raise board.ApiError(exc.code, exc.message) from None
    board._registration_member = member
    board.GUARD_ADMINS = tuple(policy.ADMINS)


def install_fc(gate, policy):
    """Retire independent FC authentication/actions; preserve analysis implementation.

    No call to FC session DB/login/logout/admin action is reachable in these routes.
    Coordinated nginx must authenticate other FC consumers through global verify.
    """
    if hasattr(gate, '_registration_fc_installed'): raise ValueError('consumer already installed')
    old_get = gate.Handler.do_GET
    def current(handler):
        conn = http.client.HTTPConnection('127.0.0.1', 8895, timeout=3)
        path = urlsplit(handler.path).path
        public = '/fc27' + handler.path if not path.startswith('/fc27/') else handler.path
        try:
            conn.request('GET', '/verify', headers={'Cookie':handler.headers.get('Cookie',''),
                'X-Original-Method':handler.command, 'X-Original-URI':public})
            response = conn.getresponse()
            headers = {key:response.getheader(key) for key in ('X-Auth-User','X-Auth-Role')}
            response.read()
            return fc_identity(response.status, headers, policy)
        except (OSError, http.client.HTTPException):
            return None, False
        finally: conn.close()
    def get(handler):
        path = handler._norm(urlsplit(handler.path).path)
        if path in ('/', '/login', '/register', '/logout'):
            return handler._redirect('/__auth/access/')
        if path == '/verify': return handler._send(401, 'independent FC identity retired')
        if path == '/analysis': return old_get(handler)
        if path == '/healthz': return old_get(handler)
        return handler._send(403, 'independent FC administration retired')
    def post(handler):
        handler.close_connection = True
        return handler._send(405, 'Use global CSRF protected access portal')
    gate.Handler._current_identity = current
    gate.Handler.do_GET = get
    gate.Handler.do_HEAD = get
    gate.Handler.do_POST = post
    gate._registration_fc_installed = True
