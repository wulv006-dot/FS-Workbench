import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';
import {centerSeed} from '../center-seed.mjs';
import {initialLayout,validateLayout,previewCatalog,makeStore} from '../store.mjs';

const app=new URL('../../',import.meta.url),catalog=JSON.parse(fs.readFileSync(new URL('catalog.json',app),'utf8'));
const configBox={window:{}};vm.runInNewContext(fs.readFileSync(new URL('analytics-config.js',app),'utf8'),configBox);
const detail=()=>({product_ref:{site_id:'266',game_id:'1327',goods_id:'900000011',model_id:'900000012'},title:'Synthetic imported preview',
 platform_attribute_id:'21587',authoritative:false,checkout_enabled:false,quantity_observation:{minimum:null,raw_unit:null,raw_num:null}});
function fixture(t){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'canonical-editor-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const legacy=initialLayout(catalog),seen=[];
 const options={dir:path.join(dir,'center'),publicDir:path.join(dir,'public'),sourceRevision:'synthetic',validateFcLayout:layout=>validateLayout(layout,catalog),
  seedProvider:layout=>{seen.push(structuredClone(layout));return centerSeed(previewCatalog(catalog,layout??legacy),{products:[]});}};
 return {dir,options,legacy,seen,store:makeCenterStore(options)};
}

test('legacy FC fallback stays read-only until an explicit center save; subsequent publication uses that draft layout',t=>{
 const {store,dir,legacy,seen}=fixture(t);assert.equal(store.read().draft.fc_layout,undefined);assert.equal(fs.existsSync(path.join(dir,'center')),false);
 const draft=initialCenterDraft();draft.fc_layout=structuredClone(legacy);draft.fc_layout.weekly=draft.fc_layout.weekly.slice().reverse();
 const core=draft.fc_layout.defaultCore;draft.fc_layout.routes[core].picks=['170014917','185070945'];
 const body={revision:0,operation_id:randomUUID(),draft};const saved=store.save(body,'fixture');
 assert.deepEqual(saved.draft.fc_layout,validateLayout(draft.fc_layout,catalog));assert.deepEqual(seen.at(-1),saved.draft.fc_layout);
 assert.deepEqual(store.save(body,'fixture'),saved);assert.throws(()=>store.save({...body,operation_id:randomUUID()},'fixture'),{code:'REVISION_CONFLICT'});
 store.publish({revision:1,operation_id:randomUUID()},'fixture');const published=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json')));
 assert.deepEqual(published.fc_layout.weekly,draft.fc_layout.weekly);assert.deepEqual(published.fc_layout.routes[core].picks,['170014917','185070945']);
 assert.equal(fs.existsSync(path.join(dir,'state.json')),false);assert.equal(published.products.every(p=>p.available===false),true);
});

test('candidate FC layout is validated for save and import; import expands membership from the same candidate',t=>{
 const {store,legacy,seen}=fixture(t),draft=initialCenterDraft();draft.fc_layout=structuredClone(legacy);draft.fc_layout.weekly=['170014917'];
 const data=detail(),body={revision:0,operation_id:randomUUID(),draft,page_id:'fc27-weekly',product_ref:data.product_ref};
 const imported=store.importProduct(body,'fixture',data);assert.deepEqual(seen.at(-1).weekly,['170014917']);
 const keys=imported.draft.pages[0].product_keys,expectedFc=['170014917',...draft.fc_layout.bundles].flatMap(key=>['ps','xbox','pc'].map(code=>'fc-'+key+'-'+code));
 assert.equal(expectedFc.length,21,'one selected player and six configured fixed bundles each contribute exactly three platform references');assert.equal(new Set(expectedFc).size,21);
 assert.deepEqual(keys,[...expectedFc,imported.draft.imported_products[0].key],'import extends precisely the candidate player and shared configured bundles; no unrelated source products enter the page');
 const candidateSeed=centerSeed(previewCatalog(catalog,imported.draft.fc_layout),{products:[]});
 for(const page_id of ['fc27-weekly','fc27-trio','fc27-sbc']){const bundleRefs=candidateSeed.pageProductKeys[page_id].filter(ref=>draft.fc_layout.bundles.some(key=>ref.startsWith('fc-'+key+'-')));assert.deepEqual(bundleRefs,draft.fc_layout.bundles.flatMap(key=>['ps','xbox','pc'].map(code=>'fc-'+key+'-'+code)));assert.equal(new Set(bundleRefs).size,bundleRefs.length);}

 assert.deepEqual(imported.draft.fc_layout.weekly,['170014917']);assert.deepEqual(store.recoverImport(body),imported);
 const invalid=structuredClone(imported.draft);invalid.fc_layout.trio=['170014917'];
 assert.throws(()=>store.save({revision:1,operation_id:randomUUID(),draft:invalid},'fixture'),{code:'INVALID_FC_LAYOUT'});
 assert.throws(()=>store.importProduct({...body,revision:1,operation_id:randomUUID(),draft:invalid},'fixture',data),{code:'INVALID_FC_LAYOUT'});
 const invalidImport=structuredClone(imported.draft);invalidImport.fc_layout.sbc=[];
 assert.throws(()=>store.importProduct({...body,revision:1,operation_id:randomUUID(),draft:invalidImport},'fixture',data),{code:'INVALID_FC_LAYOUT'});
});

test('legacy draft and published snapshot are unchanged by reads, and validation cannot replace a prior snapshot',t=>{
 const {store,dir,options,legacy}=fixture(t);store.save({revision:0,operation_id:randomUUID(),draft:initialCenterDraft()},'fixture');
 store.publish({revision:1,operation_id:randomUUID()},'fixture');const before=fs.readFileSync(path.join(dir,'public/current.json'));
 const reopened=makeCenterStore(options);assert.equal(reopened.read().draft.fc_layout,undefined);assert.deepEqual(fs.readFileSync(path.join(dir,'public/current.json')),before);
 const valid=structuredClone(reopened.read().draft);valid.fc_layout=structuredClone(legacy);valid.fc_layout.weekly.reverse();
 reopened.save({revision:2,operation_id:randomUUID(),draft:valid},'fixture');assert.deepEqual(fs.readFileSync(path.join(dir,'public/current.json')),before);
 const draft=structuredClone(reopened.read().draft);draft.fc_layout={...legacy,defaultCore:'not-selected'};
 assert.throws(()=>reopened.save({revision:3,operation_id:randomUUID(),draft},'fixture'),{code:'INVALID_FC_LAYOUT'});
 assert.deepEqual(fs.readFileSync(path.join(dir,'public/current.json')),before);assert.equal(reopened.read().revision,3);
});

test('canonical management route projects legacy layout without writing it and preserves authentication, CAS and report state',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'canonical-route-')),legacyStore=makeStore(dir,catalog,configBox.window.FC_ANALYTICS_CONFIG.registry),legacy=legacyStore.read();
 fs.writeFileSync(path.join(dir,'state.json'),JSON.stringify({...legacy,revision:7,updatedBy:'legacy-fixture'}));const before=fs.readFileSync(path.join(dir,'state.json'));
 const originalFetch=globalThis.fetch,envKeys=['CAMPAIGN_DATA','CAMPAIGN_PUBLIC_RELEASE_DIR','CAMPAIGN_ORIGIN'],previous=Object.fromEntries(envKeys.map(k=>[k,process.env[k]]));
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');process.env.CAMPAIGN_ORIGIN='http://localhost';
 globalThis.fetch=async(url,options)=>{
  if(String(url)==='http://127.0.0.1:8895/verify?group=dashboard'){
   const role=options.headers.Cookie==='admin'?'admin':options.headers.Cookie==='reader'?'reader':null;
   return new Response(null,{status:role?200:401,headers:role?{'x-auth-user':'fixture','x-auth-role':role}:{}});
  }return originalFetch(url,options);
 };
 let server;
 try{
  ({server}=await import('../production-server.mjs'));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/',headers={Cookie:'admin'};
  assert.equal((await originalFetch(base+'center.html',{redirect:'manual'})).status,401);
  const redirect=await originalFetch(base+'center.html',{headers,redirect:'manual'});assert.equal(redirect.status,302);assert.equal(redirect.headers.get('Location'),'/dashboard/analytics/campaigns/analytics/products.html');
  assert.equal((await originalFetch(base+'center.js',{headers})).status,404);
  const state=await (await originalFetch(base+'api/center',{headers})).json();assert.equal(Object.hasOwn(state.draft,'fc_layout'),false);assert.deepEqual(state.effective_fc_layout,validateLayout(legacy.layout,catalog));assert.equal(fs.existsSync(path.join(dir,'center')),false);
  assert.deepEqual(Object.keys(state.fc_catalog).sort(),['products','sbc','trio']);assert(Object.values(state.fc_catalog.products).every(p=>Object.keys(p).every(k=>['key','title','name','kind','version'].includes(k))));
  const draft=structuredClone(state.draft);draft.fc_layout=structuredClone(state.effective_fc_layout);draft.fc_layout.weekly=['170014917'];const body={revision:state.revision,operation_id:randomUUID(),draft};
  const postHeaders={Cookie:'admin',Origin:'http://localhost','Content-Type':'application/json','X-CSRF-Token':state.csrf};
  assert.equal((await originalFetch(base+'api/center',{method:'POST',headers:{...postHeaders,Cookie:'reader'},body:JSON.stringify(body)})).status,403);
  assert.equal((await originalFetch(base+'api/center',{method:'POST',headers:{...postHeaders,'X-CSRF-Token':'wrong'},body:JSON.stringify(body)})).status,403);
  assert.equal((await originalFetch(base+'api/center',{method:'POST',headers:postHeaders,body:JSON.stringify(body)})).status,200);
  assert.equal((await originalFetch(base+'api/center',{method:'POST',headers:postHeaders,body:JSON.stringify({...body,operation_id:randomUUID()})})).status,409);
  assert.deepEqual(fs.readFileSync(path.join(dir,'state.json')),before);
  const reportConfig=await (await originalFetch(base+'api/config',{headers})).json();assert.equal(reportConfig.revision,7);assert.deepEqual(reportConfig.layout,legacy.layout);assert.deepEqual(reportConfig.registry,JSON.parse(JSON.stringify(legacy.registry)));
 }finally{
  if(server)await new Promise(resolve=>server.close(resolve));globalThis.fetch=originalFetch;for(const k of envKeys){if(previous[k]===undefined)delete process.env[k];else process.env[k]=previous[k];}fs.rmSync(dir,{recursive:true,force:true});
 }
});
