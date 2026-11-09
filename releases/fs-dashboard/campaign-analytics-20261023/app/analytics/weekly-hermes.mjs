import {canonical,fail} from '../runtime/snapshot.mjs';
import {fcPlatforms} from '../runtime/model-cards.mjs';

export const weeklyHermesModel='gpt-6.1-sol';
const pageIds=['fc27-trio','fc27-weekly','fc27-sbc'];
const object=value=>value&&typeof value==='object'&&!Array.isArray(value);
const only=(value,keys)=>object(value)&&Object.keys(value).every(key=>keys.includes(key));
const invalid=()=>fail('INVALID_WEEKLY_HERMES_INPUT');
const plain=(value,max)=>{if(typeof value!=='string'||!value.trim()||value.length>max||/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value))invalid();return value;};
const positive=value=>typeof value==='string'&&/^[1-9]\d{0,19}$/.test(value);

// Historical receipt validation only. New generation is owned by weekly/run.
function candidates(response,request,now){
 const {input}=request;
 if(!only(response,['model','source_revision','sbc_update_id','recommendations'])||response.model!==request.model||response.source_revision!==input.source_revision||response.sbc_update_id!==input.sbc_update.id||!Array.isArray(response.recommendations)||response.recommendations.length>60)invalid();
 const catalog=new Map(input.catalog.map(product=>[product.key,product])),seen=new Set();
 return response.recommendations.map(row=>{
  if(!only(row,['page_id','product_key','core_product_key','reason','evidence_indices'])||!pageIds.includes(row.page_id)||!catalog.has(row.product_key)||!Array.isArray(row.evidence_indices)||row.evidence_indices.length>20||new Set(row.evidence_indices).size!==row.evidence_indices.length||row.evidence_indices.some(index=>!Number.isInteger(index)||index<0||index>=input.sbc_update.sources.length))invalid();
  const product=catalog.get(row.product_key),core=catalog.get(row.core_product_key),sbc=row.page_id==='fc27-sbc';
  if(sbc?(!input.pages.find(page=>page.page_id==='fc27-sbc').core_product_keys.includes(row.core_product_key)||row.core_product_key===row.product_key):row.core_product_key!=null)invalid();
  const signature=canonical([row.page_id,row.product_key,row.core_product_key??null]);if(seen.has(signature))invalid();seen.add(signature);
  const pending=new Set();
  for(const item of [product,...(core?[core]:[])]){
   if(fcPlatforms[item.platform.code]!==item.platform.attribute_id)pending.add('platform_unverified');
   if(!positive(item.product_ref.goods_id)||['missing','ambiguous','offline'].includes(item.binding_state))pending.add('identity_unverified');
   if(item.available!==true)pending.add('sellability_unverified');
   pending.add('product_freshness_unknown');
  }
  if(core&&core.platform.code!==product.platform.code)pending.add('platform_mismatch');
  const update=input.sbc_update;
  if(!row.evidence_indices.length)pending.add('source_evidence_missing');
  if(update.expires_at==null)pending.add('update_expiry_unknown');
  else if(Date.parse(update.expires_at)<=now)pending.add('update_expired');
  if(Date.parse(update.observed_at)>now||row.evidence_indices.some(index=>Date.parse(update.sources[index].observed_at)>now))pending.add('source_time_unverified');
  return {page_id:row.page_id,product_key:row.product_key,...(sbc?{core_product_key:row.core_product_key}:{}),reason:plain(row.reason,800),evidence_indices:[...row.evidence_indices],pending_verification:[...pending],verification_scope:'recommendation_only'};
 });
}

export function projectWeeklyResponse(response,request,now=Date.now()){
 return {model:weeklyHermesModel,schedule_enabled:false,publication:false,verification_scope:'recommendation_only',status:'completed',
  source_revision:request.input.source_revision,sbc_update_id:request.input.sbc_update.id,dedupe_key:request.dedupe_key,candidates:candidates(response,request,now)};
}
