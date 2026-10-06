"""Executable local portal + approval + trusted proxy + UUID consumer integration."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import sqlite3
import tempfile

from auth_candidate import App, PREFIX, Denied
from bootstrap_local import initialize, mark_ready
from native_integration import (NativeAdapter, Namespace, Registry, bind_functions,
                                policy, taskboard_role)

SYNTHETIC_PASSWORD = 'Local-synthetic-admin-42'


class Environment:
    def __init__(self, root, secret=None, checkpoint=lambda phase: None):
        if Path(root).is_symlink(): raise ValueError('sandbox link rejected')
        root=Path(root).resolve(); temp=Path(tempfile.gettempdir()).resolve()
        if temp not in root.parents or not root.name.startswith('fs-registration-'):
            raise ValueError('local synthetic sandbox only')
        self.root=root
        groups={name:str(root/(name+'.synthetic-htpasswd')) for name in ('dashboard','deploy')}
        self.portal=bind_functions({'secret':secret or secrets.token_hex(32),'cookie':'MMOEXP_AUTH'},groups)
        self.namespace=Namespace(root,self.portal)
        with self.namespace.fence():
            pending = initialize(root,self.portal,SYNTHETIC_PASSWORD,checkpoint)
            self.store=Registry(root,self.namespace,allow_existing=True)
            checkpoint('registry')
            if pending: mark_ready(root,checkpoint)
        self.adapter=NativeAdapter(self.store,self.portal,self.namespace)
        self.consumer=sqlite3.connect(':memory:',check_same_thread=False)
        self.consumer.row_factory=sqlite3.Row
        self.consumer.execute('CREATE TABLE members(username TEXT PRIMARY KEY,role TEXT,active INTEGER)')
        self.consumer.execute('INSERT INTO members VALUES(?,?,1)',('synthetic.native.reader','viewer'))
        self.consumer.commit()

    def close(self): self.consumer.close()


def create_server(environment, port=0):
    env=environment;web=Path(__file__).parent/'web'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self): self.route()
        def do_HEAD(self): self.route()
        def do_POST(self): self.route()
        def do_PUT(self): self.route()
        def do_DELETE(self): self.route()
        def send(self,code,body,headers=None):
            if not isinstance(body,bytes): body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(code);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            for key,value in (headers or {}).items():
                if key=='Cache-Control': continue
                for item in value if isinstance(value,list) else [value]: self.send_header(key,item)
            self.end_headers()
            if self.command!='HEAD': self.wfile.write(body)
        def route(self):
            if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}': return self.send(403,{})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<=length<=4096 or self.headers.get('Transfer-Encoding'): return self.send(400,{})
                body=self.rfile.read(length);cookies=env.portal.parse_cookies(self.headers.get('Cookie',''))
                path=self.path.split('?',1)[0]
                static={PREFIX+'/':('index.html','text/html; charset=utf-8'),
                    PREFIX+'/app.js':('app.js','text/javascript; charset=utf-8'),
                    PREFIX+'/base.css':('base.css','text/css; charset=utf-8'),
                    PREFIX+'/access.css':('access.css','text/css; charset=utf-8')}
                if path in static and self.command in ('GET','HEAD'):
                    name,mime=static[path]
                    return self.send(200,(web/name).read_bytes(),{'Content-Type':mime,
                        'Content-Security-Policy':"default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"})
                if path.startswith(PREFIX+'/api/'):
                    code,result,headers=self.server.app.dispatch(self.command,self.path[len(PREFIX):],
                        headers=dict(self.headers),cookies=cookies,body=body,client=self.client_address[0])
                    return self.send(code,result,headers|{'Content-Type':'application/json'})
                # Trusted proxy equivalent: client identity/original-method headers never used.
                code,verified=env.adapter.verify(cookies,self.command,self.path,'dashboard')
                if code!=200: return self.send(code,{'error':'access denied'})
                if path not in ('/dashboard/index.html','/dashboard/tasks/api/projects','/dashboard/'):
                    return self.send(404,{})
                role,registered=taskboard_role(env.consumer,verified['X-Auth-User'],verified['X-Auth-Role'],env.namespace.policy)
                if not registered: return self.send(403,{})
                if self.command not in ('GET','HEAD') and role!='admin': return self.send(403,{})
                return self.send(200,{'synthetic':True,'subject':verified['X-Auth-User'],
                    'portalRole':verified['X-Auth-Role'],'consumerRole':role,'source':'native taskboard member_state + UUID increment'},verified)
            except Denied as exc: return self.send(exc.code,{'error':exc.message})
            except Exception: return self.send(503,{'error':'local integration unavailable'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    server.app=App(env.adapter,f'http://127.0.0.1:{server.server_port}')
    return server
