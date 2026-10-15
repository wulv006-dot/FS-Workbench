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
 for(const name of ['fs-tokens.css','fs-ui.css','legacy.css','hubnav.css']){const css=document.createElement('link');css.rel='stylesheet';css.href=uiRoot+name;document.head.append(css);}
 const themeScript=document.createElement('script');themeScript.src=uiRoot+'fs-theme.js';document.head.append(themeScript);
 document.body.classList.add('fs-ui-page');document.documentElement.dataset.fsUiVersion='20261015-v1';
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
 function matches(path){const url=new URL(path,location.origin);return location.pathname===url.pathname||(url.pathname.endsWith('/')&&location.pathname.startsWith(url.pathname));}
 function render(user,tools){
  tree.replaceChildren(link('首页','/dashboard/','hn-home'));
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
  let remembered='light';try{remembered=localStorage.getItem('fs-navigation-theme')||remembered;}catch{}selector.value=window.FSTheme?.get()||remembered;selector.onchange=()=>window.FSTheme?.set(selector.value);themeLabel.append(selector);tree.append(themeLabel);status.textContent='';
 }
 function denied(){clearMenuCache();currentUser=null;tree.replaceChildren(link('首页','/dashboard/'),link('重新登录','/__auth/login?next='+encodeURIComponent(location.pathname+location.search)));status.textContent='登录或访问范围未确认，业务入口已清除。';}
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
 addEventListener('pagehide',()=>{stopped=true;clearInterval(timer);});
 addEventListener('pageshow',e=>{if(e.persisted){stopped=false;clearInterval(timer);timer=watch();load();}});
})();
