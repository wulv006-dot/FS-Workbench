"""Actual source Handler over HTTP, synthetic globals; no production config import."""
import ast
from contextlib import closing
import hashlib
import html
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.parse
import runtime as r
from native_integration import bind_functions
from portal_bridge import install
from source_cas import construct
from consumer_seams import install_fc, install_taskboard

HERE = Path(__file__).parent


class DirectTests(unittest.TestCase):
    def test_actual_main_boot_failure_never_opens_listener(self):
        source=(HERE/'fixtures/portal.py.txt').read_bytes()
        patched=construct(source,hashlib.sha256(source).hexdigest(),'portal',origin='https://synthetic.invalid')
        for secure in (False,True):
            with self.subTest(secure=secure),tempfile.TemporaryDirectory(prefix='fs-registration-main-') as directory:
                root=Path(directory);(root/'template.html').write_text('<html>synthetic</html>')
                native=bind_functions({'secret':'Synthetic-http-key-only-42','cookie':'SYNTHETIC_AUTH','secure':secure},
                    {'dashboard':str(root/'synthetic-members')})
                module=types.ModuleType('synthetic_actual_main')
                module.__dict__.update(native.__dict__)
                module.__dict__['__name__']='synthetic_actual_main'
                module.CFG=dict(native.CFG,data_dir=str(root),prefix='/__auth',template=str(root/'template.html'),
                    bind='127.0.0.1',port=0,tz_offset=8)
                def reject_listener(*args,**kw):raise AssertionError('failed boot opened listener')
                module.__dict__.update(BaseHTTPRequestHandler=BaseHTTPRequestHandler,
                    ThreadingHTTPServer=reject_listener,urllib=urllib,html=html,time=time,json=json,
                    os=os,sys=sys,VERSION='synthetic',log=lambda *args:None,_SAFE_NEXT_RE=re.compile(r'^/(?!/)'))
                exec(compile(patched,'<actual-main-CAS>','exec'),module.__dict__)
                old=sys.modules.get(module.__name__);sys.modules[module.__name__]=module
                try:
                    with self.assertRaises((ValueError,FileNotFoundError)):module.main()
                    self.assertFalse((root/'registration-approval').exists())
                    self.assertFalse(hasattr(module,'_registration_bridge'))
                finally:
                    if old is None:sys.modules.pop(module.__name__,None)
                    else:sys.modules[module.__name__]=old

    def test_actual_taskboard_context_caller_enforces_verified_role(self):
        with tempfile.TemporaryDirectory(prefix='fs-registration-taskboard-') as directory:
            db_path=Path(directory)/'synthetic.sqlite3'
            with closing(sqlite3.connect(db_path)) as db:
                db.execute('CREATE TABLE members(username TEXT PRIMARY KEY, role TEXT, active INTEGER)');db.commit()
            source=(HERE/'fixtures/taskboard.py.txt').read_bytes()
            patched=construct(source,hashlib.sha256(source).hexdigest(),'taskboard').decode()
            tree=ast.parse(patched);tree.body=[node for node in tree.body if node.name!='main']
            def connect():
                db=sqlite3.connect(db_path);db.row_factory=sqlite3.Row;return db
            module=types.ModuleType('synthetic_actual_taskboard')
            module.__dict__.update(BaseHTTPRequestHandler=BaseHTTPRequestHandler, Ctx=None,
                VERSION='synthetic',
                ROLES=('admin','editor','viewer'), GUARD_ADMINS=('wulv','chenchao','DY'),
                db_connect=connect, q=lambda db,sql,args,one=False:db.execute(sql,args).fetchone())
            exec(compile(tree,'<actual-taskboard-context>','exec'),module.__dict__)
            native=bind_functions({'secret':'Synthetic-key-42','cookie':'SYNTHETIC_AUTH','secure':True},{})
            install_taskboard(module,native._fs_policy)
            handler=object.__new__(module.Handler);handler.client_address=('127.0.0.1',0)
            for name in native._fs_policy.ADMINS:
                handler.headers={'X-Auth-User':name,'X-Auth-Role':'admin'}
                ctx=handler._ctx();self.assertTrue(ctx.is_admin);module.require_admin(ctx)
            subject='reg:12345678-1234-1234-1234-123456789abc'
            handler.headers={'X-Auth-User':subject,'X-Auth-Role':'readonly'}
            ctx=handler._ctx();self.assertEqual('viewer',ctx.role);self.assertFalse(ctx.to_json()['canEditOwn'])
            with self.assertRaises(module.ApiError):module.require_admin(ctx)
            for subject,role in ((subject,'admin'),('fstech','readonly'),('unknownuser','admin')):
                handler.headers={'X-Auth-User':subject,'X-Auth-Role':role}
                with self.assertRaises(module.ApiError) as error:handler._ctx()
                self.assertEqual(403,error.exception.status)

    def test_exact_source_cas_for_three_actual_callers(self):
        for kind in ('portal','taskboard','fc_gate'):
            source = (HERE / 'fixtures' / (kind + '.py.txt')).read_bytes()
            expected = hashlib.sha256(source).hexdigest()
            patched = construct(source, expected, kind)
            self.assertIn(b'_registration_install(', patched)
            self.assertIn(b'_registration_boot_marker', patched)
            with self.assertRaises(ValueError): construct(source, '0'*64, kind)
            with self.assertRaises(ValueError): construct(patched, hashlib.sha256(patched).hexdigest(), kind)
            if kind == 'taskboard': self.assertIn(b'_registration_member(conn, user,', patched)
            if kind == 'fc_gate': self.assertIn(b'pass  # independent FC auth retired', patched)

    def test_real_portal_handler_http(self):
        with tempfile.TemporaryDirectory(prefix='fs-registration-http-') as directory:
            root = Path(directory)
            native = bind_functions({'secret':'Synthetic-http-key-only-42','cookie':'SYNTHETIC_AUTH','secure':True},
                {'dashboard':str(root/'synthetic-members')})
            encoded = native.apr1_md5('Synthetic-password-42', 'qa123456')
            (root/'synthetic-members').write_text('\n'.join(name+':'+encoded for name in (*native._fs_policy.ADMINS,'oldreader'))+'\n')
            (root/'template.html').write_text('<html>{{USER}}{{MSG}}</html>')
            module = types.ModuleType('synthetic_actual_portal')
            module.__dict__.update(native.__dict__)
            module.CFG = dict(native.CFG, data_dir=str(root),prefix='/__auth',tz_offset=8,
                template=str(root/'template.html'),status_tpl=str(root/'template.html'))
            module.__dict__.update(BaseHTTPRequestHandler=BaseHTTPRequestHandler, urllib=urllib,
                html=html, time=time, json=json, VERSION='synthetic', log=lambda *args:None,
                _SAFE_NEXT_RE=re.compile(r'^/(?!/)'))
            source = (HERE/'fixtures/portal.py.txt').read_text(encoding='utf-8')
            tree = ast.parse(source)
            # Run actual defs/class, never original main/config/env/service code.
            tree.body = [node for node in tree.body if node.name != 'main']
            exec(compile(tree,'<actual-source-handler>', 'exec'), module.__dict__)
            r.RuntimeStore.initialize_fresh(root, module, isolated=True)
            store, adapter, app = install(module,'https://synthetic.invalid',isolated=True)
            server = ThreadingHTTPServer(('127.0.0.1',0),module.Handler)
            thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            def request(method,path,body=None,cookies='',csrf='',origin='https://synthetic.invalid'):
                conn = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                headers = {'Cookie':cookies,'Origin':origin,'X-CSRF-Token':csrf}
                if body is not None: body=json.dumps(body);headers['Content-Type']='application/json'
                try:
                    conn.request(method,path,body,headers)
                    response=conn.getresponse(); payload=response.read()
                    return response.status,payload,response.getheaders()
                finally: conn.close()
            try:
                for path in ('/access/','/access/app.js','/access/base.css','/access/access.css'):
                    self.assertEqual(200,request('GET',path)[0]);self.assertEqual(200,request('HEAD',path)[0])
                self.assertEqual(200,request('GET','/login')[0])
                self.assertEqual(302,request('GET','/logout')[0]);self.assertEqual(405,request('POST','/logout',{})[0])
                code,body,headers=request('GET','/access/api/bootstrap');self.assertEqual(200,code)
                csrf=json.loads(body)['csrf']; cookie=next(v.split(';')[0] for k,v in headers if k.lower()=='set-cookie')
                form={'username':'newreader','password':'Synthetic-password-42','team':'QA','purpose':'Read'}
                self.assertEqual(403,request('POST','/access/api/register',form,cookie,'wrong')[0])
                code,body,_=request('POST','/access/api/register',form,cookie,csrf)
                self.assertEqual(200,code);rid=json.loads(body)['request_id']
                code,body,headers=request('POST','/access/api/native-login',{'username':'fstech','password':'Synthetic-password-42'},cookie,csrf)
                self.assertEqual(200,code)
                values=[v for k,v in headers if k.lower()=='set-cookie'];self.assertEqual(2,len(values))
                for value in values:
                    for attribute in ('Secure','HttpOnly','SameSite=Strict','Path=/'):self.assertIn(attribute,value)
                cookies='; '.join(v.split(';')[0] for v in values);csrf=json.loads(body)['csrf']
                # Actual original route strips trailing '/' before dispatch. Every
                # supported alias must be intercepted without cookie-clear success.
                native_cookie=next(v.split(';')[0] for v in values if v.startswith('SYNTHETIC_AUTH='))
                signed_token=native_cookie.split('=',1)[1]
                with store.connection() as db:
                    before_count=db.execute('SELECT count(*) FROM native_revocations').fetchone()[0]
                for alias in ('/logout','/logout/','/logout///','http://synthetic.invalid/logout/'):
                    for query in ('','?next=/dashboard/','?next=//external.invalid&group=deploy'):
                        for method,expected in (('GET',302),('HEAD',302),('POST',405)):
                            code,body,response_headers=request(method,alias+query,
                                {} if method=='POST' else None,cookies)
                            self.assertEqual(expected,code,(method,alias,query))
                            self.assertFalse(any(k.lower()=='set-cookie' for k,v in response_headers))
                            if method in ('GET','HEAD'):
                                self.assertIn(('Location','/__auth/access/'),response_headers)
                            self.assertIsNotNone(module.read_token(signed_token))
                # These are not logout aliases in the actual old router; do not
                # decode, widen or normalize the separate access API/static routes.
                for path in ('/LOGOUT','/%6cogout','/logout%2f','/logout/extra','//synthetic.invalid/logout/','/access/api/logout/'):
                    self.assertEqual(404,request('GET',path,cookies=cookies)[0])
                self.assertEqual(404,request('POST','/access/api/logout/',{},cookies,csrf)[0])
                handler=object.__new__(module.Handler);handler.command='GET'
                handler._redirect=lambda location:(302,location)
                handler._send=lambda code,*args,**kw:(code,args)
                self.assertEqual((302,'/__auth/access/'),handler._do_logout('/dashboard/'))
                handler.command='POST';self.assertEqual(405,handler._do_logout('/dashboard/')[0])
                with store.connection() as db:
                    self.assertEqual(before_count,db.execute('SELECT count(*) FROM native_revocations').fetchone()[0])
                self.assertEqual(200,request('GET','/access/api/requests',cookies=cookies)[0])
                self.assertEqual(200,request('POST','/access/api/decision',{'request_id':rid,'version':0,'action':'approve','reason':'QA'},cookies,csrf)[0])
                self.assertEqual(200,request('GET','/access/api/audit',cookies=cookies)[0])
                self.assertEqual(200,request('POST','/access/api/logout?next=//external.invalid',{},cookies,csrf)[0])
                self.assertIsNone(module.read_token(signed_token))
                self.assertEqual(401,adapter.verify({'SYNTHETIC_AUTH':signed_token},'GET','/dashboard/')[0])
                with store.connection() as db:
                    self.assertEqual(before_count+1,db.execute('SELECT count(*) FROM native_revocations').fetchone()[0])
                # Actual native status uses replaced parser; old token cannot recover.
                self.assertEqual(302,request('GET','/status',cookies=native_cookie)[0])
                for alias in ('/logout','/logout/','/logout///'):
                    for method in ('GET','HEAD','POST'):
                        self.assertIn(request(method,alias+'?next=/status',
                            {} if method=='POST' else None,cookies)[0],(302,405))
                        self.assertIsNone(module.read_token(signed_token))
                        self.assertEqual(401,request('GET','/verify?group=dashboard',cookies=native_cookie)[0])
                self.assertEqual(401,request('GET','/verify?group=dashboard',cookies='fc27sess=old')[0])
                self.assertEqual(401,request('GET','/verify?group=dashboard',cookies=native_cookie)[0])
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)

    def test_fc_retired_direct_handler_routes_do_not_call_legacy_db(self):
        source=(HERE/'fixtures/fc_gate.py.txt').read_text(encoding='utf-8')
        tree=ast.parse(source);tree.body=[node for node in tree.body if isinstance(node,ast.ClassDef)]
        module=types.ModuleType('synthetic_fc_gate')
        module.__dict__.update(BaseHTTPRequestHandler=BaseHTTPRequestHandler, urllib=urllib,
            http=http,json=json,time=time,BASE='/fc27')
        exec(compile(tree,'<actual-FC-handler>','exec'),module.__dict__)
        native=bind_functions({'secret':'Synthetic-key-42','cookie':'SYNTHETIC_AUTH','secure':True},{})
        install_fc(module,native._fs_policy)
        handler=object.__new__(module.Handler)
        handler._redirect=lambda location:(302,location)
        handler._send=lambda code,*args,**kw:(code,args)
        for path in ('/','/login','/register','/logout'):
            handler.path=path;self.assertEqual((302,'/__auth/access/'),handler.do_GET())
        for path in ('/verify','/admin','/admin/action'):
            handler.path=path;self.assertIn(handler.do_GET()[0],(401,403))
            self.assertEqual(405,handler.do_POST()[0])


if __name__=='__main__':unittest.main()
