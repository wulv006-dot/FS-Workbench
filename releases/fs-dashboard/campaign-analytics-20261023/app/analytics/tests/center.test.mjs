import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {makeCenterStore,initialCenterDraft,validateDraft} from '../center-store.mjs';
import {centerSeed} from '../center-seed.mjs';
import {createCommerce} from '../../runtime/commerce.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
function seed(){const box={};vm.runInNewContext(fs.readFileSync(path.join(root,'seasonal/campaign-data.js'),'utf8'),box);return centerSeed(JSON.parse(fs.readFileSync(path.join(root,'catalog.json'),'utf8')),box.SeasonalData);}
test('original four pages preserve product identity and disable unverified purchasing',()=>{
 const s=seed();assert.equal(s.seedProducts.filter(p=>p.key.startsWith('seasonal-')).length,18);
 assert(s.seedProducts.every(p=>p.available===false));assert.deepEqual(Object.keys(s.pageProductKeys),['fc27-weekly','fc27-sbc','fc27-trio','seasonal-vault']);
 const p=s.seedProducts.find(p=>p.key==='seasonal-fc-1');assert.equal(p.product_ref.goods_id,'163329311');assert.equal(p.quantity.min,'100');assert.equal(p.quantity.unit,'K');
});
test('draft CAS, persistent same-id replay, public projection and original runtime reload',()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-center-'));
 try{
  const options={dir:path.join(tmp,'private'),publicDir:path.join(tmp,'public'),sourceRevision:'candidate-1',...seed()};let store=makeCenterStore(options);
  const draft=initialCenterDraft(),save={revision:0,operation_id:randomUUID(),draft};draft.pages[0].description='Original accepted design';
  assert.equal(store.save(save,'admin').revision,1);
  store=makeCenterStore(options);assert.equal(store.save(save,'admin').revision,1);
  assert.throws(()=>store.save({...save,draft:{...draft,seasonal_theme:'christmas'}},'admin'),e=>e.code==='REQUEST_CONFLICT');
  assert.throws(()=>store.save({...save,operation_id:randomUUID()},'admin'),e=>e.code==='REVISION_CONFLICT');
  const publish={revision:1,operation_id:randomUUID()};assert.equal(store.publish(publish,'admin').revision,2);assert.equal(store.publish(publish,'admin').revision,2);
  const snapshot=JSON.parse(fs.readFileSync(path.join(tmp,'public/current.json'),'utf8'));
  assert.equal(snapshot.publication_status,'published');assert(snapshot.products.length>=Object.keys(JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url),'utf8')).products).length);assert.equal(snapshot.updated_by,undefined);assert.equal(snapshot.pages[0].benefit_refs,undefined);
  const commerce=createCommerce({snapshotProvider:()=>JSON.parse(fs.readFileSync(path.join(tmp,'public/current.json'),'utf8')),snapshot,dir:path.join(tmp,'ops')});
  assert.equal(commerce.config().release_id,'campaign-preview-2');assert.equal(commerce.capabilities().live_checkout,false);
  assert.throws(()=>commerce.intent({activity_id:'fc27-season2',page_id:'fc27-weekly',rule_version:'preview-2',benefit_binding_version:'unverified-2',currency:'USD',lines:[{line_key:'a',product_key:snapshot.pages[0].product_keys[0],quantity:{value:'1',unit:'item',group:'1'}}]}),e=>e.code==='PRODUCT_UNAVAILABLE');
 }finally{fs.rmSync(tmp,{recursive:true,force:true});}
});
test('invalid scope, dates, theme and unsafe text cannot become a draft',()=>{
 for(const mutate of [d=>d.pages.pop(),d=>d.pages[0].title='<script>',d=>d.seasonal_theme='other',d=>{d.pages[0].starts_at='2026-10-25T00:00:00Z';d.pages[0].ends_at='2026-10-24T00:00:00Z';},d=>d.pages[0].benefit_refs=[{kind:'coupon',native_id:'../secret'}]]){
  const draft=initialCenterDraft();mutate(draft);assert.throws(()=>validateDraft(draft));
 }
});
test('publication recovers the frozen plan at every durable boundary even if source seeds change',()=>{
 for(const boundary of ['prepared','public-pointer','state','receipt']){
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-publish-crash-'));
  try{
   let currentSeed=seed();const options={dir:path.join(tmp,'private'),publicDir:path.join(tmp,'public'),sourceRevision:'candidate-1',seedProvider:()=>currentSeed};
   makeCenterStore(options).save({revision:0,operation_id:randomUUID(),draft:initialCenterDraft()},'admin');
   const request={revision:1,operation_id:randomUUID()},broken=makeCenterStore({...options,checkpoint:stage=>{if(stage===boundary)throw Error('simulated crash');}});
   assert.throws(()=>broken.publish(request,'admin'),/simulated crash/);
   const prepared=JSON.parse(fs.readFileSync(path.join(tmp,'private/pending.json'),'utf8'));
   currentSeed=structuredClone(currentSeed);currentSeed.seedProducts[0].title='Changed after crash';
   const recovered=makeCenterStore(options).publish(request,'admin');
   const publicSnapshot=JSON.parse(fs.readFileSync(path.join(tmp,'public/current.json'),'utf8'));
   assert.equal(publicSnapshot.config_hash,prepared.snapshot.config_hash);
   assert.equal(publicSnapshot.products[0].title,prepared.snapshot.products[0].title);
   assert.equal(recovered.published.config_hash,publicSnapshot.config_hash);
   assert.equal(recovered.revision,2);assert.equal(fs.existsSync(path.join(tmp,'private/pending.json')),false);
   assert.equal(makeCenterStore(options).publish(request,'admin').revision,2);
  }finally{fs.rmSync(tmp,{recursive:true,force:true});}
 }
});
test('management center preserves original session role, origin and CSRF gates',async()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-management-')),originalFetch=globalThis.fetch;
 process.env.CAMPAIGN_DATA=path.join(tmp,'private');process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(tmp,'public');
 process.env.CAMPAIGN_ORIGIN='http://localhost';
 globalThis.fetch=async(url,options)=>{
  if(String(url)==='http://127.0.0.1:8895/verify?group=dashboard'){
   const role=options.headers.Cookie==='admin'?'admin':options.headers.Cookie==='reader'?'reader':null;
   return new Response(null,{status:role?200:401,headers:role?{'x-auth-user':'fixture','x-auth-role':role}:{}});
  }
  return originalFetch(url,options);
 };
 let server;
 try{
  ({server}=await import('../production-server.mjs'));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/api/center';
  assert.equal((await originalFetch(base)).status,401);
  const readonly=await (await originalFetch(base,{headers:{Cookie:'reader'}})).json();assert.equal(readonly.canEdit,false);assert.equal(readonly.csrf,null);
  assert.equal((await originalFetch(base,{method:'POST',headers:{Cookie:'reader','Content-Type':'application/json',Origin:'http://localhost'},body:'{}'})).status,403);
  const state=await (await originalFetch(base,{headers:{Cookie:'admin'}})).json();
  const headers={Cookie:'admin','Content-Type':'application/json',Origin:'http://localhost','X-CSRF-Token':state.csrf};
  assert.equal((await originalFetch(base,{method:'POST',headers:{...headers,Origin:'https://untrusted.invalid'},body:'{}'})).status,403);
  const saved=await originalFetch(base,{method:'POST',headers,body:JSON.stringify({revision:0,operation_id:randomUUID(),draft:state.draft})});assert.equal(saved.status,200);
  const published=await originalFetch(base+'/publish',{method:'POST',headers,body:JSON.stringify({revision:1,operation_id:randomUUID()})});assert.equal(published.status,200);assert.equal((await published.json()).published.live_checkout,false);
 }finally{if(server)await new Promise(resolve=>server.close(resolve));globalThis.fetch=originalFetch;fs.rmSync(tmp,{recursive:true,force:true});}
});
