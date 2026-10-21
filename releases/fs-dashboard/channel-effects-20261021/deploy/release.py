"""Exact channel dashboard adapter over the existing CAS/backup/rollback publisher."""
import hashlib
import json
from pathlib import Path
import sqlite3
import types
from contextlib import closing

HERE=Path(__file__).resolve().parent
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
SCOPE='fs-channel-effects-20261021'
TARGETS={'runtime/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py', 'runtime/channel_source.py': '/opt/fs-hermes-fc/channel_source.py', 'runtime/channel_cost_source.py': '/opt/fs-hermes-fc/channel_cost_source.py', 'runtime/channel_mapping.json': '/opt/fs-hermes-fc/channel_mapping.json', 'http/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'nav/hubnav.js': '/var/www/hub/hubnav.js', 'nav/navigation.json': '/var/www/dashboard/fs-home/navigation.json', 'nav/index.html': '/var/www/dashboard/fs-home/index.html', 'ui/index.html': '/var/lib/fs-navigation-formal-static/channel-effects-665e903dff04/index.html', 'ui/channel.js': '/var/lib/fs-navigation-formal-static/channel-effects-665e903dff04/channel.js', 'ui/channel.css': '/var/lib/fs-navigation-formal-static/channel-effects-665e903dff04/channel.css', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
REPOSITORY_SOURCES={'runtime/channel_effects.py': 'source/channel_effects.py', 'runtime/channel_source.py': 'source/channel_source.py', 'runtime/channel_cost_source.py': 'source/channel_cost_source.py', 'runtime/channel_mapping.json': 'source/channel_mapping.json', 'http/range_api.py': 'source/range_api.py', 'nav/hubnav.js': 'source/hubnav.js', 'nav/navigation.json': 'source/navigation.json', 'nav/index.html': 'source/home-index.html', 'ui/index.html': 'ui/index.html', 'ui/channel.js': 'ui/channel.js', 'ui/channel.css': 'ui/channel.css'}
NEW=frozenset(['runtime/channel_cost_source.py', 'runtime/channel_effects.py', 'runtime/channel_mapping.json', 'runtime/channel_source.py', 'ui/channel.css', 'ui/channel.js', 'ui/index.html'])


def checked_manifest(approved):
    if approved.get('scope')!=SCOPE or len(approved.get('files',[]))!=len(TARGETS) or {r['candidate']:r['target'] for r in approved['files']}!=TARGETS:
        raise ValueError('exact_channel_targets_required')
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
    # The original existing-file rule remains; only the explicit NEW targets may be absent.
    source=source.replace(anchor,"r.get('beforeSha256') is None for r in files if r['candidate'] not in V2_NEW if not (",1)
    # Changed navigation files have exact target CAS instead of an unchanged guard.
    guard_anchor="  if not required.issubset(protected) or set(protected)&set(targets.values()):"
    if source.count(guard_anchor)!=1:raise ValueError('frozen_consumer_guard_anchor_drift')
    source=source.replace(guard_anchor,"  required-=set(TARGETS_CHANGED_NAV)\n"+guard_anchor,1)
    base=types.ModuleType('frozen_hermes_v2_publisher');base.__file__=str(HERE/'release_navigation_base.py')
    base.V2_NEW=NEW
    base.TARGETS_CHANGED_NAV={'/var/www/dashboard/fs-home/index.html'}
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
    restart=base.restart_for
    def restart_with_navigation(manifest,admission_fence=None):
        restart(manifest,admission_fence)
        if manifest.get('scope')==SCOPE:
            import subprocess
            subprocess.run(['nginx','-t'],check=True,timeout=20)
            subprocess.run(['systemctl','reload','nginx'],check=True,timeout=20)
    base.restart_for=restart_with_navigation
    return base


if __name__=='__main__':load_base().main()
