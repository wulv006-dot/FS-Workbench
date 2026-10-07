"""New production caller/recovery delta only; synthetic local fixtures, no sockets.

The complete candidate modules are loaded without modifying their source bytes.
Native policy loading is redirected to the frozen byte-identical policy; listener
objects are replaced by inert recorders. Runtime's explicit isolated=True test
boundary is used only in this test, never added to the production payload.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CANDIDATE = REPO / 'candidates/registration-import-20261007'
FORMAL = CANDIDATE / 'formal'
RECOVERY = CANDIDATE / 'recovery'
RUNTIME = REPO / 'registration_approval_runtime_v3_20261006'
sys.path.insert(0, str(RUNTIME))
import portal_bridge
import runtime
import native_access_policy as policy

ORIGIN = 'https://47.85.224.112'
RUNTIME_TARGET = '/opt/auth-portal/registration-runtime/20261007-ca6258ad'
PASSWORD = 'Synthetic-password-42'


class InertServer:
    opened = []
    def __init__(self, address, handler):
        self.opened.append((address, handler))
    def serve_forever(self): pass
    def server_close(self): pass


def load_module(path, name):
    original = importlib.util.spec_from_file_location
    def redirect(mod_name, location, *args, **kwargs):
        if location == '/opt/fs-access-policy/access_policy.py':
            location = RUNTIME / 'vendor/native_access_policy.py'
        return original(mod_name, location, *args, **kwargs)
    spec = original(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with patch.object(importlib.util, 'spec_from_file_location', redirect):
        spec.loader.exec_module(module)
    module.ThreadingHTTPServer = InertServer
    module.log = lambda *a, **kw: None
    return module


def boot_portal(module):
    original_install = portal_bridge.install
    original_isdir = os.path.isdir
    def isdir(path):
        return True if path == RUNTIME_TARGET else original_isdir(path)
    with patch.object(os.path, 'isdir', isdir), patch.object(portal_bridge, 'install',
            lambda portal, origin: original_install(portal, origin, isolated=True)):
        module.main()


def handler_for(module, path, method='GET', headers=None):
    handler = object.__new__(module.Handler)
    handler.path = path
    handler.command = method
    handler.headers = dict(headers or {})
    handler.client_address = ('127.0.0.1', 1)
    handler.close_connection = False
    handler.rfile = io.BytesIO(b'')
    handler._send = lambda code, body=b'', *a, **kw: (code, body, kw)
    handler._redirect = lambda target, *a, **kw: (302, target, kw)
    return handler


class Reply:
    def __init__(self, status, user=None, role=None):
        self.status = status
        self.headers = {'X-Auth-User': user, 'X-Auth-Role': role}
    def getheader(self, name): return self.headers.get(name)
    def read(self): return b''


class Connection:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []
        self.closed = False
    def request(self, method, path, headers): self.requests.append((method, path, headers))
    def getresponse(self): return self.reply
    def close(self): self.closed = True


class ReleaseDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-registration-release-delta-')
        self.root = Path(self.temp.name)
        self.members = self.root / 'synthetic-members'
        template = self.root / 'login.html'
        template.write_text('Synthetic template', encoding='utf-8')
        self.env = patch.dict(os.environ, {
            'AUTH_DATA_DIR': str(self.root), 'AUTH_SECRET': 'Synthetic-secret-for-isolated-release-test',
            'AUTH_GROUPS': 'dashboard=' + str(self.members), 'AUTH_TEMPLATE': str(template),
            'AUTH_COOKIE_SECURE': '1', 'TASKBOARD_DATA': str(self.root/'board'),
            'FC27_DB': str(self.root/'old-FC-must-not-be-created.sqlite3')})
        self.env.start()
        InertServer.opened = []
        self.portal = load_module(FORMAL/'auth_portal.py', 'release_test_portal')
        encoded = self.portal.apr1_md5(PASSWORD, 'qa123456')
        self.members.write_text('\n'.join(name+':'+encoded for name in (*policy.ADMINS, 'oldreader'))+'\n', encoding='utf-8')
        self.source_before = self.file_hashes()

    def file_hashes(self):
        return {p.relative_to(CANDIDATE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for root in (FORMAL, RECOVERY) for p in root.rglob('*')
                if p.is_file() and '__pycache__' not in p.parts}

    def tearDown(self):
        self.assertEqual(self.source_before, self.file_hashes())
        self.env.stop()
        self.temp.cleanup()

    def initialize(self):
        runtime.RuntimeStore.initialize_fresh(self.root, self.portal, isolated=True)

    def test_portal_exact_main_refuses_missing_store_before_listener_without_init(self):
        with self.assertRaises((FileNotFoundError, ValueError)):
            boot_portal(self.portal)
        self.assertEqual([], InertServer.opened)
        self.assertFalse((self.root/'registration-approval').exists())
        self.assertFalse((self.root/'.registration-checkpoint').exists())

    def test_portal_exact_main_rejects_insecure_cookie_before_listener(self):
        self.initialize()
        self.portal.CFG['secure'] = False
        with self.assertRaisesRegex(ValueError, 'insecure'):
            boot_portal(self.portal)
        self.assertEqual([], InertServer.opened)
        self.assertFalse(hasattr(self.portal, '_registration_bridge'))

    def test_portal_installed_verify_no_old_FC_fallback_and_legacy_logout_inert(self):
        self.initialize()
        boot_portal(self.portal)
        handler = handler_for(self.portal, '/verify', headers={'Cookie': 'fc27sess=synthetic-old-FC'})
        with patch('http.client.HTTPConnection', side_effect=AssertionError('old FC fallback called')):
            self.assertEqual(401, self.portal.Handler._do_verify(handler)[0])
        handler = handler_for(self.portal, '/logout/')
        self.assertEqual((302, '/__auth/access/'), self.portal.Handler._do_logout(handler)[:2])
        self.assertEqual(1, len(InertServer.opened))

    def test_FC_exact_main_retires_initialization_and_all_old_identity_routes(self):
        gate = load_module(FORMAL/'fc27_gate.py', 'release_test_gate')
        old_db = Path(gate.DB_PATH)
        with (patch.object(gate, 'init_db', side_effect=AssertionError('old DB init')),
              patch.object(gate, 'purge_expired', side_effect=AssertionError('old DB purge')),
              contextlib.redirect_stdout(io.StringIO())):
            gate.main()
        self.assertFalse(old_db.exists())
        for path in ('/login','/register','/logout','/'):
            self.assertEqual((302, '/__auth/access/'), gate.Handler.do_GET(handler_for(gate, path))[:2])
        for path, code in (('/verify',401),('/admin',403),('/admin/audit',403)):
            self.assertEqual(code, gate.Handler.do_GET(handler_for(gate, path))[0])
        for path in ('/login','/register','/logout','/admin/action'):
            handler = handler_for(gate, path, 'POST')
            self.assertEqual(405, gate.Handler.do_POST(handler)[0])
            self.assertTrue(handler.close_connection)
        reply = Connection(Reply(200,'fstech','admin'))
        handler = handler_for(gate,'/analysis?x=1',headers={'Cookie':'synthetic', 'X-Original-URI':'/forged'})
        with patch('http.client.HTTPConnection', return_value=reply):
            self.assertEqual(('fstech',True), gate.Handler._current_identity(handler))
        self.assertEqual('/fc27/analysis?x=1', reply.requests[0][2]['X-Original-URI'])
        self.assertTrue(reply.closed)
        self.assertFalse(old_db.exists())

    def board(self):
        board = load_module(FORMAL/'taskboard_server.py', 'release_test_board')
        board.init_db = lambda: {'synthetic': True}
        board.main([])
        return board

    def test_board_direct_spoof_and_verifier_failure_rejected_before_DB_access(self):
        board = self.board()
        for response, headers, expected in (
                (Reply(401), {'X-Auth-User':'fstech','X-Auth-Role':'admin'}, 401),
                (Reply(200,'oldreader','readonly'), {'X-Auth-User':'fstech','X-Auth-Role':'admin'},403),
                (Reply(200,'fstech',None), {},503),
                (Reply(500), {},503)):
            conn = Connection(response)
            handler = handler_for(board,'/api/tasks?x=1', 'POST', headers)
            with patch('http.client.HTTPConnection', return_value=conn), patch.object(board,'db_connect',side_effect=AssertionError('DB accessed before verification')):
                with self.assertRaises(board.ApiError) as caught: board.Handler._ctx(handler)
                self.assertEqual(expected,caught.exception.status)
            self.assertEqual('/dashboard/tasks/api/tasks?x=1',conn.requests[0][2]['X-Original-URI'])
            self.assertEqual('POST',conn.requests[0][2]['X-Original-Method'])
            self.assertTrue(conn.closed)
        failed = Connection(Reply(200,'fstech','admin'))
        failed.request = lambda *a, **kw: (_ for _ in ()).throw(OSError('synthetic refused'))
        with patch('http.client.HTTPConnection', return_value=failed):
            with self.assertRaises(board.ApiError) as caught:
                board._registration_verified_identity(handler_for(board,'/api/session'))
            self.assertEqual(503,caught.exception.status)

    def test_board_verified_four_admins_native_editor_and_registered_viewer(self):
        board = self.board()
        def db():
            conn = sqlite3.connect(':memory:'); conn.row_factory=sqlite3.Row
            conn.execute('CREATE TABLE members(username TEXT, role TEXT, active INTEGER)')
            conn.execute("INSERT INTO members VALUES('oldreader','editor',1)")
            return conn
        cases = [(name,'admin','admin',True) for name in policy.ADMINS]
        cases += [('oldreader','readonly','editor',True),('reg:12345678-1234-1234-1234-123456789abc','readonly','viewer',True)]
        for name,verified_role,role,registered in cases:
            conn = Connection(Reply(200,name,verified_role))
            with patch('http.client.HTTPConnection',return_value=conn), patch.object(board,'db_connect',db):
                ctx = board.Handler._ctx(handler_for(board,'/api/session'))
                self.assertEqual((name,role,registered),(ctx.user,ctx.role,ctx.registered))

    def test_exact_recovery_boot_retains_logged_out_native_and_revoked_registered_denials(self):
        self.initialize()
        boot_portal(self.portal)
        bridge = self.portal._registration_bridge
        native, proof = bridge.adapter.native_login('fstech', PASSWORD)
        request = bridge.adapter.store.register('newreader', PASSWORD,'QA','Synthetic delta')
        bridge.adapter.store.decide(proof, request['request_id'],0,'approve','Synthetic approval')
        registered, _ = bridge.adapter.store.login('newreader',PASSWORD)
        bridge.adapter.store.decide(proof, request['request_id'],1,'revoke','Synthetic revoke')
        session, csrf = bridge.adapter.store.new_session(legacy_user=proof.user)
        cookies = {runtime.core.COOKIE:session,self.portal.CFG['cookie']:native}
        code = bridge.app.dispatch('POST','/api/logout',cookies=cookies,body=b'{}',headers={
            'Origin':ORIGIN,'X-CSRF-Token':csrf,'Content-Type':'application/json'})[0]
        self.assertEqual(200,code)
        db = self.root/'registration-approval/registration.sqlite3'
        anchor = self.root/'.registration-checkpoint/state.json'
        before = (db.read_bytes(),anchor.read_bytes())
        recovery = load_module(RECOVERY/'auth_portal.py','release_test_recovery')
        boot_portal(recovery)
        self.assertEqual(before,(db.read_bytes(),anchor.read_bytes()))
        for cookie in (self.portal.CFG['cookie']+'='+native,runtime.core.COOKIE+'='+registered):
            handler = handler_for(recovery,'/verify',headers={'Cookie':cookie,'X-Original-URI':'/dashboard/','X-Original-Method':'GET'})
            self.assertEqual(401,recovery.Handler._do_verify(handler)[0])
        self.assertIsNone(recovery.read_token(native))
        for method,path in (('GET','/api/bootstrap'),('POST','/api/login'),('POST','/api/logout'),('POST','/api/decide')):
            self.assertEqual(503,recovery._registration_bridge.app.dispatch(method,path)[0])
        self.assertEqual(before,(db.read_bytes(),anchor.read_bytes()))


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseDeltaTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'scope':'new caller/recovery delta only; existing 43+4 not rerun',
        'python':sys.version,'platform':sys.platform,'synthetic_only':True,
        'sockets_opened':False,'production_write':False,'source_bytes_unchanged':True,
        'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'passed':result.wasSuccessful()}
    (HERE/'delta-test-result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
