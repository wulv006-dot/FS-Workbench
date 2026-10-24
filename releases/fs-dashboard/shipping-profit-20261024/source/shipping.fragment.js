const shippingCategories=[['-1','全部类目'],['0','混合'],['1','货币'],['2','物品'],['3','账号'],['4','代练'],['5','CD keys'],['6','Coaching'],['7','Top Up'],['8','Skins'],['9','Gift cards']];
let shippingCategory=shippingCategories.some(([v])=>v===scope.seed?.b_profit_category)?scope.seed.b_profit_category:'-1';
if(scope.seed?.b_profit_site==='all')scope.referenceScope='all';
function shippingFields(key,s){return key==='RS'?{}:{profit_site:s.profit_site||'main',profit_category:s.profit_category||'-1'};}
function shippingSame(key,a,b){return key==='RS'?rsSame(a,b):a?.profit_site===b?.profit_site&&a?.profit_category===b?.profit_category;}
function shippingSelection(key,s){return key==='RS'?s:{...s,profit_site:['all','combined'].includes(scope.referenceScope)?'all':'main',profit_category:shippingCategory};}
function shippingRenderFilters(){
 let box=document.getElementById('shipping-filters');if(!box){box=document.createElement('div');box.id='shipping-filters';box.className='toolbar';document.getElementById('rangeBar').after(box);}box.hidden=KEY==='RS';if(box.hidden)return;box.replaceChildren();
 const label=document.createElement('label');label.htmlFor='shipping-category';label.textContent='发货利润类目 ';const select=document.createElement('select');select.id='shipping-category';
 for(const [value,title] of shippingCategories){const o=document.createElement('option');o.value=value;o.textContent=title;select.append(o);}select.value=shippingCategory;label.append(select);box.append(label);
 const note=document.createElement('span');note.className='hint';note.textContent='仅筛选发货利润及每日曲线；订单、美元销售和逐单成本毛利保持各自原范围。';box.append(note);
 select.onchange=()=>{shippingCategory=select.value;window.FSExactRange.force();workspaceClearRanges();renderAll();workspaceSync();document.getElementById('shipping-category')?.focus();};
}
function shippingMetrics(profile,all=false){
 const s=profile?.shipping,period=profile?.supplement?.period,query=currentSelection(),site=all?'all':'main';
 const valid=s?.status==='available'&&s.currency==='CNY'&&s.sourceContract==='order-shipping-v1'&&s.profileKey===profile?.key&&s.period?.start===period?.start&&s.period?.end===period?.end&&s.shippingSelection?.site===site&&s.shippingSelection?.cid===query.profit_category;
 const out={},scopeLabel=s?.scopeLabel||((all?'全部网站':'MMOEXP主站')+' · 发货统计所选类目');
 for(const key of ['profitCny','profitMarginPct','shippingSalesCny','shippingCostCny']){const m=valid?s.metrics?.[key]:null;out[key]=m?.status==='available'&&Number.isFinite(m.value)||m?.status==='not_applicable'?{...m,source:'Order发货统计',scope:scopeLabel+' · 交易时间；非净利润',stale:!!s.stale,pendingPhase:s.readPhase}:{value:null,status:'not_provided',source:'Order发货统计',scope:scopeLabel+' · 等待同范围发货统计',pendingPhase:s?.readPhase||'reading'};}return out;
}
function shippingDailyDays(history,start,end){
 const q=currentSelection(),rows=new Map((history.daily||[]).filter(r=>r.profileKey===KEY&&r.sourceContract==='order-shipping-v1'&&r.currency==='CNY'&&r.scope?.sites===(q.profit_site==='all'?'all-websites':'www.mmoexp.com')&&r.scope.orderProductType===q.profit_category&&r.scope.orderStatus==='-1'&&r.scope.orderAreaId==='0').map(r=>[r.date,r]));
 const out=[],a=Date.parse(start+'T00:00:00Z'),b=Date.parse(end+'T00:00:00Z');if(!Number.isFinite(a)||!Number.isFinite(b)||b<a||b-a>366*86400000)return [];
 for(let ts=a;ts<=b;ts+=86400000){const day=new Date(ts).toISOString().slice(0,10),r=rows.get(day);out.push({day,rate:r?.profitMarginPct??null,notApplicable:!!r&&r.salesCny===0,orders:r?.orders??null,sales:r?.salesCny??null,profit:r?.profitCny??null,capturedAt:r?.capturedAt,stale:!!r?.stale,latestAttemptAt:r?.latestAttemptAt});}return out;
}
