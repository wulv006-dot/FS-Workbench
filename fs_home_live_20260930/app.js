'use strict';
const $=id=>document.getElementById(id), M=FSHomeMetrics;
let registry={modules:[],tools:[]}, groups=[], snapshot=null, selectedScope='all', pending=null, transactionData=null;
const profileChoice={all:'MMOEXP',sports:'FC27',arpg:'D4'};
const number=new Intl.NumberFormat('en-US'), money=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
function el(tag,text,className){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(className)e.className=className;return e;}
function closeMenu(){ $('sidebar').classList.remove('open');$('scrim').hidden=true;$('menu').setAttribute('aria-expanded','false'); }
function showDialog(title,paragraphs){$('dialog-title').textContent=title;$('dialog-body').replaceChildren(...paragraphs.map(p=>el('p',p)));if(!$('detail-dialog').open)$('detail-dialog').showModal();}
function go(path){if(M.safePath(path)){closeMenu();location.assign(path);}}
function entry(id){const t=registry.tools.find(t=>t.id===id);if(t&&(!t.requiredGroup||groups.includes(t.requiredGroup)))go(t.path);}
async function publishedEntry(t){
 if(!M.safePath(t.path)||!M.safePath(t.probeJson))return false;
 try{const rs=await Promise.all([fetch(t.path,{method:'HEAD',credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)}),fetch(t.probeJson,{method:'HEAD',credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)})]);return rs.every(r=>r.ok&&!r.redirected)&&rs[0].headers.get('content-type')?.includes('text/html')&&rs[1].headers.get('content-type')?.includes('application/json');}catch{return false;}
}
async function json(path){const r=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(65000)});if(r.status===401){go('/__auth/login?next='+encodeURIComponent('/dashboard/'));throw Error('session_expired');}if(r.status===403)throw Error('forbidden');if(r.redirected||!r.headers.get('content-type')?.includes('application/json'))throw Error('session_or_data_unavailable');const d=await r.json();if(!r.ok)throw Error('data_unavailable');return d;}
function renderRegistry(){
 $('navigation').replaceChildren();for(const [id,icon,label] of [['overview','◈','首页'],['statistics','◷','数据统计'],['automation','⚡','自动化工作区'],['tools','▦','业务工具'],['access','♙','成员与权限'],['about','ⓘ','平台介绍']]){const a=el('a');a.href='#'+id;a.append(el('span',icon),document.createTextNode(label));a.className=id==='overview'?'active':'';a.onclick=()=>{document.querySelectorAll('nav a').forEach(n=>n.classList.remove('active'));a.classList.add('active');closeMenu();};$('navigation').append(a);}
 $('module-grid').replaceChildren();for(const m of registry.modules){if(!['analytics','marketing','tasks','ops','weekly'].includes(m.id)||!/^fs-mmoexp-[a-z-]+\.png$/.test(m.image)||!M.safePath(m.path))continue;const link=el('a',null,'module-card');link.href=m.path;link.setAttribute('aria-label','进入'+m.title);const img=el('img');img.src='/dashboard/fs-home/assets/'+m.image;img.alt='';const copy=el('div',null,'module-copy');const title=el('strong',m.title);title.append(el('span','↗','module-arrow'));copy.append(el('small',m.english),title,el('p',m.description));if(m.availability==='pending-report')copy.append(el('span','待上线','module-state'));link.append(img,copy);link.onclick=closeMenu;$('module-grid').append(link);}
 $('segments').replaceChildren();for(const [id,label] of [['all','全局'],['sports','球类'],['arpg','ARPG']]){const b=el('button',label,id==='all'?'active':'');b.type='button';b.id='scope-tab-'+id;b.setAttribute('role','tab');b.setAttribute('aria-selected',String(id==='all'));b.setAttribute('aria-controls','home-statistics');b.tabIndex=id==='all'?0:-1;b.onclick=()=>{selectedScope=id;for(const x of $('segments').children){x.classList.toggle('active',x===b);x.setAttribute('aria-selected',String(x===b));x.tabIndex=x===b?0:-1;}renderHomeOverview();};b.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const tabs=[...$('segments').children],i=tabs.indexOf(b),next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].click();tabs[next].focus();}};$('segments').append(b);}
 $('overview-profile').onchange=()=>{profileChoice[selectedScope]=$('overview-profile').value;renderHomeOverview();};
 $('tool-grid').replaceChildren();for(const t of registry.tools){if(!M.safePath(t.path)||(t.requiredGroup&&!groups.includes(t.requiredGroup)))continue;const pending=t.availability==='verify-published-page';const a=el(pending?'button':'a',null,'tool');if(pending){a.disabled=true;a.type='button';a.dataset.pendingEntry=t.id;}else{a.href=t.path;a.onclick=closeMenu;}a.append(el('span',t.icon),el('span','↗','tool-arrow'),el('strong',t.label),el('p',t.short),el('small',pending?'当前会话验证中':'维护人待确认'));$('tool-grid').append(a);if(pending)publishedEntry(t).then(ok=>{if(!a.isConnected)return;if(ok){const ready=el('a',null,'tool');ready.href=t.path;ready.append(...a.childNodes);ready.querySelector('small').textContent='维护人待确认';ready.onclick=closeMenu;a.replaceWith(ready);}else{a.querySelector('small').textContent='当前会话未通过入口验证';}});}
 document.querySelectorAll('[data-entry]').forEach(b=>b.onclick=()=>entry(b.dataset.entry));
}
function renderMetrics(raw){
 const d=M.normaliseToday(raw),ok=d.status==='available', values=[ok?number.format(d.metrics.orders):'—',ok?money.format(d.metrics.revenueUsd):'—',ok&&d.metrics.newCustomers!==null?number.format(d.metrics.newCustomers):'—'];
 document.querySelectorAll('.kpi-value').forEach((e,i)=>{e.replaceChildren(document.createTextNode(values[i]),el('span',['笔','USD','人'][i]));});
 document.querySelectorAll('.kpi-foot').forEach(e=>{e.replaceChildren(el('span',null,'dot'),document.createTextNode(ok?'快照日期 '+d.date+' · 截至 '+d.period.end.slice(11,16):'数据不可用'));});
 const note=document.querySelector('.notice p');note.textContent=ok?'所有网站合计 · order订单/金额，admin补充新客 · 更新于 '+new Date(d.generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间 · USD':'今日经营数据不可用，请稍后刷新或打开原经营看板。';
 $('loading-error').hidden=ok;
}
function overviewValue(m,key,format){const n=m?.[key]?.value;return Number.isFinite(n)?format==='money'?money.format(n):format==='percent'?n.toFixed(2)+'%':number.format(n):m?.[key]?.status==='not_computable'?'不可计算':'未提供';}
function renderHomeOverview(){
 const host=$('home-statistics'),picker=$('overview-profile'),data=transactionData;host.replaceChildren();picker.replaceChildren();
 host.setAttribute('aria-labelledby','scope-tab-'+selectedScope);
 const keys=selectedScope==='all'?['MMOEXP']:data?.dashboard?.groups?.find(g=>g.key===(selectedScope==='arpg'?'rpg':'sports'))?.profiles||[];
 const available=keys.filter(k=>data?.profiles?.[k]);if(!available.length){picker.disabled=true;$('overview-period').textContent='';host.append(el('p','经营数据暂不可用，请打开完整看板查看最后有效版本。','fsi-empty'));return;}
 if(!available.includes(profileChoice[selectedScope]))profileChoice[selectedScope]=available[0];
 for(const key of available){const o=el('option',data.profiles[key].name||key);o.value=key;picker.append(o);}picker.value=profileChoice[selectedScope];picker.disabled=available.length===1;
 const p=data.profiles[picker.value],m=p.metrics||{},sm=p.supplement?.metrics||{};
 $('overview-period').textContent=(p.period?.start||'—')+' 至 '+(p.period?.end||'—')+' · 北京时间 · USD';
 const cards=el('div',null,'fsi-metrics');
 const fields=[['订单数量','orders','count',true],['订单金额','revenueUsd','money',true],['单均价','averageOrderUsd','money',true],['利润率','profitMarginPct','percent',true],['新客人数','newCustomers','count'],['付款人数','payingCustomers','count'],['新客付款金额','newCustomerRevenueUsd','money'],['复购率','repeatRatePct','percent'],['新客占比','newCustomerSharePct','percent'],['纯销售额','pureSalesUsd','money'],['退款金额','refundAmountUsd','money'],['退款订单','refundOrders','count'],['发货完成率','fulfillmentRatePct','percent'],['支付成功率','paymentSuccessRatePct','percent']];
 for(const [label,key,format,core] of fields){const primary=m[key],source=core||primary?.value!=null?m:sm;const item=source[key],card=el('article',null,'fsi-metric');const detail=key==='newCustomerSharePct'?'Admin新客 ÷ Admin订单 × 100':item?.source==='primary'||core?'Order后台原值':'Admin补源原值';card.append(el('span',label),el('strong',overviewValue(source,key,format)),el('small',detail));cards.append(card);}host.append(cards);
 const sourceNote=el('p','Order主源 / Admin补缺 · 更新 '+new Date(data.generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间 · '+(p.primary?.filters?.status==='3'?'已完成订单':'全部订单状态')+'；补源为已付款。球类/ARPG按项目查看，不将不同项目去重人数或利润率相加。','fsi-note');host.append(sourceNote);
}
let transactionWatcher=null;
function applyTransaction(data){
 const p=data.profiles.MMOEXP;
 document.querySelectorAll('.kpi-top').forEach((e,i)=>{e.firstChild.textContent=(data.date===M.beijingDate()?'今日':'快照 '+data.date)+['全站订单数','全站销售额','全站新客人数'][i];});
 renderMetrics({status:'available',metricScope:'ALL_WEBSITES',timezone:data.timezone,currency:data.currency,date:data.date,
   period:p.period,generatedAt:data.generatedAt,source:p.primary,supplement:p.supplement,
   metrics:{orders:p.metrics.orders.value,revenueUsd:p.metrics.revenueUsd.value,newCustomers:p.metrics.newCustomers.value}});
 snapshot=data.dashboard;transactionData=data;renderHomeOverview();
}
async function refresh(){if(pending)return pending;$('refresh').disabled=true;$('refresh').textContent='读取中…';
 if(!transactionWatcher)transactionWatcher=new FSBusinessSnapshots('/dashboard/fs-home/transactions/',applyTransaction,state=>{
  const date=transactionWatcher.current?.date;if(date)document.querySelectorAll('.kpi-top').forEach((e,i)=>{e.firstChild.textContent=(date===M.beijingDate()?'今日':'快照 '+date)+['全站订单数','全站销售额','全站新客人数'][i];});
  if(state.status!=='fresh'){document.querySelector('.notice p').textContent='⚠ '+(state.status==='stale'?'数据已过期，保留最后成功快照':'经营数据不可用')+' · 更新时间 '+(state.generatedAt?new Date(state.generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'—')+' 北京时间';}
 });
 pending=transactionWatcher.check().finally(()=>{pending=null;$('refresh').disabled=false;$('refresh').textContent='检查新快照';});return pending;
}
async function boot(){
 try{const r=await fetch('/__auth/verify',{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(10000)});if(r.status===401){go('/__auth/login?next='+encodeURIComponent('/dashboard/'));return;}if(r.status!==200)throw Error('forbidden');groups=(r.headers.get('X-Auth-Groups')||'').split(',').map(x=>x.trim()).filter(Boolean);const name=r.headers.get('X-Auth-User')||'当前账号';$('profile-name').replaceChildren(document.createTextNode(name),el('small','沿用现有访问范围'));registry=await json('/dashboard/fs-home/module-registry.json');if(registry.schemaVersion!==1||!Array.isArray(registry.modules)||!Array.isArray(registry.tools))throw Error('registry_unavailable');renderRegistry();await refresh();transactionWatcher.start();
  // The separate existing FC27 gate remains authoritative for member administration.
  try{const fc=await fetch('/fc27/verify',{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(10000)});if(fc.status===200&&fc.headers.get('X-Fc27-Role')==='admin'){const a=el('a','FC27 成员管理 ↗','text-button');a.href='/fc27/admin';document.querySelector('.access-panel').append(a);}}catch{/* An independent gate outage does not invalidate aggregate metrics. */}
 }catch{renderMetrics(null);document.querySelector('.notice p').textContent='当前会话或页面数据不可用，请检查登录状态后重试。';}
}
$('menu').onclick=()=>{const open=$('sidebar').classList.toggle('open');$('scrim').hidden=!open;$('menu').setAttribute('aria-expanded',String(open));};$('scrim').onclick=closeMenu;
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenu();});addEventListener('popstate',closeMenu);addEventListener('pageshow',closeMenu);addEventListener('resize',()=>{if(innerWidth>=800)closeMenu();});
$('dialog-close').onclick=$('dialog-ok').onclick=()=>$('detail-dialog').close();$('refresh').onclick=refresh;$('access-action').onclick=()=>go('/__auth/status');
$('help').setAttribute('aria-label','查看数据说明');$('help').onclick=()=>showDialog('首页数据说明',[
 '运营总览为所有网站合计。订单数、销售额、单均价、利润率均取 order.p2pah 订单统计；新客取 admin.p2pah 全部网站 new_people 原值，两个来源分别标识，不校准订单差异、新客占比取admin新客人数÷admin订单数，复购率与付款字段取补源原值。',
 '服务器每120分钟原子发布快照，各业务看板每60秒检查同一版本；手动检查不会触发采集。今日区间冻结为北京时间00:00至快照查询截止分钟，USD。',
 '采集失败保留旧快照并标过期；新客补源缺失展示不可用。品类保留自己的状态、游戏与日期筛选。各工具沿用当前服务端门禁。']);
$('about-action').onclick=()=>showDialog('FS 运营平台',['MMOEXP 团队的统一经营工作台，连接经营数据、自动化控制台与业务工具。','球类与 ARPG 复用整体视觉和基础入口，细分业务统计沿用原经营看板。','模块与工具的维护人由团队确认。']);
boot();
