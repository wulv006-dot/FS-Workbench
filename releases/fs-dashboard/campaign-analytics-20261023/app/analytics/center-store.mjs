import {projectModelOptions} from '../runtime/model-options.mjs';
import {projectHalloween,halloweenProductKeys} from '../runtime/halloween-contract.mjs';
import fs from 'node:fs';
import path from 'node:path';
import {atomic} from './store.mjs';
import {canonical,digest,createSnapshot,fail,presentationFields,projectPreviewProduct,id,pageDisplayFields,pageCopyFields,COPY_FIELDS} from '../runtime/snapshot.mjs';
import {addImportedProduct,projectImportedProduct} from './center-seed.mjs';
import {projectModels,projectModelCard} from '../runtime/model-cards.mjs';
import {projectMedia} from '../runtime/media-contract.mjs';
import {makeMediaStore} from './media-store.mjs';

const pages=[
 ['fc27-weekly','fc27-season2','Weekly-Scout.html','每周好卡'],
 ['fc27-sbc','fc27-season2','Sbc-Companions.html','SBC 核心搭档'],
 ['fc27-trio','fc27-season2','Player-Trio.html','Player Trio'],
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
   ...selection,...pageDisplayFields({...p,path:route}),...pageCopyFields({...p,path:route}),...(Object.hasOwn(p,'media')?{media:projectMedia(p.media)}:{}),
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
 return {pages:result,...(Object.hasOwn(input,'halloween')?{halloween:projectHalloween(input.halloween)}:{}),...imports,...models,...layout,seasonal_theme:input.seasonal_theme,integration_mode:'preview'};
}
export function initialCenterDraft(){return {pages:pages.map(([page_id,activity_id,route,title])=>({page_id,activity_id,path:route,title,description:'',preview_enabled:true,starts_at:null,ends_at:null,benefit_refs:[],default_language:'original',social_image:'original'})),seasonal_theme:'halloween',integration_mode:'preview'};}

// Validation and storage have different jobs: validate the supplied known contract,
// then retain its exact legal shape instead of persisting presentation defaults.
function preserveDraftShape(input,options){
 const record=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(k=>keys.includes(k));
 if(!record(input,['pages','seasonal_theme','integration_mode','fc_layout','fc_models','imported_products','halloween'])||!Array.isArray(input.pages))fail('INVALID_CAMPAIGN_CONFIG');
 if(Object.hasOwn(input,'integration_mode')&&input.integration_mode!=='preview')fail('INVALID_CAMPAIGN_CONFIG');
 for(const page of input.pages){
  if(!record(page,['page_id','activity_id','path','title','description','preview_enabled','starts_at','ends_at','benefit_refs','default_language','social_image','product_keys','product_roles','sbc_companions','media','copy']))fail('INVALID_CAMPAIGN_CONFIG');
  const expected=pages.find(row=>row[0]===page.page_id);if(!expected)fail('INVALID_CAMPAIGN_CONFIG');
  if(Object.hasOwn(page,'activity_id')&&page.activity_id!==expected[1]||Object.hasOwn(page,'path')&&page.path!==expected[2])fail('INVALID_CAMPAIGN_CONFIG');
  for(const key of ['title','description'])if(Object.hasOwn(page,key))safeText(page[key],key==='title'?160:320);
  if(Object.hasOwn(page,'preview_enabled')&&typeof page.preview_enabled!=='boolean')fail('INVALID_CAMPAIGN_CONFIG');
  for(const key of ['starts_at','ends_at'])if(Object.hasOwn(page,key)&&page[key]!==null&&typeof page[key]!=='string')fail('INVALID_CAMPAIGN_DATES');
  for(const key of ['default_language','social_image'])if(Object.hasOwn(page,key)&&typeof page[key]!=='string')fail('INVALID_PRESENTATION_CONFIG');
  if(Object.hasOwn(page,'copy'))pageCopyFields({...page,path:expected[2]});
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
   try{for(const core of Object.keys(layout.routes).filter(key=>!layout.sbc.includes(key)))options.validateFcLayout({...layout,sbc:[core],defaultCore:core,routes:{[core]:layout.routes[core]}},input.fc_models||{});}
   catch(error){if(error.status)throw error;fail('INVALID_FC_LAYOUT');}
  }
 }
 validateDraft(input,options);
 return structuredClone(input);
}

export function makeCenterStore({dir,publicDir,sourceRevision,seedProducts=[],pageProductKeys={},fc_layout,seedProvider,validateFcLayout,nativeCheckoutProvider=()=>({status:'unconfigured'}),checkpoint=()=>{}}){
 const stateFile=path.join(dir,'state.json'),pendingFile=path.join(dir,'pending.json');
 const rawRead=()=>fs.existsSync(stateFile)?JSON.parse(fs.readFileSync(stateFile,'utf8')):{revision:0,draft:initialCenterDraft(),updated_at:null,updated_by:null,published:null};
 const readJSON=file=>JSON.parse(fs.readFileSync(file,'utf8'));
 const assets=makeMediaStore({dir:path.join(dir,'media'),publicDir,operationsDir:path.join(dir,'operations')});
 const seedNow=draft=>seedProvider?seedProvider(draft?.fc_layout,draft?.fc_models||{}):{seedProducts,pageProductKeys,...(draft?.fc_layout||fc_layout?{fc_layout:draft?.fc_layout||fc_layout}:{})};
 const draftOf=input=>validateDraft(input,{validateFcLayout});
 const storedDraft=input=>preserveDraftShape(input,{validateFcLayout});
 const requestHash=(request,kind)=>digest(canonical({kind,revision:request.revision,draft:request.draft??null,
  ...(kind==='import'?{page_id:request.page_id,product_ref:request.product_ref}: {}),...(kind==='model-import'?{page_id:request.page_id,model_id:request.model_id,model_kind:request.kind}:{}),...(kind==='restore'?{restore_revision:request.restore_revision}:{}),...(Object.hasOwn(request,'model_imports')?{model_imports:request.model_imports}:{}),...(Object.hasOwn(request,'product_imports')?{product_imports:request.product_imports}:{}),...(Object.hasOwn(request,'model_refresh_digest')?{model_refresh_digest:request.model_refresh_digest}:{})}));
 function preserveImports(current,draft){
  if(canonical(current.draft.imported_products||[])!==canonical(draft?.imported_products||[]))fail('IMPORTED_PRODUCTS_SERVER_OWNED');
  if(Object.hasOwn(current.draft,'fc_models')!==Object.hasOwn(draft||{},'fc_models')||canonical(current.draft.fc_models)!==canonical(draft?.fc_models))fail('MODELS_SERVER_OWNED');
 }
 function selectionScope(draft,seed){
  assets.manifest(draft);
  const products=new Map([...seed.seedProducts,...(draft.imported_products||[])].map(p=>[p.key,p]));
  if(draft.halloween)halloweenProductKeys(draft.halloween,[...products.values()]);
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
  result.last_operation={operation_id,hash,kind,...(kind==='restore'?{restore_revision:request.restore_revision}:{}),...(Object.hasOwn(request,'model_imports')?{model_imports:request.model_imports}:{}),...(Object.hasOwn(request,'model_refresh_digest')?{model_refresh_digest:request.model_refresh_digest}:{})};result.updated_by=user;result.updated_at=new Date().toISOString();
  const plan={operation_id,hash,previous:current,result,...(snapshot?{snapshot}:{})};
  // Freeze the exact payload and release before any externally visible publication step.
  atomic(pendingFile,plan);checkpoint('prepared');return finish(plan);
 }
 function recover(request,kind){uuid(request.operation_id);read();const file=path.join(dir,'operations',request.operation_id+'.json'),hash=requestHash(request,kind);if(fs.existsSync(file)){const prior=readJSON(file);if(prior.hash!==hash)fail('REQUEST_CONFLICT',409);return prior.result;}return null;}
 function candidate(current,request,details=[],productDetails=[],{refreshModels=false}={}){
  if(Object.hasOwn(request,'model_refresh_digest')&&(!refreshModels||request.model_refresh_digest!==digest(canonical(details))))fail('MODEL_REFRESH_SERVER_OWNED');
  if(refreshModels&&!Object.hasOwn(request,'model_refresh_digest'))fail('MODEL_REFRESH_DIGEST_REQUIRED');
  preserveImports(current,request.draft);const draft=structuredClone(request.draft),imports=Object.hasOwn(request,'model_imports')?request.model_imports:[];
  if(!Array.isArray(imports)||imports.length>33||details.length!==imports.length)fail('INVALID_MODEL_IMPORTS');
  const seen=new Set();for(let i=0;i<imports.length;i++){
   const entry=imports[i],model=projectModelCard(details[i]);if(!entry)fail('INVALID_MODEL_IMPORTS');const scope=entry.page_id+':'+entry.model_id;
   if(Object.keys(entry).some(k=>!['page_id','model_id','kind'].includes(k))||!['fc27-weekly','fc27-sbc','fc27-trio'].includes(entry.page_id)||entry.model_id!==model.model_id||entry.kind!==model.kind||seen.has(scope))fail('INVALID_MODEL_IMPORTS');seen.add(scope);
   const prior=draft.fc_models?.[model.key];if(prior&&canonical(prior)!==canonical(model)&&(!refreshModels||['site_id','game_id','model_id','kind'].some(k=>prior[k]!==model[k])))fail('MODEL_BINDING_CHANGED',409);
   const layout=draft.fc_layout,keys=entry.page_id==='fc27-weekly'?layout?.weekly:entry.page_id==='fc27-trio'?[...(layout?.trio||[]),...(layout?.bundles||[])]:[...(layout?.sbc||[]),...Object.values(layout?.routes||{}).flatMap(row=>[...(row.picks||[]),...(row.alternatives||[])])];
   if(!keys?.includes(model.key))fail('MODEL_TARGET_SELECTION_REQUIRED');
   draft.fc_models={...(draft.fc_models||{}),[model.key]:model};
  }
  const productImports=Object.hasOwn(request,'product_imports')?request.product_imports:[];
  if(!Array.isArray(productImports)||productImports.length>30||productDetails.length!==productImports.length)fail('INVALID_PRODUCT_IMPORTS');
  const seenProducts=new Set();for(let i=0;i<productImports.length;i++){
   const entry=productImports[i],product=projectImportedProduct(productDetails[i]),ref=entry?.product_ref,page=draft.pages?.find(p=>p.page_id===entry?.page_id);
   if(!entry||Object.keys(entry).some(k=>!['page_id','product_ref'].includes(k))||!page||!ref||typeof ref!=='object'||Array.isArray(ref)||Object.keys(ref).some(k=>!['site_id','game_id','goods_id','model_id','sku_id'].includes(k))
    ||['site_id','game_id','goods_id'].some(k=>ref[k]!==product.product_ref[k])||['model_id','sku_id'].some(k=>Object.hasOwn(ref,k)&&ref[k]!==product.product_ref[k]))fail('IMPORTED_PRODUCT_IDENTITY_MISMATCH');
   const scope=entry.page_id+':'+product.key;if(seenProducts.has(scope))fail('INVALID_PRODUCT_IMPORTS');seenProducts.add(scope);
   if(!page.product_keys?.includes(product.key))fail('PRODUCT_TARGET_SELECTION_REQUIRED');
   const prior=draft.imported_products?.find(p=>p.key===product.key);if(prior&&canonical(prior)!==canonical(product))fail('IMPORTED_BINDING_CHANGED',409);
   if(!prior)(draft.imported_products||=[]).push(product);
  }
  const stored=storedDraft(draft);selectionScope(draftOf(stored),seedNow(stored));return stored;
 }
 function snapshotFor(draft,revision,native_checkout){
  const release_id='campaign-preview-'+revision;
   const seed=seedNow(draft);selectionScope(draft,seed);
   const selected=Object.fromEntries(draft.pages.map(p=>[p.page_id,Object.hasOwn(p,'product_keys')?p.product_keys:seed.pageProductKeys[p.page_id]||[]]));
   if(draft.halloween)selected['seasonal-vault']=[...new Set([...selected['seasonal-vault'],...halloweenProductKeys(draft.halloween,[...seed.seedProducts,...(draft.imported_products||[])])])];
   const used=new Set(Object.values(selected).flat());
   const products=seed.seedProducts.map(p=>({...p,available:false}));
   for(const imported of (draft.imported_products||[]).filter(p=>used.has(p.key))){
    const index=products.findIndex(p=>p.key===imported.key);
    if(index<0){products.push(imported);continue;}
    const trusted=products[index];
    if(canonical(trusted.product_ref)!==canonical(imported.product_ref)||canonical(trusted.platform)!==canonical(imported.platform))fail('PROVIDER_IMPORT_IDENTITY_CONFLICT');
    // Upgrade only the publication projection. Preserve the stored draft's raw
    // shape/history; no preview-only null quantity overwrites trusted options.
    if(typeof imported.title==='string'&&!/[\u3400-\u9fff]/u.test(imported.title))products[index]={...trusted,title:imported.title};
   }
   const seasonalKeys=new Set(selected['seasonal-vault']);
   const scopedOptions=seed.seasonal_model_contracts?Object.fromEntries(Object.entries(seed.seasonal_model_contracts).flatMap(([id,source])=>{
    const combinations=source.combinations.filter(c=>seasonalKeys.has(c.product_key));
    if(!combinations.length)return [];
    // Legacy per-product selection may intentionally omit a platform. Do not
    // expose its price or reinterpret the remaining row as the original default.
    return [[id,{...source,combinations,ordering_verified:source.ordering_verified===true&&combinations.length===source.combinations.length}]];
   })):null;
   const modelOptions=scopedOptions?projectModelOptions(scopedOptions,products):null;
   return createSnapshot({schema_version:1,publication_status:'published',release_id,source_revision:sourceRevision,
    config_hash:digest(canonical({draft,products,native_checkout,pageProductKeys:selected,fc_layout:seed.fc_layout??null,...(modelOptions?{seasonal_model_contracts:modelOptions}:{})})),native_checkout,rule_hash:digest(canonical(draft.halloween?{benefits:draft.pages.map(p=>p.benefit_refs),halloween:draft.halloween}:draft.pages.map(p=>p.benefit_refs))),products,...(modelOptions?{seasonal_model_contracts:modelOptions}:{}),...(draft.halloween?{halloween:draft.halloween}:{}),seasonal_theme:draft.seasonal_theme,...(seed.fc_layout?{fc_layout:seed.fc_layout}:{}),...(seed.fc_models?{fc_models:seed.fc_models}:{}),media_assets:assets.manifest(draft),
    pages:draft.pages.map(p=>({activity_id:p.activity_id,page_id:p.page_id,path:p.path,title:p.title,
     description:p.description,default_language:p.default_language,social_image:p.social_image,...(Object.hasOwn(p,'media')?{media:p.media}:{}),...pageCopyFields({...p,product_keys:selected[p.page_id]}),rule_version:'preview-'+revision,benefit_binding_version:'unverified-'+revision,product_keys:selected[p.page_id],...pageDisplayFields({...p,product_keys:selected[p.page_id]}),
     active:p.preview_enabled,...(p.starts_at?{starts_at:p.starts_at}:{}),...(p.ends_at?{ends_at:p.ends_at}:{})}))});
 }
 return {read,recoverSave:request=>recover(request,'save'),recoverPublish:request=>recover(request,'publish'),recoverImport:request=>recover(request,'import'),recoverModel:request=>recover(request,'model-import'),restoreCandidate:state=>previousDraft(state||read())?.summary||null,
  uploadAsset:(operationId,bytes,mime,user)=>assets.stage(operationId,bytes,mime,user),readAsset:assetId=>assets.read(assetId),
  preview(request,details=[],productDetails=[]){if(fs.existsSync(pendingFile))fail('PENDING_OPERATION_RECOVERY_REQUIRED',409);const current=rawRead();if(request.revision!==current.revision)fail('REVISION_CONFLICT',409);const draft=draftOf(candidate(current,request,details,productDetails));return snapshotFor(draft,current.revision+1,{status:'unconfigured'});},
  save(request,user,details=[],productDetails=[],trustedOptions={}){return recover(request,'save')||operation(request,'save',user,current=>{
   const draft=candidate(current,request,details,productDetails,trustedOptions);
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
  publish(request,user,details=[],productDetails=[]){return recover(request,'publish')||operation(request,'publish',user,current=>{
   const stored=Object.hasOwn(request,'draft')?candidate(current,request,details,productDetails):current.draft;
   if(!Object.hasOwn(request,'draft')&&(request.model_imports?.length||request.product_imports?.length))fail('INVALID_PENDING_IMPORTS');
   const draft=draftOf(stored),revision=current.revision+1,release_id='campaign-preview-'+revision,snapshot=snapshotFor(draft,revision,nativeCheckoutProvider());
   return {snapshot,result:{...current,revision,draft:stored,published:{release_id,config_hash:snapshot.config_hash,rule_hash:snapshot.rule_hash,mode:'preview',live_checkout:false,published_at:new Date().toISOString(),source_revision:sourceRevision,seasonal_theme:draft.seasonal_theme,pages:draft.pages.map(p=>({...p}))}}};
  })}
 };
}

export {validateDraft};
