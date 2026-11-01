"""One new edge probe plus Python 3.9 grammar check; fixed blobs, no full suite."""
import ast,json,os,subprocess,sys,types
from pathlib import Path
from threading import RLock
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_support import read_sources,install_guard
ROOT=Path(__file__).resolve().parent
REPO=Path(os.environ.get('FS_ACCEPTANCE_REPO', str(ROOT.parents[2]))).resolve()
SHA='bf7f9ca2c4ccdb040cdbbcf265eda23a42e85637'
names=['date_policy','query_contract','query_planner','daily_facts','range_jobs']
sources=read_sources(REPO,SHA,{'date_policy': 'releases/fs-dashboard/tiered-data-access-20261101/source/date_policy.py', 'query_contract': 'releases/fs-dashboard/tiered-data-access-20261101/source/query_contract.py', 'query_planner': 'releases/fs-dashboard/tiered-data-access-20261101/source/query_planner.py', 'daily_facts': 'releases/fs-dashboard/tiered-data-access-20261101/source/daily_facts.py', 'range_jobs': 'releases/fs-dashboard/tiered-data-access-20261101/source/range_jobs.py'})
for n,s in sources.items():ast.parse(s,feature_version=(3,9))
install_guard()
for name in ['date_policy','range_jobs']:
    mod=types.ModuleType(name);sys.modules[name]=mod;exec(compile(sources[name],SHA+':'+name,'exec'),mod.__dict__)
from range_jobs import Engine
grant={'scope_hash':'synthetic','permission_epoch':'1','policy_version':'v1'}
jobs,subs,cache={},{},{}
engine=Engine(jobs=jobs,subscriptions=subs,cache=cache,authorize=lambda u,q:dict(grant),secret=b'x'*32,lock=RLock())
plan={'network_allowed':True,'slices':[{'start':'2026-10-01','end_exclusive':'2026-10-02'}],
      'query':{'grain':'detail','filter_hash':'synthetic-normalized','policy_version':'v1','fields':['order_id','amount']},
      'budget':{'max_requests':2,'max_rows':10,'max_bytes':1024}}
handle=engine.submit('synthetic',plan,watermark='w1',source_contract='v1')
key=subs[handle]['key']
engine.step(key,lambda req:{'rows':[{'order_id':'synthetic-1'}],'complete':True,'next_cursor':None,'watermark':'w1'})
result={'commit':SHA,'python39_grammar':'5 source files pass ast feature_version=(3,9); not actual runtime',
        'missing_requested_field':{'requested':['order_id','amount'],'returned':['order_id'],
             'job_complete':engine.status('synthetic',handle)['complete'],'cached':key in cache},
        'falsey_nonstr_cursor':{'cursor':0,'response':engine.page('synthetic',handle,cursor=0)},
        'production_validated':False}
print(json.dumps(result))
