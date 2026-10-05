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
root.MMOEXPWeeklyBusinessCore=api;
})(typeof window!=='undefined'?window:globalThis);
