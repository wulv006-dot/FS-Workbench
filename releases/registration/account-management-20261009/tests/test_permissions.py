"""Real runtime/store and taskboard HTTP in temporary isolated storage only."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

RELEASE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ['FS_PERMISSION_REPO']) if 'FS_PERMISSION_REPO' in os.environ else next(p for p in RELEASE.parents if (p/'registration_approval_runtime_v3_20261006').is_dir())
BASE = ROOT / 'registration_approval_runtime_v3_20261006'
GREEN = ROOT / 'green_plan_20261009/deploy/candidate/backend'
POLICY = ROOT / 'green_plan_review_fix_20261009/source/auth/native_access_policy.py'
if not GREEN.exists():
    GREEN = ROOT / 'releases/green-plan/20261009/candidate/backend'
    POLICY = ROOT / 'releases/green-plan/20261009-review-fix/source/auth/native_access_policy.py'
sys.path[:0] = [str(RELEASE/'source/runtime'),str(BASE/'vendor'),str(BASE),str(GREEN)]
import runtime as r
import module_permissions as permissions
import consumer_seams
from native_integration import bind_functions
import green_plan as gp

def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module; spec.loader.exec_module(module); return module

policy=load('permission_current_policy',POLICY)

class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fs-registration-permissions-')
        self.root=Path(self.temp.name)
        self.portal=bind_functions({'secret':'Synthetic-only-permission-QA','cookie':'SYNTHETIC_AUTH','secure':True},{'dashboard':str(self.root/'synthetic-members')},policy)
        encoded=self.portal.apr1_md5('Synthetic-password-42','qa123456')
        (self.root/'synthetic-members').write_text('\n'.join(n+':'+encoded for n in (*policy.ADMINS,'native_reader'))+'\n')
        r.RuntimeStore.initialize_fresh(self.root,self.portal,isolated=True)
        self.store,self.adapter,self.app=r.build(self.root,self.portal,'https://synthetic.invalid',isolated=True)
        _,self.admin=self.adapter.native_login('wulv','Synthetic-password-42')
        self.request=self.store.register('qa_reader','Synthetic-password-42','QA','Module access')
        self.rid=self.request['request_id']; self.store.decide(self.admin,self.rid,0,'approve','QA approval')
        self.uid=self.store.listing('requests')[0]['user_id']
        self.token,self.csrf=self.store.login('qa_reader','Synthetic-password-42')
        self.cookies={r.core.COOKIE:self.token}

    def tearDown(self): self.temp.cleanup()

    def set_grants(self, **changes):
        current=self.store.permission_state(self.uid); grants=dict(current['modules']);grants.update(changes)
        return self.store.permission_update(self.admin,self.rid,1,current['version'],grants,'QA permission change')

    def login(self):
        self.token,self.csrf=self.store.login('qa_reader','Synthetic-password-42');self.cookies={r.core.COOKIE:self.token}

    def test_existing_defaults_and_native_rules_preserved(self):
        self.assertEqual(permissions.DEFAULT,self.store.permission_state(self.uid)['modules'])
        self.assertEqual(200,self.adapter.verify(self.cookies,'GET','/dashboard/')[0])
        self.assertEqual(403,self.adapter.verify(self.cookies,'PATCH','/dashboard/tasks/api/tasks/1')[0])
        for user in policy.ADMINS:
            token,_=self.adapter.native_login(user,'Synthetic-password-42')
            self.assertEqual(200,self.adapter.verify({'SYNTHETIC_AUTH':token},'DELETE','/dashboard/tasks/api/tasks/1')[0])
        token,_=self.adapter.native_login('native_reader','Synthetic-password-42')
        self.assertEqual(403,self.adapter.verify({'SYNTHETIC_AUTH':token},'PATCH','/dashboard/tasks/api/tasks/1')[0])

    def test_current_nginx_header_contract(self):
        config=(RELEASE/'tests/nginx-taskboard.locations.conf').read_text(encoding='utf-8')
        for line in ['auth_request /__auth_verify;', 'auth_request_set $registration_taskboard_role $upstream_http_x_auth_role;', 'proxy_set_header X-Auth-Role $registration_taskboard_role;', 'proxy_set_header X-Auth-User $auth_user;']:
            self.assertIn(line,config)
        self.assertIn('GET|HEAD|POST|PATCH|DELETE',config)

    def test_module_changes_revoke_sessions_and_survive_restart(self):
        result=self.set_grants(business='none',tasks='editor',green_plan='none')
        self.assertTrue(result['sessions_revoked'])
        self.assertEqual(401,self.adapter.verify(self.cookies,'GET','/dashboard/')[0])
        self.login()
        for uri in ['/dashboard/','/dashboard/tasks/green-plan/','/dashboard/tasks/api/green-plan']:
            self.assertEqual(403,self.adapter.verify(self.cookies,'GET',uri)[0])
        for method,uri in [('GET','/dashboard/tasks/'),('PATCH','/dashboard/tasks/api/tasks/1'),('POST','/dashboard/tasks/api/tasks/1/ack')]:
            code,headers=self.adapter.verify(self.cookies,method,uri)
            self.assertEqual((200,'editor'),(code,headers.get('X-Auth-Role')))
        restarted,adapter,_=r.build(self.root,self.portal,'https://synthetic.invalid',isolated=True)
        self.assertEqual('none',restarted.permission_state(self.uid)['modules']['business'])
        self.assertEqual(403,adapter.verify(self.cookies,'GET','/dashboard/')[0])
        with restarted.connection() as db:self.assertEqual(4,db.execute('PRAGMA user_version').fetchone()[0])
        old=load('permission_old_runtime',BASE/'runtime.py')
        with self.assertRaises(ValueError):old.RuntimeStore(self.root,self.portal,isolated=True)

    def test_exact_write_routes_and_cross_module_denials(self):
        self.set_grants(tasks='none',green_plan='editor');self.login()
        self.assertEqual(200,self.adapter.verify(self.cookies,'PATCH','/dashboard/tasks/api/green-plan/tasks/G01')[0])
        forbidden=[('PATCH','/dashboard/tasks/api/tasks/1'),('POST','/dashboard/tasks/api/tasks'),('DELETE','/dashboard/tasks/api/green-plan/tasks/G01'),('POST','/dashboard/tasks/api/members'),('PATCH','/dashboard/tasks/api/green-plan/tasks/G01?x=1'),('PATCH','/dashboard/tasks/api/green-plan/tasks/%47%30%31'),('PATCH','/dashboard/tasks/api/green-plan/tasks/G01/'),('POST','/tools/fc27-players/api/execute'),('POST','/s/wulv/fc27-ops/api/collect')]
        for method,uri in forbidden:self.assertEqual(403,self.adapter.verify(self.cookies,method,uri)[0],uri)
        self.assertEqual(403,self.adapter.verify(self.cookies,'PATCH','/dashboard/tasks/api/green-plan/tasks/G01','deploy')[0])

    def test_cas_invalid_modes_and_admin_boundary(self):
        grants=dict(permissions.DEFAULT,players='editor')
        with self.assertRaises(r.core.Denied):self.store.permission_update(self.admin,self.rid,1,0,grants,'QA')
        self.set_grants(tasks='editor')
        with self.assertRaises(r.core.Denied):self.store.permission_update(self.admin,self.rid,1,0,permissions.DEFAULT,'stale')
        reader=r.core.LegacyIdentity('native_reader',('dashboard',),'readonly')
        with self.assertRaises(r.core.Denied):self.store.permission_update(reader,self.rid,1,0,permissions.DEFAULT,'QA')
        self.store.decide(self.admin,self.rid,1,'revoke','QA revoke')
        with self.assertRaises(r.core.Denied):self.store.permission_update(self.admin,self.rid,2,0,permissions.DEFAULT,'QA')

    def test_two_process_permission_cas_and_rollback_fence(self):
        command=[sys.executable,'-I','-B',str(Path(__file__)), '--race',str(self.root),self.rid]
        workers=[subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        try:
            for worker in workers:self.assertEqual('READY',worker.stdout.readline().strip())
            for worker in workers:worker.stdin.write('GO\n');worker.stdin.flush()
            results=[]
            for worker in workers:
                worker.stdin.close();worker.stdin=None
                out,err=worker.communicate(timeout=15);self.assertEqual(0,worker.returncode,err);results.append(out.strip())
            self.assertEqual(['denied:409','success'],sorted(results))
            with self.store.connection() as db:
                self.assertEqual(1,db.execute("SELECT COUNT(*) FROM audit WHERE action='permissions'").fetchone()[0])
                self.assertEqual(4,db.execute('PRAGMA user_version').fetchone()[0])
            # A metadata-only rollback cannot silently reactivate the old read policy.
            with closing(sqlite3.connect(self.store.path)) as db:
                db.execute('PRAGMA user_version=3');db.commit()
            self.assertEqual(503,self.adapter.verify(self.cookies,'GET','/dashboard/')[0])
        finally:
            for worker in workers:
                if worker.poll() is None:worker.kill();worker.wait()

    def test_csrf_origin_duplicate_fields_and_permissions_transport(self):
        native,_=self.adapter.native_login('wulv','Synthetic-password-42')
        code,data,headers=self.app.dispatch('GET','/api/bootstrap',cookies={'SYNTHETIC_AUTH':native})
        self.assertEqual(200,code);self.assertEqual(2,sum(m['can_edit'] for m in data['permission_modules']))
        token=headers['Set-Cookie'].split(';',1)[0].split('=',1)[1]
        cookies={'SYNTHETIC_AUTH':native,r.core.COOKIE:token}
        body=dict(request_id=self.rid,request_version=1,version=0,permissions=dict(permissions.DEFAULT,tasks='editor'),reason='QA transport')
        headers={'Origin':'https://synthetic.invalid','X-CSRF-Token':data['csrf'],'Content-Type':'application/json'}
        call=lambda h,b: self.app.dispatch('POST','/api/permissions',headers=h,cookies=cookies,body=b)[0]
        raw=json.dumps(body).encode()
        self.assertEqual(403,call(dict(headers,Origin='https://wrong.invalid'),raw))
        self.assertEqual(403,call(dict(headers,**{'X-CSRF-Token':'wrong'}),raw))
        self.assertEqual(400,call(headers,b'{"reason":"a","reason":"b"}'))
        self.assertEqual(200,call(headers,raw))
        self.assertEqual(409,call(headers,raw))
        self.assertEqual(401,self.adapter.verify(self.cookies,'GET','/dashboard/tasks/')[0])

    def test_real_backend_assignment_fields_and_per_request_roles(self):
        host=load('permission_taskboard',RELEASE/'source/taskboard/taskboard_server.py')
        host.CFG.update(data_dir=self.root,db=self.root/'taskboard.db',seed=self.root/'no-seed',unregistered='deny')
        host.init_db(False);consumer_seams.install_taskboard(host,policy)
        projection=self.set_grants(tasks='editor',green_plan='editor')['member']
        host.op_upsert_member(host.Ctx('wulv','admin'),projection)
        conn=host.db_connect()
        conn.execute("INSERT INTO projects(name,grp) VALUES('QA','QA')");conn.execute("INSERT INTO depts(name) VALUES('QA')");conn.commit();gp.init(conn);conn.close()
        subject='reg:'+self.uid
        gp.mutate(host,host.Ctx('wulv','admin'),dict(expectedRevision=1,assignee=subject),'G01')
        task=host.op_create_task(host.Ctx('wulv','admin'),dict(project='QA',dept='QA',horizon=host.HORIZONS[0],title='QA owned task',assignee=subject,checks=['QA check']))
        self.login()
        outer=self
        class Verifier(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                values={}
                for value in self.headers.get('Cookie','').split(';'):
                    if '=' in value:
                        k,v=value.strip().split('=',1);values[k]=v
                code,headers=outer.adapter.verify(values,self.headers['X-Original-Method'],self.headers['X-Original-URI'],'dashboard')
                self.send_response(code)
                for k,v in headers.items():self.send_header(k,v)
                self.send_header('Content-Length','0');self.end_headers()
        verifier=ThreadingHTTPServer(('127.0.0.1',0),Verifier);server=ThreadingHTTPServer(('127.0.0.1',0),host.Handler)
        for srv in (verifier,server):threading.Thread(target=srv.serve_forever,daemon=True).start()
        original=http.client.HTTPConnection
        def redirect(address,port=None,*args,**kwargs):
            if address=='127.0.0.1' and port==8895:port=verifier.server_port
            return original(address,port,*args,**kwargs)
        def call(method,path,body,extra=None):
            connection=original('127.0.0.1',server.server_port,timeout=5)
            headers={'Cookie':r.core.COOKIE+'='+self.token,'Content-Type':'application/json','Connection':'close','Origin':'http://127.0.0.1:'+str(server.server_port)};headers.update(extra or {})
            connection.request(method,path,json.dumps(body),headers);response=connection.getresponse();status=response.status;response.read();connection.close();return status
        try:
            with patch('http.client.HTTPConnection',redirect):
                self.assertEqual(200,call('PATCH','/api/green-plan/tasks/G01',dict(expectedRevision=2,notes='QA owned update')))
                self.assertEqual(403,call('PATCH','/api/green-plan/tasks/G02',dict(expectedRevision=1,notes='QA unauthorized')))
                self.assertEqual(403,call('PATCH','/api/green-plan/tasks/G01',dict(expectedRevision=3,title='forbidden structure')))
                self.assertEqual(200,call('PATCH','/api/tasks/'+str(task['id']),dict(progress=25)))
                self.assertEqual(403,call('PATCH','/api/tasks/'+str(task['id']),dict(title='forbidden structure')))
                self.assertEqual(403,call('POST','/api/members',dict(username='fake',role='admin')))
                self.assertEqual(403,call('PATCH','/api/tasks/'+str(task['id']),dict(progress=30),{'X-Auth-Role':'admin'}))
                self.set_grants(tasks='readonly',green_plan='editor');self.login()
                self.assertEqual(403,call('PATCH','/api/tasks/'+str(task['id']),dict(progress=30)))
                self.assertEqual(200,call('PATCH','/api/green-plan/tasks/G01',dict(expectedRevision=3,notes='QA module-specific')))
                conn=host.db_connect();conn.execute('UPDATE members SET active=0 WHERE username=?',(subject,));conn.commit();conn.close()
                self.assertEqual(403,call('PATCH','/api/green-plan/tasks/G01',dict(expectedRevision=4,notes='disabled')))
        finally:
            for srv in (server,verifier):srv.shutdown();srv.server_close()

if __name__ == '__main__':
    if sys.argv[1:2] == ['--race']:
        root=Path(sys.argv[2]);rid=sys.argv[3]
        portal=bind_functions({'secret':'Synthetic-only-permission-QA','cookie':'SYNTHETIC_AUTH','secure':True},{'dashboard':str(root/'synthetic-members')},policy)
        store,adapter,_=r.build(root,portal,'https://synthetic.invalid',isolated=True)
        _,actor=adapter.native_login('wulv','Synthetic-password-42')
        print('READY',flush=True);assert sys.stdin.readline().strip()=='GO'
        try:store.permission_update(actor,rid,1,0,dict(permissions.DEFAULT,tasks='editor'),'QA race');print('success')
        except r.core.Denied as exc:print('denied:'+str(exc.code))
    else:unittest.main(verbosity=2)
