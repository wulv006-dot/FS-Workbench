"""Freeze the two workspaces against the observed native publisher baseline."""
from pathlib import Path
import hashlib
import base64
import json
import re
import shutil

ROOT = Path(__file__).resolve().parent
PREVIOUS = ROOT.parent / 'fc_daily_20261013/release/frontend'
if not PREVIOUS.exists():
    PREVIOUS = ROOT.parent / 'fc-daily-20261013/frontend'
HOME = '/var/www/dashboard/fs-home/index.html'
FRAGMENT = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
NAV = '/var/www/dashboard/fs-home/navigation.js'
RADAR = '/etc/nginx/release-radar.locations.conf'
WEEKLY = '/opt/mmoexp-weekly-report/public/index.html'
sha = lambda data: hashlib.sha256(data).hexdigest()


def replace(text, before, after):
    if before not in text:
        assert text.count(after) == 1, 'Unexpected live source: '+before[:120]
        return text
    assert text.count(before) == 1, before[:120]
    return text.replace(before, after, 1)


def static_location(url, target):
    return '''location = %s {
    if ($request_method !~ ^(GET|HEAD)$) { return 405; }
    auth_request /__nav_formal_native_session;
    error_page 401 = @auth_login;
    alias %s;
    disable_symlinks on;
    expires -1;
    sub_filter "</body>" "</body>";
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Robots-Tag "noindex, nofollow" always;
    add_header Referrer-Policy "same-origin" always;
}
''' % (url, target)


def api_location(url, upstream, methods):
    return '''location = %s {
    if ($request_method !~ ^(%s)$) { return 405; }
    auth_request /__auth_verify;
    auth_request_set $boss_user $upstream_http_x_auth_user;
    auth_request_set $boss_role $upstream_http_x_auth_role;
    proxy_set_header X-Auth-User $boss_user;
    proxy_set_header X-Auth-Role $boss_role;
    proxy_set_header Cookie "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_pass http://127.0.0.1:8931%s;
    client_max_body_size 16k;
    proxy_read_timeout 15s;
    proxy_cache off;
    add_header Cache-Control "no-store" always;
}
''' % (url, methods, upstream)


def build():
    live = json.loads((ROOT/'baseline/live.json').read_text('utf-8'))
    old = live['version']
    texts = live['files']
    out = ROOT/'release'
    assets = out/'assets'
    assets.mkdir(parents=True, exist_ok=True)
    # Only this task's generated staging directory is updated; source ZIPs are never edited.
    content = {Path(p).name: base64.b64decode(row['bytesB64']) if 'bytesB64' in row else row['text'].encode('utf-8') for p, row in texts.items()
               if p.startswith('/var/lib/fs-navigation-formal-static/'+old+'/')}
    for path, row in texts.items():
        if path.startswith('/var/lib/fs-navigation-formal-static/'+old+'/'):
            name = Path(path).name
            if sha(content[name]) != row['sha256']:
                original = (PREVIOUS/'assets'/name).read_bytes()
                assert sha(original) == row['sha256'], 'Original asset bytes unavailable: '+name
                content[name] = original
    registry = json.loads(content['navigation.json'])
    sections = [('game-monitor', '游戏监控台', '全球新游上线 · 版本赛季 · 开服节点一屏追踪', '◉'),
                ('management', '经营管理台', '三组进度 · 健康度责任到人 · 目标沙盘与经营决策', '▦')]
    for section in registry['sections']:
        section['ids'] = [x for x in section['ids'] if x != 'release-radar']
    registry['tools'] = [t for t in registry['tools'] if t['id'] != 'release-radar']
    registry['sections'] = [r for r in registry['sections'] if r['id'] not in {x[0] for x in sections}]
    registry['tools'] = [r for r in registry['tools'] if r['id'] not in {x[0] for x in sections}]
    for key, title, intro, icon in sections:
        registry['sections'].append(dict(id=key, title=title, intro=intro, icon=icon,
                                         ids=[key], path='/dashboard/'+key+'/'))
        registry['tools'].append(dict(id=key, label=title, short=intro, icon=icon,
                                     path='/dashboard/'+key+'/', section=key,
                                     scope='global-portal', requiredGroup='dashboard',
                                     serverGuard='/__nav_formal_native_session'))
    # The Advisor task owns its assets/routes; copy only the live verified version.
    advisor_live = 'advisor.html' in content
    content['navigation.json'] = (json.dumps(registry, ensure_ascii=False, indent=2)+'\n').encode()
    shell = content['shell.js'].decode()
    shell = replace(shell, "[['release-radar','游戏监控台'],", "[['game-monitor','游戏监控台'],")
    shell = replace(shell, ".map(id=>verified.find(t=>t.id===id))", ".map(id=>verified.find(t=>t.id===(id==='release-radar'?'game-monitor':id)))")
    shell = replace(shell, "['协作工具','/dashboard/modules/collaboration/','collaboration']]", "['协作工具','/dashboard/modules/collaboration/','collaboration'],['游戏监控台','/dashboard/game-monitor/','game-monitor'],['经营管理台','/dashboard/management/','management']]")
    content['shell.js'] = shell.encode()
    css = content['workspace.css'].decode()
    css = replace(css, '.workspace-grid{display:grid;grid-template-columns:repeat(4,', '.workspace-grid{display:grid;grid-template-columns:repeat(3,')
    if '.workspace-card.game-monitor .workspace-icon' not in css:
        css += '\n.workspace-card.game-monitor .workspace-icon{background:#e8f3ff;color:#2660a4}.workspace-card.management .workspace-icon{background:#f8efe2;color:#996721}.global-nav{flex-wrap:wrap}@media(max-width:600px){.global-nav{justify-content:flex-start;gap:8px}}\n'
    content['workspace.css'] = css.encode()
    for module in ('game-monitor', 'management'):
        for file in sorted((ROOT/'source'/module).rglob('*')):
            if file.is_file():
                assert not file.is_symlink() and file.suffix in ('.html', '.js', '.css', '.json', '.jpg', '.jpeg', '.png', '.webp')
                content[module+'/'+file.relative_to(ROOT/'source'/module).as_posix()] = file.read_bytes()
    seed = b''.join(key.encode()+b'\0'+value for key, value in sorted(content.items()))
    version = 'workspace-native-20261006-'+sha(seed)[:12]
    for key, data in content.items():
        content[key] = data.replace(old.encode(), version.encode())
        target=assets/key;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content[key])
    assert {p.relative_to(assets).as_posix() for p in assets.rglob('*') if p.is_file()} == set(content), 'Stale generated files; inspect stage before rebuilding'
    prefix='/var/lib/fs-navigation-formal-static/'+version+'/'
    fragment=texts[FRAGMENT]['text'].replace(old,version)
    for key in sorted(content):
        url='/dashboard/workspace-assets/'+version+'/'+key
        if 'location = '+url+' {' not in fragment:
            fragment += static_location(url,prefix+key)
    for module in ('game-monitor','management'):
        if 'location = /dashboard/'+module+' {' in fragment:
            assert all('location = /dashboard/'+key+' {' in fragment for key in content if key.startswith(module+'/')), 'Missing current module routes'
            continue
        fragment += '\nlocation = /dashboard/'+module+' { return 302 /dashboard/'+module+'/; }\n'
        # nginx treats a trailing-slash file alias as a directory and appends index.html.
        fragment += 'location = /dashboard/'+module+'/ { rewrite ^ /dashboard/'+module+'/index.html last; }\n'
        for key in sorted(content):
            if key.startswith(module+'/'): fragment += static_location('/dashboard/'+key,prefix+key)
        for suffix in ('json', 'status.json'):
            fragment += static_location('/dashboard/'+module+'/daily.'+suffix,
                                        '/var/lib/fs-boss-workspaces/public/'+module+'.'+suffix)
        fragment += 'location ^~ /dashboard/'+module+'/ { return 404; }\n'
    if 'location = /dashboard/boss-api/insight {' not in fragment:
        fragment += api_location('/dashboard/boss-api/insight','/boss-insight','POST')
    locations = re.findall(r'location (=|\^~) (\S+) \{', fragment)
    assert len(locations) == len(set(locations)), 'Duplicate generated Nginx route'
    retired='''# Replaced by the two workspaces; original static release retained for rollback.
location = /dashboard/release-radar { return 302 /dashboard/game-monitor/; }
location = /dashboard/release-radar/ { return 302 /dashboard/game-monitor/; }
location = /dashboard/release-radar/index.html { return 302 /dashboard/game-monitor/; }
location ^~ /dashboard/release-radar/ { return 410; }
'''
    mutable = {'candidate/fs-home/index.html': (HOME,texts[HOME]['text'].replace(old,version)),
               'candidate/fs-home/navigation.js': (NAV,texts[NAV]['text'].replace(old,version)),
               'candidate/formal.conf': (FRAGMENT,fragment),
               'candidate/retired-radar.conf': (RADAR,retired)}
    for key, (_,data) in mutable.items():
        file=out/key;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data.encode('utf-8'))
    # Pin direct data/auth dependencies; the other task supplies its final backend bytes before release.
    protected=[dict(path=p,sha256=v['sha256']) for p,v in texts.items() if p.startswith('/opt/fs-') or p=='/etc/nginx/fs-business-range.locations.conf']
    protected += [dict(path=p,sha256=value) for p,value in live['protected_hashes'].items()]
    dependency=ROOT/'coordination/backend-dependency.json'
    if dependency.exists():
        additions=json.loads(dependency.read_text('utf-8'))
        by_path={r['path']:r for r in protected};by_path.update({r['path']:r for r in additions});protected=list(by_path.values())
    m=dict(schemaVersion=1,scope='FS game monitor and management workspaces; native session and shared AI',releaseReady=False,
           releaseId=version,immutableAssets=[dict(candidate='assets/'+key,target=prefix+key,url='/dashboard/workspace-assets/'+version+'/'+key,beforeSha256=None,sha256=sha(data)) for key,data in sorted(content.items())],
           targets=[dict(candidate=key,target=p,beforeSha256=texts[p]['sha256'],sha256=sha((out/key).read_bytes())) for key,(p,_) in mutable.items()],
           unchangedRequired=protected,requiredBusinessLedger=live['business_ledger'])
    raw=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(out/'release-contract.json').write_bytes(raw)
    (out/'release-manifest.json').write_bytes(raw)
    publisher=(PREVIOUS/'release_workspace.py').read_text('utf-8')
    publisher=replace(publisher,'MUTABLE = (HOME,FRAGMENT,NAVIGATION)', 'MUTABLE = '+repr(tuple(p for p,_ in mutable.values())))
    publisher=re.sub(r'^NAMES = .*$', 'NAMES = '+repr(set(content)),publisher,flags=re.M)
    publisher=re.sub(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+sha(raw)+"'",publisher)
    publisher=publisher.replace("len(rows)!=15 or {Path(r['candidate']).name for r in rows}!=NAMES", "len(rows)!=len(NAMES) or {r['candidate'][7:] for r in rows}!=NAMES")
    publisher=publisher.replace("name=Path(r['candidate']).name", "name=r['candidate'][7:]")
    publisher=publisher.replace("len(m['targets'])!=3", "len(m['targets'])!="+str(len(mutable)))
    publisher=publisher.replace("{p.name for p in (stage/'assets').iterdir()}", "{p.relative_to(stage/'assets').as_posix() for p in (stage/'assets').rglob('*') if p.is_file()}")
    publisher=publisher.replace('assets=15,mutableTargets=3', 'assets=len(NAMES),mutableTargets=len(MUTABLE)')
    publisher=publisher.replace('Exact 15 assets required','Exact frozen assets required').replace('Exact three mutable targets required','Exact frozen mutable targets required')
    (out/'release_workspace.py').write_bytes(publisher.encode('utf-8'))
    shutil.copyfile(PREVIOUS/'release_navigation.py',out/'release_navigation.py')
    summary=dict(releaseId=version,assetCount=len(content),mutableCount=len(mutable),contractSha256=sha(raw),advisorPreserved=advisor_live,backendDependencySupplied=dependency.exists(),releaseReady=False)
    (out/'build-summary.json').write_text(json.dumps(summary,indent=2)+'\n','utf-8')
    print(json.dumps(summary))


if __name__=='__main__':build()
