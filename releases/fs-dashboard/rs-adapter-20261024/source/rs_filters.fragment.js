const rsOptions={rs_site:[['all','全部网站'],['rsorders','RSOrders'],['rsmalls','RSMalls'],['rsfast','RSFast'],['mmoexp','MMOEXP']],rs_server:[['all','全部区服'],['rs3','Runescape 3'],['oldschool','Old School']],rs_category:[['all','全部类目'],['currency','货币'],['package','代练包'],['items','物品']]};
let rsFilters=rsChecked(scope.seed||{}),rsMoreOpen=false;
function rsChecked(values){return Object.fromEntries(Object.entries(rsOptions).map(([key,options])=>{const value=values['b_'+key]??values[key];return [key,options.some(([v])=>v===value)?value:'all'];}));}
function rsScope(values=rsFilters){return Object.entries(rsOptions).map(([key,options])=>options.find(([v])=>v===values[key])?.[1]||'全部').join(' · ');}
function rsSelection(key,s){return key==='RS'?{...s,...rsFilters}:s;}
function rsSame(a,b){return Object.keys(rsOptions).every(key=>(a?.[key]||'all')===(b?.[key]||'all'));}
function rsRenderFilters(){
 let box=document.getElementById('rs-filters');if(!box){box=document.createElement('div');box.id='rs-filters';box.className='toolbar';box.style.flexBasis='100%';box.setAttribute('role','group');box.setAttribute('aria-label','RS 分析范围');document.getElementById('rangeBar').after(box);}
 box.hidden=KEY!=='RS';if(box.hidden)return;
 box.replaceChildren();
 const more=document.createElement('details'),summary=document.createElement('summary');summary.textContent='更多筛选'+(rsFilters.rs_server!=='all'?' · '+rsOptions.rs_server.find(([v])=>v===rsFilters.rs_server)[1]:'');more.append(summary);more.open=rsMoreOpen;more.ontoggle=()=>{rsMoreOpen=more.open;};
 for(const [key,title] of [['rs_site','1 · 网站来源'],['rs_category','2 · 商品类目'],['rs_server','游戏区服']]){
  const options=rsOptions[key],label=document.createElement('label');label.className='scope-select';label.textContent=title+' ';
  const select=document.createElement('select');select.name=key;select.id=key;
  for(const [value,title] of options){const option=document.createElement('option');option.value=value;option.textContent=title;select.append(option);}select.value=rsFilters[key];label.append(select);(key==='rs_server'?more:box).append(label);
  select.onchange=()=>{rsFilters={...rsFilters,[key]:select.value};window.FSExactRange.force();workspaceClearRanges();renderAll();workspaceSync();document.getElementById(key)?.focus();};
 }box.append(more);
 const note=document.createElement('span');note.className='hint';note.textContent='卡片、销售趋势、国家、支付方式和设备使用同一筛选；参考指标逐项标注范围。';box.append(note);
}
function rsProjection(profile){
 const admin=profile?.supplement,order=profile?.primary,selection=admin?.rsSelection||rsFilters,scopeLabel=admin?.scopeLabel||rsScope(selection),metrics={};
 const same=admin?.period?.start===order?.period?.start&&admin?.period?.end===order?.period?.end;
 for(const key of ['orders','revenueUsd','newCustomers','payingCustomers','newCustomerRevenueUsd','repeatRatePct','newCustomerSharePct','pureSalesUsd','refundAmountUsd','refundOrders','fulfillmentRatePct','paymentSuccessRatePct','averageOrderUsd','averageCustomerUsd','minOrderAmountUsd','maxOrderAmountUsd']){
  const a=admin?.status==='available'?admin.metrics?.[key]:null,o=same&&order?.status==='available'?order.metrics?.[key]:null;
  const valid=v=>v?.status==='available'&&typeof v.value==='number'&&Number.isFinite(v.value);
  metrics[key]=valid(a)?{...a,source:a.source==='Admin订单明细'?a.source:'Admin',scope:a.scope||scopeLabel}:valid(o)?{...o,source:'Order',scope:order.scopeLabel||'Order 全部网站参考'}:{value:null,status:'not_provided',source:'Admin / Order',scope:scopeLabel,pendingPhase:order?.readPhase||'not_provided'};
 }
 const shipping=same&&order?.status==='available'&&order.sourceContract==='order-shipping-rs-v1'&&rsSame(order.rsSelection,selection);
 for(const key of ['profitMarginPct','profitCny','shippingSalesCny','shippingCostCny']){const value=shipping?order.metrics?.[key]:null;metrics[key]=value?.status==='available'&&Number.isFinite(value.value)||value?.status==='not_applicable'?{...value,source:'Order发货统计',scope:scopeLabel+' · 交易时间；人民币采购毛利，非净利润'}:{value:null,status:'not_provided',source:'Order发货统计',scope:scopeLabel+' · 等待同范围发货统计'};}
 metrics.estimatedProfitUsd={value:null,status:'not_provided',source:'Order发货统计',scope:'利润使用人民币原值'};
 for(const m of Object.values(metrics))if(['Order','Order发货统计'].includes(m.source)&&order?.stale){m.stale=true;m.pendingPhase=order.readPhase;}
 return {metrics,period:admin?.period||profile?.period,adminCapturedAt:admin?.capturedAt,orderCapturedAt:order?.capturedAt,onlyMain:true,site:scopeLabel,policy:'rs-three-dimensions-v1'};
}
function rsShippingDays(history,start,end){
 const rows=new Map((history.daily||[]).filter(r=>r.profileKey==='RS'&&r.sourceContract==='order-shipping-rs-v1'&&r.currency==='CNY'&&r.scope?.sites===(rsFilters.rs_site==='all'?'all-websites':'www.'+rsFilters.rs_site+'.com')&&r.scope.orderProductType===({all:'-1',currency:'1',package:'4',items:'2'})[rsFilters.rs_category]&&r.scope.orderGameId==='506'&&r.scope.orderStatus==='-1'&&r.scope.orderAreaId===({all:'0',rs3:'12370',oldschool:'12368'})[rsFilters.rs_server]).map(r=>[r.date,r]));
 const out=[],a=Date.parse(start+'T00:00:00Z'),b=Date.parse(end+'T00:00:00Z');if(!Number.isFinite(a)||!Number.isFinite(b)||b<a||b-a>366*86400000)return [];
 for(let ts=a;ts<=b;ts+=86400000){const day=new Date(ts).toISOString().slice(0,10),r=rows.get(day);out.push({day,rate:r?.profitMarginPct??null,orders:r?.orders??null,sales:r?.salesCny??null,profit:r?.profitCny??null,capturedAt:r?.capturedAt,stale:!!r?.stale,latestAttemptAt:r?.latestAttemptAt});}return out;
}
