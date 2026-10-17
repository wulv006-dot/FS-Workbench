"""Six exact native assets for macro traffic; advance current e065, never rebuild shared UI."""
import argparse,ast,hashlib,json,re
from pathlib import Path
import prepare_ui_followup as prior
NAMES=(*prior.NAMES,'google.css')
THEME='workspace-native-20261006-561eda9b98e2'
CSS_TARGET=prior.STATIC+THEME+'/google.css'
sha=prior.sha

def prepare(repo,previous,receipt,formal,runtime_baseline,output,expected_previous='workspace-native-20261006-e0654eaced60'):
    repo=Path(repo);previous=Path(previous);output=Path(output)
    old=json.loads((previous/'release-manifest.json').read_text(encoding='utf8'))
    if not re.fullmatch('workspace-native-20261006-[a-f0-9]{12}',expected_previous) or old['releaseId']!=expected_previous:raise ValueError('exact_current_release_required')
    old_names=tuple(Path(r['candidate']).name for r in old['immutableAssets'])
    if set(old_names) not in (set(prior.NAMES),set(NAMES)):raise ValueError('previous_asset_scope_drift')
    known={r['path']:r for r in runtime_baseline['files']}
    required={r['target']:r['sha256'] for r in old['immutableAssets']+old['targets']}
    required.update({r['path']:r['sha256'] for r in old['unchangedRequired']})
    if CSS_TARGET not in required:raise ValueError('shared_css_protection_missing')
    for target,digest in required.items():
        fact=known.get(target,{})
        if fact.get('sha256')!=digest or fact.get('is_symlink') is True:raise ValueError('current_runtime_drift: '+target)
    if receipt.get('ui_backup','').split('/')[-1]==old['releaseId'] and receipt.get('ui_assets')==5 and receipt.get('ui_targets')==2 and receipt.get('nginx')=='passed':
        receipt={'releaseId':old['releaseId'],'status':'applied-awaiting-real-desktop-URL-QA','assets':5,'entry_targets':2}
    prior.prepare(repo,previous,receipt,formal,output,asset_names=old_names)
    intermediate=json.loads((output/'release-manifest.json').read_text(encoding='utf8'));mid=intermediate['releaseId']
    raw_assets={n:(output/'assets'/n).read_bytes() for n in prior.NAMES};raw_assets['google.css']=(repo/'ui-system/modules/native/google.css').read_bytes()
    shell=(repo/'ui-system/modules/native/shell.js').read_text(encoding='utf8');old_css="new URL(state.mode+'.css',base)"
    if shell.count(old_css)!=1:raise ValueError('current_css_wiring_drift')
    shell=shell.replace(old_css,"new URL(state.mode+'.css',state.mode==='google'?base:new URL('"+prior.URL+THEME+"/',location.origin))")
    shell=shell.replace("new URL('ui/'+name,base)","new URL('ui/'+name,new URL('"+prior.URL+THEME+"/',location.origin))").replace("new URL('navigation.json',base)","new URL('navigation.json',logicBase)")
    raw_assets['shell.js']=shell.encode()
    rid='workspace-native-20261006-'+sha(Path(__file__).read_bytes()+b''.join(raw_assets[n] for n in NAMES)+json.dumps(required,sort_keys=True).encode())[:12]
    for name in ('shell.js','index.html','home.html'):raw_assets[name]=raw_assets[name].replace((prior.URL+mid+'/').encode(),(prior.URL+rid+'/').encode())
    current=Path(formal).read_bytes();css_base=old['releaseId'] if 'google.css' in old_names else THEME;blocks=re.findall(rb'location = [^\n]+\{.*?\n\}',current,re.S);matches=[b for b in blocks if b.startswith(('location = '+prior.URL+css_base+'/google.css {').encode())]
    if len(matches)!=1 or b'auth_request /__nav_formal_native_session;' not in matches[0] or b'disable_symlinks on;' not in matches[0]:raise ValueError('observed_css_route_required')
    css_route=matches[0].replace((prior.URL+css_base+'/google.css').encode(),(prior.URL+rid+'/google.css').encode()).replace((prior.STATIC+css_base+'/google.css').encode(),(prior.STATIC+rid+'/google.css').encode())
    extra_css=b'\n'+css_route+b'\n' if 'google.css' not in old_names else b''
    candidate=(output/'candidate/formal.conf').read_bytes().replace(mid.encode(),rid.encode())+extra_css
    assets=[]
    for name,raw in raw_assets.items():
        (output/'assets'/name).write_bytes(raw);assets.append({'candidate':'assets/'+name,'target':prior.STATIC+rid+'/'+name,'url':prior.URL+rid+'/'+name,'beforeSha256':None,'sha256':sha(raw)})
    (output/'candidate/formal.conf').write_bytes(candidate);(output/'candidate/home.html').write_bytes(raw_assets['home.html']);(output/'exact-route-additions.conf').write_bytes((output/'exact-route-additions.conf').read_bytes().replace(mid.encode(),rid.encode())+extra_css)
    manifest={**intermediate,'releaseId':rid,'releaseReady':False,'immutableAssets':assets}
    for row in manifest['targets']:row['sha256']=sha((output/row['candidate']).read_bytes())
    raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();(output/'release-contract.json').write_bytes(raw);(output/'release-manifest.json').write_bytes(raw)
    publisher=(output/'release_workspace.py').read_text(encoding='utf8');names=re.search(r'^NAMES = (.*)$',publisher,re.M);mutable=re.search(r'^MUTABLE = (.*)$',publisher,re.M)
    if not names or ast.literal_eval(names[1])!=set(old_names) or not mutable or set(ast.literal_eval(mutable[1]))!={prior.CONFIG,prior.HOME}:raise ValueError('prior_publisher_scope_drift')
    publisher=re.sub(r'^NAMES = .*$', 'NAMES = {'+', '.join(repr(n) for n in sorted(NAMES))+'}',publisher,flags=re.M);publisher=re.sub(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+sha(raw)+"'",publisher);(output/'release_workspace.py').write_text(publisher,encoding='utf8')
    result={'releaseId':rid,'previousReleaseId':old['releaseId'],'manifestSha256':sha(raw),'assets':6,'mutable':2,'protected':len(manifest['unchangedRequired']),'releaseReady':False,'sharedCssWrites':False};(output/'ui-v3-preparation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--previous',required=True);p.add_argument('--receipt',required=True);p.add_argument('--formal-conf',required=True);p.add_argument('--runtime-baseline',required=True);p.add_argument('--output',required=True);p.add_argument('--expected-previous',default='workspace-native-20261006-e0654eaced60');a=p.parse_args();repo=Path(__file__).resolve().parents[3]
    print(json.dumps(prepare(repo,a.previous,json.loads(Path(a.receipt).read_text(encoding='utf8')),a.formal_conf,json.loads(Path(a.runtime_baseline).read_text(encoding='utf8')),a.output,a.expected_previous),indent=2))
