import fs from 'node:fs';
import path from 'node:path';
import {projectWeeklyProviderReceipt} from './weekly-hermes-provider.mjs';
import {atomic} from './store.mjs';
import {canonical,digest,fail} from '../runtime/snapshot.mjs';
import {projectWeeklyResponse} from './weekly-hermes.mjs';

export function makeWeeklyRecommendations({dir,contextProvider,provider,now=Date.now}){
 const file=path.join(dir,'weekly-recommendations.json');
 const raw=()=>fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{operations:[],requests:[]};
 const view=(record,context=contextProvider())=>({...record.result,operation_id:record.operation_id,submitted_at:record.submitted_at,updated_at:record.updated_at,
  ...(record.id?{id:record.id}:{}),...(record.page_id?{page_id:record.page_id}:{}),sbc_update:record.sbc_update,
  stale:record.result.source_revision!==context.source_revision||Boolean(record.sbc_update.expires_at&&Date.parse(record.sbc_update.expires_at)<=now())});
 function read(){const state=raw(),context=contextProvider(),history=state.requests.map(record=>view(record,context)).reverse();return {last:history[0]??null,history};}
 async function recommend(body,user){
  if(!body||typeof body!=='object'||Array.isArray(body)||Object.keys(body).some(key=>!['revision','operation_id','id','page_id','sbc_update'].includes(key))||!Number.isSafeInteger(body.revision)||body.revision<0)fail('INVALID_WEEKLY_RECOMMENDATION');
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(body.operation_id||''))fail('INVALID_OPERATION_ID');
  if(typeof user!=='string'||!user||user.length>160||/[<>\u0000-\u001f]/.test(user))fail('INVALID_WEEKLY_RECOMMENDATION');
  if(body.id!=null&&!/^\d{4}-W(?:0[1-9]|[1-4]\d|5[0-3])$/.test(body.id)||body.page_id!=null&&!['fc27-trio','fc27-weekly','fc27-sbc'].includes(body.page_id))fail('INVALID_WEEKLY_RECOMMENDATION');
  const state=raw(),hash=digest(canonical(body)),original=state.operations.find(operation=>operation.id===body.operation_id);
  if(original){const saved=state.requests.find(record=>record.operation_id===original.request_id);if(saved.submitted_by!==user)fail('WEEKLY_RECOMMENDATION_OWNER_REQUIRED',403);if(original.hash!==hash)fail('REQUEST_CONFLICT',409);return view(saved);}
  throw Object.assign(new Error('旧推荐入口已停用，请使用顶部“按当前规则取品并生成草稿”；新版会按当前规则生成并保存待审草稿。'),{code:'WEEKLY_LEGACY_GENERATION_RETIRED_USE_WEEKLY_RUN',status:410});
 }
 async function reconcile(body,user,{provider:requestProvider}={}){
  if(!body||typeof body!=='object'||Object.keys(body).length!==1||typeof body.operation_id!=='string')fail('INVALID_WEEKLY_RECOMMENDATION');
  const state=raw(),operation=state.operations.find(item=>item.id===body.operation_id),record=state.requests.find(item=>item.operation_id===operation?.request_id);
  if(!record)fail('WEEKLY_RECOMMENDATION_NOT_FOUND',404);
  if(record.submitted_by!==user)fail('WEEKLY_RECOMMENDATION_OWNER_REQUIRED',403);
  if(!['pending','unknown'].includes(record.result.status)&&record.result.provider_outcome!=='unknown')return view(record);
  const effectiveProvider=requestProvider??provider;if(typeof effectiveProvider?.lookup!=='function')return view(record);
  let result;
  try{result=projectWeeklyResponse(await effectiveProvider.lookup({operation_id:record.operation_id}),record.prepared,now());}
  catch(error){
   if(error?.code==='WEEKLY_HERMES_PROVIDER_UNAVAILABLE'&&error.provider_outcome==='not_dispatched'&&error.original_outcome_confirmed===true)result={...record.result,status:'unavailable',error:error.code,provider_outcome:'not_dispatched',candidates:[]};
   else if(error?.code==='WEEKLY_HERMES_RECOMMENDATION_FAILED'&&error.provider_outcome==='completed'&&error.original_outcome_confirmed===true)result={...record.result,status:'failed',error:error.code,provider_outcome:'completed',candidates:[]};
   else if(['WEEKLY_HERMES_PROVIDER_PENDING','WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'].includes(error?.code))return view(raw().requests.find(item=>item.operation_id===record.operation_id));
   else throw error;
  }
  const current=raw(),saved=current.requests.find(item=>item.operation_id===record.operation_id);if(saved.result.status==='completed')return view(saved);const receipt=projectWeeklyProviderReceipt(effectiveProvider.receipt,record.operation_id);saved.result={...result,...(receipt?{receipt}:saved.result.receipt?{receipt:saved.result.receipt}:{})};saved.updated_at=new Date(now()).toISOString();atomic(file,current);return view(saved);
 }
 return {read,recommend,reconcile};
}
