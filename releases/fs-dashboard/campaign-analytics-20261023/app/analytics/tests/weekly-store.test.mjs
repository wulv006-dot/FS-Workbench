import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {makeWeeklyStore,weeklyPages,WEEKLY_PAGES} from '../weekly-store.mjs';
const clock=Date.parse('2026-11-09T04:00:00Z');
function context(){return {revision:7,draft:{pages:Object.keys(WEEKLY_PAGES).map(page_id=>({page_id,activity_id:'fc27-season2',benefit_refs:[]}))},page_bindings:Object.fromEntries(Object.keys(WEEKLY_PAGES).map(id=>[id,{product_keys:['fc-player-ps']}])),catalog_products:[{key:'fc-player-ps',title:'Test player',product_ref:{site_id:'266',game_id:'1327',goods_id:'12'},platform:{code:'ps',attribute_id:'21587'},available:false,quantity:{min:'1',max:'1',step:'1',unit:'item'},attributes:[]}],published:{mode:'preview',release_id:'test'}};}
function setup(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'fc-weekly-')),center=context();t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return {dir,center,store:makeWeeklyStore({dir,centerProvider:()=>center,now:()=>clock})};}
const request=(store,action,extra={})=>({revision:store.read().revision,operation_id:randomUUID(),action,id:'2026-W46',page_id:'fc27-sbc',...extra});

test('three pages derive source revisions and preserve evidence gaps instead of inheriting Halloween proof',()=>{
 const pages=weeklyPages(context(),{now:clock});assert.equal(pages.length,3);
 for(const page of pages){assert.equal(page.stage_status.production_verified,'evidence_gap');assert.equal(page.stage_status.deployed_readback,'evidence_gap');assert.equal(page.checks.find(c=>c.key==='identity').status,'pass');assert.equal(page.checks.find(c=>c.key==='sellable').status,'pending');assert.equal(page.checks.find(c=>c.key==='price').status,'pending');assert.equal(page.checks.find(c=>c.key==='coupon').status,'pending');}
});
test('persistent CAS and same-operation replay do not duplicate a week',t=>{
 const {store,dir,center}=setup(t),body=request(store,'create');assert.equal(store.mutate(body,'admin').revision,1);
 const fresh=makeWeeklyStore({dir,centerProvider:()=>center,now:()=>clock});assert.equal(fresh.mutate(body,'admin').weeks.length,1);
 assert.throws(()=>fresh.mutate({...body,page_id:'fc27-trio'},'admin'),e=>e.code==='REQUEST_CONFLICT');
 assert.throws(()=>fresh.mutate({...body,operation_id:randomUUID()},'admin'),e=>e.code==='REVISION_CONFLICT');
 assert.throws(()=>fresh.mutate(request(fresh,'create'),'admin'),e=>e.code==='WEEK_ALREADY_EXISTS');
});
test('manual evidence cannot claim verified production or write protected fields',t=>{
 const {store}=setup(t);store.mutate(request(store,'create'),'admin');
 const evidence=request(store,'evidence',{stage:'production_verified',reference:'manual-note-1',note:'Operator reported test'});
 assert.throws(()=>store.mutate({...evidence,verification:'verified'},'admin'),e=>e.code==='INVALID_WEEKLY_REQUEST');
 const result=store.mutate(evidence,'admin');assert.equal(result.weeks[0].evidence[0].verification,'reported');assert.equal(result.weeks[0].stage_status.production_verified,'evidence_gap');
 for(const action of ['publish','coupon_write','schedule_enable','rollback'])assert.throws(()=>store.mutate(request(store,action),'admin'),e=>e.code==='INVALID_WEEKLY_ACTION');
});
test('approval is explicit, revision-bound and never executes a production operation',t=>{
 const {store,center}=setup(t);store.mutate(request(store,'create'),'admin');
 assert.throws(()=>store.mutate(request(store,'approval',{scope:'publish',decision:'approved',note:'reviewed'}),'admin'),e=>e.code==='APPROVAL_REQUEST_REQUIRED');
 store.mutate(request(store,'approval',{scope:'publish',decision:'requested',note:'request'}),'admin');
 let state=store.mutate(request(store,'approval',{scope:'publish',decision:'approved',note:'reviewed'}),'admin');assert.equal(state.weeks[0].approval.status,'approved');assert.equal(state.weeks[0].stage_status.production_verified,'evidence_gap');assert.equal(center.revision,7);
 center.revision=8;assert.equal(store.read().weeks[0].approval.stale,true);
});
test('stale requested approval cannot be accepted and updates invalidate approvals',t=>{
 const {store,center}=setup(t);store.mutate(request(store,'create'),'admin');store.mutate(request(store,'approval',{scope:'publish',decision:'requested',note:''}),'admin');center.revision++;
 assert.throws(()=>store.mutate(request(store,'approval',{scope:'publish',decision:'approved',note:''}),'admin'),e=>e.code==='APPROVAL_STALE');
 const state=store.mutate(request(store,'update',{activity_revision:8,notes:'New version reviewed'}),'admin');assert.equal(state.weeks[0].approval,null);assert.equal(state.weeks[0].activity_revision,8);
});
test('pause and retry only change local plan state and retain operation identity',t=>{
 const {store}=setup(t);const initial=store.mutate(request(store,'create'),'admin').weeks[0];store.mutate(request(store,'pause'),'admin');const retried=store.mutate(request(store,'retry'),'admin').weeks[0];assert.equal(retried.status,'planned');assert.equal(retried.operationId,initial.operationId);assert.equal(retried.approval,null);
 assert.throws(()=>store.mutate(request(store,'retry'),'admin'),e=>e.code==='WEEK_NOT_RETRYABLE');
});
test('unknown execution blocks retry along original operation',t=>{
 const {store,dir}=setup(t);store.mutate(request(store,'create'),'admin');store.mutate(request(store,'pause'),'admin');
 const file=path.join(dir,'weekly-operations.json'),state=JSON.parse(fs.readFileSync(file));state.weeks[0].execution={status:'unknown',operation_id:randomUUID()};fs.writeFileSync(file,JSON.stringify(state));
 assert.throws(()=>store.mutate(request(store,'retry'),'admin'),e=>e.code==='ORIGINAL_OPERATION_RECONCILIATION_REQUIRED');
});
test('Hermes toggle does not enable scheduler or claim a provider connection',t=>{
 const {store}=setup(t);const result=store.mutate({revision:0,operation_id:randomUUID(),action:'hermes',enabled:true},'admin');assert.equal(result.hermes.status,'not_connected');assert.equal(result.hermes.schedule_enabled,false);assert.equal(result.hermes.model,'gpt-6.1-sol');assert.deepEqual(result.weeks,[]);
 assert.throws(()=>store.mutate({revision:1,operation_id:randomUUID(),action:'hermes',enabled:true,model:'other'},'admin'),e=>e.code==='INVALID_WEEKLY_REQUEST');
});
test('invalid scope, unsafe notes and invented revisions are refused',t=>{
 const {store}=setup(t);assert.throws(()=>store.mutate(request(store,'create',{id:'../../state'}),'admin'));assert.throws(()=>store.mutate(request(store,'create',{page_id:'seasonal-vault'}),'admin'));
 store.mutate(request(store,'create'),'admin');assert.throws(()=>store.mutate(request(store,'update',{notes:'<script>'}),'admin'));assert.throws(()=>store.mutate(request(store,'update',{product_revision:'invented'}),'admin'),e=>e.code==='CURRENT_REVISION_REQUIRED');
});
test('current price checks expire and invalid native configuration remains a failure',()=>{
 const c=context();c.catalog_products[0].product_ref.model_id='99';c.price_contracts={x:{verified:true,catalog_version:'admin-'+new Date(clock).toISOString(),model_ref:{site_id:'266',game_id:'1327',model_id:'99'},combinations:[{product_key:'fc-player-ps',choices:{platform:'21587',region:'9'},quantity:c.catalog_products[0].quantity,attributes:[],price:{source:'admin_current',base_minor:1200,currency:'USD',minor_unit_scale:2,quantity_value:'1',expires_at:new Date(clock+1000).toISOString()}}]}};
 assert.equal(weeklyPages(c,{now:clock})[0].checks.find(c=>c.key==='price').status,'pass');assert.equal(weeklyPages(c,{now:clock+1000})[0].checks.find(c=>c.key==='price').status,'pending');
 c.native_checkout={status:'configured'};assert.equal(weeklyPages(c,{now:clock})[0].checks.find(c=>c.key==='sellable').status,'fail');
});

test('trusted runtime receipt adapter checks revision, release and natural trigger',t=>{
 const {store,center}=setup(t);store.mutate(request(store,'create'),'admin');
 const receipt={revision:1,operation_id:randomUUID(),id:'2026-W46',page_id:'fc27-sbc',stage:'test_available',reference:'test-report-1',activity_revision:7,source:'isolated-test-runner',result:'passed',product_revision:store.read().weeks[0].product_revision,coupon_revision:store.read().weeks[0].coupon_revision,plan_operation_id:store.read().weeks[0].operationId};
 let result=store.recordEvidence(receipt);assert.equal(result.weeks[0].stage_status.test_available,'pass');assert.equal(result.weeks[0].stage_status.production_verified,'evidence_gap');assert.equal(store.recordEvidence(receipt).revision,2);
 assert.throws(()=>store.recordEvidence({...receipt,revision:2,operation_id:randomUUID(),stage:'natural_weekly_run',trigger:'manual'}),e=>e.code==='NATURAL_RUN_PROOF_REQUIRED');
 assert.throws(()=>store.recordEvidence({...receipt,revision:2,operation_id:randomUUID(),stage:'deployed_readback',release_id:'invented',config_hash:'invented'}),e=>e.code==='PUBLISH_RECEIPT_MISMATCH');
 center.published={release_id:'r7',config_hash:'hash7'};
 result=store.recordEvidence({...receipt,revision:2,operation_id:randomUUID(),stage:'deployed_readback',release_id:'r7',config_hash:'hash7'});assert.equal(result.weeks[0].stage_status.deployed_readback,'pass');
 assert.throws(()=>store.mutate({revision:3,operation_id:randomUUID(),action:'runtime_evidence',...receipt},'admin'),e=>e.code==='INVALID_WEEKLY_ACTION');
});

test('price cannot reuse another platform, quantity, future observation or currency',()=>{
 const c=context(),p=c.catalog_products[0];p.product_ref.model_id='99';
 c.price_contracts={x:{verified:true,catalog_version:'admin-'+new Date(clock).toISOString(),model_ref:{site_id:'266',game_id:'1327',model_id:'99'},combinations:[{product_key:p.key,choices:{platform:'21587',region:'9'},quantity:p.quantity,attributes:[],price:{source:'admin_current',base_minor:1200,currency:'USD',minor_unit_scale:2,quantity_value:'1',expires_at:new Date(clock+1000).toISOString()}}]}};
 for(const mutate of [x=>x.x.catalog_version='admin-'+new Date(clock+1).toISOString(),x=>x.x.combinations[0].price.currency='GBP',x=>x.x.combinations[0].choices.platform='21589',x=>x.x.combinations[0].quantity={...p.quantity,min:'2'},x=>x.x.combinations[0].price.quantity_value='100']){
  const candidate=structuredClone(c);mutate(candidate.price_contracts);assert.equal(weeklyPages(candidate,{now:clock})[0].checks.find(c=>c.key==='price').status,'pending');
 }
});
test('unknown runtime reconciles the original execution ID and never clears it through a new attempt',t=>{
 const {store}=setup(t);store.mutate(request(store,'create'),'admin');const week=store.read().weeks[0],executionId=randomUUID();
 const r={revision:1,operation_id:randomUUID(),id:week.id,page_id:week.page_id,stage:'production_verified',reference:'runtime-readback',activity_revision:week.activity_revision,product_revision:week.product_revision,coupon_revision:week.coupon_revision,plan_operation_id:week.operationId,source:'trusted-runner',execution_operation_id:executionId,result:'unknown'};
 assert.equal(store.recordEvidence(r).weeks[0].stage_status.production_verified,'unknown');
 assert.throws(()=>store.recordEvidence({...r,revision:2,operation_id:randomUUID(),execution_operation_id:randomUUID(),result:'passed'}),e=>e.code==='ORIGINAL_OPERATION_RECONCILIATION_REQUIRED');
 const confirmed=store.recordEvidence({...r,revision:2,operation_id:randomUUID(),result:'passed'});assert.equal(confirmed.weeks[0].execution.operation_id,executionId);assert.equal(confirmed.weeks[0].stage_status.production_verified,'pass');
});


test('platform code must match the actual FC platform attribute',()=>{
 const c=context();c.catalog_products[0].platform={code:'ps',attribute_id:'21589'};
 assert.equal(weeklyPages(c,{now:clock})[0].checks.find(c=>c.key==='platform').status,'pending');
 c.catalog_products[0].platform={code:'pc',attribute_id:'21589'};
 assert.equal(weeklyPages(c,{now:clock})[0].checks.find(c=>c.key==='platform').status,'pass');
});
test('current release receipt cannot verify a historical week from another center revision',t=>{
 const {store,center}=setup(t);store.mutate(request(store,'create'),'admin');const week=store.read().weeks[0];
 center.revision=8;center.published={release_id:'release8',config_hash:'hash8'};
 const receipt={revision:1,operation_id:randomUUID(),id:week.id,page_id:week.page_id,stage:'deployed_readback',reference:'release8-readback',activity_revision:week.activity_revision,source:'trusted-runner',release_id:'release8',config_hash:'hash8',result:'passed',product_revision:week.product_revision,coupon_revision:week.coupon_revision,plan_operation_id:week.operationId};
 assert.throws(()=>store.recordEvidence(receipt),e=>e.code==='PUBLISH_RECEIPT_MISMATCH');
 assert.equal(store.read().weeks[0].stage_status.deployed_readback,'evidence_gap');
});
