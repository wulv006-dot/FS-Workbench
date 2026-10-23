"""Exact nightly targets over the original locks, admission fence, CAS and rollback publisher."""
import hashlib
import json
from pathlib import Path
import sqlite3
import types
import urllib.request
import subprocess
from contextlib import closing

HERE = Path(__file__).resolve().parent
BASE_SHA = '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
SCOPE = 'nightly-pipeline-20261023'
TARGETS = {'source/nightly.py': '/opt/fs-hermes-fc/nightly.py', 'source/source_snapshots.py': '/opt/fs-hermes-fc/source_snapshots.py', 'source/nightly_data.py': '/opt/fs-hermes-fc/nightly_data.py', 'source/nightly_recovery_job.py': '/opt/fs-hermes-fc/nightly_recovery_job.py', 'source/nightly_ops.py': '/opt/fs-hermes-ops/nightly_ops.py', 'source/host.py': '/opt/fs-hermes-ops/host.py', 'source/archive_jobs.py': '/opt/fs-exact-range-20261001/archive_jobs.py', 'source/data-archive-first.md': '/opt/fs-hermes-fc/data-archive-first.md', 'units/fs-boss-management.timer': '/etc/systemd/system/fs-boss-management.timer', 'units/fs-boss-game-monitor.timer': '/etc/systemd/system/fs-boss-game-monitor.timer', 'units/fs-channel-cache.timer': '/etc/systemd/system/fs-channel-cache.timer', 'units/fs-data-archive.timer': '/etc/systemd/system/fs-data-archive.timer', 'units/fs-maintenance-cleanup.timer': '/etc/systemd/system/fs-maintenance-cleanup.timer'}
NEW = {'source/nightly_data.py','source/nightly_recovery_job.py','source/nightly_ops.py'}


def load_base():
    raw = (HERE / 'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    approved = json.loads((HERE / 'approved-manifest.json').read_text('utf-8'))
    if approved.get('scope') != SCOPE or len(approved.get('files', [])) != len(TARGETS) or \
            {r['candidate']: r['target'] for r in approved['files']} != TARGETS:
        raise ValueError('exact_followup_target_required')
    if any((r.get('beforeSha256') is None) != (r['candidate'] in NEW) or r.get('mode') != '0o644' or r.get('owner') != '0:0'
           for r in approved['files']) or approved.get('businessWrites') is not False or \
            approved.get('timersChanged') is not True:
        raise ValueError('existing_sources_only_no_business_writes')
    source = raw.decode('utf-8')
    anchor = "  if not required.issubset(protected) or set(protected)&set(targets.values()):"
    if source.count(anchor) != 1:
        raise ValueError('frozen_protection_anchor_drift')
    # The single changed source is checked by target CAS.
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
        result=restart(dict(manifest, scope=base.DEEP_SCOPE))
        timers=[Path(v).name for k,v in TARGETS.items() if k.startswith('units/')]
        if Path('/etc/localtime').read_bytes()!=Path('/usr/share/zoneinfo/Asia/Shanghai').read_bytes():
            raise ValueError('server_timezone_changed')
        subprocess.run(['systemctl','daemon-reload'],check=True,timeout=20)
        for unit in timers:
            subprocess.run(['systemctl','restart',unit],check=True,timeout=20)
            subprocess.run(['systemctl','is-active','--quiet',unit],check=True,timeout=10)
        return result
    base.restart_for = reload_reader
    return base


if __name__ == '__main__':
    load_base().main()
