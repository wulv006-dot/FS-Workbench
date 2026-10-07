"""One isolated QA run of reviewed caller seams + full Nginx auth round trips.

Thin runner: consumes existing approved QA inputs, never fetches/copies production
source, installs dependencies, invokes SSH/systemctl/Git, or runs the old 43+4.
Fixed production paths/ports are mapped only inside QA workers/config projections.
Source bytes remain unchanged. Actual production systemd/TLS/UID are separate gates.
"""
import argparse
import ast
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time

REVIEW_MANIFEST_SHA = '722757c03619bd0bc2d33301782ee38f31d0d993243b9b7465b89c6fdba5f1ed'
SET_SHA = '45254c1e33afc9481f45da65ea90ef14c88c560ac51c4852b2be3b377f2226a3'
RUNTIME_PATH = '/opt/auth-portal/registration-runtime/20261007-ca6258ad'
ORIGIN = 'https://47.85.224.112'
PASSWORD = 'Synthetic-password-42'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_inputs(root):
    root = root.resolve(strict=True)
    manifest = root/'review-input-manifest.json'
    if sha(manifest) != REVIEW_MANIFEST_SHA: raise ValueError('review input manifest drift')
    inputs = json.loads(manifest.read_bytes())
    for row in inputs['input_files']:
        path = root/row['path']
        if root not in path.resolve(strict=True).parents or path.is_symlink():
            raise ValueError('linked/escaping input')
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('reviewed input drift: '+row['path'])
    release = json.loads((root/'release-manifest.json').read_bytes())
    if release['payload_content_set_sha256'] != SET_SHA: raise ValueError('candidate drift')
    if len(list(p for p in (root/'payload').rglob('*') if p.is_file())) != 21:
        raise ValueError('unexpected payload file')
    return release


def load_candidate(root, kind):
    runtime_root = root/'payload'/RUNTIME_PATH.lstrip('/')
    sys.path.insert(0,str(runtime_root))
    import portal_bridge
    import runtime
    import native_access_policy
    native_spec = importlib.util.spec_from_file_location
    def spec(name, location, *a, **kw):
        if location == '/opt/fs-access-policy/access_policy.py':
            location = runtime_root/'vendor/native_access_policy.py'
        return native_spec(name,location,*a,**kw)
    importlib.util.spec_from_file_location = spec
    path = {'portal':'payload/opt/auth-portal/auth_portal.py',
            'recovery':'recovery/opt/auth-portal/auth_portal.py',
            'fc':'payload/opt/fc27-gate/fc27_gate.py',
            'board':'payload/opt/mmoexp-taskboard/taskboard_server.py'}[kind]
    module_spec = native_spec('qa_'+kind,root/path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    original_isdir = os.path.isdir
    os.path.isdir = lambda p: runtime_root.is_dir() if p == RUNTIME_PATH else original_isdir(p)
    # Explicit synthetic RuntimeStore boundary; no change to installed source.
    install = portal_bridge.install
    portal_bridge.install = lambda m,origin: install(m,origin,isolated=True)
    return module,runtime,native_access_policy


def trace(data):
    with open(os.environ['FS_QA_TRACE'],'a',encoding='utf-8') as stream:
        stream.write(json.dumps(data,separators=(',',':'))+'\n')


def worker(root, kind, fd):
    module,runtime,policy = load_candidate(root,kind)
    original_http = http.client.HTTPConnection
    portal_port = int(os.environ['FS_QA_PORTAL_PORT'])
    def http(host,port=None,*a,**kw):
        if host != '127.0.0.1' or port != 8895:
            raise ValueError('worker outbound connection outside global QA verifier')
        return original_http(host,portal_port,*a,**kw)
    http.client.HTTPConnection = http
    actual_server = module.ThreadingHTTPServer
    owned = socket.socket(fileno=fd)
    address = owned.getsockname()
    def server(bind,handler):
        if tuple(bind) != address: raise ValueError('candidate bind outside owned QA loopback')
        result = actual_server(bind,handler,bind_and_activate=False)
        result.socket.close()
        result.socket = owned
        result.server_address = address
        result.server_name = 'localhost'
        result.server_port = address[1]
        result.server_activate()
        return result
    module.ThreadingHTTPServer = server
    if kind in ('portal','recovery'):
        import portal_bridge
        original_bridge_verify = portal_bridge.Bridge.verify
        def wire_verify(bridge,handler,group=''):
            original_send = handler._send
            def send(code,*a,**kw):
                trace({'kind':'portal-verify-wire','method':handler.headers.get('X-Original-Method'),
                       'uri':handler.headers.get('X-Original-URI'),'status':code})
                return original_send(code,*a,**kw)
            handler._send = send
            try: return original_bridge_verify(bridge,handler,group)
            finally: handler._send = original_send
        portal_bridge.Bridge.verify = wire_verify
        original_verify = runtime.RuntimeAdapter.verify
        def verify(adapter,cookies,method,uri,group=''):
            code,headers = original_verify(adapter,cookies,method,uri,group)
            trace({'kind':'verify','method':method,'uri':uri,'status':code,
                   'role':headers.get('X-Auth-Role'),'groups':headers.get('X-Auth-Groups')})
            return code,headers
        runtime.RuntimeAdapter.verify = verify
    elif kind == 'board':
        ctx = module.Handler._ctx
        def observed(handler):
            trace({'kind':'board-input','method':handler.command,'path':handler.path,
                   'user':handler.headers.get('X-Auth-User'),
                   'role':handler.headers.get('X-Auth-Role'),
                   'groups':handler.headers.get('X-Auth-Groups')})
            return ctx(handler)
        module.Handler._ctx = observed
    print(json.dumps({'worker':kind,'pid':os.getpid(),'python':sys.version.split()[0],
                      'sqlite':sqlite3.sqlite_version,'source_sha256':sha(module.__file__)}),flush=True)
    module.main([]) if kind == 'board' else module.main()


def port_socket():
    result = socket.socket()
    result.bind(('127.0.0.1',0))
    return result


def full_nginx(root, scratch, ports):
    evidence = json.loads((root/'live-evidence-complete.json').read_bytes())
    configs = {}
    for target in evidence['nginx_configs']:
        candidate = root/'payload'/target.lstrip('/')
        configs[target] = (candidate if candidate.is_file() else root/'live-config'/target.lstrip('/')).read_text(encoding='utf-8')
    used = []
    def expand(path):
        used.append(path)
        text = configs[path]
        def include(match):
            target = match.group(1)
            names = ['/etc/nginx/conf.d/iggm-web.conf'] if target == '/etc/nginx/conf.d/*.conf' else [target]
            if any(name not in configs for name in names): raise ValueError('unresolved include')
            return '\n'.join(expand(name) for name in names)
        return re.sub(r'(?m)^\s*include\s+([^;\s]+)\s*;\s*$',include,text)
    text = expand('/etc/nginx/nginx.conf')
    if len(used) != 10 or set(used) != set(configs): raise ValueError('incomplete include closure')
    # QA-only environmental projection. Routing, auth, methods, headers and
    # directive order are retained; untested business upstreams are disabled.
    text = re.sub(r'(?m)^\s*user\s+[^;]+;','',text)
    text = re.sub(r'(?m)^\s*worker_processes\s+[^;]+;','worker_processes 1;',text)
    text = re.sub(r'(?m)^\s*error_log\s+[^;]+;','error_log stderr warn;',text)
    text = re.sub(r'(?m)^\s*access_log\s+[^;]+;','access_log off;',text)
    text = re.sub(r'(?m)^\s*pid\s+[^;]+;','pid '+str(scratch/'nginx.pid')+';',text)
    text = text.replace('listen 80 default_server;', 'listen 127.0.0.1:%d default_server;'%ports['http'])
    text = text.replace('listen 443 ssl;', 'listen 127.0.0.1:%d ssl;'%ports['https'])
    text = text.replace('listen [::]:80 default_server;', '')
    text = text.replace('/etc/letsencrypt/live/47.85.224.112/fullchain.pem',str(scratch/'cert.pem'))
    text = text.replace('/etc/letsencrypt/live/47.85.224.112/privkey.pem',str(scratch/'key.pem'))
    def upstream(match):
        destination = match.group(1)
        found = re.fullmatch(r'http://127\.0\.0\.1:(\d+)(.*)',destination)
        if not found: raise ValueError('non-loopback/variable upstream requires explicit QA projection')
        replacements = {8895:ports['portal'],8896:ports['fc'],8932:ports['board']}
        return 'proxy_pass http://127.0.0.1:%d%s;'%(replacements.get(int(found.group(1)),ports['blocked']),found.group(2))
    text = re.sub(r'proxy_pass\s+([^;\s]+)\s*;',upstream,text)
    text = re.sub(r'(?m)^(\s*)(root|alias)\s+([^;]+);',
                  lambda m:m.group(1)+m.group(2)+' '+str(scratch/'empty-web')+('/' if m.group(3).strip().endswith('/') else '')+';',text)
    text = text.replace('http {','http {\n client_body_temp_path '+str(scratch/'client-temp')+';\n proxy_temp_path '+str(scratch/'proxy-temp')+';\n fastcgi_temp_path '+str(scratch/'fastcgi-temp')+';\n uwsgi_temp_path '+str(scratch/'uwsgi-temp')+';\n scgi_temp_path '+str(scratch/'scgi-temp')+';',1)
    qa_user = 'user root;\n' if getattr(os,'geteuid',lambda:1)() == 0 else ''
    return 'daemon off;\n'+qa_user+text,used


def run(args):
    root = args.reviewed_root.resolve(strict=True)
    release = verify_inputs(root)
    if args.check_only:
        for path in (Path(__file__),root/'test_release_delta.py'):
            ast.parse(path.read_text(encoding='utf-8'),feature_version=(3,9))
        print(json.dumps({'status':'PREPARED_ONLY','verified_inputs':47,'candidate_set':SET_SHA,
                          'python39_syntax':True,'linux_nginx_execution':False}))
        return 0
    if sys.platform != 'linux' or sys.version_info[:3] != (3,9,18) or sqlite3.sqlite_version != '3.53.4':
        raise ValueError('requires existing authorized Linux Python3.9.18 + SQLite3.53.4')
    nginx = args.nginx.resolve(strict=True)
    version = subprocess.run([str(nginx),'-V'],capture_output=True,text=True,timeout=5)
    if 'nginx/1.26.1' not in version.stderr or '--with-http_auth_request_module' not in version.stderr or '--with-http_ssl_module' not in version.stderr:
        raise ValueError('requires existing Nginx1.26.1 auth_request + ssl modules')
    if not args.openssl: raise ValueError('existing openssl path required; no dependency install')
    output = args.output.resolve()
    if output.exists(): raise ValueError('fresh QA receipt path required')
    children=[]; handles=[]; worker_logs=[]; checks=[]; receipt={'status':'RUNNING','synthetic_only':True,'production_write':False,'old43plus4_rerun':False,
        'candidate_set':SET_SHA,'python':sys.version,'sqlite':sqlite3.sqlite_version,
        'kernel':os.uname().release,'nginx':'1.26.1','source_modified':False}
    deadline = time.monotonic()+120
    def check(name,condition):
        if not condition: raise AssertionError(name)
        checks.append(name)
    def stop(child):
        if child.poll() is None:
            try: os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError: pass
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait(timeout=5)
    with tempfile.TemporaryDirectory(prefix='fs-registration-seamqa-') as temp:
        scratch=Path(temp); os.chmod(scratch,0o700)
        data=scratch/'fs-registration-data';data.mkdir(mode=0o700)
        (scratch/'empty-web').mkdir();(scratch/'board').mkdir()
        (scratch/'login.html').write_text('Synthetic native login template',encoding='utf-8')
        (scratch/'analysis.json').write_text('{"synthetic":true}',encoding='utf-8')
        (scratch/'board-seed.json').write_text(json.dumps({'groups':[],'depts':[],'tasks':[],
            'members':[{'username':'oldreader','role':'editor','displayName':'Synthetic reader'}]}),encoding='utf-8')
        tracefile=scratch/'trace.jsonl';tracefile.touch(mode=0o600)
        sockets={name:port_socket() for name in ('portal','fc','board','http','https','blocked')}
        ports={name:s.getsockname()[1] for name,s in sockets.items()}
        env={k:v for k,v in os.environ.items() if k in ('PATH','LD_LIBRARY_PATH','LANG','LC_ALL','TMPDIR')}
        env.update({'AUTH_DATA_DIR':str(data),'AUTH_SECRET':'Synthetic-secret-for-isolated-seam-QA',
            'AUTH_GROUPS':'dashboard='+str(scratch/'synthetic-members'),'AUTH_COOKIE_SECURE':'1',
            'AUTH_TEMPLATE':str(scratch/'login.html'),'AUTH_PORT':str(ports['portal']),
            'AUTH_BIND':'127.0.0.1','FC27_PORT':str(ports['fc']),'FC27_DB':str(scratch/'never-create-old-FC.sqlite3'),
            'FC27_ANALYSIS':str(scratch/'analysis.json'),'TASKBOARD_PORT':str(ports['board']),
            'TASKBOARD_BIND':'127.0.0.1','TASKBOARD_DATA':str(scratch/'board'),
            'TASKBOARD_SEED':str(scratch/'board-seed.json'),
            'FS_QA_TRACE':str(tracefile),'FS_QA_PORTAL_PORT':str(ports['portal']),'PYTHONDONTWRITEBYTECODE':'1'})
        def start(kind, secure=True):
            log=scratch/(kind+'-'+str(len(children))+'.log')
            handle=open(log,'wb'); handles.append(handle)
            childenv=dict(env,AUTH_COOKIE_SECURE='1' if secure else '0')
            child=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--reviewed-root',str(root),
                '--worker',kind,'--fd',str(sockets['portal' if kind=='recovery' else kind].fileno())],env=childenv,
                stdout=handle,stderr=handle,pass_fds=(sockets['portal' if kind=='recovery' else kind].fileno(),),start_new_session=True)
            children.append(child);worker_logs.append(log); return child
        try:
            missing=start('portal');check('missing-store process exits before listen',missing.wait(timeout=5)!=0)
            check('missing-store boot never first-initializes',not (data/'registration-approval').exists() and not (data/'.registration-checkpoint').exists())
            previous=dict(os.environ);os.environ.clear();os.environ.update(env)
            portal,runtime,policy=load_candidate(root,'portal')
            encoded=portal.apr1_md5(PASSWORD,'qa123456')
            (scratch/'synthetic-members').write_text('\n'.join(n+':'+encoded for n in (*policy.ADMINS,'oldreader'))+'\n',encoding='utf-8')
            runtime.RuntimeStore.initialize_fresh(data,portal,isolated=True)
            store,adapter,app=runtime.build(data,portal,ORIGIN,isolated=True)
            native={n:adapter.native_login(n,PASSWORD)[0] for n in (*policy.ADMINS,'oldreader')}
            _,proof=adapter.native_login('fstech',PASSWORD)
            request=store.register('newreader',PASSWORD,'QA','Synthetic seam fixture')
            store.decide(proof,request['request_id'],0,'approve','Synthetic seam approval')
            registered,_=store.login('newreader',PASSWORD)
            os.environ.clear();os.environ.update(previous)
            insecure=start('portal',False);check('insecure-cookie process exits before listen',insecure.wait(timeout=5)!=0)
            portal_child=start('portal');fc_child=start('fc');board_child=start('board')
            def owned_listener(child,port):
                if child.poll() is not None:return False
                fds=[]
                for p in Path('/proc/%d/fd'%child.pid).iterdir():
                    try:fds.append(os.readlink(p))
                    except OSError:pass
                for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
                    fields=line.split()
                    if int(fields[1].split(':')[1],16)==port and fields[3]=='0A' and 'socket:['+fields[9]+']' in fds:return True
                return False
            def ready(child,port):
                while time.monotonic()<deadline:
                    if owned_listener(child,port):return
                    if child.poll() is not None:raise RuntimeError('owned QA service failed to start')
                    time.sleep(0.05)
                raise TimeoutError('bounded QA startup deadline')
            for child,name in ((portal_child,'portal'),(fc_child,'fc'),(board_child,'board')):ready(child,ports[name])
            cert=subprocess.run([str(args.openssl), 'req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                '-subj','/CN=synthetic.invalid','-keyout',str(scratch/'key.pem'),'-out',str(scratch/'cert.pem')],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            check('synthetic TLS fixture created',cert.returncode==0)
            config,closure=full_nginx(root,scratch,ports); configfile=scratch/'nginx.conf';configfile.write_text(config,encoding='utf-8')
            parsed=subprocess.run([str(nginx),'-e','stderr','-p',str(scratch)+'/', '-c',str(configfile),'-t'],
                capture_output=True,timeout=10)
            check('full master + all10 includes native Nginx parse',parsed.returncode==0)
            receipt['full_include_count']=len(closure);receipt['QA_projection_sha256']=sha(configfile)
            sockets['http'].close();sockets['https'].close()
            handle=open(scratch/'nginx.log','wb');handles.append(handle)
            proxy=subprocess.Popen([str(nginx),'-e','stderr','-p',str(scratch)+'/', '-c',str(configfile)],
                stdout=handle,stderr=handle,start_new_session=True);children.append(proxy)
            ready(proxy,ports['http']);ready(proxy,ports['https'])
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
            def request_http(path,method='GET',cookie='',headers=None,tls=True,port=None):
                if time.monotonic()>deadline:raise TimeoutError('bounded QA request deadline')
                if path not in ('/__auth/access/','/__auth/access/api/bootstrap','/dashboard/tasks/api/session?probe=%2F',
                                '/dashboard/tasks/api/members','/fc27/verify','/fc27/analysis','/api/session','/__auth/logout'):
                    raise ValueError('request outside finite synthetic route allowlist')
                target=port or ports['https' if tls else 'http']
                conn=http.client.HTTPSConnection('127.0.0.1',target,context=context,timeout=3) if tls else http.client.HTTPConnection('127.0.0.1',target,timeout=3)
                values={'Host':'47.85.224.112','Cookie':cookie};values.update(headers or {})
                try:
                    conn.request(method,path,headers=values);response=conn.getresponse();body=response.read(1048576)
                    return response.status,dict(response.getheaders()),body
                finally:conn.close()
            status,headers,_=request_http('/__auth/access/',tls=False)
            check('HTTP auth entry 308 fixed HTTPS',status==308 and headers.get('Location')==ORIGIN+'/__auth/access/')
            check('HTTPS access static200',request_http('/__auth/access/')[0]==200)
            check('legacy GET logout confirmation only',request_http('/__auth/logout')[0]==302)
            check('legacy POST logout rejected',request_http('/__auth/logout','POST')[0]==405)
            status,headers,_=request_http('/dashboard/tasks/api/session?probe=%2F')
            check('no-cookie business redirects new access entry',status==302 and '/__auth/access/' in headers.get('Location',''))
            for name in policy.ADMINS:
                cookie=portal.CFG['cookie']+'='+native[name]
                status,_,body=request_http('/dashboard/tasks/api/session?probe=%2F',cookie=cookie,
                    headers={'X-Auth-User':'forged','X-Auth-Role':'readonly','X-Auth-Groups':'forged'})
                viewer=json.loads(body)['viewer'] if status==200 else {}
                check('real Nginx four-admin '+name,status==200 and viewer.get('role')=='admin' and viewer.get('user')==name)
            status,_,body=request_http('/dashboard/tasks/api/session?probe=%2F',cookie=portal.CFG['cookie']+'='+native['oldreader'])
            check('native readonly keeps existing board editor',status==200 and json.loads(body)['viewer']['role']=='editor')
            cookie=runtime.core.COOKIE+'='+registered
            status,_,body=request_http('/dashboard/tasks/api/session?probe=%2F',cookie=cookie)
            check('registered readonly real taskboard viewer',status==200 and json.loads(body)['viewer']['role']=='viewer')
            check('readonly actual POST denied',request_http('/dashboard/tasks/api/members','POST',cookie)[0]==403)
            check('direct forged board headers denied',request_http('/api/session',headers={'X-Auth-User':'fstech','X-Auth-Role':'admin'},tls=False,port=ports['board'])[0]==401)
            check('oldFC cookie retired',request_http('/fc27/verify',cookie='fc27sess=synthetic-old')[0]==401)
            check('sensitive FC analysis readonly denied',request_http('/fc27/analysis',cookie=cookie)[0]==401)
            check('FC analysis valid admin preserved',request_http('/fc27/analysis',cookie=portal.CFG['cookie']+'='+native['fstech'])[0]==200)
            rows=[json.loads(line) for line in tracefile.read_text().splitlines()]
            check('Nginx user role groups overwrite client',any(row.get('kind')=='board-input' and row.get('user')=='fstech' and row.get('role')=='admin' and 'deploy' in (row.get('groups') or '').split(',') for row in rows))
            check('actual method and URI reach verifier',any(row.get('kind')=='verify' and row.get('method')=='POST' and row.get('uri')=='/dashboard/tasks/api/members' and row.get('status')==403 for row in rows))
            db=data/'registration-approval/registration.sqlite3';anchor=data/'.registration-checkpoint/state.json'
            moved=db.with_suffix('.unavailable-QA');db.rename(moved)
            try:
                status=request_http('/dashboard/tasks/api/session?probe=%2F',cookie=cookie)[0]
                observed=[json.loads(line) for line in tracefile.read_text().splitlines()]
                check('actual verifier503 fails closed through Nginx',status>=500 and any(row.get('kind')=='portal-verify-wire' and row.get('status')==503 for row in observed))
            finally:moved.rename(db)
            stop(portal_child)
            store.decide(proof,request['request_id'],1,'revoke','Synthetic seam revoke')
            session,csrf=store.new_session(legacy_user=proof.user)
            check('synthetic native logout fixture',app.dispatch('POST','/api/logout',cookies={runtime.core.COOKIE:session,portal.CFG['cookie']:native['fstech']},body=b'{}',headers={'Origin':ORIGIN,'X-CSRF-Token':csrf,'Content-Type':'application/json'})[0]==200)
            before=(sha(db),sha(anchor));recovery=start('recovery');ready(recovery,ports['portal'])
            for label,old in (('native',portal.CFG['cookie']+'='+native['fstech']),('registered',cookie)):
                status,headers,_=request_http('/dashboard/tasks/api/session?probe=%2F',cookie=old)
                check('recovery old '+label+' token denied',status==302 and '/__auth/access/' in headers.get('Location',''))
            check('recovery access bootstrap503',request_http('/__auth/access/api/bootstrap')[0]==503)
            check('recovery retained exact latest DB + witness',before==(sha(db),sha(anchor)))
            check('FC old identity DB never created',not (scratch/'never-create-old-FC.sqlite3').exists())
            workers=[json.loads(log.read_text(encoding='utf-8').splitlines()[0]) for log in worker_logs]
            check('all6 actual Python workers report target39 + SQLite3534',len(workers)==6 and all(row['python']=='3.9.18' and row['sqlite']=='3.53.4' for row in workers))
            receipt['actual_worker_receipts']=workers
            verify_inputs(root)
            receipt.update(status='PASS',checks=checks,source_modified=False,
                recovery_sha256=release['recovery']['sha256'],production_ready=False,
                production_systemd_or_real_roles_verified=False,
                QA_projection=['synthetic-only data/credentials/cert','owned loopback sockets and port remap',
                    'runtime path + native-policy loader mapping','isolated store boundary',
                    'header observer without cookies','unrelated upstreams disabled + empty web roots',
                    'QA log/pid/temp paths + worker UID'])
        except Exception as exc:
            receipt.update(status='FAIL',checks=checks,error_type=type(exc).__name__,error=str(exc))
        finally:
            for child in reversed(children):stop(child)
            for stream in handles:stream.close()
            for sock in sockets.values():sock.close()
            receipt['all_owned_children_reaped']=all(child.poll() is not None for child in children)
            receipt['child_returncodes']=[child.returncode for child in children]
    receipt['synthetic_temp_cleaned']=True
    output.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':receipt['status'],'checks':len(checks),'receipt':str(output),
                      'production_write':False,'43plus4_rerun':False}))
    return 0 if receipt['status']=='PASS' else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--reviewed-root',type=Path,required=True)
    parser.add_argument('--nginx',type=Path)
    parser.add_argument('--openssl',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--worker',choices=('portal','recovery','fc','board'))
    parser.add_argument('--fd',type=int)
    args=parser.parse_args()
    if args.worker:
        verify_inputs(args.reviewed_root)
        worker(args.reviewed_root,args.worker,args.fd)
    else:
        sys.exit(run(args))
