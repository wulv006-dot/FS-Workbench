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

const $=id=>document.getElementById(id), page=document.body.dataset.page;
let registry, identity={portal:false,global:false,groups:[],origin:''}, visible=[], watcher;
function el(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;}
function closeMenu(){ $('sidebar').classList.remove('open');$('scrim').hidden=true;$('menu').setAttribute('aria-expanded','false'); }
function link(path,label,cls){const a=el('a',label,cls);a.href=path;a.onclick=closeMenu;return a;}
function safePath(path){return typeof path==='string'&&(/^\/dashboard\/analytics\/\?mode=(business|google)$/.test(path)||/^\/dashboard\/fs-home\/brain\/index\.html\?report_kind=(daily|weekly|monthly)#reports$/.test(path)||/^\/(?!\/)[a-zA-Z0-9_./-]+$/.test(path)&&!path.split('/').includes('..'));}
async function head(path,type='text/html'){if(!safePath(path))return false;return menuAccess(path,type,()=>probeHead(path,type));}
async function probeHead(path,type='text/html'){if(!safePath(path))return false;try{let r=await fetch(path,{method:'HEAD',credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});if([404,405,501].includes(r.status))r=await fetch(path,{method:'GET',credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});return r.status===200&&!r.redirected&&r.headers.get('content-type')?.includes(type);}catch{return false;}}
async function verify(path){try{const r=await fetch(path,{credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});return r.status===200&&!r.redirected?r:null;}catch{return null;}}
function renderNavigation(){
 const nav=$('navigation');nav.replaceChildren();
 for(const s of [{id:'home',icon:'◈',title:'首页',path:'/dashboard/'},...registry.sections.filter(s=>visible.some(t=>t.section===s.id))]){const a=link(s.path,null,page===s.id?'active':'');a.append(el('span',s.icon,'nav-icon'),el('span',s.title));if(page===s.id)a.setAttribute('aria-current','page');nav.append(a);}
}
function renderEntries(){
 renderNavigation();const home=page==='home',host=$(home?'module-grid':'tool-grid');if(!host)return;host.replaceChildren();
 if(home){for(const s of registry.sections){const count=visible.filter(t=>t.section===s.id).length;if(!count)continue;const a=link(s.path,null,'module-card');a.append(el('span',s.icon,'module-icon'),el('small',count+' 项功能'),el('strong',s.title),el('p',s.intro),el('span','进入工作区 →','card-arrow'));host.append(a);}}
 else{const section=registry.sections.find(s=>s.id===page),rows=section?section.ids.map(id=>visible.find(t=>t.id===id)).filter(Boolean):[];let category=null;
 for(const t of rows){if(page==='sports'&&t.category!==category){category=t.category;const title=el('h2',category,'tool-category');title.id=category.toLowerCase();host.append(title);}const a=link(t.path,null,'tool-card');a.append(el('span',t.icon||'↗','tool-icon'),el('strong',t.label),el('p',t.short),el('span',t.available?'打开功能页面 ↗':'🔒 需授权','card-arrow'));a.dataset.access=t.available?'available':'locked';if(!t.available){a.href='#';a.setAttribute('aria-disabled','true');a.title='当前账号暂不可进入';a.onclick=e=>{e.preventDefault();$('toast').textContent='该功能需授权，请联系管理员核实访问范围。';};}host.append(a);}}
 if(!host.children.length)host.append(el('p','当前会话没有已验证的可用入口。请查看账号状态，或在原登录页面登录后再试。','empty'));
}
function renderMetrics(raw){
 const d=FSHomeMetrics.normaliseToday(raw),ok=d.status==='available',number=new Intl.NumberFormat('en-US'),money=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
 const values=[ok?number.format(d.metrics.orders):'—',ok?money.format(d.metrics.revenueUsd):'—',ok&&d.metrics.newCustomers!==null?number.format(d.metrics.newCustomers):'—'];
 document.querySelectorAll('.kpi-value').forEach((e,i)=>e.replaceChildren(document.createTextNode(values[i]),el('span',['笔','USD','人'][i])));
 document.querySelectorAll('.kpi-foot').forEach((e,i)=>e.textContent=ok?(i===2&&d.metrics.newCustomers===null?'Admin 新客补源缺失':'快照 '+d.date+' · 截至 '+d.period.end.slice(11,16)):'数据不可用');
 $('data-note').textContent=ok?'所有网站合计 · Order订单/金额，Admin补充新客 · 更新 '+new Date(d.generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间 · USD':'经营数据不可用，请查看原经营看板或稍后检查快照。';
}
function applyTransaction(data){
 const p=data.profiles.MMOEXP;
 document.querySelectorAll('.kpi-top').forEach((e,i)=>e.firstChild.textContent=(data.date===FSHomeMetrics.beijingDate()?'今日':'快照 '+data.date)+['全站订单数','全站销售额','全站新客人数'][i]);
 renderMetrics({status:'available',metricScope:'ALL_WEBSITES',timezone:data.timezone,currency:data.currency,date:data.date,period:p.period,generatedAt:data.generatedAt,source:p.primary,supplement:p.supplement,metrics:{orders:p.metrics.orders.value,revenueUsd:p.metrics.revenueUsd.value,newCustomers:p.metrics.newCustomers.value}});
}
async function refresh(){if(!watcher)return;$('refresh').disabled=true;$('refresh').textContent='读取中…';await watcher.check();$('refresh').disabled=false;$('refresh').textContent='检查新快照';}
async function boot(){
 // One provider: existing signed portal session and current global membership.
 const r=await verify('/__auth/verify');
 if(!r)clearMenuCache();
 if(r){
  const groups=(r.headers.get('X-Auth-Groups')||'').split(',').map(x=>x.trim()).filter(Boolean);
  if(groups.includes('dashboard')){identity.groups=groups;identity.global=true;identity.origin='portal';rememberMenuIdentity({name:r.headers.get('X-Auth-User'),role:r.headers.get('X-Auth-Role'),groups});$('profile-name').textContent=r.headers.get('X-Auth-User')||'当前账号';}
 }
 try{
  const r=await fetch('/dashboard/fs-home/navigation.json',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(10000)});if(!r.ok||!r.headers.get('content-type')?.includes('application/json'))throw Error('registry_unavailable');registry=await r.json();if(registry.schemaVersion!==1||!Array.isArray(registry.tools)||!Array.isArray(registry.sections))throw Error('invalid_registry');
  const permitted=registry.tools.filter(t=>safePath(t.path));
  const checked=await Promise.all(permitted.map(async t=>({...t,available:identity.global&&(t.requiredGroup!=='deploy'||identity.groups.includes('deploy'))&&await head(t.path)&&(t.probeJson?await head(t.probeJson,'application/json'):true)})));visible=checked;renderEntries();
  $('access-state').textContent=identity.global?'当前账号 · 已审批全局访问范围':'功能目录可浏览；业务访问须经审批';
 }catch{$('access-state').textContent='入口信息暂不可用，请查看当前账号后重试。';}
 if(page==='home'){
  if(identity.global){watcher=new FSBusinessSnapshots('/dashboard/fs-home/transactions/',applyTransaction,state=>{if(state.status!=='fresh')$('data-note').textContent=(state.status==='stale'?'数据已过期，保留最后成功快照':'经营数据不可用')+' · 更新 '+(state.generatedAt?new Date(state.generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'—')+' 北京时间';});await refresh();watcher.start();}
  else $('data-note').textContent='当前身份没有全站经营概览权限。已有业务入口按原门禁显示。';
 }
}
$('menu').onclick=()=>{const open=$('sidebar').classList.toggle('open');$('scrim').hidden=!open;$('menu').setAttribute('aria-expanded',String(open));};$('scrim').onclick=closeMenu;
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenu();});addEventListener('resize',()=>{if(innerWidth>=900)closeMenu();});addEventListener('pageshow',closeMenu);
let theme='light';try{theme=localStorage.getItem('fs-navigation-theme')||theme;}catch{}if(['light','dark'].includes(theme))document.documentElement.dataset.theme=theme;
$('theme').onclick=()=>{theme=(document.documentElement.dataset.theme|| (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'))==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;window.FSTheme?.set(theme);try{localStorage.setItem('fs-navigation-theme',theme);}catch{}};
$('copy-url').onclick=async()=>{try{await navigator.clipboard.writeText(location.href);$('toast').textContent='链接已复制';}catch{$('toast').replaceChildren(el('span','复制此页面地址：'));const input=el('input');input.readOnly=true;input.value=location.href;$('toast').append(input);input.select();}};
if($('refresh'))$('refresh').onclick=refresh;
boot();

{const href=new URL('/__hub/hubnav.js?v=nav-unified-20261120-aaec928afc3e',document.baseURI).href;if(!document.getElementById('hubNav')&&![...document.scripts].some(s=>s.src===href)){const sharedNav=document.createElement('script');sharedNav.src=href;sharedNav.defer=true;document.head.append(sharedNav);}}
