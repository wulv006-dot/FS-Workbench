"""Advance an already-applied minimal UI release without replaying the original config."""
import argparse,hashlib,json,re
from pathlib import Path
NAMES=('business.js','google.js','shell.js','index.html','home.html')
CONFIG='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
HOME='/var/www/dashboard/fs-home/index.html'
STATIC='/var/lib/fs-navigation-formal-static/'
URL='/dashboard/workspace-assets/'
sha=lambda data:hashlib.sha256(data).hexdigest()

def prepare(repo,previous,receipt,formal,output,asset_names=NAMES):
    repo=Path(repo);previous=Path(previous);output=Path(output)
    if output.exists():raise ValueError('output_exists')
    if output.resolve()==repo.resolve() or repo.resolve() in output.resolve().parents:raise ValueError('output_must_be_outside_repository')
    old=json.loads((previous/'release-manifest.json').read_text(encoding='utf8'));raw_contract=(previous/'release-contract.json').read_bytes();contract=json.loads(raw_contract)
    if dict(old,releaseReady=False)!=contract:raise ValueError('previous_contract_drift')
    if receipt.get('releaseId')!=old['releaseId'] or receipt.get('status')!='applied-awaiting-real-desktop-URL-QA' or receipt.get('assets')!=len(asset_names) or receipt.get('entry_targets')!=2:raise ValueError('previous_not_verified_applied')
    if len(old['immutableAssets'])!=len(asset_names) or {r['candidate'] for r in old['immutableAssets']}!={'assets/'+n for n in asset_names} or {r['target'] for r in old['targets']}!={CONFIG,HOME}:raise ValueError('previous_scope_drift')
    for row in old['immutableAssets']+old['targets']:
        if sha((previous/row['candidate']).read_bytes())!=row['sha256']:raise ValueError('previous_payload_drift')
    oldid=old['releaseId'];current=Path(formal).read_bytes();old_config=next(r for r in old['targets'] if r['target']==CONFIG);old_home=next(r for r in old['targets'] if r['target']==HOME)
    if sha(current)!=old_config['sha256']:raise ValueError('current_formal_drift')
    data={n:(previous/'assets'/n).read_bytes() for n in asset_names}
    for name in ('business.js','google.js'):data[name]=(repo/'ui-system/modules/native'/name).read_bytes()
    rid='workspace-native-20261006-'+sha(Path(__file__).read_bytes()+raw_contract+current+b''.join(data[n] for n in asset_names))[:12]
    for name in ('shell.js','index.html','home.html'):data[name]=data[name].replace((URL+oldid+'/').encode(),(URL+rid+'/').encode())
    blocks=re.findall(rb'location = [^\n]+\{.*?\n\}',current,re.S);additions=[]
    for name in asset_names:
        prefix=('location = '+URL+oldid+'/'+name+' {').encode();matches=[b for b in blocks if b.startswith(prefix)]
        if len(matches)!=1:raise ValueError('previous_route_missing: '+name)
        block=matches[0]
        if b'auth_request /__nav_formal_native_session;' not in block or b'disable_symlinks on;' not in block:raise ValueError('route_access_policy_missing')
        additions.append(block.replace((URL+oldid+'/').encode(),(URL+rid+'/').encode()).replace((STATIC+oldid+'/').encode(),(STATIC+rid+'/').encode()))
    entry=[b for b in blocks if b.startswith(b'location = /dashboard/analytics/index.html {')]
    old_alias=('alias '+STATIC+oldid+'/index.html;').encode()
    if len(entry)!=1 or entry[0].count(old_alias)!=1:raise ValueError('analytics_alias_drift')
    candidate=current.replace(entry[0],entry[0].replace(old_alias,('alias '+STATIC+rid+'/index.html;').encode()),1)+b'\n\n'+b'\n\n'.join(additions)+b'\n'
    output.mkdir(parents=True);(output/'assets').mkdir();(output/'candidate').mkdir()
    assets=[]
    for name,raw in data.items():
        (output/'assets'/name).write_bytes(raw);assets.append({'candidate':'assets/'+name,'target':STATIC+rid+'/'+name,'url':URL+rid+'/'+name,'beforeSha256':None,'sha256':sha(raw)})
    (output/'candidate/formal.conf').write_bytes(candidate);(output/'candidate/home.html').write_bytes(data['home.html']);(output/'exact-route-additions.conf').write_bytes(b'\n\n'.join(additions)+b'\n')
    targets=[{'candidate':'candidate/formal.conf','target':CONFIG,'beforeSha256':old_config['sha256'],'sha256':sha(candidate)},{'candidate':'candidate/home.html','target':HOME,'beforeSha256':old_home['sha256'],'sha256':sha(data['home.html'])}]
    manifest={**old,'releaseReady':False,'releaseId':rid,'immutableAssets':assets,'targets':targets}
    raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();(output/'release-contract.json').write_bytes(raw);(output/'release-manifest.json').write_bytes(raw)
    publisher=(previous/'release_workspace.py').read_text(encoding='utf8')
    if "CONTRACT_SHA = '"+sha(raw_contract)+"'" not in publisher:raise ValueError('previous_publisher_contract_drift')
    publisher=publisher.replace("CONTRACT_SHA = '"+sha(raw_contract)+"'", "CONTRACT_SHA = '"+sha(raw)+"'");(output/'release_workspace.py').write_text(publisher,encoding='utf8')
    for name in ('release_navigation.py','release_navigation_base.py'):(output/name).write_bytes((previous/name).read_bytes())
    return {'releaseId':rid,'previousReleaseId':oldid,'manifestSha256':sha(raw),'assets':len(asset_names),'mutable':2,'protected':len(manifest['unchangedRequired']),'releaseReady':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--previous',required=True);p.add_argument('--receipt',required=True);p.add_argument('--formal-conf',required=True);p.add_argument('--output',required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[3]
    print(json.dumps(prepare(repo,a.previous,json.loads(Path(a.receipt).read_text(encoding='utf8')),a.formal_conf,a.output),indent=2))
