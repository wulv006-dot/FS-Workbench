import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {createWeeklyHermesProvider} from '../weekly-hermes-provider.mjs';
const reply=(id)=>new Response(JSON.stringify({status:'completed',result:{model:'gpt-6.1-sol',source_revision:'7',sbc_update_id:'sbc1',recommendations:[]},receipt:{operation_id:id,task_id:'task1',run_id:'run1',model:'gpt-6.1-sol',cookie:'never copy',usage:{input_tokens:10,output_tokens:20,credential:'never copy'}}}),{status:200});

test('request-scoped actor and session reach only fixed local headers; original ID and input reach host',async()=>{
 const id=randomUUID(),calls=[],provider=createWeeklyHermesProvider({cookie:'fixture-session',actor:'verified-admin',fetchImpl:async(url,options)=>{calls.push({url,options});return reply(id);}}),input={source_revision:'7',catalog:[]};
 const result=await provider({input,model:'browser-model',instructions:'never forward'},{operation_id:id});assert.equal(result.model,'gpt-6.1-sol');
 assert.equal(calls[0].url,'http://127.0.0.1:8931/internal/hermes/campaign-recommendations');assert.equal(calls[0].options.redirect,'error');assert.equal(calls[0].options.headers.Cookie,'fixture-session');assert.equal(calls[0].options.headers['X-FS-Actor'],'verified-admin');
 assert.deepEqual(JSON.parse(calls[0].options.body),{contract:'campaign_recommendation_v1',operation_id:id,input});assert(!JSON.stringify(provider.receipt).includes('never copy'));
 await provider.lookup({operation_id:id});assert.equal(calls[1].options.method,'GET');assert.equal(calls[1].options.body,undefined);assert(calls[1].url.endsWith('?operation_id='+id));
});
test('parallel callers cannot exchange their identity or session',async()=>{
 const calls=[];const make=(actor,id)=>createWeeklyHermesProvider({cookie:'session-'+actor,actor,fetchImpl:async(_,options)=>{await new Promise(resolve=>setTimeout(resolve,1));calls.push(options.headers);return reply(id);}});
 const a=randomUUID(),b=randomUUID();await Promise.all([make('a',a)({input:{}},{operation_id:a}),make('b',b)({input:{}},{operation_id:b})]);assert.deepEqual(calls.map(h=>[h['X-FS-Actor'],h.Cookie]).sort(),[['a','session-a'],['b','session-b']]);
});
test('missing host, expired auth and known not-dispatched are unavailable',async()=>{
 for(const status of [401,403,404,413]){const provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl:async()=>new Response('{}',{status})});await assert.rejects(provider({input:{}},{operation_id:randomUUID()}),e=>e.code==='WEEKLY_HERMES_PROVIDER_UNAVAILABLE'&&e.provider_outcome==='not_dispatched');}
 const provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl:async()=>{throw Object.assign(Error('secret'),{cause:{code:'ECONNREFUSED'}});}});await assert.rejects(provider({input:{}},{operation_id:randomUUID()}),{code:'WEEKLY_HERMES_PROVIDER_UNAVAILABLE'});
});
test('pending, disconnect, malformed reply and wrong receipt preserve unknown without replay',async()=>{
 const id=randomUUID();for(const fetchImpl of [async()=>new Response(JSON.stringify({status:'pending'}),{status:202}),async()=>{throw Error('private transport failure');},async()=>new Response('not-json'),async()=>reply(randomUUID())]){
  const provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl});await assert.rejects(provider({input:{}},{operation_id:id}),e=>e.code==='WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'&&e.provider_outcome==='unknown'&&!e.message.includes('private'));
 }
});
test('lookup never resubmits missing original operation and invalid local identity never calls host',async()=>{
 const provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl:async()=>new Response('{}',{status:404})});await assert.rejects(provider.lookup({operation_id:randomUUID()}),{code:'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'});
 let calls=0;const missing=createWeeklyHermesProvider({cookie:'',actor:'admin',fetchImpl:async()=>{calls++;}});await assert.rejects(missing({input:{}},{operation_id:randomUUID()}),{code:'WEEKLY_HERMES_PROVIDER_UNAVAILABLE'});assert.equal(calls,0);
});


test('accepted async operation remains pending and lookup never submits it again',async()=>{
 const operation_id=randomUUID(),methods=[],provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl:async(_,options)=>{methods.push(options.method);return new Response(JSON.stringify({status:'pending',operation_id,task_id:'task1'}),{status:202});}});
 await assert.rejects(provider({input:{}},{operation_id}),e=>e.code==='WEEKLY_HERMES_PROVIDER_PENDING'&&e.provider_outcome==='pending');
 await assert.rejects(provider.lookup({operation_id}),{code:'WEEKLY_HERMES_PROVIDER_PENDING'});assert.deepEqual(methods,['POST','GET']);
});


test('lookup has a bounded signal and streaming response stops at its byte limit',async()=>{
 let signal,cancelled=false;const provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl:async(_,options)=>{signal=options.signal;return new Response(new ReadableStream({pull(controller){controller.enqueue(new Uint8Array(600000));},cancel(){cancelled=true;}}));}});
 await assert.rejects(provider.lookup({operation_id:randomUUID()}),{code:'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'});assert(signal instanceof AbortSignal);assert.equal(cancelled,true);
});

test('known no-dispatch JSON must name the original operation before releasing uncertainty',async()=>{
 const operation_id=randomUUID();for(const receiptId of [undefined,randomUUID(),operation_id]){
  const provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl:async()=>new Response(JSON.stringify({operation_id:receiptId,status:'unavailable',error:'WEEKLY_HERMES_PROVIDER_UNAVAILABLE',provider_outcome:'not_dispatched'}))});
  await assert.rejects(provider({input:{}},{operation_id}),{code:receiptId===operation_id?'WEEKLY_HERMES_PROVIDER_UNAVAILABLE':'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'});
 }
});

test('only matched explicit paid failure is a trusted terminal result',async()=>{
 const operation_id=randomUUID(),base={status:'failed',operation_id,error:'WEEKLY_HERMES_RECOMMENDATION_FAILED',provider_outcome:'completed',receipt:{operation_id,task_id:'task1',run_id:'run1',model:'gpt-6.1-sol',usage:{input_tokens:10}}};
 for(const [status,patch,expected] of [[200,{},'WEEKLY_HERMES_RECOMMENDATION_FAILED'],[500,{},'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'],[200,{operation_id:randomUUID()},'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'],[200,{error:'OTHER_FAILURE'},'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'],[200,{receipt:{...base.receipt,operation_id:randomUUID()}},'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN']]){
  const provider=createWeeklyHermesProvider({cookie:'session',actor:'admin',fetchImpl:async()=>new Response(JSON.stringify({...base,...patch}),{status})});
  await assert.rejects(provider.lookup({operation_id}),{code:expected});
  if(expected==='WEEKLY_HERMES_RECOMMENDATION_FAILED')assert.equal(provider.receipt.run_id,'run1');
 }
});
