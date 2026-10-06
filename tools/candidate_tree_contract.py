"""Exact upload-tree contract; no broad ignored source directories or business execution."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

MANIFEST_PATHS = ('docs/integration/UPLOAD-ALLOWLIST.json', 'docs/provenance/UPLOAD-ALLOWLIST.json')

def _unlinked_stat(path):
    info = path.lstat()
    # Windows junctions and other reparse points need not report S_IFLNK.
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('linked candidate path: ' + str(path))
    return info

def _canonical_path(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('invalid allowlist path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or ':' in value or p.as_posix() != value or value == '.':
        raise ValueError('non-canonical allowlist path')
    if p.parts[0] == '.git':
        raise ValueError('Git metadata must not be uploaded')
    return value

def _regular_source(repo, rel):
    source = repo / rel
    if not source.exists() or not source.resolve().is_relative_to(repo.resolve()):
        raise ValueError('missing or escaped candidate source: ' + rel)
    for p in [source, *source.parents]:
        info = _unlinked_stat(p)
        if p == repo:
            break
        if p == source and not stat.S_ISREG(info.st_mode):
            raise ValueError('non-regular candidate source: ' + rel)
    return source

def validate_tree(repo):
    _unlinked_stat(Path(repo))
    repo = Path(repo).resolve()
    manifests = [json.loads(_regular_source(repo, rel).read_text(encoding='utf-8')) for rel in MANIFEST_PATHS]
    allow = manifests[0]
    if manifests[1] != allow:
        raise ValueError('integration/provenance manifests disagree')
    exclusions = allow.get('manifestSelfExclusions')
    if not isinstance(exclusions, list) or len(exclusions) != 2 or any(not isinstance(x, str) for x in exclusions) or set(exclusions) != set(MANIFEST_PATHS):
        raise ValueError('only the two exact manifest self-exclusions are allowed')
    rows = allow.get('files')
    if not isinstance(rows, list):
        raise ValueError('missing allowlist rows')
    paths = []
    for row in rows:
        rel = _canonical_path(row['path'])
        if rel in MANIFEST_PATHS:
            raise ValueError('self-excluded manifest must not appear in content rows')
        if not re.fullmatch(r'[0-9a-f]{64}', row.get('sha256', '')):
            raise ValueError('invalid source SHA: ' + rel)
        if type(row.get('bytes')) is not int or row['bytes'] < 0:
            raise ValueError('invalid source size: ' + rel)
        if 'gitMode' in row and row['gitMode'] not in ('100644', '100755'):
            raise ValueError('unsupported source mode: ' + rel)
        paths.append(rel)
    if len(set(paths)) != len(paths) or len({x.casefold() for x in paths}) != len(paths):
        raise ValueError('duplicate or case-colliding candidate paths')
    if type(allow.get('contentFiles')) is not int or allow['contentFiles'] != len(rows):
        raise ValueError('content count differs')
    if type(allow.get('contentBytes')) is not int or allow['contentBytes'] != sum(r['bytes'] for r in rows):
        raise ValueError('content byte total differs')
    # Preserve the manifest's recorded order: the accepted first upload used
    # Windows pathlib ordering, which differs from Unicode/POSIX path sorting.
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    if allow.get('contentSetSha256') != digest:
        raise ValueError('content set digest differs')
    expected = set(paths) | set(MANIFEST_PATHS)
    expected_dirs = {parent.as_posix() for rel in expected for parent in PurePosixPath(rel).parents if parent != PurePosixPath('.')}
    actual = set()
    def walk_error(error):
        raise error
    for directory, dirs, filenames in os.walk(repo, followlinks=False, onerror=walk_error):
        at_root = Path(directory) == repo
        # Root .git is local checkout metadata only. Nested .git, caches, venv,
        # testdeps and .checks have no blanket exemption.
        for name in list(dirs):
            child = Path(directory) / name
            _unlinked_stat(child)
            if at_root and name == '.git':
                dirs.remove(name)
                continue
            rel = child.relative_to(repo).as_posix()
            if rel not in expected_dirs:
                raise ValueError('unlisted candidate directory: ' + rel)
        for name in filenames:
            _unlinked_stat(Path(directory) / name)
            if at_root and name == '.git':
                continue
            actual.add((Path(directory) / name).relative_to(repo).as_posix())
    if actual != expected:
        raise ValueError('candidate allowlist differs: ' + str(sorted(actual ^ expected)))
    for row in rows:
        source_bytes(repo, row)
    return rows

def source_bytes(repo, row):
    source = _regular_source(Path(repo), row['path'])
    # Git modes promise the executable bit, not exact POSIX rw/ownership bits.
    # NTFS does not expose an equivalent through stat; report it as unverified.
    if 'gitMode' in row and os.name == 'posix':
        executable = bool(source.stat().st_mode & 0o111)
        if executable != (row['gitMode'] == '100755'):
            raise ValueError('candidate executable mode differs: ' + row['path'])
    b = source.read_bytes()
    if len(b) != row['bytes'] or hashlib.sha256(b).hexdigest() != row['sha256']:
        raise ValueError('candidate changed: ' + row['path'])
    if 'gitBlobSha1' in row and hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest() != row['gitBlobSha1']:
        raise ValueError('candidate Git blob differs: ' + row['path'])
    return b

def decode_unit_result(process, group):
    try:
        obj = json.loads(process.stdout.strip().splitlines()[-1])
        if not isinstance(obj, dict) or type(obj.get('passed')) is not bool:
            raise ValueError('invalid child test result')
    except (ValueError, IndexError, AttributeError, TypeError):
        obj = {'check': group, 'passed': False, 'output': process.stderr}
    obj['returncode'] = process.returncode
    obj['passed'] = obj['passed'] is True and process.returncode == 0
    return obj

def result_exit_code(results):
    return 0 if results and all(r.get('passed') is True and r.get('returncode', 0) == 0 for r in results) else 1
