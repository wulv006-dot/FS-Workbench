import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {canonical,digest} from '../../runtime/snapshot.mjs';
import {makeWeeklyRecommendations} from '../weekly-recommendations.mjs';
const now=()=>Date.parse('2026-11-09T10:00:00Z');
function fixture(t,status='pending'){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-history-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const body={revision:1,operation_id:randomUUID(),sbc_update:{id:'old-sbc',observed_at:'2026-11-09T09:00:00Z',expires_at:null,context:'Historical',sources:[]}};
 const prepared={model:'gpt-6.1-sol',dedupe_key:'old-dedupe',input:{source_revision:'1',sbc_update:body.sbc_update,catalog:[],pages:[]}};
 const record={operation_id:body.operation_id,submitted_by:'owner',submitted_at:new Date(now()).toISOString(),updated_at:new Date(now()).toISOString(),sbc_update:body.sbc_update,prepared,result:{status,source_revision:'1',candidates:[],publication:false}};
 const file=path.join(dir,'weekly-recommendations.json');const state={operations:[{id:body.operation_id,hash:digest(canonical(body)),request_id:body.operation_id}],requests:[record]};fs.writeFileSync(file,JSON.stringify(state));
 let calls=0;const provider=async()=>{calls++;throw Error('must not dispatch');};
 const store=makeWeeklyRecommendations({dir,contextProvider:()=>({source_revision:'1'}),provider,now});
 return {store,body,provider,file,calls:()=>calls,prepared};
}
test('new legacy operation is retired without provider call or persistence',async t=>{
 const f=fixture(t),before=fs.readFileSync(f.file,'utf8');await assert.rejects(f.store.recommend({...f.body,operation_id:randomUUID()},'owner'),{code:'WEEKLY_LEGACY_GENERATION_RETIRED_USE_WEEKLY_RUN',status:410});assert.equal(f.calls(),0);assert.equal(fs.readFileSync(f.file,'utf8'),before);
});
test('historical original ID is read-only and requires original owner and payload',async t=>{
 const f=fixture(t),before=fs.readFileSync(f.file,'utf8');assert.equal((await f.store.recommend(f.body,'owner')).status,'pending');await assert.rejects(f.store.recommend(f.body,'other'),{status:403});await assert.rejects(f.store.recommend({...f.body,revision:2},'owner'),{code:'REQUEST_CONFLICT'});assert.equal(f.calls(),0);assert.equal(fs.readFileSync(f.file,'utf8'),before);assert.equal(f.store.read().history.length,1);
});
test('historical reconcile only looks up original ID and preserves receipts',async t=>{
 const f=fixture(t);let lookups=0;f.provider.lookup=async({operation_id})=>{lookups++;assert.equal(operation_id,f.body.operation_id);return {model:'gpt-6.1-sol',source_revision:'1',sbc_update_id:'old-sbc',recommendations:[]};};f.provider.receipt={operation_id:f.body.operation_id,task_id:'task-old',run_id:'run-old',model:'gpt-6.1-sol'};
 const result=await f.store.reconcile({operation_id:f.body.operation_id},'owner');assert.equal(result.status,'completed');assert.equal(result.receipt.task_id,'task-old');assert.equal(f.calls(),0);assert.equal(lookups,1);await f.store.reconcile({operation_id:f.body.operation_id},'owner');assert.equal(lookups,1);
});
test('unknown historical outcome remains protected and never causes POST',async t=>{
 const f=fixture(t);f.provider.lookup=async()=>{throw Object.assign(Error('unknown'),{code:'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'});};assert.equal((await f.store.reconcile({operation_id:f.body.operation_id},'owner')).status,'pending');assert.equal(f.calls(),0);await assert.rejects(f.store.reconcile({operation_id:f.body.operation_id},'other'),{status:403});
});
test('confirmed original no-dispatch and failed receipts remain queryable',async t=>{
 for(const [code,provider_outcome,status] of [['WEEKLY_HERMES_PROVIDER_UNAVAILABLE','not_dispatched','unavailable'],['WEEKLY_HERMES_RECOMMENDATION_FAILED','completed','failed']]){
 const f=fixture(t);f.provider.lookup=async()=>{throw Object.assign(Error(code),{code,provider_outcome,original_outcome_confirmed:true});};assert.equal((await f.store.reconcile({operation_id:f.body.operation_id},'owner')).status,status);assert.equal(f.calls(),0);}
});
