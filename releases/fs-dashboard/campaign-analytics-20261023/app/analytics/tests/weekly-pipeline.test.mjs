import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {weeklyRuntime} from './weekly-runtime-fixture.mjs';
import {startWeeklyBridge,callWeeklyBridge} from '../weekly-bridge.mjs';

const model=(id,kind='player')=>({key:'model-266-1327-'+id,site_id:'266',game_id:'1327',model_id:id,kind,title:'Fixture Player '+id+'/Edition '+id,version_label:'Edition '+id,image_url:null,image_provenance:null,site_association:'observed',verification_scope:'catalog_identity_only',available:false,authoritative:false,checkout_enabled:false,
 platforms:Object.fromEntries(['ps','xbox','pc'].map((p,i)=>[p,{state:'verified',product_ref:{site_id:'266',game_id:'1327',model_id:id,goods_id:id+String(i)},observed_quantity:{minimum:'1',group:'1',unit:''}}]))});
function fixture(t,{enabledProvider=()=>true}={}){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-pipeline-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));let reads=0;
 const source={rules_version:'fc27_weekly_selection_v1',observed_at:new Date().toISOString(),models:['11','12','13','14'].map(id=>model(id)).concat(model('20','sbc')),latest_player_ids:['14','13','12','11'],trio_player_ids:['14','13','12'],scout_model_ids:['11','12','13'],sbc_model_ids:['20'],evidence:{popular_tag_id:'12305'}};
 const pipeline=weeklyRuntime({dir,enabledProvider,publicDir:path.join(dir,'public'),sourceProvider:async()=>{reads++;return source;}});return {dir,pipeline,source,reads:()=>reads};}
function response(prepared){const p=prepared.input.pages,rows=[];for(const page of p){if(page.page_id==='fc27-sbc')for(const core of page.core_product_keys)for(const key of p.find(p=>p.page_id==='fc27-trio').product_keys)rows.push({page_id:page.page_id,product_key:key,core_product_key:core,reason:'Fixture',evidence_indices:[0]});else for(const key of page.product_keys)rows.push({page_id:page.page_id,product_key:key,core_product_key:null,reason:'Fixture',evidence_indices:[0]});}
 return {model:'gpt-6.1-sol',source_revision:prepared.input.source_revision,sbc_update_id:prepared.input.sbc_update.id,recommendations:rows};}
const sources=()=>[{url:'https://example.com/football',title:'Fixture source',observed_at:new Date(Date.now()-1000).toISOString()}];
test('real center runtime imports fresh identities and saves three layouts once without publishing',async t=>{const f=fixture(t),operation_id=randomUUID(),p=await f.pipeline.prepare({operation_id},'fixture');assert.equal(f.reads(),1);assert.deepEqual(await f.pipeline.prepare({operation_id},'fixture'),p);assert.equal(f.reads(),1);
 const request={operation_id,plan_ref:p.plan_ref,recommendation:response(p),evidence_sources:sources()},saved=f.pipeline.apply(request,'fixture');assert.equal(saved.status,'draft_saved');assert.equal(saved.draft_revision,1);assert.deepEqual(f.pipeline.apply(request,'fixture'),saved);
 const state=JSON.parse(fs.readFileSync(path.join(f.dir,'center/state.json')));assert.equal(state.published,null);assert.deepEqual(state.draft.fc_layout.weekly,['11','12','13'].map(id=>'model-266-1327-'+id));assert.equal(state.draft.fc_layout.routes['model-266-1327-20'].alternatives.length,1);assert.equal(Object.keys(state.draft.fc_models).length,5);assert(state.draft.fc_models['model-266-1327-14'].available===false);
 assert.throws(()=>f.pipeline.apply({...request,recommendation:{...request.recommendation,model:'other'}},'fixture'),{code:'REQUEST_CONFLICT'});
});
test('owner and exact Scout order, Trio sources, and stale center scope are enforced',async t=>{const f=fixture(t),operation_id=randomUUID(),p=await f.pipeline.prepare({operation_id},'fixture');await assert.rejects(()=>f.pipeline.prepare({operation_id},'other'),{code:'WEEKLY_OPERATION_OWNER_MISMATCH'});
 const request={operation_id,plan_ref:p.plan_ref,recommendation:response(p),evidence_sources:sources()};assert.throws(()=>f.pipeline.apply(request,'other'),{code:'WEEKLY_OPERATION_OWNER_MISMATCH'});
 const bad=structuredClone(request),rows=bad.recommendation.recommendations,indices=rows.map((r,i)=>r.page_id==='fc27-weekly'?i:-1).filter(i=>i>=0);[rows[indices[0]],rows[indices[1]]]=[rows[indices[1]],rows[indices[0]]];assert.throws(()=>f.pipeline.apply(bad,'fixture'),{code:'WEEKLY_SELECTION_RULE_MISMATCH'});
 assert.throws(()=>f.pipeline.apply({...request,evidence_sources:[]},'fixture'),{code:'INVALID_WEEKLY_HERMES_INPUT'});
 const second=await f.pipeline.prepare({operation_id:randomUUID()},'fixture');f.pipeline.apply(request,'fixture');assert.throws(()=>f.pipeline.apply({operation_id:second.operation_id,plan_ref:second.plan_ref,recommendation:response(second),evidence_sources:sources()},'fixture'),{code:'REVISION_CONFLICT'});
});
test('read-only inspect recovers original center receipt after weekly response interruption without a second save',async t=>{const f=fixture(t),operation_id=randomUUID(),p=await f.pipeline.prepare({operation_id},'fixture'),request={operation_id,plan_ref:p.plan_ref,recommendation:response(p),evidence_sources:sources()};
 assert.equal(f.pipeline.inspect(request,'fixture').status,'not_found');f.pipeline.apply(request,'fixture');
 const planFile=path.join(f.dir,'center/weekly-plans',operation_id+'.json'),plan=JSON.parse(fs.readFileSync(planFile));delete plan.applied;fs.writeFileSync(planFile,JSON.stringify(plan));
 const before=fs.readFileSync(path.join(f.dir,'center/state.json'),'utf8'),result=f.pipeline.inspect(request,'fixture');assert.equal(result.status,'draft_saved');assert.equal(result.draft_revision,1);assert.equal(fs.readFileSync(path.join(f.dir,'center/state.json'),'utf8'),before);assert(!JSON.parse(fs.readFileSync(planFile)).applied);
 assert.equal(f.pipeline.apply(request,'fixture').draft_revision,1);assert.equal(fs.readFileSync(path.join(f.dir,'center/state.json'),'utf8'),before);
});
test('helper switch prevents source work and draft mutation without disabling original receipt inspection',async t=>{let enabled=false;const f=fixture(t,{enabledProvider:()=>enabled}),operation_id=randomUUID();assert.equal((await f.pipeline.prepare({operation_id},'fixture')).status,'disabled');assert.equal(f.reads(),0);
 enabled=true;const p=await f.pipeline.prepare({operation_id},'fixture');enabled=false;const body={operation_id,plan_ref:p.plan_ref,recommendation:response(p),evidence_sources:sources()};assert.equal(f.pipeline.apply(body,'fixture').status,'disabled');assert.equal(f.pipeline.inspect(body,'fixture').status,'not_found');assert(!fs.existsSync(path.join(f.dir,'center/state.json')));
});
test('local IPC applies on the one original center writer and concurrent stale requests cannot overwrite',async t=>{const f=fixture(t),socketPath=process.platform==='win32'?'\\\\.\\pipe\\fc-weekly-'+randomUUID():path.join(f.dir,'ipc','weekly.sock'),bridge=await startWeeklyBridge({pipeline:f.pipeline,socketPath});t.after(()=>new Promise(resolve=>bridge.close(resolve)));
 const call=body=>callWeeklyBridge({contract:'campaign_weekly_run_v1',owner:'fixture',...body},{socketPath});const plans=await Promise.all([1,2].map(()=>call({action:'prepare',operation_id:randomUUID()})));
 const results=await Promise.all(plans.map(p=>call({action:'apply_draft',operation_id:p.operation_id,plan_ref:p.plan_ref,recommendation:response(p),evidence_sources:sources()})));
 assert.equal(results.filter(r=>r.status==='draft_saved').length,1);assert.equal(results.filter(r=>r.error==='REVISION_CONFLICT').length,1);assert.equal(JSON.parse(fs.readFileSync(path.join(f.dir,'center/state.json'))).revision,1);
 const saved=results.find(r=>r.status==='draft_saved');assert.equal((await call({action:'inspect_operation',operation_id:saved.operation_id,plan_ref:saved.plan_ref})).draft_revision,1);
});
test('later weekly refresh updates selected existing model facts with an immutable digest and preserves other configuration',async t=>{const f=fixture(t),first=await f.pipeline.prepare({operation_id:randomUUID()},'fixture');f.pipeline.apply({operation_id:first.operation_id,plan_ref:first.plan_ref,recommendation:response(first),evidence_sources:sources()},'fixture');
 f.source.models[0].title='Updated real title / Card edition';f.source.models[0].platforms.pc.state='offline';const next=await f.pipeline.prepare({operation_id:randomUUID()},'fixture'),request={operation_id:next.operation_id,plan_ref:next.plan_ref,recommendation:response(next),evidence_sources:sources()};const saved=f.pipeline.apply(request,'fixture');assert.equal(saved.draft_revision,2);
 const state=JSON.parse(fs.readFileSync(path.join(f.dir,'center/state.json')));assert.equal(state.draft.fc_models['model-266-1327-11'].title,f.source.models[0].title);assert.equal(state.draft.fc_models['model-266-1327-11'].platforms.pc.state,'offline');assert.match(state.last_operation.model_refresh_digest,/^[a-f0-9]{64}$/);assert.equal(f.pipeline.apply(request,'fixture').draft_revision,2);assert.equal(state.draft.seasonal_theme,'halloween');
});

