import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
import {makeWeeklyWorkflow} from '../weekly-workflow.mjs';
import {makeCenterStore} from '../center-store.mjs';
import {makeWeeklyStore} from '../weekly-store.mjs';

function fixture(t){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-workflow-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const run=randomUUID(),draft={pages:['fc27-weekly','fc27-sbc','fc27-trio','seasonal-vault'].map(page_id=>({page_id,title:page_id,benefit_refs:page_id.startsWith('fc27-')?[{kind:'discount',native_id:'6049'}]:[]})),seasonal_theme:'halloween'};
 let state={revision:2,draft,published:null},clock=Date.now(),installed=0,publishes=0,linked=0,failRecord=false,policy='before',validationError=null,previewRound=0;const receipts=new Map();
 const center={read:()=>structuredClone(state),recoverPublish:r=>receipts.get(r.operation_id)||null,publish(r,owner){assert.equal(r.revision,state.revision);publishes++;state={...state,revision:state.revision+1,updated_by:owner,published:{release_id:'campaign-preview-'+(state.revision+1),config_hash:'a'.repeat(64),rule_hash:'b'.repeat(64)},last_operation:{operation_id:r.operation_id,kind:'publish'}};receipts.set(r.operation_id,structuredClone(state));return structuredClone(state);}};
 const weekly={syncDraft(){linked++;return {weeks:[]};},read:()=>({weeks:[]}),recordConfirmation(){},recordPublication(){if(failRecord)throw Error('RECORD_INTERRUPTED');}};
 const pipeline={workflowPlan(id,owner){assert.equal(id,run);if(owner!=='owner')throw Object.assign(Error('WEEKLY_OPERATION_OWNER_MISMATCH'),{code:'WEEKLY_OPERATION_OWNER_MISMATCH',status:403});return {operation_id:run,owner,created_at:new Date(clock).toISOString(),draft:structuredClone(draft),applied:{result:{draft_revision:2}}};}};
 const workflow=makeWeeklyWorkflow({dir,center,weekly,pipeline,now:()=>clock,prepareCommerce:async()=>({can_publish:true,blockers:[],status:'prepared',policy_before_sha:policy,candidate_sha:'after',expires_at:new Date(clock+60000).toISOString()}),validateCommerce:p=>{if(validationError)throw validationError;if(policy!==p.policy_before_sha)throw Object.assign(Error('WEEKLY_COMMERCE_POLICY_CHANGED'),{code:'WEEKLY_COMMERCE_POLICY_CHANGED',status:409});return p;},installCommerce:async()=>{installed++;policy='after';},makePreviews:()=>{previewRound++;return draft.pages.slice(0,3).map(p=>({...p,preview_url:'/preview/'+previewRound+'/'+p.page_id}));},readPublic:()=>state.published});
 return {run,workflow,dir,validationError:e=>{validationError=e;},state:()=>state,change:()=>{state.revision++;},expire:()=>{clock+=60001;},policyChange:()=>{policy='other';},failRecord:v=>{failRecord=v;},counts:()=>({installed,publishes,linked})};
}
const review=f=>f.workflow.review({action:'review',operation_id:randomUUID(),run_operation_id:f.run},'owner');
const request=(f,r)=>({action:'publish',operation_id:randomUUID(),run_operation_id:f.run,revision:r.revision,review_hash:r.review_hash,confirmed:true});
test('review creates three previews and links records, but never installs or publishes; explicit confirmation publishes once',async t=>{
 const f=fixture(t),r=await review(f);assert.equal(r.previews.length,3);assert.equal(r.can_publish,true);assert.deepEqual(f.counts(),{installed:0,publishes:0,linked:1});
 const body=request(f,r);await assert.rejects(()=>f.workflow.publish({...body,confirmed:false},'owner'));
 const result=await f.workflow.publish(body,'owner');assert.equal(result.publication.readback.status,'verified');assert.equal(result.publication.operation_id,body.operation_id);
 assert.deepEqual(await f.workflow.publish(body,'owner'),result);assert.deepEqual(f.counts(),{installed:1,publishes:1,linked:1});
 assert.equal((await review(f)).can_publish,false);assert.equal(f.workflow.read(f.run,'owner').publication.operation_id,body.operation_id);assert.equal(f.counts().publishes,1);
 await assert.rejects(()=>f.workflow.publish({...body,revision:999},'owner'),{code:'REQUEST_CONFLICT'});
});
test('changed draft, expired review, changed policy, and different actor cannot publish',async t=>{
 for(const change of ['change','expire','policyChange']){const f=fixture(t),r=await review(f);f[change]();await assert.rejects(()=>f.workflow.publish(request(f,r),'owner'));assert.equal(f.counts().publishes,0);assert.equal(f.counts().installed,0);}
 const f=fixture(t),r=await review(f);await assert.rejects(()=>f.workflow.publish(request(f,r),'other'),{code:'WEEKLY_OPERATION_OWNER_MISMATCH'});
});
test('original center receipt recovers interrupted record write after expiry without installing or publishing twice',async t=>{
 const f=fixture(t),r=await review(f),body=request(f,r);f.failRecord(true);await assert.rejects(()=>f.workflow.publish(body,'owner'));assert.equal(f.counts().publishes,1);
 f.expire();f.failRecord(false);const result=await f.workflow.publish(body,'owner');assert.equal(result.publication.readback.status,'verified');assert.equal(f.counts().installed,1);assert.equal(f.counts().publishes,1);
});
test('real center transaction and weekly ledger recover an interrupted public-pointer write through one approval and receipt',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-workflow-center-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));let interrupted=false,installs=0;
 const center=makeCenterStore({dir:path.join(dir,'center'),publicDir:path.join(dir,'public'),sourceRevision:'fixture',checkpoint:stage=>{if(stage==='public-pointer'&&!interrupted){interrupted=true;throw Error('INTERRUPTED');}}});
 const draft=center.read().draft;draft.pages.filter(p=>p.page_id.startsWith('fc27-')).forEach(p=>p.benefit_refs=[{kind:'discount',native_id:'6049'}]);center.save({operation_id:randomUUID(),revision:0,draft},'owner');
 const run=randomUUID(),weekly=makeWeeklyStore({dir:path.join(dir,'center'),centerProvider:()=>center.read()});weekly.syncRun({operation_id:run,owner:'owner',draft_revision:1,created_at:'2026-11-09T10:00:00Z'});
 const workflow=makeWeeklyWorkflow({dir:path.join(dir,'workflow'),center,weekly,pipeline:{workflowPlan:()=>({operation_id:run,owner:'owner',draft,applied:{result:{draft_revision:1}}})},prepareCommerce:async()=>({can_publish:true,status:'ready'}),validateCommerce:p=>p,installCommerce:async()=>{installs++;},makePreviews:()=>[],readPublic:()=>JSON.parse(fs.readFileSync(path.join(dir,'public/current.json')))});
 const r=await workflow.review({action:'review',operation_id:randomUUID(),run_operation_id:run},'owner'),body={action:'publish',operation_id:randomUUID(),run_operation_id:run,revision:1,review_hash:r.review_hash,confirmed:true};
 await assert.rejects(()=>workflow.publish(body,'owner'),/INTERRUPTED/);assert(weekly.read().weeks.every(w=>w.approval.status==='approved'));
 const result=await workflow.publish(body,'owner');assert.equal(installs,1);assert.equal(result.publication.revision,2);assert.equal(result.work_orders.length,3);
 for(const w of weekly.read().weeks){assert.equal(w.status,'published');assert.equal(w.approval_history.length,1);assert.equal(w.run_history[0].publications.length,1);assert.equal(w.run_history[0].publications[0].publication_operation_id,body.operation_id);assert.equal(w.stage_status.deployed_readback,'pass');assert.equal(w.stage_status.production_verified,'evidence_gap');}
});

test('completed review read restores confirmation without preparing, linking or writing again',async t=>{
 const f=fixture(t),r=await review(f),before=Object.fromEntries(fs.readdirSync(f.dir).map(n=>[n,fs.readFileSync(path.join(f.dir,n),'utf8')])),counts=f.counts();
 const restored=f.workflow.read(f.run,'owner');assert.equal(restored.can_publish,true);assert.equal(restored.requires_review,false);assert.equal(restored.review_hash,r.review_hash);assert.equal(restored.expires_at,r.expires_at);assert.equal(restored.previews.length,3);assert.notDeepEqual(restored.previews,r.previews);
 assert.deepEqual(f.counts(),counts);assert.deepEqual(Object.fromEntries(fs.readdirSync(f.dir).map(n=>[n,fs.readFileSync(path.join(f.dir,n),'utf8')])),before);
});
test('read requires review after expiry, revision, draft hash or policy change and rejects another owner',async t=>{
 for(const change of ['expire','change','policyChange','hash']){const f=fixture(t);await review(f);if(change==='hash')f.state().draft.seasonal_theme='changed';else f[change]();const r=f.workflow.read(f.run,'owner');assert.equal(r.can_publish,false,change);assert.equal(r.requires_review,true,change);assert.equal(f.counts().installed,0);assert.equal(f.counts().publishes,0);}
 const f=fixture(t);await review(f);assert.throws(()=>f.workflow.read(f.run,'other'),{code:'WEEKLY_OPERATION_OWNER_MISMATCH'});
});

test('read only downgrades known stale commerce evidence; corruption and proposal owner errors remain errors',async t=>{
 for(const code of ['WEEKLY_COMMERCE_PROPOSAL_EXPIRED','WEEKLY_COMMERCE_DRAFT_CHANGED','WEEKLY_COMMERCE_POLICY_CHANGED']){const f=fixture(t);await review(f);f.validationError(Object.assign(Error(code),{code}));assert.equal(f.workflow.read(f.run,'owner').requires_review,true);}
 for(const code of ['EIO','WEEKLY_COMMERCE_CANDIDATE_CHANGED','WEEKLY_COMMERCE_OWNER_MISMATCH']){const f=fixture(t);await review(f);f.validationError(Object.assign(Error(code),{code}));assert.throws(()=>f.workflow.read(f.run,'owner'),{code});}
});
