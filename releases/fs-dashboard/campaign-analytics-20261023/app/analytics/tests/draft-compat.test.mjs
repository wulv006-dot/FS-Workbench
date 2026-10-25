import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';
import {centerSeed} from '../center-seed.mjs';
import {initialLayout,previewCatalog,validateLayout} from '../store.mjs';

const app=new URL('../../',import.meta.url),catalog=JSON.parse(fs.readFileSync(new URL('catalog.json',app),'utf8'));
const configBox={window:{}};vm.runInNewContext(fs.readFileSync(new URL('analytics-config.js',app),'utf8'),configBox);
const oldDraft=()=>{const draft=initialCenterDraft();for(const p of draft.pages){delete p.default_language;delete p.social_image;}
 delete draft.pages[1].benefit_refs;draft.pages[0].starts_at='2026-10-25T09:00:00+08:00';draft.pages[0].ends_at='';return draft;};
function fixture(t){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'draft-compat-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const options={dir:path.join(dir,'center'),publicDir:path.join(dir,'published'),sourceRevision:'synthetic',validateFcLayout:layout=>validateLayout(layout,catalog),
  seedProvider:layout=>centerSeed(previewCatalog(catalog,layout??initialLayout(catalog)),{products:[]})};
 const state={revision:2,draft:oldDraft(),published:{release_id:'synthetic-existing-release',config_hash:'a'.repeat(64)},updated_at:'2026-10-25T01:00:00Z',updated_by:'fixture'};
 fs.mkdirSync(options.dir,{recursive:true});fs.writeFileSync(path.join(options.dir,'state.json'),JSON.stringify(state));
 fs.mkdirSync(options.publicDir,{recursive:true});fs.writeFileSync(path.join(options.publicDir,'current.json'),'synthetic-public-bytes');
 return {dir,options,state,store:makeCenterStore(options),publicBytes:()=>fs.readFileSync(path.join(options.publicDir,'current.json'))};
}
const save=(store,draft=store.read().draft)=>store.save({revision:store.read().revision,operation_id:randomUUID(),draft},'fixture');

test('old revision2 first save changes only explicit text and preserves missing defaults, inheritance and source values',t=>{
 const {store,state,publicBytes}=fixture(t),draft=structuredClone(state.draft);draft.pages[0].title='Explicit title edit';
 const result=save(store,draft);assert.deepEqual(result.draft,draft);assert.deepEqual(result.draft.pages.slice(1),state.draft.pages.slice(1));
 assert.equal(Object.hasOwn(result.draft,'fc_layout'),false);assert(result.draft.pages.every(p=>!Object.hasOwn(p,'product_keys')));
 assert.equal(result.draft.pages[0].starts_at,'2026-10-25T09:00:00+08:00');assert.equal(result.draft.pages[0].ends_at,'');
 assert.deepEqual(publicBytes(),Buffer.from('synthetic-public-bytes'));
 assert.deepEqual(store.restoreCandidate(),{revision:2,changed_fields:['pages'],changed_pages:['fc27-weekly']});
});

test('explicit sorting pins only the changed page and exact restore removes that property instead of reverse-sorting',t=>{
 const {store,state,options}=fixture(t),draft=structuredClone(state.draft);draft.pages[0].product_keys=['fc-170014917-pc','fc-170014917-ps'];
 const saved=save(store,draft);assert.deepEqual(saved.draft,draft);assert.deepEqual(saved.draft.pages.slice(1),state.draft.pages.slice(1));
 const body={revision:3,operation_id:randomUUID(),restore_revision:2},restored=store.restoreDraft(body,'fixture');
 assert.deepEqual(restored.draft,state.draft);assert.equal(restored.revision,4);assert.equal(restored.last_operation.kind,'restore');assert.equal(restored.last_operation.restore_revision,2);
 assert.deepEqual(restored.published,state.published);assert.deepEqual(makeCenterStore(options).restoreDraft(body,'fixture'),restored);
 assert.throws(()=>store.restoreDraft({...body,restore_revision:1},'fixture'),{code:'REQUEST_CONFLICT'});
 const history=JSON.parse(fs.readFileSync(path.join(options.dir,'history/3.json')));assert.deepEqual(history.draft,draft);
});

test('read/cancel is byte-preserving, unrelated page edits retain inherited membership, and stale restore CAS rejects',t=>{
 const {store,state,options}=fixture(t),file=path.join(options.dir,'state.json'),before=fs.readFileSync(file);
 store.read();store.restoreCandidate();assert.deepEqual(fs.readFileSync(file),before);
 const first=structuredClone(state.draft);first.pages[0].description='First edit';save(store,first);
 const second=structuredClone(store.read().draft);second.pages[3].title='Seasonal only';save(store,second);
 assert.equal(Object.hasOwn(store.read().draft,'fc_layout'),false);assert(store.read().draft.pages.every(p=>!Object.hasOwn(p,'product_keys')));
 assert.throws(()=>store.restoreDraft({revision:3,operation_id:randomUUID(),restore_revision:2},'fixture'),{code:'REVISION_CONFLICT'});
 assert.throws(()=>store.restoreDraft({revision:4,operation_id:randomUUID(),restore_revision:2},'fixture'),{code:'RESTORE_REVISION_CONFLICT'});
 assert.deepEqual(store.read().draft,second);
});

test('illegal raw values and extra fields cannot be normalized into a legal persistent draft',t=>{
 const {store,state,options}=fixture(t),before=fs.readFileSync(path.join(options.dir,'state.json'));
 for(const mutate of [d=>d.integration_mode='live',d=>d.secret='untrusted',d=>d.pages[0].path='other.html',d=>d.pages[0].activity_id='other',
  d=>d.pages[0].preview_enabled='false',d=>d.pages[0].default_language=null,d=>d.pages[0].description=null,d=>d.pages[0].unknown='x',
  d=>d.pages[0].starts_at=0,d=>d.pages[0].benefit_refs=[{kind:'coupon',native_id:123}],
  d=>{d.fc_layout=structuredClone(initialLayout(catalog));d.fc_layout.secret='untrusted';},
  d=>{d.fc_layout=structuredClone(initialLayout(catalog));d.fc_layout.routes.unselected=structuredClone(d.fc_layout.routes[d.fc_layout.defaultCore]);},
  d=>{d.fc_layout=structuredClone(initialLayout(catalog));d.fc_layout.routes[d.fc_layout.defaultCore].label={en:'<script>'};}
 ]){const draft=structuredClone(state.draft);mutate(draft);assert.throws(()=>save(store,draft));assert.deepEqual(fs.readFileSync(path.join(options.dir,'state.json')),before);}
});

test('deselecting a legitimate SBC core preserves and validates its dormant route without publishing it',t=>{
 const {store,state,options}=fixture(t),draft=structuredClone(state.draft);draft.fc_layout=structuredClone(initialLayout(catalog));
 const removed=draft.fc_layout.sbc.find(key=>key!==draft.fc_layout.defaultCore);assert(removed);
 draft.fc_layout.sbc=draft.fc_layout.sbc.filter(key=>key!==removed);const dormant=structuredClone(draft.fc_layout.routes[removed]);
 const saved=save(store,draft);assert.deepEqual(saved.draft,draft);assert.deepEqual(saved.draft.fc_layout.routes[removed],dormant);
 const invalid=structuredClone(saved.draft);invalid.fc_layout.routes[removed].picks=['not-a-product','185070945'];
 assert.throws(()=>save(store,invalid),{code:'INVALID_FC_LAYOUT'});
 store.publish({revision:3,operation_id:randomUUID()},'fixture');const snapshot=JSON.parse(fs.readFileSync(path.join(options.publicDir,'current.json')));
 assert.equal(Object.hasOwn(snapshot.fc_layout.routes,removed),false);assert.deepEqual(store.read().draft.fc_layout.routes[removed],dormant);
});

test('restore remains within save history and cannot undo publication or imports, including import property presence',t=>{
 const {store,state,options}=fixture(t),draft=structuredClone(state.draft);draft.pages[0].title='Edit';save(store,draft);
 const previousPath=path.join(options.dir,'history/2.json'),previous=JSON.parse(fs.readFileSync(previousPath));
 fs.writeFileSync(previousPath,JSON.stringify({...previous,draft:{...previous.draft,imported_products:[]}}));
 assert.equal(store.restoreCandidate(),null);assert.throws(()=>store.restoreDraft({revision:3,operation_id:randomUUID(),restore_revision:2},'fixture'),{code:'DRAFT_RESTORE_UNAVAILABLE'});
 fs.writeFileSync(previousPath,JSON.stringify({...previous,published:{release_id:'different'}}));assert.equal(store.restoreCandidate(),null);
 fs.writeFileSync(previousPath,JSON.stringify(previous));assert(store.restoreCandidate());
 store.publish({revision:3,operation_id:randomUUID()},'fixture');assert.equal(store.restoreCandidate(),null);
 const data={product_ref:{site_id:'266',game_id:'1327',goods_id:'900000021',model_id:'900000022'},title:'Synthetic imported',platform_attribute_id:null,authoritative:false,checkout_enabled:false};
 store.importProduct({revision:4,operation_id:randomUUID(),draft:store.read().draft,page_id:'fc27-weekly',product_ref:data.product_ref},'fixture',data);
 assert.equal(store.restoreCandidate(),null);assert.throws(()=>store.restoreDraft({revision:5,operation_id:randomUUID(),restore_revision:4},'fixture'),{code:'DRAFT_RESTORE_UNAVAILABLE'});
 assert.throws(()=>store.restoreDraft({revision:5,operation_id:randomUUID(),restore_revision:4,draft:state.draft},'fixture'),{code:'INVALID_DRAFT_RESTORE'});
});

test('uncertain restore resumes the same durable operation once at every transaction boundary',t=>{
 for(const boundary of ['prepared','state','receipt']){
  const {store,state,options,publicBytes}=fixture(t),draft=structuredClone(state.draft);draft.fc_layout=structuredClone(initialLayout(catalog));draft.fc_layout.weekly.reverse();save(store,draft);
  assert(store.restoreCandidate().changed_fields.includes('fc_layout'));
  const body={revision:3,operation_id:randomUUID(),restore_revision:2},broken=makeCenterStore({...options,checkpoint:point=>{if(point===boundary)throw Error('synthetic interrupted response');}});
  assert.throws(()=>broken.restoreDraft(body,'fixture'),/synthetic interrupted response/);
  const resumed=makeCenterStore(options),result=resumed.restoreDraft(body,'fixture');assert.equal(result.revision,4);assert.deepEqual(result.draft,state.draft);
  assert.deepEqual(resumed.restoreDraft(body,'fixture'),result);assert.deepEqual(publicBytes(),Buffer.from('synthetic-public-bytes'));
  assert.equal(fs.existsSync(path.join(options.dir,'pending.json')),false);assert.equal(Object.hasOwn(result.draft,'fc_layout'),false);
 }
});

test('GET separates effective FC fallback from raw draft; restore HTTP retains auth, origin, CSRF and exact source shape',async t=>{
 const {options,state,dir}=fixture(t),originalFetch=globalThis.fetch,keys=['CAMPAIGN_DATA','CAMPAIGN_PUBLIC_RELEASE_DIR','CAMPAIGN_ORIGIN'],previous=Object.fromEntries(keys.map(k=>[k,process.env[k]]));
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=options.publicDir;process.env.CAMPAIGN_ORIGIN='http://localhost';
 globalThis.fetch=async(url,opts)=>{if(String(url)==='http://127.0.0.1:8895/verify?group=dashboard'){
  const role=opts.headers.Cookie==='admin'?'admin':opts.headers.Cookie==='reader'?'reader':null;
  return new Response(null,{status:role?200:401,headers:role?{'x-auth-user':'fixture','x-auth-role':role}:{}});
 }return originalFetch(url,opts);};
 let server;
 try{
  ({server}=await import('../production-server.mjs'));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/api/center',file=path.join(options.dir,'state.json'),before=fs.readFileSync(file);
  const read=await (await originalFetch(base,{headers:{Cookie:'admin'}})).json();assert.deepEqual(read.draft,state.draft);assert.deepEqual(read.effective_fc_layout,validateLayout(initialLayout(catalog),catalog));assert.equal(read.restore_candidate,null);assert.deepEqual(fs.readFileSync(file),before);
  const draft=structuredClone(read.draft);draft.pages[0].title='HTTP title';const headers={Cookie:'admin',Origin:'http://localhost','Content-Type':'application/json','X-CSRF-Token':read.csrf};
  const saved=await (await originalFetch(base,{method:'POST',headers,body:JSON.stringify({revision:2,operation_id:randomUUID(),draft})})).json();assert.equal(saved.revision,3,JSON.stringify(saved));assert.deepEqual(saved.draft,draft);assert.equal(saved.restore_candidate.revision,2);
  const body=JSON.stringify({revision:3,operation_id:randomUUID(),restore_revision:2});
  for(const bad of [{...headers,Cookie:'reader'},{...headers,Origin:'https://untrusted.invalid'},{...headers,'X-CSRF-Token':'wrong'}])assert.equal((await originalFetch(base+'/restore',{method:'POST',headers:bad,body})).status,403);
  const response=await originalFetch(base+'/restore',{method:'POST',headers,body});assert.equal(response.status,200);const restored=await response.json();assert.deepEqual(restored.draft,state.draft);assert.deepEqual(restored.published,state.published);assert.equal(restored.revision,4);
  assert.equal((await originalFetch(base+'/restore',{method:'POST',headers,body})).status,200);
 }finally{if(server)await new Promise(resolve=>server.close(resolve));globalThis.fetch=originalFetch;for(const key of keys){if(previous[key]===undefined)delete process.env[key];else process.env[key]=previous[key];}}
});
