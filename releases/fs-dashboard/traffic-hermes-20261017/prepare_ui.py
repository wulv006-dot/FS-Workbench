"""Prepare only traffic/ES assets; never publish or reconstruct a partial Nginx config."""
from pathlib import Path
import argparse,hashlib,json,re

ACTIVE='workspace-native-20261006-ba0a83afd594'
THEME='workspace-native-20261006-561eda9b98e2'
STATIC='/var/lib/fs-navigation-formal-static/'
URL='/dashboard/workspace-assets/'
CONFIG='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
EXPECTED={CONFIG:'8b112899db9683440c78b5712b457e7091d4efe9584fe8ab3d19a3a39b9f39bc',STATIC+ACTIVE+'/shell.js':'535a6817f2dc9dc41cbf30fe9b277c091934ab24f1d61649b2ba56b67d1f646e',STATIC+ACTIVE+'/index.html':'898404303af0614f0be818a119b1a9d663e11cbcb6e3da4246718193f90d9249',STATIC+ACTIVE+'/home.html':'ff05e65f207773a3e1fb4fb0cdc51ac526e3706d9397a22804b472e6fb9bd463'}
# Read-only activity evidence from 2026-10-17; these dependencies are never published here.
ACTIVE_DEPENDENCIES={STATIC+ACTIVE+'/'+n:h for n,h in {
'runtime.js':'7d021464703e02dbd879fa1c4eede18f948416e15998b9531bab8d2e4607c41c',
'business.html':'82ea9b8f540ff54d2ce90b6e37802df72d5a8e8f7b0f28f71bd666441db00537',
'google.html':'df2bb278dd979cf995d1f6d5e7322cb81a667a772c8754091b88541fb46fd493',
'navigation.json':'496fe59571e43c1afeb584caafee6cdcd86f8e09bcc70477e7ca7e0f695db5fd',
'workspace.css':'c08de4e8db104444446cba0012c857a744e0807fb06abea733049d7534c3f239'}.items()}
NAMES=('business.js','google.js','shell.js','index.html','home.html')
sha=lambda b:hashlib.sha256(b).hexdigest()

def prepare(repo,baseline,output,formal=None,dependencies=None):
    repo=Path(repo);output=Path(output)
    if output.exists():raise ValueError('output_exists')
    if repo.resolve()==output.resolve() or repo.resolve() in output.resolve().parents:raise ValueError('output_must_be_outside_repository')
    files={r['path']:r for r in baseline['files']}
    for path,digest in EXPECTED.items():
        if files.get(path,{}).get('sha256')!=digest or files[path].get('is_symlink'):raise ValueError('active_baseline_changed: '+path)
    config_bytes=Path(formal).read_bytes() if formal else None
    if config_bytes is not None and sha(config_bytes)!=EXPECTED[CONFIG]:raise ValueError('active_formal_changed')
    source=repo/'ui-system/modules/native';data={n:(source/n).read_bytes() for n in NAMES}
    for n in ('index.html','home.html'):
        if sha(data[n])!=EXPECTED[STATIC+ACTIVE+'/'+n]:raise ValueError('active_html_changed: '+n)
    # Include this preparation rule in the immutable version, not just business payloads.
    rid='workspace-native-20261006-'+sha(Path(__file__).read_bytes()+b''.join(data[n] for n in NAMES)+(json.dumps(dependencies,sort_keys=True).encode() if dependencies else b''))[:12]
    shell=data['shell.js'].decode()
    shell=shell.replace("new URL(state.mode+'.css',base)","new URL(state.mode+'.css',new URL('"+URL+THEME+"/',location.origin))")
    shell=shell.replace("new URL('ui/'+name,base)","new URL('ui/'+name,new URL('"+URL+THEME+"/',location.origin))")
    shell=shell.replace("new URL('navigation.json',base)","new URL('navigation.json',logicBase)")
    data['shell.js']=shell.encode()
    for n in ('index.html','home.html'):
        data[n]=data[n].replace((URL+ACTIVE+'/shell.js').encode(),(URL+rid+'/shell.js').encode())
    routes=re.findall(r'location = [^\n]+\{.*?\n\}',config_bytes.decode(),re.S) if config_bytes is not None else baseline.get('routes',[])
    def template(name):
        key='location = '+URL+ACTIVE+'/'+name+' {'
        if name=='google.js':key='location = '+URL+'workspace-native-20261006-fd4cfd0a70aa/google.js {'
        matches=[r for r in routes if r.startswith(key)]
        if len(matches)!=1:raise ValueError('missing_observed_route_template: '+name)
        block=matches[0]
        if 'auth_request /__nav_formal_native_session;' not in block or 'disable_symlinks on;' not in block:raise ValueError('route_access_policy_missing')
        old=re.search(r'location = ('+re.escape(URL)+r'[^ ]+) \{',block).group(1)
        alias=re.search(r'alias ([^;]+);',block).group(1)
        return block.replace(old,URL+rid+'/'+name).replace(alias,STATIC+rid+'/'+name)
    # business.js shares the exact existing JS policy; old immutable routes are untouched.
    additions=[]
    for name in NAMES:additions.append(template('shell.js' if name=='business.js' else name).replace(URL+rid+'/shell.js',URL+rid+'/'+name).replace(STATIC+rid+'/shell.js',STATIC+rid+'/'+name) if name=='business.js' else template(name))
    output.mkdir(parents=True);(output/'assets').mkdir()
    assets=[]
    for name,raw in data.items():
        (output/'assets'/name).write_bytes(raw);assets.append({'candidate':'assets/'+name,'target':STATIC+rid+'/'+name,'url':URL+rid+'/'+name,'beforeSha256':None,'sha256':sha(raw)})
    (output/'exact-route-additions.conf').write_text('\n\n'.join(additions)+'\n',encoding='utf8')
    aliases=[]
    for block in routes:
        if block.startswith('location = '+URL):continue
        for name in ('index.html','home.html'):
            old=STATIC+ACTIVE+'/'+name
            if 'alias '+old+';' in block:
                aliases.append({'route':block.split(' {')[0].removeprefix('location = '),'beforeBlockSha256':sha(block.encode()),'beforeAlias':old,'afterAlias':STATIC+rid+'/'+name})
    plan={'schemaVersion':1,'releaseId':rid,'releaseReady':False,'status':'assets_prepared_config_incomplete','missing':['full current formal.conf bytes; locked CAS readback; unchanged dependency hashes; existing publisher manifest assembly'],'assets':assets,'config':{'target':CONFIG,'beforeSha256':EXPECTED[CONFIG],'additions':'exact-route-additions.conf','aliasChanges':aliases,'preserveAllExistingImmutableRoutes':True},'requiredCAS':[{'path':p,'sha256':d} for p,d in EXPECTED.items()],'dependencies':{'logicBase':URL+ACTIVE+'/','themeBase':URL+THEME+'/','runtime':'runtime.js','markup':['business.html','google.html'],'style':['business.css','google.css','ui/fs-ui.css','ui/native-alias.css'],'navigation':'navigation.json'},'publisherBridge':'ui-system/publishers/native_bridge.py','publisher':'releases/fs-dashboard/menu-cache-20261015/native/release_workspace.py','productionWrites':False}
    if config_bytes is not None:
        candidate=config_bytes
        for change in aliases:
            if change['route']!='/dashboard/analytics/index.html':continue
            original=next(b for b in routes if b.startswith('location = '+change['route']+' {'))
            patched=original.replace('alias '+change['beforeAlias']+';','alias '+change['afterAlias']+';')
            candidate=candidate.replace(original.encode(),patched.encode(),1)
        candidate+=('\n\n'+'\n\n'.join(additions)+'\n').encode()
        (output/'candidate').mkdir();(output/'candidate/formal.conf').write_bytes(candidate);(output/'candidate/home.html').write_bytes(data['home.html'])
        targets=[{'candidate':'candidate/formal.conf','target':CONFIG,'beforeSha256':EXPECTED[CONFIG],'sha256':sha(candidate)},{'candidate':'candidate/home.html','target':'/var/www/dashboard/fs-home/index.html','beforeSha256':EXPECTED[STATIC+ACTIVE+'/home.html'],'sha256':sha(data['home.html'])}]
        manifest={'schemaVersion':1,'scope':'traffic-es-ui-20261017','releaseReady':False,'releaseId':rid,'immutableAssets':assets,'targets':targets,'unchangedRequired':plan['requiredCAS'],'requiredBusinessLedger':None,'missing':['current requiredBusinessLedger; observed immutable dependency SHA256s; exact frozen existing publisher adaptation'],'businessWrites':False,'timersChanged':False}
        if dependencies:
            deps={r['path']:r for r in dependencies['files']}
            ledger_row=deps['/var/lib/fs-dashboard-release/current.json'];ledger_text=ledger_row['text']
            if sha(ledger_text.encode())!=ledger_row['sha256']:raise ValueError('ledger_text_sha_mismatch')
            ledger=json.loads(ledger_text)
            if deps['/var/www/dashboard/index.html']['sha256']!=ledger['sha256']:raise ValueError('ledger_dashboard_mismatch')
            theme_paths=[STATIC+THEME+'/'+n for n in ('ui/fs-tokens.css','ui/fs-ui.css','ui/fs-theme.js','ui/native-alias.css','workspace.css','business.css','google.css')]
            for path in theme_paths:
                if not re.fullmatch('[a-f0-9]{64}',deps.get(path,{}).get('sha256','')):raise ValueError('missing_theme_sha: '+path)
            protected={r['path']:r['sha256'] for r in manifest['unchangedRequired'] if r['path'] not in {t['target'] for t in targets}}
            protected.update(ACTIVE_DEPENDENCIES)
            protected.update({p:deps[p]['sha256'] for p in theme_paths+['/var/lib/fs-dashboard-release/current.json','/var/www/dashboard/index.html']})
            manifest.update(unchangedRequired=[{'path':p,'sha256':h} for p,h in protected.items()],requiredBusinessLedger=ledger,missing=[])
            raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();(output/'release-contract.json').write_bytes(raw);(output/'release-manifest.json').write_bytes(raw)
            publisher=(repo/'releases/fs-dashboard/menu-cache-20261015/native/release_workspace.py').read_text(encoding='utf8')
            publisher=re.sub(r'^NAMES = .*$', 'NAMES = {'+', '.join(repr(n) for n in sorted(NAMES))+'}',publisher,flags=re.M)
            publisher=re.sub(r'^MUTABLE = .*$', 'MUTABLE = '+repr(tuple(t['target'] for t in targets)),publisher,flags=re.M)
            publisher=publisher.replace("if len(m['targets'])!=4", "if len(m['targets'])!=2")
            publisher=re.sub(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+sha(raw)+"'",publisher)
            (output/'release_workspace.py').write_text(publisher,encoding='utf8')
            bridge=(repo/'ui-system/publishers/native_bridge.py').read_text(encoding='utf8').replace("Path(__file__).resolve().parents[1] / 'native/release_navigation_base.py'", "Path(__file__).resolve().with_name('release_navigation_base.py')")
            (output/'release_navigation.py').write_text(bridge,encoding='utf8')
            base=(repo/'releases/fs-dashboard/menu-cache-20261015/native/release_navigation.py').read_bytes()
            if sha(base)!='5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357':raise ValueError('reviewed_publisher_base_changed')
            (output/'release_navigation_base.py').write_bytes(base)
        (output/'release-manifest.candidate.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        plan['status']='inspectable_frozen_candidate' if dependencies else 'candidate_config_and_manifest_require_runtime_guards';plan['missing']=manifest['missing'];plan['config']['candidate']='candidate/formal.conf'
    (output/'ui-preparation.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return plan

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--output',required=True);p.add_argument('--formal-conf');p.add_argument('--dependencies');a=p.parse_args();repo=Path(__file__).resolve().parents[3]
    print(json.dumps(prepare(repo,json.loads(Path(a.baseline).read_text(encoding='utf8')),a.output,a.formal_conf,json.loads(Path(a.dependencies).read_text(encoding='utf8')) if a.dependencies else None),ensure_ascii=False,indent=2))
