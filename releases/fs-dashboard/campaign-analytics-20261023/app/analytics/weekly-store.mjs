import fs from 'node:fs';
import path from 'node:path';
import nativeHandoff from '../native-code-handoff.js';
import {atomic} from './store.mjs';
import {canonical,digest,fail} from '../runtime/snapshot.mjs';

export const WEEKLY_PAGES = {'fc27-trio':'Player Trio','fc27-weekly':'Weekly Scout','fc27-sbc':'SBC Core'};
export const WEEKLY_STAGES = ['planned','code_implemented','test_available','production_verified','deployed_readback','natural_weekly_run','pending','evidence_gap'];
const fcPlatforms = {ps:'21587',xbox:'21585',pc:'21589'};
const scopes = ['publish','coupon_write','schedule_enable','rollback'];
const text = (value,max=2000) => {if(typeof value!=='string'||value.length>max||/[\u0000-\u0008\u000b\u000c\u000e-\u001f<>]/.test(value))fail('INVALID_WEEKLY_TEXT');return value;};
const uuid = value => {if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value||''))fail('INVALID_OPERATION_ID');return value;};
const fields = (value,keys) => {if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!keys.includes(k)))fail('INVALID_WEEKLY_REQUEST');};
const stageStatus = () => Object.fromEntries(WEEKLY_STAGES.map(stage=>[stage,['planned','code_implemented'].includes(stage)?'pass':'evidence_gap']));
const check = (key,label,status,detail) => ({key,label,status,detail});

export function weeklyPages(center,{now=Date.now()}={}) {
 return Object.entries(WEEKLY_PAGES).map(([page_id,title])=>{
  const page=center.draft.pages.find(p=>p.page_id===page_id),keys=center.page_bindings?.[page_id]?.product_keys||page?.product_keys||[];
  const all=[...(center.catalog_products||[]),...(center.draft.imported_products||[])],products=keys.map(key=>all.find(p=>p.key===key)).filter(Boolean);
  const identities=products.length===keys.length&&keys.length>0&&products.every(p=>p.product_ref?.site_id==='266'&&p.product_ref?.game_id==='1327'&&/^[1-9]\d*$/.test(p.product_ref?.goods_id||''));
  const platforms=products.length>0&&products.every(p=>Object.hasOwn(fcPlatforms,p.platform?.code||'')&&fcPlatforms[p.platform.code]===p.platform.attribute_id);
  const quantity=products.length>0&&products.every(p=>p.quantity?.unit&&Number(p.quantity.min)>0);
  const prices=products.map(p=>Object.values(center.price_contracts||{}).filter(c=>c.verified===true&&canonical(c.model_ref)===canonical(Object.fromEntries(['site_id','game_id','model_id'].map(k=>[k,p.product_ref[k]])))&&Date.parse(c.catalog_version?.replace(/^admin-/,''))<=now).flatMap(c=>c.combinations||[]).find(c=>c.product_key===p.key&&c.choices?.platform===p.platform.attribute_id&&c.choices?.region&&canonical(c.quantity)===canonical(p.quantity)&&canonical(c.attributes)===canonical(p.attributes))?.price);
  const priceFresh=prices.length>0&&prices.every((p,i)=>p?.source==='admin_current'&&p.currency==='USD'&&p.minor_unit_scale===2&&p.quantity_value===products[i].quantity.min&&Number.isSafeInteger(p.base_minor)&&p.base_minor>0&&Date.parse(p.expires_at)>now);
  let checkout={status:'unconfigured'},mappingError=null;
  try{checkout=nativeHandoff.projectConfiguration(center.native_checkout,center.draft.pages,all);}catch(error){mappingError=error.code||error.message;}
  const bindings=checkout.bindings||[];
  const mapped=checkout?.status==='configured'&&Date.parse(checkout.valid_from)<=now&&Date.parse(checkout.valid_until)>now&&products.length>0&&products.every(p=>!p.preview_only&&bindings.some(b=>b.page_id===page_id&&b.product_key===p.key&&b.native?.id===p.product_ref.goods_id));
  const checks=[check('identity','商品身份',identities?'pass':'pending',identities?'站点266、FC27游戏及商品ID完整；身份不等于可售。':'商品ID或真实商品映射缺失。'),
   check('platform','平台',platforms?'pass':'pending',platforms?'平台及属性ID已记录。':'平台或属性ID尚待核实。'),
   check('quantity','数量与单位',quantity?'pass':'pending',quantity?'数量与单位已记录。':'缺少可核对的数量或单位。'),
   check('region','区服与规格','pending','须逐商品核对原站区服和规格；未将缺失区服当成全球通用。'),
   check('sellable','真实可售映射',mapped?'pass':mappingError?'fail':'pending',mapped?'当前服务器原生结账配置存在对应映射；仍需三页真实入口测试。':mappingError?'原生映射合同校验失败：'+mappingError:'尚无本页有效原生结账映射。'),
   check('price','价格与有效期',priceFresh?'pass':'pending',priceFresh?'当前Admin参考价及有效期可读；结账金额仍以原站确认。':'当前有效价格、币种或有效期证据不足。'),
   check('coupon','优惠券与折扣','pending',(page?.benefit_refs||[]).length?'已记录优惠引用，需校验有效期、适用商品及叠加规则。':'尚无本页已核验优惠券与折扣依据。'),
   check('checkout','主站结账与自动用码','pending','复用现有链路；本页测试/生产回执需单独接入。'),
   check('tracking','追踪与归因','pending','复用活动追踪，缺少本周页面与订单归因复查。')];
  return {page_id,title,activity_revision:center.revision,product_revision:digest(canonical(products)),coupon_revision:digest(canonical(page?.benefit_refs||[])),
   products,checks,stage_status:stageStatus(),published:center.published||null};
 });
}

export function makeWeeklyStore({dir,centerProvider,now=Date.now}) {
 const file=path.join(dir,'weekly-operations.json');
 const rawRead=()=>fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{schema_version:1,revision:0,weeks:[],operations:[],hermes:{enabled:false,model:'gpt-6.1-sol',status:'not_connected',schedule_enabled:false}};
 function view(state,center=centerProvider()) {
  const pages=weeklyPages(center,{now:now()});
  return {revision:state.revision,operations:state.operations.map(({id,hash})=>({operationId:id,request_hash:hash})),hermes:state.hermes,pages,weeks:state.weeks.map(w=>{
   const page=pages.find(p=>p.page_id===w.page_id),stages=stageStatus();
   // Human-submitted references are reports, never machine-verified production evidence.
   for(const e of w.evidence)if(e.activity_revision===w.activity_revision&&e.product_revision===w.product_revision&&e.coupon_revision===w.coupon_revision&&e.plan_operation_id===w.operationId&&e.verification!=='reported')stages[e.stage]=e.verification==='verified'?'pass':e.verification;
   return {...w,checks:page.checks,checks_scope:'current_center',stage_status:stages,change_summary:{center_revision_changed:w.activity_revision!==page.activity_revision,products_changed:w.product_revision!==page.product_revision,coupon_changed:w.coupon_revision!==page.coupon_revision},
    approval:w.approval?{...w.approval,stale:w.approval.center_revision!==center.revision||w.approval.product_revision!==page.product_revision||w.approval.coupon_revision!==page.coupon_revision}:null};
  })};
 }
 function mutate(body,user) {
  const base=['revision','operation_id','action'],weekKeys=['id','page_id'];
  const allowed={create:weekKeys,update:[...weekKeys,'notes','activity_revision','product_revision','coupon_revision'],review:[...weekKeys,'note'],approval:[...weekKeys,'decision','scope','note'],pause:weekKeys,retry:weekKeys,evidence:[...weekKeys,'stage','reference','note'],hermes:['enabled']};
  if(!allowed[body?.action])fail('INVALID_WEEKLY_ACTION');fields(body,[...base,...allowed[body.action]]);uuid(body.operation_id);
  if(!Number.isSafeInteger(body.revision)||body.revision<0)fail('INVALID_WEEKLY_REVISION');text(user,160);
  const state=rawRead(),hash=digest(canonical(body)),prior=state.operations.find(o=>o.id===body.operation_id);
  if(prior){if(prior.hash!==hash)fail('REQUEST_CONFLICT',409);return view(state);}
  if(body.revision!==state.revision)fail('REVISION_CONFLICT',409);
  const center=centerProvider(),pages=weeklyPages(center,{now:now()}),at=new Date(now()).toISOString();
  if(body.action==='hermes'){
   if(typeof body.enabled!=='boolean')fail('INVALID_HERMES_SETTING');state.hermes={...state.hermes,enabled:body.enabled,status:body.enabled?'not_connected':'disabled'};
  }else{
   if(!/^\d{4}-W(?:0[1-9]|[1-4]\d|5[0-3])$/.test(body.id||'')||!Object.hasOwn(WEEKLY_PAGES,body.page_id))fail('INVALID_WEEKLY_SCOPE');
   const page=pages.find(p=>p.page_id===body.page_id);let week=state.weeks.find(w=>w.id===body.id&&w.page_id===body.page_id);
   if(body.action==='create'){
    if(week)fail('WEEK_ALREADY_EXISTS',409);
    week={id:body.id,page_id:body.page_id,status:'planned',activity_revision:page.activity_revision,product_revision:page.product_revision,coupon_revision:page.coupon_revision,operationId:body.operation_id,notes:'',evidence:[],reviews:[],approval:null,approval_history:[],check_snapshot:{center_revision:center.revision,checked_at:at,checks:structuredClone(page.checks)},created_at:at,updated_at:at};state.weeks.push(week);
   }else{
    if(!week)fail('WEEK_NOT_FOUND',404);
    if(body.action==='update'){
     if(week.execution?.status==='unknown'&&['activity_revision','product_revision','coupon_revision'].some(k=>body[k]!==undefined))fail('ORIGINAL_OPERATION_RECONCILIATION_REQUIRED',409);
     if(body.notes!==undefined)week.notes=text(body.notes);
     for(const key of ['activity_revision','product_revision','coupon_revision'])if(body[key]!==undefined){if(body[key]!==page[key])fail('CURRENT_REVISION_REQUIRED',409);week[key]=body[key];}
     if(week.approval)week.approval_history.push({...week.approval,invalidated_at:at,reason:'plan_updated'});week.approval=null;week.status='planned';
    }else if(body.action==='review')week.reviews.push({note:text(body.note),recorded_at:at,recorded_by:user});
    else if(body.action==='evidence'){
     if(!WEEKLY_STAGES.includes(body.stage))fail('INVALID_EVIDENCE_STAGE');
     week.evidence.push({stage:body.stage,reference:text(body.reference,500),note:text(body.note),verification:'reported',activity_revision:week.activity_revision,recorded_at:at,recorded_by:user,product_revision:week.product_revision,coupon_revision:week.coupon_revision,plan_operation_id:week.operationId});
    }else if(body.action==='approval'){
     if(!scopes.includes(body.scope)||!['requested','approved','rejected'].includes(body.decision))fail('INVALID_APPROVAL');
     const note=text(body.note);
     if(body.decision==='requested')week.approval={status:'requested',scope:body.scope,note,center_revision:center.revision,product_revision:page.product_revision,coupon_revision:page.coupon_revision,requested_by:user,reviewed_by:null,updated_at:at};
     else{
      if(week.approval?.status!=='requested'||week.approval.scope!==body.scope)fail('APPROVAL_REQUEST_REQUIRED',409);
      if(body.decision==='approved'&&(week.approval.center_revision!==center.revision||week.activity_revision!==center.revision||week.approval.product_revision!==page.product_revision||week.approval.coupon_revision!==page.coupon_revision||week.product_revision!==page.product_revision||week.coupon_revision!==page.coupon_revision))fail('APPROVAL_STALE',409);
      week.approval={...week.approval,status:body.decision,note,reviewed_by:user,updated_at:at};
     }
     week.approval_history.push(structuredClone(week.approval));week.status=body.decision==='requested'?'review_pending':body.decision;
    }else if(body.action==='pause')week.status='paused';
    else if(body.action==='retry'){
     if(week.execution?.status==='unknown')fail('ORIGINAL_OPERATION_RECONCILIATION_REQUIRED',409);
     if(!['paused','rejected'].includes(week.status))fail('WEEK_NOT_RETRYABLE',409);
     week.status='planned';week.approval=null;
    }
    week.updated_at=at;
   }
  }
  state.revision++;state.updated_at=at;state.updated_by=user;state.operations.push({id:body.operation_id,hash});
  atomic(file,state);return view(state,center);
 }
 // Server-only adapter: never expose this method through the browser mutation route.
 function recordEvidence(record) {
  fields(record,['revision','operation_id','id','page_id','stage','reference','activity_revision','source','release_id','config_hash','trigger','result','product_revision','coupon_revision','plan_operation_id','execution_operation_id']);
  uuid(record.operation_id);
  if(!['test_available','production_verified','deployed_readback','natural_weekly_run'].includes(record.stage)||!['passed','failed','unknown'].includes(record.result))fail('INVALID_RUNTIME_EVIDENCE');
  text(record.reference,500);text(record.source,160);if(!record.reference.trim()||!record.source.trim())fail('EVIDENCE_REFERENCE_REQUIRED');
  const state=rawRead(),hash=digest(canonical(record)),prior=state.operations.find(o=>o.id===record.operation_id);
  if(prior){if(prior.hash!==hash)fail('REQUEST_CONFLICT',409);return view(state);}
  if(record.revision!==state.revision)fail('REVISION_CONFLICT',409);
  const week=state.weeks.find(w=>w.id===record.id&&w.page_id===record.page_id);if(!week)fail('WEEK_NOT_FOUND',404);
  if(record.activity_revision!==week.activity_revision||record.product_revision!==week.product_revision||record.coupon_revision!==week.coupon_revision||record.plan_operation_id!==week.operationId)fail('EVIDENCE_REVISION_MISMATCH',409);
  const center=centerProvider();
  if(record.stage==='deployed_readback'&&(center.revision!==week.activity_revision||record.release_id!==center.published?.release_id||record.config_hash!==center.published?.config_hash||!record.config_hash))fail('PUBLISH_RECEIPT_MISMATCH',409);
  if(record.stage==='natural_weekly_run'&&record.trigger!=='scheduled')fail('NATURAL_RUN_PROOF_REQUIRED');
  const executionId=uuid(record.execution_operation_id||record.operation_id);
  if(week.execution?.status==='unknown'&&(week.execution.operation_id!==executionId||week.execution.stage!==record.stage))fail('ORIGINAL_OPERATION_RECONCILIATION_REQUIRED',409);
  const at=new Date(now()).toISOString();
  week.evidence.push({stage:record.stage,reference:record.reference,source:record.source,verification:record.result==='passed'?'verified':record.result,activity_revision:record.activity_revision,product_revision:record.product_revision,coupon_revision:record.coupon_revision,plan_operation_id:record.plan_operation_id,operationId:record.operation_id,release_id:record.release_id||null,recorded_at:at,recorded_by:record.source});
  week.execution={status:record.result==='passed'?'completed':record.result,operation_id:executionId,stage:record.stage};week.updated_at=at;
  state.revision++;state.updated_at=at;state.updated_by=record.source;state.operations.push({id:record.operation_id,hash});atomic(file,state);return view(state,center);
 }
 return {read:()=>view(rawRead()),mutate,recordEvidence};
}
