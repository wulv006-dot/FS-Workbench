"""Execute only a completely hashed, sealed mapping; never search a live APP dir."""
import hashlib
import importlib.abc
import importlib.util
import re
import sys
import os
import stat
from pathlib import PurePosixPath
from types import MappingProxyType


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class SnapshotFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, sources, origins):
        # bytes and tuples are immutable; compile everything before any exec.
        self.records = MappingProxyType({name: (bytes(raw), origins[name], digest(raw),
            compile(raw, 'verified-memory:' + digest(raw) + '/' + name + '.py', 'exec'))
            for name, raw in sources.items()})

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.records:
            return importlib.util.spec_from_loader(fullname, self,
                origin='verified-memory:' + self.records[fullname][2] + '/' + fullname + '.py')

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raw, origin, sha, code = self.records[module.__name__]
        module.__file__ = 'verified-memory:' + sha + '/' + module.__name__ + '.py'
        module.__verified_origin__ = origin
        module.__verified_sha256__ = sha
        module.__verified_loader__ = 'sealed-memory-v1'
        exec(code, module.__dict__)


def install(sources, expected, origins, allowed_names):
    if set(sources) != set(expected) or set(sources) != set(origins):
        raise ValueError('dependency_closure_incomplete')
    if set(sources) != set(allowed_names):
        raise ValueError('dependency_name_allowlist_changed')
    for name, raw in sources.items():
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('dependency_module_name_invalid')
        if digest(raw) != expected[name]:
            raise ValueError('dependency_hash_changed_before_import')
        if name in sys.modules:
            raise ValueError('dependency_loaded_before_validation')
    finder = SnapshotFinder(sources, origins)
    sys.meta_path.insert(0, finder)
    return finder


def record(module):
    if getattr(module, '__verified_loader__', None) != 'sealed-memory-v1':
        raise ValueError('dependency_not_loaded_from_snapshot')
    return {'path': module.__verified_origin__, 'sha256': module.__verified_sha256__}


def read_verified_sources(scope, include_image_helper=False):
    """No imports: read the entire approved runtime closure before returning it."""
    paths = dict(scope['expected_sources'])
    metadata = scope['source_metadata']
    if include_image_helper:
        helper = scope['proof_provenance']['modules']['p2pah_session_service']
        paths[helper['path']] = helper['sha256']
    out = {};origins = {};expected = {}
    for path, wanted in paths.items():
        parts = PurePosixPath(path).parts
        if not parts or parts[0] != '/' or '..' in parts:
            raise ValueError('runtime_source_path_invalid')
        directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = None
        try:
            for part in parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
                current = os.fstat(child)
                if current.st_uid != 0 or stat.S_IMODE(current.st_mode) & 0o022:
                    os.close(child);raise ValueError('source_parent_untrusted')
                os.close(directory);directory = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != 0 or stat.S_IMODE(before.st_mode) & 0o022):
                raise ValueError('runtime_source_metadata_untrusted')
            if path in metadata:
                bound = metadata[path]
                if (before.st_uid != bound['uid'] or before.st_gid != bound['gid']
                        or stat.S_IMODE(before.st_mode) != int(bound['mode'], 8)
                        or (before.st_dev, before.st_ino) != (bound['device'], bound['inode'])):
                    raise ValueError('runtime_source_binding_changed')
            chunks = [];length = 0
            while True:
                chunk = os.read(fd, 1048576)
                if not chunk:break
                length += len(chunk)
                if length > 32000000:raise ValueError('bounded_source_exceeded')
                chunks.append(chunk)
            raw = b''.join(chunks);after = os.fstat(fd)
            current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
                    or digest(raw) != wanted):
                raise ValueError('runtime_source_changed_before_import')
            name = PurePosixPath(path).stem
            if name in out:raise ValueError('duplicate_runtime_module')
            out[name] = raw;origins[name] = path;expected[name] = wanted
        finally:
            if fd is not None:os.close(fd)
            os.close(directory)
    return out, expected, origins
