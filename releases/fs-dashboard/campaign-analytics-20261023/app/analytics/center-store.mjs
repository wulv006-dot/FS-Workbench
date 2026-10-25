import fs from 'node:fs';
import path from 'node:path';
import {atomic} from './store.mjs';
import {canonical,digest,createSnapshot,fail,presentationFields,projectPreviewProduct,id,pageDisplayFields} from '../runtime/snapshot.mjs';
import {addImportedProduct,projectImportedProduct} from './center-seed.mjs';
import {projectModels,projectModelCard} from '../runtime/model-cards.mjs';
import {projectMedia} from '../runtime/media-contract.mjs';
import {makeMediaStore} from './media-store.mjs';

const pages=[
 ['fc27-weekly','fc27-season2','Weekly-Scout.html','每周好卡'],
 ['fc27-sbc','fc27-season2','Sbc-Companions.html','SBC 核心搭档'],
 ['fc27-trio','fc27-season2','Player-Trio.html','Star Performer 三人组'],
 ['seasonal-vault','mmoexp-seasonal','seasonal/index.html','MMOEXP Seasonal Vault']
];
const safeText=(v,max)=>{if(typeof v!=='string'||v.length>max||/[\u0000-\u001f<>]/.test(v))fail('INVALID_CAMPAIGN_CONFIG');return v;};
const uuid=v=>{if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v||''))fail('INVALID_OPERATION_ID');return v;};
function validateDraft(input,{validateFcLayout}={}) {
 if(!input||!Array.isArray(input.pages)||input.pages.length!==pages.length)fail('INVALID_CAMPAIGN_CONFIG');
 const result=pages.map(([page_id,activity_id,route,title])=>{
  const rows=input.pages.filter(p=>p.page_id===page_id);if(rows.length!==1)fail('INVALID_CAMPAIGN_CONFIG');const p=rows[0];
  const date=value=>{if(value===''||value==null)return null;if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))fail('INVALID_CAMPAIGN_DATES');return new Date(value).toISOString();};
  const starts_at=date(p.starts_at),ends_at=date(p.ends_at);
  if(starts_at&&ends_at&&starts_at>=ends_at)fail('INVALID_CAMPAIGN_DATES');
  let selection={};
  if(Object.hasOwn(p,'product_keys')){
   if(!Array.isArray(p.product_keys)||p.product_keys.length>500||new Set(p.product_keys).size!==p.product_keys.length||p.product_keys.some(k=>typeof k!=='string'))fail('INVALID_PAGE_PRODUCTS');
   selection={product_keys:p.product_keys.map(id)};
  }
  return {page_id,activity_id,path:route,title:safeText(p.title||title,160),description:safeText(p.description||'',320),
   ...selection,...pageDisplayFields({...p,path:route}),...(Object.hasOwn(p,'media')?{media:projectMedia(p.media)}:{}),
   preview_enabled:p.preview_enabled===true,starts_at,ends_at,...presentationFields({...p,path:route}),
   // Native benefits are references for review. They cannot activate checkout or issue coupons.
   benefit_refs:Array.isArray(p.benefit_refs)?p.benefit_refs.map(b=>{
    if(!['coupon','discount'].includes(b.kind)||!/^\d{1,20}$/.test(b.native_id||''))fail('INVALID_BENEFIT_REFERENCE');
    return {kind:b.kind,native_id:b.native_id};
   }).slice(0,20):[]};
 });
 if(!['halloween','thanksgiving','christmas','black-friday'].includes(input.seasonal_theme))fail('INVALID_CAMPAIGN_THEME');
 let imports={};
 if(Object.hasOwn(input,'imported_products')){
  if(!Array.isArray(input.imported_products)||input.imported_products.length>500)fail('INVALID_IMPORTED_PRODUCT');
  const imported_products=input.imported_products.map(projectPreviewProduct);
  if(new Set(imported_products.map(p=>p.key)).size!==imported_products.length)fail('INVALID_IMPORTED_PRODUCT');
  imports={imported_products};
 }
 let layout={};
 const models=Object.hasOwn(input,'fc_models')?{fc_models:projectModels(input.fc_models)}:{};
 if(Object.hasOwn(input,'fc_layout')){
  if(typeof validateFcLayout!=='function')fail('FC_LAYOUT_VALIDATOR_REQUIRED');
  try{layout={fc_layout:validateFcLayout(input.fc_layout,models.fc_models||{})};}catch(error){if(error.status)throw error;fail('INVALID_FC_LAYOUT');}
 }
 return {pages:result,...imports,...models,...layout,seasonal_theme:input.seasonal_theme,integration_mode:'preview'};
}
export function initialCenterDraft(){return {pages:pages.map(([page_id,activity_id,route,title])=>({page_id,activity_id,path:route,title,description:'',preview_enabled:true,starts_at:null,ends_at:null,benefit_refs:[],default_language:'original',social_image:'original'})),seasonal_theme:'halloween',integration_mode:'preview'};}

// Validation and storage have different jobs: validate the supplied known contract,
// then retain its exact legal shape instead of persisting presentation defaults.
function preserveDraftShape(input,options){
 const record=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(k=>keys.includes(k));
 if(!record(input,['pages','seasonal_theme','integration_mode','fc_layout','fc_models','imported_products'])||!Array.isArray(input.pages))fail('INVALID_CAMPAIGN_CONFIG');
 if(Object.hasOwn(input,'integration_mode')&&input.integration_mode!=='preview')fail('INVALID_CAMPAIGN_CONFIG');
 for(const page of input.pages){
  if(!record(page,['page_id','activity_id','path','title','description','preview_enabled','starts_at','ends_at','benefit_refs','default_language','social_image','product_keys','product_roles','sbc_companions','media']))fail('INVALID_CAMPAIGN_CONFIG');
  const expected=pages.find(row=>row[0]===page.page_id);if(!expected)fail('INVALID_CAMPAIGN_CONFIG');
  if(Object.hasOwn(page,'activity_id')&&page.activity_id!==expected[1]||Object.hasOwn(page,'path')&&page.path!==expected[2])fail('INVALID_CAMPAIGN_CONFIG');
  for(const key of ['title','description'])if(Object.hasOwn(page,key))safeText(page[key],key==='title'?160:320);
  if(Object.hasOwn(page,'preview_enabled')&&typeof page.preview_enabled!=='boolean')fail('INVALID_CAMPAIGN_CONFIG');
  for(const key of ['starts_at','ends_at'])if(Object.hasOwn(page,key)&&page[key]!==null&&typeof page[key]!=='string')fail('INVALID_CAMPAIGN_DATES');
  for(const key of ['default_language','social_image'])if(Object.hasOwn(page,key)&&typeof page[key]!=='string')fail('INVALID_PRESENTATION_CONFIG');
  if(Object.hasOwn(page,'benefit_refs')&&(!Array.isArray(page.benefit_refs)||page.benefit_refs.length>20||page.benefit_refs.some(ref=>!record(ref,['kind','native_id'])||typeof ref.native_id!=='string')))fail('INVALID_BENEFIT_REFERENCE');
 }
 if(Object.hasOwn(input,'fc_layout')){
  const layout=input.fc_layout;
  if(!record(layout,['weekly','trio','bundles','sbc','defaultCore','routes'])||!layout.routes||typeof layout.routes!=='object'||Array.isArray(layout.routes)||!Array.isArray(layout.sbc))fail('INVALID_FC_LAYOUT');
  for(const row of Object.values(layout.routes)){
   if(!record(row,['picks','alternatives','label']))fail('INVALID_FC_LAYOUT');
   if(Object.hasOwn(row,'label')){if(!record(row.label,['zh','en']))fail('INVALID_FC_LAYOUT');for(const value of Object.values(row.label))safeText(value,160);}
  }
  // The original editor retains routes for deselected catalog cores. Validate
  // those dormant entries through the same catalog contract without deleting them.
  if(Object.keys(layout.routes).some(key=>!layout.sbc.includes(key))){
   if(typeof options?.validateFcLayout!=='function')fail('FC_LAYOUT_VALIDATOR_REQUIRED');
   try{options.validateFcLayout({...layout,sbc:[...new Set([...layout.sbc,...Object.keys(layout.routes)])]},input.fc_models||{});}
   catch(error){if(error.status)throw error;fail('INVALID_FC_LAYOUT');}
  }
 }
 validateDraft(input,options);
 return structuredClone(input);
}

export function makeCenterStore({dir,publicDir,sourceRevision,seedProducts=[],pageProductKeys={},fc_layout,seedProvider,validateFcLayout,checkpoint=()=>{}}){
 const stateFile=path.join(dir,'state.json'),pendingFile=path.join(dir,'pending.json');
 const rawRead=()=>fs.existsSync(stateFile)?JSON.parse(fs.readFileSync(stateFile,'utf8')):{revision:0,draft:initialCenterDraft(),updated_at:null,updated_by:null,published:null};
 const readJSON=file=>JSON.parse(fs.readFileSync(file,'utf8'));
 const assets=makeMediaStore({dir:path.join(dir,'media'),publicDir,operationsDir:path.join(dir,'operations')});
 const seedNow=draft=>seedProvider?seedProvider(draft?.fc_layout,draft?.fc_models||{}):{seedProducts,pageProductKeys,...(draft?.fc_layout||fc_layout?{fc_layout:draft?.fc_layout||fc_layout}:{})};
 const draftOf=input=>validateDraft(input,{validateFcLayout});
 const storedDraft=input=>preserveDraftShape(input,{validateFcLayout});
 const requestHash=(request,kind)=>digest(canonical({kind,revision:request.revision,draft:request.draft??null,
  ...(kind==='import'?{page_id:request.page_id,product_ref:request.product_ref}: {}),...(kind==='model-import'?{page_id:request.page_id,model_id:request.model_id,model_kind:request.kind}:{}),...(kind==='restore'?{restore_revision:request.restore_revision}:{})}));
 function preserveImports(current,draft){
  if(canonical(current.draft.imported_products||[])!==canonical(draft?.imported_products||[]))fail('IMPORTED_PRODUCTS_SERVER_OWNED');
  if(Object.hasOwn(current.draft,'fc_models')!==Object.hasOwn(draft||{},'fc_models')||canonical(current.draft.fc_models)!==canonical(draft?.fc_models))fail('MODELS_SERVER_OWNED');
 }
 function selectionScope(draft,seed){
  assets.manifest(draft);
  const products=new Map([...seed.seedProducts,...(draft.imported_products||[])].map(p=>[p.key,p]));
  for(const page of draft.pages){const identities=new Map();for(const key of Object.hasOwn(page,'product_keys')?page.product_keys:seed.pageProductKeys[page.page_id]||[]){
   const product=products.get(key);if(!product)fail('PAGE_PRODUCT_NOT_FOUND');
   if(page.page_id.startsWith('fc27-')&&product.product_ref?.game_id!=='1327')fail('PAGE_PRODUCT_GAME_MISMATCH');
   if(page.page_id.startsWith('fc27-')&&product.product_ref?.goods_id){const identity=canonical([product.product_ref.site_id,product.product_ref.game_id,product.product_ref.goods_id,product.platform.attribute_id||product.platform.code]);
    const logical=/^fc-(.+)-(ps|xbox|pc)$/.exec(key)?.[1]||key;
    if(identities.has(identity)&&identities.get(identity)!==logical)fail('DUPLICATE_PAGE_PRODUCT');identities.set(identity,logical);
   }
  }
  }
 }
 function previousDraft(current){
  if(!Number.isSafeInteger(current.revision)||current.revision<1||!['save','restore','model-import'].includes(current.last_operation?.kind))return null;
  const revision=current.revision-1,file=path.join(dir,'history',revision+'.json');
  try{
   const info=fs.lstatSync(file);if(!info.isFile()||info.isSymbolicLink())return null;
   const previous=readJSON(file);
   if(previous.revision!==revision||canonical(previous.published)!==canonical(current.published)
    ||Object.hasOwn(previous.draft,'imported_products')!==Object.hasOwn(current.draft,'imported_products')
    ||canonical(previous.draft.imported_products)!==canonical(current.draft.imported_products))return null;
   const draft=storedDraft(previous.draft);selectionScope(draft,seedNow(draft));
   const changed_fields=[...new Set([...Object.keys(current.draft),...Object.keys(draft)])].filter(key=>canonical(current.draft[key])!==canonical(draft[key])).sort();
   if(!changed_fields.length)return null;
   const changed_pages=draft.pages.filter(page=>canonical(page)!==canonical(current.draft.pages.find(p=>p.page_id===page.page_id))).map(page=>page.page_id);
   return {draft,summary:{revision,changed_fields,changed_pages}};
  }catch{return null;}
 }
 function finish(plan){
  const current=rawRead();
  if(current.revision!==plan.previous.revision&&current.last_operation?.operation_id!==plan.operation_id)fail('PENDING_OPERATION_CONFLICT',409);
  if(plan.snapshot){
   fs.mkdirSync(publicDir,{recursive:true,mode:0o755});
   if(fs.lstatSync(publicDir).isSymbolicLink())fail('INVALID_PUBLIC_DIRECTORY',503);
   // The management unit uses UMask=0077; only this sanitized projection is public.
   fs.chmodSync(publicDir,0o755);
   assets.publish(plan.snapshot.media_assets||{});
   const immutable=path.join(publicDir,plan.snapshot.release_id+'.json');
   if(fs.existsSync(immutable)&&canonical(readJSON(immutable))!==canonical(plan.snapshot))fail('IMMUTABLE_RELEASE_CONFLICT',409);
   if(!fs.existsSync(immutable))atomic(immutable,plan.snapshot);
   fs.chmodSync(immutable,0o644);
   atomic(path.join(publicDir,'current.json'),plan.snapshot);fs.chmodSync(path.join(publicDir,'current.json'),0o644);
   checkpoint('public-pointer');
  }
  atomic(path.join(dir,'history',plan.previous.revision+'.json'),plan.previous);
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
  const operation_id=uuid(request.operation_id),opFile=path.join(dir,'operations',operation_id+'.json'),hash=requestHash(request,kind);
  const current=read();if(request.revision!==current.revision)fail('REVISION_CONFLICT',409);
  const {result,snapshot}=action(current);
  result.last_operation={operation_id,hash,kind,...(kind==='restore'?{restore_revision:request.restore_revision}:{})};result.updated_by=user;result.updated_at=new Date().toISOString();
  const plan={operation_id,hash,previous:current,result,...(snapshot?{snapshot}:{})};
  // Freeze the exact payload and release before any externally visible publication step.
  atomic(pendingFile,plan);checkpoint('prepared');return finish(plan);
 }
 function recover(request,kind){uuid(request.operation_id);read();const file=path.join(dir,'operations',request.operation_id+'.json'),hash=requestHash(request,kind);if(fs.existsSync(file)){const prior=readJSON(file);if(prior.hash!==hash)fail('REQUEST_CONFLICT',409);return prior.result;}return null;}
 return {read,recoverImport:request=>recover(request,'import'),recoverModel:request=>recover(request,'model-import'),restoreCandidate:state=>previousDraft(state||read())?.summary||null,
  uploadAsset:(operationId,bytes,mime,user)=>assets.stage(operationId,bytes,mime,user),readAsset:assetId=>assets.read(assetId),
  save(request,user){return recover(request,'save')||operation(request,'save',user,current=>{
   preserveImports(current,request.draft);const draft=storedDraft(request.draft);selectionScope(draftOf(draft),seedNow(draft));
   return {result:{...current,revision:current.revision+1,draft}};
  });},
  importModel(request,user,detail){return recover(request,'model-import')||operation(request,'model-import',user,current=>{
   preserveImports(current,request.draft);const model=projectModelCard(detail);
   if(!['fc27-weekly','fc27-trio','fc27-sbc'].includes(request.page_id)||request.model_id!==model.model_id||request.kind!==model.kind)fail('MODEL_SCOPE_MISMATCH');
   const prior=current.draft.fc_models?.[model.key];if(prior&&canonical(prior)!==canonical(model))fail('MODEL_BINDING_CHANGED',409);
   const candidate=structuredClone(request.draft);candidate.fc_models={...(candidate.fc_models||{}),[model.key]:model};
   const keysFor=(layout,page)=>page==='fc27-weekly'?layout?.weekly||[]:page==='fc27-trio'?[...(layout?.trio||[]),...(layout?.bundles||[])]:page==='fc27-sbc'?[...(layout?.sbc||[]),...Object.values(layout?.routes||{}).flatMap(r=>[...(r.picks||[]),...(r.alternatives||[])])]:[];
   if(!keysFor(candidate.fc_layout,request.page_id).includes(model.key))fail('MODEL_TARGET_SELECTION_REQUIRED');
   if(!prior&&candidate.pages.some(p=>p.page_id!==request.page_id&&(keysFor(candidate.fc_layout,p.page_id).includes(model.key)||p.product_keys?.some(key=>key.startsWith('fc-'+model.key+'-')))))fail('MODEL_PAGE_SCOPE_MISMATCH');
   const draft=storedDraft(candidate);selectionScope(draftOf(draft),seedNow(draft));
   return {result:{...current,revision:current.revision+1,draft}};
  });},
  importProduct(request,user,detail){return recover(request,'import')||operation(request,'import',user,current=>{
   preserveImports(current,request.draft);
   const imported=projectImportedProduct(detail),ref=request.product_ref;
   if(!ref||typeof ref!=='object'||Array.isArray(ref)||Object.keys(ref).some(k=>!['site_id','game_id','goods_id','model_id','sku_id'].includes(k))
    ||['site_id','game_id','goods_id'].some(k=>ref[k]!==imported.product_ref[k])
    ||['model_id','sku_id'].some(k=>Object.hasOwn(ref,k)&&ref[k]!==imported.product_ref[k]))fail('IMPORTED_PRODUCT_IDENTITY_MISMATCH');
   const candidate=storedDraft(request.draft),seed=seedNow(candidate),draft=storedDraft(addImportedProduct(candidate,request.page_id,detail,seed));selectionScope(draftOf(draft),seed);
   return {result:{...current,revision:current.revision+1,draft}};
  });},
  restoreDraft(request,user){
   if(!request||Object.keys(request).some(k=>!['revision','operation_id','restore_revision'].includes(k))||!Number.isSafeInteger(request.restore_revision)||request.restore_revision<0)fail('INVALID_DRAFT_RESTORE');
   return recover(request,'restore')||operation(request,'restore',user,current=>{
    if(request.restore_revision!==current.revision-1)fail('RESTORE_REVISION_CONFLICT',409);
    const previous=previousDraft(current);if(!previous)fail('DRAFT_RESTORE_UNAVAILABLE',409);
    return {result:{...current,revision:current.revision+1,draft:previous.draft}};
   });
  },
  publish(request,user){return recover(request,'publish')||operation(request,'publish',user,current=>{
   const draft=draftOf(current.draft),revision=current.revision+1,release_id='campaign-preview-'+revision;
   const seed=seedNow(draft);selectionScope(draft,seed);
   const selected=Object.fromEntries(draft.pages.map(p=>[p.page_id,Object.hasOwn(p,'product_keys')?p.product_keys:seed.pageProductKeys[p.page_id]||[]]));
   const used=new Set(Object.values(selected).flat());
   const products=[...seed.seedProducts.map(p=>({...p,available:false})),...(draft.imported_products||[]).filter(p=>used.has(p.key))];
   const snapshot=createSnapshot({schema_version:1,publication_status:'published',release_id,source_revision:sourceRevision,
    config_hash:digest(canonical({draft,products,pageProductKeys:selected,fc_layout:seed.fc_layout??null})),rule_hash:digest(canonical(draft.pages.map(p=>p.benefit_refs))),products,seasonal_theme:draft.seasonal_theme,...(seed.fc_layout?{fc_layout:seed.fc_layout}:{}),...(seed.fc_models?{fc_models:seed.fc_models}:{}),media_assets:assets.manifest(draft),
    pages:draft.pages.map(p=>({activity_id:p.activity_id,page_id:p.page_id,path:p.path,title:p.title,
     description:p.description,default_language:p.default_language,social_image:p.social_image,...(Object.hasOwn(p,'media')?{media:p.media}:{}),rule_version:'preview-'+revision,benefit_binding_version:'unverified-'+revision,product_keys:selected[p.page_id],...pageDisplayFields({...p,product_keys:selected[p.page_id]}),
     active:p.preview_enabled,...(p.starts_at?{starts_at:p.starts_at}:{}),...(p.ends_at?{ends_at:p.ends_at}:{})}))});
   return {snapshot,result:{...current,revision,draft:current.draft,published:{release_id,config_hash:snapshot.config_hash,rule_hash:snapshot.rule_hash,mode:'preview',live_checkout:false,published_at:new Date().toISOString(),source_revision:sourceRevision,seasonal_theme:draft.seasonal_theme,pages:draft.pages.map(p=>({...p}))}}};
  })}
 };
}

export {validateDraft};
