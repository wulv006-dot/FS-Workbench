"""Prepare the reviewed UI through the existing immutable publisher; never apply it."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

FROZEN_PUBLICATION_BLOB = 'dfc5819645418e9af348b7a4d14eac3d88721619'
OLD_ROUTE = '/dashboard/game-monitor/index.html'
NEW_ROUTE = '/dashboard/game-monitor/operations.html'


def route(template, old, new, target):
    if template.count('location = '+old+' {') != 1 or len(re.findall(r'^\s*alias [^;]+;',template,re.M)) != 1:
        raise ValueError('ambiguous_existing_route')
    result=template.replace('location = '+old+' {','location = '+new+' {',1)
    return re.sub(r'(^\s*alias )[^;]+;',lambda m:m[1]+str(target)+';',result,flags=re.M)


def current_assets(identities):
    return {name:digest for name,digest in identities.items()
        if not name.startswith('game-monitor/') or name in ('game-monitor/index.html','game-monitor/operations.html')}


def retire_routes(fragment, version):
    keep={'index.html','operations.html','intelligence.json','intelligence.status.json','seo-news.json','seo-news.status.json'}
    pattern=r'^location = (\S+) \{\r?\n.*?^\}'
    for match in list(re.finditer(pattern,fragment,re.M|re.S)):
        path=match[1]
        asset_prefix='/dashboard/workspace-assets/'+version+'/game-monitor/'
        if (path.startswith('/dashboard/game-monitor/') and path.removeprefix('/dashboard/game-monitor/') not in keep
                or path.startswith(asset_prefix) and path.removeprefix(asset_prefix) not in ('index.html','operations.html')):
            fragment=fragment.replace(match[0],'',1)
    return fragment


def asset_rows(identities, static, version):
    return [dict(candidate='assets/'+name,target=str(static/version/name),
        url='/dashboard/workspace-assets/'+version+'/'+name,beforeSha256=None,sha256=digest)
        for name,digest in sorted(identities.items())]


def default_entry(fragment):
    old='location = /dashboard/game-monitor/ { rewrite ^ /dashboard/game-monitor/index.html last; }'
    new='location = /dashboard/game-monitor/ { rewrite ^ /dashboard/game-monitor/operations.html last; }'
    if fragment.count(old)==1 and new not in fragment:
        return fragment.replace(old,new,1)
    if fragment.count(new)==1 and old not in fragment:
        return fragment
    raise ValueError('default_entry_route_drift')


def prepare(asset, stage, module=Path('/opt/fs-hermes-ops/game_monitor/publication.py')):
    raw=module.read_bytes()
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=FROZEN_PUBLICATION_BLOB:
        raise ValueError('existing_publisher_adapter_drift')
    sys.path.insert(0,str(module.parent))
    sys.path.insert(1,'/opt/fs-hermes-ops/game_monitor')
    import publication as pub
    before=pub.active().read_bytes()
    original_fragment=pub.FRAGMENT.read_bytes()
    after=asset
    prepared=pub.prepare(stage,before,after)
    manifest=json.loads((stage/'release-manifest.json').read_bytes())
    old_version=manifest['releaseId']
    name='game-monitor/operations.html'
    (stage/'assets'/name).write_bytes(asset)
    identities={row['candidate'].removeprefix('assets/'):row['sha256'] for row in manifest['immutableAssets']}
    identities[name]=pub.sha(asset)
    retained=current_assets(identities)
    for retired in set(identities)-set(retained):
        (stage/'assets'/retired).unlink()
    identities=retained
    version='workspace-native-20261006-'+pub.sha(json.dumps(identities,sort_keys=True).encode())[:12]
    manifest['immutableAssets']=asset_rows(identities,pub.STATIC,version)
    fragment_row=next(row for row in manifest['targets'] if row['target']==str(pub.FRAGMENT))
    fragment=default_entry((stage/fragment_row['candidate']).read_bytes().decode().replace(old_version,version))
    blocks=pub.blocks(fragment)
    template=blocks[OLD_ROUTE]
    additions={NEW_ROUTE:route(template,OLD_ROUTE,NEW_ROUTE,pub.STATIC/version/name),
        '/dashboard/workspace-assets/'+version+'/'+name:route(template,OLD_ROUTE,'/dashboard/workspace-assets/'+version+'/'+name,pub.STATIC/version/name)}
    for path,block in additions.items():
        if path in blocks:
            fragment=fragment.replace(blocks[path],block,1)
        else:
            fragment+='\n'+block+'\n'
    # The supplementary JSON routes inherit the existing authenticated JSON route.
    current=pub.blocks(original_fragment.decode())
    for old,new,target in [('/dashboard/game-monitor/intelligence.json','/dashboard/game-monitor/intelligence.json','/var/lib/fs-boss-workspaces/public/intelligence.json'),('/dashboard/game-monitor/intelligence.status.json','/dashboard/game-monitor/intelligence.status.json','/var/lib/fs-boss-workspaces/public/intelligence.status.json'),('/dashboard/game-monitor/intelligence.status.json','/dashboard/game-monitor/seo-news.status.json','/var/lib/fs-boss-workspaces/public/seo-news.status.json')]:
        if old not in current:
            raise ValueError('json_route_template_unavailable:'+old)
        block=route(current[old],old,new,target)
        if new in pub.blocks(fragment):fragment=fragment.replace(pub.blocks(fragment)[new],block,1)
        else:fragment+='\n'+block+'\n'
    fragment=retire_routes(fragment,version)
    pub.blocks(fragment)
    fragment_bytes=fragment.encode();(stage/fragment_row['candidate']).write_bytes(fragment_bytes)
    fragment_row['sha256']=pub.sha(fragment_bytes)
    manifest.update(scope='Game intelligence replaces retired workspace and legacy collectors',releaseId=version,releaseReady=False)
    contract=(json.dumps(manifest,indent=2)+'\n').encode();(stage/'release-contract.json').write_bytes(contract)
    manifest['releaseReady']=True;(stage/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    source=(stage/'release_workspace.py').read_text()
    source=re.sub(r'^NAMES = .*$', 'NAMES = {'+', '.join(repr(n) for n in sorted(identities))+'}',source,flags=re.M)
    source=re.sub(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+pub.sha(contract)+"'",source)
    ast.parse(source);(stage/'release_workspace.py').write_text(source)
    if pub.active().read_bytes()!=before or pub.FRAGMENT.read_bytes()!=original_fragment:
        raise ValueError('prepare_concurrent_drift')
    inspection=pub.run(['/opt/python39/bin/python3','-B',str(stage/'release_workspace.py'),'inspect'])
    return dict(stage=str(stage),release=version,asset_sha256=pub.sha(asset),original_page_sha256=pub.sha(before),
        new_route=NEW_ROUTE,default_route='/dashboard/game-monitor/',inspect=inspection,applied=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset',type=Path,required=True)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--adapter',type=Path,default=Path('/opt/fs-hermes-ops/game_monitor/publication.py'))
    args=parser.parse_args()
    print(json.dumps(prepare(args.asset.read_bytes(),args.stage,args.adapter),ensure_ascii=False))
