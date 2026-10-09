import {lifecycle,protectedRead,sessionIdentity,moduleAvailable} from './runtime.js';
// User-approved 2026-10-09: Admin main-site values; labelled Order supplements and estimated profit.
function fsMainSite(profile){
 const numeric=v=>typeof v==='number'&&Number.isFinite(v);
 const missing=(source,scope)=>({value:null,status:'not_provided',source,scope});
 const take=(m,source,scope)=>m?.status==='available'&&numeric(m.value)?{...m,source,scope}:missing(source,scope);
 const admin=profile?.supplement,order=profile?.primary;
 const rows=admin?.dimensions?.channels;
 const same=admin?.period?.start===order?.period?.start&&admin?.period?.end===order?.period?.end;
 const available=admin?.status==='available'&&same&&!!admin?.period?.start;
 const main=available&&Array.isArray(rows)?rows.filter(r=>(r.code||r.name)==='www.mmoexp.com'):[];
 const mainRow=main.length===1?main[0]:null;
 const onlyMain=!!mainRow&&rows.length===1;
 const mainMetrics={};
 for(const key of ['orders','revenueUsd','newCustomers','payingCustomers','newCustomerRevenueUsd','repeatRatePct','newCustomerSharePct','pureSalesUsd','refundAmountUsd','refundOrders','fulfillmentRatePct','paymentSuccessRatePct','averageOrderUsd','averageCustomerUsd','minOrderAmountUsd','maxOrderAmountUsd']){
  mainMetrics[key]=available?take(admin.metrics?.[key],'Admin',onlyMain?'MMOEXP':'后台原统计范围（含其他站点），仅参考'):missing('Admin','MMOEXP');
 }
 for(const key of ['orders','revenueUsd'])mainMetrics[key]=missing('Admin','MMOEXP');
 for(const key of ['orders','revenueUsd'])if(mainRow&&numeric(mainRow[key])&&(key!=='orders'||Number.isSafeInteger(mainRow[key])&&mainRow[key]>=0))mainMetrics[key]={value:mainRow[key],status:'available',source:'Admin',scope:'MMOEXP'};
 // A zero-only response can omit site ranks. Nonzero values are never treated as site-specific without a rank.
 if(available&&(!rows||rows.length===0)&&admin.metrics?.orders?.value===0&&admin.metrics?.revenueUsd?.value===0){
  for(const key of ['orders','revenueUsd'])mainMetrics[key]={value:0,status:'available',source:'Admin',scope:'MMOEXP'};
 }
 for(const key of ['profitMarginPct','averageOrderUsd','averageCustomerUsd','minOrderAmountUsd','maxOrderAmountUsd','fulfillmentRatePct']){
  if(mainMetrics[key]?.value!=null)continue;
  mainMetrics[key]=order?.status==='available'&&order.currency==='USD'?take(order.metrics?.[key],'Order','后台全站参考；与 Admin 主站口径不同'):missing('Order','后台全站参考');
 }
 const revenue=mainMetrics.revenueUsd.value,rate=mainMetrics.profitMarginPct.value;
 const raw=revenue!==null&&rate!==null?Math.round(Math.round(revenue*100)*Math.round(rate*100)/10000)/100:null;
 mainMetrics.estimatedProfitUsd={value:numeric(raw)?raw:null,status:numeric(raw)?'available':'not_provided',source:'Admin × Order',scope:'预估：MMOEXP销售额 × Order利润率；不是后台实结利润'};
 return {metrics:mainMetrics,period:admin?.period,adminCapturedAt:admin?.capturedAt,orderCapturedAt:order?.capturedAt,onlyMain,
  site:'MMOEXP',policy:'admin-main-order-labelled-supplement-v1'};
}

function fsReferenceTotal(profile){
 const main=fsMainSite(profile).metrics.revenueUsd.value,rows=profile?.dimensions?.channels;
 const primary=profile?.primary,admin=profile?.supplement;
 if(main===null||primary?.status!=='available'||primary?.currency!=='USD'||primary.period?.start!==admin?.period?.start||primary.period?.end!==admin?.period?.end||!Array.isArray(rows))return null;
 const names=rows.map(r=>r.name),known=['www.mmoexp.com','eldorado.gg','g2g.com'];
 if(new Set(names).size!==names.length||!known.every(s=>names.includes(s)))return null;
 if(rows.some(r=>typeof r.amountUsd!=='number'||!Number.isFinite(r.amountUsd)))return null;
 // Other brands and backend reconciliation differences do not invalidate explicit satellite amounts.
 return (Math.round(main*100)+rows.filter(r=>['eldorado.gg','g2g.com'].includes(r.name)).reduce((n,r)=>n+Math.round(r.amountUsd*100),0))/100;
}

const $=id=>document.getElementById(id),home=document.body.dataset.page==='home',base=new URL('./',import.meta.url);
const homeURL=document.body.dataset.workspaceHome||new URL('home.html',base).href,analyticsURL=document.body.dataset.workspaceAnalytics||new URL('index.html',base).href;
const allowed=['b_group','b_profile','b_grain','b_align','b_range','b_start','b_end','b_section','b_metrics','g_brand','g_period','g_source','g_business_profile'];
let state={},active=null,epoch=0,identity=null,verified=[],theme='system',restored=false,last={},checkedAt={},watcher=null,homeController=null,dialogTrigger=null;
const media=matchMedia('(prefers-color-scheme: dark)');
function node(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;}
function link(label,path,cls){const a=node('a',label,cls);a.href=path;return a;}
function toolLink(t,label,cls){const a=link(label,t.available?t.path:'#',cls);a.dataset.access=t.available?'available':'locked';if(!t.available){a.setAttribute('aria-disabled','true');a.title='需授权 · 当前账号暂不可进入';a.onclick=e=>{e.preventDefault();toast('该功能需授权，请联系管理员核实访问范围。');};}return a;}
function readURL(){const p=new URL(location.href).searchParams;state={mode:p.get('mode')==='google'?'google':'business'};for(const key of allowed)state[key]=(p.get(key)||'').slice(0,128);const q=p.get('theme');if(['light','dark','system'].includes(q))theme=q;}
function save(push=false){const u=new URL(location.href);u.search='';u.searchParams.set('mode',state.mode);u.searchParams.set('theme',theme);for(const key of allowed)if(state[key])u.searchParams.set(key,state[key]);if(u.href!==location.href)history[push?'pushState':'replaceState'](null,'',u);}
function applyTheme(){const value=theme==='system'?(media.matches?'dark':'light'):theme;document.documentElement.dataset.theme=value;if(active)active.host.dataset.theme=value;if($('theme'))$('theme').value=theme;try{localStorage.setItem('fs-navigation-theme',theme);}catch{}}
function toast(text){$('toast').textContent=text;setTimeout(()=>{if($('toast').textContent===text)$('toast').textContent='';},4000);}
function header(){const h=$('platform-header');h.append(link('FS',homeURL,'brand-mark'));const brand=link('MMOEXP',homeURL,'brand');brand.append(node('small','运营工作台'));h.append(brand);const nav=node('nav',null,'global-nav');nav.setAttribute('aria-label','平台导航');
 for(const [label,path,key] of [['工作台',homeURL,'home'],['数据分析',analyticsURL,'analytics'],['球类运营','/dashboard/modules/sports/','sports'],['ARPG 运营','/dashboard/modules/arpg/','arpg'],['协作工具','/dashboard/modules/collaboration/','collaboration']]){const a=link(label,path);a.dataset.section=key;if((home?'home':'analytics')===key)a.setAttribute('aria-current','page');else if(key!=='home')a.hidden=true;nav.append(a);}h.append(nav);
 const actions=node('div',null,'header-actions'),select=node('select');select.id='theme';select.setAttribute('aria-label','显示主题');for(const [v,l] of [['system','跟随系统'],['light','浅色主题'],['dark','深色主题']]){const o=node('option',l);o.value=v;select.append(o);}select.onchange=()=>{theme=select.value;applyTheme();if(!home)save();};const manage=link('账号与权限管理','/__auth/access/','account-management');manage.hidden=true;manage.title='审批注册申请、设置模块权限';actions.append(select,manage,link('当前账号','/__auth/status','account'));h.append(actions);applyTheme();}
function accountNavigation(user){const manage=document.querySelector('.account-management');manage.hidden=user?.role!=='admin';}
async function readonly(url,type='application/json',method='GET',signal){return protectedRead(url,{method,signal:signal||AbortSignal.timeout(15000)},halt,type);}
function halt(status){epoch++;active?.scope.destroy();active=null;homeController?.abort();watcher?.stop();watcher=null;identity=null;accountNavigation(null);verified=[];$('content-panel')?.replaceChildren();$('status').replaceChildren(node('span',status===403?'当前账号未获授权。':'登录已失效，请重新登录。'),link(' 重新登录','/__auth/login?next='+encodeURIComponent(location.pathname+location.search)));document.querySelectorAll('.global-nav a:not([aria-current])').forEach(a=>a.hidden=true);document.querySelectorAll('#orders,#revenueUsd,#newCustomers').forEach(e=>e.textContent='—');$('workspaces')?.replaceChildren();$('tools')?.replaceChildren();$('recent')?.replaceChildren();if($('data-dialog')?.open)$('data-dialog').close();last={};checkedAt={};dialogTrigger=null;$('dialog-content')?.replaceChildren();$('status').dataset.state='error';const account=document.querySelector('.account');if(account)account.textContent='当前账号';if($('recent')?.parentElement)$('recent').parentElement.hidden=true;try{sessionStorage.removeItem('fs-workspace-recent');}catch{}}
function statusView(q){last[state.mode]=q;if(q.checkedAt)checkedAt[state.mode]=q.checkedAt;const error=q.phase==='error',loading=q.phase==='loading',stale=q.phase==='stale',missing=q.phase==='unavailable';const mode=state.mode==='business'?'MMOEXP · Admin主站 / Order补充参考':'Google · 来源独立';$('status').textContent=mode+' · '+(error?'读取失败，请查看来源提示':stale?'快照过期或本次检查失败，保留最后成功值':missing?'经营快照不可用，未填零':loading?'正在读取所选区间':q.businessUntil?'数据截至 '+q.businessUntil+' 北京时间':'各来源日期与覆盖分别见下方');$('status').dataset.state=error||stale||missing?'error':loading?'loading':'available';}
function capture(q){if(!active||document.hidden)return;if(!restored){if(active.api?.apply(state)){restored=true;return;}return;}const prefix=state.mode==='business'?'b_':'g_';for(const key of allowed.filter(k=>k.startsWith(prefix)))if(q[key]!==undefined)state[key]=String(q[key]);statusView(q);save();}
async function nativeLoad(retried=false){
 const id=++epoch;active?.scope.destroy();active=null;restored=false;$('content-panel').replaceChildren();
 document.querySelectorAll('.mode-tabs [role=tab]').forEach(t=>{const on=t.id==='tab-'+state.mode;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;});$('content-panel').setAttribute('aria-labelledby','tab-'+state.mode);
 if(document.hidden){$('status').textContent='当前页面检查已暂停；服务器采集按原计划运行。';return;}
 if(!identity)return;
 const host=document.createElement('div');host.className='native-content';host.dataset.theme=document.documentElement.dataset.theme;$('content-panel').append(host);
 const scope=lifecycle(host,capture,halt);scope.seed={...state};active={host,scope,api:null};$('status').textContent='正在读取'+(state.mode==='business'?'经营分析':'Google 运营')+'…';
 try{
  const [markup,stylesheet,module]=await Promise.all([readonly(new URL(state.mode+'.html',base),'text/html','GET',scopeSignal()),readonly(new URL(state.mode+'.css',base),'text/css','GET',scopeSignal()),import(new URL(state.mode+'.js'+(retried?'?retry=1':''),base).href)]);
  if(id!==epoch)return;const style=document.createElement('style');style.textContent=await stylesheet.text();scope.root.append(style);const template=document.createElement('template');template.innerHTML=await markup.text();scope.root.append(template.content);
  if(state.mode==='business'){
   // ponytail: authenticated historical PROFIT still lives in the old source page;
   // extract data only until its owner exposes an equivalent protected JSON endpoint.
   try{const original=await readonly('/dashboard/index.html','text/html','GET',scopeSignal()),text=await original.text();const m=text.match(/^const PROFIT = (\{[^\n]*\});\s*$/m);if(!m)throw Error('profit_contract_missing');scope.profit=JSON.parse(m[1]);}
   catch(e){if(e.status){halt(e.status);return;}scope.profit={};scope.root.querySelector('#profitHint').textContent='原历史利润数据读取失败，未估算或填零。';}
  }
  if(id!==epoch)return;active.api=module.mount(scope);scope.root.addEventListener('click',()=>queueMicrotask(()=>{if(id===epoch&&active?.api)capture(active.api.state());}));
 }catch(e){if(id!==epoch)return;if(e.status){halt(e.status);return;}active?.scope.destroy();active=null;
  const transient=e.name==='TypeError'||e.name==='TimeoutError'||/^protected_read_failed_50[234]$/.test(e.message);
  if(!retried&&transient){$('status').textContent='页面资源暂时未加载，正在自动重试一次…';await new Promise(resolve=>setTimeout(resolve,1500));if(id===epoch&&identity)await nativeLoad(true);return;}
  $('status').textContent='页面组件加载失败，筛选条件仍保留；请重新加载。';
  const retry=node('button','重新加载数据页');retry.type='button';retry.onclick=()=>location.reload();$('content-panel').append(retry);}
}
function scopeSignal(){return active?AbortSignal.any([active.scope.signal,AbortSignal.timeout(20000)]):AbortSignal.timeout(20000);}
async function verify(){return sessionIdentity();}
async function boot(){const id=++epoch;try{const next=await verify();if(id!==epoch)return;identity=next;accountNavigation(next);const registry=await(await readonly(new URL('navigation.json',base))).json();if(id!==epoch)return;if(registry.schemaVersion!==1)throw Error('入口合同错误');const permitted=registry.tools.filter(t=>/^\/(?!\/)[\w./-]+(?:\?mode=(?:business|google))?$/.test(t.path)&&!t.path.split('/').includes('..'));
 const checked=await Promise.all(permitted.map(async t=>{const path=t.id.startsWith('unified-')?analyticsURL:t.path;const permitted=t.requiredGroup!=='deploy'||next.groups.includes('deploy');const available=permitted&&await moduleAvailable(path)&&(!t.probeJson||await moduleAvailable(t.probeJson,'application/json'));return {...t,available};}));
 if(id!==epoch||!identity||identity.name!==next.name)return;verified=checked.filter(Boolean);
 for(const a of document.querySelectorAll('.global-nav a[data-section]'))if(verified.some(t=>t.section===a.dataset.section))a.hidden=false;
 document.querySelector('.account').textContent=next.name;if(home){homeEntries(registry);homeData();}else nativeLoad();
 }catch(e){if(id!==epoch)return;if(e.status)halt(e.status);else $('status').textContent=e.message;}}
function homeEntries(registry){const user=identity?.name;if(!user)return;const grid=$('workspaces');grid.replaceChildren();$('tools').replaceChildren();
 for(const s of registry.sections){const tools=verified.filter(t=>t.section===s.id);if(!tools.length)continue;const card=node('article',null,'workspace-card '+s.id),a=link('',s.id==='analytics'?analyticsURL:s.path,'workspace-main');a.append(node('span',s.icon,'workspace-icon'),node('h3',s.title),node('p',s.id==='analytics'?'经营表现与 Google 运营分析。':s.intro),node('span','进入工作区 →','entry'));card.append(a);
  grid.append(card);
 }
 for(const [id,label] of [['release-radar','游戏监控台'],['coins','FC 改价台'],['d4','RPG 改价台'],['tasks','工作任务分配台']]){const t=verified.find(t=>t.id===id);if(!t)continue;const entry=toolLink(t,label+(t.available?'':' · 需授权'));entry.dataset.tool=id;if(t.available)entry.onclick=()=>{if(identity?.name!==user)return;try{const key='fs-workspace-recent',old=JSON.parse(sessionStorage.getItem(key)||'{}'),ids=old.user===user?old.ids||[]:[];sessionStorage.setItem(key,JSON.stringify({user:user,ids:[id,...ids.filter(v=>v!==id)].slice(0,3)}));}catch{}};$('tools').append(entry);}
 try{const old=JSON.parse(sessionStorage.getItem('fs-workspace-recent')||'{}');if(old.user===user){const entries=(old.ids||[]).map(id=>verified.find(t=>t.id===id)).filter(Boolean).slice(0,3);if(entries.length){$('recent').replaceChildren();$('recent').parentElement.hidden=false;for(const t of entries)$('recent').append(toolLink(t,t.label+(t.available?' →':' · 需授权')));}}else sessionStorage.removeItem('fs-workspace-recent');}catch{}
}
function homeData(){watcher?.stop();homeController?.abort();homeController=new AbortController();const id=++epoch;watcher=new FSBusinessSnapshots('/dashboard/fs-home/transactions/',data=>{
 if(id!==epoch||!identity)return;
 const p=data.profiles.MMOEXP,main=fsMainSite(p).metrics,d={status:main.orders.value!==null&&main.revenueUsd.value!==null?'available':'unavailable',metrics:{orders:main.orders.value,revenueUsd:main.revenueUsd.value,newCustomers:main.estimatedProfitUsd.value}};
 for(const k of ['orders','revenueUsd','newCustomers']){const v=d.metrics[k];$(k).textContent=d.status==='available'&&v!=null?new Intl.NumberFormat('en-US',{maximumFractionDigits:k==='orders'?0:2,minimumFractionDigits:k==='orders'?0:2}).format(v):'—';$('label-'+k).textContent=(data.date===FSHomeMetrics.beijingDate()?'今日':'快照 '+data.date)+'MMOEXP '+{orders:'订单数',revenueUsd:'销售额',newCustomers:'预估利润'}[k];}
 $('status').textContent='MMOEXP · Admin订单/销售额；预估利润=Admin销售额×Order利润率（跨来源参考） · 数据截至 '+p.period.end+' 北京时间 · 快照生成 '+data.generatedAt;
 },s=>{if(id!==epoch||!identity)return;if(s.status!=='fresh'){$('status').dataset.state='error';$('status').textContent=(s.status==='stale'?'快照过期或本次检查失败，保留最后成功值':'经营数据不可用')+' · 最后生成 '+(s.generatedAt||'—');}else $('status').dataset.state='available';});
 const signal=homeController.signal;watcher.read=async path=>{try{return await readonly(path,'application/json','GET',AbortSignal.any([signal,AbortSignal.timeout(20000)]));}catch(e){if(e.status&&id===epoch)halt(e.status);throw e;}};
 watcher.start();$('refresh').disabled=false;}
header();try{theme=localStorage.getItem('fs-navigation-theme')||'system';}catch{}if(!['light','dark','system'].includes(theme))theme='system';if(!home)readURL();applyTheme();media.addEventListener('change',()=>{if(theme==='system')applyTheme();});
$('refresh').onclick=async()=>{const id=epoch,user=identity?.name;if(!user){boot();return;}$('refresh').disabled=true;try{const next=await verify();if(id!==epoch||!identity)return;if(next.name!==user){halt(403);await boot();return;}identity=next;accountNavigation(next);if(home)await watcher?.check();else if(active?.api)await active.api.update();else await nativeLoad();}catch(e){if(e.status)halt(e.status);else $('status').textContent=e.message;}finally{$('refresh').disabled=false;}};
if(!home){
 for(const mode of ['business','google'])$('tab-'+mode).onclick=()=>{if(state.mode===mode)return;if(active?.api&&restored)capture(active.api.state());state.mode=mode;save(true);nativeLoad();};
 document.querySelector('.mode-tabs').onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('.mode-tabs button')],i=tabs.indexOf(document.activeElement);tabs[e.key==='Home'?0:e.key==='End'?1:(i+1)%2].focus();};
 $('details').onclick=()=>{dialogTrigger=document.activeElement;$('dialog-content').replaceChildren();for(const mode of ['business','google']){const q=last[mode];if(!q)continue;const s=node('section');s.append(node('h3',mode==='business'?'经营':'Google'),node('p','业务截至：'+(q.businessUntil||'见各来源覆盖')),node('p','快照生成：'+(q.generatedAt||q.details||'—')),node('p','页面最近检查：'+(checkedAt[mode]||'—')),node('p','快照版本：'+(q.snapshotId||'见来源详情')),node('p',q.details));$('dialog-content').append(s);}$('data-dialog').showModal();};
 $('close-dialog').onclick=()=>$('data-dialog').close();$('data-dialog').addEventListener('close',()=>dialogTrigger?.focus());
 $('copy-link').onclick=async()=>{try{await navigator.clipboard.writeText(location.href);toast('视图链接已复制');}catch{toast('请复制地址栏中的视图链接');}};
 addEventListener('popstate',()=>{readURL();applyTheme();nativeLoad();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('details.more[open]').forEach(d=>d.open=false);});
}
// Keep the mounted view and range cache when another tab/app takes focus.
let visibilityCheck=null;
document.addEventListener('visibilitychange',async()=>{
 if(document.hidden||!identity||visibilityCheck)return;
 const id=epoch,user=identity.name;
 const pending=verify();visibilityCheck=pending;
 try{
  const next=await pending;
  if(id!==epoch||document.hidden||!identity)return;
  if(next.name!==user){halt(403);await boot();return;}
  identity=next;accountNavigation(next);
  if(home){if(watcher)await watcher.check();else homeData();}
  else if(active?.api){capture(active.api.state());await active.api.update();}
  else if(!active)await nativeLoad();
 }catch(e){
  if(id!==epoch)return;
  if(e.status)halt(e.status);
  else {$('status').textContent='检查失败，保留当前视图；可稍后检查新版本。';$('status').dataset.state='error';}
 }finally{if(visibilityCheck===pending)visibilityCheck=null;}
});
addEventListener('pagehide',()=>{epoch++;active?.scope.destroy();active=null;homeController?.abort();watcher?.stop();});addEventListener('pageshow',e=>{if(e.persisted){if(home&&identity)homeData();else nativeLoad();}});boot();
