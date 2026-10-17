/* Shared navigation only. Every business page keeps its existing server permission gate. */
(async function(){
 'use strict';

const menuCacheSlot='fs-menu-access-v1',menuEpochSlot='fs-menu-access-epoch';
let menuIdentityKey=null;
function clearMenuCache(){menuIdentityKey=null;try{sessionStorage.removeItem(menuCacheSlot);}catch{}}
function rememberMenuIdentity(user){
 if(!user?.name){clearMenuCache();return;}
 try{
  const key=JSON.stringify([user.name,user.role||'', [...user.groups].sort(),localStorage.getItem(menuEpochSlot)]);
  const old=JSON.parse(sessionStorage.getItem(menuCacheSlot)||'null');
  if(old?.key!==key)sessionStorage.setItem(menuCacheSlot,JSON.stringify({key,paths:{}}));
  menuIdentityKey=key;
 }catch{clearMenuCache();}
}
async function menuAccess(path,type,probe){
 const key=menuIdentityKey,slot=JSON.stringify([path,type]);
 try{const cache=JSON.parse(sessionStorage.getItem(menuCacheSlot)||'null');if(key&&cache?.key===key&&cache.paths?.[slot]===true)return true;}catch{}
 const available=await probe();
 try{const cache=JSON.parse(sessionStorage.getItem(menuCacheSlot)||'null');if(available&&key&&menuIdentityKey===key&&cache?.key===key){cache.paths[slot]=true;sessionStorage.setItem(menuCacheSlot,JSON.stringify(cache));}}catch{}
 return available;
}
addEventListener('storage',event=>{if(event.key===menuEpochSlot||event.key===null)clearMenuCache();});

 if(window.parent!==window||document.getElementById('hubNav')||location.pathname.startsWith('/__auth/')||location.pathname.startsWith('/fc27/'))return;
 const uiRoot='/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/';
 const styledModule=location.pathname.startsWith('/dashboard/')||location.pathname.startsWith('/tools/fc27-gallery/')||location.pathname.startsWith('/tools/fc27-players/');
 // Older tools retain their own content palette until their module-specific adapter is verified.
 for(const name of (styledModule?['fs-tokens.css','fs-ui.css','legacy.css','hubnav.css']:['fs-tokens.css','hubnav.css'])){const css=document.createElement('link');css.rel='stylesheet';css.href=uiRoot+name;document.head.append(css);}
 if(location.pathname.startsWith('/dashboard/tasks/')){const local=document.querySelector('#nav'),main=document.querySelector('main');if(local&&main){local.classList.add('fs-module-nav');local.setAttribute('aria-label','任务视图');main.prepend(local);}}
 const moduleStyle=document.createElement('style');moduleStyle.textContent='#hubNav{display:block}.fs-ui-page #nav.fs-module-nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px;padding:10px;background:var(--fs-surface);border:1px solid var(--fs-line);border-radius:12px}.fs-ui-page #nav.fs-module-nav button{width:auto;color:var(--fs-muted);background:var(--fs-surface-2)}.fs-ui-page #nav.fs-module-nav button.active{color:var(--fs-brand);background:var(--fs-brand-soft)}';document.head.append(moduleStyle);
 if(location.pathname.startsWith('/dashboard/game-monitor/')){document.body.dataset.fsModule='monitor';const topStyle=document.createElement('style');topStyle.textContent='.fs-ui-page[data-fs-module=monitor] .topbar{background:var(--fs-surface);color:var(--fs-text);border-color:var(--fs-line)}.fs-ui-page[data-fs-module=monitor] .topbar *{color:inherit}';document.head.append(topStyle);}
 if(['/dashboard/fc27-coins.html','/dashboard/madden27-coins.html'].includes(location.pathname)||location.pathname.startsWith('/tools/fc27-gallery/')){document.body.dataset.fsModule='pricing';const priceStyle=document.createElement('style');priceStyle.textContent='.fs-ui-page[data-fs-module=pricing] .panel>.head,.fs-ui-page[data-fs-module=pricing] .panel>h2{background:var(--fs-surface-2);color:var(--fs-text);border-color:var(--fs-line)}.fs-ui-page[data-fs-module=pricing] .controls label,.fs-ui-page[data-fs-module=pricing] .automation-grid>label,.fs-ui-page[data-fs-module=pricing] .switch-card,.fs-ui-page[data-fs-module=pricing] .switch{background:var(--fs-surface-2);color:var(--fs-text);border-color:var(--fs-line)}.fs-ui-page[data-fs-module=pricing] .switch-card:has(input:checked){background:var(--fs-ok-soft);border-color:var(--fs-ok)}.fs-ui-page[data-fs-module=pricing] input:not([type=checkbox]),.fs-ui-page[data-fs-module=pricing] select{background:var(--fs-surface);color:var(--fs-text);border-color:var(--fs-line)}.fs-ui-page[data-fs-module=pricing] .notice{background:var(--fs-surface-2);color:var(--fs-text);border-color:var(--fs-line)}.fs-ui-page[data-fs-module=pricing] .notice.success{background:var(--fs-ok-soft);color:var(--fs-ok)}.fs-ui-page[data-fs-module=pricing] .notice.error{background:var(--fs-danger-soft);color:var(--fs-danger)}.fs-ui-page[data-fs-module=pricing] button{background:var(--fs-brand);color:var(--fs-brand-on);border-color:var(--fs-brand)}.fs-ui-page[data-fs-module=pricing] button.secondary{background:var(--fs-surface);color:var(--fs-brand);border-color:var(--fs-line)}.fs-ui-page[data-fs-module=pricing] button.danger{background:var(--fs-danger);color:var(--fs-danger-on)}';document.head.append(priceStyle);}
 const themeScript=document.createElement('script');themeScript.src=uiRoot+'fs-theme.js';document.head.append(themeScript);
 if(styledModule)document.body.classList.add('fs-ui-page');document.documentElement.dataset.fsUiVersion='20261015-v1';
 if(location.pathname.startsWith('/dashboard/management/')){document.body.dataset.fsModule='management';const polish=document.createElement('style');polish.textContent='.fs-ui-page[data-fs-module=management] .gc{background:var(--fs-surface);border-color:var(--fs-line)}.fs-ui-page[data-fs-module=management] .topbar a[href*=sandbox]{background:var(--fs-warn);color:var(--fs-warn-on)}';document.head.append(polish);}
 const nav=document.createElement('nav');nav.id='hubNav';nav.setAttribute('aria-label','FS 统一导航');
 const tree=document.createElement('div'),status=document.createElement('p');status.className='hn-status';status.setAttribute('role','status');
 const toggle=document.createElement('button');toggle.id='hubNavToggle';toggle.type='button';toggle.textContent='☰ 导航';toggle.setAttribute('aria-controls','hubNav');toggle.setAttribute('aria-expanded','false');
 const scrim=document.createElement('button');scrim.id='hubNavScrim';scrim.type='button';scrim.hidden=true;scrim.setAttribute('aria-label','关闭导航');
 function close(){nav.classList.remove('open');nav.inert=innerWidth<900;scrim.hidden=true;toggle.setAttribute('aria-expanded','false');}
 nav.inert=innerWidth<900;
 toggle.onclick=()=>{const open=nav.classList.toggle('open');nav.inert=!open;scrim.hidden=!open;toggle.setAttribute('aria-expanded',String(open));if(open)nav.querySelector('a')?.focus();};scrim.onclick=()=>{close();toggle.focus();};
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&nav.classList.contains('open')){close();toggle.focus();}});
 addEventListener('resize',()=>{if(innerWidth>=900)close();else nav.inert=!nav.classList.contains('open');});
 function element(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
 function safe(path){return typeof path==='string'&&/^\/(?!\/)[a-zA-Z0-9_./-]+(?:\?(?:mode=(?:business|google)|report_kind=(?:daily|weekly|monthly)(?:#reports)?))?$/.test(path)&&!path.split('?')[0].split('/').includes('..');}
 function link(label,path,cls){const a=element('a',label,cls);a.href=path;a.onclick=close;return a;}
 nav.append(link('FS · MMOEXP','/dashboard/','hn-brand'),tree,status);document.body.prepend(nav,toggle,scrim);document.body.classList.add('fs-unified-navigation');
 let currentUser=null,registry=null,stopped=false;
 async function verify(){const r=await fetch('/__auth/verify',{credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});if(r.status!==200||r.redirected){clearMenuCache();throw Error('identity_unavailable');}const user={name:r.headers.get('X-Auth-User'),role:r.headers.get('X-Auth-Role'),groups:(r.headers.get('X-Auth-Groups')||'').split(',').map(x=>x.trim()).filter(Boolean)};rememberMenuIdentity(user);return user;}
 async function probe(path){return menuAccess(path,'text/html',()=>probePath(path));}
 async function probePath(path){try{let r=await fetch(path,{method:'HEAD',credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});if([404,405,501].includes(r.status))r=await fetch(path,{method:'GET',credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});return r.status===200&&!r.redirected&&r.headers.get('content-type')?.includes('text/html');}catch{return false;}}
 function matches(path){const url=new URL(path,location.origin),current=new URL(location.href);if(url.searchParams.has('report_kind'))return current.pathname===url.pathname&&current.searchParams.get('report_kind')===url.searchParams.get('report_kind');return current.pathname===url.pathname||(url.pathname.endsWith('/')&&current.pathname.startsWith(url.pathname));}

 // Homepage shortcut cards share the native card structure and existing permission probes.
 let homeCardsObserver=null;
 function clearHomeCards(){homeCardsObserver?.disconnect();homeCardsObserver=null;document.querySelectorAll('[data-fs-home-shortcut]').forEach(e=>e.remove());}
 function mountHomeCards(user,tools){
  clearHomeCards();
  if(!['/dashboard/','/dashboard/fs-home/index.html'].includes(location.pathname))return;
  const grid=document.getElementById('workspaces');if(!grid)return;
  function place(){
   if(stopped||currentUser?.name!==user.name)return;
   let after=grid.querySelector('.workspace-card.arpg');if(!after)return;
   for(const id of ['management','game-monitor']){
    const tool=tools.find(t=>t.id===id);if(!tool?.available)continue;
    let card=grid.querySelector('[data-fs-home-shortcut="'+id+'"]');
    if(!card){card=element('article',null,'workspace-card '+id);card.dataset.fsHomeShortcut=id;const a=link('',tool.path,'workspace-main');
     a.append(element('span',id==='management'?'◎':'◷','workspace-icon'),element('h3',id==='management'?'经营管理台':'游戏监控台'),element('p',id==='management'?'三组进度 · 健康度责任到人 · 目标沙盘与经营决策':'全球新游上线 · 版本赛季 · 开服节点一屏追踪'),element('span','进入工作区 →','entry'));card.append(a);}
    if(after.nextElementSibling!==card)after.after(card);after=card;
   }
  }
  place();homeCardsObserver=new MutationObserver(place);homeCardsObserver.observe(grid,{childList:true});
 }

 function render(user,tools){
  const homeLink=link('首页','/dashboard/','hn-home');if(['/dashboard/','/dashboard/fs-home/index.html'].includes(location.pathname))homeLink.setAttribute('aria-current','page');tree.replaceChildren(homeLink);
  for(const section of registry.sections.filter(s=>!['game-monitor','management'].includes(s.id))){
   if(!safe(section.path))continue;
   const rows=section.ids.map(id=>tools.find(t=>t.id===id)).filter(Boolean);
   const group=element('section',null,'hn-group'),heading=link(section.title,section.path,'hn-heading');
   if(matches(section.path)||rows.some(t=>matches(t.path)))heading.setAttribute('aria-current','true');
   heading.replaceChildren(element('span',section.icon||'◈','hn-icon'),element('span',section.title));
   group.append(heading);
   if(section.id==='analytics')for(const t of rows){const a=link(t.label,t.path,'hn-tool');if(matches(t.path))a.setAttribute('aria-current','page');if(!t.available){a.removeAttribute('href');a.setAttribute('aria-disabled','true');a.onclick=()=>{status.textContent='该功能需授权或暂不可用。';};}group.append(a);}
   if(!rows.some(t=>t.available)){heading.removeAttribute('href');heading.setAttribute('aria-disabled','true');heading.onclick=()=>{status.textContent='该功能需授权或暂不可用，请核实访问范围。';};}
   tree.append(group);
  }
  const account=element('div',null,'hn-account');account.append(link(user.name||'当前账号','/__auth/status'));
  if(user.role==='admin')account.append(link('账号与权限管理','/__auth/access/'));
  tree.append(account);
  const themeLabel=element('label','显示主题','hn-theme'),selector=element('select');selector.dataset.fsThemeControl='';selector.setAttribute('aria-label','全站显示主题');
  for(const [v,t] of [['light','浅色'],['dark','深色'],['system','跟随系统']]){const o=element('option',t);o.value=v;selector.append(o);}
  let remembered='light';try{remembered=localStorage.getItem('fs-navigation-theme')||remembered;}catch{}selector.value=window.FSTheme?.get()||remembered;selector.onchange=()=>window.FSTheme?.set(selector.value);themeLabel.append(selector);tree.append(themeLabel);status.textContent='';mountHomeCards(user,tools);
 }
 function denied(){clearHomeCards();clearMenuCache();currentUser=null;tree.replaceChildren(link('首页','/dashboard/'),link('重新登录','/__auth/login?next='+encodeURIComponent(location.pathname+location.search)));status.textContent='登录或访问范围未确认，业务入口已清除。';}
 async function load(){try{
  const user=await verify();if(!user.name||!user.groups.includes('dashboard'))throw Error('dashboard_not_permitted');
  const r=await fetch('/dashboard/fs-home/navigation.json',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(10000)});if(!r.ok||!r.headers.get('content-type')?.includes('application/json'))throw Error('registry_unavailable');
  registry=await r.json();if(registry.schemaVersion!==1||!Array.isArray(registry.sections)||!Array.isArray(registry.tools))throw Error('registry_invalid');
  const rows=registry.tools.filter(t=>safe(t.path)),tools=await Promise.all(rows.map(async t=>({...t,available:(t.requiredGroup!=='deploy'||user.groups.includes('deploy'))&&await probe(t.path)})));
  if(stopped)return;const next=await verify();if(stopped)return;if(next.name!==user.name||next.role!==user.role||JSON.stringify(next.groups)!==JSON.stringify(user.groups))throw Error('identity_changed');
  currentUser=next;render(next,tools);
 }catch{if(!stopped)denied();}}
 status.textContent='正在确认导航访问范围…';await load();
 function watch(){return setInterval(async()=>{if(document.hidden||!currentUser)return;try{const user=await verify();if(user.name!==currentUser.name||user.role!==currentUser.role||JSON.stringify(user.groups)!==JSON.stringify(currentUser.groups)){denied();return;}currentUser=user;}catch{denied();}},60000);}
 let timer=watch();
 addEventListener('pagehide',()=>{stopped=true;clearInterval(timer);homeCardsObserver?.disconnect();});
 addEventListener('pageshow',e=>{if(e.persisted){stopped=false;clearInterval(timer);timer=watch();load();}});
})();
