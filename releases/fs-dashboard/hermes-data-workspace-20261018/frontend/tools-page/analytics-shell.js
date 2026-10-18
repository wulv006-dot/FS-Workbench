function fsPeriodPolicy(){
 const day=(now=Date.now())=>new Date(now+8*3600000).toISOString().slice(0,10);
 const shift=(d,n)=>new Date(Date.parse(d+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
 const selection=(mode,custom,min,max,anchor=day())=>custom?{...custom,grain:'day'}:mode==='today'?{start:anchor,end:anchor,grain:'day'}:mode==='yesterday'?{start:shift(anchor,-1),end:shift(anchor,-1),grain:'day'}:+mode>0?{start:shift(anchor,-Number(mode)),end:shift(anchor,-1),grain:'day'}:{start:min,end:max<anchor?max:shift(anchor,-1),grain:'day'};
 const active=(s,now=Date.now())=>!!s?.end&&s.end.slice(0,10)>=day(now);
 return {day,shift,selection,active,ttl:(s,now=Date.now())=>active(s,now)?900:7200};
}
class LiveSummary {
 constructor(selection,update,state){this.selection=selection;this.update=update;this.state=state;this.pending=null;this.current=null;this.epoch=0;this.key=null;}
 async read(path){return fetch(path,{credentials:'same-origin',cache:'no-store',redirect:'error',signal:this.controller.signal});}
 check(){
  const selection=this.selection(),key=JSON.stringify(selection);
  if(this.pending&&key===this.key)return this.pending;
  if(key!==this.key){this.controller?.abort();this.epoch++;this.current=null;this.key=key;this.state({phase:'loading',clear:true,message:'正在读取所选日期的经营指标…'});}
  const epoch=this.epoch;this.controller=new AbortController();
  const promise=(async()=>{try{
   const started=Date.now(),params=new URLSearchParams({...selection,mode:'summary'});
   do {
    const r=await this.read('/dashboard/fs-home/range.json?'+params);
    if(epoch!==this.epoch)return;
    if(r.status===401||r.status===403){this.current=null;this.state({phase:'denied',status:r.status,message:'登录或来源权限失效，已清除经营指标。'});return;}
    const data=await r.json();
    if(epoch!==this.epoch)return;
    if(r.status===202||r.status===429){this.state({phase:'loading',message:'后台正在读取或队列繁忙；尚无新结果。'});await new Promise(resolve=>setTimeout(resolve,2000));continue;}
    if(!r.ok||!['available','stale'].includes(data.status)||data.scopeContractId!=='admin-main-order-labelled-supplement-v1'||data.profile?.key!==selection.profile||data.query?.start!==selection.start||data.query?.end!==selection.end)throw Error('summary_unavailable');
    this.current=data;this.nextRefreshAt=Date.now()+((Object.values(data.sources||{}).some(x=>x.status==='pending')?900:Math.max(1,(data.expiresInSeconds??900)+1))*1000);this.update(data);this.state({phase:'available'});
    // Retry temporary Order contention only inside the initial read budget;
    // do not wait a whole 15-minute cache cycle after a short lock conflict.
    const pending=data.sources?.Admin?.status==='pending'||data.sources?.Order?.status==='pending';
    const order=data.sources?.Order;
    const deferred=order?.phase==='deferred'&&['collector_busy','scheduled_collection_due'].includes(order.error);
    const delay=pending?2000:30000;
    if((pending||deferred)&&Date.now()-started+delay<100000){await new Promise(resolve=>setTimeout(resolve,delay));continue;}
    return;
   }while(Date.now()-started<100000&&epoch===this.epoch);
   throw Error('summary_wait_timeout');
  }catch(e){
   if(epoch!==this.epoch)return;
   if(e.status===401||e.status===403){this.current=null;this.state({phase:'denied',status:e.status,message:'登录或访问权限失效，已清除经营指标。'});return;}
   if(this.current){this.current={...this.current,stale:true,status:'stale'};this.update(this.current);}
   this.state({phase:this.current?'stale':'unavailable',message:this.current?'⚠ 检查失败，保留已过期值；读取时间见来源。':'经营指标暂不可用；缺失没有填零。'});
  }})();
  promise.finally(()=>{if(this.pending===promise){this.pending=null;if(this.running){clearTimeout(this.timer);this.timer=setTimeout(()=>this.check(),Math.max(1000,(this.nextRefreshAt||Date.now()+900000)-Date.now()));}}});
  this.pending=promise;return promise;
 }
 start(){if(this.running)return;this.running=true;this.check();}
 stop(){this.running=false;clearTimeout(this.timer);this.timer=null;this.epoch++;this.controller?.abort();this.current=null;this.pending=null;}
}

import {lifecycle,protectedRead,sessionIdentity,moduleAvailable} from '/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/runtime.js';
// User-approved 2026-10-09: Admin main-site values; labelled Order supplements and estimated profit.
function fsMainSite(profile,all=false){
 const numeric=v=>typeof v==='number'&&Number.isFinite(v);
 const missing=(source,scope)=>({value:null,status:'not_provided',source,scope});
 const take=(m,source,scope)=>m?.status==='available'&&numeric(m.value)?{...m,source,scope}:missing(source,scope);
 const admin=profile?.supplement,order=profile?.primary;
 const rows=admin?.dimensions?.channels;
 const same=admin?.period?.start===order?.period?.start&&admin?.period?.end===order?.period?.end;
 const available=admin?.status==='available'&&!!admin?.period?.start&&(!all||(admin.normalisedScope==='all-websites'&&['',0,'0'].includes(admin.filters?.site)));
 const main=!all&&available&&Array.isArray(rows)?rows.filter(r=>(r.code||r.name)==='www.mmoexp.com'):[];
 const mainRow=main.length===1?main[0]:null;
 const onlyMain=!!mainRow&&rows.length===1;
 const mainMetrics={};
 for(const key of ['orders','revenueUsd','newCustomers','payingCustomers','newCustomerRevenueUsd','repeatRatePct','newCustomerSharePct','pureSalesUsd','refundAmountUsd','refundOrders','fulfillmentRatePct','paymentSuccessRatePct','averageOrderUsd','averageCustomerUsd','minOrderAmountUsd','maxOrderAmountUsd']){
  mainMetrics[key]=available?take(admin.metrics?.[key],'Admin',all?'全部网站':onlyMain?'MMOEXP':'后台原统计范围（含其他站点），仅参考'):missing('Admin',all?'全部网站':'MMOEXP');
 }
 if(!all){
 for(const key of ['orders','revenueUsd'])mainMetrics[key]=missing('Admin','MMOEXP');
 for(const key of ['orders','revenueUsd'])if(mainRow&&numeric(mainRow[key])&&(key!=='orders'||Number.isSafeInteger(mainRow[key])&&mainRow[key]>=0))mainMetrics[key]={value:mainRow[key],status:'available',source:'Admin',scope:'MMOEXP'};
 // A zero-only response can omit site ranks. Nonzero values are never treated as site-specific without a rank.
 if(available&&(!rows||rows.length===0)&&admin.metrics?.orders?.value===0&&admin.metrics?.revenueUsd?.value===0){
  for(const key of ['orders','revenueUsd'])mainMetrics[key]={value:0,status:'available',source:'Admin',scope:'MMOEXP'};
 }
 }else if(mainMetrics.orders.value!==null&&(!Number.isSafeInteger(mainMetrics.orders.value)||mainMetrics.orders.value<0)){mainMetrics.orders=missing('Admin','全部网站');}
 for(const key of ['profitMarginPct','averageOrderUsd','averageCustomerUsd','minOrderAmountUsd','maxOrderAmountUsd','fulfillmentRatePct']){
  if(mainMetrics[key]?.value!=null)continue;
  mainMetrics[key]=same&&order?.status==='available'&&order.currency==='USD'?take(order.metrics?.[key],'Order',all?'后台全部网站参考；与 Admin 网站集合可能不同':'后台全站参考；与 Admin 主站口径不同'):missing('Order','后台全站参考');
 }
 const revenue=mainMetrics.revenueUsd.value,rate=mainMetrics.profitMarginPct.value;
 const raw=revenue!==null&&rate!==null?Math.round(Math.round(revenue*100)*Math.round(rate*100)/10000)/100:null;
 mainMetrics.estimatedProfitUsd={value:numeric(raw)?raw:null,status:numeric(raw)?'available':'not_provided',source:'Admin × Order',scope:'预估：'+(all?'全部网站':'MMOEXP')+'销售额 × Order利润率；不是后台实结利润'};
 for(const item of Object.values(mainMetrics)){if(item.value===null&&item.source==='Order')item.pendingPhase=order?.status==='pending'?(order.readPhase||'reading'):order?.status==='unavailable'?(order.readPhase||'failed'):'not_provided';}
 mainMetrics.estimatedProfitUsd.pendingPhase=revenue!==null?mainMetrics.profitMarginPct.pendingPhase:'not_provided';
 for(const item of Object.values(mainMetrics)){if(item.source==='Order'&&item.value!==null&&order?.stale&&profile?.cachePolicy!=='historical')item.stale=true;}
 mainMetrics.estimatedProfitUsd.stale=!!(mainMetrics.profitMarginPct.stale&&mainMetrics.estimatedProfitUsd.value!==null);
 return {metrics:mainMetrics,period:admin?.period,adminCapturedAt:admin?.capturedAt,orderCapturedAt:order?.capturedAt,onlyMain,
  site:all?'全部网站':'MMOEXP',policy:'admin-main-order-labelled-supplement-v1'};
}

function fsOrderLabel(source){return ({available:'读取完成',queued:'排队中',reading:'读取中',deferred:'采集繁忙，稍后重试',failed:'读取失败',pending:'读取中',unavailable:'读取失败'}[source?.phase||source?.status]||'尚未读取')+(source?.stale&&source?.capturedAt?' · 已过期':'');}
function fsMetricText(item,format){
 if(item?.value!=null)return format(item.value)+(item.stale?'（已过期，更新中）':'');
 return {queued:'Order 排队中',reading:'Order 读取中',deferred:'Order 暂忙，稍后重试',failed:'Order 读取失败','period-mismatch':'Order 日期待对齐'}[item?.pendingPhase]||'源未提供';
}


const $=id=>document.getElementById(id),home=document.body.dataset.page==='home',base=new URL('/dashboard/workspace-assets/workspace-native-20261006-72d7ba0dbca8/',location.origin),logicBase=new URL('/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/',location.origin);
const homeURL=document.body.dataset.workspaceHome||new URL('home.html',base).href,analyticsURL=document.body.dataset.workspaceAnalytics||new URL('index.html',base).href;
const allowed=['fc_tab','b_group','b_profile','b_grain','b_align','b_range','b_start','b_end','b_section','b_metrics','g_brand','g_period','g_source','g_project','g_business_profile'];
let state={},active=null,epoch=0,identity=null,verified=[],theme='light',restored=false,last={},checkedAt={},watcher=null,homeController=null,dialogTrigger=null;
const media=matchMedia('(prefers-color-scheme: dark)');
function node(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;}
function link(label,path,cls){const a=node('a',label,cls);a.href=path;return a;}
function toolLink(t,label,cls){const a=link(label,t.available?t.path:'#',cls);a.dataset.access=t.available?'available':'locked';if(!t.available){a.setAttribute('aria-disabled','true');a.title='需授权 · 当前账号暂不可进入';a.onclick=e=>{e.preventDefault();toast('该功能需授权，请联系管理员核实访问范围。');};}return a;}
function readURL(){const p=new URL(location.href).searchParams;state={mode:p.get('mode')==='google'?'google':'business'};for(const key of allowed)state[key]=(p.get(key)||'').slice(0,128);const q=p.get('theme');if(['light','dark','system'].includes(q))theme=q;}
function save(push=false){const u=new URL(location.href);u.search='';u.searchParams.set('mode',state.mode);u.searchParams.set('theme',theme);for(const key of allowed)if(state[key])u.searchParams.set(key,state[key]);if(u.href!==location.href)history[push?'pushState':'replaceState'](null,'',u);}
function applyTheme(){window.FSTheme?.set(theme);const value=theme==='system'?(media.matches?'dark':'light'):theme;document.documentElement.dataset.theme=value;document.documentElement.dataset.fsTheme=value;if(active)active.host.dataset.theme=value;if($('theme'))$('theme').value=theme;try{localStorage.setItem('fs-navigation-theme',theme);}catch{}}
function toast(text){$('toast').textContent=text;setTimeout(()=>{if($('toast').textContent===text)$('toast').textContent='';},4000);}
function header(){const h=$('platform-header');h.append(link('FS',homeURL,'brand-mark'));const brand=link('MMOEXP',homeURL,'brand');brand.append(node('small','运营工作台'));h.append(brand);const nav=node('nav',null,'global-nav');nav.setAttribute('aria-label','平台导航');
 for(const [label,path,key] of [['工作台',homeURL,'home'],['数据分析','/dashboard/modules/analytics/','analytics'],['球类运营','/dashboard/modules/sports/','sports'],['ARPG 运营','/dashboard/modules/arpg/','arpg'],['协作工具','/dashboard/modules/collaboration/','collaboration'],['游戏监控台','/dashboard/game-monitor/','game-monitor'],['经营管理台','/dashboard/management/','management']]){const a=link(label,path);a.dataset.section=key;if((home?'home':'analytics')===key)a.setAttribute('aria-current','page');else if(key!=='home')a.hidden=true;nav.append(a);}h.append(nav);
 const actions=node('div',null,'header-actions'),select=node('select');select.id='theme';select.setAttribute('aria-label','显示主题');for(const [v,l] of [['system','跟随系统'],['light','浅色主题'],['dark','深色主题']]){const o=node('option',l);o.value=v;select.append(o);}select.onchange=()=>{theme=select.value;applyTheme();if(!home)save();};const manage=link('账号与权限管理','/__auth/access/','account-management');manage.hidden=true;manage.title='审批注册申请、设置模块权限';actions.append(select,manage,link('当前账号','/__auth/status','account'));h.append(actions);applyTheme();}
function accountNavigation(user){const manage=document.querySelector('.account-management');manage.hidden=user?.role!=='admin';}
async function readonly(url,type='application/json',method='GET',signal){return protectedRead(url,{method,signal:signal||AbortSignal.timeout(15000)},halt,type);}
function halt(status){try{sessionStorage.removeItem('fs-menu-access-v1');}catch{}epoch++;active?.scope.destroy();active=null;homeController?.abort();watcher?.stop();watcher=null;identity=null;accountNavigation(null);verified=[];$('content-panel')?.replaceChildren();$('status').replaceChildren(node('span',status===403?'当前账号未获授权。':'登录已失效，请重新登录。'),link(' 重新登录','/__auth/login?next='+encodeURIComponent(location.pathname+location.search)));document.querySelectorAll('.global-nav a:not([aria-current])').forEach(a=>a.hidden=true);document.querySelectorAll('#orders,#revenueUsd,#newCustomers').forEach(e=>e.textContent='—');$('workspaces')?.replaceChildren();$('tools')?.replaceChildren();$('recent')?.replaceChildren();if($('data-dialog')?.open)$('data-dialog').close();last={};checkedAt={};dialogTrigger=null;$('dialog-content')?.replaceChildren();$('status').dataset.state='error';const account=document.querySelector('.account');if(account)account.textContent='当前账号';if($('recent')?.parentElement)$('recent').parentElement.hidden=true;try{sessionStorage.removeItem('fs-workspace-recent');}catch{}}
function statusView(q){last[state.mode]=q;if(q.checkedAt)checkedAt[state.mode]=q.checkedAt;const error=q.phase==='error',loading=q.phase==='loading',stale=q.phase==='stale',missing=q.phase==='unavailable';const mode=state.mode==='business'?'MMOEXP · Admin主站 / Order补充参考':'Google · 来源独立';$('status').textContent=mode+' · '+(error?'读取失败，请查看来源提示':stale?'快照过期或本次检查失败，保留最后成功值':missing?'经营快照不可用，未填零':loading?'正在读取所选区间':q.businessUntil?'数据截至 '+q.businessUntil+' 北京时间':'各来源日期与覆盖分别见下方');$('status').dataset.state=error||stale||missing?'error':loading?'loading':'available';}
function capture(q){if(!active||document.hidden)return;if(!restored){if(active.api?.apply(state)){restored=true;return;}return;}const prefix=state.mode==='business'?'b_':'g_';for(const key of allowed.filter(k=>k.startsWith(prefix)||(prefix==='b_'&&k==='fc_tab')))if(q[key]!==undefined)state[key]=String(q[key]);statusView(q);save();}
async function nativeLoad(retried=false){
 const id=++epoch;active?.scope.destroy();active=null;restored=false;$('content-panel').replaceChildren();
 document.querySelectorAll('.mode-tabs [role=tab]').forEach(t=>{const on=t.id==='tab-'+state.mode;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;});$('content-panel').setAttribute('aria-labelledby','tab-'+state.mode);
 if(document.hidden){$('status').textContent='当前页面检查已暂停；重新进入时检查共享缓存。';return;}
 if(!identity)return;
 const host=document.createElement('div');host.className='native-content';host.dataset.theme=document.documentElement.dataset.theme;$('content-panel').append(host);
 const scope=lifecycle(host,capture,halt);scope.seed={...state};active={host,scope,api:null};$('status').textContent='正在读取'+(state.mode==='business'?'经营分析':'Google 运营')+'…';
 try{
  const [markup,stylesheet,module]=await Promise.all([readonly(new URL(state.mode+'.html',logicBase),'text/html','GET',scopeSignal()),readonly(new URL(state.mode+'.css',state.mode==='google'?base:new URL('/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/',location.origin)),'text/css','GET',scopeSignal()),import(new URL(state.mode+'.js'+(retried?'?retry=1':''),base).href)]);
  if(id!==epoch)return;for(const name of ['fs-ui.css','native-alias.css']){const shared=document.createElement('link');shared.rel='stylesheet';shared.href=new URL('ui/'+name,new URL('/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/',location.origin));scope.root.append(shared);}const style=document.createElement('style');style.textContent=await stylesheet.text();scope.root.append(style);const template=document.createElement('template');template.innerHTML=await markup.text();scope.root.append(template.content);
  if(id!==epoch)return;active.api=module.mount(scope);scope.root.addEventListener('click',()=>queueMicrotask(()=>{if(id===epoch&&active?.api)capture(active.api.state());}));
 }catch(e){if(id!==epoch)return;if(e.status){halt(e.status);return;}active?.scope.destroy();active=null;
  const transient=e.name==='TypeError'||e.name==='TimeoutError'||/^protected_read_failed_50[234]$/.test(e.message);
  if(!retried&&transient){$('status').textContent='页面资源暂时未加载，正在自动重试一次…';await new Promise(resolve=>setTimeout(resolve,1500));if(id===epoch&&identity)await nativeLoad(true);return;}
  $('status').textContent='页面组件加载失败，筛选条件仍保留；请重新加载。';
  const retry=node('button','重新加载数据页');retry.type='button';retry.onclick=()=>location.reload();$('content-panel').append(retry);}
}
function scopeSignal(){return active?AbortSignal.any([active.scope.signal,AbortSignal.timeout(20000)]):AbortSignal.timeout(20000);}
async function verify(){return sessionIdentity();}
async function boot(){const id=++epoch;try{const next=await verify();if(id!==epoch)return;identity=next;accountNavigation(next);const registry=await(await readonly(new URL('navigation.json',logicBase))).json();if(id!==epoch)return;if(registry.schemaVersion!==1)throw Error('入口合同错误');const permitted=registry.tools.filter(t=>/^\/(?!\/)[\w./-]+(?:\?(?:mode=(?:business|google)|report_kind=(?:daily|weekly|monthly)(?:#reports)?))?$/.test(t.path)&&!t.path.split('/').includes('..'));
 const checked=await Promise.all(permitted.map(async t=>{const path=t.id.startsWith('unified-')?analyticsURL:t.path;const permitted=t.requiredGroup!=='deploy'||next.groups.includes('deploy');const available=permitted&&await moduleAvailable(path)&&(!t.probeJson||await moduleAvailable(t.probeJson,'application/json'));return {...t,available};}));
 if(id!==epoch||!identity||identity.name!==next.name)return;verified=checked.filter(Boolean);
 for(const a of document.querySelectorAll('.global-nav a[data-section]'))if(verified.some(t=>t.section===a.dataset.section))a.hidden=false;
 document.querySelector('.account').textContent=next.name;if(home){homeEntries(registry);homeData();}else nativeLoad();
 }catch(e){if(id!==epoch)return;if(e.status)halt(e.status);else $('status').textContent=e.message;}}
function homeEntries(registry){const user=identity?.name;if(!user)return;const grid=$('workspaces');grid.replaceChildren();$('tools').replaceChildren();
 for(const s of registry.sections){const tools=verified.filter(t=>s.ids.includes(t.id));if(!tools.length)continue;const card=node('article',null,'workspace-card '+s.id),a=link('',s.path,'workspace-main');a.append(node('span',s.icon,'workspace-icon'),node('h3',s.title),node('p',s.intro),node('span','进入工作区 →','entry'));card.append(a);
  grid.append(card);
 }
 for(const [id,label] of [['management','经营管理台'],['game-monitor','游戏监控台'],['coins','FC 改价台'],['d4','RPG 改价台'],['tasks','工作任务分配台']]){const t=verified.find(t=>t.id===id);if(!t)continue;const entry=toolLink(t,label+(t.available?'':' · 需授权'));entry.dataset.tool=id;if(t.available)entry.onclick=()=>{if(identity?.name!==user)return;try{const key='fs-workspace-recent',old=JSON.parse(sessionStorage.getItem(key)||'{}'),ids=old.user===user?old.ids||[]:[];sessionStorage.setItem(key,JSON.stringify({user:user,ids:[id,...ids.filter(v=>v!==id)].slice(0,3)}));}catch{}};$('tools').append(entry);}
 try{const old=JSON.parse(sessionStorage.getItem('fs-workspace-recent')||'{}');if(old.user===user){const entries=(old.ids||[]).map(id=>verified.find(t=>t.id===(id==='release-radar'?'game-monitor':id))).filter(Boolean).slice(0,3);if(entries.length){$('recent').replaceChildren();$('recent').parentElement.hidden=false;for(const t of entries)$('recent').append(toolLink(t,t.label+(t.available?' →':' · 需授权')));}}else sessionStorage.removeItem('fs-workspace-recent');}catch{}
}
function homeData(){
 watcher?.stop();homeController?.abort();homeController=new AbortController();const id=++epoch;
 watcher=new LiveSummary(()=>{const day=FSHomeMetrics.beijingDate();return {profile:'MMOEXP',start:day,end:day,grain:'day'};},data=>{
  if(id!==epoch||!identity)return;const p=data.profile,m=fsMainSite(p).metrics;
  for(const [k,metric] of [['orders','orders'],['revenueUsd','revenueUsd'],['newCustomers','estimatedProfitUsd']]){
   const v=m[metric].value;$(k).textContent=v!=null?new Intl.NumberFormat('en-US',{maximumFractionDigits:k==='orders'?0:2,minimumFractionDigits:k==='orders'?0:2}).format(v):fsMetricText(m[metric],()=> '—');
   $('label-'+k).textContent='今日MMOEXP '+{orders:'订单数',revenueUsd:'销售额',newCustomers:'预估利润'}[k];
  }
  $('status').dataset.state=data.stale?'error':'available';
  $('status').textContent=(data.stale?'⚠ 已过期，保留故障兜底 · ':'')+'Admin主站 · 查询截至 '+p.period.end+' 北京时间 · Admin读取 '+(data.sources.Admin.capturedAt||'—')+' · 上游统计水位 '+(data.sources.Admin.sourceDataAsOf||'未提供')+' · Order '+fsOrderLabel(data.sources.Order)+' · 共享缓存 '+(data.refreshSeconds||900)+'秒';
 },state=>{if(id!==epoch||!identity)return;if(state.clear)for(const k of ['orders','revenueUsd','newCustomers'])$(k).textContent='—';if(state.status===401||state.status===403){halt(state.status);return;}if(state.phase!=='available'){$('status').dataset.state='error';$('status').textContent=state.message;}});
 watcher.read=path=>readonly(path,'application/json','GET',homeController.signal);watcher.start();$('refresh').disabled=false;
}
try{theme=localStorage.getItem('fs-navigation-theme')||'light';}catch{}header();if(!['light','dark','system'].includes(theme))theme='light';if(!home)readURL();if(location.pathname.startsWith('/s/wulv/fc27-ops/')){state.mode='business';state.b_profile='FC27';state.b_group='sports';}applyTheme();media.addEventListener('change',()=>{if(theme==='system')applyTheme();});
$('refresh').onclick=async()=>{const id=epoch,user=identity?.name;if(!user){boot();return;}$('refresh').disabled=true;try{const next=await verify();if(id!==epoch||!identity)return;if(next.name!==user){halt(403);await boot();return;}identity=next;accountNavigation(next);if(home)await watcher?.check();else if(active?.api)await active.api.update();else await nativeLoad();}catch(e){if(e.status)halt(e.status);else $('status').textContent=e.message;}finally{$('refresh').disabled=false;}};
if(!home){
 for(const mode of ['business','google'])$('tab-'+mode).onclick=()=>{if(state.mode===mode)return;if(active?.api&&restored)capture(active.api.state());state.mode=mode;save(true);nativeLoad();};
 document.querySelector('.mode-tabs').onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('.mode-tabs button')],i=tabs.indexOf(document.activeElement);tabs[e.key==='Home'?0:e.key==='End'?1:(i+1)%2].focus();};
 $('details').onclick=()=>{dialogTrigger=document.activeElement;$('dialog-content').replaceChildren();for(const mode of ['business','google']){const q=last[mode];if(!q)continue;const s=node('section');s.append(node('h3',mode==='business'?'经营':'Google'),node('p','业务截至：'+(q.businessUntil||'见各来源覆盖')),node('p','来源读取：'+(q.generatedAt||q.details||'—')),node('p','页面最近检查：'+(checkedAt[mode]||'—')),node('p','目录版本：'+(q.snapshotId||'见来源详情')),node('p',q.details));$('dialog-content').append(s);}$('data-dialog').showModal();};
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
  else if(active?.api){capture(active.api.state());if(state.mode==='google')await active.api.update();else await active.api.resume?.();}
  else if(!active)await nativeLoad();
 }catch(e){
  if(id!==epoch)return;
  if(e.status)halt(e.status);
  else {$('status').textContent='检查失败，保留当前视图；可稍后检查新版本。';$('status').dataset.state='error';}
 }finally{if(visibilityCheck===pending)visibilityCheck=null;}
});
const permissionTimer=setInterval(async()=>{if(document.hidden||!identity)return;const id=epoch,user=identity.name;try{const next=await verify();if(id!==epoch||!identity)return;if(next.name!==user||JSON.stringify(next.groups)!==JSON.stringify(identity.groups)){halt(403);return;}identity=next;accountNavigation(next);}catch(e){if(id===epoch&&e.status)halt(e.status);}},60000);
addEventListener('pagehide',()=>{clearInterval(permissionTimer);epoch++;active?.scope.destroy();active=null;homeController?.abort();watcher?.stop();});addEventListener('pageshow',e=>{if(e.persisted){if(home&&identity)homeData();else nativeLoad();}});boot();

const sharedNav=document.createElement('script');sharedNav.src='/__hub/hubnav.js?v=fs-revision-20261015';sharedNav.defer=true;document.head.append(sharedNav);

document.addEventListener('fs-theme-change',e=>{theme=e.detail.preference;document.querySelectorAll('.native-content').forEach(h=>{h.dataset.theme=e.detail.resolved;h.dataset.fsTheme=e.detail.resolved;});if($('theme'))$('theme').value=theme;});
