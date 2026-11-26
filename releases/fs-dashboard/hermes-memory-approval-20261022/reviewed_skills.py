"""Complete package receipts and read-only discovery; no skill application implementation."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

CONTRACT = 'fs-hermes-reviewed-skills-v1'
TARGET_CONTRACT = 'fs-hermes-skill-target-v1'
# Curator owns this package's lifecycle. Keep its approvals for audit only.
HERMES_MANAGED_SKILLS = frozenset({'fs-operations/fs-business-context-rulings'})
PUBLISHED_ROOTS = ('/approved-skills', '/var/lib/fs-hermes-memory-approval/published-skills')
NATIVE_SHA256 = {
    'write_approval': '8d8a15d29a73dceb2e8cf76f613d59d91115314c908a8086ffe1c72572382c7f',
    'skill_manager_tool': '10f5ad4260ab8e56eccaabd3e1563a838903805e02bd9c9ac49c0458766e62fc',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('unsafe_skill_path')
    path = PurePosixPath(value)
    if path.is_absolute() or ':' in value or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('unsafe_skill_path')
    return path


def safe_path(root, value):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('unsafe_skills_root')
    path = root
    for part in relative(value).parts:
        path /= part
        if path.is_symlink():
            raise ValueError('skill_symlink')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('skill_path_escape')
    return path


def package(root, value, *, backup=False):
    path = safe_path(root, value)
    result = dict(path=value, exists=path.exists(), entries=[])
    if result['exists']:
        if not path.is_dir():
            raise ValueError('skill_target_not_directory')
        for entry in [path] + sorted(path.rglob('*')):
            info = entry.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError('skill_nonregular_entry')
            row = dict(path=entry.relative_to(path).as_posix(),
                       kind='directory' if entry.is_dir() else 'file',
                       mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)
            if row['kind'] == 'file':
                raw = entry.read_bytes()
                row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                if backup:
                    row['bytes_base64'] = base64.b64encode(raw).decode()
            result['entries'].append(row)
    manifest = dict(result, entries=[{k: v for k, v in row.items() if k != 'bytes_base64'}
                                     for row in result['entries']])
    result['sha256'] = digest(manifest)
    return result


def operations(payload):
    ops = payload.get('operations') if payload.get('operations') is not None else [payload]
    if not isinstance(ops, list) or not ops:
        raise ValueError('empty_skill_operations')
    default = payload.get('name')
    checked = []
    for raw in ops:
        if not isinstance(raw, dict) or raw.get('action') not in (
                'create', 'edit', 'patch', 'write_file', 'remove_file', 'delete'):
            raise ValueError('unsupported_skill_operation')
        op = dict(raw, name=raw.get('name') or default)
        name = relative(op['name'])
        if len(name.parts) > 2 or any(not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', p)
                                     for p in name.parts):
            raise ValueError('skill_name')
        if op.get('category'):
            category = relative(op['category'])
            if len(category.parts) != 1 or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', str(category)):
                raise ValueError('skill_category')
        if op.get('file_path'):
            relative(op['file_path'])
        checked.append(op)
    return checked


def skill_targets(payload, manager):
    root = Path(manager._skills_dir())
    resolved = {}
    for op in operations(payload):
        name = op['name']
        if op['action'] == 'create':
            target = manager._resolve_skill_dir(name, op.get('category'))
        elif name in resolved:
            continue
        else:
            found = manager._find_skill(name)
            if not found:
                raise ValueError('skill_not_found')
            target = found['path']
        try:
            value = Path(target).relative_to(root).as_posix()
        except ValueError:
            raise ValueError('skill_outside_approved_profile') from None
        safe_path(root, value)
        resolved[name] = value
    return resolved


def target_snapshot(payload, manager, *, backup=False):
    targets = skill_targets(payload, manager)
    root = manager._skills_dir()
    packages = [package(root, value, backup=backup) for value in sorted(set(targets.values()))]
    manifest = dict(contract=TARGET_CONTRACT,
                    packages=[dict(path=p['path'], sha256=p['sha256']) for p in packages])
    return dict(**manifest, sha256=digest(manifest), targets=targets, snapshots=packages)


def checked_native(manager, approval):
    for name, module in (('skill_manager_tool', manager), ('write_approval', approval)):
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != NATIVE_SHA256[name]:
            raise ValueError('installed_skill_contract_changed')


def skill_candidate(record, manager):
    row = dict(id='skill:' + record['id'], record=record, sha256=digest(record))
    try:
        row['target'] = target_snapshot(record['payload'], manager)
        row['target_sha256'] = row['target']['sha256']
    except ValueError as error:
        row['validation_error'] = str(error)
        row['target_sha256'] = digest(dict(blocked=str(error)))
    return row


def review_metadata(value, paths):
    if not isinstance(value, dict) or set(value) != set(paths):
        raise ValueError('review_metadata_for_each_surviving_skill_required')
    for row in value.values():
        if (not isinstance(row, dict) or not isinstance(row.get('description'), str)
                or not 1 <= len(row['description'].strip()) <= 1024
                or not isinstance(row.get('modules'), list) or not row['modules']
                or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', x)
                       for x in row['modules'])):
            raise ValueError('reviewed_skill_scope')
    return value


def apply_review(data, manager, approval):
    """The caller has durably saved the complete backup before this write is reached."""
    key = data['id'].split(':')[1]
    record = approval.get_pending(approval.SKILLS, key)
    if record is None or digest(record) != data['expected_sha']:
        raise ValueError('candidate_changed')
    if data['decision'] == 'reject':
        if not approval.discard_pending(approval.SKILLS, key):
            raise ValueError('pending_discard_failed')
        return dict(success=True, applied=False, rejected=True)
    checked_native(manager, approval)
    ops = operations(record['payload'])
    with manager._skill_mutation_locks([op['name'] for op in ops]):
        before = target_snapshot(record['payload'], manager)
        if before['sha256'] != data['target_sha']:
            raise ValueError('skill_target_changed')
        current = approval.get_pending(approval.SKILLS, key)
        if current is None or digest(current) != data['expected_sha']:
            raise ValueError('candidate_changed')
        deleted = {before['targets'][op['name']] for op in ops if op['action'] == 'delete'}
        surviving = set(before['targets'].values()) - deleted
        metadata = review_metadata(data.get('reviewed_skills'), surviving)
        native_result = json.loads(manager.apply_skill_pending(record['payload']))
        after = [package(manager._skills_dir(), p) for p in sorted(set(before['targets'].values()))]
        after_sha = digest(dict(contract=TARGET_CONTRACT,
                                packages=[dict(path=p['path'], sha256=p['sha256']) for p in after]))
        if not native_result.get('success'):
            if after_sha != before['sha256']:
                raise RuntimeError('native_skill_failure_with_changes_inspect_before_retry')
            return dict(success=False, applied=False, error=native_result.get('error') or
                        native_result.get('message') or 'native_skill_apply_failed', after_sha256=after_sha)
        if any(p['exists'] != (p['path'] not in deleted) for p in after):
            raise RuntimeError('native_skill_readback_mismatch')
        for p in after:
            if p['exists'] and not any(x['path'] == 'SKILL.md' and x['kind'] == 'file'
                                       for x in p['entries']):
                raise RuntimeError('native_skill_readback_missing_skill')
        if not approval.discard_pending(approval.SKILLS, key):
            raise RuntimeError('applied_pending_cleanup_failed_inspect_receipt')
        return dict(success=True, applied=True, after_sha256=after_sha, packages=after,
                    reviewed_skills=metadata, native_result=native_result)


def approved_index(receipts):
    items = {}
    for row in sorted(receipts, key=lambda r: (r.get('completed_at', r.get('created_at', 0)), r['request_id'])):
        if not row.get('decision', {}).get('id', '').startswith('skill:'):
            continue
        result = row.get('result') or {}
        if row.get('status') != 'completed' or not result.get('applied') or not result.get('success'):
            continue
        for pkg in result['packages']:
            path = pkg['path']
            items.pop(path, None)
            if pkg['exists'] and path not in HERMES_MANAGED_SKILLS:
                metadata = result['reviewed_skills'][path]
                items[path] = dict(id=path, sha256=pkg['sha256'], package_sha256=pkg['sha256'],
                                   relative_path=path, files=pkg['entries'],
                                   modules=metadata['modules'], description=metadata['description'],
                                   review_request_id=row['request_id'], candidate_id=row['decision']['id'])
    manifest = dict(contract=CONTRACT, items=[items[p] for p in sorted(items)])
    return dict(manifest, sha256=digest(manifest))


def _catalog(skills_root, index, modules, expected_index_sha):
    if (index.get('contract') != CONTRACT or index.get('sha256') != expected_index_sha
            or digest({k: v for k, v in index.items() if k != 'sha256'}) != index.get('sha256')):
        raise ValueError('reviewed_skill_index_changed')
    items = []
    for row in index['items']:
        # Old frozen indexes may still list the Hermes-managed package.
        if row['id'] in HERMES_MANAGED_SKILLS:
            continue
        if {m.casefold() for m in modules}.intersection(m.casefold() for m in row['modules']):
            current = package(skills_root, row['id'])
            if current['sha256'] != row['sha256'] or current['entries'] != row['files']:
                raise ValueError('reviewed_skill_package_changed')
            items.append(row)
    return dict(contract=CONTRACT, items=items, missing=False, sha256=index['sha256'])


def list_reviewed(skills_root, index_path, modules, *, expected_index_sha):
    """Explicit-version reads bind the publisher's independently pinned expected hash."""
    if not Path(index_path).exists():
        return dict(contract=CONTRACT, items=[], missing=True, sha256=None)
    index = json.loads(Path(index_path).read_text(encoding='utf-8'))
    return _catalog(skills_root, index, modules, expected_index_sha)


def current_catalog(skills_root, published_root, modules):
    """Read the trusted current index once; callers freeze its returned content/hash per task."""
    root = Path(published_root)
    if str(root) not in PUBLISHED_ROOTS:
        raise ValueError('untrusted_reviewed_skill_root')
    if root.is_symlink():
        raise ValueError('untrusted_reviewed_skill_directory')
    if not root.exists():
        return dict(contract=CONTRACT, items=[], missing=True, sha256=None)
    for directory in (root, *root.parents):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            raise ValueError('untrusted_reviewed_skill_directory')
    path = root/'index.json'
    if path.is_symlink():
        raise ValueError('untrusted_reviewed_skill_index')
    if not path.exists():
        return dict(contract=CONTRACT, items=[], missing=True, sha256=None)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError('untrusted_reviewed_skill_index')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                or opened.st_uid != 0 or stat.S_IMODE(opened.st_mode) & 0o022):
            raise ValueError('reviewed_skill_index_changed_during_read')
        index = json.loads(stream.read())
    return _catalog(skills_root, index, modules, index.get('sha256'))


def read_reviewed_skill(skills_root, index_path, modules, skill_id, expected_sha, file_path='SKILL.md',
                        *, expected_index_sha):
    listing = list_reviewed(skills_root, index_path, modules, expected_index_sha=expected_index_sha)
    item = next((r for r in listing['items'] if r['id'] == skill_id and r['sha256'] == expected_sha), None)
    if item is None:
        raise ValueError('reviewed_skill_not_selected')
    path = safe_path(safe_path(skills_root, skill_id), str(relative(file_path)))
    raw = path.read_bytes()
    row = next((r for r in item['files'] if r['path'] == file_path and r['kind'] == 'file'), None)
    if row is None or hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise ValueError('reviewed_skill_file_changed')
    return dict(id=skill_id, package_sha256=expected_sha, path=file_path, sha256=row['sha256'],
                content=raw.decode('utf-8'), review_request_id=item['review_request_id'])
