"""Single host / same lock late-generation checkpoint probe, fixed commit."""
import json,os,subprocess,sys,tempfile,types
from pathlib import Path
from threading import Event,RLock,Thread
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_support import read_sources,install_guard
ROOT=Path(__file__).resolve().parent
REPO=Path(os.environ.get('FS_ACCEPTANCE_REPO', str(ROOT.parents[2]))).resolve()
SHA='40dbf3df38adcd19f5a1afda853b06712886d3e0'
paths={'date_policy':'tiered-data-access-20261101/source/date_policy.py',
       'range_jobs':'tiered-data-access-20261101/source/range_jobs.py',
       'query_checkpoint':'tiered-data-access-20261101/source/query_checkpoint.py',
       'daily_archive':'daily-archive-20261021/source/daily_archive.py'}
sources=read_sources(REPO,SHA,{'date_policy': 'releases/fs-dashboard/tiered-data-access-20261101/source/date_policy.py', 'range_jobs': 'releases/fs-dashboard/tiered-data-access-20261101/source/range_jobs.py', 'query_checkpoint': 'releases/fs-dashboard/tiered-data-access-20261101/source/query_checkpoint.py', 'daily_archive': 'releases/fs-dashboard/daily-archive-20261021/source/daily_archive.py'})
install_guard()
for n,s in sources.items():
    m=types.ModuleType(n);sys.modules[n]=m;exec(compile(s,SHA+':'+paths[n],'exec'),m.__dict__)
from daily_archive import Archive
from query_checkpoint import Checkpoints
from range_jobs import Engine
grant={'scope_hash':'synthetic','permission_epoch':'1','policy_version':'v1'}
plan={'network_allowed':True,'slices':[{'start':'2026-10-01','end_exclusive':'2026-10-02'}],
      'query':{'grain':'detail','filter_hash':'synthetic-normalized','policy_version':'v1','fields':['order_id','amount']},
      'budget':{'max_requests':3,'max_rows':10,'max_bytes':1024}}
with tempfile.TemporaryDirectory() as directory:
    store=Checkpoints(Archive(Path(directory)/'archive'));store.initialize()
    engine=Engine(jobs={},subscriptions={},cache={},authorize=lambda u,q:dict(grant),secret=b'x'*32,lock=RLock(),checkpoint=store.save)
    def submit():return engine.submit('synthetic',plan,watermark='w1',source_contract='v1')
    first=submit();key=engine.subscriptions[first]['key'];old_generation=engine.jobs[key]['generation']
    entered,release=Event(),Event();errors=[]
    def adapter(req):
        entered.set()
        if not release.wait(5):raise RuntimeError('probe_timeout')
        return {'rows':[{'order_id':'old','amount':'1'}],'watermark':'w1','complete':True,'next_cursor':None}
    def run():
        try:engine.step(key,adapter)
        except BaseException as e:errors.append(type(e).__name__)
    thread=Thread(target=run);thread.start()
    try:
        if not entered.wait(5):raise RuntimeError('probe_timeout')
        engine.cancel('synthetic',first)
        second=submit();new_generation=engine.jobs[key]['generation']
        before,_=store.load()
    finally:release.set();thread.join(6)
    if thread.is_alive():raise RuntimeError('probe_thread_still_running')
    after,subscriptions=store.load()
    result={'commit':SHA,'host_count':1,'same_engine_and_lock':True,'thread_errors':errors,
            'old_generation':old_generation,'new_generation':new_generation,
            'durable_generation_before_late_return':before[key]['generation'],
            'memory_new_status':engine.status('synthetic',second)['status'],
            'durable_generation_after_late_return':after[key]['generation'],
            'durable_status_after_late_return':after[key]['status'],
            'new_subscription_persisted_active':subscriptions[second]['active'],'production_validated':False}
    print(json.dumps(result))
