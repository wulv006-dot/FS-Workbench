"""Exact user analytics adapter over the existing CAS/backup/rollback publisher."""
import hashlib
import json
from pathlib import Path
import sqlite3
import types
from contextlib import closing

HERE=Path(__file__).resolve().parent
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
SCOPE='fs-user-analytics-20261022'
TARGETS={'runtime/user_config.json': '/opt/fs-hermes-fc/user_config.json', 'runtime/user_contract.py': '/opt/fs-hermes-fc/user_contract.py', 'runtime/user_http.py': '/opt/fs-hermes-fc/user_http.py', 'runtime/user_jobs.py': '/opt/fs-hermes-fc/user_jobs.py', 'runtime/user_lifecycle.py': '/opt/fs-hermes-fc/user_lifecycle.py', 'runtime/user_query.py': '/opt/fs-hermes-fc/user_query.py', 'runtime/user_runtime.py': '/opt/fs-hermes-fc/user_runtime.py', 'runtime/user_source.py': '/opt/fs-hermes-fc/user_source.py', 'runtime/user_store.py': '/opt/fs-hermes-fc/user_store.py', 'runtime/user_tools.py': '/opt/fs-hermes-fc/user_tools.py', 'integration/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'integration/research.py': '/opt/fs-hermes-fc/research.py', 'integration/fs_evidence.py': '/opt/fs-hermes-fc/fs_evidence.py', 'integration/rbac.py': '/opt/fs-access-policy/rbac.py', 'integration/fs_readonly.py': '/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/__init__.py', 'nav/navigation.json': '/var/www/dashboard/fs-home/navigation.json', 'nav/hubnav.js': '/var/www/hub/hubnav.js', 'nav/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', 'ui/index.html': '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/index.html', 'ui/users.js': '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js', 'ui/users.css': '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.css', 'units/fs-user-analytics.service': '/etc/systemd/system/fs-user-analytics.service', 'units/fs-user-analytics.timer': '/etc/systemd/system/fs-user-analytics.timer'}
REPOSITORY_SOURCES={'runtime/user_config.json': 'source/user_config.json', 'runtime/user_contract.py': 'source/user_contract.py', 'runtime/user_http.py': 'source/user_http.py', 'runtime/user_jobs.py': 'source/user_jobs.py', 'runtime/user_lifecycle.py': 'source/user_lifecycle.py', 'runtime/user_query.py': 'source/user_query.py', 'runtime/user_runtime.py': 'source/user_runtime.py', 'runtime/user_source.py': 'source/user_source.py', 'runtime/user_store.py': 'source/user_store.py', 'runtime/user_tools.py': 'source/user_tools.py', 'integration/range_api.py': 'releases/fs-dashboard/daily-archive-20261021/source/range_api.py', 'integration/research.py': 'releases/fs-dashboard/fc-coins-workflow-20261022/source/research.py', 'integration/fs_evidence.py': 'releases/fs-dashboard/fc-coins-workflow-20261022/source/fs_evidence.py', 'integration/rbac.py': 'opt/fs-access-policy/rbac.py', 'integration/fs_readonly.py': 'releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/__init__.py', 'ui/index.html': 'ui/index.html', 'ui/users.js': 'ui/users.js', 'ui/users.css': 'ui/users.css', 'units/fs-user-analytics.service': 'deploy/fs-user-analytics.service', 'units/fs-user-analytics.timer': 'deploy/fs-user-analytics.timer'}
NEW=frozenset(['runtime/user_config.json', 'runtime/user_contract.py', 'runtime/user_http.py', 'runtime/user_jobs.py', 'runtime/user_lifecycle.py', 'runtime/user_query.py', 'runtime/user_runtime.py', 'runtime/user_source.py', 'runtime/user_store.py', 'runtime/user_tools.py', 'ui/index.html', 'ui/users.css', 'ui/users.js', 'units/fs-user-analytics.service', 'units/fs-user-analytics.timer'])
AUTHORIZED_TIMERS=frozenset(['/etc/systemd/system/fs-user-analytics.service','/etc/systemd/system/fs-user-analytics.timer'])


def checked_manifest(approved):
    if approved.get('scope')!=SCOPE or len(approved.get('files',[]))!=len(TARGETS) or {r['candidate']:r['target'] for r in approved['files']}!=TARGETS:
        raise ValueError('exact_user_analytics_targets_required')
    for row in approved['files']:
        if (row.get('beforeSha256') is None)!=(row['candidate'] in NEW) or row.get('owner')!='0:0' or row.get('mode')!='0o644':
            raise ValueError('v2_exact_new_existing_boundary')
    if approved.get('businessWrites') is not False or approved.get('timersChanged') is not bool(AUTHORIZED_TIMERS):
        raise ValueError('v2_readonly_schedule_boundary')
    if AUTHORIZED_TIMERS and {v for k,v in TARGETS.items() if k.startswith('units/')} != AUTHORIZED_TIMERS:
        raise ValueError('exact_authorized_channel_units_required')
    return approved


def load_base():
    raw=(HERE/'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_publisher_drift')
    approved=checked_manifest(json.loads((HERE/'approved-manifest.json').read_text('utf-8')))
    source=raw.decode('utf-8')
    if SCOPE == 'fs-user-analytics-search-help-20261023' or (SCOPE == 'knowledge-native-fs-20261023' and approved.get('nativePluginOnly') is True):
        # Preserve the concurrently deployed native image; never roll it back for a UI release.
        old_image='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
        new_image='sha256:d51507514f3f52fdcc3cb6bc0d36e2b12863517aa590ae1338dd462ffe1636a4'
        if source.count(old_image)!=4 or approved.get('imageId')!=new_image:
            raise ValueError('search_exact_native_image_required')
        source=source.replace(old_image,new_image)
    anchor="r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor)!=1:raise ValueError('frozen_new_file_anchor_drift')
    # The original existing-file rule remains; only the explicit NEW targets may be absent.
    source=source.replace(anchor,"r.get('beforeSha256') is None for r in files if r['candidate'] not in V2_NEW if not (",1)
    # Changed navigation files have exact target CAS instead of an unchanged guard.
    guard_anchor="  if not required.issubset(protected) or set(protected)&set(targets.values()):"
    if source.count(guard_anchor)!=1:raise ValueError('frozen_consumer_guard_anchor_drift')
    source=source.replace(guard_anchor,"  required-=set(TARGETS_CHANGED_NAV)\n"+guard_anchor,1)
    parent_anchor="if s.st_uid!=0 or not approved_daily_group(manifest,root,item,s) or s.st_mode&0o022:raise ValueError('unsafe daily source boundary')"
    if source.count(parent_anchor)!=1:raise ValueError('frozen_parent_guard_drift')
    source=source.replace(parent_anchor,"if not USERS_SAFE_PARENT(root,item,s):raise ValueError('unsafe daily source boundary')",1)
    if AUTHORIZED_TIMERS:
        # This publisher instance admits only the four newly authorized channel units.
        needle="manifest.get('timersChanged') is not False:raise ValueError('Hermes readonly/schedule boundary')"
        if source.count(needle)!=2:raise ValueError('frozen_schedule_guard_drift')
        source=source.replace(needle,"manifest.get('timersChanged') is not True:raise ValueError('channel scheduling approval required')")
    base=types.ModuleType('frozen_hermes_v2_publisher');base.__file__=str(HERE/'release_navigation_base.py')
    base.V2_NEW=NEW
    base.TARGETS_CHANGED_NAV=set()
    def safe_parent(root,item,info):
        # Preserve the two existing Hermes profile boundaries exactly; grant no access.
        exact={'/var/lib/fs-hermes-fc/profile':(9876,9876,0o700),'/var/lib/fs-hermes-fc':(0,9876,0o750)}
        for path,expected in exact.items():
            if item==root/path.lstrip('/'):
                return (info.st_uid,info.st_gid,info.st_mode&0o777)==expected
        return info.st_uid==0 and info.st_gid==0 and not info.st_mode&0o022
    base.USERS_SAFE_PARENT=safe_parent
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
    def desktop_idle():
        import urllib.request
        token=Path('/var/lib/fs-hermes-fc/profile/.desktop-management/token').read_text().strip()
        request=urllib.request.Request('http://127.0.0.1:8942/api/health/idle',headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(request,timeout=5) as response:value=json.load(response)
        if value.get('idle') is not True:raise ValueError('active_or_unknown_desktop_turn')
    def idle(root):
        quiescent(root)
        desktop_idle()
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
        if manifest.get('scope')==SCOPE:
            if admission_fence is None:raise ValueError('channel admission fence required')
            admission_fence.stop_then_unlock_database()
            restart(dict(manifest,scope=base.HERMES_WORKER_SCOPE),admission_fence)
            import subprocess
            subprocess.run(['systemctl','restart','auth-portal.service'],check=True,timeout=30)
            subprocess.run(['systemctl','is-active','--quiet','auth-portal.service'],check=True)
            restart(dict(manifest,scope=base.DEEP_SCOPE),admission_fence)
            desktop_idle()
            subprocess.run(['systemctl','restart','fs-hermes-desktop.service'],check=True,timeout=60)
            subprocess.run(['systemctl','is-active','--quiet','fs-hermes-desktop.service'],check=True)
            subprocess.run(['nginx','-t'],check=True,timeout=20)
            subprocess.run(['systemctl','reload','nginx'],check=True,timeout=20)
            subprocess.run(['systemctl','daemon-reload'],check=True,timeout=20)
            timer='fs-user-analytics.timer'
            if Path('/etc/systemd/system/'+timer).is_file():
                subprocess.run(['systemctl','enable','--now',timer],check=True,timeout=20)
            else:
                # Rollback removes only the new timer; retained customer facts stay private.
                subprocess.run(['systemctl','disable','--now',timer],check=False,timeout=20)
        else:restart(manifest,admission_fence)
    base.restart_for=restart_with_navigation
    return base


if __name__=='__main__':load_base().main()
