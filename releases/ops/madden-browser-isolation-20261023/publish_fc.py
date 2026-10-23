"""Patch only backend bindings under original FC queue and writer locks."""
from contextlib import ExitStack
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time
from fc_isolation_patch import python_source,launcher

APP=Path('/opt/fc27-cloud-browser')
BACKUP=Path('/var/backups/fc-backend-isolation-20261023')
PY={
 'collect_p2pah_cost.py':('312f47f8305308558d69401a92d170aed1726e4f67f1944ac246b1d66c1ef812',{'tab':1}),
 'preview_backend.py':('42a302a1e0dfd74ffaec4e2308b6f8cea8ccecf391fcb732a29f3fad3a424986',{'page':1}),
 'price_writer.py':('db45ea5ebf51a469983543b61c78383ce55071c069803c068c04ebd6a287c644',{'page':1}),
 'restore_price.py':('5ced0d190afb3c4182e90d45b6c3afd7624dd52389709e993f727418317cb9a9',{'page':2})}
SH={
 'collect_p2pah_cost.sh':'f7bf7534f14e79e6eb19c82370c3dbd5b6d40e48eeb9a66b4871ccfde86f3124',
 'preview_backend.sh':'316c6241c17ca86d0856344ed650a080d1fd75a59552a5c5e9e4f1f9a89c9ddc',
 'execute_price.sh':'cade852b5da35a768ec4aaad423dae7f381eabb43546abf8af56c418e2533ebc',
 'restore_price.sh':'35993f7f850bdb87885739db9f89565c06368a88791d856db85955678e16349b'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    assert not BACKUP.exists(),'existing_release_requires_original_receipt_readback'
    sys.path.insert(0,str(APP));import automation_tick as tick
    import fc27_cloud_api as api
    from snapshot_layer import ROOT
    sys.path.insert(0,'/opt/fs-hermes-ops');from host import publisher
    atomic=publisher().atomic
    changes={};expected={};modes={}
    for name,(before,closes) in PY.items():
        p=APP/name;raw=p.read_bytes();assert sha(raw)==before
        changes[p]=python_source(raw.decode(),closes).encode();expected[p]=before;modes[p]=p.stat().st_mode&0o777
    for name,before in SH.items():
        p=APP/name;raw=p.read_bytes();assert sha(raw)==before
        changes[p]=launcher(raw.decode()).encode();expected[p]=before;modes[p]=p.stat().st_mode&0o777
    helper=APP/'isolated_backend.py';assert not helper.exists()
    changes[helper]=Path(__file__).with_name('isolated_backend.py').read_bytes();expected[helper]=None;modes[helper]=0o644
    with tick.queue_mutation(),ExitStack() as stack:
        names=set(tick.RETRY_LOCKS)|{'price-writer.lock','preview.lock','p2pah-cost.lock'}
        for name in sorted(names):
            held=stack.enter_context((ROOT/'state'/name).open('a+b'))
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert tick.retry_guard()=='ready','active_retry_guard'
        assert not list((ROOT/'queue').glob('*.json')),'active_fc_queue'
        assert api.health()['incomplete_executions']==0,'unresolved_execution'
        assert not any(json.loads(p.read_text()).get('status') in ('running','queued') for p in (ROOT/'jobs').glob('*.json')),'active_fc_job'
        BACKUP.mkdir(mode=0o700)
        receipt={'operation':'fc-backend-isolation-20261023','status':'prepared','files':{},'price_writes':0,'collections':0,'model_requests':0}
        for p,after in changes.items():
            raw=p.read_bytes() if p.is_file() else None
            assert (sha(raw) if raw is not None else None)==expected[p]
            receipt['files'][str(p)]={'before':expected[p],'after':sha(after)}
            if raw is not None:atomic(BACKUP/p.name,raw,0o600)
        atomic(BACKUP/'receipt.json',json.dumps(receipt).encode(),0o600)
        for p,after in changes.items():
            assert (sha(p.read_bytes()) if p.is_file() else None)==expected[p]
            atomic(p,after,modes[p]);assert sha(p.read_bytes())==sha(after)
        receipt.update(status='published_sha_verified',worker_memory_bytes=2147483648,verified_at=time.time(),service_restarts=0)
        atomic(BACKUP/'receipt.json',json.dumps(receipt).encode(),0o600)
    print(json.dumps(receipt))


if __name__=='__main__':
    with open('/var/lock/fs-navigation-release.lock','a+b') as a,open('/var/lock/fs-dashboard-release.lock','a+b') as b:
        fcntl.flock(a,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(b,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
