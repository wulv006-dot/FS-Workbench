"""Prepare and read back a data-only derivative of the existing native publisher."""
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
from contract import require,sha

STATIC=Path('/var/lib/fs-navigation-formal-static')
FRAGMENT=Path('/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf')
ORIGINAL=Path('/var/lib/fs-navigation-staging/game-monitor-sop-20261022/candidate-final')
LEDGER=Path('/var/lib/fs-dashboard-release/current.json')
BACKUPS=Path('/var/backups/fs-navigation-native-20261006')
PUBLISHER_SHA='82a5c2df830e128b3077d9c3d88286789680c4f3631966b400748e2e6e985056'
NAVIGATION_SHA='c61ae129feccd8f81a63f51dde414753b620ee8658061a477b0997ae0befc89f'

def safe(path):
    for item in (path,*path.parents):require(not item.is_symlink(),'linked_publication_path')
    return path

def blocks(text):
    rows=list(re.finditer(r'^location = (\S+) \{\n.*?^\}',text,re.M|re.S))
    require(len({m[1] for m in rows})==len(rows),'duplicate_nginx_route')
    return {m[1]:m[0] for m in rows}

def active():
    rows=blocks(safe(FRAGMENT).read_text())
    block=rows['/dashboard/game-monitor/index.html']
    aliases=re.findall(r'^\s*alias ([^;]+);',block,re.M)
    require(len(aliases)==1,'game_route_ambiguous')
    path=Path(aliases[0]);safe(path)
    require(path.parent.name=='game-monitor' and path.parent.parent.parent==STATIC and re.fullmatch(r'workspace-native-20261006-[a-f0-9]{12}',path.parent.parent.name),'game_route_outside_namespace')
    return path

def once(text,old,new):
    require(text.count(old)==1,'ambiguous_exact_replace');return text.replace(old,new,1)

def run(argv,timeout=90):
    child=subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
    require(child.returncode==0,'existing_publisher_failed:'+child.stderr[-200:])
    return json.loads(child.stdout)

def prepare(stage,before,after):
    require(not stage.exists(),'existing_stage_reconcile_required')
    current=active();require(current.read_bytes()==before,'live_baseline_drift')
    publisher=safe(ORIGINAL/'release_workspace.py').read_bytes()
    require(sha(publisher)==PUBLISHER_SHA and sha(safe(ORIGINAL/'release_navigation.py').read_bytes())==NAVIGATION_SHA,'existing_publisher_drift')
    manifest=json.loads((ORIGINAL/'release-manifest.json').read_bytes())
    base=current.parent.parent
    names={p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}
    require(100<=len(names)<=1000,'unexpected_asset_inventory')
    identities={name:sha(safe(base/name).read_bytes()) for name in names}
    identities['game-monitor/index.html']=sha(after)
    version='workspace-native-20261006-'+sha(json.dumps(identities,sort_keys=True).encode())[:12]
    conf_raw=FRAGMENT.read_bytes();conf=conf_raw.decode();routes=blocks(conf)
    new=once(conf,routes['/dashboard/game-monitor/index.html'],once(routes['/dashboard/game-monitor/index.html'],str(current),str(STATIC/version/'game-monitor/index.html')))
    old_version=base.name
    copies=[block.replace(old_version,version) for url,block in routes.items() if url.startswith('/dashboard/workspace-assets/'+old_version+'/')]
    require(len(copies)==len(names),'current_immutable_routes_incomplete')
    new+='\n\n# Hermes data-only static content publication.\n'+'\n\n'.join(copies)+'\n'
    blocks(new)
    target_names={x['target'] for x in manifest['targets']}
    protected={x['path'] for x in manifest['unchangedRequired']}|{str(base/name) for name in names}
    protected={name:sha(safe(Path(name)).read_bytes()) for name in protected-target_names}
    stage.mkdir(parents=True,mode=0o700)
    shutil.copytree(base,stage/'assets')
    (stage/'assets/game-monitor/index.html').write_bytes(after)
    for row in manifest['targets']:
        raw=safe(Path(row['target'])).read_bytes()
        updated=new.encode() if row['target']==str(FRAGMENT) else raw
        destination=stage/row['candidate'];destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(updated)
        row.update(beforeSha256=sha(raw),sha256=sha(updated))
    manifest.update(scope='Hermes authorized data-only game-monitor content maintenance',releaseId=version,releaseReady=False,
        requiredBusinessLedger=json.loads(LEDGER.read_bytes()),
        unchangedRequired=[dict(path=name,sha256=value) for name,value in sorted(protected.items())],
        immutableAssets=[dict(candidate='assets/'+name,target=str(STATIC/version/name),url='/dashboard/workspace-assets/'+version+'/'+name,beforeSha256=None,sha256=value) for name,value in sorted(identities.items())])
    contract=(json.dumps(manifest,indent=2)+'\n').encode();(stage/'release-contract.json').write_bytes(contract)
    manifest['releaseReady']=True;approved=(json.dumps(manifest,indent=2)+'\n').encode();(stage/'release-manifest.json').write_bytes(approved)
    source=publisher.decode()
    source,count=re.subn(r'^NAMES = .*$', 'NAMES = {'+', '.join(repr(n) for n in sorted(names))+'}',source,flags=re.M);require(count==1,'publisher_names_constant')
    source,count=re.subn(r"CONTRACT_SHA = '[a-f0-9]+'","CONTRACT_SHA = '"+sha(contract)+"'",source);require(count==1,'publisher_contract_constant')
    ast.parse(source)
    # The frozen implementation is reused verbatim apart from its two data constants.
    normalize=lambda x:re.sub(r"CONTRACT_SHA = '[a-f0-9]+'","CONTRACT_SHA = 'FROZEN'",re.sub(r'^NAMES = .*$',"NAMES = FROZEN",x,flags=re.M))
    require(normalize(source)==normalize(publisher.decode()),'publisher_implementation_changed')
    (stage/'release_workspace.py').write_text(source)
    shutil.copyfile(ORIGINAL/'release_navigation.py',stage/'release_navigation.py')
    require(current.read_bytes()==before and FRAGMENT.read_bytes()==conf_raw,'prepare_concurrent_drift')
    result=run(['/opt/python39/bin/python3','-B',str(stage/'release_workspace.py'),'inspect'])
    return dict(stage=str(stage),release=version,manifest_sha256=sha(approved),inspect=result)

def verify(stage):
    manifest=json.loads((stage/'release-manifest.json').read_bytes())
    for row in manifest['immutableAssets']+manifest['targets']:require(sha(safe(Path(row['target'])).read_bytes())==row['sha256'],'published_target_drift')
    for row in manifest['unchangedRequired']:require(sha(safe(Path(row['path'])).read_bytes())==row['sha256'],'protected_target_drift')
    require(active().read_bytes()==(stage/'assets/game-monitor/index.html').read_bytes(),'active_route_readback_failed')
    child=subprocess.run(['nginx','-t'],capture_output=True,text=True,timeout=20);require(child.returncode==0,'nginx_readback_failed')
    backup=Path('/var/backups/fs-navigation-native-20261006')/manifest['releaseId']
    journal=json.loads((backup/'journal.json').read_bytes())
    require(journal['status']=='applied-awaiting-real-desktop-URL-QA','publisher_journal_unresolved')
    require(sha((backup/'approved-manifest.json').read_bytes())==sha((stage/'release-manifest.json').read_bytes()),'backup_manifest_drift')
    return dict(release=manifest['releaseId'],assets=len(manifest['immutableAssets']),mutable=len(manifest['targets']),protected=len(manifest['unchangedRequired']),backup=str(backup),status='published_file_and_route_readback_verified')


def verify_rollback(stage,before_sha256):
    raw=safe(stage/'release-manifest.json').read_bytes()
    manifest=json.loads(raw)
    require(re.fullmatch(r'[a-zA-Z0-9-]+',manifest['releaseId']),'invalid_release_id')
    backup=BACKUPS/manifest['releaseId']
    require(safe(backup/'approved-manifest.json').read_bytes()==raw,'backup_manifest_drift')
    journal=json.loads(safe(backup/'journal.json').read_bytes())
    require(journal.get('approvedManifestSha256')==sha(raw),'rollback_manifest_drift')
    require(journal.get('status')=='rolled-back-immutable-history-retained' and journal.get('activationAttempted') is False,'rollback_not_proven')
    require(sha(active().read_bytes())==before_sha256,'rollback_live_drift')
    return dict(status='rolled_back_verified',backup=str(backup),failure=journal.get('failure'),activation_attempted=False)
