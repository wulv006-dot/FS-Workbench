(function(root){
'use strict';
const CONTRACT='all-websites-order-primary-admin-supplement-v1';
const BASE='/dashboard/fs-home/transactions/';
const KEYS=['MMOEXP','D4','POE2','FC27','FC26','NBA2K27','NFL27','MLB26','CFB27'];
const FIELDS=[
 ['orders','订单数','orders'],['revenueUsd','订单金额','USD'],['averageOrderUsd','Order单均价','USD'],['profitMarginPct','Order后台利润率','percent'],
 ['fulfillmentRatePct','发货完成率','percent'],['newCustomers','业务新客数','people'],['payingCustomers','付款人数','people'],['newCustomerRevenueUsd','新客付款金额','USD'],
 ['newCustomerSharePct','新客占比','percent'],['repeatRatePct','后台复购率','percent'],['pureSalesUsd','纯销售额','USD'],['averageCustomerUsd','补源客单价','USD'],
 ['paymentSuccessRatePct','支付成功率','percent'],['refundOrders','退款单数','orders'],['refundAmountUsd','退款金额','USD'],['deductedAmountUsd','扣款金额','USD'],
 ['maxOrderAmountUsd','最大订单额','USD'],['minOrderAmountUsd','最小订单额','USD'],['receiptsCny','收款总额','CNY'],['goodsPaymentCny','货款总额','CNY'],
 ['costUsd','成本金额','USD'],['profitUsd','利润金额','USD']
];
const CORE=new Set(['orders','revenueUsd','averageOrderUsd','profitMarginPct']);
function number(value){if(value===null||value===undefined||value===''||typeof value==='boolean')return null;const n=Number(value);return Number.isFinite(n)?n:null;}
function metric(profile,key){
 const catalog=FIELDS.find(row=>row[0]===key)||[key,key,''];
 const top=profile.metrics?.[key],primary=profile.primary?.metrics?.[key],supplement=profile.supplement?.metrics?.[key];
 const valid=m=>m&&number(m.value)!==null&&!['failed','not_provided','unavailable'].includes(m.status);
 const preferred=[top?.source==='primary'?top:null,primary];
 let selected=preferred.find(valid);
 // An existing but failed/missing primary core field must not silently change source.
 if(!selected&&CORE.has(key)&&(top?.source==='primary'||primary||profile.primary?.status==='failed')){
   selected=top?.source==='primary'?top:primary||{value:null,status:'unavailable',source:'primary'};
 }else if(!selected){selected=[top,supplement].find(valid)||top||supplement||primary||{value:null,status:'not_provided'};}
 const value=number(selected.value);
 return {key,label:catalog[1],unit:selected.unit||catalog[2],value,raw:selected.raw??null,
   source:selected.source||(selected===primary?'primary':selected===supplement?'supplement':'unknown'),
   status:value===null?selected.status||'not_provided':'available',definition:selected.definition||'',field:selected.field||null};
}
function rows(value){return Array.isArray(value)?value:[];}
function cleanRows(values,columns){return rows(values).slice(0,500).map(row=>Object.fromEntries(columns.map(key=>[key,['orders','revenueUsd','amountUsd','value','count','counts'].includes(key)?number(row[key]):row[key]??null])));}
function normalize(value,manifest){
 if(value.schemaVersion!==2||value.supplementContractVersion!==1||value.scopeContractId!==CONTRACT||value.scope!=='all-websites'||value.snapshotId!==manifest.snapshotId)throw Error('CONTRACT_INVALID');
 if(value.timezone!=='Asia/Shanghai'||value.currency!=='USD')throw Error('UNITS_INVALID');
 if(!Number.isFinite(Date.parse(manifest.generatedAt)))throw Error('TIMESTAMP_INVALID');
 const profiles={};
 for(const key of KEYS){const p=value.profiles?.[key];if(!p)continue;
   const metrics=Object.fromEntries(FIELDS.map(([field])=>[field,metric(p,field)]));
   const dim=p.dimensions||{},supp=p.supplement?.dimensions||{},chart=value.dashboard?.profiles?.[key]||{};
   profiles[key]={key,name:key==='MMOEXP'?'所有网站合计':p.name||key,period:p.period||{},primary:p.primary||{},supplement:p.supplement||{},metrics,
    channels:cleanRows(dim.channels,['name','amountUsd','orders']),products:cleanRows(dim.products,['name','type','count','value']),statuses:cleanRows(dim.statuses,['name','status','counts','value']),
    websiteDistribution:cleanRows(supp.channels,['name','code','orders','revenueUsd']),countries:cleanRows(supp.countries,['name','code','orders','revenueUsd']),
    devices:cleanRows(supp.devices,['name','orders','revenueUsd']),payments:cleanRows(supp.payments,['name','orders','revenueUsd']),games:cleanRows(supp.games,['name','code','adminGameId','orders','revenueUsd']),
    couponProvided:Array.isArray(dim.coupon)||Array.isArray(supp.coupon),
    series:cleanRows(chart.series,['date','orders','amount','partial']),hourly:cleanRows(chart.hourly,['ts','orders','amount']),historyWindow:chart.window||{}};
 }
 if(!profiles.MMOEXP)throw Error('ALL_WEBSITES_REQUIRED');
 return {snapshotId:value.snapshotId,generatedAt:manifest.generatedAt,generatedAtShanghai:manifest.generatedAtShanghai,
  staleAfterSeconds:manifest.staleAfterSeconds||7200,scope:'all-websites',profiles,
  crossSourceConversionRate:null,financialRoas:null,kolAttribution:null};
}
async function readSnapshot(fetcher,cryptoObject,previous){
 const response=await fetcher(BASE+'current.json',{credentials:'same-origin',cache:'no-store'});
 if(!response.ok)throw Error('MANIFEST_UNAVAILABLE');
 const manifest=await response.json();
 if(manifest.schemaVersion!==2||manifest.scopeContractId!==CONTRACT||!/^snapshots\/[A-Za-z0-9_-]+\/snapshot\.json$/.test(manifest.path)||!/^[a-f0-9]{64}$/.test(manifest.sha256)||manifest.path.split('/')[1]!==manifest.snapshotId)throw Error('MANIFEST_INVALID');
 if(previous?.snapshotId===manifest.snapshotId&&previous.sha256===manifest.sha256)return previous;
 const result=await fetcher(BASE+manifest.path,{credentials:'same-origin',cache:'no-store'});
 if(!result.ok)throw Error('SNAPSHOT_UNAVAILABLE');
 const buffer=await result.arrayBuffer();if(buffer.byteLength>5000000)throw Error('SNAPSHOT_TOO_LARGE');
 const hash=Array.from(new Uint8Array(await cryptoObject.subtle.digest('SHA-256',buffer))).map(n=>n.toString(16).padStart(2,'0')).join('');
 if(hash!==manifest.sha256)throw Error('SHA_MISMATCH');
 const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(buffer));
 return {...normalize(value,manifest),sha256:hash};
}
function profitColor(margin){if(margin===null)return '#a5aaa5';if(margin<0)return '#bd5d56';return margin===0?'#d9bd74':`hsl(158 45% ${Math.max(30,70-Math.min(margin,80)*.45)}%)`;}
function profitLayout(profiles){
 const positive=[],excluded=[];
 for(const key of KEYS.filter(key=>key!=='MMOEXP')){const p=profiles[key];if(!p)continue;const revenue=p.metrics.revenueUsd.value,margin=p.metrics.profitMarginPct.value;
   const row={key,name:p.name,revenue,margin,color:profitColor(margin)};
   (revenue!==null&&revenue>0?positive:excluded).push(row);
 }
 function split(list,x,y,w,h){if(!list.length)return [];if(list.length===1)return [{...list[0],x,y,w,h}];const total=list.reduce((sum,p)=>sum+p.revenue,0);let sum=0,i=0;while(i<list.length-1&&sum<total/2){sum+=list[i++].revenue;}const ratio=sum/total;
   return w>=h?[...split(list.slice(0,i),x,y,w*ratio,h),...split(list.slice(i),x+w*ratio,y,w*(1-ratio),h)]:[...split(list.slice(0,i),x,y,w,h*ratio),...split(list.slice(i),x,y+h*ratio,w,h*(1-ratio))];}
 return {tiles:split(positive.sort((a,b)=>b.revenue-a.revenue),0,0,900,360),excluded};
}
const api={metric,normalize,readSnapshot,profitLayout,profitColor,number,FIELDS};
if(typeof module!=='undefined'&&module.exports){module.exports=api;return;}
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=String(text);if(cls)node.className=cls;return node;};
const sourceName=source=>source==='primary'?'Order主源':source==='supplement'?'Admin补源':'未提供';
function format(value,unit){if(value===null||value===undefined)return '未提供';return new Intl.NumberFormat('zh-CN',{maximumFractionDigits:unit==='orders'||unit==='people'?0:2}).format(value)+(unit==='percent'?'%':unit==='USD'?' USD':unit==='CNY'?' CNY':'');}
function table(columns,data){const wrap=el('div',null,'table-scroll'),t=el('table'),head=el('thead'),tr=el('tr');for(const [key,label] of columns)tr.append(el('th',label));head.append(tr);t.append(head);const body=el('tbody');for(const row of data){const line=el('tr');for(const [key,label,unit] of columns)line.append(el('td',unit?format(row[key],unit):row[key]??'未提供'));body.append(line);}if(!data.length){const tr=el('tr'),td=el('td','该快照未提供此维度，未填0。','empty');td.colSpan=columns.length;tr.append(td);body.append(tr);}t.append(body);wrap.append(t);return wrap;}
function section(title,subtitle){const node=el('section',null,'report-section');node.append(el('h2',title));if(subtitle)node.append(el('p',subtitle,'section-meta'));return node;}
function periodText(p){return (p?.start||'未提供')+' 至 '+(p?.end||'未提供')+' · Asia/Shanghai';}
function sourceText(profile,which){const s=profile[which]||{},f=s.filters||{};const state=which==='primary'?(String(f.status)==='3'?'已完成订单':'全部订单状态'):(String(f.order_status)==='101'?'已完成 / 已支付':'已支付');return sourceName(which)+' · '+periodText(s.period||profile.period)+' · '+state+' · 采集 '+(s.capturedAt||'未提供');}
function chart(data,label,field,unit){const box=el('div',null,'bar-chart');const max=Math.max(...data.map(row=>number(row[field])??0),1);for(const row of data.slice(0,15)){const line=el('div',null,'bar-row'),track=el('div',null,'bar-track'),bar=el('i');bar.style.width=(Math.max(0,number(row[field])??0)/max*100)+'%';track.append(bar);line.append(el('span',row[label]||'未提供','bar-label'),track,el('b',format(row[field],unit)));box.append(line);}return box;}
function cards(profile){const grid=el('div',null,'kpi-grid');for(const [key] of FIELDS.slice(0,16)){const m=profile.metrics[key],item=el('article',null,'kpi');item.dataset.metric=key;item.append(el('span',m.label),el('strong',format(m.value,m.unit)),el('small',sourceName(m.source)));if(m.status!=='available')item.append(el('small','本版未提供此值'));grid.append(item);}return grid;}
function renderProfit(panel,data){const block=section('项目利润地图','面积是已提供项目的Order营收，颜色是Order后台利润率：正值绿色、负值红色、零金色、缺失灰色。全站比例采用全站原值，不平均项目利润率；ARPG为已完成、球类为全状态，项目金额不作为全站合计；未估算利润金额。');const map=profitLayout(data.profiles),ns='http://www.w3.org/2000/svg';
 if(map.tiles.length){const svg=document.createElementNS(ns,'svg');svg.classList.add('profit-map');svg.setAttribute('viewBox','0 0 900 360');svg.setAttribute('role','img');svg.setAttribute('aria-label','项目营收面积与Order后台利润率');for(const tile of map.tiles){const g=document.createElementNS(ns,'g'),rect=document.createElementNS(ns,'rect');for(const [k,v] of Object.entries({x:tile.x,y:tile.y,width:tile.w,height:tile.h,fill:tile.color,stroke:'white','stroke-width':2}))rect.setAttribute(k,String(v));const title=document.createElementNS(ns,'title');title.textContent=tile.name+' · '+format(tile.revenue,'USD')+' · 利润率 '+format(tile.margin,'percent');g.append(title,rect);if(tile.w>90&&tile.h>42){const text=document.createElementNS(ns,'text');text.setAttribute('x',tile.x+12);text.setAttribute('y',tile.y+24);text.textContent=tile.name.length>14?tile.key:tile.name;g.append(text);if(tile.h>65){const sub=document.createElementNS(ns,'text');sub.setAttribute('x',tile.x+12);sub.setAttribute('y',tile.y+48);sub.textContent=format(tile.margin,'percent');g.append(sub);}}svg.append(g);}block.append(svg);}else block.append(el('p','本版没有可用于面积的正营收项目。','empty'));
 block.append(table([['name','项目'],['revenue','Order订单金额','USD'],['margin','Order后台利润率','percent']],KEYS.filter(k=>k!=='MMOEXP').filter(k=>data.profiles[k]).map(k=>({name:data.profiles[k].name,revenue:data.profiles[k].metrics.revenueUsd.value,margin:data.profiles[k].metrics.profitMarginPct.value}))));
 if(map.excluded.length)block.append(el('p','无正营收或缺失项目保留在表中：'+map.excluded.map(r=>r.name).join('、'),'coverage'));panel.append(block);}
function renderHistory(panel,p){const block=section('Order经营趋势 · 最近30日及今日小时','表列最近30日、图列最近15日，来自主源历史快照，今日尚未结束。这里不是所选Google自然周；没有逐用户、渠道或广告归因关联。');const daily=p.series.slice(-30).map(r=>({date:r.date+(r.partial?'（当日未结束）':''),orders:r.orders,revenue:r.amount}));block.append(chart(daily.slice(-15),'date','revenue','USD'),table([['date','上海日期'],['orders','订单数','orders'],['revenue','订单金额','USD']],daily));const hour=p.hourly.map(r=>({date:r.ts,orders:r.orders,revenue:r.amount}));block.append(el('h3','今日小时'),table([['date','上海小时'],['orders','订单数','orders'],['revenue','订单金额','USD']],hour));panel.append(block);}
function dimension(panel,title,subtitle,data,columns,field,unit){const block=section(title,subtitle);if(data.length)block.append(chart(data,'name',field,unit));block.append(table(columns,data));panel.append(block);}
let current=null,cache=null,inFlight=false,selectedProfile='MMOEXP',lastError=false;
function render(panel,data){const selected=data.profiles[selectedProfile]?selectedProfile:'MMOEXP',p=data.profiles[selected];panel.replaceChildren();
 const head=section('经营对照 · 所有网站','该经营快照覆盖所有网站，与MMOEXP/RSOrder Google标签分开。每次渲染固定同一不可变版本并核验SHA-256。');
 const row=el('div',null,'business-toolbar'),select=el('select');select.setAttribute('aria-label','经营项目');for(const key of KEYS){const p=data.profiles[key];if(!p)continue;const option=el('option',p.name);option.value=key;select.append(option);}select.value=selected;select.addEventListener('change',()=>{selectedProfile=select.value;render(panel,cache);});row.append(select,el('span','服务器每120分钟采集 · 本标签每60秒检查版本','section-meta'));head.append(row);
 const stale=(Date.now()-Date.parse(data.generatedAt))/1000>data.staleAfterSeconds;
 head.append(el('p','版本 '+data.snapshotId+' · 生成 '+(data.generatedAtShanghai||data.generatedAt)+' · '+(stale?'超过更新周期，保留最近有效值':'有效快照'),'watermark'));
 if(lastError)head.append(el('p','本次经营快照读取或校验失败，保留上一有效版本。','business-refresh-error failure'));
 head.append(el('p','统计区间 '+periodText(p.period),'period-title'),el('p',sourceText(p,'primary'),'coverage'),el('p',sourceText(p,'supplement'),'coverage'));
 head.append(el('aside','共有有效字段优先Order主源，单边字段直接采用。来源总数不一致仍分别展示；新客占比采用Admin同范围分母，复购率和Order利润率保留后台原值。USD/CNY独立，不相减推算利润。','financial-note'),cards(p));
 const audit=el('details');audit.append(el('summary','查看源查询范围与筛选'),el('pre',JSON.stringify({primary:p.primary.filters,supplement:p.supplement.filters},null,2)));head.append(audit);const detail=el('details');detail.append(el('summary','查看全部字段、原值和来源定义'),table([['label','指标'],['display','实际值'],['raw','后台原字符串'],['source','来源'],['status','状态'],['definition','定义']],FIELDS.map(([key])=>{const m=p.metrics[key];return {...m,display:format(m.value,m.unit),source:sourceName(m.source),status:m.value===null?'未提供':'有效'};})));head.append(detail);panel.append(head);
 renderProfit(panel,data);
 dimension(panel,'Order来源网站金额',sourceText(p,'primary')+' · 主源未提供渠道订单数，缺值保留；这些是网站来源，不是Google营销归因渠道。',p.channels,[['name','来源网站'],['amountUsd','Order金额','USD'],['orders','Order渠道订单数','orders']],'amountUsd','USD');
 dimension(panel,'Admin网站来源分布',sourceText(p,'supplement')+' · site_rank实际返回，和Order图分开；不冒称投放渠道，不计算跨源渠道每单金额。',p.websiteDistribution,[['name','网站'],['orders','订单数','orders'],['revenueUsd','金额','USD']],'revenueUsd','USD');
 dimension(panel,'国家与地区',sourceText(p,'supplement')+' · country_rank订单维度；未与仅MMOEXP的GSC/GA4国家强行关联。',p.countries,[['name','国家地区'],['code','国家码'],['orders','订单数','orders'],['revenueUsd','金额','USD']],'revenueUsd','USD');
 dimension(panel,'订单设备',sourceText(p,'supplement')+' · chart_pay_device仅提供订单数，金额未提供。',p.devices,[['name','设备'],['orders','订单数','orders'],['revenueUsd','金额','USD']],'orders','orders');
 dimension(panel,'付款方式',sourceText(p,'supplement'),p.payments,[['name','方式'],['orders','订单数','orders'],['revenueUsd','金额','USD']],'revenueUsd','USD');
 dimension(panel,'游戏项目分布 · Admin补源',sourceText(p,'supplement')+' · 保留Admin游戏ID，不能当作Order或GA4游戏ID。',p.games,[['name','项目'],['adminGameId','Admin游戏ID'],['orders','订单数','orders'],['revenueUsd','金额','USD']],'revenueUsd','USD');
 dimension(panel,'产品类型 · Order主源',sourceText(p,'primary'),p.products,[['name','类型'],['type','产品tid'],['count','订单数','orders'],['value','金额','USD']],'value','USD');
 dimension(panel,'订单状态 · Order主源',sourceText(p,'primary'),p.statuses,[['name','状态'],['status','状态ID'],['counts','订单数','orders'],['value','金额','USD']],'value','USD');
 renderHistory(panel,p);
 const gap=section('KOL与跨源关联','本版提供真实经营维度，不假造跨源漏斗或转换率。');gap.append(el('p','折扣码/优惠券：'+(p.couponProvided?'已返回维度，但尚未有创作者映射。':'统一快照未提供，KOL订单归属无法确认。')),el('p','创作者粉丝、浏览、点赞、佣金和花名册：未接入。来源网站/支付设备不能替代KOL证据。'),el('p','营销对照：Google是独立自然周/品牌范围，本经营面板是全网站今日/历史范围；尚无同站点同日期的渠道、国家、设备或项目归因join，不计算逐用户转化率、经营ROAS或利润金额。'));panel.append(gap);
}
async function refresh(){if(!current?.isConnected||inFlight)return;inFlight=true;try{const next=await readSnapshot(root.fetch.bind(root),root.crypto,cache);cache=next;lastError=false;if(current?.isConnected)render(current,cache);}catch{lastError=true;if(current?.isConnected){if(cache)render(current,cache);else current.replaceChildren(el('p','经营快照暂不可用，请保留登录后稍后重试。缺失值没有填0。','failure'));}}finally{inFlight=false;}}
api.mount=panel=>{current=panel;if(cache)render(panel,cache);else panel.append(el('p','正在核验统一经营快照…','watermark'));refresh();};api.unmount=()=>{current=null;};api.refresh=refresh;api.render=render;
root.MMOEXPBusiness=api;setInterval(()=>{if(!document.hidden)refresh();},60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
})(typeof window!=='undefined'?window:globalThis);
