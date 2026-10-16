"""Two existing backend files only; no restarts, task changes or collection."""
import argparse, contextlib, hashlib, json, os, re, stat, subprocess, tempfile, types
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCOPE='game-monitor-news-cards-20261016'
TARGETS={'source/mmoexp_news.py':'/opt/fs-boss-workspaces/backend/mmoexp_news.py',
         'source/game_intelligence.py':'/opt/fs-boss-workspaces/backend/game_intelligence.py'}
NEWS_BASELINE='0450a4d07ca5298a45bb89a4d4548a2c2dc07d526246c55036de7055331046c6'
INTEL_BASELINE='992f2369b5fd0203102bf0d2631a174bdcf0cfe3f4e4eeb199ab5e6cd0219c05'
BOSS='/opt/fs-boss-workspaces/backend/boss_daily.py'
REQUIRED={BOSS,'/opt/fs-boss-workspaces/backend/workspace_official_model.py','/etc/systemd/system/fs-boss-game-monitor.service','/etc/systemd/system/fs-boss-game-monitor.timer'}
BACKUPS='/var/backups/game-monitor-news-cards-20261016'
HASH=re.compile(r'[a-f0-9]{64}')
SHANGHAI=timezone(timedelta(hours=8))

def rooted(root,path):return root/path.lstrip('/')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def today():return datetime.now(SHANGHAI).date().isoformat()

def ownership(info):
    if os.name=='posix' and (info.st_uid!=0 or info.st_mode&0o022):raise ValueError('unsafe root ownership/mode')

def safe(path,required=True):
    for item in (path,*path.parents):
        if item.is_symlink():raise ValueError('symlink boundary: '+str(item))
        if item.exists():
            info=item.stat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)) or (item.is_file() and info.st_nlink!=1):raise ValueError('unsafe file type/link count')
            ownership(info)
    if required and not path.is_file():raise ValueError('existing regular file required: '+str(path))

def sync(path):
    if os.name!='posix':return
    fd=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def atomic(path,payload,mode=0o600):
    safe(path,False)
    fd,name=tempfile.mkstemp(prefix='.news-cards-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(payload);stream.flush()
            os.fchmod(stream.fileno(),mode) if hasattr(os,'fchmod') else os.chmod(name,mode)
            os.fsync(stream.fileno())
        safe(path,False);os.replace(name,path);sync(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)

def validate(manifest):
    files=manifest.get('files',[]);protected=manifest.get('unchangedRequired',[])
    if manifest.get('schemaVersion')!=1 or manifest.get('scope')!=SCOPE or manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:raise ValueError('exact readonly News scope required')
    if len(files)!=2 or {r.get('candidate') for r in files}!=set(TARGETS):raise ValueError('exact two-file allowlist required')
    for row in files:
        if row.get('target')!=TARGETS[row['candidate']] or not all(isinstance(row.get(k),str) and HASH.fullmatch(row[k]) for k in ('beforeSha256','sha256')):raise ValueError('existing target CAS required')
        if row['candidate']=='source/mmoexp_news.py' and row['beforeSha256']!=NEWS_BASELINE:raise ValueError('News baseline differs')
        if row['candidate']=='source/game_intelligence.py' and row['beforeSha256']!=INTEL_BASELINE:raise ValueError('official intelligence baseline differs')
    paths=[r.get('path') for r in protected]
    if any(not isinstance(p,str) or not p.startswith('/') or '..' in p.split('/') or str(Path(p).as_posix())!=p for p in paths) or len(set(paths))!=len(paths) or not REQUIRED.issubset(paths) or set(paths)&set(TARGETS.values()):raise ValueError('protected path boundary differs')
    if any(not isinstance(r.get('sha256'),str) or not HASH.fullmatch(r['sha256']) for r in protected):raise ValueError('protected SHA required')
    return files

def idle():
    result=subprocess.run(['systemctl','show','fs-boss-game-monitor.service','--no-pager','-p','ActiveState','-p','MainPID'],check=True,stdout=subprocess.PIPE,universal_newlines=True)
    if dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)!={'ActiveState':'inactive','MainPID':'0'}:raise ValueError('game monitor busy; defer release')

def guards(manifest,root):
    idle()
    for row in manifest['unchangedRequired']:
        path=rooted(root,row['path']);safe(path)
        if digest(path)!=row['sha256']:raise ValueError('protected source drift: '+row['path'])

def inspect(manifest,stage,root=Path('/')):
    files=validate(manifest);guards(manifest,root)
    for row in files:
        target=rooted(root,row['target']);source=stage/'candidate'/row['candidate']
        safe(target);safe(source)
        if digest(target)!=row['beforeSha256'] or digest(source)!=row['sha256']:raise ValueError('target/staged source CAS drift: '+row['candidate'])
    return {'status':'checked','files':2,'mutations':False}

@contextlib.contextmanager
def locks(manifest,root):
    helper=rooted(root,BOSS);safe(helper)
    payload=helper.read_bytes()
    if hashlib.sha256(payload).hexdigest()!=next(r['sha256'] for r in manifest['unchangedRequired'] if r['path']==BOSS):raise ValueError('boss lock helper drift')
    boss=types.ModuleType('news_cards_boss_lock');exec(compile(payload,str(helper),'exec'),boss.__dict__)
    day=today()
    with contextlib.ExitStack() as stack:
        paths=['/run/lock/fs-navigation-release.lock','/run/lock/fs-dashboard-release.lock',
               '/var/lib/fs-boss-workspaces/locks/game-monitor-'+day+'.lock']
        for name in paths:
            path=rooted(root,name);safe(path,False)
            if not path.parent.is_dir():raise ValueError('existing lock directory required')
            stack.enter_context(boss.file_lock(path))
        yield day

def save(backup,journal):atomic(backup/'journal.json',json.dumps(journal,ensure_ascii=False,indent=2).encode())

def restore(backup,journal,root):
    validate(journal['manifest']);idle()
    for row in journal['files']:
        path=rooted(root,row['target']);saved=backup/Path(row['candidate']).name
        safe(path);safe(saved)
        if digest(saved)!=row['beforeSha256'] or digest(path) not in ({row['beforeSha256'],row['sha256']} if row.get('intent') else {row['beforeSha256']}):raise ValueError('rollback CAS drift; preserve for reconciliation')
    for row in reversed(journal['files']):
        path=rooted(root,row['target'])
        if digest(path)==row['beforeSha256']:continue
        idle();safe(path);payload=(backup/Path(row['candidate']).name).read_bytes()
        if digest(path)!=row['sha256'] or hashlib.sha256(payload).hexdigest()!=row['beforeSha256']:raise ValueError('rollback target/backup drift before replacement')
        row['rollbackIntent']=True;save(backup,journal)
        safe(path)
        if digest(path)!=row['sha256']:raise ValueError('rollback target drift after journaling')
        atomic(path,payload,row['mode']);row['restored']=True;save(backup,journal)
    if any(digest(rooted(root,r['target']))!=r['beforeSha256'] for r in journal['files']):raise ValueError('rollback readback differs')
    journal['status']='rolled-back';save(backup,journal)

def apply(manifest,stage,approved_sha,raw,release_id,root=Path('/')):
    if manifest.get('releaseReady') is not True or hashlib.sha256(raw).hexdigest()!=approved_sha or json.loads(raw)!=manifest:raise ValueError('approved ready manifest bytes required')
    if not re.fullmatch(r'news-cards-[0-9]{8}T[0-9]{6}Z',release_id or ''):raise ValueError('unique news-cards-YYYYMMDDTHHMMSSZ required')
    inspect(manifest,stage,root)
    with locks(manifest,root) as day:
        inspect(manifest,stage,root)
        if today()!=day:raise ValueError('day changed; recheck nightly lock')
        backup=rooted(root,BACKUPS+'/'+release_id);safe(backup,False)
        if backup.exists():raise ValueError('release ID already used; reconcile journal, do not replay')
        backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700);safe(backup.parent,False)
        sync(backup.parent.parent);backup.mkdir(mode=0o700);sync(backup.parent)
        journal={'status':'preparing-backup','approvedManifestSha256':approved_sha,'manifest':manifest,'files':[]}
        atomic(backup/'approved-manifest.json',raw);save(backup,journal)
        try:
            for row in manifest['files']:
                path=rooted(root,row['target']);safe(path)
                if digest(path)!=row['beforeSha256']:raise ValueError('target changed before backup')
                atomic(backup/Path(row['candidate']).name,path.read_bytes())
                if digest(backup/Path(row['candidate']).name)!=row['beforeSha256']:raise ValueError('backup CAS drift')
                journal['files'].append(dict(row,mode=stat.S_IMODE(path.stat().st_mode),intent=False));save(backup,journal)
        except Exception as error:
            journal.update(status='backup-failed-no-target-written',error=str(error))
            try:save(backup,journal)
            except OSError:pass
            raise
        journal['status']='prepared';save(backup,journal)
        try:
            for row in journal['files']:
                guards(manifest,root)
                if today()!=day:raise ValueError('day changed; refuse replacement')
                for current in journal['files']:
                    target=rooted(root,current['target']);safe(target)
                    if digest(target)!=(current['sha256'] if current.get('written') else current['beforeSha256']):raise ValueError('release target set drift')
                path=rooted(root,row['target']);source=stage/'candidate'/row['candidate'];safe(path);safe(source)
                payload=source.read_bytes()
                if digest(path)!=row['beforeSha256'] or hashlib.sha256(payload).hexdigest()!=row['sha256']:raise ValueError('CAS drift before replacement')
                row['intent']=True;save(backup,journal)
                safe(path)
                if digest(path)!=row['beforeSha256']:raise ValueError('target drift after journaling')
                atomic(path,payload,row['mode']);row['written']=True;save(backup,journal)
            guards(manifest,root)
            if any(digest(rooted(root,r['target']))!=r['sha256'] for r in journal['files']):raise ValueError('final target SHA differs')
            journal['status']='applied';save(backup,journal)
        except Exception as error:
            journal.update(status='apply-failed',error=str(error))
            try:save(backup,journal)
            except OSError:pass
            try:restore(backup,journal,root)
            except Exception as rollback_error:
                journal.update(status='rollback-needs-reconciliation',rollbackError=str(rollback_error));save(backup,journal)
                raise RuntimeError('release failed; preserve journal and reconcile exact targets') from rollback_error
            raise
    return {'status':'applied','backup':str(backup),'files':2,'restarts':0,'timerActions':0}

def rollback(backup,approved_sha,root=Path('/')):
    if backup.parent!=rooted(root,BACKUPS) or not re.fullmatch(r'news-cards-[0-9]{8}T[0-9]{6}Z',backup.name):raise ValueError('exact release backup required')
    safe(backup/'approved-manifest.json');safe(backup/'journal.json')
    raw=(backup/'approved-manifest.json').read_bytes();journal=json.loads((backup/'journal.json').read_bytes())
    if hashlib.sha256(raw).hexdigest()!=approved_sha or journal['approvedManifestSha256']!=approved_sha or json.loads(raw)!=journal['manifest']:raise ValueError('approved backup manifest differs')
    files=validate(journal['manifest'])
    if len(journal['files'])!=2 or {r['candidate'] for r in journal['files']}!=set(TARGETS) or any(any(row.get(k)!=value for k,value in next(r for r in files if r['candidate']==row['candidate']).items()) for row in journal['files']):raise ValueError('journal target scope differs')
    idle()
    with locks(journal['manifest'],root):restore(backup,journal,root)
    return {'status':journal['status'],'restarts':0,'timerActions':0}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','apply','rollback'],nargs='?',default='inspect')
    parser.add_argument('--manifest',type=Path,default=Path(__file__).with_name('approved-manifest.json'));parser.add_argument('--approved-manifest-sha');parser.add_argument('--release-id');parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    if args.action!='inspect' and (os.name!='posix' or os.geteuid()!=0):raise ValueError('mutations require root on reviewed Linux')
    if args.action=='rollback':
        if args.backup is None:parser.error('--backup is required for rollback')
        result=rollback(args.backup,args.approved_manifest_sha)
    else:
        raw=args.manifest.read_bytes();manifest=json.loads(raw)
        result=inspect(manifest,args.manifest.parent) if args.action=='inspect' else apply(manifest,args.manifest.parent,args.approved_manifest_sha,raw,args.release_id)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
