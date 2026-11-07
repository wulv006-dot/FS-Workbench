"""Deploy the reviewed news release; preserve publication records on rollback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

BOT = Path('/opt/mmoexp-fc-community')
FS = Path('/opt/bot-console')
BEFORE = {
    str(BOT/'content_bot.py'): '8d05739924348cf5424dce9c2fcd6978f38ec20bc46a698daa836a550c804e56',
    str(BOT/'news_feed.py'): '0e27de455688f473b19f675ffe2428b7e4d15479ef026880398f960908dc71a5',
    str(FS/'server.py'): '6a78c91f5e3e6e9c5e24242d4bcff93ad984cfd25092f01959ad6ae317134013',
    str(FS/'static/fc27.html'): '8cdf84b321c12f64acddf01950a81785d13c9179fd29803ab685a04236b7a760',
}

def run(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise RuntimeError('Command failed: '+args[0])
    return p.stdout.strip()

def atomic(path, data, reference=None):
    st = (path if path.exists() else reference).stat()
    fd, name = tempfile.mkstemp(prefix='.news-release-', dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chown(name,st.st_uid,st.st_gid); os.chmod(name,st.st_mode & 0o777)
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def main():
    if len(sys.argv)!=3 or sys.argv[2]!='--release-reviewed':
        raise SystemExit('Usage: deploy_news_center.py STAGE --release-reviewed')
    stage=Path(sys.argv[1]).resolve()
    if not str(stage).startswith('/opt/mmoexp-fc-news-stage-'):
        raise SystemExit('Invalid isolated stage')
    files={BOT/n: stage/'mmoexp-fc-pilot'/n for n in ('news_feed.py','content_bot.py','collector_router.py')}
    files.update({FS/'server.py':stage/'fs-console-fc/candidate/server.py', FS/'static/fc27.html':stage/'fs-console-fc/candidate/static/fc27.html'})
    for name,expected in BEFORE.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected: raise RuntimeError('Production drift: '+name)
    manifest=json.loads((stage/'reviewed-manifest.json').read_text())
    for destination,source in files.items():
        if hashlib.sha256(source.read_bytes()).hexdigest()!=manifest[str(source.relative_to(stage))]: raise RuntimeError('Candidate drift')
    cfgpath=BOT/'content.config.json'; envpath=Path('/etc/mmoexp-fc-community.env')
    original_cfg=cfgpath.read_bytes(); original_env=envpath.read_bytes()
    cfg=json.loads(original_cfg)
    if cfg['news_publish']['poll_seconds']!=21600: raise RuntimeError('News schedule changed')
    cfg['news_publish']['collector']='auto'
    sys.path.insert(0,str(stage/'mmoexp-fc-pilot'))
    from content_bot import validate_config
    validate_config(cfg)
    additions={'FC27_NEWS_SSH_KEY':'/etc/mmoexp-fc-news/collector_ed25519','FC27_NEWS_KNOWN_HOSTS':'/etc/mmoexp-fc-news/known_hosts'}
    if not all(Path(v).is_file() for v in additions.values()): raise RuntimeError('Remote route not installed')
    lines=[line for line in original_env.decode().splitlines() if not any(line.startswith(k+'=') for k in additions)]
    env=('\n'.join(lines+[k+'='+v for k,v in additions.items()])+'\n').encode()
    originals={path:path.read_bytes() if path.exists() else None for path in files}
    markers={p:p.read_bytes() for p in (BOT/'var').glob('*panel*.json')}
    backup=BOT/'backups'/('news-center-'+str(int(time.time())))
    backup.mkdir(mode=0o700)
    for i,(path,data) in enumerate(originals.items()):
        if data is not None: (backup/(str(i)+'-'+path.name)).write_bytes(data)
    (backup/'content.config.json').write_bytes(original_cfg)
    (backup/'community.env').write_bytes(original_env)
    changed=False
    try:
        run('systemctl','stop','bot-console','mmoexp-fc-community')
        if cfgpath.read_bytes()!=original_cfg or envpath.read_bytes()!=original_env: raise RuntimeError('Configuration drift')
        with sqlite3.connect(str(BOT/'var/news.sqlite3')) as src, sqlite3.connect(str(backup/'news.sqlite3')) as dst: src.backup(dst)
        changed=True
        for destination,source in files.items(): atomic(destination,source.read_bytes(),BOT/'news_feed.py')
        atomic(cfgpath,(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode())
        atomic(envpath,env)
        from news_feed import NewsStore
        NewsStore(BOT/'var/news.sqlite3')  # Migrate once with both writers stopped.
        run('systemctl','start','mmoexp-fc-community','bot-console')
        for _ in range(45):
            pid=int(run('systemctl','show','mmoexp-fc-community','-p','MainPID').split('=')[1])
            ready=json.loads((BOT/'var/ready.json').read_text())
            if ready.get('connected') and ready.get('pid')==pid and ready.get('test_guild_present'): break
            time.sleep(1)
        else: raise RuntimeError('Bot readiness failed')
        run('systemctl','is-active','bot-console','mmoexp-fc-community','mmoexp-fc-quotes')
        if any(p.read_bytes()!=b for p,b in markers.items()): raise RuntimeError('Panel markers changed')
        result={'status':'ready','backup':str(backup),'pid':pid,'collector':'auto','poll_hours':6,'markers_unchanged':True,'files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    except Exception:
        if changed:
            run('systemctl','stop','bot-console','mmoexp-fc-community')
            for path,data in originals.items():
                if data is not None: atomic(path,data)
            atomic(cfgpath,original_cfg); atomic(envpath,original_env)
            # Never restore an old DB after a send: that could duplicate messages.
        run('systemctl','start','mmoexp-fc-community','bot-console')
        raise
    (stage/'deployment.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))

if __name__=='__main__': main()
