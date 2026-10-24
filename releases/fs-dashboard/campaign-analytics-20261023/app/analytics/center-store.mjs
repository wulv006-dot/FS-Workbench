import fs from 'node:fs';
import path from 'node:path';
import {atomic} from './store.mjs';
import {canonical,digest,createSnapshot,fail} from '../runtime/snapshot.mjs';

const pages=[
 ['fc27-weekly','fc27-season2','Weekly-Scout.html','每周好卡'],
 ['fc27-sbc','fc27-season2','Sbc-Companions.html','SBC 核心搭档'],
 ['fc27-trio','fc27-season2','Player-Trio.html','Star Performer 三人组'],
 ['seasonal-vault','mmoexp-seasonal','seasonal/index.html','MMOEXP Seasonal Vault']
];
const safeText=(v,max)=>{if(typeof v!=='string'||v.length>max||/[\u0000-\u001f<>]/.test(v))fail('INVALID_CAMPAIGN_CONFIG');return v;};
const uuid=v=>{if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v||''))fail('INVALID_OPERATION_ID');return v;};
function validateDraft(input) {
 if(!input||!Array.isArray(input.pages)||input.pages.length!==pages.length)fail('INVALID_CAMPAIGN_CONFIG');
 const result=pages.map(([page_id,activity_id,route,title])=>{
  const rows=input.pages.filter(p=>p.page_id===page_id);if(rows.length!==1)fail('INVALID_CAMPAIGN_CONFIG');const p=rows[0];
  const date=value=>{if(value===''||value==null)return null;if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))fail('INVALID_CAMPAIGN_DATES');return new Date(value).toISOString();};
  const starts_at=date(p.starts_at),ends_at=date(p.ends_at);
  if(starts_at&&ends_at&&starts_at>=ends_at)fail('INVALID_CAMPAIGN_DATES');
  return {page_id,activity_id,path:route,title:safeText(p.title||title,160),description:safeText(p.description||'',320),
   preview_enabled:p.preview_enabled===true,starts_at,ends_at,
   // Native benefits are references for review. They cannot activate checkout or issue coupons.
   benefit_refs:Array.isArray(p.benefit_refs)?p.benefit_refs.map(b=>{
    if(!['coupon','discount'].includes(b.kind)||!/^\d{1,20}$/.test(b.native_id||''))fail('INVALID_BENEFIT_REFERENCE');
    return {kind:b.kind,native_id:b.native_id};
   }).slice(0,20):[]};
 });
 if(!['halloween','thanksgiving','christmas','black-friday'].includes(input.seasonal_theme))fail('INVALID_CAMPAIGN_THEME');
 return {pages:result,seasonal_theme:input.seasonal_theme,integration_mode:'preview'};
}
export function initialCenterDraft(){return {pages:pages.map(([page_id,activity_id,route,title])=>({page_id,activity_id,path:route,title,description:'',preview_enabled:true,starts_at:null,ends_at:null,benefit_refs:[]})),seasonal_theme:'halloween',integration_mode:'preview'};}

export function makeCenterStore({dir,publicDir,sourceRevision,seedProducts=[],pageProductKeys={},seedProvider,checkpoint=()=>{}}){
 const stateFile=path.join(dir,'state.json'),pendingFile=path.join(dir,'pending.json');
 const rawRead=()=>fs.existsSync(stateFile)?JSON.parse(fs.readFileSync(stateFile,'utf8')):{revision:0,draft:initialCenterDraft(),updated_at:null,updated_by:null,published:null};
 const readJSON=file=>JSON.parse(fs.readFileSync(file,'utf8'));
 function finish(plan){
  const current=rawRead();
  if(current.revision!==plan.previous.revision&&current.last_operation?.operation_id!==plan.operation_id)fail('PENDING_OPERATION_CONFLICT',409);
  if(plan.snapshot){
   fs.mkdirSync(publicDir,{recursive:true,mode:0o755});
   const immutable=path.join(publicDir,plan.snapshot.release_id+'.json');
   if(fs.existsSync(immutable)&&canonical(readJSON(immutable))!==canonical(plan.snapshot))fail('IMMUTABLE_RELEASE_CONFLICT',409);
   if(!fs.existsSync(immutable))atomic(immutable,plan.snapshot);
   fs.chmodSync(immutable,0o644);
   atomic(path.join(publicDir,'current.json'),plan.snapshot);fs.chmodSync(path.join(publicDir,'current.json'),0o644);
   checkpoint('public-pointer');
  }
  if(plan.previous.revision)atomic(path.join(dir,'history',plan.previous.revision+'.json'),plan.previous);
  atomic(stateFile,plan.result);checkpoint('state');
  atomic(path.join(dir,'operations',plan.operation_id+'.json'),{hash:plan.hash,result:plan.result});checkpoint('receipt');
  fs.unlinkSync(pendingFile);
  if(process.platform!=='win32'){const fd=fs.openSync(dir,'r');try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
  return plan.result;
 }
 // The management writer is a single synchronous service. Every read/mutation reconciles
 // its persisted transaction first; failures cannot return an old, apparently successful state.
 function read(){if(fs.existsSync(pendingFile))finish(readJSON(pendingFile));return rawRead();}
 function operation(request,kind,user,action){
  const operation_id=uuid(request.operation_id),opFile=path.join(dir,'operations',operation_id+'.json'),hash=digest(canonical({kind,revision:request.revision,draft:request.draft??null}));
  const current=read();if(request.revision!==current.revision)fail('REVISION_CONFLICT',409);
  const {result,snapshot}=action(current);
  result.last_operation={operation_id,hash};result.updated_by=user;result.updated_at=new Date().toISOString();
  const plan={operation_id,hash,previous:current,result,...(snapshot?{snapshot}:{})};
  // Freeze the exact payload and release before any externally visible publication step.
  atomic(pendingFile,plan);checkpoint('prepared');return finish(plan);
 }
 function recover(request,kind){uuid(request.operation_id);read();const file=path.join(dir,'operations',request.operation_id+'.json'),hash=digest(canonical({kind,revision:request.revision,draft:request.draft??null}));if(fs.existsSync(file)){const prior=readJSON(file);if(prior.hash!==hash)fail('REQUEST_CONFLICT',409);return prior.result;}return null;}
 return {read,
  save(request,user){return recover(request,'save')||operation(request,'save',user,current=>({result:{...current,revision:current.revision+1,draft:validateDraft(request.draft)}}));},
  publish(request,user){return recover(request,'publish')||operation(request,'publish',user,current=>{
   const draft=validateDraft(current.draft),revision=current.revision+1,release_id='campaign-preview-'+revision;
   const seed=seedProvider?seedProvider():{seedProducts,pageProductKeys};
   const snapshot=createSnapshot({schema_version:1,publication_status:'published',release_id,source_revision:sourceRevision,
    config_hash:digest(canonical({draft,products:seed.seedProducts,pageProductKeys:seed.pageProductKeys})),rule_hash:digest(canonical(draft.pages.map(p=>p.benefit_refs))),products:seed.seedProducts,seasonal_theme:draft.seasonal_theme,
    pages:draft.pages.map(p=>({activity_id:p.activity_id,page_id:p.page_id,path:p.path,title:p.title,
     description:p.description,rule_version:'preview-'+revision,benefit_binding_version:'unverified-'+revision,product_keys:seed.pageProductKeys[p.page_id]||[],
     active:p.preview_enabled,...(p.starts_at?{starts_at:p.starts_at}:{}),...(p.ends_at?{ends_at:p.ends_at}:{})}))});
   return {snapshot,result:{...current,revision,draft,published:{release_id,config_hash:snapshot.config_hash,rule_hash:snapshot.rule_hash,mode:'preview',live_checkout:false,published_at:new Date().toISOString()}}};
  })}
 };
}

export {validateDraft};
