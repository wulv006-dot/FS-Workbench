"""One resumable closeout entry. Native tools and the existing publisher execute actions."""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / '.agent_runtime/knowledge-closeout/ledger.sqlite3'
STEPS = ('git_version', 'server_publish', 'load_readback', 'notion_sync')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def plan(root, base, paths=None):
    root = Path(root)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    discover = paths is None
    if discover:
        tracked = subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z', base], cwd=root).decode().split('\0')
        new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
        paths = sorted(set(tracked + new) - {''})
    catalog_raw = (root / 'knowledge/index.json').read_bytes().replace(b'\r\n', b'\n')
    index = json.loads(catalog_raw)
    files = {}
    affected = set()
    if 'knowledge/index.json' in paths:
        old = {}
        if discover:
            prior = subprocess.run(['git', 'show', base + ':knowledge/index.json'], cwd=root, capture_output=True)
            if prior.returncode == 0:
                old = {(r['id'],r['revision']):r for r in json.loads(prior.stdout)['entries']}
            elif not any(x in prior.stderr.decode(errors='replace') for x in ('does not exist in', 'exists on disk, but not in')):
                raise ValueError('closeout_base_index_unreadable')
        for row in index['entries']:
            if old.get((row['id'],row['revision'])) != row:
                affected.add(row['id'])
        current={(r['id'],r['revision']) for r in index['entries']}
        affected.update(key[0] for key in old if key not in current)
    for name in paths:
        path = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink():
            raise ValueError('closeout_path_boundary')
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        for row in index['entries']:
            if name == row['source']['path']:
                affected.add(row['id'])
    rule_paths = {
        'releases/fs-dashboard/channel-effects-20261021/source/channel_mapping.json',
        'releases/fs-dashboard/channel-effects-20261021/source/channel_source.py',
        'releases/fs-dashboard/fs-business-baseline-20261021/source/coupon_channels.json',
    }
    unmapped_rule_paths = sorted((set(files) & rule_paths) - {row['source']['path'] for row in index['entries']})
    native_prefix = 'releases/fs-dashboard/hermes-server-unify-20261022/'
    native_runtime = any(x.startswith(native_prefix + 'fs_readonly/') or x in
                         {native_prefix + 'fs_native_entry.py', native_prefix + 'patch_factory.py', native_prefix + 'Dockerfile.native',
                          'releases/fs-dashboard/knowledge-layering-20261023/deploy/native_release.py'} for x in files)
    runtime = native_runtime or any(x.startswith('releases/') and Path(x).name in
                  ('business_context.py','controller.py','knowledge_catalog.py','learning_registry.py','learning_service.py','report_method.py') for x in files)
    relevant = runtime or bool(affected) or any(x.startswith(('knowledge/', 'docs/planning/knowledge-layering-20261023/', 'tools/knowledge_closeout')) for x in files)
    business = any(row['id'] in affected and row['layer'] == 'current' for row in index['entries'])
    delivery = runtime or business or 'knowledge/index.json' in files
    steps = ['git_version'] if relevant else []
    if delivery:
        steps += ['server_publish', 'load_readback']
    if relevant:
        steps += ['notion_sync']
    known_conflicts = [r['id'] for r in index['entries'] if r['status'] == 'conflict']
    result = dict(contract='fs-knowledge-closeout-v1', base=base, head=head, files=files,
                  affected_ids=sorted(affected), catalog_sha256=hashlib.sha256(catalog_raw).hexdigest(),
                  unmapped_rule_paths=unmapped_rule_paths, semantic_review_required=bool(unmapped_rule_paths),
                  known_conflicts=known_conflicts, blocking_conflicts=sorted(set(known_conflicts) & affected),
                  business_rule_confirmation_required=business, production_confirmation_required=delivery,
                  steps=steps, requires_restart=runtime,
                  restart_scope='native_hermes_only_after_approval' if native_runtime else 'existing_scope' if runtime else 'none',
                  notion_pages=['3fc9a8a79c4e81578ed1c5fa218837ea', '3ff9a8a79c4e81bc8a4feb15aab87a5a'],
                  rollback='沿既有publisher原发布ID和前值回滚；保留DB/原任务/账本。Notion只按本变更标识修订自己管理的摘要。',
                  extra_authorities=[], maintenance='老D原凌晨任务不变，使用同一change_id去重；不覆盖人工正文。')
    result['change_id'] = 'KL-' + digest(result)[:24]
    result['notion_candidate'] = dict(change_id=result['change_id'], status='candidate_not_effective',
                                    affected_ids=result['affected_ids'], source_commit=head,
                                    summary='按实际变更/来源/版本、验证、未验证及下一步更新；不得把候选或Git合并写为生产完成。',
                                    known_conflicts=known_conflicts)
    result['plan_sha256'] = digest(result)
    return result


def verify_workspace(db, change_id, root):
    value = json.loads(db.execute('SELECT plan FROM runs WHERE id=?', (change_id,)).fetchone()[0])
    for name, expected in value['files'].items():
        path = Path(root) / name
        if path.is_symlink() or (hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None) != expected:
            raise ValueError('closeout_scope_changed:' + name)
    current = hashlib.sha256((Path(root) / 'knowledge/index.json').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    if current != value['catalog_sha256']:
        raise ValueError('closeout_catalog_changed')


def connect(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,plan TEXT NOT NULL,approval TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS steps(run TEXT,name TEXT,state TEXT NOT NULL,operation_id TEXT NOT NULL,receipt TEXT,PRIMARY KEY(run,name))')
    return db


def register(db, value):
    if digest({k: v for k, v in value.items() if k != 'plan_sha256'}) != value['plan_sha256']:
        raise ValueError('closeout_plan_changed')
    old = db.execute('SELECT plan FROM runs WHERE id=?', (value['change_id'],)).fetchone()
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
    if old and old[0] != encoded:
        raise ValueError('closeout_id_conflict')
    with db:
        db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,NULL)', (value['change_id'], encoded))
        for step in value['steps']:
            db.execute('INSERT OR IGNORE INTO steps VALUES(?,?,\'pending\',?,NULL)', (value['change_id'], step, value['change_id'] + ':' + step))
    return value['change_id']


def approve(db, change_id, approval):
    """The calling Codex must establish direct human authorization; files do not grant it."""
    value = json.loads(db.execute('SELECT plan FROM runs WHERE id=?', (change_id,)).fetchone()[0])
    if approval.get('plan_sha256') != value['plan_sha256'] or approval.get('source') != 'direct_user' or not approval.get('message_reference'):
        raise PermissionError('direct_exact_scope_approval_required')
    if value.get('blocking_conflicts'):
        raise ValueError('resolve_affected_knowledge_conflict_before_approval')
    if set(approval.get('actions', [])) - set(value['steps']) or approval.get('extra_authorities'):
        raise PermissionError('approval_scope_expansion')
    current = db.execute('SELECT approval FROM runs WHERE id=?', (change_id,)).fetchone()[0]
    text = json.dumps(approval, sort_keys=True, ensure_ascii=False)
    if current and current != text:
        raise PermissionError('approval_changed_reconcile_scope')
    with db:
        db.execute('UPDATE runs SET approval=? WHERE id=?', (text, change_id))


def next_step(db, change_id):
    row = db.execute('SELECT plan,approval FROM runs WHERE id=?', (change_id,)).fetchone()
    value = json.loads(row[0])
    approval = json.loads(row[1]) if row[1] else None
    for name in value['steps']:
        step = dict(db.execute('SELECT * FROM steps WHERE run=? AND name=?', (change_id, name)).fetchone())
        if step['state'] == 'completed':
            continue
        if step['state'] in ('inflight', 'unknown', 'denied', 'failed'):
            return dict(step, next_action='reconcile_original_operation', mutation_allowed=False)
        if not approval or name not in approval['actions']:
            return dict(step, next_action='await_scope_confirmation', mutation_allowed=False)
        return dict(step, next_action='execute_existing_tool_then_readback', mutation_allowed=True,
                    plan_sha256=value['plan_sha256'], catalog_sha256=value['catalog_sha256'])
    return {'state': 'completed', 'change_id': change_id, 'mutation_allowed': False}


def begin(db, change_id, name):
    step = next_step(db, change_id)
    if step.get('name') != name or not step['mutation_allowed']:
        raise PermissionError('closeout_not_admitted')
    with db:
        n = db.execute("UPDATE steps SET state='inflight' WHERE run=? AND name=? AND state IN ('pending','retryable')", (change_id, name)).rowcount
        if n != 1:
            raise ValueError('closeout_concurrent_attempt')
    return step['operation_id']


def notion_candidate(original, summary, change_id):
    start, end = '## 知识同步｜' + change_id, '变更记录结束：' + change_id
    block = start + '\n\n' + summary.strip() + '\n\n' + end
    if start in original or end in original:
        if original.count(start) != 1 or original.count(end) != 1 or block not in original:
            raise ValueError('notion_managed_block_conflict')
        return {'changed': False, 'content': original}
    return {'changed': True, 'content': block + '\n\n' + original}


def record(db, change_id, name, receipt):
    old = db.execute('SELECT * FROM steps WHERE run=? AND name=?', (change_id, name)).fetchone()
    if old is None or receipt.get('operation_id') != old['operation_id']:
        raise ValueError('original_operation_required')
    status = receipt.get('status')
    if status not in ('completed', 'retryable', 'unknown', 'denied', 'failed'):
        raise ValueError('closeout_receipt_status')
    if status == 'completed' and not (receipt.get('readback') and receipt.get('evidence') and receipt.get('scope_verified') is True):
        raise ValueError('closeout_readback_required')
    if status == 'retryable' and receipt.get('no_write_proven') is not True:
        raise ValueError('closeout_unknown_cannot_retry')
    encoded = json.dumps(receipt, sort_keys=True, ensure_ascii=False)
    if old['state'] == 'completed':
        if old['receipt'] != encoded:
            raise ValueError('closeout_completed_receipt_conflict')
        return
    if old['state'] not in ('inflight', 'unknown', 'denied', 'failed'):
        raise ValueError('closeout_receipt_without_original_attempt')
    with db:
        db.execute('UPDATE steps SET state=?,receipt=? WHERE run=? AND name=?', (status, encoded, change_id, name))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['plan', 'approve', 'next', 'begin', 'record'])
    p.add_argument('--base')
    p.add_argument('--change-id')
    p.add_argument('--step', choices=STEPS)
    p.add_argument('--file')
    p.add_argument('--ledger', type=Path, default=DB)
    a = p.parse_args()
    with connect(a.ledger) as db:
        if a.action == 'plan':
            base = a.base or subprocess.check_output(['git', 'merge-base', 'HEAD', 'origin/main'], cwd=ROOT, text=True).strip()
            result = plan(ROOT, base)
            source = ROOT / 'releases/fs-dashboard/knowledge-layering-20261023/source'
            sys.path.insert(0, str(source))
            from knowledge_catalog import select
            index = json.loads((ROOT / 'knowledge/index.json').read_text(encoding='utf-8'))
            effective_ids = [r['id'] for r in index['entries'] if r['layer']=='current' and r['status']=='effective']
            check = select(ROOT, 'knowledge/index.json', result['catalog_sha256'], ['FS', 'FC27', 'reporting', 'marketing'], effective_ids, preview=True)
            if check['status'] != 'available_preview':
                raise ValueError('closeout_knowledge_conflict:' + str(check))
            subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s',
                            'releases/fs-dashboard/knowledge-layering-20261023/tests', '-v'], cwd=ROOT, check=True)
            register(db, result)
        elif a.action == 'approve':
            approve(db, a.change_id, json.loads(Path(a.file).read_text(encoding='utf-8')))
            result = next_step(db, a.change_id)
        elif a.action == 'begin':
            verify_workspace(db, a.change_id, ROOT)
            result = {'operation_id': begin(db, a.change_id, a.step)}
        elif a.action == 'record':
            record(db, a.change_id, a.step, json.loads(Path(a.file).read_text(encoding='utf-8')))
            result = next_step(db, a.change_id)
        else:
            result = next_step(db, a.change_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
