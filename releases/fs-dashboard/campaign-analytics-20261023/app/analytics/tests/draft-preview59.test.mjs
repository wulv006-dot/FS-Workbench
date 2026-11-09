import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';import {centerSeed} from '../center-seed.mjs';import {initialLayout,validateLayout,previewCatalog} from '../store.mjs';import {effectiveFcCatalog} from '../../runtime/model-cards.mjs';
const catalog=JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url)));
const model=()=>({key:'model-266-1327-900059',site_id:'266',game_id:'1327',model_id:'900059',kind:'player',title:'Synthetic pending model',version_label:null,image_url:null,image_provenance:null,site_association:'observed',verification_scope:'catalog_identity_only',available:false,authoritative:false,checkout_enabled:false,platforms:Object.fromEntries(['ps','xbox','pc'].map(code=>[code,{state:'unknown',product_ref:null,observed_quantity:null}]))});
const product=()=>({product_ref:{site_id:'266',game_id:'891',goods_id:'9000591',model_id:'9000592'},title:'Synthetic pending product',platform_attribute_id:null,authoritative:false,checkout_enabled:false,quantity_observation:{minimum:null,raw_unit:null,raw_num:null}});
const productKey='admin-266-891-9000591-unknown';
function setup(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'draft-preview59-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const options={dir:path.join(dir,'center'),publicDir:path.join(dir,'published'),sourceRevision:'synthetic59',validateFcLayout:(layout,models)=>validateLayout(layout,effectiveFcCatalog(catalog,models)),seedProvider:(layout,models)=>centerSeed(previewCatalog(effectiveFcCatalog(catalog,models),layout??initialLayout(catalog)),{products:[]})};return {dir,options,store:makeCenterStore(options)};}
const body=()=>{const draft=initialCenterDraft();draft.pages[0].title='Unsaved whole page';draft.fc_layout=structuredClone(initialLayout(catalog));draft.fc_layout.weekly=[model().key];return {revision:0,draft,page_id:'fc27-weekly',model_imports:[{page_id:'fc27-weekly',model_id:'900059',kind:'player'}]};};
test('whole candidate preview shares the publication projection but creates no state/history/release or native authorization',t=>{
 const {dir,options}=setup(t),store=makeCenterStore({...options,nativeCheckoutProvider:()=>{throw Error('Preview must not read native authorization');}}),request=body(),snapshot=store.preview(request,[model()]);
 assert.equal(snapshot.pages[0].title,'Unsaved whole page');assert.deepEqual(snapshot.fc_layout.weekly,[model().key]);assert.equal(snapshot.products.filter(p=>p.model_card_key===model().key).length,3);assert.deepEqual(snapshot.native_checkout,{status:'unconfigured'});
 assert.equal(fs.existsSync(options.dir),false);assert.equal(fs.existsSync(options.publicDir),false);assert.deepEqual(store.read().draft,initialCenterDraft());
 assert.throws(()=>store.preview({...request,revision:1},[model()]),{code:'REVISION_CONFLICT'});assert.equal(fs.readdirSync(dir).length,0);
});
test('legal omitted legacy page fields use identical preview/publication defaults without materializing stored raw draft',t=>{
 const {store,options}=setup(t),draft=initialCenterDraft();for(const field of ['title','activity_id','path'])delete draft.pages[0][field];const raw=structuredClone(draft),request={revision:0,draft,page_id:'fc27-weekly'};
 const preview=store.preview(request);assert.equal(fs.existsSync(options.dir),false);assert.deepEqual(request.draft,raw);
 const published=store.publish({...request,operation_id:randomUUID()},'synthetic');assert.deepEqual(published.draft,raw);assert.deepEqual(JSON.parse(fs.readFileSync(path.join(options.publicDir,'current.json'))),preview);
});
test('one atomic candidate publication resolves all pending facts before CAS and freezes same-ID replay',t=>{
 const {store,options}=setup(t),request={...body(),operation_id:randomUUID()};const wrong=model();wrong.kind='bundle';assert.throws(()=>store.publish(request,'synthetic',[wrong]));assert.equal(store.read().revision,0);assert.equal(fs.existsSync(options.publicDir),false);
 const saved=store.publish(request,'synthetic',[model()]);assert.equal(saved.revision,1);assert.equal(saved.draft.fc_models[model().key].title,model().title);assert.equal(saved.draft.pages[0].title,'Unsaved whole page');assert.deepEqual(store.recoverPublish(request),saved);
 assert.deepEqual(store.publish(request,'synthetic'),saved);assert.throws(()=>store.publish({...request,model_imports:[]},'synthetic'),{code:'REQUEST_CONFLICT'});assert.throws(()=>store.save({...request,operation_id:randomUUID()},'synthetic',[model()]),{code:'REVISION_CONFLICT'});
 const published=JSON.parse(fs.readFileSync(path.join(options.publicDir,'current.json')));assert.deepEqual(published.fc_layout.weekly,[model().key]);assert(published.products.every(p=>p.available===false));
});
test('pending product references share preview/save/publish and original receipts without trusting browser metadata',t=>{
 const {store,options}=setup(t),request=body();request.product_imports=[{page_id:'seasonal-vault',product_ref:product().product_ref}];request.draft.pages[3].product_keys=[productKey];
 const preview=store.preview(request,[model()],[product()]);assert.equal(preview.products.find(p=>p.key===productKey).quantity,null);assert.equal(fs.existsSync(options.dir),false);assert.equal(fs.existsSync(options.publicDir),false);
 const drift=product();drift.platform_attribute_id='21587';assert.throws(()=>store.save({...request,operation_id:randomUUID()},'synthetic',[model()],[drift]),{code:'PRODUCT_TARGET_SELECTION_REQUIRED'});assert.equal(store.read().revision,0);
 const saved=store.save({...request,operation_id:randomUUID()},'synthetic',[model()],[product()]);assert.equal(saved.revision,1);assert.equal(saved.draft.imported_products[0].available,false);assert.equal(saved.draft.imported_products[0].quantity,null);
 const next={revision:1,draft:structuredClone(saved.draft),product_imports:request.product_imports,operation_id:randomUUID()},changed=product();changed.title='Changed upstream fact';assert.throws(()=>store.publish(next,'synthetic',[],[changed]),{code:'IMPORTED_BINDING_CHANGED'});assert.equal(store.read().revision,1);
 const published=store.publish(next,'synthetic',[],[product()]);assert.equal(published.revision,2);assert.deepEqual(store.recoverPublish(next),published);assert.deepEqual(store.publish(next,'synthetic'),published);assert.throws(()=>store.publish({...next,product_imports:[]},'synthetic'),{code:'REQUEST_CONFLICT'});
 const output=JSON.parse(fs.readFileSync(path.join(options.publicDir,'current.json')));assert(output.pages.find(p=>p.page_id==='seasonal-vault').product_keys.includes(productKey));assert.equal(output.products.find(p=>p.key===productKey).available,false);
});
test('management preview URL is authenticated, read-only, expiring and renders the unsaved page through actual renderer',async t=>{
 const {dir}=setup(t),priorFetch=globalThis.fetch,names=['CAMPAIGN_DATA','CAMPAIGN_PUBLIC_RELEASE_DIR','CAMPAIGN_ORIGIN','CAMPAIGN_PYTHON','CAMPAIGN_BACKEND_BRIDGE'],before=Object.fromEntries(names.map(key=>[key,process.env[key]])),bridge=path.join(dir,'synthetic.cjs');fs.writeFileSync(bridge,'process.stdin.resume();process.stdin.on("end",()=>process.stdout.write('+JSON.stringify(JSON.stringify({status:'ok',data:{model:model(),product:product()}}))+'));');
 Object.assign(process.env,{CAMPAIGN_DATA:path.join(dir,'http'),CAMPAIGN_PUBLIC_RELEASE_DIR:path.join(dir,'public'),CAMPAIGN_ORIGIN:'http://127.0.0.1',CAMPAIGN_PYTHON:process.execPath,CAMPAIGN_BACKEND_BRIDGE:bridge});
 globalThis.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:options.headers.Cookie==='synthetic-admin'?200:401,headers:options.headers.Cookie==='synthetic-admin'?{'x-auth-user':'synthetic','x-auth-role':'admin'}:{}}):priorFetch(url,options);
 const {server}=await import('../production-server.mjs');await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port,base=origin+'/dashboard/analytics/campaigns/analytics/';
 try{
  const state=await(await priorFetch(base+'api/center',{headers:{Cookie:'synthetic-admin'}})).json(),headers={Cookie:'synthetic-admin',Origin:'http://127.0.0.1','Content-Type':'application/json','X-CSRF-Token':state.csrf},request=body();request.product_imports=[{page_id:'seasonal-vault',product_ref:product().product_ref}];request.draft.pages[3].product_keys=[productKey];
  assert.equal((await priorFetch(base+'api/center/preview',{method:'POST',headers:{...headers,'X-CSRF-Token':'bad'},body:JSON.stringify(request)})).status,403);
  // A same-revision persisted proposal must not make malformed drafts hash(undefined).
  const proposalDir=path.join(dir,'http/center/weekly-commerce');fs.mkdirSync(proposalDir,{recursive:true});
  fs.writeFileSync(path.join(proposalDir,randomUUID()+'.json'),JSON.stringify({owner:'synthetic',revision:0,created_at:new Date().toISOString()}),{mode:0o600});
  for(const draft of [undefined,null,'invalid',[],42]){
   const invalid=await priorFetch(base+'api/center/preview',{method:'POST',headers,body:JSON.stringify({revision:0,page_id:'fc27-weekly',draft})});
   assert([400,422].includes(invalid.status),'invalid draft status '+invalid.status);
  }
  for(const name of fs.readdirSync(proposalDir))fs.unlinkSync(path.join(proposalDir,name));
  const response=await priorFetch(base+'api/center/preview',{method:'POST',headers,body:JSON.stringify(request)});assert.equal(response.status,200);const preview=await response.json();assert.match(preview.preview_url,/analytics\/preview\/[a-f0-9]{48}\/Weekly-Scout.html$/);
  assert.equal((await priorFetch(origin+preview.preview_url)).status,401);const page=await(await priorFetch(origin+preview.preview_url,{headers})).text();assert(page.includes('Unsaved whole page'));assert(page.includes('Unsaved draft preview'));assert(page.includes('data-campaign-runtime='));
  const root=preview.preview_url.replace('Weekly-Scout.html',''),config=await(await priorFetch(origin+root+'api/campaign/config',{headers})).json();assert.deepEqual(config.native_checkout,{status:'unconfigured'});assert.equal(config.live_checkout,false);assert.equal(config.fc_models[model().key].title,model().title);assert.equal(config.products.find(p=>p.key===productKey).title,product().title);
  const projected=await(await priorFetch(origin+root+'catalog.js',{headers})).text();assert(projected.includes(model().key));assert.equal((await priorFetch(origin+root+'native-code-handoff.js',{headers})).status,200);assert.equal((await priorFetch(origin+root+'seasonal/runtime-bridge.js',{headers})).status,200);
  assert.equal((await priorFetch(origin+root+'api/campaign/intents',{method:'POST',headers,body:'{}'})).status,404);assert.equal(fs.existsSync(path.join(dir,'http/center/state.json')),false);assert.equal(fs.existsSync(path.join(dir,'public/current.json')),false);
  const now=Date.now;t.mock.method(Date,'now',()=>now()+11*60*1000);assert.equal((await priorFetch(origin+preview.preview_url,{headers})).status,404);t.mock.restoreAll();
 }finally{await new Promise(r=>server.close(r));globalThis.fetch=priorFetch;for(const key of names)if(before[key]===undefined)delete process.env[key];else process.env[key]=before[key];}
});
