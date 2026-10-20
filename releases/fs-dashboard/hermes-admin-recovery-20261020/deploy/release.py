"""Reuse the pinned publisher for two files; reload only the 8931 reader."""
import hashlib
import json
from pathlib import Path
import sqlite3
import types
import urllib.request
from contextlib import closing

HERE = Path(__file__).resolve().parent
BASE_SHA = '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
SCOPE = 'hermes-admin-recovery-20261020'
TARGETS = {'source/controller.py': '/opt/fs-hermes-fc/controller.py',
           'source/fc_daily.py': '/opt/fs-exact-range-20261001/fc_daily.py'}


def load_base():
    raw = (HERE / 'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    approved = json.loads((HERE / 'approved-manifest.json').read_text('utf-8'))
    if approved.get('scope') != SCOPE or len(approved.get('files', [])) != 2 or \
            {r['candidate']: r['target'] for r in approved['files']} != TARGETS:
        raise ValueError('exact_two_targets_required')
    if any(not r.get('beforeSha256') or r.get('mode') != '0o644' or r.get('owner') != '0:0'
           for r in approved['files']) or approved.get('businessWrites') is not False or \
            approved.get('timersChanged') is not False:
        raise ValueError('existing_sources_only_no_business_writes')
    source = raw.decode('utf-8')
    anchor = "  if not required.issubset(protected) or set(protected)&set(targets.values()):"
    if source.count(anchor) != 1:
        raise ValueError('frozen_protection_anchor_drift')
    # fc_daily changes in this scope; it is checked by target CAS, rather than unchanged CAS.
    source = source.replace(anchor, "  if manifest.get('scope')==HERMES_HISTORY_SCOPE:required-=set(targets.values())\n" + anchor)
    base = types.ModuleType('frozen_admin_recovery_publisher')
    base.__file__ = str(HERE / 'release_navigation_base.py')
    exec(compile(source, base.__file__, 'exec'), base.__dict__)
    base.HERMES_HISTORY_SCOPE, base.HERMES_HISTORY_TARGETS = SCOPE, TARGETS
    base.expected_files = lambda manifest: set(TARGETS) if manifest.get('scope') == SCOPE else set()
    base.target_for = lambda relative: TARGETS[relative]
    validate = base.validate
    def exact_validate(manifest, stage):
        if manifest != approved:
            raise ValueError('frozen_manifest_required')
        return validate(manifest, stage)
    base.validate = exact_validate
    quiescent = base.hermes_quiescent
    def idle(root):
        quiescent(root)
        for path, query in (
            ('/var/lib/fs-hermes-fc/fs/conversations/conversations.db', "SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db', "SELECT count(*) FROM scan_jobs WHERE state='pending'"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db', "SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')")):
            database = base.rooted(root, path)
            base.no_target_link(database)
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                if db.execute(query).fetchone()[0]:
                    raise ValueError('active_conversation_or_tracking')
        if root == Path('/'):
            with urllib.request.urlopen('http://127.0.0.1:8767/health', timeout=3) as response:
                health = json.load(response)
            if health.get('ready') is not True or any(health.get(k) != 0 for k in ('active_model_reads', 'active_customer_reads')):
                raise ValueError('session_not_idle')
    base.hermes_quiescent = idle
    restart = base.restart_for
    def reload_reader(manifest, admission_fence=None):
        if manifest.get('scope') != SCOPE or admission_fence is None:
            raise ValueError('exact_reader_reload_fence_required')
        admission_fence.stop_then_unlock_database()
        return restart(dict(manifest, scope=base.DEEP_SCOPE))
    base.restart_for = reload_reader
    return base


if __name__ == '__main__':
    load_base().main()
