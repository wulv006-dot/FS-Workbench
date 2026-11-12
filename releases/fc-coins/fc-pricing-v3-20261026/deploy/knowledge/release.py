"""Publish the V3 teaching catalog using the pinned original CAS publisher."""
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import types

HERE = Path(__file__).resolve().parent
SCOPE = 'fc-pricing-v3-knowledge-20261026'
RELEASE_PREFIX = 'fc-three-platform-100k-knowledge-20261110-'
RUNTIME = {'runtime/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md',
           'runtime/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'}
# Exact Git LF normalization of the frozen original publisher (raw CRLF SHA 1d070ee8...).
BASE_SHA = '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'


def release_identity(source_commit):
    if not isinstance(source_commit,str) or not re.fullmatch('[a-f0-9]{40}',source_commit):
        raise ValueError('knowledge_release_identity_invalid')
    release=RELEASE_PREFIX+source_commit
    return release,'/var/lib/fs-hermes-fc/fs/knowledge-releases/'+release+'/'


def targets(manifest):
    release,prefix=release_identity(manifest.get('sourceCommit'))
    if manifest.get('knowledgeRelease')!=release or manifest.get('scope')!=SCOPE:
        raise ValueError('knowledge_release_identity_invalid')
    rows = manifest.get('files', [])
    mapping = {r['candidate']: r['target'] for r in rows}
    if len(mapping) != len(rows) or not RUNTIME.items() <= mapping.items():
        raise ValueError('knowledge_exact_runtime_targets')
    for name, target in mapping.items():
        if name in RUNTIME:
            continue
        if not name.startswith('artifact/') or '..' in Path(name).parts or '\\' in name or \
                target != prefix + name[len('artifact/'):]:
            raise ValueError('knowledge_immutable_release_boundary')
    if mapping.get('artifact/index.json') != prefix + 'index.json':
        raise ValueError('knowledge_release_index_required')
    return mapping


def load_base():
    raw = (HERE / 'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    approved = json.loads((HERE / 'approved-manifest.json').read_text('utf-8'))
    mapping = targets(approved)
    if approved.get('scope') != SCOPE or approved.get('businessWrites') is not False or \
            approved.get('timersChanged') is not False or approved.get('releaseReady') is not True:
        raise ValueError('knowledge_exact_scope_required')
    for row in approved['files']:
        is_new = row['candidate'] not in RUNTIME
        if (row.get('beforeSha256') is None) != is_new or row.get('owner') != '0:0' or \
                row.get('mode') != '0o644':
            raise ValueError('knowledge_exact_existing_new_metadata_required')
    source = raw.decode('utf-8')
    anchor = "r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor) != 1:
        raise ValueError('frozen_new_file_anchor_drift')
    source = source.replace(anchor,
        "r.get('beforeSha256') is None for r in files if r['candidate'] not in V3_NEW if not (", 1)
    base = types.ModuleType('frozen_fc_v3_knowledge_publisher')
    base.__file__ = str(HERE / 'release_navigation_base.py')
    base.V3_NEW = frozenset(name for name in mapping if name not in RUNTIME)
    exec(compile(source, base.__file__, 'exec'), base.__dict__)
    base.HERMES_HISTORY_SCOPE, base.HERMES_HISTORY_TARGETS = SCOPE, mapping
    base.expected_files = lambda m: set(mapping) if m.get('scope') == SCOPE else set()
    base.target_for = lambda relative: mapping[relative]
    original_validate = base.validate

    def validate(manifest, stage):
        if manifest != approved:
            raise ValueError('frozen_manifest_required')
        return original_validate(manifest, stage)

    base.validate = validate
    original_group = base.approved_daily_group

    def existing_shared_parent(value, root, item, info):
        return original_group(value, root, item, info) or (
            value.get('scope') == SCOPE and
            item == base.rooted(root, '/var/lib/fs-hermes-fc') and
            (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 9876, 0o750))

    base.approved_daily_group = existing_shared_parent
    original_quiescent = base.hermes_quiescent

    def quiescent(root):
        original_quiescent(root)
        for path, query in (
            ('/var/lib/fs-hermes-fc/fs/conversations/conversations.db',
             "SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',
             "SELECT count(*) FROM scan_jobs WHERE state='pending'"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',
             "SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')")):
            database = base.rooted(root, path)
            base.no_target_link(database)
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                if db.execute(query).fetchone()[0]:
                    raise ValueError('active_conversation_or_tracking')
        database = base.rooted(root, '/var/lib/fs-hermes-fc/fs/tasks.sqlite3')
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_events'").fetchone():
                if db.execute("SELECT count(*) FROM learning_events WHERE state IN ('running','unknown')").fetchone()[0]:
                    raise ValueError('active_or_unreconciled_learning')

    base.hermes_quiescent = quiescent
    original_live_lock=base.live_lock
    original_fence=base.hermes_admission_fence
    original_restart=base.restart_for

    @contextmanager
    def document_live_lock(value,root):
        if value.get('scope')!=SCOPE:
            with original_live_lock(value,root):yield
            return
        # Only the exact two-document/immutable-artifact scope passed targets().
        # Its admission fence below does not contend with ordinary cost reads.
        yield

    @contextmanager
    def document_fence(value,root):
        if value.get('scope')!=SCOPE:
            with original_fence(value,root) as fence:yield fence
            return
        # Existing knowledgeOnly reader-entry + task-DB publication protocol.
        # Already-admitted cost readers retain their admission shared lease.
        import fcntl
        path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/reader-entry.lock')
        base.no_target_link(path)
        fd,db=os.open(str(path),os.O_RDWR|getattr(os,'O_NOFOLLOW',0)),None
        try:
            info,current=os.fstat(fd),path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or
                    info.st_uid!=os.geteuid() or info.st_mode&0o077 or
                    (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino)):
                raise ValueError('unsafe knowledge admission entry')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            database=base.rooted(root,'/var/lib/fs-hermes-fc/fs/tasks.sqlite3')
            base.no_target_link(database)
            db=sqlite3.connect(database.as_uri()+'?mode=rw',uri=True,timeout=0)
            db.execute('BEGIN IMMEDIATE')
            base.hermes_quiescent(root)
            yield None
        finally:
            try:
                if db is not None:
                    try:db.rollback()
                    finally:db.close()
            finally:os.close(fd)

    def restart(value,admission_fence=None):
        if value.get('scope')!=SCOPE:return original_restart(value,admission_fence)
        # Policy and baseline are read for each new admission; no code changed.

    base.live_lock=document_live_lock
    base.hermes_admission_fence=document_fence
    base.restart_for = restart
    return base


if __name__ == '__main__':
    load_base().main()
