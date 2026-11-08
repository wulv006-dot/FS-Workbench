"""Narrow WoW release helper: backup/CAS/atomic copy; never restore a database."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

ROOT=Path('/opt/d4follow')
STAGE=ROOT/'release_wow_dual_20261108'
BACKUP=ROOT/'backup_wow_dual_20261108'
FILES=('core_wow_gold.py','core_wow_sources.py','wow_gold_apply.py','wow_gold_config.json')
BASELINE={'core_wow_gold.py':'b8d94e8e99e00d0e1f1d2471913a848157673e55a78ab0771eed97f0ee642f9a',
          'wow_gold_apply.py':'65f997276442c45f5fb0ab4644839994c7fa05051e15dcbde279c1082c757dcc',
          'wow_gold_config.json':'920b3005b197d92ce86daf1a7697c3f2d53bf3b9417d7247c46f78e98a20b517'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def active(name):return subprocess.run(['systemctl','is-active','--quiet',name]).returncode==0
def cmd(*args):subprocess.run(args,check=True)
def no_pending():
    db=sqlite3.connect('file:/opt/d4follow/data/iggm_follow.db?mode=ro',uri=True)
    rows=db.execute("SELECT id,status FROM local_job WHERE kind='writegold' AND title LIKE '%WoW Forever%' AND status IN ('pending','dispatched')").fetchall()
    assert not rows,('in-flight WoW jobs',rows)
def atomic(src,dst):
    tmp=dst.with_name(dst.name+'.wow-dual-publish')
    shutil.copy2(src,tmp)
    os.chmod(tmp,0o644)
    os.replace(tmp,dst)
def main(mode):
    assert mode in ('publish','rollback')
    was_active=active('wow-gold-follow.timer')
    cmd('systemctl','stop','wow-gold-follow.timer')
    try:
        assert not active('wow-gold-follow.service'),'existing WoW round still active'
        no_pending()
        if mode=='publish':
            assert not BACKUP.exists(),'backup already exists; inspect before retry'
            for name,digest in BASELINE.items():assert sha(ROOT/name)==digest,('baseline drift',name)
            assert not (ROOT/'core_wow_sources.py').exists(),'new module unexpectedly exists'
            trial=json.loads((STAGE/'trial_result.json').read_text())
            assert trial['hardcore']==8 and trial['priced']>0
            # Final backend values for per-row price rollback, reusing current session.
            sys.path.insert(0,str(ROOT));sys.path.insert(0,'/opt/fs-order-session')
            import core_wow_gold as old
            from core_p2pah import P2PAHClient
            client=P2PAHClient(json.loads((ROOT/'config.json').read_text()),log=lambda *a:None)
            assert client.login(),'backend session unavailable'
            values=old.read_backend_rows(client,old.load_cfg(),log=lambda *a:None)
            assert len(values)==40
            BACKUP.mkdir(mode=0o700)
            for name in BASELINE:shutil.copy2(ROOT/name,BACKUP/name)
            manifest={'time':dt.datetime.now().isoformat(),'timer_was_active':was_active,
                      'before':BASELINE,'after':{n:sha(STAGE/n) for n in FILES}}
            (BACKUP/'manifest.json').write_text(json.dumps(manifest,indent=2))
            (BACKUP/'backend_rows_before.json').write_text(json.dumps(values,ensure_ascii=False,indent=1))
            done=[]
            try:
                for name in FILES:atomic(STAGE/name,ROOT/name);done.append(name)
            except Exception:
                for name in done:
                    if (BACKUP/name).exists():atomic(BACKUP/name,ROOT/name)
                raise
            print('PUBLISHED',json.dumps(manifest),flush=True)
            # Keep only the WoW timer stopped until the first real batch is read back.
            print('NEXT: systemctl start wow-gold-follow.service; verify writer receipt; start timer',flush=True)
        else:
            manifest=json.loads((BACKUP/'manifest.json').read_text())
            for name in FILES:assert sha(ROOT/name)==manifest['after'][name],('post-release drift',name)
            for name in BASELINE:atomic(BACKUP/name,ROOT/name)
            # New source module remains unused for audit; no file/database deletion.
            if manifest['timer_was_active']:cmd('systemctl','start','wow-gold-follow.timer')
            print('ROLLED_BACK_CODE_CONFIG; price snapshots retained for original writer',flush=True)
    except Exception:
        if was_active:cmd('systemctl','start','wow-gold-follow.timer')
        raise
if __name__=='__main__':main(sys.argv[1])
