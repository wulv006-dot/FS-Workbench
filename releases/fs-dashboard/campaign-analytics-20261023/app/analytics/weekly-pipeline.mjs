import fs from 'node:fs';
import path from 'node:path';
import {atomic} from './store.mjs';
import {canonical,digest,fail} from '../runtime/snapshot.mjs';
import {modelVariants,projectModels} from '../runtime/model-cards.mjs';

const pageIds=['fc27-trio','fc27-weekly','fc27-sbc'];
const uuid=value=>{if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value||''))fail('INVALID_OPERATION_ID');return value;};
const actor=value=>{if(typeof value!=='string'||!value.trim()||value.length>160||/[\u0000-\u001f]/.test(value))fail('WEEKLY_ACTOR_REQUIRED',403);return value;};
const same=(a,b)=>canonical(a)===canonical(b);
export function makeWeeklyPipeline({dir,center,contextProvider,sourceProvider,nativeCandidateProvider=()=>null,enabledProvider=()=>false,onDraftSaved=()=>{},beforeDraftSave=()=>{},now=Date.now}){
 const file=id=>path.join(dir,uuid(id)+'.json');
 const read=id=>fs.existsSync(file(id))?JSON.parse(fs.readFileSync(file(id),'utf8')):null;
 const commercePlan=(operation_id,owner)=>{
  uuid(operation_id);const plan=read(operation_id);
  if(!plan||plan.owner!==owner)fail('WEEKLY_OPERATION_OWNER_MISMATCH',403);
  const current=center.read(),revision=plan.applied?.result?.draft_revision??null;
  if(revision===null)fail('WEEKLY_COMMERCE_DRAFT_NOT_SAVED',409);
  const layout=current.draft.fc_layout,selected=new Set([...(layout?.weekly||[]),...(layout?.trio||[]),...(layout?.sbc||[]),...Object.values(layout?.routes||{}).flatMap(r=>[...(r.picks||[]),...(r.alternatives||[])])].map(key=>current.draft.fc_models?.[key]?.model_id).filter(Boolean));
  const proposal=plan.native_candidates,candidate=proposal?.native_catalog_candidate;
  const models=candidate?Object.fromEntries(Object.entries(candidate.model_contracts||{}).filter(([id])=>selected.has(id))):{};
  const products=candidate?.products.filter(p=>selected.has(p.product_ref.model_id))||[];
  const catalog=products.length?{...structuredClone(candidate),products:structuredClone(products),model_contracts:structuredClone(models)}:null;
  return {operation_id,plan_ref:operation_id,draft_revision:revision,current_revision:current.revision,stale:revision!==current.revision,
   expired:!catalog||Date.parse(catalog.valid_until)<=now(),approval_required:true,policy_written:false,publication:false,
   native_catalog_candidate:catalog,price_policy_candidates:structuredClone((proposal?.price_policy_candidates||[]).filter(p=>selected.has(p.policy.model_ref.model_id))),
   models:structuredClone((proposal?.models||[]).filter(p=>selected.has(p.model_id)))};
 };
 const notifySaved=(plan,result)=>{onDraftSaved({operation_id:plan.operation_id,owner:plan.owner,draft_revision:result.draft_revision,trigger:plan.trigger||'unknown',created_at:plan.created_at});return result;};
 const output=plan=>({status:'prepared',operation_id:plan.operation_id,plan_ref:plan.operation_id,input:plan.input,rules_version:plan.input.rules.version,
  trio_players:plan.input.catalog.filter(p=>plan.input.pages.find(p=>p.page_id==='fc27-trio').product_keys.includes(p.key)).map(p=>({name:p.title,model_id:p.product_ref.model_id,key:p.key})),
  evidence_refs:[],source_evidence:plan.source.evidence,checks:plan.checks});
 return {
  workflowPlan(operation_id,owner){
   uuid(operation_id);actor(owner);const plan=read(operation_id);if(!plan||plan.owner!==owner)fail('WEEKLY_OPERATION_OWNER_MISMATCH',403);
   const receipt=this.inspect({operation_id,plan_ref:operation_id},owner);
   return structuredClone(receipt.status==='draft_saved'&&!plan.applied?{...plan,applied:{hash:plan.apply_hash,result:receipt}}:plan);
  },
  commercePlan({operation_id},owner){actor(owner);return commercePlan(operation_id,owner);},
  draftTrade(){const current=center.read(),operation_id=current.last_operation?.operation_id;if(!operation_id)return null;const plan=read(operation_id);if(!plan?.applied)return null;const bundle=commercePlan(operation_id,plan.owner);return bundle.stale||bundle.expired?null:bundle.native_catalog_candidate;},
  inspect({operation_id,plan_ref},owner){
   uuid(operation_id);actor(owner);if(plan_ref!==operation_id)fail('WEEKLY_PLAN_MISMATCH');const plan=read(operation_id);
   if(!plan||plan.owner!==owner)fail('WEEKLY_OPERATION_OWNER_MISMATCH',403);
   if(plan.applied)return notifySaved(plan,plan.applied.result);
   const receiptFile=path.join(path.dirname(dir),'operations',operation_id+'.json');
   if(fs.existsSync(receiptFile)){
    const receipt=JSON.parse(fs.readFileSync(receiptFile,'utf8')),last=receipt.result?.last_operation;
    const expected=plan.save_request?digest(canonical({kind:'save',revision:plan.save_request.revision,draft:plan.save_request.draft,model_imports:plan.save_request.model_imports,...(plan.save_request.model_refresh_digest?{model_refresh_digest:plan.save_request.model_refresh_digest}:{})})):null;
    if(!expected||receipt.hash!==expected||last?.hash!==expected||last?.operation_id!==operation_id||last.kind!=='save'||receipt.result.updated_by!==owner||receipt.result.revision!==plan.base_revision+1)return {status:'unknown',operation_id,plan_ref,publication:false};
    return notifySaved(plan,{status:'draft_saved',operation_id,plan_ref,base_revision:plan.base_revision,draft_revision:receipt.result.revision,readback:{status:'verified',source:'center_operation_receipt',operation_id,revision:receipt.result.revision,hash:receipt.hash},checks:plan.checks,publication:false,source_evidence:plan.source.evidence});
   }
   return {status:fs.existsSync(path.join(path.dirname(dir),'pending.json'))?'unknown':'not_found',operation_id,plan_ref,publication:false};
  },
  async prepare({operation_id,trigger='unknown'},owner){
   if(!['manual','scheduled','unknown'].includes(trigger))fail('INVALID_WEEKLY_TRIGGER');
   uuid(operation_id);actor(owner);if(!enabledProvider())return {status:'disabled',operation_id,reason:'hermes_disabled',publication:false};const prior=read(operation_id);
   if(prior){if(prior.owner!==owner)fail('WEEKLY_OPERATION_OWNER_MISMATCH',403);return output(prior);}
   const current=center.read(),context=contextProvider(current),source=await sourceProvider();
   if(!enabledProvider())return {status:'disabled',operation_id,reason:'hermes_disabled',publication:false};if(center.read().revision!==current.revision)fail('REVISION_CONFLICT',409);
   if(source.rules_version!=='fc27_weekly_selection_v1'||!Array.isArray(source.models))fail('WEEKLY_SOURCE_INVALID');
   const models=projectModels(Object.fromEntries(source.models.map(model=>[model.key,model])));
   const representative=mid=>'fc-model-266-1327-'+mid+'-ps';
   const catalog=modelVariants(models).filter(p=>p.platform.code==='ps').map(p=>({key:p.key,title:p.title,product_ref:p.product_ref,platform:p.platform,available:false,binding_state:p.binding_state}));
   const keys=new Set(catalog.map(p=>p.key)),pool=ids=>{if(!Array.isArray(ids)||ids.some(id=>!keys.has(representative(id))))fail('WEEKLY_SOURCE_INVALID');return ids.map(representative);};
   const scout=pool(source.scout_model_ids),trio=pool(source.trio_player_ids),cores=pool(source.sbc_model_ids);
   const normal=new Set((source.observations||[]).filter(o=>o.player_type==='normal').map(o=>o.model_id));
   const players=[...new Set([...pool(source.latest_player_ids),...scout])].filter(key=>{const mid=catalog.find(p=>p.key===key).product_ref.model_id;return normal.has(mid)&&models['model-266-1327-'+mid]?.kind==='player';});
   if(scout.length!==3||trio.length<3)fail('WEEKLY_SOURCE_INVALID');
   if(source.evidence?.newest_complete!==true||!source.evidence.newest_tag_id||source.evidence.newest_normal_count!==trio.length||trio.some(key=>!normal.has(catalog.find(p=>p.key===key).product_ref.model_id)))fail('WEEKLY_NEWEST_POOL_UNVERIFIED');
   if(cores.length!==9||new Set(cores).size!==9)fail('WEEKLY_SBC_CORE_COVERAGE_INCOMPLETE');
   if(players.length<18)fail('WEEKLY_SBC_COMPANION_POOL_INSUFFICIENT');
   const input={source_revision:String(current.revision),sbc_update:{id:operation_id,observed_at:source.observed_at,expires_at:null,context:'Current FC27 Admin model identities. The complete Trio candidate pool comes from the active Newest tag, filtered to observed normal Players. Choose three popular players using supplied external market, social and specialist-site evidence plus model judgment; Newest membership and candidate order do not prove popularity. Missing market evidence must remain explicit, and external popularity must not be described as our sales. Scout preserves the supplied Popular source order. SBC/core ordering may use model ID descending where creation timestamps are not provided. The SBC Player pool is restricted to observed normal Player types. Assign exactly 2 different players to each of the 9 SBC cores, using 18 distinct Player models globally; do not output extra alternatives. The application makes the shared 18-player dropdown from these assignments. Preserve real card versions; do not assert prices or checkout readiness. Actual game SBC expiry is not supplied.',sources:[]},
    pages:[{page_id:'fc27-trio',product_keys:trio},{page_id:'fc27-weekly',product_keys:scout},{page_id:'fc27-sbc',product_keys:[...cores,...players],core_product_keys:cores}],catalog,
    rules:{version:'fc27_weekly_selection_v1',scout_top_keys:scout}};
   const native_candidates=nativeCandidateProvider(source);
   const plan={operation_id,owner,trigger,created_at:new Date(now()).toISOString(),base_revision:current.revision,draft:current.draft,layout:context.effective_fc_layout,source,models,input,native_candidates,
    checks:{goods_identity:'observed_per_platform',quote:'pending',native_checkout:'pending',coupon:'pending',publication:false,...(native_candidates?{native_candidate_status:native_candidates.status,model_mapping:native_candidates.models}:{})}};
   // First writer retains its frozen source; a duplicate prepare never replaces it.
   fs.mkdirSync(dir,{recursive:true,mode:0o700});let fd;
   try{fd=fs.openSync(file(operation_id),'wx',0o600);fs.writeFileSync(fd,JSON.stringify(plan));fs.fsyncSync(fd);}catch(error){if(error.code!=='EEXIST')throw error;const saved=read(operation_id);if(saved.owner!==owner)fail('WEEKLY_OPERATION_OWNER_MISMATCH',403);return output(saved);}finally{if(fd!==undefined)fs.closeSync(fd);}
   return output(plan);
  },
  apply({operation_id,plan_ref,recommendation,evidence_sources=[]},owner){
   uuid(operation_id);actor(owner);if(plan_ref!==operation_id)fail('WEEKLY_PLAN_MISMATCH');const plan=read(operation_id);
   if(!plan||plan.owner!==owner)fail('WEEKLY_OPERATION_OWNER_MISMATCH',403);
   const hash=digest(canonical({recommendation,evidence_sources}));
   if(plan.apply_hash&&plan.apply_hash!==hash)fail('REQUEST_CONFLICT',409);
   if(plan.applied){if(plan.applied.hash!==hash)fail('REQUEST_CONFLICT',409);return notifySaved(plan,plan.applied.result);}
   if(!enabledProvider())return {status:'disabled',operation_id,reason:'hermes_disabled',publication:false};
   if(!Array.isArray(evidence_sources)||evidence_sources.length>20||evidence_sources.some(s=>{
    try{const u=new URL(s.url);return u.protocol!=='https:'||u.username||u.password||u.search||u.hash||typeof s.title!=='string'||s.title.length>240||!Number.isFinite(Date.parse(s.observed_at))||Date.parse(s.observed_at)>now();}catch{return true;}
   }))fail('WEEKLY_EVIDENCE_INVALID');
   const input=plan.input,result=recommendation;
   if(result?.model!=='gpt-6.1-sol'||result.source_revision!==input.source_revision||result.sbc_update_id!==input.sbc_update.id||!Array.isArray(result.recommendations)||result.recommendations.length!==24)fail('INVALID_WEEKLY_HERMES_INPUT');
   const catalog=new Map(input.catalog.map(p=>[p.key,p])),rows=result.recommendations,seen=new Set();
   for(const row of rows){const page=input.pages.find(p=>p.page_id===row.page_id),sig=canonical([row.page_id,row.product_key,row.core_product_key??null]);
    if(!page?.product_keys.includes(row.product_key)||seen.has(sig)||!Array.isArray(row.evidence_indices)||row.evidence_indices.some(i=>!Number.isInteger(i)||i<0||i>=evidence_sources.length))fail('INVALID_WEEKLY_HERMES_INPUT');seen.add(sig);
    if(row.page_id==='fc27-sbc'){if(!page.core_product_keys.includes(row.core_product_key)||page.core_product_keys.includes(row.product_key))fail('INVALID_WEEKLY_HERMES_INPUT');}
    else if(row.core_product_key!=null)fail('INVALID_WEEKLY_HERMES_INPUT');
   }
   const weekly=rows.filter(r=>r.page_id==='fc27-weekly'),trio=rows.filter(r=>r.page_id==='fc27-trio'),sbc=rows.filter(r=>r.page_id==='fc27-sbc');
   if(!same(weekly.map(r=>r.product_key),input.rules.scout_top_keys)||trio.length!==3||new Set(trio.map(r=>catalog.get(r.product_key).product_ref.model_id)).size!==3)fail('WEEKLY_SELECTION_RULE_MISMATCH');
   plan.checks.external_evidence=trio.every(r=>r.evidence_indices.length)?'provided_unverified':trio.some(r=>r.evidence_indices.length)?'partial':'metadata_only';
   const logical=key=>'model-266-1327-'+catalog.get(key).product_ref.model_id;
   const companionPool=sbc.map(r=>logical(r.product_key));
   if(input.pages.find(p=>p.page_id==='fc27-sbc').core_product_keys.length!==9||companionPool.length!==18||new Set(companionPool).size!==18)fail('WEEKLY_SELECTION_RULE_MISMATCH');
   const layout=structuredClone(plan.layout);layout.weekly=weekly.map(r=>logical(r.product_key));layout.trio=trio.map(r=>logical(r.product_key));
   layout.sbc=input.pages.find(p=>p.page_id==='fc27-sbc').core_product_keys.map(logical);layout.defaultCore=layout.sbc[0];
   // Existing dormant routes, bundles and all other pages remain in their source draft.
   for(const core of input.pages.find(p=>p.page_id==='fc27-sbc').core_product_keys){const companions=sbc.filter(r=>r.core_product_key===core).map(r=>logical(r.product_key));
    if(companions.length!==2||new Set(companions).size!==2)fail('WEEKLY_SELECTION_RULE_MISMATCH');
    layout.routes[logical(core)]={picks:companions,alternatives:companionPool.filter(key=>!companions.includes(key))};
   }
   const draft=structuredClone(plan.draft);draft.fc_layout=layout;
   // FC page keys inherit the real layout, replacing only these three selections.
   for(const page of draft.pages)if(pageIds.includes(page.page_id))delete page.product_keys;
   const used=[...new Set([...layout.weekly,...layout.trio,...layout.sbc,...layout.sbc.flatMap(k=>[...layout.routes[k].picks,...layout.routes[k].alternatives])])];
   const imports=used.filter(key=>!same(draft.fc_models?.[key]??null,plan.models[key]??null)).map(key=>{const model=plan.models[key];if(!model)fail('WEEKLY_SOURCE_INVALID');return {page_id:layout.weekly.includes(key)?'fc27-weekly':layout.trio.includes(key)?'fc27-trio':'fc27-sbc',model_id:model.model_id,kind:model.kind};});
   const details=imports.map(i=>plan.models['model-266-1327-'+i.model_id]);
   const request={operation_id,revision:plan.base_revision,draft,model_imports:imports,model_refresh_digest:digest(canonical(details))};
   if(plan.save_request&&!same(plan.save_request,request))fail('REQUEST_CONFLICT',409);
   plan.save_request=request;plan.apply_hash=hash;atomic(file(operation_id),plan);
   let saved=center.recoverSave(request);if(!saved){beforeDraftSave();saved=center.save(request,owner,details,[],{refreshModels:true});}
   const persisted=JSON.parse(fs.readFileSync(path.join(path.dirname(dir),'operations',operation_id+'.json'),'utf8'));
   if(persisted.hash!==saved.last_operation?.hash||persisted.result?.revision!==saved.revision||persisted.result?.last_operation?.operation_id!==operation_id)fail('WEEKLY_DRAFT_READBACK_UNKNOWN',409);
   const receipt={status:'draft_saved',operation_id,plan_ref,base_revision:plan.base_revision,draft_revision:saved.revision,readback:{status:'verified',source:'center_operation_receipt',operation_id,revision:saved.revision,hash:persisted.hash},checks:plan.checks,publication:false,source_evidence:plan.source.evidence};
   plan.applied={hash,result:receipt,evidence_sources,at:new Date(now()).toISOString()};atomic(file(operation_id),plan);return notifySaved(plan,receipt);
  }
 };
}
