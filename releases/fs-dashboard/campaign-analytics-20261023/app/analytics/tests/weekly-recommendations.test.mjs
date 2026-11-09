import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {makeWeeklyRecommendations} from '../weekly-recommendations.mjs';

const now=()=>Date.parse('2026-11-09T10:00:00Z');
const update=()=>({id:'fixture-sbc',observed_at:'2026-11-09T09:00:00Z',context:'Fixture weekly update',sources:[]});
function fixture(t,options={}){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-recommend-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const context={source_revision:'1',draft:{pages:['fc27-trio','fc27-weekly','fc27-sbc'].map(page_id=>({page_id}))},catalog_products:[{key:'fc-player-ps',title:'Fixture',product_ref:{site_id:'266',game_id:'1327',goods_id:'1'},platform:{code:'ps',attribute_id:'21587'},available:false}],
  page_bindings:Object.fromEntries(['fc27-trio','fc27-weekly','fc27-sbc'].map(page_id=>[page_id,{product_keys:['fc-player-ps']}]))};
 const config={dir,contextProvider:()=>context,enabledProvider:()=>true,now,...options};
 const body={revision:1,operation_id:randomUUID(),id:'2026-W46',page_id:'fc27-sbc',sbc_update:update()};
 return {dir,config,context,body,store:makeWeeklyRecommendations(config)};
}
const reply=request=>({model:request.model,source_revision:request.input.source_revision,sbc_update_id:request.input.sbc_update.id,recommendations:[{page_id:'fc27-weekly',product_key:'fc-player-ps',reason:'Fixture recommendation',evidence_indices:[]}]});

test('unconnected provider is recorded without touching center and original request is immutable',async t=>{
 const {context,body,store}=fixture(t),before=structuredClone(context),result=await store.recommend(body,'fixture');
 assert.equal(result.status,'unavailable');assert.deepEqual(context,before);assert.deepEqual(await store.recommend(body,'fixture'),result);
 await assert.rejects(store.recommend({...body,sbc_update:{...body.sbc_update,context:'Changed'}},'fixture'),{code:'REQUEST_CONFLICT'});
 assert.equal(store.read().last.sbc_update.id,body.sbc_update.id);
});

test('same operation or content cannot dispatch twice, including concurrent callers and restart',async t=>{
 let calls=0,release;const f=fixture(t,{provider:request=>{calls++;return new Promise(resolve=>release=()=>resolve(reply(request)));}});
 const running=f.store.recommend(f.body,'fixture');
 assert.equal(f.store.read().last.status,'pending');
 assert.equal((await f.store.recommend(f.body,'fixture')).status,'pending');
 const second={...f.body,operation_id:randomUUID()};assert.equal((await f.store.recommend(second,'fixture')).duplicate_of,f.body.operation_id);assert.equal(calls,1);
 release();assert.equal((await running).status,'completed');
 const restarted=makeWeeklyRecommendations(f.config);assert.equal((await restarted.recommend(second,'fixture')).status,'completed');assert.equal(calls,1);
 f.context.source_revision='2';assert.equal(restarted.read().last.stale,true);
});

test('stale new requests reject before provider and persisted timeout stays unknown without replay',async t=>{
 let calls=0;const {store,body}=fixture(t,{timeout_ms:5,provider:async()=>{calls++;return new Promise(()=>{});}});
 await assert.rejects(store.recommend({...body,revision:0},'fixture'),{code:'REVISION_CONFLICT'});assert.equal(calls,0);
 const result=await store.recommend(body,'fixture');assert.equal(result.error,'WEEKLY_HERMES_PROVIDER_TIMEOUT');assert.equal(result.provider_outcome,'unknown');
 const duplicate=await store.recommend({...body,operation_id:randomUUID()},'fixture');assert.equal(duplicate.provider_outcome,'unknown');assert.equal(calls,1);
});

test('disabled or unavailable preflight can be explicitly requested later after provider connection',async t=>{
 let enabled=false,calls=0;const f=fixture(t,{enabledProvider:()=>enabled,provider:async request=>{calls++;return reply(request);}});
 assert.equal((await f.store.recommend(f.body,'fixture')).status,'disabled');assert.equal(calls,0);
 enabled=true;assert.equal((await f.store.recommend({...f.body,operation_id:randomUUID()},'fixture')).status,'completed');assert.equal(calls,1);
 assert.equal((await f.store.recommend(f.body,'fixture')).status,'disabled');
});

test('stored recommendations become stale when the bound update expires without changing a center revision',async t=>{
 let time=now();const f=fixture(t,{now:()=>time,provider:async request=>reply(request)});
 f.body.sbc_update.expires_at=new Date(time+1000).toISOString();
 assert.equal((await f.store.recommend(f.body,'fixture')).stale,false);
 time+=1000;assert.equal(f.store.read().last.stale,true);
});
