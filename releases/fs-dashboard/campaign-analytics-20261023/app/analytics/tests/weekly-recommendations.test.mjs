import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {createWeeklyHermesProvider} from '../weekly-hermes-provider.mjs';
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

test('original operations and content dedupe are isolated by authenticated owner',async t=>{
 let calls=0;const provider=async()=>{calls++;throw Object.assign(Error('pending'),{code:'WEEKLY_HERMES_PROVIDER_PENDING',provider_outcome:'pending'});};
 const f=fixture(t,{provider});assert.equal((await f.store.recommend(f.body,'owner-a')).status,'pending');
 await assert.rejects(f.store.recommend(f.body,'owner-b'),{code:'WEEKLY_RECOMMENDATION_OWNER_REQUIRED'});assert.equal(calls,1);
 const b={...f.body,operation_id:randomUUID()};const result=await f.store.recommend(b,'owner-b');assert.equal(result.operation_id,b.operation_id);assert.equal(result.duplicate_of,undefined);assert.equal(calls,2);
 await assert.rejects(f.store.reconcile({operation_id:b.operation_id},'owner-a'),{code:'WEEKLY_RECOMMENDATION_OWNER_REQUIRED'});
 assert.equal((await f.store.reconcile({operation_id:b.operation_id},'owner-b')).operation_id,b.operation_id);
});
test('pending and completed receipts persist only original-scope safe metadata',async t=>{
 let request;const provider=async(input,{operation_id})=>{request=input;provider.receipt={operation_id,task_id:'task1',session:'never-persist',usage:{input_tokens:10,password:'never-persist'}};throw Object.assign(Error('pending'),{code:'WEEKLY_HERMES_PROVIDER_PENDING',provider_outcome:'pending'});};
 const f=fixture(t,{provider});provider.lookup=async({operation_id})=>{provider.receipt={operation_id,task_id:'task1',run_id:'run1',model:'gpt-6.1-sol',usage:{input_tokens:10,output_tokens:20,total_tokens:30,secret:'never-persist'}};return reply(request);};
 const pending=await f.store.recommend(f.body,'fixture');assert.equal(pending.receipt.task_id,'task1');assert.equal(pending.receipt.session,undefined);
 const completed=await f.store.reconcile({operation_id:f.body.operation_id},'fixture');assert.equal(completed.receipt.run_id,'run1');assert.equal(completed.receipt.operation_id,f.body.operation_id);assert.equal(completed.receipt.usage.total_tokens,30);
 const persisted=fs.readFileSync(path.join(f.dir,'weekly-recommendations.json'),'utf8');assert(!persisted.includes('never-persist'));assert.equal(makeWeeklyRecommendations(f.config).read().last.receipt.run_id,'run1');
});
test('receipt from a different operation is never attributed to the current result',async t=>{
 const provider=async request=>{provider.receipt={operation_id:randomUUID(),run_id:'wrong-run'};return reply(request);};const f=fixture(t,{provider});const result=await f.store.recommend(f.body,'fixture');assert.equal(result.status,'completed');assert.equal(result.receipt,undefined);
});
test('late POST pending cannot overwrite completed original-ID reconciliation',async t=>{
 let rejectSubmission,prepared;const provider=(request,{operation_id})=>{prepared=request;provider.receipt={operation_id,task_id:'task1'};return new Promise((resolve,reject)=>{rejectSubmission=()=>reject(Object.assign(Error('pending'),{code:'WEEKLY_HERMES_PROVIDER_PENDING',provider_outcome:'pending'}));});};
 const f=fixture(t,{provider}),running=f.store.recommend(f.body,'fixture');
 const lookup=async()=>{};lookup.lookup=async({operation_id})=>{lookup.receipt={operation_id,task_id:'task1',run_id:'run1'};return reply(prepared);};
 assert.equal((await f.store.reconcile({operation_id:f.body.operation_id},'fixture',{provider:lookup})).status,'completed');
 rejectSubmission();const result=await running;assert.equal(result.status,'completed');assert.equal(result.receipt.run_id,'run1');assert.equal(f.store.read().last.status,'completed');
});


test('confirmed original no-dispatch reconciliation ends pending and permits a new explicit attempt',async t=>{
 let posts=0;const provider=createWeeklyHermesProvider({cookie:'fixture',actor:'fixture',fetchImpl:async(url,options)=>{
  const operation_id=options.method==='POST'?JSON.parse(options.body).operation_id:new URL(url).searchParams.get('operation_id');
  if(options.method==='POST'){posts++;return new Response(JSON.stringify({status:'pending',operation_id}),{status:202});}
  return new Response(JSON.stringify({status:'unavailable',operation_id,error:'WEEKLY_HERMES_PROVIDER_UNAVAILABLE',provider_outcome:'not_dispatched'}));
 }});
 const f=fixture(t,{provider});assert.equal((await f.store.recommend(f.body,'fixture')).status,'pending');
 const result=await f.store.reconcile({operation_id:f.body.operation_id},'fixture');assert.equal(result.status,'unavailable');assert.equal(result.provider_outcome,'not_dispatched');assert.equal(f.store.read().last.status,'unavailable');
 await f.store.recommend({...f.body,operation_id:randomUUID()},'fixture');assert.equal(posts,2);
});
test('lookup authentication or connection failure never proves original model was not dispatched',async t=>{
 for(const failure of [401,403,413,'refused']){
  let posts=0;const provider=createWeeklyHermesProvider({cookie:'fixture',actor:'fixture',fetchImpl:async(url,options)=>{
   if(options.method==='POST'){posts++;return new Response(JSON.stringify({status:'pending',operation_id:JSON.parse(options.body).operation_id}),{status:202});}
   if(failure==='refused')throw Object.assign(Error('unavailable transport'),{cause:{code:'ECONNREFUSED'}});
   return new Response('{}',{status:failure});
  }});
  const f=fixture(t,{provider});await f.store.recommend(f.body,'fixture');
  await assert.rejects(f.store.reconcile({operation_id:f.body.operation_id},'fixture'),{code:'WEEKLY_HERMES_PROVIDER_UNAVAILABLE'});
  assert.equal(f.store.read().last.status,'pending');const again=await f.store.recommend({...f.body,operation_id:randomUUID()},'fixture');assert.equal(again.duplicate_of,f.body.operation_id);assert.equal(posts,1);
 }
});

test('paid invalid-output terminal failure reconciles and remains deduplicated',async t=>{
 let posts=0;const provider=createWeeklyHermesProvider({cookie:'fixture',actor:'fixture',fetchImpl:async(url,options)=>{
  const operation_id=options.method==='POST'?JSON.parse(options.body).operation_id:new URL(url).searchParams.get('operation_id');
  if(options.method==='POST'){posts++;return new Response(JSON.stringify({status:'pending',operation_id,task_id:'task1'}),{status:202});}
  return new Response(JSON.stringify({status:'failed',operation_id,error:'WEEKLY_HERMES_RECOMMENDATION_FAILED',provider_outcome:'completed',receipt:{operation_id,task_id:'task1',run_id:'run1',model:'gpt-6.1-sol',usage:{input_tokens:10,output_tokens:20}}}));
 }});
 const f=fixture(t,{provider});await f.store.recommend(f.body,'fixture');const result=await f.store.reconcile({operation_id:f.body.operation_id},'fixture');
 assert.equal(result.status,'failed');assert.equal(result.provider_outcome,'completed');assert.equal(result.receipt.run_id,'run1');assert.equal(result.receipt.usage.output_tokens,20);
 const duplicate=await f.store.recommend({...f.body,operation_id:randomUUID()},'fixture');assert.equal(duplicate.status,'failed');assert.equal(duplicate.duplicate_of,f.body.operation_id);assert.equal(posts,1);
 assert.equal((await f.store.reconcile({operation_id:f.body.operation_id},'fixture')).status,'failed');
});
test('immediate trusted paid failure is persisted as terminal with its receipt',async t=>{
 const provider=createWeeklyHermesProvider({cookie:'fixture',actor:'fixture',fetchImpl:async(_,options)=>{const operation_id=JSON.parse(options.body).operation_id;return new Response(JSON.stringify({status:'failed',operation_id,error:'WEEKLY_HERMES_RECOMMENDATION_FAILED',provider_outcome:'completed',receipt:{operation_id,task_id:'task1',run_id:'run1',model:'gpt-6.1-sol'}}));}});
 const f=fixture(t,{provider}),result=await f.store.recommend(f.body,'fixture');assert.equal(result.status,'failed');assert.equal(result.provider_outcome,'completed');assert.equal(result.receipt.run_id,'run1');
});
