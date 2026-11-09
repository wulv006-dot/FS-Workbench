"""Exact activation adapter over the installed publisher. Never edits business state."""
from contextlib import contextmanager,closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,time,types,urllib.request

PUBLISHER=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
SCOPE='traffic-source-tabs-ui-finish-20261019'
UNITS=('fs-campaign-dashboard.service', 'fs-campaign-runtime.service', 'fs-business-range.service')
TARGETS={'code/analytics/admin-price-provider.mjs': '/opt/fs-campaign-dashboard/analytics/admin-price-provider.mjs', 'code/analytics/center-store.mjs': '/opt/fs-campaign-dashboard/analytics/center-store.mjs', 'code/analytics/production-server.mjs': '/opt/fs-campaign-dashboard/analytics/production-server.mjs', 'code/analytics/products.html': '/opt/fs-campaign-dashboard/analytics/products.html', 'code/analytics/products.js': '/opt/fs-campaign-dashboard/analytics/products.js', 'code/analytics/weekly-commerce-install.py': '/opt/fs-campaign-dashboard/analytics/weekly-commerce-install.py', 'code/analytics/weekly-commerce.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-commerce.mjs', 'code/analytics/weekly-pipeline.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs', 'code/analytics/weekly-store.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-store.mjs', 'code/analytics/weekly-workflow.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-workflow.mjs', 'code/analytics/weekly.css': '/opt/fs-campaign-dashboard/analytics/weekly.css', 'code/analytics/weekly.html': '/opt/fs-campaign-dashboard/analytics/weekly.html', 'code/analytics/weekly.js': '/opt/fs-campaign-dashboard/analytics/weekly.js', 'code/runtime/model-options.mjs': '/opt/fs-campaign-dashboard/runtime/model-options.mjs', 'code/backend/bridge.py': '/opt/fs-campaign-dashboard/backend/bridge.py', 'code/backend/campaign_backend/benefits.py': '/opt/fs-campaign-dashboard/backend/campaign_backend/benefits.py'}
ROLLBACK_BASELINES={'/opt/fs-campaign-dashboard/analytics/admin-price-provider.mjs': 'e79f4a857c5e68b4c61f0595240d9537268d3215adfe6362d8e5a376927a17c9', '/opt/fs-campaign-dashboard/analytics/center-store.mjs': '6152bf9b60acf23ce04d872f6c709abfcc1806ee28163789df64c0b23e8e3766', '/opt/fs-campaign-dashboard/analytics/production-server.mjs': '7b22da3647348fa843fd47ed113d31213003d17da12020d4241174bc2df7f3eb', '/opt/fs-campaign-dashboard/analytics/products.html': '3d0e2020026ea5c9ff4631d46d8f560938adf2eb345418a721f74119ea7d2ac1', '/opt/fs-campaign-dashboard/analytics/products.js': 'efd1ed102ca62b458b8b3eba7c80137da6196c51dc54c53c915c3dd8a62f1ad2', '/opt/fs-campaign-dashboard/analytics/weekly-commerce-install.py': None, '/opt/fs-campaign-dashboard/analytics/weekly-commerce.mjs': None, '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs': '2d1b395d1b0a5023f7ef0ab9b165e8ba9b10b2e05102f1cc36f2a63ad8719a67', '/opt/fs-campaign-dashboard/analytics/weekly-store.mjs': '689ac0265ef4f732057b3e3e7ffe555f2e4ee0d8798e74eedb6756adbe96d18e', '/opt/fs-campaign-dashboard/analytics/weekly-workflow.mjs': None, '/opt/fs-campaign-dashboard/analytics/weekly.css': '7b19296865ed098de5b462ef8f7ad66d69f7607d36c4674afb9d2dc9f6167516', '/opt/fs-campaign-dashboard/analytics/weekly.html': '8389f3766b63aaca644c18937770847a0d53d9af0bcae8d7551b8ac45656f8b3', '/opt/fs-campaign-dashboard/analytics/weekly.js': '81fe7d069cca4beb2884ccff31bc4b100ce9739957f7df137d3d3a6f9afc23dc', '/opt/fs-campaign-dashboard/runtime/model-options.mjs': '6dd2fb99e13a1575a5a33e8d5a5db895124e982f5ffbe99d559ef7daa6c25971', '/opt/fs-campaign-dashboard/backend/bridge.py': 'a08ce475ef34a9174c2dac2371061ac4357d20996a89d437801b30df0cbb3847', '/opt/fs-campaign-dashboard/backend/campaign_backend/benefits.py': 'b296d893088c8d02e4fb4c4be1c66677fc949d1e3397087438e5d464f12ab056'}
PINS={'release_ui_finish.py':'fcab510f397582596e86fa913e7edfa4220ff6b44d679839452f920d63160188',
      'release_source_tabs.py':'78b4b054162a9cf578543f11bc6cea3b0041b535d49ea1c8f6059514f90e3466',
      'release_navigation_base.py':'57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'}


def observations(root=Path('/')):
    """Read counts only: no text, prompts, cookies, model content or DB initialization."""
    queries={
      '/var/lib/fs-hermes-fc/fs/tasks.sqlite3':{
        'requests':("state IN ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE')",True),
        'tasks':("state='RUNNING'",True),
        'learning_events':("state IN ('running','unknown')",False),
        'campaign_weekly_runs':("state='pending'",False),
        'campaign_recommendations':("state='pending'",False)},
      '/var/lib/fs-hermes-fc/fs/conversations/conversations.db':{
        'turns':("state IN ('preparing','dispatch_unknown','queued','running','stopping')",True)},
      '/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db':{
        'scan_jobs':("state='pending'",True),'milestones':("state IN ('claimed','creating','dispatch_unknown','queued','running')",True)},
      '/var/lib/fs-business-ranges/advisor/advisor.sqlite3':{'jobs':("state IN ('pending','running')",True)},
      '/var/lib/fs-business-ranges/fc-daily/daily.sqlite3':{'jobs':("state IN ('pending','running')",True),'model_calls':("state='started'",True)}}
    result={}
    for name,tables in queries.items():
        path=root/name.lstrip('/')
        if not path.is_file() or any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('inflight_database_unavailable:'+name)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            for table,(where,required) in tables.items():
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                if not exists:
                    if required:raise ValueError('inflight_table_unavailable:'+table)
                    continue
                result[name+':'+table]=db.execute('SELECT count(*) FROM '+table+' WHERE '+where).fetchone()[0]
    return dict(blocks_release=any(result.values()),counts=result)


def load(stage):
    targets=json.loads((stage/'targets.json').read_text())
    if targets!=TARGETS:raise ValueError('exact_commerce_code_targets_required')
    for name,expected in PINS.items():
        if hashlib.sha256((PUBLISHER/name).read_bytes()).hexdigest()!=expected:raise ValueError('existing_publisher_drift:'+name)
    path=PUBLISHER/'release_ui_finish.py';ui=types.ModuleType('reviewed_existing_ui_publisher');ui.__file__=str(path)
    exec(compile(path.read_bytes(),str(path),'exec'),ui.__dict__);ui.TARGETS=targets
    base=ui.publisher();original_locks=base.locks;original_quiescent=base.hermes_quiescent
    current={'fence':None,'rollback':False,'ready':False}
    original_atomic=base.atomic
    def protected_atomic(path,data,mode=0o644):
        if str(path) in set(targets.values()):
            if current['fence'] is None:raise ValueError('original_admission_fence_required')
            current['fence'].modified=True
        return original_atomic(path,data,mode)
    base.atomic=protected_atomic
    rollback_journal=base.rollback_journal
    def compatible_rollback(backup,journal,root):
        current['ready']=False
        files=journal.get('files',[])
        if (len(files)!=16 or {row['target']:row['beforeSha256'] for row in files}!=ROLLBACK_BASELINES
                or {row['candidate']:row['target'] for row in files}!=TARGETS):
            raise ValueError('rollback_requires_pinned_pre_corrections_baseline')
        result=rollback_journal(backup,journal,root)
        current['rollback']=True
        return result
    base.rollback_journal=compatible_rollback

    def quiescent(root):
        original_quiescent(root)
        if observations(root)['blocks_release']:raise ValueError('shared_model_or_task_active_defer_release')
    base.hermes_quiescent=quiescent

    @contextmanager
    def coordinated_locks(root):
        # Original UI lock order, then the existing Hermes DB/admission fence and provider lock.
        scoped={'scope':base.HERMES_UPDATE_SCOPE}
        with original_locks(root),base.hermes_admission_fence(scoped,root) as fence,base.model_release_lock(scoped,root):
            if fence is None:raise ValueError('original_admission_fence_required')
            current['fence']=fence
            current['rollback']=current['ready']=False
            try:
                yield
            except BaseException:raise
            else:
                if fence.modified:
                    if not current['ready']:raise ValueError('activation_not_confirmed')
                    fence.confirmed=True
            finally:current['fence']=None
    base.locks=coordinated_locks

    def activate(manifest,unused=None):
        if manifest['scope']!=SCOPE or current['fence'] is None:raise ValueError('weekly_activation_requires_original_fence')
        fence=current['fence']
        # The exact correction sources are installed by the original journalled publisher.
        # Keep new admissions excluded through process replacement and readiness.
        fence.modified=True
        fence.stop_then_unlock_database()
        for unit in UNITS:
            subprocess.run(['systemctl','restart',unit],check=True,timeout=60)
            subprocess.run(['systemctl','is-active','--quiet',unit],check=True,timeout=15)
        for attempt in range(50):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8931/health',timeout=1) as response:
                    if json.load(response).get('ok') is True:break
            except OSError:pass
            if attempt==49:raise ValueError('shared_range_readiness_failed')
            time.sleep(.1)
        current['ready']=True
        # Successful rollback may still propagate the original apply exception.
        # Ordinary apply is confirmed only after the publisher's final hash/journal readback.
        if current['rollback']:fence.confirmed=True
    base.restart_for=activate
    return base


def main():
    stage=Path(__file__).resolve().parent
    if len(sys.argv)<2:raise ValueError('inspect|inflight|apply|rollback required')
    action=sys.argv[1]
    if action=='inflight':result=observations()
    else:
        base=load(stage);raw=(stage/'manifest.json').read_bytes();manifest=json.loads(raw)
        if action=='inspect':
            result=dict(publisher=base.inspect(manifest,stage),inflight=observations())
        elif action=='apply':
            if len(sys.argv)!=4:raise ValueError('apply manifest_sha release_id required')
            result=base.apply(manifest,stage,sys.argv[2],raw,sys.argv[3])
        elif action=='rollback':
            if len(sys.argv)!=4:raise ValueError('rollback backup manifest_sha required')
            result=base.rollback(Path(sys.argv[2]),sys.argv[3])
        else:raise ValueError('unsupported action')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
