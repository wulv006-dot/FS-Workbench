function fsProcurementProjection(data, selection) {
 if(data?.status!=='available'||data.revenueBasis!=='admin_order_cny'||data.period?.start!==selection.start||data.period?.end!==selection.end)throw Error('采购毛利来源或日期不一致');
 const m=data.denominator;
 if(!m||!['orders','completedOrders','coveredOrders','missingCostOrders','legacyRevenueOrders','pendingOrders'].every(k=>Number.isSafeInteger(m[k])&&m[k]>=0)||m.coveredOrders>m.completedOrders||m.completedOrders>m.orders||m.legacyRevenueOrders)throw Error('采购毛利覆盖合同错误');
 if(m.coveredOrders&&(!['saleCny','costCny','profitCny'].every(k=>Number.isFinite(m[k]))||m.saleCny<0||m.costCny<0||Math.abs(m.saleCny-m.costCny-m.profitCny)>0.011||(m.saleCny? !Number.isFinite(m.margin)||Math.abs(m.profitCny/m.saleCny-m.margin)>0.000001:m.margin!==null)))throw Error('采购毛利金额合同错误');
 return {...m,profitCny:m.coveredOrders?m.profitCny:m.orders===0?0:null,margin:m.coveredOrders?m.margin:null,
  capturedAt:data.generatedAt,costCapturedAt:data.sources?.cost?.generatedAt||null,refreshing:!!data.refreshing,stale:!!data.stale,costError:!!data.costError};
}
let procurementRead=null,procurementForce=false;
function fsProcurementQuery(profile,all,selection){
 if(all||selection?.grain!=='day'||!selection.start||!selection.end)return null;
 if(profile?.key==='FC27'&&Object.entries(fcFilters).some(([key,value])=>value!==(key==='site_group'?'main':'all')))return null;
 const gid=profile?.key==='MMOEXP'?'':String(profile?.supplement?.filters?.game??'');
 if(profile?.key!=='MMOEXP'&&!/^[1-9]\d*$/.test(gid))return null;
 return {start:selection.start,end:selection.end,mode:'code',status:'valid',...(gid?{gid}:{} )};
}
function fsProcurementNote(state){
 if(!state?.data)return state?.phase==='denied'?'逐单成本权限未开通；保留原参考估算。':state?.phase==='failed'?'逐单采购毛利读取失败；可用更新视图重试，未填零。':'正在复用原日归档核对逐单收入和实际成本…';
 const m=state.data;
 return '已完成覆盖 '+m.coveredOrders+'/'+m.completedOrders+' 单；'+(m.missingCostOrders?'收入或成本待补 '+m.missingCostOrders+' 单；':'')+'未完成 '+m.pendingOrders+' 单暂不核利润。'+(m.coveredOrders?'覆盖单收入 ¥'+m.saleCny+'；实际成本 ¥'+m.costCny+'。':m.orders?'暂无可核完成单。':'本期无经营订单。')+'Admin订单读取 '+m.capturedAt+'；成本读取 '+(m.costCapturedAt||'见原逐单回执')+(state.phase==='failed'?'；本次补核等待未完成，保留已核值，可更新视图重试':m.refreshing?'；原来源正在补核':m.costError?'；成本补核失败，保留已核值':m.stale?'；保留来源读取时点':'')+'。';
}
function fsClearProcurement(force=false){procurementRead?.abort.abort();procurementRead=null;procurementForce=force;}
function fsEnsureProcurement(profile,all=false){
 const selection=currentSelection(),query=fsProcurementQuery(profile,all,selection);
 if(!query){fsClearProcurement();return null;}
 const id=JSON.stringify([profile.key,query]),now=Date.now();
 if(procurementRead?.id===id&&(procurementRead.loading||now<procurementRead.expiresAt))return procurementRead;
 const previous=procurementRead?.id===id?procurementRead.data:null;
 procurementRead?.abort.abort();
 const abort=new AbortController(),state={id,abort,loading:true,phase:'reading',data:previous,expiresAt:now+600000};procurementRead=state;
 const force=procurementForce;procurementForce=false;
 (async()=>{
  let timer;
  try{
   timer=setTimeout(()=>abort.abort(),100000);
   const params=new URLSearchParams(query);if(force)params.set('refresh','1');
   while(!abort.signal.aborted){
    const response=await fetch('/dashboard/channel-effects/data.json?'+params,{credentials:'same-origin',cache:'no-store',redirect:'error',signal:abort.signal});
    if(procurementRead!==state||abort.signal.aborted)return;
    if(response.status===401||response.status===403){state.data=null;state.phase='denied';return;}
    const data=await response.json();
    if(procurementRead!==state||abort.signal.aborted)return;
    if(response.status!==429)params.delete('refresh');
    if(response.status===202||response.status===429){await fcWait(3000,abort.signal);continue;}
    if(!response.ok)throw Error('逐单采购毛利读取失败');
    state.data=fsProcurementProjection(data,selection);state.phase='available';
    kpiCards();renderProfit();fcDetailShow();
    if(!data.refreshing)return;
    await fcWait(5000,abort.signal);
   }
  }catch(error){if(procurementRead===state){state.phase='failed';state.error=error.message;}}
  finally{
   clearTimeout(timer);state.loading=false;
   if(procurementRead===state&&!scope.signal.aborted){kpiCards();renderProfit();fcDetailShow();}
  }
 })();
 return state;
}
scope.signal.addEventListener('abort',()=>fsClearProcurement(),{once:true});
window.addEventListener('fs-exact-permission-denied',()=>fsClearProcurement(),{signal:scope.signal});

