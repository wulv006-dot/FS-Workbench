"""Fixed-commit dry-run proof freshness probe; synthetic object only."""
import hashlib,json,os,subprocess,sys,tempfile,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_support import read_sources,install_guard
ROOT=Path(__file__).resolve().parent;REPO=Path(os.environ.get('FS_ACCEPTANCE_REPO', str(ROOT.parents[2]))).resolve()
SHA='0c29890b51c8370d40bccaf4c6538f3849b6e22f'
names=['date_policy','eviction_policy','recovery_contract']
sources=read_sources(REPO,SHA,{'date_policy': 'releases/fs-dashboard/tiered-data-access-20261101/source/date_policy.py', 'eviction_policy': 'releases/fs-dashboard/tiered-data-access-20261101/source/eviction_policy.py', 'recovery_contract': 'releases/fs-dashboard/tiered-data-access-20261101/source/recovery_contract.py'})
install_guard()
for name,source in sources.items():
    m=types.ModuleType(name);sys.modules[name]=m;exec(compile(source,SHA+':'+name,'exec'),m.__dict__)
from eviction_policy import CHECKS,dry_run
from recovery_contract import decision
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);raw=b'{"synthetic":true}';ident=hashlib.sha256(raw).hexdigest();p=root/(ident+'.data.json');p.write_bytes(raw)
    item=dict(path=str(p),object_id=ident,dataset_id='fixture',scope_hash='s1',source_contract='v1',classification='L1',active_job=False,mode='fresh',expires_at=1,start='2026-10-01',end_exclusive='2026-10-02',fields=['order_id'],proof_id='old-proof')
    proof=dict(proof_id='old-proof',verified=True,evidence_kind='synthetic',mode='current_state',evidence_sha256='0'*64,dataset_id='fixture',scope_hash='s1',source_contract='v1',start=item['start'],end_exclusive=item['end_exclusive'],fields=['order_id'],stable_key='order_id',checks={k:True for k in CHECKS},verified_at=0,expires_at=1,revoked=True)
    policy=dict(contract='fs-cache-eviction-dryrun-v1',policy_id='fixture',roots=[str(root)],datasets=['fixture'],quarantine_days=7,max_object_bytes=1000,max_batch_bytes=1000)
    refs=dict(complete=True,epoch='r1',pins={ident:0},references=[])
    value=dry_run([item],policy,{'old-proof':proof},lambda d:refs,now=2,fixture=True)
    recovery=decision('cache_miss',proof=proof,query=item,fixture=True)
    result={'commit':SHA,'synthetic_only':True,'now':2,'proof_expires_at':1,'proof_revoked':True,
            'candidate_count':len(value['candidates']),'held':value['held'],'mutations':value['mutations'],
            'recovery_status':recovery['status'],'file_unchanged':p.read_bytes()==raw,'production_validated':False}
    print(json.dumps(result))
