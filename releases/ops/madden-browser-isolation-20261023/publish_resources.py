"""Publish bounded launcher arguments with the installed atomic publisher."""
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from resource_boundaries import unit,rpg

BACKUP=Path('/var/backups/service-resource-boundaries-20261023')
UNITS={
 'fs-hermes-desktop.service':('829857986b22b27779e8fb800260d2d008757a40b1468cf7a5550c8bd6c94d54',7,'fs-hermes-desktop'),
 'fc27-p2pah-session.service':('b3441da437c9f625eeeb96ce66584d0143fe66bd05b7fe114c263ad11f357643',3,'fc27-p2pah-session')}
RPG=Path('/opt/d4follow/srv_exec.py')
RPG_SHA='7dc1b55cb7e840ec6cfe2c94258cdd5f2a5dcc6e178457e4b8b05a8f2a5a49ae'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def call(args):return subprocess.run(args,capture_output=True,text=True,check=True,timeout=25).stdout


def main():
    assert not BACKUP.exists(),'read_original_receipt_before_retry'
    changes={};containers={}
    for name,(expected,gib,container) in UNITS.items():
        p=Path('/etc/systemd/system')/name;raw=p.read_bytes();assert sha(raw)==expected
        changes[p]=unit(raw.decode(),gib).encode()
        c=json.loads(call(['docker','inspect',container]))[0]
        assert c['State']['Running'] and not c['State']['OOMKilled'] and c['HostConfig']['Memory']==0
        containers[container]={'id':c['Id'],'started_at':c['State']['StartedAt'],'gib':gib}
    original=RPG.read_bytes();assert sha(original)==RPG_SHA
    changes[RPG]=rpg(original.decode()).encode()
    sys.path.insert(0,'/opt/fs-hermes-ops');from host import publisher
    atomic=publisher().atomic
    BACKUP.mkdir(mode=0o700)
    receipt={'operation':'service-resource-boundaries-20261023','status':'prepared','containers':containers,'files':{},'models':0,'price_writes':0}
    for p,after in changes.items():
        raw=p.read_bytes();backup=BACKUP/p.name;atomic(backup,raw,0o600)
        receipt['files'][str(p)]={'before':sha(raw),'after':sha(after)}
    atomic(BACKUP/'receipt.json',json.dumps(receipt).encode(),0o600)
    # A brief existing-DB reservation prevents a new dispatch between the idle check and stop.
    with sqlite3.connect('/opt/d4follow/data/iggm_follow.db',timeout=5,isolation_level=None) as database:
        database.execute('BEGIN IMMEDIATE')
        try:
            assert database.execute("SELECT count(*) FROM local_job WHERE status='dispatched'").fetchone()[0]==0
            call(['systemctl','stop','p2pah-srv-exec.service'])
            try:
                with open('/opt/d4follow/data/srv_exec.lock','r+b') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    for p,after in changes.items():
                        assert sha(p.read_bytes())==receipt['files'][str(p)]['before']
                        atomic(p,after,p.stat().st_mode&0o777)
                        assert sha(p.read_bytes())==receipt['files'][str(p)]['after']
            finally:
                database.execute('ROLLBACK')
                call(['systemctl','start','p2pah-srv-exec.service'])
        except BaseException:
            if database.in_transaction:database.execute('ROLLBACK')
            raise
    call(['systemctl','daemon-reload'])
    for name,c in containers.items():
        current=json.loads(call(['docker','inspect',name]))[0]
        assert current['Id']==c['id'] and current['State']['StartedAt']==c['started_at']
        call(['docker','update','--memory',str(c['gib'])+'g','--memory-swap',str(c['gib'])+'g',name])
        current=json.loads(call(['docker','inspect',name]))[0]
        assert current['Id']==c['id'] and current['HostConfig']['Memory']==c['gib']*1024**3
    call(['systemctl','set-property','fs-business-range.service','MemoryLimit=2147483648'])
    assert 'MemoryLimit=2147483648' in call(['systemctl','show','fs-business-range.service','-p','MemoryLimit'])
    receipt.update(status='published_readback_verified',native_range_memory_bytes=2147483648,
                   rpg_worker_memory_bytes=2147483648,shared_containers_restarted=False,verified_at=time.time())
    atomic(BACKUP/'receipt.json',json.dumps(receipt).encode(),0o600)
    print(json.dumps(receipt))


if __name__=='__main__':
    with open('/var/lock/fs-navigation-release.lock','a+b') as a,open('/var/lock/fs-dashboard-release.lock','a+b') as b:
        fcntl.flock(a,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(b,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
