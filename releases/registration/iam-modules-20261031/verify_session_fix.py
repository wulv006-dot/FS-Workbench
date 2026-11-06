"""Read-only deployed-route audit; registered identity uses an in-process seam.

No registered credential is minted, exported or stored. This does not claim a
login in the member's browser. Native HTTPS checks use a short-lived operator
token only in memory, never print/store cookies or response business payloads.
"""
import hashlib
import importlib.util
import io
import json
import os
import ssl
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
for line in Path('/opt/auth-portal/config.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")
sys.path[:0] = ['/opt/fs-access-policy', '/opt/auth-portal',
               '/opt/auth-portal/registration-runtime/20261007-ca6258ad']
import auth_portal as portal
import access_policy
import rbac
import iam_console
import management_config_http as management
import consumer_seams
from runtime import build, core


class Handler:
    command = 'GET'
    path = '/management-config/api/view'
    headers = {'Cookie': core.COOKIE + '=in-process-diagnostic'}
    def _send(self, code, body=b'', ctype='', headers=None):
        self.code, self.body = code, body
        return code


def main():
    policy_path = Path(rbac.LIVE_POLICY)
    before = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    policy = rbac.load_policy()
    store, adapter, app = build(portal.CFG['data_dir'], portal, 'https://47.85.224.112')
    portal._registration_bridge = types.SimpleNamespace(adapter=adapter)
    with store.connection() as db:
        users = [dict(row) for row in db.execute(
            'SELECT id AS user_id,name AS live_name,state AS live_state FROM users')]
    navigation = json.loads(Path('/var/www/dashboard/fs-home/navigation.json').read_text())
    paths = sorted({item['path'].split('#')[0] for item in navigation['tools']})
    paths += ['/dashboard/management/config/api/view', '/__auth/access/api/session',
              '/__auth/iam/api/overview', '/dashboard/fs-home/navigation.json',
              '/dashboard/fs-home/module-registry.json', '/dashboard/tasks/api/session']
    original_session = store.session
    mismatches, decisions, allowed, denied = [], 0, 0, 0
    target = None
    for row in users:
        subject = 'reg:' + row['user_id']
        account = store.accounts.row(subject)
        store.session = lambda token, row=row: row if token == 'in-process-diagnostic' else original_session(token)
        for path in paths:
            expected = rbac.authorize(policy, subject, 'GET', path, 'dashboard')
            if row['live_state'] != 'readonly' or not account['enabled']:
                expected = 403
            code, headers = adapter.verify({core.COOKIE: 'in-process-diagnostic'}, 'GET', path, 'dashboard')
            decisions += 1
            allowed += code == 200
            denied += code != 200
            if code != expected:
                mismatches.append(dict(subject=subject, path=path, expected=expected, actual=code))
            if code == 200:
                wanted = 'admin' if rbac.is_admin(policy, subject) else 'editor' if path == '/dashboard/tasks/api/session' and 'edit' in access_policy.matrix(subject).get('tasks', []) else None
                if wanted and headers.get('X-Auth-Role') != wanted:
                    mismatches.append(dict(subject=subject, path=path, expectedRole=wanted, actualRole=headers.get('X-Auth-Role')))
        if row['live_name'].casefold() == 'liule':
            handler = Handler()
            actor = iam_console._session_user(portal, handler)
            management.handle(portal, handler, handler.path, {})
            assert actor == subject and handler.code == 200, (actor, handler.code)
            body = json.loads(handler.body)
            assert body.get('config') and body.get('facts') is not None
            # Exercise role consumption on a current route; the retired /fc27
            # analysis route must remain unmapped for registered accounts.
            code, headers = adapter.verify({core.COOKIE:'in-process-diagnostic'}, 'GET', '/api/fc27/cloud/automation', 'dashboard')
            assert code == 200 and consumer_seams.fc_identity(code, headers, access_policy) == (subject, True)
            assert adapter.verify({core.COOKIE:'in-process-diagnostic'}, 'GET', '/fc27/analysis', 'dashboard')[0] == 403
            target = dict(user='liule', managementDataStatus=handler.code, configLoaded=True,
                          role=headers['X-Auth-Role'], browserLoginTest=False)
    store.session = original_session
    assert target, 'target account missing'
    assert not mismatches, mismatches
    anonymous = Handler()
    anonymous.headers = {'X-Auth-User':'chenchao','X-Auth-Role':'admin'}
    management.handle(portal, anonymous, anonymous.path, {})
    assert anonymous.code == 401
    bad = adapter.verify({core.COOKIE:'invalid'}, 'GET', '/dashboard/management/', 'dashboard')[0]
    assert bad == 401

    # Validate the real HTTPS route, filesystem readability and authentication.
    token = store.accounts.make_token('chenchao', ['dashboard','deploy'], 120)
    cookie = portal.CFG['cookie'] + '=' + token
    context = ssl._create_unverified_context()  # Existing IP certificate, pinned loopback transport.
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    actual = []
    for path in ('/dashboard/management/', '/dashboard/management/config/api/view',
                 '/dashboard/fs-home/navigation.json', '/dashboard/fs-home/module-registry.json',
                 '/__auth/access/api/session', '/dashboard/tasks/api/session', '/bots/api/overview'):
        request = urllib.request.Request('https://127.0.0.1'+path, headers={'Cookie':cookie,'Host':'47.85.224.112'})
        try:
            with opener.open(request, timeout=15) as response:
                data = response.read(8*1024*1024)
                code = response.status
                if 'json' in path or '/api/' in path:
                    parsed = json.loads(data)
                    if path == '/__auth/access/api/session': assert parsed['user'] == 'chenchao'
        except urllib.error.HTTPError as error:
            code = error.code
        actual.append(dict(path=path, code=code))
        assert code == 200, actual[-1]
    assert hashlib.sha256(policy_path.read_bytes()).hexdigest() == before
    report = dict(registeredAccounts=len(users), routeCount=len(paths), decisions=decisions,
                  allowed=allowed, denied=denied, mismatches=mismatches, liule=target,
                  anonymousManagement=anonymous.code, invalidSession=bad, nativeHTTPS=actual,
                  policyUnchanged=True, registeredCredentialMinted=False, browserTest=False)
    (HERE/'verification-session-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
