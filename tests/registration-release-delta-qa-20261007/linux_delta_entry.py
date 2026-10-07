"""One isolated QA run of frozen caller seams + synthetic Nginx auth round trips.

Driver: consumes one pinned clean source checkout, never fetches/copies production
source, installs dependencies, invokes SSH/systemctl, mutates/fetches Git, or runs the old 43+4.
Fixed runtime paths/ports are mapped only inside QA workers and a synthetic fixture.
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

SOURCE_COMMIT = '2152c8c9ea2fd68be3876349299d490d38903404'
SOURCE_MANIFEST = 'candidates/registration-import-20261007/candidate-manifest.json'
SOURCE_MANIFEST_SHA = '6a1391e26013415e1f1f68d858ce25715e47ee6e56f83c2a9ec726713ec8aef0'
DERIVED_FROM_ENTRY_SHA = 'aa37ce503cc23fbead8a0867f4e37a9ad75f36dd5bb0e7b9fd7de19149598a24'
CANDIDATE_DIRECTORY = 'candidates/registration-import-20261007'
ORIGINAL_TEST_DIRECTORY = 'tests/registration-import-20261007'
RUNTIME_DIRECTORY = 'registration_approval_runtime_v3_20261006'
RUNTIME_SUBTREE = '790c5ec62472c12950e6652c5b3c4760a36df7f2'
WORKFLOW_PATH = '.github/workflows/registration-target39-manual-qa.yml'
NGINX_FIXTURE_SHA = '938d71023c1179f30b69959e011a12d22479655187a7e123cd03eb7b0191c2fc'
NGINX_FIXTURE = """daemon off;
@@QA_USER@@
worker_processes 1;
error_log stderr warn;
pid @@QA_DIR@@/nginx.pid;
events { worker_connections 128; }
http {
    access_log off;
    client_body_temp_path @@QA_DIR@@/client-temp;
    proxy_temp_path @@QA_DIR@@/proxy-temp;
    server {
        listen 127.0.0.1:@@PORT_HTTP@@;
        server_name 47.85.224.112;
        location = /__auth { return 301 /__auth/access/; }
        location /__auth/ { return 308 https://47.85.224.112$request_uri; }
        location / { return 404; }
    }
    server {
        listen 127.0.0.1:@@PORT_HTTPS@@ ssl;
        server_name 47.85.224.112;
        ssl_certificate @@QA_DIR@@/cert.pem;
        ssl_certificate_key @@QA_DIR@@/key.pem;
        location = /__auth { return 301 /__auth/access/; }
        location /__auth/ {
            proxy_pass http://127.0.0.1:@@PORT_PORTAL@@/;
            proxy_set_header Host $host;
            proxy_set_header Cookie $http_cookie;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Real-IP 127.0.0.1;
        }
        location = /__auth_verify {
            internal;
            proxy_pass http://127.0.0.1:@@PORT_PORTAL@@/verify;
            proxy_pass_request_body off;
            proxy_set_header Content-Length "";
            proxy_set_header Cookie $http_cookie;
            proxy_set_header X-Original-URI $qa_uri;
            proxy_set_header X-Original-Method $qa_method;
            proxy_set_header X-Real-IP 127.0.0.1;
        }
        location /dashboard/tasks/ {
            set $qa_method $request_method;
            set $qa_uri $request_uri;
            auth_request /__auth_verify;
            auth_request_set $qa_user $upstream_http_x_auth_user;
            auth_request_set $qa_role $upstream_http_x_auth_role;
            auth_request_set $qa_groups $upstream_http_x_auth_groups;
            error_page 401 = @auth_login;
            proxy_pass http://127.0.0.1:@@PORT_BOARD@@/;
            proxy_set_header Host $host;
            proxy_set_header Cookie $http_cookie;
            proxy_set_header X-Original-URI $request_uri;
            proxy_set_header X-Original-Method $request_method;
            proxy_set_header X-Auth-User $qa_user;
            proxy_set_header X-Auth-Role $qa_role;
            proxy_set_header X-Auth-Groups $qa_groups;
        }
        location /fc27/ {
            proxy_pass http://127.0.0.1:@@PORT_FC@@/;
            proxy_set_header Host $host;
            proxy_set_header Cookie $http_cookie;
            proxy_set_header X-Original-URI $request_uri;
            proxy_set_header X-Original-Method $request_method;
        }
        location @auth_login { return 302 /__auth/access/?next=$request_uri; }
        location / { return 404; }
    }
}
"""
RUNTIME_PATH = '/opt/auth-portal/registration-runtime/20261007-ca6258ad'
ORIGIN = 'https://47.85.224.112'
PASSWORD = 'Synthetic-password-42'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_source_file(root, relative):
    name = Path(relative)
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or name.is_absolute() or any(p in ('', '.', '..') for p in relative.split('/'))):
        raise ValueError('unsafe source path')
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('linked source input')
    resolved = path.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError('escaping/nonregular source input')
    return resolved


def source_git(root, arguments):
    # Local metadata reads only. No fetch, credential lookup or Git mutation.
    env = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *arguments], env=env,
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise ValueError('source checkout Git identity unavailable')
    return result.stdout.strip()


def verify_inputs(root):
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('absolute nonlinked source checkout required')
    root = root.resolve(strict=True)
    if source_git(root, ['rev-parse', 'HEAD']) != SOURCE_COMMIT:
        raise ValueError('source checkout must be the exact frozen commit')
    manifest = safe_source_file(root, SOURCE_MANIFEST)
    if sha(manifest) != SOURCE_MANIFEST_SHA:
        raise ValueError('source manifest drift')
    inputs = json.loads(manifest.read_bytes())
    rows = inputs['files']
    dependencies = inputs['dependency']['sourceFilesVerified']
    if (inputs['approvedUploadFileCount'] != 20 or len(rows) != 19
            or len(dependencies) != 15 or inputs['releaseReady'] is not False
            or inputs['dependency']['path'] != RUNTIME_DIRECTORY
            or inputs['dependency']['gitTree'] != RUNTIME_SUBTREE):
        raise ValueError('unexpected frozen input contract')
    expected = {SOURCE_MANIFEST}
    hashes = {SOURCE_MANIFEST: sha(manifest)}
    for row in rows:
        name = row['path']
        if not name.startswith((CANDIDATE_DIRECTORY + '/', ORIGINAL_TEST_DIRECTORY + '/')) or name in expected:
            raise ValueError('unexpected/duplicate candidate path')
        path = safe_source_file(root, name)
        data = path.read_bytes()
        if (len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']
                or hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != row['gitBlobSha1']):
            raise ValueError('frozen candidate input drift: ' + name)
        expected.add(name)
        hashes[name] = row['sha256']
    for directory in (CANDIDATE_DIRECTORY, ORIGINAL_TEST_DIRECTORY):
        actual = set()
        for path in (root / directory).rglob('*'):
            if path.is_symlink() or path.name == '__pycache__':
                raise ValueError('linked/cache candidate input')
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
        if actual != {name for name in expected if name.startswith(directory + '/')}:
            raise ValueError('extra or missing candidate files')
    dependency_names = set()
    for row in dependencies:
        name = row['path']
        if not name.startswith(RUNTIME_DIRECTORY + '/') or name in dependency_names:
            raise ValueError('unexpected/duplicate runtime dependency')
        path = safe_source_file(root, name)
        data = path.read_bytes()
        if (len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']
                or hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != row['gitBlobSha']):
            raise ValueError('frozen runtime input drift: ' + name)
        dependency_names.add(name)
        hashes[name] = row['sha256']
    if source_git(root, ['rev-parse', 'HEAD:' + RUNTIME_DIRECTORY]) != RUNTIME_SUBTREE:
        raise ValueError('runtime subtree identity mismatch')
    scoped = [CANDIDATE_DIRECTORY, ORIGINAL_TEST_DIRECTORY, RUNTIME_DIRECTORY]
    if source_git(root, ['status', '--porcelain', '--untracked-files=all', '--ignored', '--', *scoped]):
        raise ValueError('modified/untracked/ignored files in source inputs')
    recovery = next(row for row in rows if row['path'] == CANDIDATE_DIRECTORY + '/recovery/auth_portal.py')
    return {'source_commit': SOURCE_COMMIT, 'source_manifest_sha256': SOURCE_MANIFEST_SHA,
            'runtime_subtree': RUNTIME_SUBTREE, 'candidate_files': 20, 'runtime_dependencies': 15,
            'verified_file_sha256': hashes, 'recovery': {'sha256': recovery['sha256']}}


def load_candidate(root, kind):
    runtime_root = root/RUNTIME_DIRECTORY
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
    path = {'portal':CANDIDATE_DIRECTORY+'/formal/auth_portal.py',
            'recovery':CANDIDATE_DIRECTORY+'/recovery/auth_portal.py',
            'fc':CANDIDATE_DIRECTORY+'/formal/fc27_gate.py',
            'board':CANDIDATE_DIRECTORY+'/formal/taskboard_server.py'}[kind]
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
    def mapped_http(host,port=None,*a,**kw):
        if host != '127.0.0.1' or port != 8895:
            raise ValueError('worker outbound connection outside global QA verifier')
        return original_http(host,portal_port,*a,**kw)
    http.client.HTTPConnection = mapped_http
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


def validate_fixture():
    if hashlib.sha256(NGINX_FIXTURE.encode('utf-8')).hexdigest() != NGINX_FIXTURE_SHA:
        raise ValueError('synthetic Nginx fixture drift')
    tokens = set(re.findall(r'@@([A-Z_]+)@@', NGINX_FIXTURE))
    expected = {'QA_USER', 'QA_DIR', 'PORT_HTTP', 'PORT_HTTPS', 'PORT_PORTAL', 'PORT_BOARD', 'PORT_FC'}
    if tokens != expected or NGINX_FIXTURE.count('{') != NGINX_FIXTURE.count('}'):
        raise ValueError('synthetic Nginx placeholder/brace contract mismatch')
    if re.search(r'(?m)^\s*(include|load_module)\s', NGINX_FIXTURE):
        raise ValueError('external Nginx configuration forbidden')
    listens = re.findall(r'(?m)^\s*listen\s+([^;]+);', NGINX_FIXTURE)
    proxies = re.findall(r'(?m)^\s*proxy_pass\s+([^;]+);', NGINX_FIXTURE)
    if (listens != ['127.0.0.1:@@PORT_HTTP@@', '127.0.0.1:@@PORT_HTTPS@@ ssl']
            or len(proxies) != 4
            or any(not re.fullmatch(r'http://127\.0\.0\.1:@@PORT_(PORTAL|BOARD|FC)@@/(verify)?', value) for value in proxies)):
        raise ValueError('non-loopback/unexpected Nginx network directive')
    for directive in ('pid', 'client_body_temp_path', 'proxy_temp_path', 'ssl_certificate', 'ssl_certificate_key'):
        values = re.findall(r'(?m)^\s*' + directive + r'\s+([^;]+);', NGINX_FIXTURE)
        if len(values) != 1 or not values[0].startswith('@@QA_DIR@@/'):
            raise ValueError('Nginx file path outside synthetic directory')
    return {'fixture_sha256': NGINX_FIXTURE_SHA, 'fixture_bytes': len(NGINX_FIXTURE.encode()),
            'placeholder_names': sorted(tokens), 'nginx_parse_performed': False}


def synthetic_nginx(scratch, ports):
    validate_fixture()
    if (not scratch.is_absolute() or not scratch.is_dir()
            or any(p.is_symlink() for p in (scratch, *scratch.parents))
            or Path(tempfile.gettempdir()).resolve() not in scratch.resolve().parents
            or not scratch.name.startswith('fs-registration-seamqa-')
            or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(scratch))
            or scratch.stat().st_uid != os.geteuid() or scratch.stat().st_mode & 0o077):
        raise ValueError('private owned synthetic Nginx directory required')
    required = {'http', 'https', 'portal', 'board', 'fc', 'blocked'}
    if (set(ports) != required or any(type(p) is not int or not 1 <= p <= 65535 for p in ports.values())
            or len(set(ports.values())) != len(ports)):
        raise ValueError('unique prebound loopback port map required')
    replacements = {'QA_USER': 'user root;' if os.geteuid() == 0 else '', 'QA_DIR': str(scratch)}
    replacements.update({'PORT_' + name.upper(): str(ports[name]) for name in required if name != 'blocked'})
    rendered = NGINX_FIXTURE
    for name, value in replacements.items():
        rendered = rendered.replace('@@' + name + '@@', value)
    if '@@' in rendered:
        raise ValueError('unresolved synthetic Nginx placeholder')
    return rendered


def driver_check():
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / 'overlay-manifest.json').read_bytes())
    if (manifest.get('source_commit') != SOURCE_COMMIT
            or manifest.get('source_manifest_sha256') != SOURCE_MANIFEST_SHA
            or manifest.get('derived_from_entry_sha256') != DERIVED_FROM_ENTRY_SHA
            or manifest.get('synthetic_fixture_sha256') != NGINX_FIXTURE_SHA
            or manifest.get('required_environment') != {'platform':'Linux','python':'3.9.18','sqlite':'3.53.4','nginx':'1.26.1'}
            or manifest.get('integration_executed') is not False
            or manifest.get('production_ready') is not False):
        raise ValueError('driver manifest contract mismatch')
    files = manifest.get('files', [])
    if {row.get('path') for row in files} != {'linux_delta_entry.py', 'EXECUTE.md'} or len(files) != 2:
        raise ValueError('driver manifest file set mismatch')
    for row in files:
        path = here / row['path']
        if path.is_symlink() or path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('driver file drift')
    source = Path(__file__).read_text(encoding='utf-8')
    ast.parse(source, feature_version=(3, 9))
    fixture = validate_fixture()
    workflow = here.parents[1] / WORKFLOW_PATH
    if workflow.is_symlink() or sha(workflow) != manifest['workflow_sha256']:
        raise ValueError('workflow differs from reviewed driver manifest')
    config = json.loads(workflow.read_text(encoding='utf-8'))  # Existing workflow is JSON-valid YAML.
    events = config.get('on', {})
    if set(events) != {'workflow_dispatch'} or config.get('permissions') != {'contents': 'read'}:
        raise ValueError('workflow must be manual-only and contents-read')
    inputs = events['workflow_dispatch']['inputs']
    if (inputs['mode'] != {'description': inputs['mode']['description'], 'type': 'choice', 'required': True,
                          'default': 'registration_delta', 'options': ['registration_delta', 'runtime43_multiprocess4']}
            or inputs['free_quota_confirmed']['type'] != 'boolean'
            or inputs['free_quota_confirmed']['required'] is not True
            or inputs['free_quota_confirmed']['default'] is not False):
        raise ValueError('workflow input mode/quota controls changed')
    jobs = config['jobs']
    if set(jobs) != {'target39', 'registration_delta'}:
        raise ValueError('unexpected workflow jobs')
    condition = "${{ github.event_name == 'workflow_dispatch' && github.repository == 'wulv006-dot/FS-Workbench' && github.ref == 'refs/heads/main' && inputs.mode == '%s' && inputs.free_quota_confirmed }}"
    if (jobs['target39']['if'] != condition % 'runtime43_multiprocess4'
            or jobs['registration_delta']['if'] != condition % 'registration_delta'):
        raise ValueError('manual/main/mode/free-quota job guard changed')
    delta = jobs['registration_delta']
    if (delta['timeout-minutes'] != 10 or delta['runs-on'] != 'ubuntu-24.04'
            or delta.get('permissions') != {'contents': 'read'} or delta.get('continue-on-error', False)):
        raise ValueError('delta job execution bounds changed')
    steps = delta['steps']
    if any(step.get('continue-on-error', False) for step in steps):
        raise ValueError('required delta steps cannot ignore failures')
    checkout = [step for step in steps if step.get('uses', '').startswith('actions/checkout@')]
    if len(checkout) != 2:
        raise ValueError('separate driver/source checkout required')
    for step in checkout:
        options = step['with']
        if (step['uses'] != 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1'
                or options.get('repository') != 'wulv006-dot/FS-Workbench'
                or options.get('persist-credentials') is not False
                or options.get('submodules') is not False or options.get('lfs') is not False
                or options.get('fetch-depth') != 1):
            raise ValueError('checkout scope or credential persistence changed')
    if (checkout[0]['with']['ref'] != '${{ github.sha }}' or checkout[0]['with'].get('path')
            or checkout[1]['with']['ref'] != SOURCE_COMMIT
            or checkout[1]['with']['path'] != 'registration-source'):
        raise ValueError('driver/source checkout identities changed')
    by_id = {step['id']: step for step in steps if 'id' in step}
    if by_id['python']['with']['python-version'] != '3.9.18':
        raise ValueError('target interpreter version changed')
    nginx_build = by_id['nginx']['run']
    for value in ('02725ce722bc7b34fa307d611eac3956ef744efa', '1300cfe81af6453b2740a9f1c08640d44851087f',
                  '--with-http_auth_request_module', '--with-http_ssl_module', 'pkg-config --exists'):
        if value not in nginx_build:
            raise ValueError('pinned private Nginx build guard missing')
    integration = by_id['delta']['run']
    required = ('unshare --net --pid --fork --mount-proc --kill-child=KILL', 'ip link set lo up', 'ip -o link show', 'ip route show default',
                'ip -6 route show default', 'exec setpriv', 'env -i', '--source-root',
                '--nginx', '--openssl', '--output', 'timeout --signal=TERM --kill-after=15s 120s')
    if any(value not in integration for value in required):
        raise ValueError('network/identity/timeout integration guard missing')
    entry = 'tests/registration-release-delta-qa-20261007/linux_delta_entry.py'
    if integration.count(entry) != 1 or '--driver-check' in integration:
        raise ValueError('exactly one integration invocation required')
    static_steps = [step for step in steps if '--driver-check' in step.get('run', '')]
    if len(static_steps) != 1 or steps.index(static_steps[0]) >= steps.index(by_id['delta']):
        raise ValueError('separate preceding static driver check required')
    scripts = '\n'.join(step.get('run', '') for step in steps)
    if ('multiprocess_probe.py' in scripts or 'test_release_delta.py' in scripts
            or 'unittest discover' in scripts
            or re.search(r'(?m)^\s*(sudo\s+)?(?:apt(?:-get)?|pip[0-9.]*)\s+install\b', scripts)):
        raise ValueError('delta workflow expands tests/global-install scope')
    uploads = [step for step in steps if step.get('uses', '').startswith('actions/upload-artifact@')]
    if (len(uploads) != 1 or uploads[0]['uses'] != 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
            or uploads[0]['with']['path'] != '${{ steps.delta.outputs.receipt }}'
            or uploads[0]['with']['retention-days'] != 7
            or 'always()' not in uploads[0]['if']):
        raise ValueError('sanitized receipt retention scope changed')
    if not any('always()' in step.get('if', '') and 'QA_DELTA_BASE' in step.get('env', {}) for step in steps):
        raise ValueError('owned-prefix cleanup missing')
    print(json.dumps({'status': 'DRIVER_STATIC_ONLY', 'python39_syntax': True,
                      'driver_manifest_verified': True, 'workflow_controls_verified': True,
                      **fixture, 'source_checkout_read': False, 'candidate_imported': False,
                      'integration_executed': False, 'production_nginx_verified': False,
                      'production_ready': False}))
    return 0


def reap_owned(children):
    # Only groups created by start_new_session=True in this controller.
    for child in reversed(children):
        if child.poll() is None:
            try: os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError: pass
    until=time.monotonic()+5.0
    for child in children:
        if child.poll() is None:
            try: child.wait(timeout=max(0.01,until-time.monotonic()))
            except subprocess.TimeoutExpired: pass
    for child in children:
        if child.poll() is None:
            try: os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError: pass
    until=time.monotonic()+2.0
    for child in children:
        if child.poll() is None:
            try: child.wait(timeout=max(0.01,until-time.monotonic()))
            except subprocess.TimeoutExpired: pass
    return all(child.poll() is not None for child in children)


def run(args):
    if args.source_root is None or args.nginx is None or args.openssl is None or args.output is None:
        raise ValueError('source-root, nginx, openssl and fresh output paths required')
    root = args.source_root
    release = verify_inputs(root)
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
        'source_commit':SOURCE_COMMIT,'source_manifest_sha256':SOURCE_MANIFEST_SHA,
        'runtime_subtree':RUNTIME_SUBTREE,'driver_sha256':sha(__file__),
        'driver_commit':os.environ.get('DRIVER_COMMIT'),
        'production_nginx_verified':False,'production_ready':False,
        'python':sys.version,'sqlite':sqlite3.sqlite_version,
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
            child=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--source-root',str(root),
                '--worker',kind,'--fd',str(sockets['portal' if kind=='recovery' else kind].fileno())],env=childenv,
                stdout=handle,stderr=handle,pass_fds=(sockets['portal' if kind=='recovery' else kind].fileno(),),start_new_session=True)
            children.append(child);worker_logs.append(log); return child
        old_handlers={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
        def terminated(signum,frame):
            raise TimeoutError('owned QA controller termination requested')
        for sig in old_handlers:signal.signal(sig,terminated)
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
            config=synthetic_nginx(scratch,ports); configfile=scratch/'nginx.conf';configfile.write_text(config,encoding='utf-8')
            parsed=subprocess.run([str(nginx),'-e','stderr','-p',str(scratch)+'/', '-c',str(configfile),'-t'],
                capture_output=True,timeout=10)
            check('synthetic fixture native Nginx parse',parsed.returncode==0)
            receipt['synthetic_fixture_sha256']=NGINX_FIXTURE_SHA;receipt['QA_projection_sha256']=sha(configfile)
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
            check('source inputs unchanged after integration',verify_inputs(root)==release)
            receipt.update(status='PASS',checks=checks,source_modified=False,
                recovery_sha256=release['recovery']['sha256'],production_ready=False,
                production_systemd_or_real_roles_verified=False,
                QA_projection=['synthetic-only data/credentials/cert','owned loopback sockets and port remap',
                    'runtime path + native-policy loader mapping','isolated store boundary',
                    'header observer without cookies','minimal synthetic Nginx route fixture; no live includes',
                    'owned QA log/pid/temp paths + worker UID'])
        except Exception as exc:
            receipt.update(status='FAIL',checks=checks,error_type=type(exc).__name__,error=str(exc))
        finally:
            # Ignore repeated termination only during bounded owned-group cleanup.
            for sig in old_handlers:signal.signal(sig,signal.SIG_IGN)
            receipt['all_owned_children_reaped']=reap_owned(children)
            for stream in handles:stream.close()
            for sock in sockets.values():sock.close()
            receipt['all_owned_children_reaped']=all(child.poll() is not None for child in children)
            receipt['child_returncodes']=[child.returncode for child in children]
            try:
                receipt['source_pre_post_unchanged'] = verify_inputs(root) == release
                if not receipt['source_pre_post_unchanged']:
                    receipt.update(status='FAIL',error_type='SourceDrift',source_modified=True)
            except Exception as exc:
                receipt.update(status='FAIL',error_type=type(exc).__name__,source_modified=True)
            if not receipt['all_owned_children_reaped']:
                receipt.update(status='FAIL',error_type='CleanupIncomplete')
            for sig,handler in old_handlers.items():signal.signal(sig,handler)
    receipt['synthetic_temp_cleaned']=True
    output.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':receipt['status'],'checks':len(checks),'receipt':str(output),
                      'production_write':False,'43plus4_rerun':False}))
    return 0 if receipt['status']=='PASS' else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--nginx',type=Path)
    parser.add_argument('--openssl',type=Path)
    parser.add_argument('--output',type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--driver-check',action='store_true')
    mode.add_argument('--worker',choices=('portal','recovery','fc','board'))
    parser.add_argument('--fd',type=int)
    args=parser.parse_args()
    if args.driver_check:
        sys.exit(driver_check())
    elif args.worker:
        if args.source_root is None or args.fd is None:
            parser.error('worker requires source-root and an owned fd')
        verify_inputs(args.source_root)
        worker(args.source_root,args.worker,args.fd)
    else:
        driver_check()
        sys.exit(run(args))
