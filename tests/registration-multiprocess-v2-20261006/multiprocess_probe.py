"""Separate Linux-only synthetic QA; candidate sources stay byte-for-byte frozen."""
import sys
sys.dont_write_bytecode = True

from contextlib import contextmanager
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

COMMIT = 'd9dd533008fe298946eadd9e4bfea3a294aec111'
TREE = 'd30ccde1e6551cd8ef6228a55d6629b7d603b84f'
SUBTREE = '790c5ec62472c12950e6652c5b3c4760a36df7f2'
MANIFEST_SHA = 'c1c545b142cb8c5e838f71d0dcd6dbb43507f4b0f6487fcf0ecdf69ff093aa95'
MANIFEST = Path(__file__).resolve().with_name('runtime-test-manifest.json')
PREFIX = 'registration_approval_runtime_v3_20261006/'
MODULES = {name: 'vendor/' + name + '.py' for name in (
    'auth_candidate', 'native_integration', 'native_access_policy',
    'native_portal_functions', 'native_taskboard_member', 'schema_contract')}
MODULES.update(runtime='runtime.py', process_probe='process_probe.py',
               storage_checkpoint='storage_checkpoint.py')
PHASES = ('prepare', 'hold-1', 'hold-2', 'contend-blocked', 'contend-release',
          'register-a', 'register-b')


def no_links(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('QA input/path link rejected')


def git_tree(files):
    node = {}
    for name, data in files.items():
        current = node
        parts = name.split('/')
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).digest()

    def digest(directory):
        items = sorted(directory.items(), key=lambda item: (item[0] + ('/' if isinstance(item[1], dict) else '')).encode())
        raw = b''.join((b'40000' if isinstance(value, dict) else b'100644') + b' ' + name.encode() + b'\0' +
                       (digest(value) if isinstance(value, dict) else value) for name, value in items)
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).digest()
    return digest(node).hex()


def verify_package(package):
    base = Path(package)
    if not base.is_absolute():
        raise ValueError('absolute independent QA stage required')
    no_links(base)
    base = base.resolve(strict=True)
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA:
        raise ValueError('pinned32 manifest mismatch')
    manifest = json.loads(raw)
    files = {}
    for row in manifest['payloads']:
        name = row['path']
        if not name.startswith(PREFIX) or row['mode'] != '100644':
            raise ValueError('unexpected manifest path/mode')
        relative = name[len(PREFIX):]
        if relative in files or not relative or any(part in ('', '.', '..') for part in relative.split('/')):
            raise ValueError('invalid/duplicate manifest path')
        path = base / relative
        no_links(path)
        data = path.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('candidate payload mismatch: ' + relative)
        files[relative] = data
    actual = set()
    for path in base.rglob('*'):
        no_links(path)
        if path.name == '__pycache__':
            raise ValueError('source bytecode cache rejected')
        if path.is_file():
            actual.add(path.relative_to(base).as_posix())
    if manifest['payload_count'] != 32 or len(files) != 32 or actual != set(files):
        raise ValueError('stage must contain exactly the pinned32 files; no cache/metadata/extras')
    if git_tree(files) != SUBTREE:
        raise ValueError('candidate source subtree mismatch')
    return {'commit': COMMIT, 'tree': TREE, 'source_subtree': SUBTREE,
            'package': str(base), 'manifest_sha256': MANIFEST_SHA, 'payloads': 32,
            'subtree_recomputed': True,
            'commit_tree_provenance': 'pinned prior immutable remote readback; no live Git/network query'}


def module_origins(base):
    result = {}
    for name, relative in MODULES.items():
        module = sys.modules.get(name)
        path = Path(getattr(module, '__file__', '')).resolve()
        if module is None or path != (base / relative).resolve():
            raise ValueError('candidate module origin mismatch: ' + name)
        result[name] = str(path)
    return result


def bound_modules(package):
    binding = verify_package(package)
    if any(name in sys.modules for name in MODULES):
        raise ValueError('preloaded candidate modules rejected; fresh process required')
    base = Path(binding['package'])
    sys.path.insert(0, str(base))
    runtime = importlib.import_module('runtime')
    probe = importlib.import_module('process_probe')
    origins = module_origins(base)
    return runtime, probe, dict(binding, module_origins=origins)


def synthetic_root(directory):
    root = Path(directory)
    no_links(root)
    root = root.resolve(strict=True)
    if Path(tempfile.gettempdir()).resolve() not in root.parents or not root.name.startswith('fs-registration-'):
        raise ValueError('dedicated synthetic temp required')
    return root


def await_file(path, child=None, timeout=10):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if path.exists():
            return
        if child is not None and child.poll() is not None:
            raise AssertionError('own worker exited before handshake')
        time.sleep(0.025)  # bounded handshake polling, never concurrency evidence
    raise AssertionError('synthetic child handshake timed out')


def child_environment():
    env = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONOPTIMIZE'):
        env.pop(name, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


class Children:
    def __init__(self):
        self.items = []

    def start(self, phase, package, root):
        args = [sys.executable, '-B', str(Path(__file__).resolve()), 'worker', phase, str(package), str(root)]
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, env=child_environment())
        self.items.append((phase, child))  # register before any second launch/wait
        return child

    def finish(self, child, expected, timeout=20):
        out, err = child.communicate(timeout=timeout)
        if child.returncode != 0 or out.strip() != expected:
            raise AssertionError('own worker exit/output mismatch')

    def cleanup(self):
        results, errors = [], []
        for phase, child in self.items:
            try:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()  # ONLY this registered synthetic Popen object
                    child.communicate(timeout=5)
                if child.poll() is None:
                    raise AssertionError('own child remains live')
                results.append({'phase': phase, 'returncode': child.returncode})
            except Exception as exc:
                errors.append(type(exc).__name__)
        if errors:
            raise AssertionError('own child cleanup failed: ' + ','.join(errors))
        return results


@contextmanager
def observe_real_lock(root):
    import fcntl  # Linux-only worker; the original Namespace.fence still runs
    original = fcntl.flock
    announced = False

    def observed(fd, operation):
        nonlocal announced
        if operation == fcntl.LOCK_EX and not announced:
            lock = root / 'registration-approval' / 'namespace.lock'
            fst, pst = os.fstat(fd), lock.stat()
            if (fst.st_dev, fst.st_ino) != (pst.st_dev, pst.st_ino):
                raise AssertionError('unexpected real fence fd')
            try:
                original(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                announced = True
                (root / 'contender-attempt').write_text('kernel-blocked')
            else:
                original(fd, fcntl.LOCK_UN)
                raise AssertionError('holder did not exclude real lock attempt')
        return original(fd, operation)  # actual blocking acquire/unlock, no fake lock

    fcntl.flock = observed
    try:
        yield
    finally:
        fcntl.flock = original


def worker(phase, package, directory):
    if os.name != 'posix' or sys.platform != 'linux' or not __debug__:
        raise ValueError('Linux non-optimized QA interpreter required')
    if phase not in PHASES:
        raise ValueError('unknown synthetic phase')
    root = synthetic_root(directory)
    runtime, probe, binding = bound_modules(package)
    binding.update(python=sys.version.split()[0], executable=sys.executable,
                   sqlite_version=runtime.sqlite3.sqlite_version,
                   bytecode_disabled=sys.dont_write_bytecode)
    (root / (phase + '-provenance.json')).write_text(json.dumps(binding))
    if phase == 'prepare':
        sys.argv = [str(Path(package) / 'process_probe.py'), 'prepare', str(root)]
        probe.main()
        return
    if phase == 'contend-blocked':
        with observe_real_lock(root):
            store = runtime.build(root, probe.portal(root), 'https://synthetic.invalid', isolated=True)[0]
            with store.namespace.fence(), store.connection():
                (root / 'contender-entered').write_text('entered')
        print('ENTERED')
        return
    store = runtime.build(root, probe.portal(root), 'https://synthetic.invalid', isolated=True)[0]
    if phase.startswith('hold-'):
        with store.namespace.fence():
            (root / 'holder-ready').write_text('ready')
            await_file(root / 'release-holder')
        print('RELEASED')
    elif phase == 'contend-release':
        with store.namespace.fence(), store.connection():
            (root / 'contender-entered').write_text('entered')
        print('ENTERED')
    else:
        (root / (phase + '-ready')).write_text('ready')
        await_file(root / 'start-race')
        try:
            store.register('raceuser', 'Synthetic-password-42', 'QA', 'Read')
            print('REGISTERED')
        except Exception as exc:
            if getattr(exc, 'code', None) == 409:
                print('CONFLICT')
            else:
                raise


def controller(package):
    if not __debug__ or os.name != 'posix' or sys.platform != 'linux':
        raise ValueError('Linux non-optimized QA interpreter required; Windows cannot accept these four')
    binding = verify_package(package)
    evidence = dict(binding, platform=sys.platform, python=sys.version.split()[0],
                    synthetic_only=True, production_write=False, checks=[], status='failed')
    failure = None
    with tempfile.TemporaryDirectory(prefix='fs-registration-multiprocess-') as directory:
        root = Path(directory)
        children = Children()
        try:
            children.finish(children.start('prepare', package, root), 'PREPARED')
            holder = children.start('hold-1', package, root)
            await_file(root / 'holder-ready', holder)
            contender = children.start('contend-blocked', package, root)
            await_file(root / 'contender-attempt', contender)
            assert (root / 'contender-attempt').read_text() == 'kernel-blocked'
            assert contender.poll() is None and not (root / 'contender-entered').exists()
            (root / 'release-holder').write_text('release')
            children.finish(holder, 'RELEASED')
            children.finish(contender, 'ENTERED')
            evidence['checks'].append('cross_process_exclusion_and_release')
            for name in ('holder-ready', 'release-holder', 'contender-entered', 'contender-attempt'):
                (root / name).unlink()
            holder = children.start('hold-2', package, root)
            await_file(root / 'holder-ready', holder)
            assert holder.poll() is None
            holder.terminate()
            holder.communicate(timeout=20)
            assert holder.poll() is not None
            children.finish(children.start('contend-release', package, root), 'ENTERED')
            evidence['checks'].append('crashed_holder_kernel_lock_release')
            first = children.start('register-a', package, root)
            second = children.start('register-b', package, root)
            await_file(root / 'register-a-ready', first)
            await_file(root / 'register-b-ready', second)
            assert first.poll() is None and second.poll() is None
            (root / 'start-race').write_text('start')
            results = sorted((first.communicate(timeout=20)[0].strip(), second.communicate(timeout=20)[0].strip()))
            assert results == ['CONFLICT', 'REGISTERED'] and first.returncode == second.returncode == 0
            evidence['checks'].append('two_process_same_name_single_commit')
            runtime, probe, controller_binding = bound_modules(package)
            evidence['sqlite_version'] = runtime.sqlite3.sqlite_version
            store = runtime.build(root, probe.portal(root), 'https://synthetic.invalid', isolated=True)[0]
            with store.connection() as db:
                assert db.execute("SELECT count(*) FROM users WHERE name_key='raceuser'").fetchone()[0] == 1
            evidence['checks'].append('consistent_checkpoint_after_concurrent_commits')
            evidence['controller_module_provenance'] = controller_binding
            evidence['child_module_provenance'] = [json.loads((root / (phase + '-provenance.json')).read_text()) for phase in PHASES]
            evidence['status'] = 'passed'
        except BaseException as exc:
            failure = exc
            evidence['error_type'] = type(exc).__name__
        finally:
            try:
                evidence['children'] = children.cleanup()
                evidence['source_pre_post_unchanged'] = verify_package(package) == binding
                assert evidence['source_pre_post_unchanged']
            except BaseException as exc:
                failure = failure or exc
                evidence['status'] = 'failed'
                evidence['cleanup_or_input_error_type'] = type(exc).__name__
    print(json.dumps(evidence, indent=2))
    if failure is not None:
        raise RuntimeError('synthetic harness failed; see structured evidence') from failure


if __name__ == '__main__':
    if sys.argv[1] == 'worker':
        worker(*sys.argv[2:5])
    else:
        controller(sys.argv[1])
