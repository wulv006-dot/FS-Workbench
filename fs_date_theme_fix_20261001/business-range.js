(function(root){'use strict';
const day=s=>String(s||'').slice(0,10);
const shift=(s,n)=>new Date(Date.parse(day(s)+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
const missing=()=>({value:null,status:'range_unavailable',definition:'该区间未提供准确聚合；不累加每日人数或百分比'});
function matches(period,range){return range.grain!=='hour'&&period&&day(period.start)===day(range.start)&&
 (period.end.endsWith('00:00')?shift(period.end,-1):day(period.end))===day(range.end);}
function select(data,range){
 if(!range)return data;
 const profiles={};
 for(const [key,p] of Object.entries(data.profiles||{})){
  const series=data.dashboard?.profiles?.[key]?.series||[];
  const points=range.grain==='hour'?(data.dashboard?.profiles?.[key]?.hourly||[]).map(r=>({...r,date:r.ts})):series;
  const rows=points.filter(r=>r.date>=range.start&&r.date<=range.end);
  const covered=rows.length>0&&range.start>=(points[0]?.date||'')&&range.end<=(points.at(-1)?.date||'');
  const hist=data.rangeMeta?.[key]?.primaryHistory;
  const exact=matches(p.period,range)?p.primary:matches(hist?.period,range)?hist:null;
  const metrics=Object.fromEntries(Object.keys(p.metrics||{}).map(k=>[k,missing()]));
  if(exact){Object.assign(metrics,exact.metrics||{});metrics.orders={value:exact.orders,source:'primary'};metrics.revenueUsd={value:exact.revenueUsd,source:'primary'};}
  else if(covered){metrics.orders={value:rows.reduce((a,r)=>a+r.orders,0),source:'primary',definition:'Order所选区间订单桶合计'};
   metrics.revenueUsd={value:Math.round(rows.reduce((a,r)=>a+r.amount,0)*100)/100,source:'primary',definition:'Order所选区间销售额桶合计'};}
  const sameSupplement=matches(p.supplement?.period,range);
  const supplement=sameSupplement?p.supplement:{...p.supplement,period:{start:range.start,end:range.end},metrics:Object.fromEntries(Object.keys(p.supplement?.metrics||{}).map(k=>[k,missing()])),dimensions:{}};
  profiles[key]={...p,period:{start:range.start,end:range.end},metrics,supplement,dimensions:matches(p.period,range)?p.dimensions:{},rangeSelected:true,rangeExact:!!exact,rangeCovered:!!exact||covered};
 }
 return {...data,profiles,selectedRange:range};
}
function tableWindow(rows,range,days){if(!range?.start||!range?.end)return {rows:[],remaining:0};const selected=rows.filter(r=>r.d>=range.start&&r.d<=range.end);const lo=shift(range.end,-(days-1));return {rows:selected.filter(r=>r.d>=lo),remaining:selected.filter(r=>r.d<lo).length};}
root.FSBusinessRange={select,matches,shift,tableWindow};
})(typeof window!=='undefined'?window:globalThis);
