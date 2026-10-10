(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.FSHomeMetrics=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 function beijingDate(now=new Date()){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);}
 function unavailable(reason){return {status:'unavailable',reason,metrics:{orders:null,revenueUsd:null,newCustomers:null}};}
 function normaliseToday(d){
  if(!d||d.status!=='available'||d.metricScope!=='ALL_WEBSITES'||d.timezone!=='Asia/Shanghai'||d.currency!=='USD')return unavailable('范围或来源不符');
  if(d.source?.system!=='order.p2pah.cn'||d.source.normalisedScope!=='all-websites'||!Number.isFinite(Date.parse(d.generatedAt))||!d.period||!d.period.start.startsWith(d.date))return unavailable('主源合同不符');
  const m=d.metrics;for(const k of ['orders','revenueUsd'])if(typeof m?.[k]!=='number'||!Number.isFinite(m[k])||m[k]<0)return unavailable('主源缺失');
  if(!Number.isInteger(m.orders))return unavailable('订单无效');
  if(m.newCustomers!==null&&(!Number.isInteger(m.newCustomers)||m.newCustomers<0||d.supplement?.system!=='admin.p2pah.cn'||d.supplement.normalisedScope!=='all-websites'))return unavailable('新客补源无效');
  return d;
 }
 function safePath(path){return typeof path==='string'&&path.startsWith('/')&&!path.startsWith('//')&&!path.includes('\\')&&!/[\u0000-\u0020]/.test(path)&&!path.split('/').includes('..');}
 return {beijingDate,normaliseToday,unavailable,safePath};
});
