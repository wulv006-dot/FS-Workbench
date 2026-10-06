"""Real local HTTP and native-source authentication; no resolver mocks or real credentials."""
import concurrent.futures
import hashlib
from http.cookies import SimpleCookie
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
import sys

from auth_candidate import COOKIE, PREFIX, Denied, Store, LegacyIdentity
from integrated_server import Environment, create_server, SYNTHETIC_PASSWORD
from native_integration import PORTAL_COOKIE, bind_functions, policy


class Client:
    def __init__(self, server):
        self.server=server;self.cookies={};self.csrf=''
    def call(self,method,path,data=None,extra=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        headers={'Origin':f'http://127.0.0.1:{self.server.server_port}',
                 'Content-Type':'application/json','X-CSRF-Token':self.csrf,
                 'Cookie':'; '.join(k+'='+v for k,v in self.cookies.items())}
        headers.update(extra or {})
        conn.request(method,path,body=json.dumps(data or {}).encode() if method=='POST' else None,headers=headers)
        response=conn.getresponse();raw=response.read();code=response.status
        for key,value in response.getheaders():
            if key.lower()=='set-cookie':
                jar=SimpleCookie();jar.load(value)
                for name,item in jar.items(): self.cookies[name]=item.value
        result=json.loads(raw) if raw else {}
        if isinstance(result,dict) and 'csrf' in result:self.csrf=result['csrf']
        conn.close();return code,result
    def boot(self):
        code,result=self.call('GET',PREFIX+'/api/bootstrap');assert code==200,(code,result);return result
    def native(self,name):
        self.boot();return self.call('POST',PREFIX+'/api/native-login',{'username':name,'password':SYNTHETIC_PASSWORD})
    def registered(self,name='integration.reader'):
        self.boot()
        code,result=self.call('POST',PREFIX+'/api/register',{'username':name,'password':SYNTHETIC_PASSWORD,'team':'Synthetic integration','purpose':'Source-bound integration'})
        assert code==200,(code,result)
        rid=result['request_id']
        code,_=self.call('POST',PREFIX+'/api/login',{'username':name,'password':SYNTHETIC_PASSWORD});assert code==200
        return rid


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='fs-registration-')
        self.secret='synthetic-test-key-only-32-characters'
        self.env=Environment(self.tmp.name,self.secret)
        self.start()
    def start(self):
        self.server=create_server(self.env)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
    def tearDown(self):
        self.stop();self.env.close();self.tmp.cleanup()
    def admin(self,name=None):
        client=Client(self.server)
        self.assertEqual(client.native(name or sorted(policy.ADMINS)[0])[0],200)
        client.boot();return client
    def decide(self,admin,rid,version=0,action='approve'):
        route='revoke' if action=='revoke' else 'decision'
        data={'request_id':rid,'version':version,'reason':'Synthetic source-verified admin'}
        if route=='decision':data['action']=action
        return admin.call('POST',PREFIX+'/api/'+route,data)

    def test_full_http_pending_admin_approval_uuid_readonly_revoke(self):
        user=Client(self.server);rid=user.registered()
        self.assertEqual(user.call('GET','/dashboard/tasks/api/projects')[0],403)
        self.assertEqual(user.call('GET',PREFIX+'/api/requests')[0],403)
        admin=self.admin();self.assertEqual(self.decide(admin,rid)[0],200)
        code,result=user.call('GET','/dashboard/tasks/api/projects')
        self.assertEqual(code,200);self.assertTrue(result['subject'].startswith('reg:'))
        self.assertEqual(result['consumerRole'],'viewer');self.assertEqual(result['portalRole'],'readonly')
        for method,path in (('POST','/dashboard/tasks/api/projects'),('GET','/dashboard/tasks/api/projects?cmd='),
                            ('GET','/dashboard/tasks/api/admin'),('GET','/unreviewed')):
            self.assertEqual(user.call(method,path,extra={'X-Auth-User':'fstech','X-Auth-Role':'admin','X-Original-Method':'GET'})[0],403)
        self.assertEqual(self.decide(admin,rid,1,'revoke')[0],200)
        self.assertEqual(user.call('GET','/dashboard/tasks/api/projects')[0],401)

    def test_all_policy_admins_and_existing_native_readonly_use_real_source(self):
        self.assertEqual(len(policy.ADMINS),4)
        for name in policy.ADMINS:
            admin=self.admin(name)
            self.assertEqual(admin.call('GET',PREFIX+'/api/requests')[0],200)
            self.assertEqual(admin.call('POST','/dashboard/tasks/api/projects')[1]['consumerRole'],'admin')
        reader=Client(self.server);self.assertEqual(reader.native('synthetic.native.reader')[0],200)
        self.assertEqual(reader.call('GET','/dashboard/tasks/api/projects')[0],200)
        self.assertEqual(reader.call('POST','/dashboard/tasks/api/projects')[0],403)
        self.assertEqual(reader.call('GET',PREFIX+'/api/requests')[0],403)

    def test_native_signature_expiry_live_groups_and_unavailability(self):
        admin=self.admin();token=admin.cookies[PORTAL_COOKIE]
        self.assertIsNotNone(self.env.portal.read_token(token))
        admin.cookies[PORTAL_COOKIE]=token[:-2]+'xx'
        self.assertEqual(admin.call('GET','/dashboard/tasks/api/projects')[0],401)
        admin.cookies[PORTAL_COOKIE]=self.env.portal.make_token(sorted(policy.ADMINS)[0],['dashboard'], -10)
        self.assertEqual(admin.call('GET','/dashboard/tasks/api/projects')[0],401)
        admin.cookies[PORTAL_COOKIE]=token
        target=sorted(policy.ADMINS)[0]
        with self.env.namespace.fence():
            for path in self.env.portal.GROUPS.values():
                p=Path(path);p.write_text(''.join(line for line in p.read_text().splitlines(True) if not line.startswith(target+':')),encoding='utf-8')
            self.env.portal._ht_cache.clear()
        self.assertEqual(admin.call('GET','/dashboard/tasks/api/projects')[0],401)
        Path(self.env.portal.GROUPS['deploy']).unlink()
        user=Client(self.server);user.boot()
        code,_=user.call('POST',PREFIX+'/api/register',{'username':'source.failure','password':SYNTHETIC_PASSWORD,'team':'t','purpose':'p'})
        self.assertEqual(code,503)

    def test_same_name_concurrent_native_and_registered_creators_fenced(self):
        barrier=threading.Barrier(2)
        def create(kind):
            barrier.wait(timeout=5)
            try:
                if kind=='native':self.env.namespace.create_native('collision.reader',SYNTHETIC_PASSWORD)
                else:self.env.store.register('collision.reader',SYNTHETIC_PASSWORD,'t','p')
                return 200
            except Denied as exc:return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(create,('native','registered'))),[200,409])

    def test_signed_group_claim_does_not_grant_admin_and_policy_is_source_behavior(self):
        reader=Client(self.server);reader.boot()
        reader.cookies[PORTAL_COOKIE]=self.env.portal.make_token('synthetic.native.reader',['dashboard','deploy'],43200)
        self.assertEqual(reader.call('GET',PREFIX+'/api/requests')[0],401) # csrf binding differs
        reader.boot();self.assertEqual(reader.call('GET',PREFIX+'/api/requests')[0],403)
        self.assertEqual(reader.call('POST','/dashboard/tasks/api/projects')[0],403)
        original=policy.ADMINS
        name=sorted(original)[0];admin=self.admin(name)
        try:
            policy.ADMINS=original-{name}
            self.assertEqual(admin.boot()['account']['role'],'readonly')
            self.assertEqual(admin.call('GET',PREFIX+'/api/requests')[0],403)
        finally:policy.ADMINS=original

    def test_double_principals_fail_closed_and_logout_clears_revokes_both(self):
        user=Client(self.server);user.registered();admin=self.admin()
        copied=admin.cookies[PORTAL_COOKIE]
        user.cookies[PORTAL_COOKIE]=copied
        self.assertEqual(user.call('GET',PREFIX+'/api/bootstrap')[0],403)
        self.assertEqual(user.call('GET','/dashboard/tasks/api/projects')[0],403)
        self.assertEqual(user.call('POST',PREFIX+'/api/logout',{})[0],200)
        self.assertEqual(user.cookies[COOKIE],'');self.assertEqual(user.cookies[PORTAL_COOKIE],'')
        admin.cookies[PORTAL_COOKIE]=copied
        self.assertEqual(admin.call('GET','/dashboard/tasks/api/projects')[0],401)

    def test_restart_preserves_approvals_revocation_and_history(self):
        user=Client(self.server);rid=user.registered();admin=self.admin()
        self.decide(admin,rid);old_cookies=user.cookies.copy()
        self.decide(admin,rid,1,'revoke')
        admin.call('POST',PREFIX+'/api/logout',{})
        self.stop();self.env.close();self.env=Environment(self.tmp.name,self.secret);self.start()
        user.server=self.server;user.cookies=old_cookies
        self.assertEqual(user.call('GET','/dashboard/tasks/api/projects')[0],401)
        self.assertEqual([a['action'] for a in self.env.store.listing('audit')],['register','approve','revoke'])
        self.assertEqual(self.env.store.listing('requests')[0]['purpose'],'Source-bound integration')
        self.assertEqual(self.env.store.listing('requests')[0]['status'],'revoked')

    def test_additive_schema2_migration_and_unknown_version_refused(self):
        rid=self.env.store.register('migration.reader',SYNTHETIC_PASSWORD,'t','Purpose schema2')['request_id']
        with self.env.store.transaction() as db:
            db.execute('DROP TABLE native_revocations');db.execute('PRAGMA user_version=2')
        self.stop();self.env.close();self.env=Environment(self.tmp.name,self.secret);self.start()
        self.assertEqual(next(r for r in self.env.store.listing('requests') if r['id']==rid)['purpose'],'Purpose schema2')
        with self.env.store.connection() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
        with self.env.store.transaction() as db:db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):Store(self.tmp.name,reserved_names=lambda:set(),allow_existing=True)

    def test_http_csrf_header_spoof_and_old_fc_cookie_not_accepted(self):
        user=Client(self.server);user.boot()
        self.assertEqual(user.call('POST',PREFIX+'/api/native-login',{'username':sorted(policy.ADMINS)[0],'password':SYNTHETIC_PASSWORD},extra={'X-CSRF-Token':'invalid'})[0],403)
        user.cookies['fc27sess']='synthetic-old-fc-cookie'
        self.assertEqual(user.call('GET','/dashboard/tasks/api/projects',extra={'X-Auth-User':sorted(policy.ADMINS)[0],'X-Auth-Role':'admin'})[0],401)
        self.assertEqual(user.call('GET','/__auth/verify')[0],401)

    def test_multiprocess_native_registered_namespace_collision(self):
        script = '''
import sys
from integrated_server import Environment,SYNTHETIC_PASSWORD
from auth_candidate import Denied
env=Environment(sys.argv[1], 'synthetic-child-process-key-only-32')
try:
    if sys.argv[2]=='native': env.namespace.create_native('process.collision',SYNTHETIC_PASSWORD)
    else: env.store.register('process.collision',SYNTHETIC_PASSWORD,'t','p')
    print(200)
except Denied as exc: print(exc.code)
finally: env.close()
'''
        processes=[subprocess.Popen([sys.executable,'-c',script,self.tmp.name,mode],
            cwd=Path(__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            for mode in ('native','registered')]
        results=[]
        for process in processes:
            stdout,stderr=process.communicate(timeout=20)
            self.assertEqual(process.returncode,0,stderr)
            results.append(int(stdout.strip()))
        self.assertEqual(sorted(results),[200,409])

    def test_namespace_creator_cannot_grant_admin_and_uuid_consumer_not_name_lookup(self):
        from native_integration import taskboard_role
        for name in policy.ADMINS:
            with self.assertRaises(Denied):self.env.namespace.create_native(name.upper(),SYNTHETIC_PASSWORD)
        with self.assertRaises(Denied):taskboard_role(self.env.consumer,'reg:fstech','readonly')
        with self.assertRaises(Denied):taskboard_role(self.env.consumer,'reg:00000000-0000-0000-0000-000000000001','admin')

    def test_restart_preserves_approved_uuid_and_native_logout_denylist(self):
        user=Client(self.server);rid=user.registered();admin=self.admin()
        self.decide(admin,rid)
        subject=user.call('GET','/dashboard/tasks/api/projects')[1]['subject']
        native_copy=admin.cookies[PORTAL_COOKIE]
        admin.call('POST',PREFIX+'/api/logout',{})
        self.stop();self.env.close();self.env=Environment(self.tmp.name,self.secret);self.start()
        user.server=self.server
        code,result=user.call('GET','/dashboard/tasks/api/projects')
        self.assertEqual(code,200);self.assertEqual(result['subject'],subject)
        restored_native=Client(self.server);restored_native.cookies[PORTAL_COOKIE]=native_copy
        self.assertEqual(restored_native.call('GET','/dashboard/tasks/api/projects')[0],401)


if __name__=='__main__':unittest.main(verbosity=2)
