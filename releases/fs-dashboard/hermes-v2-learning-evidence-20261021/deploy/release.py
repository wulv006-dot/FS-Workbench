"""Exact V2 adapter over the existing CAS/backup/rollback publisher."""
import hashlib
import json
from pathlib import Path
import sqlite3
import types
from contextlib import closing

HERE=Path(__file__).resolve().parent
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
SCOPE='hermes-v2-learning-evidence-20261021'
NAMES=('learning_service.py',)
TARGETS={'source/'+n:'/opt/fs-hermes-fc/'+n for n in NAMES}
NEW=frozenset()


def checked_manifest(approved):
    if approved.get('scope')!=SCOPE or len(approved.get('files',[]))!=len(TARGETS) or {r['candidate']:r['target'] for r in approved['files']}!=TARGETS:
        raise ValueError('exact_v2_targets_required')
    for row in approved['files']:
        if (row.get('beforeSha256') is None)!=(row['candidate'] in NEW) or row.get('owner')!='0:0' or row.get('mode')!='0o644':
            raise ValueError('v2_exact_new_existing_boundary')
    if approved.get('businessWrites') is not False or approved.get('timersChanged') is not False:
        raise ValueError('v2_readonly_schedule_boundary')
    return approved


def load_base():
    raw=(HERE/'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_publisher_drift')
    approved=checked_manifest(json.loads((HERE/'approved-manifest.json').read_text('utf-8')))
    source=raw.decode('utf-8')
    anchor="r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor)!=1:raise ValueError('frozen_new_file_anchor_drift')
    # The original existing-file rule remains; this repair allows no absent target files.
    source=source.replace(anchor,"r.get('beforeSha256') is None for r in files if r['candidate'] not in V2_NEW if not (",1)
    base=types.ModuleType('frozen_hermes_v2_publisher');base.__file__=str(HERE/'release_navigation_base.py')
    base.V2_NEW=NEW
    exec(compile(source,base.__file__,'exec'),base.__dict__)
    base.HERMES_HISTORY_SCOPE,base.HERMES_HISTORY_TARGETS=SCOPE,TARGETS
    base.expected_files=lambda manifest:set(TARGETS) if manifest.get('scope')==SCOPE else set()
    base.target_for=lambda relative:TARGETS[relative]
    validate=base.validate
    def exact_validate(manifest,stage):
        if manifest!=approved:raise ValueError('frozen_manifest_required')
        return validate(manifest,stage)
    base.validate=exact_validate
    quiescent=base.hermes_quiescent
    def idle(root):
        quiescent(root)
        for path,query in (
            ('/var/lib/fs-hermes-fc/fs/conversations/conversations.db',"SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',"SELECT count(*) FROM scan_jobs WHERE state='pending'"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',"SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')")):
            database=base.rooted(root,path);base.no_target_link(database)
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                if db.execute(query).fetchone()[0]:raise ValueError('active_conversation_or_tracking')
        database=base.rooted(root,'/var/lib/fs-hermes-fc/fs/tasks.sqlite3')
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_events'").fetchone():
                if db.execute("SELECT count(*) FROM learning_events WHERE state IN ('running','unknown')").fetchone()[0]:
                    raise ValueError('active_or_unreconciled_learning')
    base.hermes_quiescent=idle
    return base


if __name__=='__main__':load_base().main()
