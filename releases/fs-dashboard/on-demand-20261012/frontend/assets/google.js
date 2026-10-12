export function mount(scope){
const {window,document,fetch,URL,setTimeout,setInterval,clearTimeout,clearInterval,requestAnimationFrame,cancelAnimationFrame,MutationObserver,ResizeObserver,addEventListener,matchMedia}=scope;
const globalThis=window;
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
let current=null,cache=null,inFlight=false,selectedProfile=scope.seed?.g_business_profile||'MMOEXP',lastError=false;
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
'use strict';
/* Server-authenticated read-only snapshots. No Google credential or mutation endpoint. */
(function(){
const labels={sessions:'会话',activeUsers:'活跃用户',newUsers:'新用户',engagedSessions:'参与会话',engagementRate:'参与率',screenPageViews:'页面/屏幕浏览',averageSessionDuration:'平均会话时长',bounceRate:'跳出率',ecommercePurchases:'购买事件',purchaseRevenue:'GA4报告收入',clicks:'点击',impressions:'展示',ctr:'CTR（点击率）',position:'平均位置',cost:'花费 · USD',cpc:'CPC（单次点击花费）· USD',conversions:'Ads归因转化',cpa:'CPA（单次转化花费）· USD',conversionsValue:'Ads归因价值 · USD',platformRoas:'Ads平台ROAS（广告回报倍数）',share:'占比',impressionShare:'展示占比',campaignId:'Campaign ID（广告系列编号）',customerId:'Customer ID（广告账号编号）',campaignName:'广告系列',date:'数据日期'};
const explanations={
 sessions:'一次访问过程；同一个人可多次访问。默认连续30分钟没有互动后结束一次会话，实际以GA4设置为准。',
 activeUsers:'在所选期间内达到GA4活跃条件的去重用户数；同一人在不同分组出现时，分组人数不能直接相加。',
 newUsers:'GA4首次记录到访问的用户数；不是后台首次付款的新客户。',
 engagedSessions:'达到参与条件的访问次数：超过设定时长（默认10秒）、触发关键事件，或浏览至少2个页面/屏幕，满足任一即可。',
 engagementRate:'参与会话数 ÷ 全部会话数；表示有较明显互动的访问占比。',
 screenPageViews:'页面或屏幕被查看的总次数；重复查看同一页面也计数。',
 averageSessionDuration:'每次访问平均持续多少秒；不是页面保持在前台的平均互动时长。',
 bounceRate:'未达到参与条件的会话占比，等于1减参与率；不是简单的“只看一页就离开”。',
 ecommercePurchases:'GA4记录的购买事件次数；埋点、重复上报和同意设置会影响结果，不等于后台订单数。',
 purchaseRevenue:'GA4根据购买事件记录的收入；受埋点和退款记录影响，仅作参考，不替代Admin经营销售额。',
 sessionSourceMedium:'这次访问从哪里来 / 通过什么方式来；来源是网站或平台，媒介是自然搜索、付费广告、引荐等。',
 deviceCategory:'访问时使用的设备类别，如电脑、手机、平板。',
 country:'访问所在地的国家或地区，通常根据网络位置判断；不代表国籍、收货地址或购买国家。',
 landingPage:'一次访问首先打开的页面路径；不是这次访问浏览的所有页面。',
 share:'该行会话数 ÷ 同范围GA4总会话数；不是人数占比，明细合计可能与独立汇总不同。',
 query:'用户在Google搜索时输入的词；受隐私保护影响，部分搜索词不会显示。',
 page:'在Google自然搜索中获得展示或点击的网站页面。',
 clicks:'点击次数：GSC为Google自然搜索结果点击，Ads为广告点击；不是去重用户数。',
 impressions:'展示次数：GSC为自然搜索结果被展示，Ads为广告被展示。',
 ctr:'点击率 = 点击次数 ÷ 展示次数；说明看到结果或广告后，有多少比例发生点击。',
 position:'Google自然搜索中网站最高位置的平均排名；数字越小通常排名越靠前，以GSC原值为准。',
 cost:'Google Ads记录的广告花费，单位美元；不是商品采购成本。',
 cpc:'平均每次广告点击花费 = 广告花费 ÷ 点击次数；没有点击时不可计算。',
 conversions:'Google Ads按账号转化设置和归因模型分配的转化次数，可为小数；不一定是订单。',
 cpa:'每次广告归因转化的平均花费 = 广告花费 ÷ 归因转化次数；没有转化时不可计算。',
 conversionsValue:'Google Ads为转化分配的价值，单位美元；不是Admin后台实收销售额。',
 platformRoas:'广告归因价值 ÷ 广告花费；例如2倍表示每花1美元对应2美元归因价值，不代表利润。',
 impressionShare:'此意图类别展示数 ÷ 同国GSC总展示数；不是Google Ads可获展示份额。',
 campaignId:'Google Ads广告系列的唯一编号。',customerId:'Google Ads广告账号的唯一编号；不同编号分别核算。',campaignName:'Google Ads中设置的广告系列名称。',
 currency:'广告账号记录的币种；美元指标按该账号原值展示，不混算不同币种。',timezone:'该广告账号统计数据采用的时区；可能与北京时间不同。',
 date:'这行数据对应的日期；按该来源自己的时区统计。',label:'该行对应的数据来源、广告账号或意图分类。',latestDate:'来源最近返回有效数据的日期；不是页面打开时间。',
 name:'后台原始折扣码或优惠券名称；名称本身不能证明推广归属。',site:'后台记录的适用网站；此处只展示明确属于MMOEXP主站的记录。',game:'后台配置的适用游戏；未提供时显示缺失。',uses:'后台累计使用次数，不是所选Google日期内的次数。',claimed:'后台累计领取次数，不等于去重领取人数。',usedAt:'后台记录的这次用券时间；当前列表没有按Google日期区间完整筛选。',batch:'后台记录的发券批次号，用于识别同一批活动。',repeatOrders90d:'后台提供的90天复购次数原值；不按当前日期区间重新计算。',
};
const sourceNames={google:'Google',bing:'必应',duckduckgo:'DuckDuckGo搜索',yahoo:'雅虎',baidu:'百度',yandex:'Yandex搜索','(direct)':'直接访问','accounts.google.com':'Google账号网站','youtube.com':'YouTube','ea.com':'EA网站','chatgpt.com':'ChatGPT','cardpay.com':'CardPay网站','js.klarna.com':'Klarna网站','search.brave.com':'Brave搜索网站','pale.tools':'Pale Tools网站'};
const mediumNames={organic:'自然搜索',cpc:'按点击付费广告',ppc:'按点击付费广告',referral:'网站引荐',email:'电子邮件',social:'社交流量','paid-social':'付费社交广告',display:'展示广告',affiliate:'联盟推广','ai-assistant':'AI助手引荐','(none)':'无媒介标记','(not set)':'未设置','(data not available)':'数据不可用'};
const regionEnglish=new Intl.DisplayNames(['en'],{type:'region',fallback:'code'}),regionChinese=new Intl.DisplayNames(['zh-Hans'],{type:'region',fallback:'code'});
const countryCodes=new Map();
for(let a=65;a<=90;a++)for(let b=65;b<=90;b++){const code=String.fromCharCode(a,b),name=regionEnglish.of(code);if(name!==code){countryCodes.set(name.toLowerCase(),code);countryCodes.set(code.toLowerCase(),code);}}
for(const [name,code] of Object.entries({'united states of america':'US','south korea':'KR','north korea':'KP','czech republic':'CZ','russian federation':'RU','turkey':'TR','vietnam':'VN','laos':'LA','palestine':'PS','hong kong':'HK','macau':'MO','taiwan':'TW'}))countryCodes.set(name,code);
for(const [name,code] of Object.entries({"": "001", "abw": "AW", "afg": "AF", "ago": "AO", "aia": "AI", "ala": "AX", "alb": "AL", "and": "AD", "are": "AE", "arg": "AR", "arm": "AM", "asm": "AS", "atg": "AG", "aus": "AU", "aut": "AT", "aze": "AZ", "bdi": "BI", "bel": "BE", "ben": "BJ", "bes": "BQ", "bfa": "BF", "bgd": "BD", "bgr": "BG", "bhr": "BH", "bhs": "BS", "bih": "BA", "blm": "BL", "blr": "BY", "blz": "BZ", "bmu": "BM", "bol": "BO", "bra": "BR", "brb": "BB", "brn": "BN", "btn": "BT", "bwa": "BW", "caf": "CF", "can": "CA", "cck": "CC", "che": "CH", "chl": "CL", "chn": "CN", "civ": "CI", "cmr": "CM", "cod": "CD", "cog": "CG", "cok": "CK", "col": "CO", "com": "KM", "cpv": "CV", "cri": "CR", "cub": "CU", "cuw": "CW", "cxr": "CX", "cym": "KY", "cyp": "CY", "cze": "CZ", "deu": "DE", "dji": "DJ", "dma": "DM", "dnk": "DK", "dom": "DO", "dza": "DZ", "ecu": "EC", "egy": "EG", "eri": "ER", "esp": "ES", "est": "EE", "eth": "ET", "fin": "FI", "fji": "FJ", "flk": "FK", "fra": "FR", "fro": "FO", "fsm": "FM", "gab": "GA", "gbr": "GB", "geo": "GE", "ggy": "GG", "gha": "GH", "gib": "GI", "gin": "GN", "glp": "GP", "gmb": "GM", "gnb": "GW", "gnq": "GQ", "grc": "GR", "grd": "GD", "grl": "GL", "gtm": "GT", "guf": "GF", "gum": "GU", "guy": "GY", "hkg": "HK", "hnd": "HN", "hrv": "HR", "hti": "HT", "hun": "HU", "idn": "ID", "imn": "IM", "ind": "IN", "iot": "IO", "irl": "IE", "irn": "IR", "irq": "IQ", "isl": "IS", "isr": "IL", "ita": "IT", "jam": "JM", "jey": "JE", "jor": "JO", "jpn": "JP", "kaz": "KZ", "ken": "KE", "kgz": "KG", "khm": "KH", "kir": "KI", "kna": "KN", "kor": "KR", "kwt": "KW", "lao": "LA", "lbn": "LB", "lbr": "LR", "lby": "LY", "lca": "LC", "lie": "LI", "lka": "LK", "lso": "LS", "ltu": "LT", "lux": "LU", "lva": "LV", "mac": "MO", "maf": "MF", "mar": "MA", "mco": "MC", "mda": "MD", "mdg": "MG", "mdv": "MV", "mex": "MX", "mhl": "MH", "mkd": "MK", "mli": "ML", "mlt": "MT", "mmr": "MM", "mne": "ME", "mng": "MN", "mnp": "MP", "moz": "MZ", "mrt": "MR", "msr": "MS", "mtq": "MQ", "mus": "MU", "mwi": "MW", "mys": "MY", "myt": "YT", "nam": "NA", "ncl": "NC", "ner": "NE", "nfk": "NF", "nga": "NG", "nic": "NI", "niu": "NU", "nld": "NL", "nor": "NO", "npl": "NP", "nru": "NR", "nzl": "NZ", "omn": "OM", "pak": "PK", "pan": "PA", "pcn": "PN", "per": "PE", "phl": "PH", "plw": "PW", "png": "PG", "pol": "PL", "pri": "PR", "prk": "KP", "prt": "PT", "pry": "PY", "pse": "PS", "pyf": "PF", "qat": "QA", "reu": "RE", "rou": "RO", "rus": "RU", "rwa": "RW", "sau": "SA", "sdn": "SD", "sen": "SN", "sgp": "SG", "shn": "SH", "sjm": "SJ", "slb": "SB", "sle": "SL", "slv": "SV", "smr": "SM", "som": "SO", "spm": "PM", "srb": "RS", "ssd": "SS", "stp": "ST", "sur": "SR", "svk": "SK", "svn": "SI", "swe": "SE", "swz": "SZ", "sxm": "SX", "syc": "SC", "syr": "SY", "tca": "TC", "tcd": "TD", "tgo": "TG", "tha": "TH", "tjk": "TJ", "tkl": "TK", "tkm": "TM", "tls": "TL", "ton": "TO", "tto": "TT", "tun": "TN", "tur": "TR", "tuv": "TV", "twn": "TW", "tza": "TZ", "uga": "UG", "ukr": "UA", "umi": "UM", "ury": "UY", "usa": "US", "uzb": "UZ", "vat": "VA", "vct": "VC", "ven": "VE", "vgb": "VG", "vir": "VI", "vnm": "VN", "vut": "VU", "wlf": "WF", "wsm": "WS", "yem": "YE", "zaf": "ZA", "zmb": "ZM", "zwe": "ZW"}))countryCodes.set(name,code);
function translatedDimension(dim,value){
 const original=value==null||value===''?'未知':String(value),key=original.toLowerCase();
 if(['(not set)','(other)','(data not available)','unknown','未知'].includes(key))return original+'（'+({'(not set)':'未设置：来源没有提供此信息','(other)':'其他汇总项','(data not available)':'数据不可用',unknown:'未知',未知:'未知'}[key])+'）';
 if(dim==='sessionSourceMedium'){
  const parts=original.split(/\s+\/\s+/),source=parts[0],medium=parts.slice(1).join(' / ');
  if(!medium)return original+'（来源或媒介未完整提供）';
  return original+'（'+(sourceNames[source.toLowerCase()]||'来源：'+source)+' / '+(mediumNames[medium.toLowerCase()]||'自定义媒介：'+medium)+'）';
 }
 if(dim==='country'){const code=countryCodes.get(key);return original+'（'+(code?regionChinese.of(code):'国家或地区名称待确认')+'）';}
 if(dim==='deviceCategory')return original+'（'+({desktop:'电脑',mobile:'手机',tablet:'平板',smarttv:'智能电视'}[key]||'其他设备类别')+'）';
 return original;
}

const categoryNames={brand:'品牌',transaction:'交易品类',content:'内容资讯',other:'其他'};
const rates=new Set(['ctr','bounceRate','engagementRate','share','impressionShare']);
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined&&text!==null)n.textContent=String(text);if(cls)n.className=cls;return n;}
function fmt(key,value){if(value===undefined||value===null||!Number.isFinite(Number(value)))return '—';const v=Number(value);if(rates.has(key))return (v*100).toFixed(2)+'%';if(key==='platformRoas')return v.toFixed(2)+'×';if(key==='averageSessionDuration')return v.toFixed(1)+' 秒';return new Intl.NumberFormat('zh-CN',{maximumFractionDigits:key==='position'?2:key==='conversions'?3:2}).format(v);}
function help(label,text){
 const button=el('button','?','help-icon');button.type='button';button.setAttribute('aria-label',label+'：查看说明');
 const tip=el('span',text,'help-tooltip');tip.id='field-tip-'+(++scope.tipId);tip.setAttribute('role','tooltip');tip.hidden=true;button.setAttribute('aria-describedby',tip.id);
 const hide=()=>{tip.hidden=true;tip.remove();};
 const show=()=>{scope.root.querySelectorAll('.help-tooltip').forEach(n=>n.remove());scope.root.append(tip);tip.hidden=false;const r=button.getBoundingClientRect(),box=tip.getBoundingClientRect();tip.style.left=Math.max(8,Math.min(r.left,innerWidth-box.width-8))+'px';tip.style.top=(r.bottom+box.height+8<innerHeight?r.bottom+8:Math.max(8,r.top-box.height-8))+'px';};
 button.addEventListener('mouseenter',show);button.addEventListener('mouseleave',hide);button.addEventListener('focus',show);button.addEventListener('blur',hide);button.addEventListener('click',show);button.addEventListener('keydown',event=>{if(event.key==='Escape')hide();});return button;
}
function field(label,text){const name=el('span',label,'field-label');if(text)name.append(help(label,text));return name;}
function table(columns,rows){const wrap=el('div',null,'table-scroll'),t=el('table'),h=el('thead'),hr=el('tr');for(const c of columns){const th=el('th');th.append(field(c.label||labels[c.key]||c.key,explanations[c.key]));hr.append(th);}h.append(hr);t.append(h);const b=el('tbody');for(const row of rows){const r=el('tr');for(const c of columns){const value=c.get?c.get(row):row[c.key];const td=el('td',c.numeric?fmt(c.key,value):value===undefined||value===null?'—':value);if(!c.numeric){td.textContent=translatedDimension(c.key,value);td.title=String(value??'');}r.append(td);}b.append(r);}if(!rows.length){const r=el('tr'),d=el('td','未返回可用明细；不按零处理。','empty');d.colSpan=columns.length;r.append(d);b.append(r);}t.append(b);wrap.append(t);return wrap;}
const metricCol=key=>({key,numeric:true,get:r=>r.metrics?.[key]});
function section(title,subtitle){const n=el('section',null,'report-section');n.append(el('h2',title));if(subtitle)n.append(el('p',subtitle,'section-meta'));return n;}
function changeText(change){if(!change)return '';const v=Number(change.value);return '较前周 '+(v>0?'+':'')+v.toFixed(2)+(change.kind==='percentage_points'?' 个百分点':'%');}
function cards(keys,values,changes){const grid=el('div',null,'kpi-grid');for(const key of keys){const item=el('article',null,'kpi');item.dataset.metric=key;item.append(field(labels[key],explanations[key]),el('strong',fmt(key,values?.[key])));if(changes?.[key])item.append(el('small',changeText(changes[key]),'change'));grid.append(item);}return grid;}
function bars(rows,dimension,metric,max=10){const box=el('div',null,'bar-chart');const list=rows.slice(0,max);const biggest=Math.max(...list.map(v=>Number(v.metrics?.[metric])||0),1);for(const row of list){const label=typeof dimension==='function'?dimension(row):row.dimensions?.[dimension]||row[dimension]||'未知';const item=el('div',null,'bar-row'),name=el('span',typeof dimension==='string'?translatedDimension(dimension,label):label,'bar-label');name.title=label;const track=el('div',null,'bar-track'),bar=el('i');bar.style.width=Math.max(0,(Number(row.metrics?.[metric])||0)/biggest*100)+'%';track.append(bar);item.append(name,track,el('b',fmt(metric,row.metrics?.[metric])));box.append(item);}if(!list.length)box.append(el('p','暂无可用数据。','empty'));return box;}
function line(rows,metric,period){const box=el('div',null,'line-chart');const heading=el('h3');heading.append(field(labels[metric]+' · 逐日',explanations[metric]));box.append(heading);const points=rows.filter(r=>r.dimensions?.date&&r.metrics?.[metric]!==undefined).sort((a,b)=>a.dimensions.date.localeCompare(b.dimensions.date));if(!points.length){box.append(el('p','暂无逐日数据。'));return box;}const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 620 205');svg.setAttribute('role','img');svg.setAttribute('aria-label',labels[metric]+'逐日趋势，缺失日期没有填零');const max=Math.max(...points.map(p=>Number(p.metrics[metric])),1),start=Date.parse(period.start+'T00:00:00Z');const xy=p=>[48+((Date.parse(p.dimensions.date+'T00:00:00Z')-start)/86400000)/Math.max(1,(Date.parse(period.end+'T00:00:00Z')-start)/86400000)*552,155-Number(p.metrics[metric])/max*120];let previous=null;for(const p of points){const [x,y]=xy(p);if(previous&&Date.parse(p.dimensions.date)-Date.parse(previous.dimensions.date)===86400000){const q=xy(previous),s=document.createElementNS(ns,'line');for(const [k,v] of Object.entries({x1:q[0],y1:q[1],x2:x,y2:y,stroke:'#13846d','stroke-width':3}))s.setAttribute(k,String(v));svg.append(s);}const c=document.createElementNS(ns,'circle');c.setAttribute('cx',x);c.setAttribute('cy',y);c.setAttribute('r',4);c.setAttribute('fill','#13846d');const title=document.createElementNS(ns,'title');title.textContent=p.dimensions.date+' '+fmt(metric,p.metrics[metric]);c.append(title);svg.append(c);const text=document.createElementNS(ns,'text');text.setAttribute('x',x);text.setAttribute('y',180);text.setAttribute('text-anchor','middle');text.textContent=p.dimensions.date.slice(5);svg.append(text);previous=p;}for(const [y,value] of [[35,max],[155,0]]){const text=document.createElementNS(ns,'text');text.setAttribute('x',0);text.setAttribute('y',y);text.textContent=fmt(metric,value);svg.append(text);}box.append(svg);return box;}
function statusNote(s){const c=s.coverage||{};let text='来源时区 '+s.timezone+' · 请求 '+c.requested_start+' — '+c.requested_end+' · 实际返回 '+c.returned_days+'/'+c.requested_days+' 天 · 最新返回日期 '+(c.latest_data_date||'—');if(c.query_range_complete!==undefined){text='来源时区 '+s.timezone+' · 查询范围 '+c.requested_start+' — '+c.requested_end+' · 查询/分页'+(c.query_range_complete?'完整':'尚不完整')+' · 返回有指标行 '+c.returned_days+'/'+c.requested_days+' 天 · 最近有指标日期 '+(c.latest_data_date||'—');if(c.no_metric_row_dates?.length)text+=' · 日期未返回指标行 '+c.no_metric_row_dates.join('、')+'；API按日期分段会省略所有选定指标均为零的行，未补零记录，不能当作采集失败。';}else if(c.missing_dates?.length)text+=' · 缺少 '+c.missing_dates.join('、');const q=s.status?.quality||{};if(q.subject_to_thresholding)text+=' · 受隐私阈值影响';if(q.sampling_present)text+=' · 存在采样';if(q.data_loss_from_other_row)text+=' · 高基数Other行数据损失';if(q.active_metric_restrictions?.length)text+=' · 部分指标权限受限';const n=el('p',text,'watermark');n.dataset.nativeSummary='来源时区 '+s.timezone+' · 覆盖 '+c.returned_days+'/'+c.requested_days+' 天 · 数据至 '+(c.latest_data_date||'—')+(c.query_range_complete===false?' · 查询尚不完整':'')+(q.subject_to_thresholding?' · 隐私阈值影响':'')+(q.sampling_present?' · 存在采样':'')+(q.data_loss_from_other_row?' · Other行损失':'')+(q.active_metric_restrictions?.length?' · 指标权限受限':'')+(s.status?.retained_previous?' · 请求失败，保留旧报告':'');if(s.status?.retained_previous)n.append(el('strong',' 最近请求未成功，保留上次有效报告。'));if(s.status?.collected_at)n.append(el('span',' · 采集 '+s.status.collected_at));return n;}
function coverageNote(t,query=false){let text='返回维度 '+t.returned_dimension_rows+' 行 · 当前展示 '+t.displayed_rows+' 行 · 明细'+(t.coverage_metric==='sessions'?'会话':'点击')+'覆盖 '+fmt('share',t.row_coverage);if(t.coverage_basis==='byPage_total')text+=' · 分母为同口径byPage总点击，区别于站点byProperty总量';if(query)text+=' · 搜索词隐私/Top行限制可使明细少于总量；覆盖率不代表完整性';if(t.status?.quality?.pagination_capped)text+=' · 达到本次分页上限';if(t.status?.retained_previous)text+=' · 上次有效报告';return el('p',text,'coverage');}
function renderGA(parent,s,period){const block=section('GA4 · 网站行为','Property（GA4资源编号） '+s.resource+' · 新用户是GA4首次访问用户，经营新客采用统一业务快照定义。');block.append(statusNote(s));block.append(cards(['sessions','activeUsers','newUsers','engagedSessions','engagementRate','screenPageViews','averageSessionDuration','bounceRate','ecommercePurchases','purchaseRevenue'],s.metrics,s.changes));if(s.comparison_status!=='complete_source_dates')block.append(el('p','前周对比缺少完整来源日期，未计算变化率。','coverage'));block.append(el('p','GA4收入仅供埋点核查，不替代经营销售额；零值原因尚未确定。','financial-note'));
const plotGrid=el('div',null,'plot-grid');plotGrid.append(line(s.daily,'sessions',period),line(s.daily,'activeUsers',period));block.append(plotGrid);
for(const [name,title,dim,limit] of [['source_medium','会话来源 / 媒介','sessionSourceMedium',10],['device','设备','deviceCategory',20],['country','国家','country',10],['landing_page','落地页','landingPage',15]]){const t=s.breakdowns[name],card=el('article',null,'breakdown');const heading=el('h3');heading.append(field(title,explanations[dim]));card.append(heading,coverageNote(t),bars(t.rows,dim,'sessions',limit),table([{key:dim,label:title,get:r=>r.dimensions?.[dim]},metricCol('sessions'),metricCol('activeUsers'),metricCol('bounceRate'),metricCol('share')],t.rows));block.append(card);}parent.append(block);}
function renderGSC(parent,s,period){const block=section('GSC · 自然搜索','Property（GSC资源） '+s.resource+' · 仅final（最终版）数据，完整性按实际返回日期判断；平均位置使用来源汇总，不平均日均值。');block.append(statusNote(s),cards(['impressions','clicks','ctr','position'],s.metrics,s.changes));if(s.comparison_status!=='complete_source_dates')block.append(el('p','日期不足，前周变化率不可用。','coverage'));const plots=el('div',null,'plot-grid');plots.append(line(s.daily,'clicks',period),line(s.daily,'impressions',period));block.append(plots);for(const [name,title,dim] of [['query','Top 20 搜索词','query'],['page','Top 15 页面','page'],['country','Top 10 国家','country']]){const t=s.breakdowns[name],card=el('article',null,'breakdown');card.append(el('h3',title),coverageNote(t,true),bars(t.rows,dim,'clicks',name==='query'?10:15),table([{key:dim,label:title,get:r=>r.dimensions?.[dim]},...['clicks','impressions','ctr','position'].map(metricCol)],t.rows));block.append(card);}parent.append(block);
const markets=section('主要市场 × 搜索意图','四类规则按优先级匹配：品牌 → 交易品类 → 内容资讯 → 其他。未返回/匿名词不硬填到“其他”。展示占比的分母为同国GSC总展示。');const rule=el('details');rule.append(el('summary','查看分类规则 '+period.query_rules.version),el('pre',JSON.stringify(period.query_rules,null,2)));markets.append(rule);for(const market of s.markets){const box=el('article',null,'breakdown');box.append(el('h3',market.label+(market.country_codes.length?' · '+market.country_codes.join(','):'')));if(!market.available){box.append(el('p','此市场未返回可用country×query记录；未假定为零，未与订单国家强行关联。','empty'));markets.append(box);continue;}box.append(el('p','搜索词点击覆盖 '+fmt('share',market.query_row_coverage)+' · 隐私和Top行限制可能导致不足100%。','coverage'));const categoryRows=market.categories.map(v=>({label:categoryNames[v.category],metrics:v.metrics}));box.append(bars(categoryRows,'label','impressions',4),table([{key:'label',label:'意图类别'},...['impressions','clicks','impressionShare','ctr','position'].map(metricCol)],categoryRows),el('h4','Top 15 搜索词'),table([{key:'query',label:'搜索词',get:r=>r.dimensions.query},...['clicks','impressions','ctr','position'].map(metricCol)],market.top_queries));markets.append(box);}parent.append(markets);}
function renderAds(parent,accounts,brand,period){const block=section('Google Ads · '+(brand==='rsorder'?'RSOrder':'MMOEXP'),'按Customer ID分开核算。RSOrder-1与rsgoldfast.com是两个不同ID、同属RSOrder业务；不按名称重复计数。转化可为小数，归因价值不是经营销售额。');const overview=accounts.filter(a=>a.metrics).map(a=>({label:a.label+' · '+a.customerId,metrics:a.metrics}));block.append(bars(overview,'label','cost',8),table([{key:'label',label:'账号'},{key:'customerId',label:'Customer ID（广告账号编号）'},...['cost','clicks','cpc','conversions','cpa','conversionsValue','platformRoas'].map(metricCol)],accounts));for(const a of accounts){const box=el('article',null,'breakdown');box.dataset.customer=a.customerId;box.append(el('h3',a.label+' · '+a.customerId),el('p','当前Google名称 '+(a.observed_name||'未读取')+' · '+a.currency+' · '+a.timezone,'section-meta'),statusNote(a),cards(['cost','clicks','cpc','conversions','cpa','conversionsValue','platformRoas'],a.metrics,a.changes));if(a.comparison_status!=='complete_query_ranges')box.append(el('p','本账号查询范围或分页未完整验证，未计算前周变化率。','coverage'));box.append(table([{key:'date',get:r=>r.dimensions.date},...['impressions','clicks','conversions','conversionsValue'].map(metricCol),{key:'cost',numeric:true,get:r=>Number(r.metrics.costMicros)/1000000}],a.daily));block.append(box);}
const campaigns=accounts.flatMap(a=>a.campaigns).sort((a,b)=>Number(b.metrics.cost)-Number(a.metrics.cost)),top=campaigns.slice(0,12);const camp=el('article',null,'breakdown');camp.append(el('h3','广告系列 · Top 8图 / Top 12表'),el('p','同一Customer / Campaign / Date只计一次；下表为 '+period.start+' — '+period.end+' 的各账号币种及来源时区。','coverage'),bars(campaigns,r=>r.campaignName+' · '+r.customerId+'/'+r.campaignId,'cost',8),table([{key:'campaignName'}, {key:'customerId'}, {key:'campaignId'}, {key:'currency',label:'币种'}, {key:'timezone',label:'来源时区'}, ...['cost','clicks','cpc','conversions','cpa','conversionsValue','platformRoas'].map(metricCol)],top));for(const a of accounts)camp.append(el('p',a.customerId+' · 返回广告系列 '+a.campaign_count+' · 系列花费覆盖账号总花费 '+fmt('share',a.campaign_row_cost_coverage)+(a.campaign_status?.retained_previous?' · 保留旧报告':''),'coverage'));block.append(camp);parent.append(block);}
function renderBusinessLinks(parent,value){
 const block=section('经营关联 · MMOEXP主站','Admin会员统计、折扣码与优惠券；与Google流量分别统计，原始日期与范围单独列明。');
 block.dataset.businessLinks='true';parent.querySelector('[data-business-links]')?.remove();
 if(!value||value.status==='unavailable'){block.append(el('p','经营关联尚未读取，请在上方选择日期并应用区间。','coverage'));parent.append(block);return;}
 const member=value.membership;block.append(el('h3','会员统计'));
 if(member?.status==='available'){
  block.append(el('p',member.start+' — '+member.end+' · '+member.site+' · 注册与支付按同一期间统计 · Asia/Shanghai','coverage'));
  const grid=el('div',null,'kpi-grid');for(const m of member.metrics){const card=el('article',null,'kpi');card.dataset.metric=m.field;card.append(field(m.label+(m.unit==='USD'?' · USD':''),m.explanation),el('strong',fmt(m.field,m.value)));grid.append(card);}block.append(grid);
 }else block.append(el('p','会员统计本次未取得，未填零。','coverage'));
 for(const [key,title] of [['discount','最近折扣码配置'],['coupon','最近优惠券配置'],['usage','最近用券记录']]){
  const part=value[key];block.append(el('h3',title));
  if(!part||part.status==='unavailable'){block.append(el('p','本次未取得，未填零。','coverage'));continue;}
  block.append(el('p',part.basis+' · 返回主站 '+part.returnedMainSiteRows+' 条 / 本页 '+part.returnedRows+' 条；后台全部站点总项数 '+fmt('',part.totalAllSites),'coverage'));
  const columns=[{key:'name',label:key==='discount'?'折扣码':'优惠券名称'},{key:'site',label:'适用站点'}];
  if(key==='usage')columns.push({key:'usedAt',label:'使用时间'},{key:'batch',label:'活动批次'},{key:'repeatOrders90d',label:'后台90天复购次数',numeric:true});
  else {columns.push({key:'game',label:'适用游戏'},{key:'uses',label:'累计使用次数',numeric:true});if(key==='coupon')columns.push({key:'claimed',label:'累计领取次数',numeric:true});}
  block.append(table(columns,part.rows));
 }
 block.append(el('p','当前未接入创作者名单、佣金或GA4用户与订单的逐人关联，不能据折扣码名称推断KOL归属或计算跨源转化率。','coverage'));parent.append(block);
}
async function loadBusinessLinks(parent,period,value){
 const key=period.start+'_'+period.end;scope.businessLinksCache??=new Map();
 const cached=scope.businessLinksCache.get(key);
 if(value?.membership?.start===period.start&&value.membership.end===period.end){renderBusinessLinks(parent,value);return;}
 if(cached&&Date.now()-cached.at<300000){renderBusinessLinks(parent,cached.value);return;}
 renderBusinessLinks(parent,null);
 try{
  const url='/dashboard/marketing/business-links.json?'+new URLSearchParams({start:period.start,end:period.end});
  for(let n=0;n<20;n++){
   const r=await fetch(url,{cache:'no-store',credentials:'same-origin'});
   if(r.status===202||r.status===429){await new Promise(resolve=>setTimeout(resolve,5000));continue;}
   if(!r.ok)throw Error('links_unavailable');const links=await r.json();
   if(links.start!==period.start||links.end!==period.end)throw Error('links_range_mismatch');
   scope.businessLinksCache.set(key,{at:Date.now(),value:links});if(parent.isConnected)renderBusinessLinks(parent,links);return;
  }
 }catch{}
 if(parent.isConnected)renderBusinessLinks(parent,{status:'unavailable'});
}
function rangeControls(toolbar,container,model,periods,selector){
 const controls=el('form',null,'traffic-range');controls.setAttribute('aria-label','流量分析自定义区间');
 const start=el('input'),end=el('input');start.type=end.type='date';start.required=end.required=true;start.setAttribute('aria-label','流量开始日期');end.setAttribute('aria-label','流量结束日期');
 const current=periods.find(p=>p.id===selector.value)||periods[0];start.value=current?.start||'';end.value=current?.end||'';
 const apply=el('button','应用区间');apply.type='submit';const note=el('p','可自定义起止日期；Google各来源按自己的时区与实际覆盖返回，关联会员按北京时间统计。','coverage');note.setAttribute('role','status');
 controls.append(el('span','自定义日期'),start,el('span','至'),end,apply);toolbar.after(controls,note);
 controls.addEventListener('submit',async event=>{
  event.preventDefault();if(!start.value||!end.value||start.value>end.value){note.textContent='起始日期不能晚于结束日期。';return;}
  const lo=start.value,hi=end.value;apply.disabled=true;note.textContent='正在查询 '+lo+' — '+hi+'；来源读取期间保留原视图。';
  try{
   const url='/dashboard/marketing/range.json?'+new URLSearchParams({start:lo,end:hi});let result;
   for(let attempt=0;attempt<130;attempt++){
    const response=await fetch(url,{cache:'no-store',credentials:'same-origin'});if(response.status===202){await new Promise(resolve=>setTimeout(resolve,5000));continue;}
    if(!response.ok)throw Error(response.status===429?'已有区间查询正在运行，请稍后再试。':'区间查询未成功，请检查日期或重新登录后再试。');
    result=await response.json();break;
   }
   if(!result||result.status!=='available'||result.start!==lo||result.end!==hi||!result.period)throw Error('这次区间未取得可用数据，已保留原视图。');
   if(!container.isConnected||scope.root!==container.getRootNode()&&!scope.root.contains(container))return;
   const next=structuredClone(model),p=result.period;p.id='custom_'+lo+'_'+hi;p.isCustomRange=true;
   next.details.periods=[p,...next.details.periods.filter(x=>!x.isCustomRange)];next.businessLinks=result.businessLinks;scope.customRange={period:p,businessLinks:result.businessLinks};container.dataset.period=p.id;render(container,next);
   container.querySelector('.traffic-range + .coverage').textContent='已查询 '+lo+' — '+hi+'；各来源覆盖及失败项见对应卡片。';
  }catch(error){if(container.isConnected)note.textContent=error.message;}finally{apply.disabled=false;}
 });
}

function render(container,model){scope.tipId=scope.tipId||0;scope.root.querySelectorAll('.help-tooltip').forEach(n=>n.remove());scope.model=model;const brand=container.dataset.brand||'mmoexp',saved=container.dataset.period;container.replaceChildren();if(model.schemaVersion!==1||model.isMock!==false){container.append(el('p','未取得已验证真实快照。','failure'));return;}const header=el('header',null,'module-heading'),title=el('div');title.append(el('small','MARKETING INTELLIGENCE','eyebrow'),el('h1','Google 运营数据'),el('p','流量、搜索、广告分来源核对 · MMOEXP / RSOrder分品牌'));const home=el('a','返回主页','home-link');home.href='/dashboard/';header.append(title,home);container.append(el('p','Google快照生成 '+model.data_generated_at+' · Google每日北京时间09:00采集 / 页签每5分钟检查 · 经营标签独立每60秒检查 · 不缓存','snapshot-time'));const latest=el('p','日汇总最新数据：'+model.sources.map(s=>s.id.toUpperCase()+' '+(s.latestDate||'—')).join(' · ')+'。以下细分按所选完整自然周请求，各来源实际覆盖单独显示。','watermark');container.append(latest,el('aside','经营销售额以order.p2pah全网站订单主源为准；GA4购买事件、Ads归因价值分别展示，不拼成全站财务或逐用户转化率。','financial-note'));
const toolbar=el('div',null,'toolbar'),tabs=el('div',null,'brand-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','经营品牌');const periods=model.details?.periods||[],selector={value:periods.some(p=>p.id===saved)?saved:periods[0]?.id};toolbar.append(tabs);container.append(toolbar);rangeControls(toolbar,container,model,periods,selector);const panel=el('div');panel.id='brand-panel';panel.setAttribute('role','tabpanel');container.append(panel);const buttons=[];
function show(which){container.dataset.brand=which;container.dataset.period=selector.value;container.querySelector('.traffic-range').hidden=which==='business';window.MMOEXPBusiness?.unmount();for(const button of buttons){const selected=button.dataset.brand===which;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;}panel.replaceChildren();panel.setAttribute('aria-labelledby','tab-'+which);if(which==='business'){window.MMOEXPBusiness?.mount(panel);return;}const p=periods.find(v=>v.id===selector.value);if(!p){panel.append(el('p','细分报告尚未接入。日汇总请使用现有数据，失败不按零显示。','empty'),table([{key:'label',label:'来源'},{key:'latestDate',label:'最新来源日期'}],model.sources.concat(model.adsAccounts||[])));return;}panel.append(el('p',(p.isCustomRange?'自定义区间 ':'统计周 ')+p.start+' — '+p.end+' · 前周 '+(p.comparison_period||'未取得')+' · '+(which==='rsorder'?'仅RSOrder业务的两个Ads customer；其GA4/GSC未接入。':'MMOEXP GA4/GSC与指定Ads customer。'),'period-title'));if(which==='mmoexp'){renderGA(panel,p.sources.ga4,p);renderGSC(panel,p.sources.gsc,p);}renderAds(panel,p.adsAccounts.filter(a=>a.brand===which),which,p);const gaps=section('尚未接入的经营关联','这里保留明确缺口，不把未接入字段填成零。');gaps.append(el('p','所有网站经营指标、项目利润率及国家/设备等维度见“经营对照·所有网站”标签；采集与Google独立，不混算转化率。','coverage'));for(const gap of model.details.phase2_gaps.filter(gap=>!gap.module.includes('订单/游戏'))){const connected=which==='mmoexp'&&/KOL|折扣码|优惠券|会员/.test(gap.module);gaps.append(el('h3',connected?'KOL推广与订单归因':gap.module),el('p',connected?'会员统计、折扣码和优惠券已接入上方经营关联；创作者归属、佣金、推广花费与渠道订单归因仍未接入。':gap.reason,'coverage'));}if(which==='mmoexp'){const links=el('div');links.className='business-links-host';panel.append(links);loadBusinessLinks(links,p,model.businessLinks);}panel.append(gaps);}
for(const [b,label] of [['mmoexp','MMOEXP'],['rsorder','RSOrder'],['business','经营对照·所有网站']]){const button=el('button',label);button.id='tab-'+b;button.type='button';button.dataset.brand=b;button.setAttribute('role','tab');button.setAttribute('aria-controls','brand-panel');button.addEventListener('click',()=>show(b));buttons.push(button);tabs.append(button);}tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const i=buttons.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(i+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();show(buttons[next].dataset.brand);});show(['rsorder','business'].includes(brand)?brand:'mmoexp');container.append(el('footer','已登录只读 · Google广告写操作未开放 · 查询分类规则可查看 · 来源数据可修订','module-footer'));}
async function load(container){try{const response=await fetch('/dashboard/marketing/data.json',{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw Error('DATA_NOT_AVAILABLE');scope.checkedAt=new Date().toISOString();const fresh=await response.json();if(scope.customRange){fresh.details.periods=[scope.customRange.period,...fresh.details.periods];fresh.businessLinks=scope.customRange.businessLinks;}render(container,fresh);}catch{const old=container.querySelector('.refresh-error');if(old)old.remove();container.prepend(el('p','本次更新未成功；若有已显示数据则保留，重新登录后再刷新。','refresh-error failure'));}}
window.MMOEXPMarketing={render,load};const target=document.getElementById('marketing');if(target){load(target);setInterval(()=>{if(!document.hidden)load(target);},300000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load(target);});}
})();
let workspaceQueued=false;
function workspaceState(){const target=document.getElementById('marketing');scope.businessProfile=target.querySelector('[aria-label="经营项目"]')?.value||scope.businessProfile||scope.seed?.g_business_profile||'MMOEXP';return {g_brand:target.dataset.brand||'mmoexp',g_period:target.dataset.period||'',g_source:scope.source||'all',g_business_profile:scope.businessProfile,details:target.querySelector('.snapshot-time')?.textContent,generatedAt:scope.model?.data_generated_at,checkedAt:scope.checkedAt,phase:target.querySelector('.refresh-error')?'error':target.querySelector('.brand-tabs')?'available':'loading'};}
function workspaceApply(s){
 const target=document.getElementById('marketing');if(!scope.model)return false;
 if(scope.model.details?.periods.some(p=>p.id===s.g_period)){target.dataset.period=s.g_period;window.MMOEXPMarketing.render(target,scope.model);}
 target.querySelector('[data-brand="'+(['mmoexp','rsorder','business'].includes(s.g_brand)?s.g_brand:'mmoexp')+'"]')?.click();
 scope.source=['all','ga4','gsc','ads'].includes(s.g_source)?s.g_source:'all';workspaceSync();return true;
}
function workspaceSync(){if(workspaceQueued)return;workspaceQueued=true;requestAnimationFrame(()=>{
 workspaceQueued=false;const target=document.getElementById('marketing'),toolbar=target.querySelector('.toolbar');
 if(toolbar&&!document.getElementById('google-sources')){const tabs=document.createElement('nav');tabs.id='google-sources';tabs.className='content-tabs';tabs.setAttribute('aria-label','Google 来源');
  for(const [key,label] of [['all','全部来源'],['ga4','GA4 · 站内行为'],['gsc','GSC · 自然搜索'],['ads','Ads · 广告投放']]){const button=document.createElement('button');button.type='button';button.dataset.source=key;button.textContent=label;button.onclick=()=>{scope.source=key;workspaceSync();const block=[...target.querySelectorAll('.report-section')].find(s=>s.dataset.source===key);block?.scrollIntoView({block:'start'});};tabs.append(button);}toolbar.after(tabs);}
 for(const block of target.querySelectorAll('#brand-panel > .report-section')){const title=block.querySelector('h2')?.textContent||'';const key=title.startsWith('GA4')?'ga4':title.startsWith('GSC')||title.includes('搜索意图')?'gsc':title.startsWith('Google Ads')?'ads':'other';block.dataset.source=key;}
 for(const button of target.querySelectorAll('#google-sources button')){button.setAttribute('aria-pressed',String((scope.source||'all')===button.dataset.source));button.disabled=target.dataset.brand!=='mmoexp'&&['ga4','gsc'].includes(button.dataset.source);}
 const time=target.querySelector('.snapshot-time');if(time&&!time.closest('details')){const detail=document.createElement('details');detail.className='source-details';detail.append(document.createElement('summary'));detail.firstChild.textContent='Google 快照与口径详情';target.append(detail);detail.append(time);
  for(const p of target.querySelectorAll(':scope > .watermark,:scope > .financial-note'))detail.append(p);
 }
 const period=target.querySelector('#brand-panel > .period-title'),overall=target.querySelector(':scope > .source-details');
 if(period&&overall){overall.querySelector('[data-panel-period]')?.remove();period.dataset.panelPeriod='true';overall.append(period);}
 const head=target.querySelector('.business-toolbar')?.closest('.report-section');
 if(head&&!head.querySelector('.native-audit')){const detail=document.createElement('details');detail.className='source-details native-audit';detail.append(document.createElement('summary'));detail.firstChild.textContent='经营对照来源与口径';
  for(const p of head.querySelectorAll(':scope > .section-meta,:scope > .watermark,:scope > .coverage,:scope > .financial-note'))detail.append(p);head.append(detail);
 }
 for(const card of target.querySelectorAll('.report-section,.breakdown')){const note=card.querySelector(':scope > .watermark[data-native-summary]');if(!note)continue;
  const line=document.createElement('p');line.className='source-summary';line.textContent=note.dataset.nativeSummary;note.before(line);
  const detail=document.createElement('details');detail.className='source-details source-audit';detail.append(document.createElement('summary'));detail.firstChild.textContent='来源覆盖与口径详情';card.append(detail);detail.append(note);
  const meta=card.querySelector(':scope > .section-meta');if(meta)detail.append(meta);
 }
 scope.changed(workspaceState());
});}
new MutationObserver(workspaceSync).observe(scope.root,{subtree:true,childList:true,attributes:true,attributeFilter:['data-brand','data-period']});workspaceSync();

return {state:workspaceState,apply:workspaceApply,update:()=>window.MMOEXPMarketing.load(document.getElementById("marketing"))};
}
