"""Prepare reviewed learning archives; external tools execute Git/Notion closeout."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

CONTRACT = 'hermes-review-archive-v1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode())


def approved(row):
    # FS revocation also returns applied=True: the original approve decision is essential.
    result = row.get('result') or {}
    return (row.get('status') == 'completed' and row.get('decision', {}).get('decision') == 'approve'
            and result.get('success') is True and result.get('applied') is True)


def collect():
    """Run via the approved SSH stdin entry; only read original receipts and skill files."""
    sys.path.insert(0, '/opt/fs-hermes-memory-approval')
    import review_queue as queue
    rows = []
    for path in sorted(queue.ROOT.glob('*.json')):
        if not re.fullmatch(r'[a-f0-9]{64}\.json', path.name):
            continue
        raw = path.read_bytes()
        row = json.loads(raw)
        item = dict(receipt=row, receipt_sha256=sha(raw), receipt_bytes_base64=base64.b64encode(raw).decode())
        if approved(row) and row['decision']['id'].startswith('skill:'):
            # A changed installed package cannot substitute for the historic applied version.
            paths = [p['path'] for p in row['result']['packages']]
            code = "from tools import skill_manager_tool as sm\nprint(json.dumps([package(sm._skills_dir(),p,backup=True) for p in DATA['paths']],ensure_ascii=True))"
            try:
                item['packages'] = queue.run(code, dict(paths=paths))
            except Exception as error:
                item['collection_error'] = type(error).__name__
        rows.append(item)
    return dict(contract=CONTRACT, receipts=rows)


def safe_text(value, *, allow_empty=False, references=()):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError('reviewed_text_required')
    # Only exact reviewed operational references can be exported; secrets stay blocked.
    if not isinstance(references, (list, tuple)) or any(not isinstance(x, str) or not re.fullmatch(
            r'(?:/var/lib/|/profile/|/fs-source/|(?:\d{1,3}\.){3}\d{1,3})', x) for x in references):
        raise ValueError('export_reference_kind')
    matches = re.finditer(r'(?i)(-----BEGIN .*PRIVATE KEY|\b(?:gh[pousr]_|sk-)[a-z0-9_-]{16,}|'
                 r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|'
                 r'\b(?:token|password|api[_-]?key)\s*[:=]\s*["\x27]?\S{8,}|'
                 r'\b(?:\d{1,3}\.){3}\d{1,3}\b|/var/lib/|/profile/|/fs-source/)', value)
    if any(match.group() not in references for match in matches):
        raise ValueError('possible_private_material')
    return value

def relative(value):
    path = PurePosixPath(value)
    if (not value or '\\' in value or ':' in value or '\x00' in value or path.is_absolute()
            or any(x in ('', '.', '..') for x in value.split('/'))):
        raise ValueError('archive_path_boundary')
    return path


def render(snapshot, selections):
    """Only explicit reviewed fields leave the private snapshot. Never copy raw candidates."""
    if snapshot.get('contract') != CONTRACT:
        raise ValueError('snapshot_contract')
    rows = {x['receipt']['request_id']: x for x in snapshot['receipts']}
    if len(rows) != len(snapshot['receipts']):
        raise ValueError('duplicate_source_receipt')
    files, ids = {}, []
    for selection in selections:
        key = selection['request_id']
        if not re.fullmatch('[a-f0-9]{64}', key) or key in ids:
            raise ValueError('archive_request_id')
        ids.append(key)
        source = rows[key]
        row = source['receipt']
        original = base64.b64decode(source['receipt_bytes_base64'], validate=True)
        if sha(original) != source['receipt_sha256'] or json.loads(original) != row:
            raise ValueError('source_receipt_bytes_changed')
        decision, result = row['decision'], row.get('result') or {}
        if not approved(row) or key != digest(decision):
            raise ValueError('original_completed_approval_required')
        if (selection.get('receipt_sha256') != source['receipt_sha256']
                or not re.fullmatch('[a-f0-9]{64}', source['receipt_sha256'])):
            raise ValueError('source_receipt_changed')
        candidate = row['candidate']
        if (candidate['sha256'] != decision['expected_sha']
                or digest(candidate['record']) != decision['expected_sha']):
            raise ValueError('original_candidate_changed')
        if selection.get('disposition') not in ('summary_only', 'reusable'):
            raise ValueError('explicit_archive_disposition_required')
        if selection.get('privacy_reviewed') is not True or selection.get('rule_change') is not False:
            raise PermissionError('privacy_review_or_business_authorization_required')
        summary = safe_text(selection['summary'])
        evidence = safe_text(selection['evidence'])
        modules = selection['modules']
        if (not isinstance(modules, list) or not modules
                or any(not isinstance(x, str) or not re.fullmatch('[A-Za-z0-9_.-]{1,64}', x) for x in modules)):
            raise ValueError('archive_modules')
        kind = decision['id'].split(':')[0]
        payload = candidate['record'].get('payload') or {}
        if payload.get('target') == 'user' and selection['disposition'] != 'summary_only':
            raise PermissionError('private_user_profile_summary_only')
        prefix = 'knowledge/reviewed/' + key
        record = dict(contract=CONTRACT, request_id=key, receipt_sha256=source['receipt_sha256'],
                      candidate_id=decision['id'], candidate_sha256=decision['expected_sha'],
                      kind=kind, disposition=selection['disposition'], summary=summary, modules=modules,
                      evidence=evidence, decision='approve', application='completed_applied',
                      formal_rule_change=False, runtime_activation=False)
        if kind == 'experience':
            record['expires_at'] = candidate['record'].get('expires_at')
            record['original_content_sha256'] = candidate['record'].get('content_hash')
        exports = selection.get('reference_exports')
        if exports is not None:
            if (kind != 'skill' or exports.get('source') != 'direct_user'
                    or not exports.get('message_reference') or not isinstance(exports.get('files'), dict)):
                raise PermissionError('explicit_reference_export_approval_required')
            safe_text(exports['message_reference'])
            record['reference_exports'] = exports
        reviewed_files = set()
        if kind == 'skill':
            if selection['disposition'] != 'reusable':
                raise ValueError('approved_skills_require_complete_package')
            packages = source.get('packages', [])
            expected = result['packages']
            if len(packages) != len(expected) or len({p['path'] for p in packages}) != len(packages):
                raise ValueError('complete_skill_packages_required')
            record['packages'] = []
            for pkg in packages:
                relative(pkg['path'])
                manifest = dict(pkg, entries=[{k: v for k, v in e.items() if k != 'bytes_base64'} for e in pkg['entries']])
                if (not any(manifest == p for p in expected)
                        or digest({k: v for k, v in manifest.items() if k != 'sha256'}) != pkg['sha256']):
                    raise ValueError('applied_skill_package_changed')
                copied = []
                for entry in pkg['entries']:
                    if entry['kind'] == 'directory':
                        if entry['path'] != '.':
                            relative(entry['path'])
                        continue
                    if entry['kind'] != 'file':
                        raise ValueError('skill_nonregular_entry')
                    rel = relative(entry['path']).as_posix()
                    raw = base64.b64decode(entry['bytes_base64'], validate=True)
                    if len(raw) != entry['bytes'] or sha(raw) != entry['sha256']:
                        raise ValueError('skill_file_changed')
                    # shortcut: binary skill assets require a separately reviewed export scope.
                    reference = (exports['files'].get(pkg['path'] + '/' + rel) if exports else None)
                    if reference is not None:
                        if reference.get('sha256') != entry['sha256']:
                            raise ValueError('export_reference_file_changed')
                        reviewed_files.add(pkg['path'] + '/' + rel)
                    text = safe_text(raw.decode('utf-8'), allow_empty=True,
                                     references=reference['values'] if reference else ())
                    files[prefix + '/skills/' + pkg['path'] + '/' + rel] = text
                    copied.append(dict(path=rel, sha256=entry['sha256'], mode=entry['mode']))
                if pkg['exists'] and not any(e['path'] == 'SKILL.md' for e in copied):
                    raise ValueError('complete_skill_document_required')
                record['packages'].append(dict(path=pkg['path'], exists=pkg['exists'],
                                               sha256=pkg['sha256'], files=copied))
        elif kind not in ('native', 'experience'):
            raise ValueError('unsupported_learning_kind')
        if kind != 'skill' and selection['disposition'] == 'reusable':
            files[prefix + '/NOTE.md'] = safe_text(selection['content'])
        if exports and reviewed_files != set(exports['files']):
            raise ValueError('export_reference_unused_file')
        files[prefix + '/record.json'] = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    return files


def prepare(root, base, snapshot, selections):
    from knowledge_closeout import plan
    root = Path(root)
    files = render(snapshot, selections)
    changed = []
    # Validate the whole batch before writing any files; never overwrite previous archives.
    for name, content in files.items():
        path = root / name
        if any(p.is_symlink() for p in [path] + list(path.parents)):
            raise ValueError('archive_symlink')
        if path.exists():
            if path.read_bytes() != content.encode():
                raise ValueError('immutable_archive_conflict:' + name)
        else:
            changed.append(name)
    for name in changed:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(files[name].encode())
    value = plan(root, base, sorted(files))
    # Archives are explicitly outside the active catalog and never trigger a runtime publish.
    if value['production_confirmation_required'] or value['steps'] != ['git_version', 'notion_sync']:
        raise ValueError('archive_unexpected_production_scope')
    value['archive_requests'] = sorted(s['request_id'] for s in selections)
    value['archive_only'] = True
    value['plan_sha256'] = digest({k: v for k, v in value.items() if k != 'plan_sha256'})
    return dict(plan=value, changed=changed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('source', 'prepare'))
    parser.add_argument('--snapshot')
    parser.add_argument('--selections')
    parser.add_argument('--base')
    parser.add_argument('--ledger', type=Path)
    args = parser.parse_args()
    if args.action == 'source':
        result = collect()
    else:
        from knowledge_closeout import ROOT, connect, register
        result = prepare(ROOT, args.base, json.loads(Path(args.snapshot).read_text(encoding='utf-8-sig')),
                         json.loads(Path(args.selections).read_text(encoding='utf-8')))
        with closing(connect(args.ledger) if args.ledger else connect()) as db:
            # Resume the original run when the same requests/files were already registered.
            for old in db.execute('SELECT plan FROM runs'):
                previous = json.loads(old['plan'])
                if previous.get('archive_requests') == result['plan']['archive_requests']:
                    if previous['files'] != result['plan']['files']:
                        raise ValueError('archive_scope_changed_reconcile_original')
                    result['plan'] = previous
                    break
            register(db, result['plan'])
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
