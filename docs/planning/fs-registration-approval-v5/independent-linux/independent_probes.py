"""Independent synthetic probes; never imports or touches production configuration."""
import sys
from pathlib import Path
import tempfile
import json
import importlib
import socket
import sqlite3
from unittest.mock import patch

root = Path(__file__).resolve().parent
source = root / 'package/candidates/fs-registration-approval/v5'
sys.path.insert(0, str(source))
checks = []
assertions = 0

def check(condition, message):
    global assertions
    assertions += 1
    assert condition, message

with patch.object(socket.socket, 'bind', side_effect=AssertionError('import bound socket')), patch.object(sqlite3, 'connect', side_effect=AssertionError('import opened database')):
    for name in ('auth_candidate','native_portal_functions','native_access_policy','native_integration','bootstrap_local','integrated_server','preview','schema_contract','qa'):
        importlib.import_module(name)
checks.append('active modules import without opening a SQLite connection or listening socket')

from integrated_server import Environment, SYNTHETIC_PASSWORD
from native_integration import policy, PORTAL_COOKIE
from auth_candidate import COOKIE, READ_ROUTES, Denied

# All further probes need no sockets at all.
with patch.object(socket.socket, 'connect', side_effect=AssertionError('unexpected outbound connection')):
    with tempfile.TemporaryDirectory(prefix='fs-registration-independent-') as sandbox:
        env = Environment(sandbox, 'synthetic-independent-only-key')
        try:
            check(policy.ADMINS == {'wulv','chenchao','DY','fstech'}, 'four-admin policy changed')
            check(len(READ_ROUTES) == 14, 'route inventory mismatch')
            for name in (*policy.ADMINS, 'SYNTHETIC.NATIVE.READER'):
                try:
                    env.store.register(name, SYNTHETIC_PASSWORD, 'synthetic', 'collision probe')
                except Denied as exc:
                    check(exc.code in (400,409), 'unexpected collision denial')
                else:
                    raise AssertionError('existing identity registration allowed')
            checks.append('four administrators preserved; existing-name and case-folded native-name registrations denied')

            request = env.store.register('independent.reader', SYNTHETIC_PASSWORD, 'synthetic', 'independent approval probe')
            token, csrf = env.store.login('independent.reader', SYNTHETIC_PASSWORD)
            cookies = {COOKIE:token}
            for route in READ_ROUTES:
                for method in ('GET','HEAD'):
                    check(env.adapter.verify(cookies, method, route)[0] == 403, 'pending business access')
            checks.append('pending registration denied GET and HEAD on all 14 business route contracts')

            native, actor = env.adapter.native_login('fstech', SYNTHETIC_PASSWORD)
            env.store.decide(actor, request['request_id'], 0, 'approve', 'synthetic independent approval')
            for route in READ_ROUTES:
                for method in ('GET','HEAD'):
                    code, headers = env.adapter.verify(cookies, method, route)
                    check(code == 200 and headers['X-Auth-User'].startswith('reg:') and headers['X-Auth-Role'] == 'readonly', 'approved read identity incorrect')
                for method in ('POST','PUT','PATCH','DELETE','OPTIONS'):
                    check(env.adapter.verify(cookies, method, route)[0] == 403, 'non-read method allowed')
                check(env.adapter.verify(cookies, 'GET', route, 'deploy')[0] == 403, 'deploy grant allowed')
            for route in ('/unreviewed', '/dashboard/admin/', '/dashboard/tasks/api/projects?cmd=', '/dashboard/tasks/api/projects?mode=read&mode=write'):
                check(env.adapter.verify(cookies, 'GET', route)[0] == 403, 'unreviewed/control route allowed')
            checks.append('approved UUID readonly on 14 routes; 70 non-read combinations, deploy and control/unknown routes denied')

            group = Path(env.portal.GROUPS['dashboard'])
            original = group.read_bytes()
            group.unlink()
            check(env.adapter.verify(cookies, 'GET', '/dashboard/')[0] == 503, 'approved identity fails open during outage')
            check(env.adapter.verify({PORTAL_COOKIE:native}, 'GET', '/dashboard/')[0] == 503, 'native identity fails open during outage')
            group.write_bytes(original)
            check(env.adapter.verify(cookies, 'GET', '/dashboard/')[0] == 200, 'restored source did not recover')
            checks.append('missing native source denies both approved and native identities with 503; source restoration recovers')

            # Simulate an external source change, not an authorized native creator.
            group.write_bytes(original + ('INDEPENDENT.READER:' + env.portal.apr1_md5(SYNTHETIC_PASSWORD,'local123') + '\n').encode())
            check(env.adapter.verify(cookies, 'GET', '/dashboard/')[0] == 403, 'later case-folded collision fails open')
            group.write_bytes(original)
            check(env.adapter.verify(cookies, 'GET', '/dashboard/')[0] == 200, 'source restoration after collision')
            checks.append('fresh names snapshot rejects a later case-folded native-name collision')

            env.store.decide(actor, request['request_id'], 1, 'revoke', 'synthetic independent revoke')
            for route in READ_ROUTES:
                check(env.adapter.verify(cookies, 'GET', route)[0] == 401, 'old registered cookie remains valid')
            check(env.store.session(token) is None, 'revoked session retained')
            check([row['action'] for row in env.store.listing('audit')] == ['register','approve','revoke'], 'audit history incorrect')
            checks.append('revocation invalidates old session for all 14 routes and preserves register/approve/revoke history')
        finally:
            env.close()

output = {'scope':'independent Linux synthetic probes only','checks':checks,'assertions':assertions,'passed':True,'external_connections':False,'production_actions':False}
(root/'independent-probes.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output))
