"""Capture fresh metadata and prepare an weekly-frequency daily.js candidate on-host; never apply."""
import argparse, hashlib, json, os, re, shutil, stat
from datetime import datetime, timezone
from pathlib import Path

OLD='workspace-native-20261006-abc565540ced'
PRIOR=Path('/var/lib/fs-navigation-staging/news-cards-cfb-dropdown-20261016/candidate')
STATIC=Path('/var/lib/fs-navigation-formal-static')
FRAGMENT='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
LEDGER='/var/lib/fs-dashboard-release/current.json'
HTML_SHA='368a40026ca065f40a4133f9157f1d22d1d5325dd524d27de0fd13bce8c8d483'
NEW_DAILY_SHA='bf9ccaf980496d7f8c141b2bcc8b831e27e5ec97a25b8cee299ddc1ec3aa48f3'
DAILY_SHA='aeb4463af4ee5cba3bd904285a4ce4d47f2406bfb599a4c252e715f54cf9a2ca'
PUBLISHER_BODY_SHA='152bf689ef5ba5a25bc64be27da517ec042a1a10f1f98cf959550da53d5cb4cd'
NAVIGATION_SHA='c61ae129feccd8f81a63f51dde414753b620ee8658061a477b0997ae0befc89f'
sha=lambda data:hashlib.sha256(data).hexdigest()

def trusted(path):
    for item in (path,*path.parents):
        if item.is_symlink():raise ValueError('linked source/stage boundary: '+str(item))
        if item.exists():
            s=item.stat()
            if s.st_uid!=0 or s.st_gid!=0 or s.st_mode&0o022 or not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)) or (item.is_file() and s.st_nlink!=1):raise ValueError('unsafe ownership/type: '+str(item))

def read(path):
    path=Path(path);trusted(path);return path.read_bytes()

def prior():
    manifest=json.loads(read(PRIOR/'release-manifest.json'))
    if manifest['releaseId']!=OLD or len(manifest['immutableAssets'])!=139:raise ValueError('exact current 139-asset release required')
    body=read(PRIOR/'release_workspace.py')
    normalized,count=re.subn(rb"CONTRACT_SHA = '[a-f0-9]+'",b"CONTRACT_SHA = 'FROZEN'",body)
    if count!=1 or sha(normalized)!=PUBLISHER_BODY_SHA or sha(read(PRIOR/'release_navigation.py'))!=NAVIGATION_SHA:raise ValueError('reviewed publisher body differs')
    contract=read(PRIOR/'release-contract.json')
    if re.search(rb"CONTRACT_SHA = '([a-f0-9]+)'",body)[1].decode()!=sha(contract) or json.loads(contract)!=dict(manifest,releaseReady=False):raise ValueError('prior frozen contract differs')
    return manifest

def patch_config(conf,version):
    blocks=list(re.finditer(r'^location = (\S+) \{\n.*?^\}',conf,re.M|re.S))
    game=[m for m in blocks if m[1]=='/dashboard/game-monitor/daily.js']
    if len(game)!=1:raise ValueError('unique current game route required')
    old_alias=str(STATIC/'workspace-native-20261006-e7e3851862bd/game-monitor/daily.js');new_alias=str(STATIC/version/'game-monitor/daily.js')
    if game[0][0].count(old_alias)!=1:raise ValueError('current game route is not the approved release')
    changed=conf.replace(game[0][0],game[0][0].replace(old_alias,new_alias),1)
    copies=[m[0].replace(OLD,version) for m in blocks if m[1].startswith('/dashboard/workspace-assets/'+OLD+'/')]
    if len(copies)!=139:raise ValueError('exact 139 current asset routes required')
    addition='\n\n# Official intelligence and MMOEXP News collect Saturdays at 00:05 Beijing time, 2026-10-16.\n'+'\n\n'.join(copies)+'\n'
    changed+=addition
    locations=re.findall(r'^location = (\S+)',changed,re.M)
    if len(locations)!=len(set(locations)) or changed[:-len(addition)].replace(new_alias,old_alias)!=conf:raise ValueError('unexpected route changes or duplicates')
    return changed

def capture(destination):
    manifest=prior();names={r['candidate'][7:] for r in manifest['immutableAssets']}
    actual={p.relative_to(STATIC/OLD).as_posix() for p in (STATIC/OLD).rglob('*') if p.is_file()}
    if names!=actual:raise ValueError('current asset tree contains missing/extra files')
    paths={r['path'] for r in manifest['unchangedRequired']}|{r['target'] for r in manifest['targets']}|{str(STATIC/OLD/name) for name in names}
    paths|={str(PRIOR/name) for name in ('release_workspace.py','release_navigation.py','release-manifest.json','release-contract.json')}|{LEDGER}
    hashes={p:sha(read(p)) for p in sorted(paths)}
    if hashes[str(STATIC/OLD/'game-monitor/daily.js')]!=DAILY_SHA:raise ValueError('daily.js drift')
    conf=read(FRAGMENT).decode('utf-8');patch_config(conf,'workspace-native-20261006-000000000000')
    result={'capturedAt':datetime.now(timezone.utc).isoformat(),'baseReleaseId':OLD,'hashes':hashes}
    trusted(destination)
    with destination.open('xb') as stream:stream.write((json.dumps(result,indent=2)+'\n').encode())
    print(json.dumps({'baseline':str(destination),'sha256':sha(destination.read_bytes()),'paths':len(hashes),'productionWrites':0}))

def prepare(baseline,daily,destination):
    spec=json.loads(read(baseline));manifest=prior()
    if spec['baseReleaseId']!=OLD:raise ValueError('wrong baseline release')
    for path,expected in spec['hashes'].items():
        if sha(read(path))!=expected:raise ValueError('fresh CAS drift: '+path)
    changed=read(daily)
    if sha(changed)!=NEW_DAILY_SHA:raise ValueError('approved weekly UI bytes required')
    if sha(read(STATIC/OLD/'game-monitor/index.html'))!=HTML_SHA:raise ValueError('game HTML must remain unchanged')
    identities={r['candidate'][7:]:sha(read(STATIC/OLD/r['candidate'][7:])) for r in manifest['immutableAssets']}
    if identities['game-monitor/daily.js']!=DAILY_SHA:raise ValueError('daily.js must remain unchanged')
    identities['game-monitor/daily.js']=sha(changed)
    version='workspace-native-20261006-'+sha(json.dumps(identities,sort_keys=True).encode())[:12]
    altered=patch_config(read(FRAGMENT).decode('utf-8'),version).encode()
    trusted(destination);destination.mkdir()
    shutil.copytree(STATIC/OLD,destination/'assets')
    (destination/'assets/game-monitor/daily.js').write_bytes(changed)
    for name,expected in identities.items():
        if sha(read(destination/'assets'/name))!=expected:raise ValueError('copied asset drift: '+name)
    for row in manifest['targets']:
        data=read(row['target']);candidate=altered if row['target']==FRAGMENT else data
        if sha(data)!=spec['hashes'][row['target']]:raise ValueError('mutable target drift during preparation: '+row['target'])
        target=destination/row['candidate'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(candidate)
        row.update(beforeSha256=sha(data),sha256=sha(candidate))
    protected={p:h for p,h in spec['hashes'].items() if p not in {r['target'] for r in manifest['targets']}}
    manifest.update(scope='Official intelligence and MMOEXP News collect weekly on Saturday 00:05 Beijing time',releaseId=version,releaseReady=False,
                    requiredBusinessLedger=json.loads(read(LEDGER)),unchangedRequired=[dict(path=p,sha256=h) for p,h in sorted(protected.items())],
                    immutableAssets=[dict(candidate='assets/'+name,target=str(STATIC/version/name),url='/dashboard/workspace-assets/'+version+'/'+name,
                                          beforeSha256=None,sha256=h) for name,h in sorted(identities.items())])
    contract=(json.dumps(manifest,indent=2)+'\n').encode();(destination/'release-contract.json').write_bytes(contract)
    manifest['releaseReady']=True;approved=(json.dumps(manifest,indent=2)+'\n').encode();(destination/'release-manifest.json').write_bytes(approved)
    publisher,count=re.subn(rb"CONTRACT_SHA = '[a-f0-9]+'",("CONTRACT_SHA = '"+sha(contract)+"'").encode(),read(PRIOR/'release_workspace.py'))
    if count!=1:raise ValueError('publisher contract pin missing')
    (destination/'release_workspace.py').write_bytes(publisher);shutil.copyfile(PRIOR/'release_navigation.py',destination/'release_navigation.py')
    for path,expected in spec['hashes'].items():
        if sha(read(path))!=expected:raise ValueError('live drift during preparation; preserve candidate for review: '+path)
    print(json.dumps({'stage':str(destination),'releaseId':version,'manifestSha256':sha(approved),'assets':139,'changedAssets':['game-monitor/daily.js'],'dailySha256':NEW_DAILY_SHA,'productionWrites':0}))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['capture','prepare']);parser.add_argument('--baseline',type=Path,default=Path(__file__).with_name('baseline.json'))
    parser.add_argument('--daily',type=Path,default=Path(__file__).with_name('daily.js'));parser.add_argument('--stage',type=Path,default=Path(__file__).with_name('candidate'))
    args=parser.parse_args()
    if os.name!='posix' or os.geteuid()!=0:raise ValueError('on-host preparation requires reviewed Linux/root')
    capture(args.baseline) if args.action=='capture' else prepare(args.baseline,args.daily,args.stage)

if __name__=='__main__':main()
