(function(){
 'use strict';
 const $=id=>document.getElementById(id),key='fs-campaign-native-operation:'+location.pathname;
 let csrf=null,canEdit=false,busy=false,detail=null,pending=null,storageOK=true;
 try{pending=JSON.parse(sessionStorage.getItem(key)||'null');if(pending&&(!/^[0-9a-f-]{36}$/i.test(pending.operation_id)||typeof pending.native_id!=='string'))throw Error();}
 catch{storageOK=false;$('ops-error').textContent='原操作记录无法读取。请由维护人员核对服务器账本后恢复此会话，当前禁止新写入。';}
 const tell=(id,value)=>{$(id).textContent=value;};
 function locks(){
  $('query-fields').disabled=busy||!canEdit;
  $('analysis-fields').disabled=busy||!canEdit;
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
  if(!pending||result?.operation_id!==pending.operation_id)throw Error('回执操作ID不匹配，原操作保留。');
  const labels={confirmed:'已回读确认',rejected:'已拒绝',blocked:'安全条件未满足，未执行',unknown:'结果未知，请继续查询原操作'};
  tell('ops-status',(labels[result.state]||'原操作尚未确认')+(result.result?.reason_code?' · '+result.result.reason_code:''));
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
  const labels={source_orders:'来源订单',paid_observations:'有效付款观察',refunded_observations:'退款观察',coupon_log_rows:'用券记录',associated_paid_observations:'已付用券关联',bound_paid_orders:'已绑定活动付款',unbound_paid_orders:'未绑定活动付款',unresolved_orders:'待核订单',successful_runs:'成功对账次数'};
  tell('analysis-coverage',Object.entries(coverage).filter(([name,n])=>labels[name]&&Number.isSafeInteger(n)).map(([name,n])=>labels[name]+'：'+n).join(' · '));
  $('analysis-warnings').replaceChildren();for(const warning of value?.warnings||[]){const li=document.createElement('li');li.textContent=String(warning);$('analysis-warnings').append(li);}
  $('analysis-totals').replaceChildren();for(const row of value?.totals||[]){
   const tr=document.createElement('tr');for(const cell of [row.currency,Number.isSafeInteger(row.paid_orders)?row.paid_orders:'未知',money(row.associated_paid_minor,row.scale),money(row.activity_paid_minor,row.scale),money(row.refund_minor,row.scale),money(row.net_minor,row.scale)]){const td=document.createElement('td');td.textContent=String(cell??'未知');tr.append(td);}$('analysis-totals').append(tr);
  }
  if(!(value?.totals||[]).length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent='尚无已核准的订单汇总；不表示成交或收入为零。';tr.append(td);$('analysis-totals').append(tr);}
  $('analysis-activities').replaceChildren();for(const row of value?.activities||[]){const tr=document.createElement('tr');for(const cell of [row.activity_id||row.group_id||'归因范围待核',row.currency||'待核',Number.isSafeInteger(row.paid_orders)?row.paid_orders:'未知',money(row.associated_paid_minor,row.scale),money(row.activity_paid_minor,row.scale)]){const td=document.createElement('td');td.textContent=String(cell);tr.append(td);}$('analysis-activities').append(tr);}
 }
 $('benefit-query').addEventListener('submit',event=>{event.preventDefault();run(()=>readDetail($('benefit-id').value));});
 $('benefit-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{const changes={};for(const field of detail?.editability?.allowed_changes||[])if(['title','brief'].includes(field)&&$('benefit-'+field).value!==String(detail.fields?.[field]??''))changes[field]=$('benefit-'+field).value;if(!Object.keys(changes).length){tell('ops-status','字段没有变化。');return;}await mutate('benefit_edit',{changes});});});
 $('disable-benefit').addEventListener('click',()=>run(()=>detail?.editability?.can_disable===true?mutate('benefit_toggle',{enabled:false}):Promise.resolve()));
 $('reconcile-operation').addEventListener('click',()=>run(async()=>{if(!pending)return;const id=pending.native_id;operationResult(await api('operation_reconcile',{operation_id:pending.operation_id},true));if(!pending)await readDetail(id);}));
 $('read-summary').addEventListener('click',()=>run(async()=>summary(await api('analysis_summary'))));
 $('analysis-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{const from=$('analysis-from').value,to=$('analysis-to').value;if(to<from)throw Error('结束时间必须晚于开始时间。');await api('analysis_reconcile',{from:from.replace('T',' '),to:to.replace('T',' ')},true);summary(await api('analysis_summary'));});});
 async function init(){try{const response=await fetch('api/center',{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('请使用FS原有管理员会话。');const value=await response.json();csrf=value.csrf;canEdit=value.canEdit===true&&typeof csrf==='string';tell('ops-status',canEdit?'管理会话已读取；具体写入权限仍以服务端对象核验为准。':'当前会话无后台操作权限。');}catch(error){tell('ops-error',error.message);}locks();}
 init();
})();
