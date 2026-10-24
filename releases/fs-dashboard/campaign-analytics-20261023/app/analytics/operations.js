(function(){
 'use strict';
 const $=id=>document.getElementById(id),key='fs-campaign-native-operation:'+location.pathname;
 let csrf=null,canEdit=false,busy=false,detail=null,pending=null,storageOK=true,mappings={};
 try{pending=JSON.parse(sessionStorage.getItem(key)||'null');if(pending&&(!/^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$/.test(pending.operation_id)||typeof pending.native_id!=='string'))throw Error();}
 catch{storageOK=false;$('ops-error').textContent='原操作记录无法读取。请由维护人员核对服务器账本后恢复此会话，当前禁止新写入。';}
 const tell=(id,value)=>{$(id).textContent=value;};
 function locks(){
  $('query-fields').disabled=busy||!canEdit;
  $('analysis-fields').disabled=busy||!canEdit;
  $('read-mappings').disabled=busy||!canEdit;$('mapping-reference').disabled=busy||!canEdit||!Object.keys(mappings).length;
  $('edit-fields').disabled=busy||!canEdit||!detail||Boolean(pending)||!storageOK;
  const allowed=detail?.editability?.allowed_changes||[];
  $('benefit-title').disabled=!allowed.includes('title');$('benefit-brief').disabled=!allowed.includes('brief');
  $('save-benefit').disabled=!allowed.some(x=>['title','brief'].includes(x));
  $('disable-benefit').disabled=detail?.editability?.can_disable!==true;
  $('reconcile-operation').disabled=busy||!canEdit||!pending||!storageOK;
  tell('pending-state',pending?'原操作 '+pending.operation_id+' 尚待核对；新修改已锁定。':'没有待核对操作。');
 }
 function persist(value){sessionStorage.setItem(key,JSON.stringify(value));pending=value;}
 async function api(action,body={},mutate=false){
  const response=await fetch('api/center/backend-'+(mutate?'mutate':'read'),{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({...body,action,site_id:'266'})});
  let payload;try{payload=await response.json();}catch{throw Error('响应无法确认，请查询原操作。');}
  if(!response.ok||payload.status!=='ok')throw Error(payload.message||'后台操作未确认');return payload.data;
 }
 async function run(fn){if(busy||!canEdit)return;busy=true;locks();tell('ops-error','');try{await fn();}catch(error){tell('ops-error',error.message);}finally{busy=false;locks();}}
 async function readDetail(id){
  detail=null;locks();const value=await api('benefit_detail',{kind:'coupon',native_id:id});
  if(value?.native_id!==id||value.kind!=='coupon'||typeof value.before_hash!=='string')throw Error('详情身份不匹配，修改保持关闭。');
  detail=value;$('benefit-title').value=value.fields?.title||'';$('benefit-brief').value=value.fields?.brief||'';
  tell('benefit-state','券 '+id+' · 原始状态 '+String(value.fields?.status??'未知')+' · '+((value.editability?.blocked_reasons||[]).join('；')||'仅可修改服务器核准字段'));
 }
 function operationResult(result){
  if(result?.object_busy===true){
   if(!pending||result.requested_operation_id!==pending.operation_id||result.recovery_operation_id!==result.operation_id||!/^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$/.test(result.operation_id)||!['pending','unknown','confirmed','rejected','blocked'].includes(result.state))throw Error('对象占用回执无法核对，保留当前操作并联系维护人员。');
   persist({...pending,operation_id:result.recovery_operation_id});
  }
  if(!pending||result?.operation_id!==pending.operation_id)throw Error('回执操作ID不匹配，原操作保留。');
  const labels={pending:'该对象已有操作待核对，请恢复原操作',confirmed:'已回读确认',rejected:'已拒绝',blocked:'安全条件未满足，未执行',unknown:'结果未知，请继续查询原操作'};
  tell('ops-status',(result.object_busy===true?'本次修改未提交，以下为原操作结果：':'')+(labels[result.state]||'原操作尚未确认')+(result.result?.reason_code?' · '+result.result.reason_code:''));
  if(['confirmed','rejected','blocked'].includes(result.state))persist(null);
 }
 async function mutate(action,changes){
  if(!detail||pending||!storageOK||!canEdit)return;
  const body={kind:'coupon',native_id:detail.native_id,operation_id:crypto.randomUUID(),before_hash:detail.before_hash,...changes};
  persist({operation_id:body.operation_id,native_id:body.native_id});locks();
  operationResult(await api(action,body,true));if(!pending)await readDetail(body.native_id);
 }
 const money=(value,scale)=>Number.isSafeInteger(value)&&Number.isInteger(scale)&&scale>=0&&scale<=6?(value/(10**scale)).toFixed(scale):'未知 / 待分摊';
 function summary(value){
  tell('analysis-status',({ready:'已按核准口径对账',partial:'部分证据待补',blocked:'尚未具备真实对账条件'})[value?.status]||'待核验');
  const coverage=value?.coverage||{};
  const windows=[...new Set((value?.scanned_windows||[]).map(row=>String(row.window_from)+' 至 '+String(row.window_to)))];
  tell('analysis-scope','全部已保存扫描窗口汇总（订单去重），不是上方日期的筛选结果。最近成功核对：'+String(value?.verified_at||'尚未核对')+'。');
  $('analysis-windows').replaceChildren();for(const range of windows){const li=document.createElement('li');li.textContent=range;$('analysis-windows').append(li);}
  if(!windows.length){const li=document.createElement('li');li.textContent='尚无已保存扫描窗口。';$('analysis-windows').append(li);}
  const labels={source_orders:'来源订单',paid_observations:'有效付款观察',refunded_observations:'退款观察',coupon_log_rows:'用券记录',associated_paid_observations:'已付用券关联',bound_paid_orders:'已绑定活动付款',unbound_paid_orders:'未绑定活动付款',unresolved_orders:'待核订单',successful_runs:'成功对账次数'};
  tell('analysis-coverage',Object.entries(coverage).filter(([name,n])=>labels[name]&&Number.isSafeInteger(n)).map(([name,n])=>labels[name]+'：'+n).join(' · '));
  const warningLabels={ORDER_READ_NOT_PERFORMED:'尚未读取真实订单',ACTIVITY_BINDINGS_REQUIRED:'尚未核准本活动专属优惠绑定',PAID_MONEY_MAPPING_REQUIRED:'实收金额口径尚未核准',PAID_CURRENCY_CONFLICT:'实付币种字段存在冲突',SOURCE_TIME_MAPPING_REQUIRED:'来源时间与时区尚未核准',PAYMENT_STATE_UNKNOWN:'部分订单付款状态尚未核验',COUPON_LOG_STATUS_UNKNOWN:'部分用券状态尚未核验',DISCOUNT_APPLICATION_TIME_REQUIRED:'折扣码实际应用时间尚未核验',AMBIGUOUS_DISCOUNT_NATIVE_ID:'折扣码对应多个原生ID，不能确定归属',LINE_ALLOCATION_NOT_VERIFIED:'活动商品行分摊尚未核验',REFUND_EVENTS_NOT_VERIFIED:'退款事实与金额尚未核验'};
  $('analysis-warnings').replaceChildren();for(const warning of value?.warnings||[]){const li=document.createElement('li');li.textContent=warningLabels[warning]||String(warning);$('analysis-warnings').append(li);}
  if(value?.historical_refund_coverage){const li=document.createElement('li');li.textContent='历史退款与晚到付款需要明确区间重查；当前结果不代表全部历史已自动覆盖。';$('analysis-warnings').append(li);}
  $('analysis-totals').replaceChildren();for(const row of value?.totals||[]){
   const tr=document.createElement('tr');for(const cell of [row.currency,Number.isSafeInteger(row.paid_orders)?row.paid_orders:'未知',money(row.associated_paid_minor,row.scale),money(row.activity_paid_minor,row.scale),money(row.refund_minor,row.scale),money(row.net_minor,row.scale)]){const td=document.createElement('td');td.textContent=String(cell??'未知');tr.append(td);}$('analysis-totals').append(tr);
  }
  if(!(value?.totals||[]).length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent='尚无已核准的订单汇总；不表示成交或收入为零。';tr.append(td);$('analysis-totals').append(tr);}
  $('analysis-activities').replaceChildren();for(const row of value?.activities||[]){const tr=document.createElement('tr');for(const cell of [row.activity_id||row.group_id||'归因范围待核',row.currency||'待核',Number.isSafeInteger(row.paid_orders)?row.paid_orders:'未知',money(row.associated_paid_minor,row.scale),money(row.activity_paid_minor,row.scale)]){const td=document.createElement('td');td.textContent=String(cell);tr.append(td);}$('analysis-activities').append(tr);}
 }
 $('benefit-query').addEventListener('submit',event=>{event.preventDefault();run(()=>readDetail($('benefit-id').value));});
 $('read-mappings').addEventListener('click',()=>run(async()=>{
  const value=await api('catalog_mapping_read');if(!value?.mappings||typeof value.mappings!=='object'||Array.isArray(value.mappings))throw Error('商品映射版本无法确认。');
  mappings=value.mappings;const select=$('mapping-reference');select.replaceChildren(new Option('请选择页面引用',''));
  for(const [key,row] of Object.entries(mappings))select.append(new Option((row.family||'')+' · '+key,key));
  const s=value.summary||{};tell('mapping-status','已读取 '+String(s.reference_count??Object.keys(mappings).length)+' 个引用，'+String(s.unique_goods_count??'待核')+' 个商品；购买仍关闭。');$('mapping-detail').hidden=true;
 }));
 $('mapping-reference').addEventListener('change',()=>{
  const row=mappings[$('mapping-reference').value];$('mapping-detail').hidden=!row;if(!row)return;
  const q=row.quantity||{},ref=row.product_ref||{};const fields=[['商品/模型',String(ref.goods_id||'待核')+' / '+String(ref.model_id||'待核')],['平台',String(row.platform?.code||'待核')+' · '+String(row.platform?.attribute_id||'待核')],['原页面数量',q.reference_value],['后台最小数量',q.observed_minimum],['后台单位',q.observed_unit||'空值，含义待核'],['数量组',q.reference_group||'未提供'],['规格结构',({empty_selectable_properties:'已观察为空',admin_gold_quantity_tiers_v1:'已观察到后台数量档位，购买序列化仍待核验'})[row.selection_schema]||'待核验'],['购买状态','未开放']];
  $('mapping-fields').replaceChildren();for(const [name,value] of fields){const div=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=String(value??'待核');div.append(dt,dd);$('mapping-fields').append(div);}
  const reasons={PUBLIC_PURCHASE_SERIALIZATION_UNVERIFIED:'主站购买参数尚未核验',QUANTITY_STEP_AND_UPPER_BOUND_UNVERIFIED:'数量步长及上限尚未核验',SALE_STATE_SEMANTICS_UNVERIFIED:'商品状态语义尚未核验',QUANTITY_TIER_PRECEDENCE_UNVERIFIED:'商品与模型的数量档位优先级尚未核验'};
  $('mapping-reasons').replaceChildren();for(const reason of row.missing_reasons||[]){const li=document.createElement('li');li.textContent=reasons[reason]||'该引用还有待核条件（'+reason+'）';$('mapping-reasons').append(li);}
 });
 $('benefit-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{const changes={};for(const field of detail?.editability?.allowed_changes||[])if(['title','brief'].includes(field)&&$('benefit-'+field).value!==String(detail.fields?.[field]??''))changes[field]=$('benefit-'+field).value;if(!Object.keys(changes).length){tell('ops-status','字段没有变化。');return;}await mutate('benefit_edit',{changes});});});
 $('disable-benefit').addEventListener('click',()=>run(()=>detail?.editability?.can_disable===true?mutate('benefit_toggle',{enabled:false}):Promise.resolve()));
 $('reconcile-operation').addEventListener('click',()=>run(async()=>{if(!pending)return;const id=pending.native_id;operationResult(await api('operation_reconcile',{operation_id:pending.operation_id},true));if(!pending)await readDetail(id);}));
 $('read-summary').addEventListener('click',()=>run(async()=>summary(await api('analysis_summary'))));
 $('analysis-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{const from=$('analysis-from').value,to=$('analysis-to').value;if(to<from)throw Error('结束时间必须晚于开始时间。');const raw=value=>value.replace('T',' ')+(value.length===16?':00':'');await api('analysis_reconcile',{from:raw(from),to:raw(to)},true);summary(await api('analysis_summary'));});});
 async function init(){try{const response=await fetch('api/center',{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('请使用FS原有管理员会话。');const value=await response.json();csrf=value.csrf;canEdit=value.canEdit===true&&typeof csrf==='string';tell('ops-status',canEdit?'管理会话已读取；具体写入权限仍以服务端对象核验为准。':'当前会话无后台操作权限。');}catch(error){tell('ops-error',error.message);}locks();}
 init();
})();
