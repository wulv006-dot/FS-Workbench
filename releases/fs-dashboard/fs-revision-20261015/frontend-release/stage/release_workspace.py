"""Narrow native workspace publisher; inspection is read-only by default.

Reuse reviewed navigation atomic/locks and formal ownership/runtime guards.
Only 14 immutable files, homepage HTML and the existing formal fragment are written.
"""
import argparse, hashlib, json, os, re, stat, subprocess
from pathlib import Path
from release_navigation import atomic, digest, locks, directory_sync, retirement

HERE = Path(__file__).resolve().parent
BACKUPS = '/var/backups/fs-navigation-native-20261006'
HOME = '/var/www/dashboard/fs-home/index.html'
FRAGMENT = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
NAVIGATION = '/var/www/dashboard/fs-home/navigation.js'
MUTABLE = ('/var/www/dashboard/fs-home/index.html', '/var/www/dashboard/fs-home/navigation.js', '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', '/etc/nginx/release-radar.locations.conf')
NAMES = {'legacy-business.js', 'game-monitor/assets/game-tools/d4-tool-builds.jpg', 'game-monitor/assets/covers/wow-classic-20.jpg', 'game-monitor/assets/game-tools/tool-runeapps.jpg', 'game-monitor/assets/covers/dreadmyst.jpg', 'game-monitor/assets/covers/elden-ring.jpg', 'advisor.html', 'game-monitor/assets/game-tools/tool-aion2nc.jpg', 'game-monitor/assets/game-tools/tool-steamdb.jpg', 'management/mlb26.html', 'game-monitor/assets/covers/ea-sports-fc.jpg', 'game-monitor/assets/covers/dune-awakening.jpg', 'game-monitor/assets/game-tools/tool-runelite.jpg', 'game-monitor/assets/game-tools/fc-official-ea.jpg', 'game-monitor/assets/game-tools/tool-getracker.jpg', 'game-monitor/assets/ea-sports-fc/fc27_scene_war.jpg', 'game-monitor/assets/aion2/aion2_logo_art.jpg', 'game-monitor/assets/game-tools/fc-tool-futgg.jpg', 'game-monitor/assets/covers/helldivers-2.jpg', 'game-monitor/assets/game-tools/tool-daddy.jpg', 'game-monitor/fs-integration.js', 'game-monitor/assets/game-tools/poe-tool-trade.jpg', 'game-monitor/assets/game-tools/tool-maxroll.jpg', 'game-monitor/assets/game-tools/d4-tool-maxroll.jpg', 'game-monitor/assets/game-tools/fc-tool-futbin.jpg', 'google.js', 'snapshot-client.js', 'google.html', 'game-monitor/assets/game-tools/tool-diablotrade.jpg', 'game-monitor/assets/game-tools/tool-poe2db.jpg', 'game-monitor/assets/covers/skull-and-bones.jpg', 'management/dark_and_darker.html', 'game-monitor/assets/covers/aion2.jpg', 'game-monitor/assets/covers/diablo-2-resurrected.jpg', 'business.html', 'game-monitor/assets/game-tools/tool-feztra.jpg', 'game-monitor/assets/game-tools/tool-poeninja.jpg', 'google.css', 'management/nfl27.html', 'game-monitor/assets/game-tools/tool-madtools.jpg', 'runtime.js', 'game-monitor/assets/game-tools/tool-tsn.jpg', 'game-monitor/assets/game-tools/tool-steam.jpg', 'game-monitor/assets/diablo4/diablo4_scene_war.jpg', 'management/wow_forever.html', 'game-monitor/assets/game-tools/tool-helltides.jpg', 'management/arena_breakout_infinite.html', 'management/d4.html', 'game-monitor/assets/game-tools/tool-fandom.jpg', 'game-monitor/index.html', 'game-monitor/assets/game-tools/tool-mapgenie.jpg', 'game-monitor/assets/covers/nba-2k.jpg', 'game-monitor/assets/poe2/poe2_scene_war.jpg', 'game-monitor/assets/game-tools/tool-tgw.jpg', 'management/poe2.html', 'business.js', 'game-monitor/assets/covers/mistfall-hunter.jpg', 'game-monitor/assets/covers/raven-2.jpg', 'navigation.json', 'game-monitor/assets/aion2/aion2_key_art.jpg', 'game-monitor/assets/game-tools/tool-craftofexile.jpg', 'game-monitor/assets/game-tools/tool-poedb.jpg', 'game-monitor/assets/game-tools/tool-futwiz.jpg', 'game-monitor/assets/game-tools/tool-mutgg.jpg', 'game-monitor/assets/game-tools/tool-cffut.jpg', 'game-monitor/assets/covers/odin-valhalla-rising.jpg', 'game-monitor/assets/game-tools/tool-pobb.jpg', 'game-monitor/assets/game-tools/fc-tool-futwiz.jpg', 'game-monitor/fs-integration.css', 'game-monitor/assets/game-tools/d4-tool-helltides.jpg', 'game-monitor/assets/game-tools/tool-futhead.jpg', 'management/maplestory_classic.html', 'game-monitor/assets/game-tools/tool-embedded.jpg', 'game-monitor/assets/ea-sports-fc/fc27_hero_wide.jpg', 'game-monitor/assets/covers/runescape.jpg', 'game-monitor/assets/game-tools/tool-osrswiki.jpg', 'game-monitor/assets/game-tools/poe-tool-wiki.jpg', 'game-monitor/assets/covers/diablo4.jpg', 'game-monitor/assets/game-tools/tool-aion2app.jpg', 'management/aion2.html', 'game-monitor/assets/covers/arc-raiders.jpg', 'management/management.js', 'game-monitor/assets/game-tools/tool-poeregex.jpg', 'game-monitor/assets/covers/wow-forever.jpg', 'game-monitor/assets/covers/college-football-26.jpg', 'game-monitor/assets/game-tools/tool-fifaindex.jpg', 'game-monitor/assets/covers/poe1.jpg', 'game-monitor/assets/game-tools/tool-purple.jpg', 'game-monitor/assets/covers/poe2.jpg', 'shell.js', 'game-monitor/assets/covers/college-football-27.jpg', 'management/index.html', 'game-monitor/assets/game-tools/tool-poewiki.jpg', 'management/management.css', 'game-monitor/assets/game-tools/tool-codtracker.jpg', 'game-monitor/assets/game-tools/tool-dndmarket.jpg', 'game-monitor/assets/game-tools/tool-futbin.jpg', 'game-monitor/assets/game-tools/tool-madden.jpg', 'game-monitor/assets/covers/black-ops-7.jpg', 'business.css', 'management/sandbox.js', 'management/rs.html', 'management/cod_bo7.html', 'game-monitor/assets/game-tools/tool-showzone.jpg', 'management/sandbox.html', 'game-monitor/assets/game-tools/tool-poeplanner.jpg', 'index.html', 'management/fc27.html', 'game-monitor/assets/covers/maplestory.jpg', 'game-monitor/assets/covers/dark-and-darker.jpg', 'game-monitor/assets/covers/mlb-the-show-26.jpg', 'game-monitor/assets/covers/madden-nfl.jpg', 'game-monitor/assets/ea-sports-fc/fc27_banner_wide.jpg', 'game-monitor/assets/game-tools/tool-rswiki.jpg', 'game-monitor/assets/game-tools/tool-ea.jpg', 'game-monitor/assets/covers/gta6.jpg', 'game-monitor/daily.js', 'game-monitor/assets/game-tools/d4-tool-trade.jpg', 'game-monitor/assets/aion2/aion2_gamplay.jpg', 'management/arc_raiders.html', 'management/cfb27.html', 'game-monitor/assets/game-tools/tool-d4builds.jpg', 'management/targets.json', 'game-monitor/assets/game-tools/tool-filterblade.jpg', 'metrics.js', 'management/nba2k27.html', 'workspace.css', 'weekly-legacy.html', 'game-monitor/assets/covers/arena-breakout-infinite.jpg', 'game-monitor/assets/game-tools/poe-tool-db.jpg', 'game-monitor/assets/covers/wow-tbc-classic-anniversary.jpg', 'game-monitor/assets/game-tools/tool-futgg.jpg', 'game-monitor/assets/covers/legend-of-ymir.jpg', 'game-monitor/assets/game-tools/poe-tool-ninja.jpg', 'home.html', 'game-monitor/assets/game-tools/tool-diablofans.jpg', 'game-monitor/assets/game-tools/tool-snb.jpg', 'game-monitor/assets/game-tools/tool-d4armory.jpg', 'game-monitor/assets/aion2/aion2_scene_war.jpg'}
CONTRACT_SHA = '1e789b3bdbc8fa60db9e8c02880f7268b79712e7bae42c3a08ed5c0d9115a626'
hashed = lambda data: hashlib.sha256(data).hexdigest()
at = lambda root,name: root / str(name).lstrip('/')

def trusted(path,root):
    for p in (path,*path.parents):
        if p.is_symlink():raise ValueError('Linked writable boundary: '+str(p))
        if p.exists():
            s=p.stat()
            if s.st_uid!=0 or s.st_gid!=0 or stat.S_IMODE(s.st_mode)&0o022 or not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)) or (stat.S_ISREG(s.st_mode) and s.st_nlink!=1):
                raise ValueError('Unsafe ownership/type: '+str(p))
        if p==root:break

def validate(m,stage):
    if digest(HERE/'release-contract.json')!=CONTRACT_SHA:raise ValueError('Frozen release contract SHA differs')
    contract=json.loads((HERE/'release-contract.json').read_text(encoding='utf-8'))
    actual=dict(m);actual['releaseReady']=False
    if actual!=contract:raise ValueError('Exact frozen release contract differs')
    if not re.fullmatch(r'workspace-native-20261006-[a-f0-9]{12}',m['releaseId']):raise ValueError('Fixed release identifier required')
    rows=m['immutableAssets'];prefix='/var/lib/fs-navigation-formal-static/'+m['releaseId']+'/'
    if len(rows)!=len(NAMES) or {r['candidate'][7:] for r in rows}!=NAMES:raise ValueError('Exact frozen assets required')
    for r in rows:
        name=r['candidate'][7:]
        if r['candidate']!='assets/'+name or r['target']!=prefix+name or r['url']!='/dashboard/workspace-assets/'+m['releaseId']+'/'+name or r['beforeSha256'] is not None:raise ValueError('Asset path differs')
    if len(m['targets'])!=4 or {r['target'] for r in m['targets']}!=set(MUTABLE):raise ValueError('Exact frozen mutable targets required')
    if stage:
        for r in rows+m['targets']:
            source=stage/r['candidate'];trusted(source,stage)
            if digest(source)!=r['sha256']:raise ValueError('Staged bytes drift: '+r['candidate'])
        if {p.relative_to(stage/'assets').as_posix() for p in (stage/'assets').rglob('*') if p.is_file()}!=NAMES:raise ValueError('Extra/missing staged asset')
    return rows+m['targets']

def guards(m,root):
    for r in m['unchangedRequired']:
        if digest(at(root,r['path']))!=r['sha256']:raise ValueError('Protected source drift: '+r['path'])
    state=at(root,'/var/lib/fs-dashboard-release')
    if (state/'pending.json').exists():raise ValueError('Unresolved business pending; preserve')
    ledger=json.loads((state/'current.json').read_text(encoding='utf-8'))
    for key in ('releaseId','version','sha256','publishedAt'):
        if ledger.get(key)!=m['requiredBusinessLedger'][key]:raise ValueError('Business ledger advanced: '+key)
    retirement(root)

def pending(root):return at(root,BACKUPS+'/pending.json')

def inspect(m,stage,root=Path('/')):
    rows=validate(m,stage);guards(m,root)
    if pending(root).exists():raise ValueError('Unresolved native publication pending; no blind retry')
    folder=at(root,'/var/lib/fs-navigation-formal-static/'+m['releaseId']);trusted(folder,root)
    if folder.exists():raise ValueError('Immutable version already exists; no overwrite/reuse')
    for r in rows:
        p=at(root,r['target']);trusted(p,root)
        if digest(p)!=r['beforeSha256']:raise ValueError('Target baseline drift: '+r['target'])
    return dict(passed=True,releaseReady=m['releaseReady'],assets=len(NAMES),mutableTargets=len(MUTABLE),protectedPaths=len(m['unchangedRequired']),productionWrites=0)

def runtime(argv):
    result=subprocess.run(argv,capture_output=True,text=True,timeout=40)
    if result.returncode:raise RuntimeError('Command failed: '+' '.join(argv)+'; '+result.stderr[-1800:])
    return dict(argv=argv,returncode=result.returncode)

def journal_write(backup,j):atomic(backup/'journal.json',json.dumps(j,indent=2).encode(),0o600)

def assert_current(j,root):
    guards(j['manifest'],root)
    for r in j['files']:
        p=at(root,r['target']);trusted(p,root)
        allowed={r['beforeSha256'],r['sha256']} if r.get('intent') else {r['beforeSha256']}
        if digest(p) not in allowed:raise ValueError('Peer target drift; preserve journal: '+r['target'])

def restore(backup,j,root):
    mark=pending(root)
    if mark.exists() and json.loads(mark.read_text()).get('backup')!=str(backup):raise ValueError('Pending belongs to a peer; preserve before any restore')
    validate(j['manifest'],None);assert_current(j,root)
    # Validate every mutable backup before the first restoration.
    mutable=[r for r in j['files'] if r['target'] in MUTABLE]
    for r in mutable:
        trusted(backup/'original'/Path(r['candidate']).name,root)
        if digest(backup/'original'/Path(r['candidate']).name)!=r['beforeSha256']:raise ValueError('Original backup differs')
    for r in reversed(mutable):
        assert_current(j,root)
        p=at(root,r['target'])
        if r.get('intent') and digest(p)==r['sha256']:
            atomic(p,(backup/'original'/Path(r['candidate']).name).read_bytes(),r['mode'])
    if j.get('activationAttempted'):
        assert_current(j,root);runtime(['nginx','-t'])
        assert_current(j,root);runtime(['systemctl','reload','nginx'])
    assert_current(j,root)
    if any(digest(at(root,r['target']))!=r['beforeSha256'] for r in mutable):raise ValueError('Restore verification failed')
    j['status']='rolled-back-immutable-history-retained';journal_write(backup,j)
    mark=pending(root)
    if mark.exists():
        saved=json.loads(mark.read_text())
        if saved.get('backup')!=str(backup):raise ValueError('Pending belongs to a peer; preserve')
        mark.unlink();directory_sync(mark.parent)

def apply(m,stage,raw,approval,root=Path('/')):
    if m.get('releaseReady') is not True or hashed(raw)!=approval:raise ValueError('Reviewed ready manifest SHA required')
    with locks(root):
        inspect(m,stage,root)
        backup=at(root,BACKUPS+'/'+m['releaseId']);trusted(backup,root)
        if backup.exists():raise ValueError('Release backup already exists; refuse retry')
        backup.mkdir(parents=True,mode=0o700);directory_sync(backup.parent)
        atomic(backup/'approved-manifest.json',raw,0o600)
        rows=[]
        for r in m['immutableAssets']+m['targets']:
            p=at(root,r['target']);record={**r,'mode':stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o644,'intent':False}
            if r['target'] in MUTABLE:
                data=p.read_bytes()
                if hashed(data)!=r['beforeSha256']:raise ValueError('Before-backup CAS drift')
                atomic(backup/'original'/Path(r['candidate']).name,data,0o600)
            rows.append(record)
        j=dict(manifest=m,approvedManifestSha256=approval,files=rows,status='prepared',activationAttempted=False)
        journal_write(backup,j)
        trusted(pending(root),root)
        atomic(pending(root),json.dumps({'backup':str(backup),'approvedManifestSha256':approval}).encode(),0o600)
        try:
            # Version assets first, then fragment activation, homepage last.
            ordered=[r for r in rows if r['target']!=HOME]
            for r in ordered:
                assert_current(j,root);p=at(root,r['target'])
                if digest(p)!=r['beforeSha256']:raise ValueError('Before-rename CAS drift')
                data=(stage/r['candidate']).read_bytes()
                if hashed(data)!=r['sha256']:raise ValueError('Stage changed before rename')
                r['intent']=True;journal_write(backup,j);atomic(p,data,r['mode'])
            assert_current(j,root);runtime(['nginx','-t'])
            j['activationAttempted']=True;journal_write(backup,j)
            assert_current(j,root);runtime(['systemctl','reload','nginx'])
            r=next(r for r in rows if r['target']==HOME)
            assert_current(j,root)
            if digest(at(root,HOME))!=r['beforeSha256']:raise ValueError('Home CAS drift')
            data=(stage/r['candidate']).read_bytes()
            if hashed(data)!=r['sha256']:raise ValueError('Home stage drift')
            r['intent']=True;journal_write(backup,j);atomic(at(root,HOME),data,r['mode'])
            assert_current(j,root)
            if any(digest(at(root,r['target']))!=r['sha256'] for r in rows):raise ValueError('Final target SHA mismatch')
            j['status']='applied-awaiting-real-desktop-URL-QA';journal_write(backup,j)
            pending(root).unlink();directory_sync(pending(root).parent)
        except Exception as error:
            j['failure']=str(error)
            try:journal_write(backup,j)
            except OSError:pass
            restore(backup,j,root)
            raise
    return dict(status=j['status'],backup=str(backup),businessAuthCollectorTimerWrites=0)

def rollback(backup,approval,root=Path('/')):
    trusted(backup,root);trusted(backup/'approved-manifest.json',root);trusted(backup/'journal.json',root);raw=(backup/'approved-manifest.json').read_bytes()
    j=json.loads((backup/'journal.json').read_text())
    if hashed(raw)!=approval or j['approvedManifestSha256']!=approval or json.loads(raw)!=j['manifest']:raise ValueError('Rollback approved manifest differs')
    with locks(root):restore(backup,j,root)
    return dict(status=j['status'],backup=str(backup),immutableHistoryRetained=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['inspect','apply','rollback'],nargs='?',default='inspect')
    p.add_argument('--manifest',type=Path,default=HERE/'release-manifest.json');p.add_argument('--approved-manifest-sha');p.add_argument('--backup',type=Path)
    a=p.parse_args()
    if os.name!='posix' or os.geteuid()!=0:raise ValueError('Root Linux required; local tests use a temporary root')
    if a.action=='rollback':
        if not a.backup or a.backup.parent!=Path(BACKUPS) or not re.fullmatch(r'workspace-native-20261006-[a-f0-9]{12}',a.backup.name):raise ValueError('Exact native backup namespace required')
        result=rollback(a.backup,a.approved_manifest_sha)
    else:
        trusted(a.manifest,a.manifest.parent);raw=a.manifest.read_bytes();m=json.loads(raw)
        result=inspect(m,a.manifest.parent) if a.action=='inspect' else apply(m,a.manifest.parent,raw,a.approved_manifest_sha)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
