"""Exact learning scope; reuse the installed publisher's CAS, journal, fence and rollback."""
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat

HERE = Path(__file__).resolve().parent
SCOPE = 'hermes-learning-closure-20261023'
RELEASE = 'hermes-learning-closure-20261023-1'
PREFIX = '/var/lib/fs-hermes-fc/fs/knowledge-releases/' + RELEASE + '/'
RUNTIME = {'runtime/' + name: '/opt/fs-hermes-fc/' + name for name in
           ('knowledge_catalog.py', 'business_context.py', 'controller.py',
            'conversation_service.py', 'business-baseline.md', 'reviewed_skills.py')}
RUNTIME.update({'approval/' + name: '/opt/fs-hermes-memory-approval/' + name
                for name in ('review_queue.py', 'reviewed_skills.py')})
RUNTIME['daily/daily_review.py'] = '/var/lib/fs-hermes-fc/profile/scripts/hermes-memory-review/daily_review.py'
NEW_RUNTIME = {'runtime/reviewed_skills.py', 'approval/reviewed_skills.py'}


def targets(manifest):
    rows = manifest.get('files', [])
    result = {row['candidate']: row['target'] for row in rows}
    if len(rows) != len(result) or not RUNTIME.items() <= result.items():
        raise ValueError('learning_exact_runtime_targets')
    if len(set(result.values())) != len(result):
        raise ValueError('learning_duplicate_targets')
    for name, target in result.items():
        if name in RUNTIME:
            continue
        if (not name.startswith('artifact/') or PurePosixPath(name).as_posix() != name
                or '..' in PurePosixPath(name).parts or '\\' in name
                or target != PREFIX + name[len('artifact/'):]):
            raise ValueError('learning_immutable_release_boundary')
    if result.get('artifact/index.json') != PREFIX + 'index.json':
        raise ValueError('learning_release_index_required')
    if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
        raise ValueError('learning_no_business_or_schedule_writes')
    return result


def load_base():
    raw = (HERE / 'release_adapter_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != '65794d515f78826e5a23c4c88966c603e1a46dd3c977c3dd0956bc770a581344':
        raise ValueError('existing_adapter_drift')
    spec = importlib.util.spec_from_file_location('existing_learning_scope', HERE / 'release_adapter_base.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    manifest = json.loads((HERE / 'approved-manifest.json').read_text(encoding='utf-8'))
    adapter.HERE, adapter.SCOPE, adapter.TARGETS = HERE, SCOPE, targets(manifest)
    adapter.NEW = frozenset(set(adapter.TARGETS) - set(RUNTIME) | NEW_RUNTIME)
    base = adapter.load_base()
    original_group = base.approved_daily_group

    def existing_shared_parent(value, root, item, info):
        return original_group(value, root, item, info) or (
            value.get('scope') == SCOPE and item == base.rooted(root, '/var/lib/fs-hermes-fc')
            and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 9876, 0o750))

    base.approved_daily_group = existing_shared_parent
    restart = base.restart_for

    def restart_changed_code(value, admission_fence=None):
        if not any(row['candidate'].startswith('runtime/') and row['sha256'] != row['beforeSha256']
                   for row in value['files']):
            return
        if admission_fence is None:
            raise ValueError('learning_existing_admission_fence_required')
        admission_fence.stop_then_unlock_database()
        restart(dict(value, scope=base.HERMES_WORKER_SCOPE), admission_fence)
        restart(dict(value, scope=base.DEEP_SCOPE), admission_fence)

    base.restart_for = restart_changed_code
    return base


if __name__ == '__main__':
    load_base().main()
