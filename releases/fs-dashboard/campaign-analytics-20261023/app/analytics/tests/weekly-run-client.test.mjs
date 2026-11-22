import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {weeklyRunCall} from '../weekly-run-client.mjs';
test('run bridge forwards only the verified request actor and preserves original operation id',async()=>{const operation_id=randomUUID();let captured;const result=await weeklyRunCall({method:'POST',body:{action:'run',operation_id},cookie:'test-session',actor:'test-owner',fetchImpl:async(url,options)=>{captured={url,options};return new Response(JSON.stringify({status:'pending',operation_id}),{status:202});}});assert.equal(result.operation_id,operation_id);assert.equal(captured.options.headers['X-FS-Actor'],'test-owner');assert(!captured.options.body.includes('test-owner'));assert(!captured.options.body.includes('test-session'));
 await assert.rejects(()=>weeklyRunCall({method:'POST',body:{action:'run',operation_id,owner:'other'},cookie:'x',actor:'owner'}),{code:'WEEKLY_RUN_REQUEST_INVALID'});
 await assert.rejects(()=>weeklyRunCall({method:'POST',body:{action:'run',operation_id},cookie:'x',actor:'owner',fetchImpl:async()=>new Response(JSON.stringify({status:'pending',operation_id:randomUUID()}))}),{code:'WEEKLY_HOST_RESPONSE_INVALID'});
});
test('Trio review passes only on a new authenticated run',async()=>{
 const operation_id=randomUUID();
 const trio_review={keep_model_id:'212',exclude_model_ids:['216','217'],evidence:[]};
 const body={action:'run',operation_id,trio_review};
 const options={method:'POST',cookie:'test-session',actor:'test-owner',fetchImpl:async(_url,request)=>{
  assert.deepEqual(JSON.parse(request.body),body);
  return new Response(JSON.stringify({status:'pending',operation_id}),{status:202});
 }};
 await weeklyRunCall({...options,body});
 for(const action of ['configure','reconcile','resume'])await assert.rejects(
  ()=>weeklyRunCall({...options,body:{...body,action,...(action==='configure'?{revision:0,enabled:true}:{})}}),
  {code:'WEEKLY_RUN_REQUEST_INVALID'}
 );
});
