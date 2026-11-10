import fs from 'node:fs';
import path from 'node:path';
import {atomic} from './store.mjs';
import {canonical,digest,fail} from '../runtime/snapshot.mjs';

const pages=['fc27-weekly','fc27-sbc','fc27-trio'];
const uuid=v=>{if(typeof v!=='string'||! /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v))fail('INVALID_OPERATION_ID');return v;};
const fields=(v,keys)=>{if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).some(k=>!keys.includes(k)))fail('INVALID_WEEKLY_WORKFLOW_REQUEST');};
const fcOnly=d=>Object.fromEntries(Object.entries(d).filter(([key])=>!['pages','fc_layout','fc_models','imported_products'].includes(key)).concat([['pages',d.pages.filter(p=>!pages.includes(p.page_id))],['imported_products',(d.imported_products||[]).filter(p=>p.product_ref?.game_id!=='1327')]]));

// Coordinates the original center transaction and weekly ledger; never a second publisher.
export function makeWeeklyWorkflow({dir,center,weekly,pipeline,prepareCommerce,validateCommerce,installCommerce,makePreviews,readPublic,now=Date.now}){
 const file=(kind,id)=>path.join(dir,kind+'-'+id+'.json');
 const read=(kind,id)=>fs.existsSync(file(kind,id))?JSON.parse(fs.readFileSync(file(kind,id),'utf8')):null;
 const write=(kind,id,value)=>atomic(file(kind,id),value);
 const flights=new Map();
 function plan(run,owner){const value=pipeline.workflowPlan(uuid(run),owner);if(!value.applied?.result?.draft_revision)fail('WEEKLY_DRAFT_NOT_SAVED',409);return value;}
 const orders=run=>(weekly.read().weeks||[]).filter(w=>w.operationId===run||w.run_history?.some(h=>h.operation_id===run));
 const publicReview=r=>({operation_id:r.run_operation_id,revision:r.revision,review_hash:r.review_hash,expires_at:r.expires_at,previews:r.previews,
  can_publish:r.can_publish,blockers:r.blockers,changes:r.changes,commerce:r.commerce,work_orders:orders(r.run_operation_id),publication:null});
 function readRun(run,owner){plan(run,owner);const latest=read('run',run),review=latest?.review_hash?read('review',latest.review_hash):null;
  const operation=latest?.publication_id?read('publish',latest.publication_id):null;
  if(operation?.result&&operation.result.revision===center.read().revision)return {...operation.result,work_orders:orders(run)};
  if(review){
   if(review.owner!==owner||review.run_operation_id!==run)fail('WEEKLY_REVIEW_NOT_FOUND',409);
   const current=center.read(),stale={...publicReview(review),can_publish:false,requires_review:true};
   if(!review.can_publish||review.revision!==current.revision||review.draft_hash!==digest(canonical(current.draft))||!(Date.parse(review.expires_at)>now()))return stale;
   let prepared;
   try{prepared=validateCommerce(review.prepared,{revision:current.revision,draft:current.draft},owner);}
   catch(error){if(['WEEKLY_COMMERCE_PROPOSAL_EXPIRED','WEEKLY_COMMERCE_DRAFT_CHANGED','WEEKLY_COMMERCE_POLICY_CHANGED'].includes(error.code))return stale;throw error;}
   // Preview tokens are process-local; recreate them after restart without changing the frozen review.
   return {...publicReview(review),previews:makePreviews(current,prepared,owner),requires_review:false};
  }
  return {operation_id:run,revision:center.read().revision,work_orders:orders(run),publication:null,can_publish:false,requires_review:true};
 }
 async function review(body,owner){
  if(flights.size)fail('WEEKLY_PUBLICATION_IN_PROGRESS',409);
  fields(body,['action','operation_id','run_operation_id','revision']);uuid(body.operation_id);if(body.action!=='review')fail('INVALID_WEEKLY_WORKFLOW_REQUEST');
  const original=plan(body.run_operation_id,owner),current=center.read(),previous=read('run',body.run_operation_id);
  const publication=previous?.publication_id?read('publish',previous.publication_id):null;
  if(publication?.result&&publication.result.revision===current.revision)return {...publication.result,work_orders:orders(body.run_operation_id)};
  if(body.revision!==undefined&&body.revision!==current.revision)fail('REVISION_CONFLICT',409);
  weekly.syncDraft({operation_id:body.run_operation_id,owner,revision:current.revision});
  const prepared=await prepareCommerce({operation_id:body.run_operation_id,revision:current.revision,draft:current.draft},owner);
  if(center.read().revision!==current.revision)fail('REVISION_CONFLICT',409);
  const blockers=[...(prepared.blockers||[])];
  if(canonical(fcOnly(original.draft))!==canonical(fcOnly(current.draft)))blockers.push('NON_FC_DRAFT_CHANGED');
  for(const page of current.draft.pages.filter(p=>pages.includes(p.page_id)))if(canonical(page.benefit_refs)!==canonical([{kind:'discount',native_id:'6049'}]))blockers.push('FC27_SHARED_ITEMS_BENEFIT_REQUIRED');
  const changes=pages.map(page_id=>{const before=original.draft.pages.find(p=>p.page_id===page_id)||{},after=current.draft.pages.find(p=>p.page_id===page_id)||{};
   return {page_id,title:after.title,fields:[...new Set([...Object.keys(before),...Object.keys(after)])].filter(key=>canonical(before[key])!==canonical(after[key])).concat(canonical(original.draft.fc_layout)!==canonical(current.draft.fc_layout)?['fc_layout']:[])};});
  const previews=await makePreviews(current,prepared,owner);
  if(center.read().revision!==current.revision)fail('REVISION_CONFLICT',409);
  const expires=Math.min(now()+10*60*1000,prepared.expires_at?Date.parse(prepared.expires_at):Infinity);
  if(!Number.isFinite(expires)||expires<=now())blockers.push('COMMERCE_REVIEW_EXPIRED');
  const value={run_operation_id:body.run_operation_id,owner,revision:current.revision,draft_hash:digest(canonical(current.draft)),prepared,
   changes,previews,expires_at:new Date(Number.isFinite(expires)?expires:now()).toISOString(),blockers:[...new Set(blockers)],can_publish:prepared.can_publish===true&&!blockers.length,
   commerce:{status:prepared.status||'blocked',diff:prepared.diff||null,models_count:prepared.models_count??null,policy_write_required:prepared.policy_write_required===true},created_at:new Date(now()).toISOString()};
  value.review_hash=digest(canonical(value));write('review',value.review_hash,value);write('run',body.run_operation_id,{...read('run',body.run_operation_id),review_hash:value.review_hash});return publicReview(value);
 }
 function finish(record,result){
  const snapshot=readPublic(result);
  if(!snapshot||['release_id','config_hash','rule_hash'].some(k=>snapshot[k]!==result.published?.[k]))fail('WEEKLY_PUBLICATION_READBACK_UNKNOWN',503);
  weekly.recordPublication({run_operation_id:record.body.run_operation_id,publication_operation_id:record.body.operation_id,owner:record.owner,before_revision:record.body.revision,result,readback:snapshot});
  const publication={operation_id:record.body.operation_id,release_id:result.published.release_id,revision:result.revision,config_hash:result.published.config_hash,rule_hash:result.published.rule_hash,readback:{status:'verified',current:snapshot.current!==false},published_at:result.published.published_at??null};
  const output={...publicReview(record.review),revision:result.revision,can_publish:false,publication,work_orders:orders(record.body.run_operation_id)};
  record.result=output;record.phase='completed';write('publish',record.body.operation_id,record);write('run',record.body.run_operation_id,{review_hash:record.review.review_hash,publication_id:record.body.operation_id});return output;
 }
 async function publishOnce(body,owner){
  fields(body,['action','operation_id','run_operation_id','revision','review_hash','confirmed']);uuid(body.operation_id);uuid(body.run_operation_id);
  if(body.action!=='publish'||body.confirmed!==true||!Number.isSafeInteger(body.revision)||! /^[a-f0-9]{64}$/.test(body.review_hash||''))fail('EXPLICIT_WEEKLY_CONFIRMATION_REQUIRED');
  plan(body.run_operation_id,owner);const hash=digest(canonical(body));let record=read('publish',body.operation_id);
  if(record){if(record.owner!==owner||record.hash!==hash)fail('REQUEST_CONFLICT',409);if(record.result){
   const latest=read('run',body.run_operation_id),published=latest?.publication_id?read('publish',latest.publication_id):null;
   if(!published?.result||published.result.revision<record.result.revision)write('run',body.run_operation_id,{...latest,publication_id:body.operation_id});
   return record.result;
  }
   // Resolve the original completed center operation before expiry, prices or policy work.
   const prior=center.recoverPublish(record.request);if(prior)return finish(record,prior);
  }
  const r=record?.review||read('review',body.review_hash),current=center.read();
  if(!r||r.owner!==owner||r.run_operation_id!==body.run_operation_id||r.review_hash!==body.review_hash)fail('WEEKLY_REVIEW_NOT_FOUND',409);
  if(!r.can_publish)fail('WEEKLY_REVIEW_BLOCKED',409);
  if(r.revision!==body.revision||current.revision!==body.revision||r.draft_hash!==digest(canonical(current.draft)))fail('WEEKLY_REVIEW_STALE',409);
  if(Date.parse(r.expires_at)<=now())fail('WEEKLY_REVIEW_EXPIRED',409);
  if(!record){record={body:structuredClone(body),owner,hash,review:r,request:{operation_id:body.operation_id,revision:body.revision},phase:'prepared'};write('publish',body.operation_id,record);}
  weekly.recordConfirmation({run_operation_id:body.run_operation_id,publication_operation_id:body.operation_id,owner,revision:body.revision,review_hash:body.review_hash});
  // A completed private installation is reconciled by the same installer ID, never re-proposed.
  if(record.phase==='prepared')await validateCommerce(r.prepared,{revision:current.revision,draft:current.draft,publication_operation_id:body.operation_id},owner);
  record.phase='installing';write('publish',body.operation_id,record);
  try{
   await installCommerce(r.prepared,body.operation_id);record.phase='policy_installed';write('publish',body.operation_id,record);
   if(center.read().revision!==body.revision)fail('WEEKLY_REVIEW_STALE',409);
   return finish(record,center.recoverPublish(record.request)||center.publish(record.request,owner));
  }catch(error){throw Object.assign(error,{status:503,code:error.code||'WEEKLY_PUBLICATION_OUTCOME_RECONCILE_REQUIRED'});}
 }
 return {read:readRun,review,isPublishing:()=>flights.size>0,publish(body,owner){
  const id=uuid(body?.operation_id),hash=digest(canonical({body,owner}));
  if(flights.has(id)){const prior=flights.get(id);if(prior.hash!==hash)return Promise.reject(Object.assign(Error('REQUEST_CONFLICT'),{code:'REQUEST_CONFLICT',status:409}));return prior.promise;}
  if(flights.size)return Promise.reject(Object.assign(Error('WEEKLY_PUBLICATION_IN_PROGRESS'),{code:'WEEKLY_PUBLICATION_IN_PROGRESS',status:409}));
  const promise=publishOnce(body,owner).finally(()=>flights.delete(id));flights.set(id,{hash,promise});return promise;
 }};
}
