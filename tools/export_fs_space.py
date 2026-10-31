"""Export pinned FS documents for Space; never publish rules or call business services."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote

REPOSITORY = 'https://github.com/wulv006-dot/FS-Workbench'
SECRET = re.compile(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}|https?://[^\s<>]*(?:access_token|token|signature|secret)=[^\s<>]+', re.S | re.I)
EMAIL = re.compile(r'[A-Za-z0-9.!#$%&\x27*+/=?^_\x60{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}')
KEY_PATH = re.compile(r'[^\s\x60\x22\x27<>|]*(?:\.pem\b|[/\\]\.ssh[/\\][^\s\x60\x22\x27<>|]+)', re.I)
ASSIGNMENT = re.compile(r'(?im)\b(password|secret|batoken|authorization|api[_-]?key)\s*[:=]\s*[\x22\x27]?[^\s\x22\x27\x60,;]{20,}')


def redact(text):
    for pattern in (SECRET, EMAIL, KEY_PATH, ASSIGNMENT):
        text = pattern.sub('[敏感信息已脱敏]', text)
    return text


def documents(members, commit, current_paths=()):
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('space_export_commit_required')
    rows = []
    for name, raw in sorted(members):
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            raise ValueError('space_export_path_boundary')
        if path.suffix != '.md' or not (name == 'AGENTS.md' or path.parts[0] in ('docs', 'knowledge')):
            continue
        if len(raw) > 1048576:
            raise ValueError('space_export_document_too_large:' + name)
        original = raw.decode('utf-8-sig').replace('\r\n', '\n')
        content = redact(original)
        rows.append(dict(path=name, url=REPOSITORY + '/blob/' + commit + '/' + quote(name),
                         source_sha256=hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest(),
                         exported_sha256=hashlib.sha256(content.encode()).hexdigest(),
                         redacted=content != original,
                         classification='contains_current_entries' if name in current_paths else 'reference_snapshot',
                         content=content))
    if not rows:
        raise ValueError('space_export_empty')
    return dict(contract='fs-space-documents-v1', source_commit=commit,
                authority='source snapshots; effective rules remain in the published knowledge index',
                documents=rows)


def references(snapshot, snapshot_date):
    entries, sources = [], {}
    for row in snapshot['documents']:
        key = hashlib.sha256(row['path'].encode()).hexdigest()[:16]
        path = 'space-reference/' + key + '.md'
        text = '来源：' + row['url'] + '\n\n> 此为资料快照，日期仅标识归档时点，不作为当前执行规则。敏感信息按导出记录脱敏。\n\n' + row['content']
        raw = text.encode()
        if len(raw) > 1048576:
            raise ValueError('space_reference_too_large:' + path)
        sources[path] = raw
        entries.append(dict(id='fs.reference.' + key,
            revision=snapshot['source_commit'][:12], layer='archive', status='archived', modules=['FS'],
            effective_at=snapshot_date, time_precision='snapshot_date_not_policy_effective_date',
            owner='FS', authority='git', provenance=[row['url'], '固定Git原文的资料快照，按导出工具脱敏'],
            source_commit=snapshot['source_commit'], supersedes=[],
            source=dict(path=path, sha256=hashlib.sha256(raw).hexdigest(), hash_basis='utf8_lf',
                        original_path=row['path'], original_sha256=row['source_sha256'], url=row['url'])))
    return entries, sources


def export(root, output, ref='HEAD'):
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}'], cwd=root, text=True).strip()
    tracked = subprocess.check_output(['git', 'ls-tree', '-r', '-z', '--name-only', commit, '--', 'docs', 'knowledge', 'AGENTS.md'], cwd=root)
    paths = [p.decode() for p in tracked.split(b'\0') if p.endswith(b'.md')]
    members = [(name, subprocess.check_output(['git', 'show', commit + ':' + name], cwd=root)) for name in paths]
    index = json.loads(subprocess.check_output(['git', 'show', commit + ':knowledge/index.json'], cwd=root))
    current = {r['source']['path'] for r in index['entries'] if r['layer'] == 'current' and r['status'] == 'effective'}
    result = documents(members, commit, current)
    result['knowledge_index_sha256'] = hashlib.sha256(json.dumps(index, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    snapshot_date = subprocess.check_output(['git', 'show', '-s', '--format=%cs', commit], cwd=root, text=True).strip()
    entries, sources = references(result, snapshot_date)
    payload = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
    digest = hashlib.sha256(payload).hexdigest()
    catalog = '# FS完整资料与历史索引\n\n固定来源版本：' + commit + '\n\n资料快照不自动成为现行规则。历史原文保留原日期；已脱敏副本不能代替原始业务回执。\n\n'
    catalog += '\n'.join('- [' + r['path'] + '](' + r['url'] + ') — ' + r['classification'] + ('，已脱敏' if r['redacted'] else '') for r in result['documents'])
    files = {'fs-documents.json': payload, 'FS完整资料与历史索引.md': (catalog + '\n').encode(),
             'knowledge-references.json': (json.dumps(entries, ensure_ascii=False, indent=2) + '\n').encode()}
    files.update({'sources/' + name: data for name, data in sources.items()})
    output.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError('space_export_existing_output_changed:' + name)
            continue
        target.write_bytes(data)
    content_sha = hashlib.sha256(json.dumps([result['knowledge_index_sha256'], [(r['path'], r['source_sha256'], r['exported_sha256'], r['classification']) for r in result['documents']]], ensure_ascii=False).encode()).hexdigest()
    return dict(source_commit=commit, content_sha256=content_sha, documents=len(result['documents']),
                redacted=sum(r['redacted'] for r in result['documents']), sha256=digest,
                reference_sources=len(sources), files=[str(output / n) for n in
                    ('fs-documents.json', 'FS完整资料与历史索引.md', 'knowledge-references.json')])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ref', default='HEAD')
    args = parser.parse_args()
    print(json.dumps(export(Path(__file__).resolve().parents[1], args.output, args.ref), ensure_ascii=False))
