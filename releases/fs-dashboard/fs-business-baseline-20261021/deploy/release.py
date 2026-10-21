"""Exact V2 adapter over the existing CAS/backup/rollback publisher."""
import hashlib
import json
from pathlib import Path
import sqlite3
import types
from contextlib import closing

HERE=Path(__file__).resolve().parent
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
SCOPE='fs-business-baseline-20261021'
TARGETS={'runtime/coupon_channels.py': '/opt/fs-hermes-fc/coupon_channels.py', 'runtime/coupon_channels.json': '/opt/fs-hermes-fc/coupon_channels.json', 'runtime/admin_discount_analysis.py': '/opt/fs-hermes-fc/admin_discount_analysis.py', 'runtime/price_ending.py': '/opt/fs-hermes-fc/price_ending.py', 'runtime/es_order_structure.py': '/opt/fs-hermes-fc/es_order_structure.py', 'runtime/research.py': '/opt/fs-hermes-fc/research.py', 'runtime/data_workspace_request.py': '/opt/fs-hermes-fc/data_workspace_request.py', 'runtime/business_context.py': '/opt/fs-hermes-fc/business_context.py', 'runtime/pricing_simulation.py': '/opt/fs-hermes-fc/pricing_simulation.py', 'runtime/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md', 'ui/data-workspace.js': '/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/data-workspace.js', 'ui/page.js': '/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/page.js', 'ui/tools-index.html': '/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/tools-index.html', 'ui/tracking-page.js': '/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/tracking-page.js', 'ui/brain-index.html': '/var/www/dashboard/fs-home/brain/index.html', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
REPOSITORY_SOURCES={'runtime/coupon_channels.py': 'source/coupon_channels.py', 'runtime/coupon_channels.json': 'source/coupon_channels.json', 'runtime/admin_discount_analysis.py': 'source/admin_discount_analysis.py', 'runtime/price_ending.py': 'source/price_ending.py', 'runtime/es_order_structure.py': 'source/hermes/es_order_structure.py', 'runtime/research.py': 'source/hermes/research.py', 'runtime/data_workspace_request.py': 'source/hermes/data_workspace_request.py', 'runtime/business_context.py': 'source/hermes/business_context.py', 'runtime/pricing_simulation.py': 'source/hermes/pricing_simulation.py', 'runtime/business-baseline.md': 'source/hermes/business-baseline.md', 'ui/data-workspace.js': 'source/ui/data-workspace.js', 'ui/page.js': 'source/ui/page.js', 'ui/tools-index.html': 'source/ui/tools-index.html', 'ui/tracking-page.js': 'source/ui/tracking-page.js', 'ui/brain-index.html': 'source/ui/brain-index.html'}
NEW=frozenset(['runtime/coupon_channels.py', 'runtime/coupon_channels.json', 'runtime/price_ending.py', 'runtime/business-baseline.md', 'ui/data-workspace.js', 'ui/page.js', 'ui/tools-index.html', 'ui/tracking-page.js'])


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
    # The original existing-file rule remains; only the explicit NEW targets may be absent.
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
