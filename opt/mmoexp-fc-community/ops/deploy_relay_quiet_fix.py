"""Small relay hotfix: backup, require intent, replace two files, restart once."""
import hashlib,json,os,shutil,sqlite3,subprocess,sys,time
from pathlib import Path
BASE=Path('/opt/mmoexp-fc-community')
STAGE=Path('/opt/mmoexp-fc-relay-fix-20261108')
sys.path.insert(0,'/opt/mmoexp-fc-news-stage-20261108-core')
from discord_ops import request
expected={'quote_relay.py':'ad81b6f1be88834c4f54af1a6bb4303536e5a16661528b1d76ef6cd504f32279','content_bot.py':'79f276ac73adf5597942bb7f552a05ccffd0cd177ee972b30142133e9b6d091b'}
flags=request('GET','oauth2/applications/@me').get('flags',0)
config=json.loads((BASE/'content.config.json').read_text())
if config.get('quote_relay',{}).get('content_filter') and not flags & ((1<<18)|(1<<19)):
    raise SystemExit('Message Content Intent must be enabled before deployment')
for name,sha in expected.items():
    if hashlib.sha256((BASE/name).read_bytes()).hexdigest()!=sha:
        raise SystemExit('Live source drift: '+name)
backup=BASE/'backups'/('relay-quiet-'+str(int(time.time())))
backup.mkdir()
for name in expected: shutil.copy2(BASE/name,backup/name)
subprocess.run(['systemctl','stop','mmoexp-fc-community'],check=True)
try:
    dbpath=BASE/'var'/'quote-relay.sqlite3'
    with sqlite3.connect(dbpath) as db, sqlite3.connect(backup/'quote-relay.sqlite3') as saved:
        db.backup(saved)
        # Old pending entries may be plain subscription acknowledgments. Preserve highwater/claims.
        db.execute('UPDATE relay_state SET pending_id=NULL,pending_kind=NULL,due_at=NULL')
    for name in expected:
        dst=BASE/name; tmp=BASE/(name+'.new')
        shutil.copy2(STAGE/name,tmp); os.chown(tmp,dst.stat().st_uid,dst.stat().st_gid); os.replace(tmp,dst)
    subprocess.run(['systemctl','start','mmoexp-fc-community'],check=True)
except BaseException:
    for name in expected: shutil.copy2(backup/name,BASE/name)
    subprocess.run(['systemctl','start','mmoexp-fc-community'],check=True)
    raise
print(json.dumps({'backup':str(backup),'sha256':{n:hashlib.sha256((BASE/n).read_bytes()).hexdigest() for n in expected}}))
