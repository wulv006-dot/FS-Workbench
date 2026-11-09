"""Exact activation adapter over the installed publisher. Never edits business state."""
from contextlib import contextmanager,closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,time,types,urllib.request

PUBLISHER=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
SCOPE='traffic-source-tabs-ui-finish-20261019'
UNITS=('fs-campaign-dashboard.service', 'fs-campaign-runtime.service', 'fs-business-range.service')
TARGETS={'code/Player-Trio.html': '/opt/fs-campaign-dashboard/Player-Trio.html', 'code/Sbc-Companions.html': '/opt/fs-campaign-dashboard/Sbc-Companions.html', 'code/Weekly-Scout.html': '/opt/fs-campaign-dashboard/Weekly-Scout.html', 'code/activity-content.js': '/opt/fs-campaign-dashboard/activity-content.js', 'code/activity.css': '/opt/fs-campaign-dashboard/activity.css', 'code/activity.js': '/opt/fs-campaign-dashboard/activity.js', 'code/analytics/center-seed.mjs': '/opt/fs-campaign-dashboard/analytics/center-seed.mjs', 'code/analytics/center-store.mjs': '/opt/fs-campaign-dashboard/analytics/center-store.mjs', 'code/analytics/production-server.mjs': '/opt/fs-campaign-dashboard/analytics/production-server.mjs', 'code/analytics/weekly-commerce.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-commerce.mjs', 'code/analytics/weekly-pipeline.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs', 'code/index.html': '/opt/fs-campaign-dashboard/index.html', 'code/runtime/model-cards.mjs': '/opt/fs-campaign-dashboard/runtime/model-cards.mjs', 'code/runtime/presentation.mjs': '/opt/fs-campaign-dashboard/runtime/presentation.mjs', 'code/runtime/snapshot.mjs': '/opt/fs-campaign-dashboard/runtime/snapshot.mjs', 'code/backend/bridge.py': '/opt/fs-campaign-dashboard/backend/bridge.py', 'code/backend/campaign_backend/weekly.py': '/opt/fs-campaign-dashboard/backend/campaign_backend/weekly.py', 'derived/static-manifest.json': '/opt/fs-campaign-dashboard/runtime/static-manifest.json'}
ROLLBACK_BASELINES={'/opt/fs-campaign-dashboard/Player-Trio.html': 'bc83250c9f5f4751391d2f1124f5f01aa3243d64a9ca056e83764a015b7fbf9c', '/opt/fs-campaign-dashboard/Sbc-Companions.html': 'e80578dc0a5adefb0728cef69859869d60f82613c175e1061117b3ba3a2298a4', '/opt/fs-campaign-dashboard/Weekly-Scout.html': '3e0e4231241966b5e2a4bfa9c8cbae535031c7e5332b8b3f0c64aec8cbdb4870', '/opt/fs-campaign-dashboard/activity-content.js': '15fccfc8bac9de5904e1eb7e09925d7ca7738b91472f36e076b9f8a915c10138', '/opt/fs-campaign-dashboard/activity.css': 'e7eaaa9fe46dc42ef0232d4bcc8912031cfea0e8bcaacc74f26ce7d8094c177b', '/opt/fs-campaign-dashboard/activity.js': '00c7d5daf222c5d3a2209bc1d4d0a63d318ec2d9d48fe86953923baf509792cf', '/opt/fs-campaign-dashboard/analytics/center-seed.mjs': '8fa0e742b77414ec2bcefe87872fc587851fda67468b3cc3f2df994468ebabed', '/opt/fs-campaign-dashboard/analytics/center-store.mjs': 'e1010c2d22d4c4ccd0cf9bc26d7173c04794d9996cc566ac3a650dfe18ead035', '/opt/fs-campaign-dashboard/analytics/production-server.mjs': '35039916c0b7dc65e5bee330af6065a26e582182197869b37ae9afd26dcd02b1', '/opt/fs-campaign-dashboard/analytics/weekly-commerce.mjs': '6090b7057391433e9b6c20dc8ab06f971ee506e6b52ec31c411edee186ebf5be', '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs': 'f32c4ed97db063811bbc7a69db1fa122c38e45bca1ffb0b31bf0d1984253bb82', '/opt/fs-campaign-dashboard/index.html': 'ef30ff8cd453319c73f7e3fbcc425b7f64d38ee99ca6b6357c6b311d2b66c12c', '/opt/fs-campaign-dashboard/runtime/model-cards.mjs': 'cad1e6216e158989404319b9ce001a8e85ad153c3698460fa6518ad1a978f844', '/opt/fs-campaign-dashboard/runtime/presentation.mjs': '35ae007bafc7850e2e36b1723f16a0de7f325d05aadad3b59f5a4746b8417102', '/opt/fs-campaign-dashboard/runtime/snapshot.mjs': '36cf6563ffb718204037398a75749b96c17c3f0439d4c2fcf0001c3bca29555f', '/opt/fs-campaign-dashboard/backend/bridge.py': '7024b0ec87699ebf5f793cf80192785de60f48e1ca9f37ba12f15d917d67734f', '/opt/fs-campaign-dashboard/backend/campaign_backend/weekly.py': '605aa54152358fb475f70049179e0e76f406a2638c62aa6d3dce9f514e02e906', '/opt/fs-campaign-dashboard/runtime/static-manifest.json': 'fcf7053ada01ac3adcbc3847a82a2eebd0d08647950fd40f2c74318358c82504'}
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
        if (len(files)!=18 or {row['target']:row['beforeSha256'] for row in files}!=ROLLBACK_BASELINES
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
