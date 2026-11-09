"""Exact activation adapter over the installed publisher. Never edits business state."""
from contextlib import contextmanager,closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,time,types,urllib.request

PUBLISHER=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
SCOPE='traffic-source-tabs-ui-finish-20261019'
UNITS=('fs-campaign-dashboard.service', 'fs-campaign-runtime.service', 'fs-business-range.service')
TARGETS={'app/Player-Trio.html': '/opt/fs-campaign-dashboard/Player-Trio.html', 'app/Sbc-Companions.html': '/opt/fs-campaign-dashboard/Sbc-Companions.html', 'app/Weekly-Scout.html': '/opt/fs-campaign-dashboard/Weekly-Scout.html', 'app/activity-content.js': '/opt/fs-campaign-dashboard/activity-content.js', 'app/activity-core.js': '/opt/fs-campaign-dashboard/activity-core.js', 'app/activity.js': '/opt/fs-campaign-dashboard/activity.js', 'app/analytics-config.js': '/opt/fs-campaign-dashboard/analytics-config.js', 'app/analytics/activity-registry.json': '/opt/fs-campaign-dashboard/analytics/activity-registry.json', 'app/analytics/admin-price-provider.mjs': '/opt/fs-campaign-dashboard/analytics/admin-price-provider.mjs', 'app/analytics/center-seed.mjs': '/opt/fs-campaign-dashboard/analytics/center-seed.mjs', 'app/analytics/center-store.mjs': '/opt/fs-campaign-dashboard/analytics/center-store.mjs', 'app/analytics/native-catalog.mjs': '/opt/fs-campaign-dashboard/analytics/native-catalog.mjs', 'app/analytics/production-server.mjs': '/opt/fs-campaign-dashboard/analytics/production-server.mjs', 'app/analytics/products.js': '/opt/fs-campaign-dashboard/analytics/products.js', 'app/analytics/weekly-pipeline.mjs': '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs', 'app/analytics/weekly.js': '/opt/fs-campaign-dashboard/analytics/weekly.js', 'app/catalog.js': '/opt/fs-campaign-dashboard/catalog.js', 'app/catalog.json': '/opt/fs-campaign-dashboard/catalog.json', 'app/index.html': '/opt/fs-campaign-dashboard/index.html', 'app/runtime/admin-price-cache.mjs': '/opt/fs-campaign-dashboard/runtime/admin-price-cache.mjs', 'app/runtime/model-cards.mjs': '/opt/fs-campaign-dashboard/runtime/model-cards.mjs', 'app/runtime/presentation.mjs': '/opt/fs-campaign-dashboard/runtime/presentation.mjs', 'app/runtime/snapshot.mjs': '/opt/fs-campaign-dashboard/runtime/snapshot.mjs', 'app/sitemap.xml': '/opt/fs-campaign-dashboard/sitemap.xml', 'derived/static-manifest.json': '/opt/fs-campaign-dashboard/runtime/static-manifest.json'}
ROLLBACK_BASELINES={'/opt/fs-campaign-dashboard/Player-Trio.html': 'ade480d9c38a9ee0f2e2c68ac080b63da004b87978ccb2edc871715ec75d1df7', '/opt/fs-campaign-dashboard/Sbc-Companions.html': '69b7ff1ec1136f379ee5e2b0f1191b77aed0cc5fe4716b2f077ae0b73ea685c3', '/opt/fs-campaign-dashboard/Weekly-Scout.html': '47d0f793fd17a76e463d2100c780ac18f4d8f02d24db9d335703b0e8909614df', '/opt/fs-campaign-dashboard/activity-content.js': '3cfd8a1f0f464e231e1660ae7bf07810eda773bdd2c1a24ff3e28494f047aa6a', '/opt/fs-campaign-dashboard/activity-core.js': '7016c5f85f80069928f3c66341312fa9940c44c6753e33a2158205eaa996b7f7', '/opt/fs-campaign-dashboard/activity.js': '7a3e3cd3610e7aa1940b684a5e57ec0cd557c0123727acdd100004d8bfdb7972', '/opt/fs-campaign-dashboard/analytics-config.js': '7dbe7278e45ee652a3df134c3e450fba696db35a2ab8bebce1b21156f79f1d32', '/opt/fs-campaign-dashboard/analytics/activity-registry.json': '96f7559735e86f57ca7155f2c42aab6cb96922d6561e11c8cd0fb6e8ae309f2b', '/opt/fs-campaign-dashboard/analytics/admin-price-provider.mjs': '808b3b9b36923209c55bf6370b8e61072ea1f251fa82d85fdf98f56388b3e7ba', '/opt/fs-campaign-dashboard/analytics/center-seed.mjs': '683e4ff5f12b970a1d54f71695891bd9352021c23d78b2948f8ce77d8a160e75', '/opt/fs-campaign-dashboard/analytics/center-store.mjs': 'fa3ab3667eb069e7b724c4ed32fe02b661c4469af0eae8cf51ac7b9f4ebba7b3', '/opt/fs-campaign-dashboard/analytics/native-catalog.mjs': '0d5168f1e69e9b976df94e1ce383d9f519617dd7f0cb430b71039d816caa82d6', '/opt/fs-campaign-dashboard/analytics/production-server.mjs': '239ef86a5ddf13230c2d4f3bfcf918df974dfd74fcf33d936ba29a36e5c37505', '/opt/fs-campaign-dashboard/analytics/products.js': '74b5af7d8d9b935233bcf2f42976b1019c55717b9fe59b9faa012d285a6cada6', '/opt/fs-campaign-dashboard/analytics/weekly-pipeline.mjs': '7be7250f58bdd62f8f799ef017f0c69e306f5c39a7f3dfaa051aa84ae7f6d164', '/opt/fs-campaign-dashboard/analytics/weekly.js': 'd546feb7cbd067a258a657ec8d4aded7b8296995c88e9ce586cc86a2a383516d', '/opt/fs-campaign-dashboard/catalog.js': 'c16443351f561e222b69520e961962a08c6f6dee5688fb1378b3dba01872955f', '/opt/fs-campaign-dashboard/catalog.json': '2a600b6e755ebe18a28f5dcb1af2bcda16b3b135881c4cdf5c6c8d573b261f01', '/opt/fs-campaign-dashboard/index.html': '9c94475d1fad1409f8aa357c2072913ae0982fa5a23e7e2aa941c454118fb1ed', '/opt/fs-campaign-dashboard/runtime/admin-price-cache.mjs': 'c82e3cb9c464c12da9586bc68016dc7f1a6859ffb322247bfc6d14c157dcbb66', '/opt/fs-campaign-dashboard/runtime/model-cards.mjs': '3d4dc4337cda6aeb38ef631655595762287357b97167870926b8ad3c39573dc2', '/opt/fs-campaign-dashboard/runtime/presentation.mjs': '9fdcfd170d329313c03c4e9d7fe15a277c94651f8d654ced405b05be526b74cd', '/opt/fs-campaign-dashboard/runtime/snapshot.mjs': 'cfddb2d1d6c64db4f7f89fc5c2b447aa03db71338c75e4b8d842a2da8b5efeeb', '/opt/fs-campaign-dashboard/sitemap.xml': 'd67f5e53603a2e50aa42db4c0294ef1e3b10df84fb7103fccf52b29700b803d5', '/opt/fs-campaign-dashboard/runtime/static-manifest.json': 'b3f2a8bada82011516fcf77ed4bbbecedde0f1a8eea413dc0a775d86e426376e'}
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
        if (len(files)!=25 or {row['target']:row['beforeSha256'] for row in files}!=ROLLBACK_BASELINES
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
