"""Synthetic local HTTP: real policy -> verifier -> _ctx -> Green mutation. No real identities."""
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR=Path(os.environ.get('GREEN_AUTH_RUNTIME',str(ROOT/'registration_approval_runtime_v3_20261006')))
BACKEND_DIR=Path(os.environ.get('GREEN_BACKEND',str(ROOT/'green_plan_20261009/backend')))
AUTH_DIR=Path(os.environ.get('GREEN_AUTH_CANDIDATE',str(ROOT/'green_plan_review_fix_20261009/source/auth')))
sys.path.insert(0,str(RUNTIME_DIR))
sys.path.insert(0,str(BACKEND_DIR))
import runtime
import consumer_seams
import green_plan as gp

def load(name, file):
    spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
policy=load('fixed_policy',AUTH_DIR/'native_access_policy.py')
host=load('auth_flow_taskboard',BACKEND_DIR/'taskboard_server.py')
guard=runtime.RouteGuard(json.loads((AUTH_DIR/'route-contract.json').read_text(encoding='utf-8')))
checks=[]
def check(name, value):
    assert value,name
    checks.append({'name':name,'passed':True})
REG='reg:12345678-1234-1234-1234-123456789abc'
verified=[]
class Verifier(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        user=self.headers.get('Cookie','');method=self.headers['X-Original-Method'];uri=self.headers['X-Original-URI'];verified.append((user,method,uri))
        status=(200 if guard.allowed(method,uri,'dashboard') else 403) if user.startswith('reg:') else policy.authorize(user,method,uri,'dashboard')
        self.send_response(status)
        if status==200:
            self.send_header('X-Auth-User',user);self.send_header('X-Auth-Role','admin' if user in policy.ADMINS else 'readonly')
        self.send_header('Content-Length','0');self.end_headers()

def run():
    reads=[p for p in guard.paths if '/green-plan' in p]
    check('8 exact registered Green reads',len(reads)==8)
    for p in reads:
        for method in ('GET','HEAD'): check('registered '+method+' '+p,guard.allowed(method,p,'dashboard'))
        for method in ('POST','PATCH'):check('registered rejects '+method+' '+p,not guard.allowed(method,p,'dashboard'))
    for p in ('/dashboard/tasks/green-plan/evil','/dashboard/tasks/api/green-plan/tasks/G01','/dashboard/tasks/api/members', '/dashboard/tasks/api/green-plan?action=run','/dashboard/tasks/green-plan/app.js?cmd=deploy','/dashboard/tasks/green-plan/%2e%2e/api/members'):
        check('registered rejects '+p,not guard.allowed('GET',p,'dashboard'))
    for p in ('/dashboard/tasks/api/tasks/1','/tools/fc27-players/api/models/1','/d4/api/price','/dashboard/tasks/api/green-plan/tasks/G01?x=1','/dashboard/tasks/api/green-plan/tasks/G01/','/dashboard/tasks/api/green-plan/tasks/%47%30%31'):
        check('native write remains denied '+p,policy.authorize('editor','PATCH',p,'dashboard')==403)
    check('registered cannot use native exception',policy.authorize(REG,'PATCH','/dashboard/tasks/api/green-plan/tasks/G01')==403)
    with tempfile.TemporaryDirectory() as tmp:
        host.CFG.update(data_dir=Path(tmp),db=Path(tmp)/'db.sqlite',seed=Path(tmp)/'absent',unregistered='deny')
        host.init_db(False);consumer_seams.install_taskboard(host,policy)
        conn=host.db_connect();gp.init(conn)
        for user,role,active in [('editor','editor',1),('viewer','viewer',1),('disabled','editor',0)]:
            conn.execute("INSERT INTO members(username,role,active,created_at,updated_at) VALUES(?,?,?,'x','x')",(user,role,active))
        conn.commit();conn.close()
        gp.mutate(host,host.Ctx('wulv','admin'),{'expectedRevision':1,'assignee':'editor'},'G01')
        verifier=ThreadingHTTPServer(('127.0.0.1',0),Verifier);server=ThreadingHTTPServer(('127.0.0.1',0),host.Handler)
        for srv in (verifier,server):threading.Thread(target=srv.serve_forever,daemon=True).start()
        original=http.client.HTTPConnection
        def redirect(address,port=None,*args,**kwargs):
            if address=='127.0.0.1' and port==8895:port=verifier.server_port
            return original(address,port,*args,**kwargs)
        def call(user, payload, code='G01',origin=None, extra=None):
            c=original('127.0.0.1',server.server_port,timeout=5)
            headers={'Cookie':user,'Connection':'close','Content-Type':'application/json','Origin':origin or 'http://127.0.0.1:'+str(server.server_port)};headers.update(extra or {})
            c.request('PATCH','/api/green-plan/tasks/'+code,json.dumps(payload),headers);r=c.getresponse();status=r.status;r.read();c.close();return status
        try:
            with patch('http.client.HTTPConnection',redirect):
                check('real editor PATCH authorize verification context mutation succeeds',call('editor',{'expectedRevision':2,'notes':'synthetic editor update'})==200)
                check('verification derived actual PATCH public route',('editor','PATCH','/dashboard/tasks/api/green-plan/tasks/G01') in verified)
                for user in ('viewer','disabled','unknown',REG):check(user+' write rejected',call(user,{'expectedRevision':3,'notes':'reject'})==403)
                for name,payload,code,origin,status in [('other task',{'expectedRevision':1,'notes':'x'},'G02',None,403),('structure',{'expectedRevision':3,'support':'x'},'G01',None,403),('done',{'expectedRevision':3,'status':'done','evidence':'x'},'G01',None,403),('bad Origin',{'expectedRevision':3,'notes':'x'},'G01','https://evil.test',403),('old revision',{'expectedRevision':2,'notes':'x'},'G01',None,409)]:
                    check(name+' rejected',call('editor',payload,code,origin)==status)
                check('spoof identity rejected',call('editor',{'expectedRevision':3,'notes':'x'},extra={'X-Auth-User':'wulv','X-Auth-Role':'admin'})==403)
                gp.mutate(host,host.Ctx('wulv','admin'),{'expectedRevision':3,'status':'done','evidence':'synthetic proof'},'G01')
                check('already done editor rejected',call('editor',{'expectedRevision':4,'notes':'x'})==403)
            conn=host.db_connect();task=gp.all_tasks(conn)['G01'];check('denied attempts preserved revision and editor note',task['revision']==4 and task['notes']=='synthetic editor update');conn.close()
        finally:
            for srv in (server,verifier):srv.shutdown();srv.server_close()
    result={'scope':'synthetic local HTTP; real policy, RouteGuard, consumer_seams, identity verification, Handler._ctx and Green mutate; cookies are fake subject labels; only 8895 connection remapped to ephemeral verifier; no production config or real identities', 'checks':checks}
    Path(__file__).with_name('auth-flow-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(len(checks))+' auth flow checks passed')
if __name__=='__main__':run()
