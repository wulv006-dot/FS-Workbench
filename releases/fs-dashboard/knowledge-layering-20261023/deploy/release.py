"""Scope adapter only: all writes, locks, CAS, backups and rollback use the existing publisher."""
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCOPE = 'knowledge-layering-20261023'
RELEASE = 'knowledge-layering-20261023-1'
RUNTIME = {'runtime/' + n: '/opt/fs-hermes-fc/' + n for n in
           ('business_context.py', 'controller.py', 'knowledge_catalog.py')}
PREFIX = '/var/lib/fs-hermes-fc/fs/knowledge-releases/' + RELEASE + '/'
SHARED_ADMIN_ES = 'fs-fc-admin-es-shared-20261113-r2'


def targets(manifest):
    runtime, prefix = RUNTIME, PREFIX
    if manifest.get('knowledgeOnly') is True:
        commit = manifest.get('sourceCommit', '')
        release = manifest.get('knowledgeRelease', '')
        if (not re.fullmatch('[a-f0-9]{40}', commit) or
                release not in ('fc-reporting-knowledge-20261105-' + commit[:8], SHARED_ADMIN_ES + '-' + commit) or
                manifest.get('scope') != SCOPE or manifest.get('businessWrites') is not False or
                manifest.get('timersChanged') is not False):
            raise ValueError('knowledge_only_identity_or_authority')
        runtime = {'runtime/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'}
        prefix = '/var/lib/fs-hermes-fc/fs/knowledge-releases/' + release + '/'
    result = {r['candidate']: r['target'] for r in manifest['files']}
    if len(result) != len(manifest['files']) or not runtime.items() <= result.items():
        raise ValueError('knowledge_exact_runtime_targets')
    for name, target in result.items():
        if name in runtime:
            continue
        if not name.startswith('artifact/') or '..' in Path(name).parts or '\\' in name or target != prefix + name[len('artifact/'):]:
            raise ValueError('knowledge_immutable_release_boundary')
    if result.get('artifact/index.json') != prefix + 'index.json':
        raise ValueError('knowledge_release_index_required')
    return result


def load_base():
    raw = (HERE / 'release_adapter_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != '65794d515f78826e5a23c4c88966c603e1a46dd3c977c3dd0956bc770a581344':
        raise ValueError('existing_adapter_drift')
    spec = importlib.util.spec_from_file_location('existing_knowledge_scope_adapter', HERE / 'release_adapter_base.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    manifest = json.loads((HERE / 'approved-manifest.json').read_text(encoding='utf-8'))
    mapping = targets(manifest)
    adapter.HERE, adapter.SCOPE, adapter.TARGETS = HERE, SCOPE, mapping
    runtime = {'runtime/knowledge-load-policy.json'} if manifest.get('knowledgeOnly') is True else set(RUNTIME)
    adapter.NEW = frozenset(r['candidate'] for r in manifest['files'] if r['candidate'] not in runtime
                            or r['candidate'] == 'runtime/knowledge_catalog.py' and r['beforeSha256'] is None)
    base = adapter.load_base()
    original_group = base.approved_daily_group

    def existing_shared_parent(value, root, item, info):
        # Reuse the deployed user-analytics parent contract without changing permissions.
        return original_group(value, root, item, info) or (
            value.get('scope') == SCOPE
            and item == base.rooted(root, '/var/lib/fs-hermes-fc')
            and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 9876, 0o750))

    base.approved_daily_group = existing_shared_parent
    restart = base.restart_for

    def restart_changed_code(value, admission_fence=None):
        if not any(r['candidate'] in RUNTIME and r['sha256'] != r['beforeSha256'] for r in value['files']):
            return
        if admission_fence is None:
            raise ValueError('knowledge_existing_admission_fence_required')
        admission_fence.stop_then_unlock_database()
        restart(dict(value, scope=base.HERMES_WORKER_SCOPE), admission_fence)
        restart(dict(value, scope=base.DEEP_SCOPE), admission_fence)

    base.restart_for = restart_changed_code
    if manifest.get('knowledgeOnly') is True:
        base.knowledge_original_fence = base.hermes_admission_fence

        @contextmanager
        def knowledge_fence(value, root):
            # Drain admission entry, not already-admitted ordinary cost readers.
            # PREPARING/native turns remain covered by the original DB and idle checks.
            import fcntl
            path = base.rooted(root, '/var/lib/fs-hermes-fc/fs/reader-entry.lock')
            base.no_target_link(path)
            fd, db = os.open(str(path), os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)), None
            try:
                info, current = os.fstat(fd), path.stat()
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        info.st_uid != os.geteuid() or info.st_mode & 0o077 or
                        (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
                    raise ValueError('unsafe knowledge admission entry')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                database = base.rooted(root, '/var/lib/fs-hermes-fc/fs/tasks.sqlite3')
                base.no_target_link(database)
                db = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=0)
                db.execute('BEGIN IMMEDIATE')
                base.hermes_quiescent(root)
                yield None
            finally:
                try:
                    if db is not None:
                        try:
                            db.rollback()
                        finally:
                            db.close()
                finally:
                    os.close(fd)

        base.hermes_admission_fence = knowledge_fence
    return base


if __name__ == '__main__':
    load_base().main()
