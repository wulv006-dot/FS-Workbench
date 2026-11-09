import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {makeWeeklyCommerce} from '../weekly-commerce.mjs';
import {weeklyNativeCandidates} from '../weekly-native-candidates.mjs';
const at=Date.parse('2026-11-09T10:00:00Z'),platforms={ps:'21587',xbox:'21585',pc:'21589'};
function facts(mid,kind='player'){
 const ref={site_id:'266',game_id:'1327',model_id:mid};
 const products=Object.entries(platforms).map(([code,aid],i)=>({product_ref:{...ref,goods_id:String(Number(mid)*10+i)},platform_attribute_id:aid,region_id:'7645',raw_state:{status:1,auto_off:0},quantity:{minimum:'1',group:'1',unit:''},source_unit_price:'10.125',source_discount:'100',option_structures_observed:true,specification:{saleprop:{present:true,observed:[]},skuTableSet:{present:true,observed:[]},baseprop:{present:true,observed:[]}}}));
 const model={key:'model-266-1327-'+mid,...ref,kind,title:'Real card '+mid,platforms:Object.fromEntries(Object.entries(platforms).map(([code],i)=>[code,{state:'verified',product_ref:products[i].product_ref}]))};
 return {model,observation:{source:'admin_readonly',observed_at:new Date(at-1000).toISOString(),model:{model_id:mid,game_id:'1327',category_id:kind==='sbc'?'10203':kind==='bundle'?'10255':'9627',raw_state:{status:1,auto_off:0}},coverage:{complete:true},products}};
}
function fixture(t){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-commerce-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const old=facts('99'),entry={model_ref:{site_id:'266',game_id:'1327',model_id:'99'},category_id:'9627',baseline_region:'us',regional_adjustment:'none_verified',currency:'USD',minor_unit_scale:2,source_field:'unit_price',price_semantics:'native_discounted_item_display_total',rounding_contract:'native-js-number-format-tofixed-2',evidence_ref:'existing-fc-native-contract',max_age_ms:300000,quantity_value:'1',quantity_unit:'item',verified_goods_ids:old.observation.products.map(p=>p.product_ref.goods_id),descriptive_baseprop:true};
 const price={schema_version:2,refresh_interval_ms:60000,entries:[entry]},oldCat=weeklyNativeCandidates({source:{models:[old.model],provider_observations:[old.observation],observed_at:old.observation.observed_at},pricePolicy:price,now:at}).native_catalog_candidate;
 oldCat.valid_until='2027-10-25T15:59:59Z';const product=oldCat.products[0];
 const policy={untouched:{other_game:'preserved'},admin_reference_prices:price,native_catalog:oldCat,native_checkout:{status:'configured',verification_ref:'existing-fc-native-contract',valid_from:'2026-10-25T16:00:00Z',valid_until:'2027-10-25T15:59:59Z',origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,bindings:[{activity_id:'fc27-season2',page_id:'fc27-weekly',product_key:product.key,quantity:{value:'1',unit:'item'},attributes:[],off_percent:10,code:'FCSCOUT10',native:{category:'new_items',id:product.product_ref.goods_id,group:'1',num:'1',attr:'',aid:'21587'}}]}};
 const values=['22','23','24','25'].map(id=>facts(id,id==='25'?'sbc':'player')),key=id=>'model-266-1327-'+id;
 const draft={pages:['fc27-weekly','fc27-trio','fc27-sbc'].map(page_id=>({page_id,activity_id:'fc27-season2'})),fc_models:Object.fromEntries(values.map(v=>[v.model.key,v.model])),fc_layout:{weekly:[key('22')],trio:['22','23','24'].map(key),sbc:[key('25')],routes:{[key('25')]:{picks:['22','23'].map(key),alternatives:[key('24')]}}}};
 let bytes=Buffer.from(JSON.stringify(policy)),clock=at;const calls=[],installs=[],catalog={products:{}};
 const service=makeWeeklyCommerce({dir,catalog,readPolicy:()=>bytes,now:()=>clock,call:async request=>{calls.push(request);if(request.action==='product_read')return {product:{product_ref:values.flatMap(v=>v.observation.products).find(p=>p.product_ref.goods_id===request.goods_id).product_ref}};if(request.action==='model_resolve'){const v=values.find(v=>v.model.model_id===request.model_id);return {resolution_complete:true,model:v.model,player_type:v.player_type||'normal'};}return {readings:Object.fromEntries(values.map(v=>[v.model.model_id,{status:'ok',data:v.observation}]))};},installRunner:async({input})=>{installs.push(input);const p=JSON.parse(fs.readFileSync(path.join(dir,input.proposal_id+'.json')));return {state:'installed',operation_id:input.operation_id,candidate_sha:p.candidate_sha};}});
 return {dir,service,policy,draft,values,catalog,calls,installs,body:{operation_id:randomUUID(),revision:7,draft},setPolicy:x=>{bytes=Buffer.from(x);},getPolicy:()=>bytes,setClock:x=>{clock=x;}};
}
test('proposal reuses real observations, preserves installed policy, prices preview and never installs in prepare',async t=>{
 const f=fixture(t),before=Buffer.from(f.getPolicy()),p=await f.service.prepare(f.body,'alice');
 assert.equal(p.status,'prepared');assert.equal(p.can_publish,true);assert.equal(p.models_count,4);assert.deepEqual(f.getPolicy(),before);assert.equal(f.installs.length,0);
 assert.equal(f.calls.filter(r=>r.action==='model_resolve').length,4);assert.equal(p.preview_catalog.products.length,12);assert.equal(p.preview_catalog.model_contracts['22'].combinations[0].price.base_minor,1013);
 const candidate=JSON.parse(fs.readFileSync(p.candidate_path));assert.deepEqual(candidate.untouched,f.policy.untouched);assert.equal(candidate.admin_reference_prices.entries.length,5);assert.deepEqual(candidate.admin_reference_prices.entries[0],f.policy.admin_reference_prices.entries[0]);
 assert(candidate.native_checkout.bindings.every(b=>b.code==='FCSCOUT10'));assert.equal(f.service.validate({proposal_id:p.proposal_id,revision:7,draft:f.draft},'alice').proposal_sha,p.proposal_sha);
});
test('Signature and changed draft goods identity are blocked rather than joined to a different native SKU',async t=>{
 const f=fixture(t);f.values[0].model.platforms.ps.product_ref.goods_id='999999';
 // The frozen draft has its own identity, not the fresh resolver object.
 f.draft.fc_models['model-266-1327-22']=structuredClone(f.draft.fc_models['model-266-1327-22']);f.draft.fc_models['model-266-1327-22'].platforms.ps.product_ref.goods_id='220';
 const p=await f.service.prepare(f.body,'alice');assert.equal(p.can_publish,false);assert.deepEqual(p.blockers,['WEEKLY_COMMERCE_DRAFT_IDENTITY_CHANGED']);assert.equal(f.installs.length,0);
});
test('actual Signature fact blocks preparation without a policy write',async t=>{const f=fixture(t);f.values[0].player_type='Signature';const p=await f.service.prepare(f.body,'alice');assert.deepEqual(p.blockers,['WEEKLY_COMMERCE_NORMAL_PLAYER_REQUIRED']);assert.equal(f.installs.length,0);});
test('review owner, exact draft, policy SHA, candidate bytes and TTL remain binding',async t=>{
 const f=fixture(t),p=await f.service.prepare(f.body,'alice'),request={proposal_id:p.proposal_id,revision:7,draft:f.draft};
 assert.throws(()=>f.service.validate(request,'other'),{code:'WEEKLY_COMMERCE_OWNER_MISMATCH'});
 assert.throws(()=>f.service.validate({...request,revision:8},'alice'),{code:'WEEKLY_COMMERCE_DRAFT_CHANGED'});
 f.setPolicy(fs.readFileSync(p.candidate_path));assert.throws(()=>f.service.validate(request,'alice'),{code:'WEEKLY_COMMERCE_POLICY_CHANGED'});
 assert.equal(f.service.validate({...request,publication_operation_id:randomUUID()},'alice').proposal_id,p.proposal_id);
 f.setClock(at+300001);assert.throws(()=>f.service.validate(request,'alice'),{code:'WEEKLY_COMMERCE_PROPOSAL_EXPIRED'});
 const op=randomUUID();assert.equal((await f.service.install(p,op)).operation_id,op);assert.equal(f.installs.length,1,'installer owns original receipt recovery, never preview');
});
test('existing entries above 100 remain preserved within the reviewed bounded 300 contract',async t=>{
 const f=fixture(t);for(let i=0;i<100;i++)f.policy.admin_reference_prices.entries.push({...structuredClone(f.policy.admin_reference_prices.entries[0]),model_ref:{site_id:'266',game_id:'456',model_id:String(1000+i)}});
 f.setPolicy(JSON.stringify(f.policy));const p=await f.service.prepare(f.body,'alice');assert.equal(p.can_publish,true);assert.equal(p.diff.price_entries,105);
});
test('legacy selected bundles resolve actual goods to model identity and platform masks stay exact',async t=>{
 const f=fixture(t),bundle=facts('60','bundle');f.values.push(bundle);
 f.catalog.products.legacy={kind:'bundle',platforms:Object.fromEntries(Object.entries(bundle.model.platforms).map(([code,p])=>[code,{id:Number(p.product_ref.goods_id)}]))};f.draft.fc_layout.bundles=['legacy'];
 f.draft.pages[0].product_keys=['fc-model-266-1327-22-ps'];
 const p=await f.service.prepare(f.body,'alice');assert.equal(p.can_publish,true);assert.equal(p.models_count,5);assert(p.preview_catalog.model_contracts['60']);assert.equal(f.calls.filter(r=>r.action==='product_read').length,1);
 const policy=JSON.parse(fs.readFileSync(p.candidate_path));assert.equal(policy.native_checkout.bindings.filter(b=>b.page_id==='fc27-weekly'&&b.native.id.startsWith('22')).length,1);
});
test('the bounded capacity contract blocks without dropping original price entries',async t=>{
 const f=fixture(t);for(let i=0;i<297;i++)f.policy.admin_reference_prices.entries.push({...structuredClone(f.policy.admin_reference_prices.entries[0]),model_ref:{site_id:'266',game_id:'456',model_id:String(1000+i)}});
 f.setPolicy(JSON.stringify(f.policy));const before=Buffer.from(f.getPolicy()),p=await f.service.prepare(f.body,'alice');assert.deepEqual(p.blockers,['WEEKLY_COMMERCE_CAPACITY_EXCEEDED']);assert.deepEqual(f.getPolicy(),before);assert.equal(f.installs.length,0);
});
