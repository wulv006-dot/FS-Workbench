"""Exact activation adapter over the installed publisher. Never edits business state."""
from contextlib import contextmanager,closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,time,types,urllib.request

PUBLISHER=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
SCOPE='traffic-source-tabs-ui-finish-20261019'
UNITS=('fs-campaign-dashboard.service', 'fs-campaign-runtime.service', 'fs-business-range.service')
TARGETS={'app/Player-Trio.html': '/opt/fs-campaign-dashboard/Player-Trio.html', 'app/Sbc-Companions.html': '/opt/fs-campaign-dashboard/Sbc-Companions.html', 'app/Weekly-Scout.html': '/opt/fs-campaign-dashboard/Weekly-Scout.html', 'app/index.html': '/opt/fs-campaign-dashboard/index.html', 'app/activity-content.js': '/opt/fs-campaign-dashboard/activity-content.js', 'app/activity.css': '/opt/fs-campaign-dashboard/activity.css', 'app/analytics/center-store.mjs': '/opt/fs-campaign-dashboard/analytics/center-store.mjs', 'app/analytics/weekly.html': '/opt/fs-campaign-dashboard/analytics/weekly.html', 'app/analytics/production-server.mjs': '/opt/fs-campaign-dashboard/analytics/production-server.mjs', 'app/analytics/weekly-recommendations.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-recommendations.mjs', 'app/analytics/weekly-hermes.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-hermes.mjs', 'app/analytics/weekly.js': '/opt/fs-campaign-dashboard/analytics/weekly.js', 'app/analytics/store.mjs': '/opt/fs-campaign-dashboard/analytics/store.mjs', 'app/analytics/weekly-pipeline.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs', 'app/runtime/model-cards.mjs': '/opt/fs-campaign-dashboard/runtime/model-cards.mjs', 'backend/bridge.py': '/opt/fs-campaign-dashboard/backend/bridge.py', 'backend/campaign_backend/adapters.py': '/opt/fs-campaign-dashboard/backend/campaign_backend/adapters.py', 'backend/campaign_backend/models.py': '/opt/fs-campaign-dashboard/backend/campaign_backend/models.py', 'backend/campaign_backend/weekly.py': '/opt/fs-campaign-dashboard/backend/campaign_backend/weekly.py', 'shared/campaign_recommendations.py': '/opt/fs-hermes-fc/campaign_recommendations.py', 'shared/campaign_evidence.py': '/opt/fs-hermes-fc/campaign_evidence.py', 'shared/campaign_weekly.py': '/opt/fs-hermes-fc/campaign_weekly.py', 'derived/static-manifest.json': '/opt/fs-campaign-dashboard/runtime/static-manifest.json'}
ROLLBACK_BASELINES={'/opt/fs-campaign-dashboard/Player-Trio.html': 'e54076d5d335f7ffa723924a5854bbb2da921de661026a304513a55e828b52ec', '/opt/fs-campaign-dashboard/Sbc-Companions.html': 'd26f590520c7dc7c77c3bd4c3812e9361c27b7e2d91fe643d0d39c2fd7301656', '/opt/fs-campaign-dashboard/Weekly-Scout.html': '8c1b28369a10536c2e365aa1137424bf4e39bb77ea687252bf9a04d8e9270b13', '/opt/fs-campaign-dashboard/index.html': 'd6c88966b30850156708313837ab38834f315eb50be1199b41dcf430368fc3e3', '/opt/fs-campaign-dashboard/activity-content.js': 'd14af00aceab9ec20384ba9b84592ea1475d9d01c61709c1ebe4095bbd037315', '/opt/fs-campaign-dashboard/activity.css': '74e5e5ae4906c043d1acfbd243418119261a032d1fd363f5367f6cfc48b51194', '/opt/fs-campaign-dashboard/analytics/center-store.mjs': 'f9320c5804965f16ead6c532c60cb9dafae2478ef7298d9103f7b78a43c5b285', '/opt/fs-campaign-dashboard/analytics/weekly.html': '0a1ae08d6ec88da58d0669799ba5ff84615b6712d22927724d4261e42722a5d5', '/opt/fs-campaign-dashboard/analytics/production-server.mjs': '3ec461327c164ca97171ed8ca8d3ccc939df88daa6abdd99592011669a16998a', '/opt/fs-campaign-dashboard/analytics/weekly-recommendations.mjs': '54b5e05e6726eff44984c9c616d72bb421b2d13e912ddeec11cbae33c621c8eb', '/opt/fs-campaign-dashboard/analytics/weekly-hermes.mjs': '4a37b854e8b9aeb975724b29daf83754d359af16a8beffaa83bb3e4d72aad170', '/opt/fs-campaign-dashboard/analytics/weekly.js': '428c520eb381a5e49b809076cf3a9a5d61d5bcb57f308b8f65832d96a970e372', '/opt/fs-campaign-dashboard/analytics/store.mjs': 'f9236fa17180a11c34835dc64a55c0cb3661c4031df118bafcf050fa9c1a59f9', '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs': '1ffe2dbdacac2994349925a555cca5414467b489cfc42c20214f5fd7090759c3', '/opt/fs-campaign-dashboard/runtime/model-cards.mjs': '19899259ee288b1e2a1547ce6e0fdfa9e5af3033038c750a17e91d5a1bb0a5fc', '/opt/fs-campaign-dashboard/backend/bridge.py': '7a6aa5f46363a18dc9b99262fc498d1910441f820406eba1f1e2d21a0d1c1c24', '/opt/fs-campaign-dashboard/backend/campaign_backend/adapters.py': '01e0fc6a8b238b18f465a0f71aa585d7645435cbb8d468a21d618007ea014840', '/opt/fs-campaign-dashboard/backend/campaign_backend/models.py': '3e82affbdf06726bfdaaedb736ba4df17deb76bae6a83effe3e3695981562593', '/opt/fs-campaign-dashboard/backend/campaign_backend/weekly.py': 'c7f87f53b1cfd77c8dd7b604c905b351601b756965707476af603fd7169e4c25', '/opt/fs-hermes-fc/campaign_recommendations.py': '9a70af59a9459956f6e4db363cc7966d7313cf0583e8cd3460d73a261be5073a', '/opt/fs-hermes-fc/campaign_evidence.py': '6e021874581d860a8b8182a8d6388dbb418ca49fee45c4b8fd0555f68132f85f', '/opt/fs-hermes-fc/campaign_weekly.py': '4970c100f29f1b123324734d737baebc06b19001de9565ca5b1e76de29817d67', '/opt/fs-campaign-dashboard/runtime/static-manifest.json': 'bc828dc60a9edb19b42805e9e5e1deb8a68d5a6a17e277eead42b68b123b752d'}
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
    if targets!=TARGETS:raise ValueError('exact_corrections_targets_required')
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
        if (len(files)!=23 or {row['target']:row['beforeSha256'] for row in files}!=ROLLBACK_BASELINES
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
