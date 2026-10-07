"""One isolated QA run of frozen caller seams + synthetic Nginx auth round trips.

Driver: consumes one pinned clean source checkout, never fetches/copies production
source, installs dependencies, invokes SSH/systemctl, mutates/fetches Git, or runs the old 43+4.
Fixed runtime paths/ports are mapped only inside QA workers and a synthetic fixture.
Source bytes remain unchanged. Actual production systemd/TLS/UID are separate gates.
"""
import argparse
import ast
import errno
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
from urllib.parse import urlsplit

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
SESSION_READ_URI = '/dashboard/tasks/api/session?mode=%76iew'
SESSION_REJECT_URI = '/dashboard/tasks/api/session?probe=%2F'


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


def source_git(root, arguments, deadline=None):
    # Local metadata reads only. No fetch, credential lookup or Git mutation.
    env = {key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    timeout = 5.0 if deadline is None else min(5.0, deadline-time.monotonic())
    if timeout <= 0:
        raise TimeoutError('source Git verification budget exhausted')
    result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *arguments], env=env,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError('source checkout Git identity unavailable')
    return result.stdout.strip()


def verify_inputs(root, deadline=None):
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('absolute nonlinked source checkout required')
    root = root.resolve(strict=True)
    if source_git(root, ['rev-parse', 'HEAD'], deadline) != SOURCE_COMMIT:
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
    if source_git(root, ['rev-parse', 'HEAD:' + RUNTIME_DIRECTORY], deadline) != RUNTIME_SUBTREE:
        raise ValueError('runtime subtree identity mismatch')
    scoped = [CANDIDATE_DIRECTORY, ORIGINAL_TEST_DIRECTORY, RUNTIME_DIRECTORY]
    if source_git(root, ['status', '--porcelain', '--untracked-files=all', '--ignored', '--', *scoped], deadline):
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
    contract = validate_contract_plan()
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
                      **fixture, **contract, 'source_checkout_read': False, 'candidate_imported': False,
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


# This is the single executable contract. Building/validating it is pure: no
# candidate imports, checkout reads, listeners or secret/session material.
ADMINS = ('DY', 'chenchao', 'fstech', 'wulv')
PHASES = ('startup', 'native-roles', 'http-login', 'legacy-logout',
          'registration', 'reapply', 'readonly', 'negative-identities',
          'retired-fc', 'logout-controls', 'nginx-contract', 'storage-loss',
          'revocation', 'recovery', 'upstream-loss', 'assurance')


def build_contract_plan():
    rows = []
    def local(case, phase, operation, requires=(), **options):
        rows.append(dict(id=case, phase=phase, operation=operation,
                         requires=list(requires), expected_status=None,
                         expected_role=None, expected_value=True, **options))
    def http(case, phase, service, path, status, session='anonymous',
             method='GET', role=None, requires=(), **options):
        base = 'nginx' if service in ('access', 'edge', 'http') else 'services'
        rows.append(dict(id=case, phase=phase, operation='http', service=service,
                         path=path, method=method, session=session,
                         expected_status=status, expected_role=role,
                         requires=list(dict.fromkeys((base,) + tuple(requires))), **options))
    def verify(case, phase, session, status=200, role=None, requires=(),
               uri=SESSION_READ_URI, actual_method='GET', **options):
        http(case, phase, 'portal', '/verify', status, session, role=role,
             requires=requires, headers={'X-Original-URI':uri,
             'X-Original-Method':actual_method}, **options)
    def bootstrap(case, phase, save, session='anonymous', requires=(), role='guest'):
        http(case, phase, 'access', '/access/api/bootstrap', 200, session,
             role=role, requires=requires, save_session=save)
    def post(case, phase, route, session, payload, status=200, requires=(), **options):
        http(case, phase, 'access', '/access/api/'+route, status, session,
             method='POST', requires=requires, api=True, payload=payload, **options)
    def login(case, phase, guest, save, name, native=False, requires=(), role=None):
        bootstrap(case+'.bootstrap', phase, guest, requires=requires)
        post(case, phase, 'native-login' if native else 'login', guest,
             {'username':name,'password':PASSWORD}, requires=(case+'.bootstrap',),
             save_session=save, role=role, checks=['secure_two'] if native else [])

    local('missing-store', 'startup', 'missing-store')
    local('initialize', 'startup', 'initialize', ('missing-store',))
    local('insecure-cookie', 'startup', 'insecure-cookie', ('initialize',))
    local('services', 'startup', 'services', ('initialize',))
    local('tls', 'startup', 'tls', ('services',))
    local('nginx', 'startup', 'nginx', ('tls',))
    http('http-upgrade', 'native-roles', 'http', '/__auth/access/', 308,
         checks=['fixed_https_redirect'])
    for path in ('/access/', '/access/app.js', '/access/base.css', '/access/access.css'):
        http('static'+path, 'native-roles', 'access', path, 200)
    for name in ADMINS:
        label = 'native.'+name
        verify(label+'.verify', 'native-roles', label, role='admin')
        http(label+'.board', 'native-roles', 'board', '/api/session?mode=%76iew',
             200, label, role='admin', subject=name)
        for method in ('GET','HEAD'):
            http(label+'.fc.'+method, 'native-roles', 'fc', '/analysis', 200,
                 label, method, checks=['head_empty'] if method=='HEAD' else ['analysis_marker'])
        bootstrap(label+'.bootstrap', 'native-roles', label+'.combined', label, role='admin')
        for route in ('requests','audit'):
            http(label+'.'+route, 'native-roles', 'access', '/access/api/'+route,
                 200, label+'.combined', requires=(label+'.bootstrap',))
    verify('editor.verify', 'native-roles', 'native.oldreader', role='readonly')
    http('editor.board', 'native-roles', 'board', '/api/session', 200,
         'native.oldreader', role='editor', subject='oldreader')
    http('editor.members.read', 'native-roles', 'board', '/api/members', 200,
         'native.oldreader', role='editor')
    for method, path in (('POST','/api/members'),('PATCH','/api/tasks/1'),('DELETE','/api/tasks/1')):
        http('editor.write.'+method, 'native-roles', 'board', path, 403,
             'native.oldreader', method, payload={})
    for method in ('GET','HEAD'):
        http('editor.fc.'+method, 'native-roles', 'fc', '/analysis', 200,
             'native.oldreader', method, checks=['head_empty'] if method=='HEAD' else ['analysis_marker'])

    login('editor.http-login', 'http-login', 'guest.editor', 'http.editor',
          'oldreader', native=True, role='readonly')
    verify('editor.http-verify', 'http-login', 'http.editor', role='readonly',
           requires=('editor.http-login',))
    http('editor.http-board', 'http-login', 'board', '/api/session', 200,
         'http.editor', role='editor', requires=('editor.http-login',))
    login('admin.http-login', 'http-login', 'guest.admin', 'http.admin',
          'fstech', native=True, role='admin')
    login('independent.http-login', 'http-login', 'guest.independent', 'http.independent',
          'fstech', native=True, role='admin')
    local('native-token-distinction', 'http-login', 'native-token-distinction',
          ('admin.http-login','independent.http-login'))
    verify('admin.http-verify', 'http-login', 'http.admin', role='admin',
           requires=('admin.http-login',))
    http('status.raw-native', 'http-login', 'access', '/status', 200,
         'http.admin.native-only', requires=('admin.http-login',))
    http('status.combined', 'http-login', 'access', '/status', 302,
         'http.admin', requires=('admin.http-login',), checks=['access_redirect'])

    for index, alias in enumerate(('/logout','/logout/','/logout//?next=/dashboard/')):
        for method in ('GET','HEAD','POST'):
            case='legacy-logout.%d.%s'%(index,method)
            http(case, 'legacy-logout', 'access', alias, 405 if method=='POST' else 302,
                 'http.admin', method, requires=('admin.http-login',),
                 payload={} if method=='POST' else None,
                 checks=['no_set_cookie'], unchanged=True)
            verify(case+'.still-live', 'legacy-logout', 'http.admin.native-only',
                   role='admin', requires=('admin.http-login',))

    bootstrap('registration.bootstrap','registration','guest.reg')
    post('registration.create','registration','register','guest.reg',
         {'username':'newreader','password':PASSWORD,'team':'QA','purpose':'Synthetic HTTP registration'},
         requires=('registration.bootstrap',), save_request='primary', json_fields={'state':'pending'})
    post('registration.login','registration','login','guest.reg',
         {'username':'newreader','password':PASSWORD}, role='pending',
         requires=('registration.create',),save_session='reg.primary')
    for service,path,status in (('board','/api/session',403),('fc','/analysis',401)):
        http('pending.'+service,'registration',service,path,status,'reg.primary',
             requires=('registration.login',),checks=['no_analysis_marker'])
    verify('pending.verify','registration','reg.primary',403,requires=('registration.login',))
    decision={'request_id':'@primary','version':0,'action':'approve','reason':'Synthetic HTTP approval'}
    post('registration.approve','registration','decision','http.admin',decision,
         requires=('admin.http-login','registration.login'),json_fields={'state':'readonly','version':1})
    post('registration.stale-version','registration','decision','http.admin',decision,409,
         requires=('registration.approve',),unchanged=True)

    bootstrap('other.bootstrap','reapply','guest.other')
    post('other.register','reapply','register','guest.other',
         {'username':'otherreader','password':PASSWORD,'team':'QA','purpose':'Synthetic rejection fixture'},
         requires=('other.bootstrap',),save_request='other',json_fields={'state':'pending'})
    post('other.login','reapply','login','guest.other',
         {'username':'otherreader','password':PASSWORD},requires=('other.register',),
         role='pending',save_session='reg.other')
    post('other.reject','reapply','decision','http.admin',
         {'request_id':'@other','version':0,'action':'reject','reason':'Synthetic reject'},
         requires=('admin.http-login','other.login'),json_fields={'state':'rejected','version':1})
    verify('other.rejected','reapply','reg.other',403,requires=('other.reject',))
    post('other.reapply','reapply','apply','reg.other',{'purpose':'Synthetic reapplication'},
         requires=('other.reject',),save_request='reapplied',json_fields={'state':'pending'})
    post('other.approve','reapply','decision','http.admin',
         {'request_id':'@reapplied','version':0,'action':'approve','reason':'Synthetic reapproval'},
         requires=('other.reapply','admin.http-login'),json_fields={'state':'readonly','version':1})
    verify('other.readonly','reapply','reg.other',role='readonly',requires=('other.approve',))

    approved=('registration.approve',)
    verify('registered.verify','readonly','reg.primary',role='readonly',requires=approved,subject='registered')
    http('registered.board','readonly','board','/api/session?mode=%76iew',200,
         'reg.primary',role='viewer',requires=approved,subject='registered')
    http('registered.board.read','readonly','board','/api/board',200,'reg.primary',requires=approved)
    http('registered.board.head','readonly','board','/api/session',200,'reg.primary','HEAD',
         requires=approved,checks=['head_empty'])
    for suffix,query in (('combined','probe=%2F'),('unknown-key','probe=view'),('forbidden-value','mode=%2F')):
        verify('registered.query.'+suffix,'readonly','reg.primary',403,
               requires=approved,uri='/dashboard/tasks/api/session?'+query)
        http('registered.board.query.'+suffix,'readonly','board','/api/session?'+query,403,
             'reg.primary',requires=approved)
        http('registered.fc.query.'+suffix,'readonly','fc','/analysis?'+query,401,
             'reg.primary',requires=approved,checks=['no_analysis_marker'])
    for method,path,suffix in (('GET','/analysis','get'),('HEAD','/analysis','head'),
                               ('GET','/analysis?mode=%76iew','allowed-query')):
        http('registered.fc.'+suffix,'readonly','fc',path,200,'reg.primary',method,
             requires=approved,checks=['head_empty'] if method=='HEAD' else ['analysis_marker'])
    for label,session,req in (('registered','reg.primary',approved),('editor','native.oldreader',())):
        bootstrap(label+'.admin-bootstrap','readonly',label+'.admin-session',session,req,role='readonly')
        for route in ('requests','audit'):
            http(label+'.deny.'+route,'readonly','access','/access/api/'+route,403,
                 label+'.admin-session',requires=(label+'.admin-bootstrap',))
        for route in ('decision','revoke'):
            form={'request_id':'@primary','version':1,'reason':'Synthetic negative control'}
            if route=='decision':form['action']='approve'
            post(label+'.deny.'+route,'readonly',route,label+'.admin-session',form,403,
                 requires=(label+'.admin-bootstrap','registration.approve'),unchanged=True)
    for method,path in (('POST','/api/members'),('POST','/api/tasks'),
                        ('PATCH','/api/tasks/1'),('DELETE','/api/tasks/1'),('GET','/api/members')):
        http('registered.deny.'+method+path,'readonly','board',path,403,'reg.primary',method,
             requires=approved,payload={} if method!='GET' else None)
    http('registered.header-conflict','readonly','board','/api/session',403,'reg.primary',
         requires=approved,headers={'X-Auth-User':'fstech','X-Auth-Role':'admin'})
    http('native.header-conflict','readonly','board','/api/session',403,'native.fstech',
         headers={'X-Auth-User':'fstech','X-Auth-Role':'readonly'})
    http('direct.method-spoof','readonly','board','/api/members',403,'reg.primary','POST',
         requires=approved,payload={},headers={'X-Original-URI':SESSION_READ_URI,'X-Original-Method':'GET'})
    http('registered.no-native-membership','readonly','board','/api/members',200,'native.fstech',
         requires=approved,checks=['no_registered_members'])
    local('expired-fixtures','negative-identities','expired-fixtures',approved)
    for label,req in (('anonymous',()),('invalid',()),('old-FC',()),('forged',()),
                      ('expired-native',()),('expired-registered',('expired-fixtures',))):
        verify(label+'.verify','negative-identities',label,401,requires=req)
        for service,path in (('board','/api/session'),('fc','/analysis')):
            http(label+'.'+service,'negative-identities',service,path,401,label,requires=req,
                 headers={'X-Auth-User':'fstech','X-Auth-Role':'admin'},checks=['no_analysis_marker'])
    verify('mixed.verify','negative-identities','mixed',403,requires=approved)
    http('mixed.board','negative-identities','board','/api/session',403,'mixed',requires=approved)
    http('mixed.fc','negative-identities','fc','/analysis',401,'mixed',requires=approved,
         checks=['no_analysis_marker'])

    for label,session,req in (('anonymous','anonymous',()),('registered','reg.primary',approved),
                              ('native-admin','native.fstech',())):
        for path in ('/verify','/admin','/admin/audit','/unknown'):
            http('retired.'+label+'.GET'+path,'retired-fc','fc',path,401 if path=='/verify' else 403,
                 session,requires=req,checks=['no_analysis_marker'])
        for path in ('/login','/register','/logout','/admin/action','/analysis'):
            http('retired.'+label+'.POST'+path,'retired-fc','fc',path,405,session,'POST',
                 requires=req,payload={},checks=['no_set_cookie','no_analysis_marker'])
    for path in ('/','/login','/register','/logout'):
        http('retired.redirect'+path,'retired-fc','fc',path,302,checks=['access_redirect'])

    for label,session,req in (('native','http.admin',('admin.http-login',)),
                              ('registered','reg.primary',approved)):
        for fault in ('csrf','origin'):
            case=label+'.logout-deny.'+fault
            post(case,'logout-controls','logout',session,{},403,requires=req,
                 auth_fault=fault,checks=['no_set_cookie'],unchanged=True)
            verify(case+'.still-live','logout-controls',session,
                   role='admin' if label=='native' else 'readonly',requires=req)
    post('registered.logout-extra-field','logout-controls','logout','reg.primary',{'role':'admin'},400,
         requires=approved,checks=['no_set_cookie'],unchanged=True)
    login('registered.logout-login','logout-controls','guest.logout','reg.logout','newreader',
          requires=approved,role='readonly')
    post('registered.logout','logout-controls','logout','reg.logout',{},
         requires=('registered.logout-login',),checks=['clear_two'])
    verify('registered.logged-out','logout-controls','reg.logout',401,requires=('registered.logout',))
    http('registered.logged-out.fc','logout-controls','fc','/analysis',401,'reg.logout',
         requires=('registered.logout',),checks=['no_analysis_marker'])
    verify('registered.independent-retained','logout-controls','reg.primary',role='readonly',
           requires=approved)
    login('registered.multi-login','logout-controls','guest.multi','reg.multi','newreader',
          requires=approved,role='readonly')
    local('registered-session-distinction','logout-controls','registered-session-distinction',
          ('registered.multi-login','registration.login','registered.logout-login'))

    for name in ADMINS:
        http('edge.admin.'+name,'nginx-contract','edge',SESSION_READ_URI,200,'native.'+name,
             role='admin',subject=name,headers={'X-Auth-User':'forged','X-Auth-Role':'readonly','X-Auth-Groups':'forged'},
             trace_check='admin-overwrite')
    http('edge.editor','nginx-contract','edge',SESSION_READ_URI,200,'native.oldreader',role='editor',subject='oldreader')
    http('edge.registered','nginx-contract','edge',SESSION_READ_URI,200,'reg.primary',role='viewer',
         requires=approved,subject='registered',headers={'X-Auth-User':'fstech','X-Auth-Role':'admin','X-Auth-Groups':'deploy'},
         trace_check='registered-overwrite')
    http('edge.anonymous','nginx-contract','edge',SESSION_READ_URI,302,checks=['access_redirect'])
    http('edge.query-denied','nginx-contract','edge',SESSION_REJECT_URI,403,'reg.primary',requires=approved)
    for method,path in (('POST','/dashboard/tasks/api/members'),('PATCH','/dashboard/tasks/api/tasks/1'),
                        ('DELETE','/dashboard/tasks/api/tasks/1')):
        http('edge.actual-method.'+method,'nginx-contract','edge',path,403,'reg.primary',method,
             requires=approved,payload={},headers={'X-Original-URI':SESSION_READ_URI,'X-Original-Method':'GET'},
             trace_check='actual-method')
    for label,session,status,req in (('registered','reg.primary',200,approved),
                                    ('editor','native.oldreader',200,()),('admin','native.fstech',200,()),
                                    ('anonymous','anonymous',401,()),('expired','expired-native',401,())):
        for method in ('GET','HEAD'):
            http('edge.fc.'+label+'.'+method,'nginx-contract','edge','/fc27/analysis',status,session,method,
                 requires=req,checks=['head_empty'] if method=='HEAD' else ['analysis_marker' if status==200 else 'no_analysis_marker'])
    http('edge.fc.query-denied','nginx-contract','edge','/fc27/analysis?probe=%2F',401,'reg.primary',requires=approved)

    local('db-hide','storage-loss','db-hide',('initialize',))
    for label,session in (('registered','reg.primary'),('native','http.admin.native-only')):
        dep=('db-hide','registration.approve' if label=='registered' else 'admin.http-login')
        verify('db-loss.'+label,'storage-loss',session,503,requires=dep)
    http('db-loss.board','storage-loss','board','/api/session',503,'reg.primary',requires=('db-hide','registration.approve'))
    http('db-loss.edge','storage-loss','edge',SESSION_READ_URI,'5xx','reg.primary',
         requires=('db-hide','registration.approve'),trace_check='verifier-unavailable')
    http('db-loss.fc','storage-loss','fc','/analysis',401,'reg.primary',
         requires=('db-hide','registration.approve'),checks=['no_analysis_marker'])
    http('db-loss.bootstrap','storage-loss','access','/access/api/bootstrap',503,requires=('db-hide',),checks=['no_set_cookie'])
    post('db-loss.logout','storage-loss','logout','http.admin',{},503,
         requires=('db-hide','admin.http-login'),checks=['no_set_cookie'])
    local('db-not-recreated','storage-loss','db-not-recreated',('db-hide',))
    local('db-restore','storage-loss','db-restore',('db-hide',),always=True)
    verify('db-restored.registered','storage-loss','reg.primary',role='readonly',
           requires=('db-restore','registration.approve'))
    verify('db-restored.native','storage-loss','http.admin.native-only',role='admin',
           requires=('db-restore','admin.http-login'))

    post('registered.revoke','revocation','revoke','http.admin',
         {'request_id':'@primary','version':1,'reason':'Synthetic HTTP account revoke'},
         requires=('registration.approve','admin.http-login','db-restore'),
         json_fields={'state':'revoked','version':2})
    for label,session,dep in (('primary','reg.primary','registration.login'),('second','reg.multi','registered.multi-login')):
        verify('revoked.'+label,'revocation',session,401,requires=('registered.revoke',dep))
        http('revoked.'+label+'.board','revocation','board','/api/session',401,session,requires=('registered.revoke',dep))
        http('revoked.'+label+'.fc','revocation','fc','/analysis',401,session,requires=('registered.revoke',dep),checks=['no_analysis_marker'])
    http('revoked.edge','revocation','edge',SESSION_READ_URI,302,'reg.primary',
         requires=('registered.revoke',),checks=['access_redirect'])
    http('revoked.edge.fc','revocation','edge','/fc27/analysis',401,'reg.primary',requires=('registered.revoke',))
    local('account-revoke-epoch','revocation','account-revoke-epoch',('registered.revoke','registered.multi-login','expired-fixtures'))
    post('native.exact-logout','revocation','logout','http.admin',{},
         requires=('admin.http-login','db-restore'),checks=['clear_two'])
    for label,session in (('raw','http.admin.native-only'),('combined','http.admin')):
        verify('native.logged-out.'+label,'revocation',session,401,requires=('native.exact-logout',))
    http('native.logged-out.status','revocation','access','/status',302,'http.admin.native-only',
         requires=('native.exact-logout',),checks=['login_redirect'])
    for service,path,status in (('board','/api/session',401),('fc','/analysis',401),('edge',SESSION_READ_URI,302)):
        http('native.logged-out.'+service,'revocation',service,path,status,'http.admin.native-only',
             requires=('native.exact-logout',))
    for label in ('http.independent','native.fstech','native.wulv','native.oldreader'):
        dep=('native.exact-logout',)+(('independent.http-login',) if label=='http.independent' else ())
        verify('native.retained.'+label,'revocation',label,role='readonly' if label.endswith('oldreader') else 'admin',requires=dep)

    local('recovery-start','recovery','recovery-start',('services','db-restore'))
    for label,session,dep in (('native','http.admin.native-only','native.exact-logout'),
                              ('registered','reg.primary','registered.revoke'),
                              ('registered-second','reg.multi','registered.revoke'),
                              ('registered-logout','reg.logout','registered.logout')):
        req=('recovery-start',dep)+(('registered.multi-login',) if label=='registered-second' else ())
        verify('recovery.denied.'+label,'recovery',session,401,requires=req)
        for service,path,status in (('board','/api/session',401),('fc','/analysis',401),('edge',SESSION_READ_URI,302)):
            http('recovery.denied.'+label+'.'+service,'recovery',service,path,status,session,requires=req)
    http('recovery.native-status','recovery','access','/status',302,'http.admin.native-only',
         requires=('recovery-start','native.exact-logout'),checks=['login_redirect'])
    for label,session,role,boardrole,req in (
            ('registered','reg.other','readonly','viewer',('other.approve',)),
            ('independent','http.independent','admin','admin',('independent.http-login',)),
            ('initial-admin','native.fstech','admin','admin',()),
            ('admin','native.wulv','admin','admin',()),
            ('editor','native.oldreader','readonly','editor',())):
        needs=('recovery-start',)+req
        verify('recovery.retained.'+label,'recovery',session,role=role,requires=needs)
        http('recovery.retained.'+label+'.board','recovery','board','/api/session',200,session,role=boardrole,requires=needs)
        http('recovery.retained.'+label+'.fc','recovery','fc','/analysis',200,session,requires=needs,checks=['analysis_marker'])
    http('recovery.bootstrap','recovery','access','/access/api/bootstrap',503,'native.wulv',
         requires=('recovery-start',),checks=['no_set_cookie'])
    for route in ('register','login','native-login','apply','decision','revoke','logout'):
        http('recovery.api.'+route,'recovery','access','/access/api/'+route,503,'native.wulv','POST',
             requires=('recovery-start',),payload={},checks=['no_set_cookie'])
    for route in ('requests','audit'):
        http('recovery.api.'+route,'recovery','access','/access/api/'+route,503,'native.wulv',requires=('recovery-start',))
    http('recovery.static','recovery','access','/access/',200,requires=('recovery-start',))
    local('recovery-retention','recovery','recovery-retention',('recovery-start',))
    http('recovery.legacy-login','recovery','access','/login',302,method='POST',
         requires=('recovery-start',),form_login=True,save_native='recovery.legacy-native')
    verify('recovery.legacy-verify','recovery','recovery.legacy-native',role='readonly',
           requires=('recovery.legacy-login',))
    local('recovery-retention-after-login','recovery','recovery-retention',('recovery.legacy-login',))
    local('upstream-stop','upstream-loss','upstream-stop',('recovery-start',))
    http('upstream-loss.board','upstream-loss','board','/api/session',503,'native.wulv',requires=('upstream-stop',))
    http('upstream-loss.fc','upstream-loss','fc','/analysis',401,'native.wulv',requires=('upstream-stop',),checks=['no_analysis_marker'])
    http('upstream-loss.edge','upstream-loss','edge',SESSION_READ_URI,'5xx','native.wulv',requires=('upstream-stop',))
    local('old-fc-db-absent','assurance','old-fc-db-absent')
    local('worker-versions','assurance','worker-versions',('recovery-start',))
    local('owned-cleanup','assurance','owned-cleanup',finalize=True)
    local('source-post','assurance','source-post',finalize=True)
    local('temp-cleanup','assurance','temp-cleanup',finalize=True)
    return rows


CONTRACT_PLAN = build_contract_plan()


def validate_contract_plan():
    ids = set()
    methods = {'GET','HEAD','POST','PATCH','DELETE'}
    services = {'portal','access','board','fc','edge','http'}
    allowed_checks = {'head_empty','analysis_marker','no_analysis_marker','no_set_cookie',
                      'secure_two','clear_two','no_registered_members','access_redirect','login_redirect','fixed_https_redirect'}
    for row in CONTRACT_PLAN:
        if row['id'] in ids or row['phase'] not in PHASES:
            raise ValueError('duplicate/unrecognized contract case')
        if any(dep not in ids for dep in row['requires']):
            raise ValueError('forward/missing contract prerequisite')
        ids.add(row['id'])
        if row['operation']=='http':
            if (row['service'] not in services or row['method'] not in methods
                    or not row['path'].startswith('/') or any(c in row['path'] for c in '\r\n#')
                    or row['expected_status'] not in (200,302,308,400,401,403,405,409,503,'5xx')
                    or row['expected_role'] not in (None,'guest','pending','readonly','admin','editor','viewer')
                    or set(row.get('checks',()))-allowed_checks):
                raise ValueError('invalid HTTP contract row')
    required = {'missing-store','insecure-cookie','admin.http-login','native-token-distinction',
                'registration.create','registration.login','registration.approve','other.reject','other.reapply',
                'registered.fc.get','registered.fc.head','editor.members.read','status.raw-native','status.combined',
                'native.exact-logout','registered.revoke','account-revoke-epoch','db-loss.edge',
                'db-loss.logout','recovery-retention','recovery.legacy-login','worker-versions','owned-cleanup'}
    if not required.issubset(ids) or len(CONTRACT_PLAN)<250:
        raise ValueError('incomplete release contract coverage')
    for name in ADMINS:
        if 'edge.admin.'+name not in ids or 'native.'+name+'.verify' not in ids:
            raise ValueError('four retained native admins must all be exercised')
    digest = hashlib.sha256(json.dumps(CONTRACT_PLAN,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'contract_cases':len(CONTRACT_PLAN),'contract_sha256':digest,
            'contract_phases':list(PHASES),'contract_dependencies_valid':True}


def access_redirect_matches(location, request_uri=None, https_port=None):
    """Allow only this fixture's exact relative or trusted HTTPS redirect.

    For an edge row, pass the original finite-plan request_uri and the actual
    owned HTTPS port. For portal/FC redirects, omit both: only the exact relative
    '/__auth/access/' with no query is permitted. No URL is followed.
    """
    if not isinstance(location, str) or not location:
        return False
    if any(ord(c) <= 32 or ord(c) >= 127 for c in location) or '\\' in location or '#' in location:
        return False
    path = '/__auth/access/'
    if request_uri is None:
        return https_port is None and location == path
    if (not isinstance(request_uri, str) or not request_uri.startswith('/')
            or request_uri.startswith('//') or '\\' in request_uri or '#' in request_uri
            or any(ord(c) <= 32 or ord(c) >= 127 for c in request_uri)
            or type(https_port) is not int or not 1 <= https_port <= 65535):
        return False
    query = 'next=' + request_uri
    relative = path + '?' + query
    try:
        parsed = urlsplit(location)
        if parsed.path != path or parsed.query != query or parsed.fragment:
            return False
        if not parsed.scheme and not parsed.netloc:
            return location == relative
        host = '47.85.224.112'
        authorities = {host + ':' + str(https_port)}
        if https_port == 443:
            authorities.add(host)
        if (parsed.scheme != 'https' or parsed.hostname != host
                or parsed.username is not None or parsed.password is not None
                or parsed.netloc not in authorities
                or (parsed.port if parsed.port is not None else 443) != https_port):
            return False
        # Compare the original suffix as well: no parser-induced stripping,
        # empty query/fragment delimiter or path/query normalization is allowed.
        return location == 'https://' + parsed.netloc + relative
    except (ValueError, TypeError):
        return False


def response_cookie_jar(response, previous=None):
    """Preserve every Set-Cookie field; jars and exact tokens stay only in memory."""
    result = dict(previous or {})
    for name, value in response['pairs']:
        if name.lower()=='set-cookie':
            key, separator, token = value.split(';',1)[0].partition('=')
            if not separator or not key:
                raise ValueError('malformed response cookie')
            if token: result[key]=token
            else: result.pop(key,None)
    return result


class ControllerTermination(BaseException):
    """A controller signal must escape case-level Exception handling."""


class ContractRunner:
    """Importable scenario engine. No interpreter guard bypass or alternate CLI.

    A caller may use this pure engine for an explicitly separate source-HTTP
    diagnostic with its own transport. Only run() establishes target assurance.
    Exceptions are failures, unmet prerequisites are BLOCKED, deadline omissions
    are NOT_RUN. Tokens, headers and bodies are never copied to result rows.
    """
    def __init__(self, transport, actions, context, deadline, plan=None):
        self.transport=transport; self.actions=actions; self.context=context
        self.deadline=deadline; self.plan=CONTRACT_PLAN if plan is None else plan
        self.results=[]; self.by_id={}

    def record(self, row, outcome, status=None, role=None, **facts):
        result={'case':row['id'],'phase':row['phase'],'outcome':outcome,
                'expected_status':row['expected_status'],'actual_status':status,
                'expected_role':row['expected_role'],'actual_role':role}
        if row['operation']=='http':
            result.update(service=row['service'],method=row['method'],path=row['path'],
                          session_label=row['session'])
        else:
            result['expected_value']=True
        result.update(facts)
        self.results.append(result);self.by_id[row['id']]=result
        return result

    def perform(self, row):
        if row['id'] in self.by_id:raise ValueError('contract case already recorded')
        blocked=[dep for dep in row['requires'] if self.by_id.get(dep,{}).get('outcome')!='PASS']
        if blocked:
            return self.record(row,'BLOCKED',blocked_by=blocked)
        if time.monotonic()>self.deadline and not row.get('always') and not row.get('finalize'):
            return self.record(row,'NOT_RUN',reason='120-second execution budget exhausted')
        try:
            if row['operation']=='http':return self.http(row)
            result=self.actions[row['operation']](row)
            return self.record(row,'PASS' if result.get('ok') is True else 'FAIL',
                               actual_value=result.get('ok') is True,**result.get('facts',{}))
        except Exception as exc:
            # Exception strings can include response bodies, SQL or cookie values.
            return self.record(row,'FAIL',error_type=type(exc).__name__)

    def http(self, row):
        ctx=self.context
        label=row['session']
        if label=='mixed':
            jar=dict(ctx['sessions']['reg.primary']);jar.update(ctx['sessions']['native.fstech'])
        else:jar=dict(ctx['sessions'][label])
        headers=dict(row.get('headers',{}));payload=row.get('payload');body=None
        if payload is not None:
            payload={key:ctx['requests'][value[1:]] if isinstance(value,str) and value.startswith('@') else value
                     for key,value in payload.items()}
            body=json.dumps(payload,separators=(',',':')).encode()
            headers['Content-Type']='application/json'
        if row.get('api'):
            headers.update({'Origin':ORIGIN,'X-CSRF-Token':ctx['csrf'][label],
                            'Content-Type':'application/json'})
            if row.get('auth_fault')=='csrf':headers['X-CSRF-Token']='synthetic-wrong-csrf'
            if row.get('auth_fault')=='origin':headers['Origin']='https://synthetic.invalid'
        if row.get('form_login'):
            body=b'username=oldreader&password=Synthetic-password-42&next=%2Fdashboard%2F'
            headers['Content-Type']='application/x-www-form-urlencoded'
        before=ctx['storage_hashes']() if row.get('unchanged') else None
        trace_offset=ctx['trace_offset']() if row.get('trace_check') else None
        response=self.transport(row['service'],row['path'],row['method'],jar,headers,body)
        status=response['status'];document=response.get('json')
        document=document if isinstance(document,dict) else {}
        pairs=response['pairs'];lookup={key.lower():value for key,value in pairs}
        viewer=document.get('viewer');viewer=viewer if isinstance(viewer,dict) else {}
        account=document.get('account');account=account if isinstance(account,dict) else {}
        role=viewer.get('role') or account.get('role') or lookup.get('x-auth-role')
        # Never emit arbitrary server-controlled role/body strings in a receipt.
        actual_role=role if role in ('guest','pending','readonly','admin','editor','viewer') else ('unexpected' if role is not None else None)
        subject=viewer.get('user') or lookup.get('x-auth-user')
        wanted=row['expected_status']
        checks={'status':500<=status<=599 if wanted=='5xx' else status==wanted,
                'role':row['expected_role'] is None or role==row['expected_role']}
        if 'subject' in row:
            wanted_subject=row['subject']
            checks['subject']=(bool(re.fullmatch(r'reg:[a-f0-9-]{36}',subject or ''))
                               if wanted_subject=='registered' else subject==wanted_subject)
        setcookies=[value for key,value in pairs if key.lower()=='set-cookie']
        cookie_names={value.split('=',1)[0] for value in setcookies}
        expected_cookie_names={ctx['native_cookie'],ctx['registered_cookie']}
        for condition in row.get('checks',()):
            if condition=='head_empty':value=response['body']==b''
            elif condition=='analysis_marker':value=document.get('synthetic') is True
            elif condition=='no_analysis_marker':value=document.get('synthetic') is not True and b'"synthetic":true' not in response['body'].replace(b' ',b'')
            elif condition=='no_set_cookie':value=len(setcookies)==0
            elif condition=='secure_two':value=len(setcookies)==2 and cookie_names==expected_cookie_names and all('secure' in [part.strip().lower() for part in v.split(';')] for v in setcookies)
            elif condition=='clear_two':value=len(setcookies)==2 and cookie_names==expected_cookie_names and all('max-age=0' in [part.strip().lower() for part in v.split(';')] for v in setcookies)
            elif condition=='no_registered_members':
                members=document.get('members')
                value=isinstance(members,list) and all(isinstance(member,dict) and not str(member.get('username','')).startswith('reg:') and member.get('username') not in ('newreader','otherreader') for member in members)
            elif condition=='access_redirect':
                value=(access_redirect_matches(lookup.get('location'),row['path'],ctx['https_port'])
                       if row['service']=='edge' else access_redirect_matches(lookup.get('location')))
            elif condition=='login_redirect':value=lookup.get('location','').startswith('/__auth/login')
            elif condition=='fixed_https_redirect':value=lookup.get('location')==ORIGIN+'/__auth/access/'
            else:raise ValueError('unknown response assertion')
            checks[condition]=value
        for key,value in row.get('json_fields',{}).items():checks['json_'+key]=document.get(key)==value
        if row.get('unchanged'):checks['storage_unchanged']=before==ctx['storage_hashes']()
        if row.get('trace_check'):checks['correlated_trace']=ctx['trace_check'](row,trace_offset)
        updated=response_cookie_jar(response,jar)
        if row.get('save_session'):
            checks['session_cookie_present']=bool(updated.get(ctx['registered_cookie']))
            checks['csrf_present']=isinstance(document.get('csrf'),str) and bool(document['csrf'])
        if row.get('save_request'):
            checks['request_id_present']=bool(re.fullmatch(r'[a-f0-9-]{36}',str(document.get('request_id',''))))
        if row.get('save_native'):checks['native_cookie_present']=bool(updated.get(ctx['native_cookie']))
        passed=all(value is True for value in checks.values())
        if passed:
            if row.get('save_session'):
                name=row['save_session'];ctx['sessions'][name]=updated;ctx['csrf'][name]=document['csrf']
                if ctx['native_cookie'] in updated:
                    ctx['sessions'][name+'.native-only']={ctx['native_cookie']:updated[ctx['native_cookie']]}
            if row.get('save_request'):ctx['requests'][row['save_request']]=document['request_id']
            if row.get('save_native'):ctx['sessions'][row['save_native']]={ctx['native_cookie']:updated[ctx['native_cookie']]}
        return self.record(row,'PASS' if passed else 'FAIL',status,actual_role,
                           assertions=checks,expected_subject=row.get('subject'),
                           subject_matches=checks.get('subject'),set_cookie_count=len(setcookies))

    def execute(self):
        for row in self.plan:
            if not row.get('finalize'):self.perform(row)
        return self.results

    def finish_unrecorded(self, reason):
        for row in self.plan:
            if row['id'] not in self.by_id:
                self.record(row,'NOT_RUN',reason=reason)



def stop_upstream_listener(child, listener, port, children, stop, deadline):
    """Make the owned verifier genuinely unavailable, not silently still listening.

    listen() on the worker's inherited socket also changes the parent's socket.
    The controller retains that FD for the formal-to-recovery handover, so it must
    release it when no further portal worker will start. Never accept a timeout
    as evidence of an unavailable listener or as an HTTP result.
    """
    inode = os.readlink('/proc/self/fd/' + str(listener.fileno()))
    stop(child)
    if child.poll() is None:
        raise RuntimeError('owned upstream child was not reaped')
    listener.close()
    holders = 0
    for process in children:
        if process.poll() is not None:
            continue
        for descriptor in Path('/proc/%d/fd' % process.pid).iterdir():
            try:
                if os.readlink(descriptor) == inode:
                    holders += 1
            except FileNotFoundError:
                pass
    # Kernel LISTEN state covers every holder, including Nginx grandchildren;
    # direct child descriptor inspection additionally checks inheritance scope.
    listeners = 0
    for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
        fields = line.split()
        if int(fields[1].split(':')[1], 16) == port and fields[3] == '0A':
            listeners += 1
    remaining = min(0.25, deadline-time.monotonic())
    if remaining <= 0:
        raise TimeoutError('upstream shutdown verification deadline')
    probe = socket.socket()
    try:
        probe.settimeout(remaining)
        code = probe.connect_ex(('127.0.0.1', port))
    finally:
        probe.close()
    return {'ok': holders == 0 and listeners == 0 and code == errno.ECONNREFUSED,
            'facts': {'upstream_child_reaped': True, 'controller_listener_closed': True,
                      'owned_live_child_inode_holders': holders,
                      'remaining_listener_count': listeners, 'connect_errno': code}}


def run(args):
    if args.source_root is None or args.nginx is None or args.openssl is None or args.output is None:
        raise ValueError('source-root, nginx, openssl and fresh output paths required')
    root=args.source_root
    release=verify_inputs(root)
    # This guard is unconditional. Importing the contract engine is not a target run.
    if sys.platform!='linux' or sys.version_info[:3]!=(3,9,18) or sqlite3.sqlite_version!='3.53.4':
        raise ValueError('requires existing authorized Linux Python3.9.18 + SQLite3.53.4')
    nginx=args.nginx.resolve(strict=True)
    openssl=args.openssl.resolve(strict=True)
    version=subprocess.run([str(nginx),'-V'],capture_output=True,text=True,timeout=5)
    if (version.returncode or 'nginx/1.26.1' not in version.stderr
            or '--with-http_auth_request_module' not in version.stderr
            or '--with-http_ssl_module' not in version.stderr):
        raise ValueError('requires existing Nginx1.26.1 auth_request + ssl modules')
    output=args.output.resolve()
    if output.exists():raise ValueError('fresh QA receipt path required')
    contract=validate_contract_plan()
    receipt={'status':'RUNNING','synthetic_only':True,'production_write':False,
             'old43plus4_rerun':False,'source_commit':SOURCE_COMMIT,
             'source_manifest_sha256':SOURCE_MANIFEST_SHA,'runtime_subtree':RUNTIME_SUBTREE,
             'driver_sha256':sha(__file__),'driver_commit':os.environ.get('DRIVER_COMMIT'),
             'production_nginx_verified':False,'production_ready':False,
             'production_systemd_or_real_roles_verified':False,'source_modified':False,
             'python':sys.version,'sqlite':sqlite3.sqlite_version,'nginx':'1.26.1',
             'kernel':os.uname().release,'recovery_sha256':release['recovery']['sha256'],
             'source_pre_sha256':release['verified_file_sha256'],**contract,
             'receipt_policy':'No cookie values, token hashes, CSRF values, request/response bodies or raw logs',
             'session_tracking':'Exact HTTP-issued tokens retained in named in-memory jars; logout never substitutes fixture tokens',
             'QA_projection':['synthetic data, credentials and local TLS certificate',
                              'owned loopback sockets and finite route allowlist',
                              'runtime path/native-policy loader mapping and isolated store boundary',
                              'sanitized per-request header/method/URI observers',
                              'fixed minimal Nginx fixture without live includes; not production Nginx']}
    deadline=time.monotonic()+120
    children=[];handles=[];worker_logs=[];sockets={};state={}
    ctx={'sessions':{'anonymous':{},'old-FC':{'fc27sess':'synthetic-old'},
                     'forged':{'MMOEXP_AUTH':'synthetic-forged'}},'csrf':{},'requests':{}}
    tmp=tempfile.TemporaryDirectory(prefix='fs-registration-seamqa-')
    scratch=Path(tmp.name);os.chmod(scratch,0o700)
    data=scratch/'fs-registration-data';data.mkdir(mode=0o700)
    (scratch/'board').mkdir()
    (scratch/'login.html').write_text('Synthetic native login template',encoding='utf-8')
    (scratch/'status.html').write_text('Synthetic native status {{USER}}',encoding='utf-8')
    (scratch/'analysis.json').write_text('{"synthetic":true}',encoding='utf-8')
    (scratch/'board-seed.json').write_text(json.dumps({'groups':[],'depts':[],'tasks':[],
        'members':[{'username':'oldreader','role':'editor','displayName':'Synthetic reader'}]}),encoding='utf-8')
    tracefile=scratch/'trace.jsonl';tracefile.touch(mode=0o600)
    for name in ('portal','fc','board','http','https','blocked'):sockets[name]=port_socket()
    ports={name:sock.getsockname()[1] for name,sock in sockets.items()}
    ctx['https_port']=ports['https']
    db=data/'registration-approval/registration.sqlite3'
    anchor=data/'.registration-checkpoint/state.json'
    moved=db.with_suffix('.unavailable-QA')
    env={key:value for key,value in os.environ.items() if key in ('PATH','LD_LIBRARY_PATH','LANG','LC_ALL','TMPDIR')}
    env.update({'HOME':str(scratch),'AUTH_DATA_DIR':str(data),
        'AUTH_SECRET':'Synthetic-secret-for-isolated-seam-QA',
        'AUTH_GROUPS':'dashboard='+str(scratch/'synthetic-members'),'AUTH_COOKIE_SECURE':'1',
        'AUTH_TEMPLATE':str(scratch/'login.html'),'AUTH_STATUS_TEMPLATE':str(scratch/'status.html'),
        'AUTH_PORT':str(ports['portal']),'AUTH_BIND':'127.0.0.1',
        'FC27_PORT':str(ports['fc']),'FC27_DB':str(scratch/'never-create-old-FC.sqlite3'),
        'FC27_ANALYSIS':str(scratch/'analysis.json'),'TASKBOARD_PORT':str(ports['board']),
        'TASKBOARD_BIND':'127.0.0.1','TASKBOARD_DATA':str(scratch/'board'),
        'TASKBOARD_SEED':str(scratch/'board-seed.json'),'TASKBOARD_QUIET':'1',
        'FS_QA_TRACE':str(tracefile),'FS_QA_PORTAL_PORT':str(ports['portal']),
        'PYTHONDONTWRITEBYTECODE':'1'})

    def remaining(cap=5):
        left=deadline-time.monotonic()
        if left<=0:raise TimeoutError('bounded QA execution deadline')
        return min(cap,left)
    def start(kind,secure=True):
        key='portal' if kind=='recovery' else kind
        log=scratch/(kind+'-'+str(len(worker_logs))+'.log')
        handle=open(log,'wb');handles.append(handle)
        child=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),
            '--source-root',str(root),'--worker',kind,'--fd',str(sockets[key].fileno())],
            env=dict(env,AUTH_COOKIE_SECURE='1' if secure else '0'),stdout=handle,stderr=handle,
            pass_fds=(sockets[key].fileno(),),start_new_session=True)
        children.append(child);worker_logs.append(log)
        return child
    def stop(child):
        if child.poll() is None:
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:child.wait(timeout=remaining())
            except subprocess.TimeoutExpired:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait(timeout=remaining())
    def owned_listener(child,port):
        if child.poll() is not None:return False
        descriptors=[]
        for path in Path('/proc/%d/fd'%child.pid).iterdir():
            try:descriptors.append(os.readlink(path))
            except OSError:pass
        for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
            fields=line.split()
            if (int(fields[1].split(':')[1],16)==port and fields[3]=='0A'
                    and 'socket:['+fields[9]+']' in descriptors):return True
        return False
    def ready(child,port):
        until=time.monotonic()+remaining(8)
        while time.monotonic()<until:
            if owned_listener(child,port):return
            if child.poll() is not None:raise RuntimeError('owned QA service failed startup')
            time.sleep(0.025)
        raise TimeoutError('owned QA service readiness deadline')
    def storage_hashes():return (sha(db),sha(anchor))
    ctx['storage_hashes']=storage_hashes
    ctx['trace_offset']=lambda:tracefile.stat().st_size
    def trace_check(row,offset):
        with tracefile.open('r',encoding='utf-8') as stream:
            stream.seek(offset)
            records=[json.loads(line) for line in stream if line.strip()]
        method=row['method'];uri=row['path'];mode=row['trace_check']
        verified=[r for r in records if r.get('kind')=='verify' and r.get('method')==method and r.get('uri')==uri]
        wire=[r for r in records if r.get('kind')=='portal-verify-wire' and r.get('method')==method and r.get('uri')==uri]
        if mode=='verifier-unavailable':return any(r.get('status')==503 for r in wire)
        if mode=='actual-method':return any(r.get('status')==403 for r in wire) and any(r.get('status')==403 for r in verified)
        inputs=[r for r in records if r.get('kind')=='board-input' and r.get('method')==method
                and r.get('path')==uri[len('/dashboard/tasks'):]]
        if mode=='admin-overwrite':
            name=row['session'].split('.',1)[1]
            return any(r.get('status')==200 and r.get('role')=='admin' for r in verified) and any(
                r.get('user')==name and r.get('role')=='admin'
                and 'deploy' in (r.get('groups') or '').split(',')
                and 'forged' not in (r.get('groups') or '').split(',') for r in inputs)
        if mode=='registered-overwrite':
            return any(r.get('status')==200 and r.get('role')=='readonly' for r in verified) and any(
                re.fullmatch(r'reg:[a-f0-9-]{36}',r.get('user') or '') and r.get('role')=='readonly'
                and 'deploy' not in (r.get('groups') or '').split(',')
                and 'forged' not in (r.get('groups') or '').split(',') for r in inputs)
        raise ValueError('unknown trace assertion')
    ctx['trace_check']=trace_check
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
    allowed={(r['service'],r['path'],r['method']) for r in CONTRACT_PLAN if r['operation']=='http'}
    def transport(service,path,method,jar,headers,body):
        if (service,path,method) not in allowed:raise ValueError('request outside finite contract routes')
        target={'access':'https','edge':'https','http':'http'}.get(service,service)
        public='/__auth'+path if service=='access' else path
        timeout=remaining(3)
        conn=(http.client.HTTPSConnection('127.0.0.1',ports[target],context=context,timeout=timeout)
              if target=='https' else http.client.HTTPConnection('127.0.0.1',ports[target],timeout=timeout))
        values={'Host':'47.85.224.112','Cookie':'; '.join(key+'='+value for key,value in jar.items()),'Connection':'close'}
        values.update(headers)
        try:
            conn.request(method,public,body=body,headers=values)
            response=conn.getresponse();payload=response.read(1048577)
            if len(payload)>1048576:raise ValueError('response exceeds bounded allowance')
            pairs=response.getheaders()
            try:document=json.loads(payload)
            except (ValueError,UnicodeError):document=None
            return {'status':response.status,'pairs':pairs,'body':payload,'json':document}
        finally:conn.close()

    def action(row):
        op=row['operation'];facts={};ok=False
        if op=='missing-store':
            child=start('portal');code=child.wait(timeout=remaining())
            text=worker_logs[-1].read_text(encoding='utf-8',errors='replace')
            ok=(code!=0 and 'FileNotFoundError' in text and 'registration-approval' in text
                and not (data/'registration-approval').exists() and not (data/'.registration-checkpoint').exists())
            facts={'returncode':code,'never_initialized':not (data/'registration-approval').exists()}
        elif op=='initialize':
            previous=dict(os.environ)
            try:
                os.environ.clear();os.environ.update(env)
                portal,runtime,policy=load_candidate(root,'portal')
                if tuple(sorted(policy.ADMINS))!=ADMINS:raise ValueError('frozen native admin list differs')
                encoded=portal.apr1_md5(PASSWORD,'qa123456')
                (scratch/'synthetic-members').write_text('\n'.join(name+':'+encoded for name in (*ADMINS,'oldreader'))+'\n',encoding='utf-8')
                runtime.RuntimeStore.initialize_fresh(data,portal,isolated=True)
                store,adapter,app=runtime.build(data,portal,ORIGIN,isolated=True)
                state.update(portal=portal,runtime=runtime,store=store,adapter=adapter)
                ctx['native_cookie']=portal.CFG['cookie'];ctx['registered_cookie']=runtime.core.COOKIE
                for name in (*ADMINS,'oldreader'):
                    token,_=adapter.native_login(name,PASSWORD)
                    ctx['sessions']['native.'+name]={portal.CFG['cookie']:token}
                ctx['sessions']['invalid']={runtime.core.COOKIE:'synthetic-invalid-session'}
                ctx['sessions']['expired-native']={portal.CFG['cookie']:portal.make_token('fstech',['dashboard'],-60)}
                ok=True
            finally:os.environ.clear();os.environ.update(previous)
        elif op=='insecure-cookie':
            child=start('portal',False);code=child.wait(timeout=remaining())
            text=worker_logs[-1].read_text(encoding='utf-8',errors='replace')
            ok=code!=0 and 'HTTPS runtime refuses insecure native cookie configuration' in text
            facts={'returncode':code}
        elif op=='services':
            for name in ('portal','fc','board'):
                state[name+'_child']=start(name);ready(state[name+'_child'],ports[name])
            ok=True
        elif op=='tls':
            result=subprocess.run([str(openssl),'req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                '-subj','/CN=synthetic.invalid','-keyout',str(scratch/'key.pem'),'-out',str(scratch/'cert.pem')],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=remaining(10))
            ok=result.returncode==0
        elif op=='nginx':
            config=synthetic_nginx(scratch,ports);configfile=scratch/'nginx.conf'
            configfile.write_text(config,encoding='utf-8')
            result=subprocess.run([str(nginx),'-e','stderr','-p',str(scratch)+'/', '-c',str(configfile),'-t'],
                                  capture_output=True,timeout=remaining(10))
            if result.returncode:return {'ok':False,'facts':{'native_parse_returncode':result.returncode}}
            receipt.update(synthetic_fixture_sha256=NGINX_FIXTURE_SHA,QA_projection_sha256=sha(configfile),
                           synthetic_nginx_parse_performed=True)
            sockets['http'].close();sockets['https'].close()
            handle=open(scratch/'nginx.log','wb');handles.append(handle)
            child=subprocess.Popen([str(nginx),'-e','stderr','-p',str(scratch)+'/', '-c',str(configfile)],
                                   stdout=handle,stderr=handle,start_new_session=True)
            children.append(child);state['nginx_child']=child
            ready(child,ports['http']);ready(child,ports['https']);ok=True
        elif op=='native-token-distinction':
            key=ctx['native_cookie']
            values=[ctx['sessions'][name][key] for name in ('http.admin','http.independent','native.fstech')]
            ok=len(set(values))==3
            facts={'distinct_exact_native_sessions':len(set(values))}
        elif op=='expired-fixtures':
            store=state['store'];runtime=state['runtime']
            token=ctx['sessions']['reg.primary'][ctx['registered_cookie']]
            session=store.session(token);state['registered_uid']=session['user_id']
            state['registered_epoch_before_revoke']=session['epoch']
            expired,_=store.new_session(uid=session['user_id'])
            with store.transaction() as connection:
                connection.execute('UPDATE sessions SET expires=? WHERE token_hash=?',
                                   (store.now()-60,runtime.core.digest(expired)))
            ctx['sessions']['expired-registered']={ctx['registered_cookie']:expired};ok=True
        elif op=='registered-session-distinction':
            key=ctx['registered_cookie']
            values=[ctx['sessions'][name][key] for name in ('reg.primary','reg.logout','reg.multi')]
            ok=len(set(values))==3
            facts={'distinct_exact_registered_sessions':len(set(values))}
        elif op=='db-hide':
            state['before_db_loss']=storage_hashes();db.rename(moved);ok=not db.exists() and moved.is_file()
        elif op=='db-not-recreated':ok=not db.exists() and moved.is_file()
        elif op=='db-restore':
            if moved.exists():
                if db.exists():raise ValueError('unexpected synthetic DB recreation; refusing overwrite')
                moved.rename(db)
            ok=state.get('before_db_loss')==storage_hashes()
            facts={'database_and_witness_unchanged':ok}
        elif op=='account-revoke-epoch':
            store=state['store'];uid=state['registered_uid']
            with store.connection() as connection:
                user=connection.execute('SELECT epoch,state FROM users WHERE id=?',(uid,)).fetchone()
                count=connection.execute('SELECT COUNT(*) FROM sessions WHERE user_id=?',(uid,)).fetchone()[0]
            ok=user['state']=='revoked' and user['epoch']==state['registered_epoch_before_revoke']+1 and count==0
            facts={'epoch_advanced_once':user['epoch']==state['registered_epoch_before_revoke']+1,
                   'registered_sessions_remaining':count}
        elif op=='recovery-start':
            stop(state['portal_child']);state['recovery_before']=storage_hashes()
            child=start('recovery');state['recovery_child']=child;ready(child,ports['portal']);ok=True
            receipt['recovery_retained_before']={'db_sha256':state['recovery_before'][0],'witness_sha256':state['recovery_before'][1]}
        elif op=='recovery-retention':
            current=storage_hashes();ok=current==state['recovery_before']
            receipt['recovery_retained_after']={'db_sha256':current[0],'witness_sha256':current[1]}
        elif op=='upstream-stop':
            return stop_upstream_listener(state['recovery_child'],sockets['portal'],ports['portal'],
                                          children,stop,deadline)
        elif op=='old-fc-db-absent':ok=not (scratch/'never-create-old-FC.sqlite3').exists()
        elif op=='worker-versions':
            workers=[json.loads(path.read_text(encoding='utf-8').splitlines()[0]) for path in worker_logs]
            kinds=[r.get('worker') for r in workers]
            ok=(len(workers)==6 and kinds==['portal','portal','portal','fc','board','recovery']
                and all(r.get('python')=='3.9.18' and r.get('sqlite')=='3.53.4' for r in workers))
            receipt['actual_worker_receipts']=workers;facts={'actual_python_workers':len(workers)}
        elif op=='source-post':
            # Shared total Git budget, leaving time to emit a failure receipt
            # inside the workflow's 15-second post-TERM kill grace.
            receipt['source_pre_post_unchanged']=False
            receipt['source_modified']=None
            verified=verify_inputs(root,deadline=time.monotonic()+5.0);ok=verified==release
            receipt['source_pre_post_unchanged']=ok;receipt['source_modified']=not ok
            receipt['source_post_sha256']=verified['verified_file_sha256']
        elif op=='owned-cleanup':
            ok=reap_owned(children)
            for handle in handles:handle.close()
            for sock in sockets.values():sock.close()
            receipt['all_owned_children_reaped']=ok
            receipt['child_returncodes']=[child.returncode for child in children]
        elif op=='temp-cleanup':
            tmp.cleanup();ok=not scratch.exists();receipt['synthetic_temp_cleaned']=ok
        else:raise ValueError('unrecognized local contract action')
        return {'ok':bool(ok),'facts':facts}

    actions={row['operation']:action for row in CONTRACT_PLAN if row['operation']!='http'}
    runner=ContractRunner(transport,actions,ctx,deadline)
    old_handlers={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM)}
    def terminated(signum,frame):raise ControllerTermination('owned controller deadline/termination')
    for sig in old_handlers:signal.signal(sig,terminated)
    signal.alarm(120)
    try:
        runner.execute()
    except BaseException as exc:
        receipt['controller_error_type']=type(exc).__name__
    finally:
        signal.alarm(0)
        for sig in old_handlers:signal.signal(sig,signal.SIG_IGN)
        # Reap owned processes before potentially slow source verification.
        runner.perform(next(row for row in CONTRACT_PLAN if row['id']=='owned-cleanup'))
        # Restore only the owned synthetic fixture after its workers are stopped.
        if moved.exists() and not db.exists():
            try:moved.rename(db)
            except OSError:receipt['synthetic_db_restore_failed']=True
        for name in ('source-post','temp-cleanup'):
            row=next(row for row in CONTRACT_PLAN if row['id']==name)
            runner.perform(row)
        runner.finish_unrecorded('controller terminated before scheduled case')
        for sig,handler in old_handlers.items():signal.signal(sig,handler)
    receipt['checks']=runner.results
    receipt['summary']={key:sum(row['outcome']==key for row in runner.results) for key in ('PASS','FAIL','BLOCKED','NOT_RUN')}
    receipt['summary']['total']=len(runner.results)
    receipt['status']='PASS' if (len(runner.results)==len(CONTRACT_PLAN)
        and all(row['outcome']=='PASS' for row in runner.results) and 'controller_error_type' not in receipt) else 'FAIL'
    output.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':receipt['status'],'summary':receipt['summary'],'receipt':str(output),
                      'production_write':False,'43plus4_rerun':False,'production_ready':False}))
    return 0 if receipt['status']=='PASS' else 1


if __name__=='__main__':
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
    if args.driver_check:sys.exit(driver_check())
    elif args.worker:
        if args.source_root is None or args.fd is None:parser.error('worker requires source-root and an owned fd')
        verify_inputs(args.source_root)
        worker(args.source_root,args.worker,args.fd)
    else:
        driver_check()
        sys.exit(run(args))
