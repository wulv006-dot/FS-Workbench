"""Single-change release/rollback. Reuses FS release locks, preserves all runtime data."""
import fcntl,hashlib,json,os,pwd,shutil,subprocess,sys,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
APP=Path('/opt/mmoexp-lucky-loot')
CONSOLE=Path('/opt/bot-console')
UNIT=Path('/etc/systemd/system/mmoexp-lucky-loot.service')
MANIFEST=HERE/'release-receipt.json'

def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,data,mode=0o644):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.loot-')
    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.chmod(tmp,mode);os.replace(tmp,p)

def main(action):
    locks=[]
    for name in ('fs-navigation-release.lock','fs-dashboard-release.lock','bot-console-release.lock'):
        f=open('/var/lock/'+name,'a+b');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(f)
    if action=='rollback':
        receipt=json.loads(MANIFEST.read_text())
        for item in receipt['existing']:
            if sha(item['target'])!=item['after']:raise RuntimeError('Post-release drift: '+item['target'])
        run('systemctl','stop','mmoexp-lucky-loot')
        flag=Path('/etc/mmoexp-lucky-loot/enabled')
        if flag.exists():flag.rename(flag.with_name('paused'))
        for item in receipt['existing']:write(item['target'],Path(item['backup']).read_bytes())
        run('nginx','-t');run('systemctl','reload','nginx');run('systemctl','restart','bot-console')
        print(json.dumps({'rolled_back':True,'data_preserved':True}));return
    if MANIFEST.exists():raise RuntimeError('Release already applied; do not replay')
    expected=json.loads((HERE/'baseline-hashes.json').read_text())
    for target,digest in expected.items():
        if sha(target)!=digest:raise RuntimeError('Baseline changed: '+target)
    backup=HERE/'backup';backup.mkdir(mode=0o700,exist_ok=True)
    existing=[]
    for target,digest in expected.items():
        dest=backup/Path(target).name;shutil.copy2(target,dest)
        existing.append({'target':target,'before':digest,'backup':str(dest)})
    try:account=pwd.getpwnam('luckyloot')
    except KeyError:
        run('useradd','--system','--no-create-home','--shell','/sbin/nologin','luckyloot');account=pwd.getpwnam('luckyloot')
    for name in ('/etc/mmoexp-lucky-loot','/var/lib/mmoexp-lucky-loot'):
        p=Path(name);p.mkdir(mode=0o700,exist_ok=True);os.chmod(p,0o700);os.chown(p,account.pw_uid,account.pw_gid)
    key=Path('/etc/mmoexp-lucky-loot/data.key')
    if not key.exists():write(key,os.urandom(32),0o600);os.chown(key,account.pw_uid,account.pw_gid)
    APP.mkdir(mode=0o755,exist_ok=True)
    for file in (HERE/'src').iterdir():
        if file.is_file():write(APP/file.name,file.read_bytes())
    run('npm','ci','--ignore-scripts','--omit=dev','--no-audit','--no-fund','--prefix',str(APP))
    for name in ('app.cjs','core.cjs','store.cjs','coupon.cjs'):run('node','--check',str(APP/name))
    for name in ('giveaway.html','giveaway.js','giveaway.css'):write(CONSOLE/'static'/name,(HERE/'src'/name).read_bytes())
    write(CONSOLE/'lucky_proxy.py',(HERE/'src/lucky_proxy.py').read_bytes())
    write(UNIT,(HERE/'src/mmoexp-lucky-loot.service').read_bytes())
    server=(CONSOLE/'server.py').read_text()
    anchor='        query = urllib.parse.parse_qs(parsed.query)\n'
    if server.count(anchor)!=1:raise RuntimeError('Route anchor mismatch')
    server=server.replace(anchor,anchor+'\n        from lucky_proxy import handle as lucky_handle\n        if lucky_handle(self, method, path, query):\n            return\n',1)
    index=(CONSOLE/'static/index.html').read_text()
    anchor='<button id="btnRefresh">刷新</button>'
    if index.count(anchor)!=1:raise RuntimeError('UI anchor mismatch')
    index=index.replace(anchor,'<a href="giveaway.html" style="font-weight:600">🎁 幸运抽奖</a>\n  '+anchor,1)
    nginx=Path('/etc/nginx/bot-console.locations.conf').read_text()
    nginx+='\n# Lucky Loot: public policy only; no API or private data.\nlocation = /lucky-loot/privacy {\n    alias /opt/mmoexp-lucky-loot/privacy.html;\n    default_type text/html;\n    add_header X-Content-Type-Options nosniff;\n}\n'
    try:
        write(CONSOLE/'server.py',server.encode());write(CONSOLE/'static/index.html',index.encode());write('/etc/nginx/bot-console.locations.conf',nginx.encode())
        run('/opt/bot-console/venv/bin/python','-m','py_compile',str(CONSOLE/'server.py'),str(CONSOLE/'lucky_proxy.py'))
        run('nginx','-t')
        write('/etc/mmoexp-lucky-loot/enabled',b'1\n')
        run('systemctl','daemon-reload');run('systemctl','enable','mmoexp-lucky-loot');run('systemctl','start','mmoexp-lucky-loot')
        run('systemctl','restart','bot-console');run('systemctl','reload','nginx')
        for item in existing:item['after']=sha(item['target'])
        write(MANIFEST,json.dumps({'existing':existing,'new_app':str(APP),'runtime_preserved':['/etc/mmoexp-lucky-loot','/var/lib/mmoexp-lucky-loot'],'files':{p.name:sha(p) for p in APP.iterdir() if p.is_file()}},indent=2).encode(),0o600)
        print(json.dumps({'deployed':True,'service':run('systemctl','is-active','mmoexp-lucky-loot').strip(),'console':run('systemctl','is-active','bot-console').strip()}))
    except Exception:
        for item in existing:write(item['target'],Path(item['backup']).read_bytes())
        subprocess.run(['systemctl','stop','mmoexp-lucky-loot'])
        flag=Path('/etc/mmoexp-lucky-loot/enabled')
        if flag.exists():flag.rename(flag.with_name('paused'))
        subprocess.run(['systemctl','restart','bot-console']);subprocess.run(['nginx','-t']);subprocess.run(['systemctl','reload','nginx']);raise

if __name__=='__main__':main(sys.argv[1])
