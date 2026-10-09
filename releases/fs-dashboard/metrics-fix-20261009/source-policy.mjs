// User-approved 2026-10-09: Admin main-site values; labelled Order supplements and estimated profit.
export function fsMainSite(profile){
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

export function fsReferenceTotal(profile){
 const main=fsMainSite(profile).metrics.revenueUsd.value,rows=profile?.dimensions?.channels;
 const primary=profile?.primary,admin=profile?.supplement;
 if(main===null||primary?.status!=='available'||primary?.currency!=='USD'||primary.period?.start!==admin?.period?.start||primary.period?.end!==admin?.period?.end||!Array.isArray(rows))return null;
 const names=rows.map(r=>r.name),known=['www.mmoexp.com','eldorado.gg','g2g.com'];
 if(new Set(names).size!==names.length||!known.every(s=>names.includes(s)))return null;
 if(rows.some(r=>typeof r.amountUsd!=='number'||!Number.isFinite(r.amountUsd)))return null;
 // Other brands and backend reconciliation differences do not invalidate explicit satellite amounts.
 return (Math.round(main*100)+rows.filter(r=>['eldorado.gg','g2g.com'].includes(r.name)).reduce((n,r)=>n+Math.round(r.amountUsd*100),0))/100;
}
