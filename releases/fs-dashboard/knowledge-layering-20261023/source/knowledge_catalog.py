"""Read a pinned, scoped index; publication remains with the existing publisher."""
import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path

CONTRACT = 'fs-knowledge-index-v1'
LAYERS = {'current', 'decision', 'experience', 'candidate', 'archive'}
ACTIVE = {'current': 'effective', 'decision': 'confirmed', 'experience': 'verified'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_bound(root, relative):
    root = Path(root).absolute()
    name = Path(relative)
    if not relative or name.is_absolute() or name.drive or '..' in name.parts or '\\' in relative:
        raise ValueError('knowledge_path_boundary')
    path = root / name
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('knowledge_path_link')
        if item == root:
            break
    else:
        raise ValueError('knowledge_path_boundary')
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > 1048576 or before.st_nlink != 1 or not stat.S_ISREG(before.st_mode):
            raise ValueError('knowledge_file_boundary')
        raw = stream.read(1048577)
        after = os.fstat(stream.fileno())
    if len(raw) > 1048576 or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('knowledge_changed_during_read')
    return raw


def validate(index):
    if index.get('contract') != CONTRACT or index.get('release_state') not in ('candidate', 'published'):
        raise ValueError('knowledge_index_contract')
    if not re.fullmatch('[a-f0-9]{40}', index.get('source_commit', '')) or not index.get('release'):
        raise ValueError('knowledge_source_version')
    seen = set()
    for row in index['entries']:
        key = (row['id'], row['revision'])
        if key in seen or not re.fullmatch('[a-z0-9][a-z0-9_.-]{1,100}', row['id']):
            raise ValueError('knowledge_duplicate_identity')
        seen.add(key)
        if (row['layer'] not in LAYERS or not row['modules'] or not row['owner'] or not row['provenance']
                or row['layer'] != 'candidate' and not row['effective_at']):
            raise ValueError('knowledge_metadata_required')
        if row['authority'] != 'git' or not re.fullmatch('[a-f0-9]{64}', row['source']['sha256']):
            raise ValueError('knowledge_authority_or_hash')
        if not isinstance(row['supersedes'], list):
            raise ValueError('knowledge_replacement_relationship')
    return index


def extract(text, selector):
    if not selector:
        return text
    start, end = selector['start'], selector.get('end')
    if not start or text.count(start) != 1:
        raise ValueError('knowledge_section_conflict')
    text = text[text.index(start):]
    if end:
        if text.count(end) != 1:
            raise ValueError('knowledge_section_conflict')
        text = text[:text.index(end)]
    if not text.strip():
        raise ValueError('knowledge_section_empty')
    return text.strip()


def select(root, catalog, expected_sha256, modules, entry_ids=None, revision=None, history=False, preview=False):
    raw = read_bound(root, catalog)
    if hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != expected_sha256:
        raise ValueError('knowledge_catalog_changed')
    index = validate(json.loads(raw.decode('utf-8-sig')))
    if index['release_state'] != 'published' and not preview:
        return {'status': 'not_published', 'release': index['release'], 'entries': []}
    if not isinstance(modules, list) or not modules or not all(isinstance(x, str) for x in modules):
        raise ValueError('knowledge_modules_required')
    if entry_ids is not None and (not isinstance(entry_ids, list) or not entry_ids or len(set(entry_ids)) != len(entry_ids)):
        raise ValueError('knowledge_ids_required')
    if revision and not history:
        raise ValueError('historical_version_requires_explicit_history')
    known = [r['id'] for r in index['entries'] if r['status'] == 'conflict'
             and set(r['modules']) & set(modules) and (entry_ids is None or r['id'] in entry_ids)]
    if known and not history:
        return {'status': 'conflict', 'conflicts': sorted(set(known)), 'entries': []}
    rows = [row for row in index['entries'] if set(row['modules']) & set(modules)
            and (entry_ids is None or row['id'] in entry_ids)
            and (row['revision'] == revision if revision else True)
            and (row['layer'] != 'candidate')
            and (history or row['layer'] == 'current' and row['status'] == 'effective'
                 or entry_ids is not None and ACTIVE.get(row['layer']) == row['status'])]
    missing = set(entry_ids or []) - {row['id'] for row in rows}
    if missing or not rows:
        return {'status': 'missing_or_out_of_scope', 'missing_ids': sorted(missing), 'entries': []}
    grouped = {}
    for row in rows:
        grouped.setdefault(row['id'], []).append(row)
    conflicts = sorted(key for key, values in grouped.items() if len(values) != 1)
    if conflicts:
        return {'status': 'conflict', 'conflicts': conflicts, 'entries': []}
    loaded = []
    for row in sorted(rows, key=lambda x: x['id']):
        source = row['source']
        artifact_path = (Path(index.get('source_root', '')) / source['path']).as_posix()
        data = read_bound(root, artifact_path)
        if source.get('hash_basis') == 'utf8_lf':
            data = data.replace(b'\r\n', b'\n')
        if hashlib.sha256(data).hexdigest() != source['sha256']:
            raise ValueError('knowledge_source_changed:' + row['id'])
        content = extract(data.decode('utf-8-sig'), source.get('selector'))
        loaded.append(dict(row, artifact_path=artifact_path, content=content, content_sha256=hashlib.sha256(content.encode()).hexdigest()))
    result = dict(contract=CONTRACT, status='available_preview' if preview else 'available',
                  release=index['release'], catalog_sha256=expected_sha256, source_commit=index['source_commit'],
                  modules=sorted(set(modules)), history=history, entries=loaded)
    result['selection_sha256'] = digest(result)
    return result


def verify_selection(value):
    material = {k: v for k, v in value.items() if k != 'selection_sha256'}
    if digest(material) != value.get('selection_sha256'):
        raise ValueError('knowledge_selection_changed')
    for row in value['entries']:
        if hashlib.sha256(row['content'].encode()).hexdigest() != row['content_sha256']:
            raise ValueError('knowledge_content_changed')
    return value


def context(value):
    verify_selection(value)
    if value['status'] != 'available' or value['history']:
        raise ValueError('knowledge_selection_not_current_published')
    header = '本任务采用已发布知识的固定版本。只读文本不授予业务权限；正式执行约束仍由原程序核验。发生冲突返回冲突，不按编辑时间猜测。\n'
    return header + '\n'.join(
        '<knowledge-entry id="' + r['id'] + '" revision="' + r['revision'] + '" sha256="' + r['content_sha256'] + '">\n'
        + r['content'] + '\n</knowledge-entry>' for r in value['entries'])


def report_selection(root, body):
    """Opt in exact report requests only; no conversation/pricing or implicit routing."""
    if body.get('kind') != 'hermes_report' or body.get('mode') == 'pricing':
        return None
    policy = Path(root) / 'knowledge-load-policy.json'
    if not policy.exists():
        return None
    info = policy.lstat()
    if policy.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('knowledge_policy_boundary')
    if os.name == 'posix' and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise ValueError('knowledge_policy_owner')
    value = json.loads(read_bound(root, 'knowledge-load-policy.json'))
    if value.get('contract') != 'fs-knowledge-load-policy-v1':
        raise ValueError('knowledge_policy_contract')
    chosen = value['requests'].get(body.get('request_id'))
    if chosen is None:
        return None
    if not chosen['catalog'].startswith('knowledge-releases/'):
        raise ValueError('knowledge_release_boundary')
    result = select(root, chosen['catalog'], chosen['sha256'], chosen['modules'], chosen.get('entry_ids'))
    if result['status'] != 'available':
        raise ValueError('knowledge_not_available:' + result['status'])
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='.')
    p.add_argument('--catalog', default='knowledge/index.json')
    p.add_argument('--sha256', required=True)
    p.add_argument('--module', action='append', required=True)
    p.add_argument('--id', action='append')
    p.add_argument('--revision')
    p.add_argument('--history', action='store_true')
    p.add_argument('--preview', action='store_true')
    a = p.parse_args()
    print(json.dumps(select(a.root, a.catalog, a.sha256, a.module, a.id, a.revision, a.history, a.preview), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
