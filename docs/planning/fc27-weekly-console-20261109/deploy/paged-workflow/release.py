"""Exact activation adapter over the installed publisher. Never edits business state."""
from contextlib import contextmanager,closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,time,types,urllib.request

PUBLISHER=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
SCOPE='traffic-source-tabs-ui-finish-20261019'
UNITS=('fs-campaign-dashboard.service', 'fs-campaign-runtime.service', 'fs-business-range.service')
TARGETS={'code/activity.js': '/opt/fs-campaign-dashboard/activity.js', 'code/analytics/admin-price-provider.mjs': '/opt/fs-campaign-dashboard/analytics/admin-price-provider.mjs', 'code/analytics/products.html': '/opt/fs-campaign-dashboard/analytics/products.html', 'code/analytics/products.js': '/opt/fs-campaign-dashboard/analytics/products.js', 'code/analytics/weekly.html': '/opt/fs-campaign-dashboard/analytics/weekly.html', 'code/analytics/weekly.js': '/opt/fs-campaign-dashboard/analytics/weekly.js', 'code/analytics/weekly.css': '/opt/fs-campaign-dashboard/analytics/weekly.css', 'derived/static-manifest.json': '/opt/fs-campaign-dashboard/runtime/static-manifest.json'}
ROLLBACK_BASELINES={'/opt/fs-campaign-dashboard/activity.js': '2647eaec495397950fcedd0dd1f1e92acced68820921872d334efd863d0e1b7d', '/opt/fs-campaign-dashboard/analytics/admin-price-provider.mjs': '97113be3700cfb1f769136f94df9a5a2380418fb0d1834a2d77be97eed20a1b2', '/opt/fs-campaign-dashboard/analytics/products.html': '0d2f197b27d4fec2ce4b104c534765b597e5ebc9ec43827faac6d82a6d951901', '/opt/fs-campaign-dashboard/analytics/products.js': '2eb9c34c23245d35998eb869a2cd2d8b3fc9f4f14c47198f34511353f5ad7491', '/opt/fs-campaign-dashboard/analytics/weekly.html': '82c6ba88ca2f0800ae0d0c2c8356242f6254f8132196df0d9baab75a355b7bb6', '/opt/fs-campaign-dashboard/analytics/weekly.js': '8760b66396b906c69376f017ceec728748b4dfd490fa732a3bfcf37b83d063ec', '/opt/fs-campaign-dashboard/analytics/weekly.css': '257f4fe25477e057457ecb10dd8eae9e5962930fb1eacb99c0ca717865e9d3b7', '/opt/fs-campaign-dashboard/runtime/static-manifest.json': '82838fa6d36809185f6aec882d20f3441392f6cd577e21546406c783671fa953'}
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
        if (len(files)!=8 or {row['target']:row['beforeSha256'] for row in files}!=ROLLBACK_BASELINES
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
