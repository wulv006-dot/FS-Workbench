"""Build navigation-only candidates from current live files; never publish here."""
import hashlib, html, json, re
from pathlib import Path

P = Path(__file__).resolve().parent
VERSION = 'activities-nav-20261023-v1'
ROOT = '/var/www/dashboard/'
ACTIVITY = '/dashboard/analytics/campaigns/analytics/'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def group(section, tools):
    esc = lambda value: html.escape(value, quote=True)
    links = ''.join('<a class="hn-tool" href="'+esc(tools[key]['path'])+'">'+esc(tools[key]['label'])+'</a>' for key in section['ids'])
    return '<section class="hn-group"><a class="hn-heading" href="'+esc(section['path'])+'"><span class="hn-icon">'+esc(section['icon'])+'</span><span>'+esc(section['title'])+'</span></a>'+links+'</section>'

def update_registry(reg):
    reg = json.loads(json.dumps(reg))
    assert not any(s['id'] == 'activities' for s in reg['sections']), 'already prepared'
    analytics = next(s for s in reg['sections'] if s['id'] == 'analytics')
    analytics['ids'].remove('campaign-analytics')
    section = dict(id='activities', title='主站活动区', icon='◫', intro='活动转化分析、活动配置与商品编辑预览。', ids=['campaign-analytics', 'campaign-products'], path=ACTIVITY)
    reg['sections'].insert(next(i for i,s in enumerate(reg['sections']) if s['id']=='sports'), section)
    next(t for t in reg['tools'] if t['id']=='campaign-analytics')['section']='activities'
    reg['tools'].append(dict(id='campaign-products', label='商品编辑与预览', path=ACTIVITY+'products.html', icon='▣', short='维护活动商品组合、保存服务器草稿并预览', requiredGroup='dashboard', section='activities'))
    return reg

def cards(section, tools):
    def card(key):
        t=tools[key];e=lambda value: html.escape(value, quote=True)
        return '<a class="tool-card" href="'+e(t['path'])+'" data-tool="'+e(key)+'"><span class="tool-icon">'+e(t.get('icon','↗'))+'</span><strong>'+e(t['label'])+'</strong><p>'+e(t['short'])+'</p><span class="card-arrow">打开功能页面 ↗</span></a>'
    return '\n'.join(card(key) for key in section['ids'])

def prepare():
    c=P/'candidate';c.mkdir(exist_ok=True)
    targets={};before={}
    def put(name,target,text):
        targets[name]=target;before[name]=sha(Path(target));(c/name).write_text(text,encoding='utf-8')
    original=json.loads(Path(ROOT+'fs-home/navigation.json').read_text())
    reg=update_registry(original);tools={t['id']:t for t in reg['tools']}
    sections={s['id']:s for s in reg['sections']}
    fragments={key:group(sections[key],tools) for key in ('analytics','brain','activities')}
    put('navigation.json',ROOT+'fs-home/navigation.json',json.dumps(reg,ensure_ascii=False,indent=2)+'\n')
    registry=json.loads(Path(ROOT+'fs-home/module-registry.json').read_text())
    next(t for t in registry['tools'] if t['id']=='campaign-analytics')['section']='activities'
    registry['tools'].append(tools['campaign-products'])
    put('module-registry.json',ROOT+'fs-home/module-registry.json',json.dumps(registry,ensure_ascii=False,indent=2)+'\n')
    nav=Path('/var/www/hub/nav.js').read_text()
    start=nav.index('  var hermesLinks =');end=nav.index("  var KEY =",start)
    nav=nav[:start]+'''  // Compile all shared submenus from the same registry as static pages and hubnav.
  var sharedGroups = '''+json.dumps(fragments,ensure_ascii=False)+''';
  Object.keys(sharedGroups).forEach(function(id){
    var paths={analytics:'/dashboard/modules/analytics/',brain:'/dashboard/modules/hermes/',activities:''' + json.dumps(ACTIVITY)+'''};
    var heading=document.querySelector('#hubNav .hn-heading[href="'+paths[id]+'"]');
    var box=document.createElement('div');box.innerHTML=sharedGroups[id];var next=box.firstElementChild;
    if(heading)heading.parentElement.replaceWith(next);
    else if(id==='activities'){var sports=document.querySelector('#hubNav .hn-heading[href="/dashboard/modules/sports/"]');if(sports)sports.parentElement.before(next);}
  });

  var current=new URL(location.href),best=null,bestLength=-1;
  document.querySelectorAll('#hubNav a[aria-current]').forEach(function(a){a.removeAttribute('aria-current');});
  document.querySelectorAll('#hubNav .hn-home,#hubNav .hn-heading,#hubNav .hn-tool').forEach(function(a){
    var u=new URL(a.href,location.origin),exact=current.pathname===u.pathname;
    if(a.classList.contains('hn-home')&&!exact)return;
    if(!exact&&(!u.pathname.endsWith('/')||!current.pathname.startsWith(u.pathname)))return;
    if(Array.from(u.searchParams).some(function(p){return current.searchParams.get(p[0])!==p[1];}))return;
    var score=u.pathname.length+(a.classList.contains('hn-tool')?1:0);
    if(score>bestLength){best=a;bestLength=score;}
  });
  if(best){best.setAttribute('aria-current','page');var parent=best.closest('.hn-group');if(parent){var title=parent.querySelector('.hn-heading');if(title!==best)title.setAttribute('aria-current','true');}}

'''+nav[end:]
    put('nav.js','/var/www/hub/nav.js',nav)
    hub=Path('/var/www/hub/hubnav.js').read_text()
    hub,n=re.subn(r'const BUILTIN=.*?;\n',lambda _: 'const BUILTIN='+json.dumps(reg,ensure_ascii=False,separators=(',',':'))+';\n',hub,count=1)
    assert n==1
    hub=hub.replace("fs-nav-registry-users-v1",'fs-nav-registry-'+VERSION)
    hub=hub.replace("section.id==='analytics'||section.id==='brain'","section.id==='analytics'||section.id==='brain'||section.id==='activities'")
    hub,n=re.subn(r'function matches\(path\)\{[^\n]+\}',"function matches(path){const url=new URL(path,location.origin),current=new URL(location.href);if(Array.from(url.searchParams).some(([key,value])=>current.searchParams.get(key)!==value))return false;return current.pathname===url.pathname||(url.pathname.endsWith('/')&&current.pathname.startsWith(url.pathname));}",hub,count=1);assert n==1
    needle="const rows=(section.ids||[]).map(id=>tools.find(t=>t.id===id)).filter(Boolean);"
    assert hub.count(needle)==1
    hub=hub.replace(needle,needle+"const currentRow=rows.filter(t=>matches(t.path)).sort((a,b)=>b.path.length-a.path.length)[0];")
    hub=hub.replace("if(matches(t.path))a.setAttribute('aria-current','page')","if(currentRow===t)a.setAttribute('aria-current','page')")
    put('hubnav.js','/var/www/hub/hubnav.js',hub)
    pages={'home':ROOT+'fs-home/index.html',**{key:ROOT+'modules/'+key+'/index.html' for key in ('analytics','hermes','sports','arpg','bots','collaboration','about')},'report':ROOT+'fs-home/brain/index.html','conversation':ROOT+'fs-home/hermes/conversation/index.html'}
    for key,target in pages.items():
        text=Path(target).read_text()
        if 'id="hubNav"' in text:
            for name,path in [('analytics','/dashboard/modules/analytics/'),('brain','/dashboard/modules/hermes/')]:
                pattern=r'<section class="hn-group">\s*<a class="hn-heading" href="'+re.escape(path)+r'".*?</section>'
                text,n=re.subn(pattern,lambda _,name=name:fragments[name],text,flags=re.S)
                assert n==1,(key,name,n)
            marker=re.search(r'<section class="hn-group">\s*<a class="hn-heading" href="/dashboard/modules/sports/"',text)
            assert marker,key
            text=text[:marker.start()]+fragments['activities']+'\n'+text[marker.start():]
        text=re.sub(r'nav\.js\?v=[A-Za-z0-9_-]+','nav.js?v='+VERSION,text)
        if key=='home':
            marker='<article class="workspace-card sports">';assert text.count(marker)==1
            card='<article class="workspace-card activities"><a class="workspace-main" href="'+ACTIVITY+'"><span class="workspace-icon">◫</span><h3>主站活动区</h3><p>活动转化分析、活动配置与商品编辑预览。</p><span class="entry">进入工作区 →</span></a></article>\n'
            text=text.replace(marker,card+marker)
        if key=='analytics':
            text,n=re.subn(r'(<section class="tool-grid" aria-label="数据分析">).*?(</section>)',lambda m:m[1]+'\n'+cards(sections['analytics'],tools)+'\n'+m[2],text,flags=re.S);assert n==1
            text=re.sub(r'\d+ 个功能入口',str(len(sections['analytics']['ids']))+' 个功能入口',text)
        put('page-'+key+'.html',target,text)
    for name,target in [('z-main.conf','/etc/nginx/conf.d/iggm-web.conf'),('zz-formal.conf','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf')]:
        text=Path(target).read_text();text,n=re.subn(r'hubnav\.js\?v=[A-Za-z0-9_-]+','hubnav.js?v='+VERSION,text);assert n>0
        put(name,target,text)
    # Formal FS only: remove synthetic/local demo choices and their data script at response time.
    target='/opt/fs-campaign-dashboard/analytics/production-server.mjs'
    text=(P.parent/'app/analytics/production-server.mjs').read_text()
    put('production-server.mjs',target,text)
    manifest={'schemaVersion':1,'scope':'traffic-source-tabs-ui-finish-20261019','releaseReady':True,'businessWrites':False,'timersChanged':False,'runtimeRequired':{'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}},'unchangedRequired':[], 'files':[dict(candidate=name,target=target,beforeSha256=before[name],sha256=sha(c/name)) for name,target in targets.items()]}
    for target in ('/var/www/dashboard/index.html','/opt/auth-portal/auth_portal.py','/opt/fs-access-policy/rbac.py','/var/lib/fs-campaign-dashboard/state.json','/var/lib/fs-campaign-dashboard/posthog-secret.json'):
        manifest['unchangedRequired'].append(dict(path=target,sha256=sha(Path(target))))
    (P/'targets.json').write_text(json.dumps(targets,indent=2))
    raw=json.dumps(manifest,indent=2).encode();(P/'manifest.json').write_bytes(raw)
    print(json.dumps(dict(manifestSha256=hashlib.sha256(raw).hexdigest(),files=len(targets),analyticsItems=sections['analytics']['ids'])))

if __name__=='__main__':prepare()
