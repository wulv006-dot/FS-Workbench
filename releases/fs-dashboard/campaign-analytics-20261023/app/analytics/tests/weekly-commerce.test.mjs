import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import vm from 'node:vm';
import {createSnapshot} from '../../runtime/snapshot.mjs';
import {createPublicServer} from '../../runtime/server.mjs';
import {makeWeeklyCommerce} from '../weekly-commerce.mjs';
import {weeklyNativeCandidates} from '../weekly-native-candidates.mjs';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';
import {centerSeed} from '../center-seed.mjs';
import {previewCatalog,validateLayout} from '../store.mjs';
import {effectiveFcCatalog} from '../../runtime/model-cards.mjs';
import {mergeNativeCatalog,readNativeLaunchPolicy} from '../native-catalog.mjs';
import {projectFcCatalog} from '../../runtime/presentation.mjs';
import {makeAdminPriceProvider} from '../admin-price-provider.mjs';
import {applyPublicPriceCache} from '../../runtime/admin-price-cache.mjs';
import core from '../../activity-core.js';
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
 const discount={kind:'discount',native_id:'6049',scope_status:'exact_site',before_hash:'a'.repeat(64),fields:{code:'FCSCOUT10',uid:0,status:1,type:1,discount:'90.00',attain:'0.00',site_id:266,gid:['1327'],cid:['2'],exclude_gids:[],aid:0,repeat_qty:0,timestart:'2026-10-26 00:00:00',timeend:'2027-10-25 23:59:59'}};
 const service=makeWeeklyCommerce({dir,catalog,readPolicy:()=>bytes,now:()=>clock,call:async request=>{calls.push(request);if(request.action==='benefit_detail')return discount;if(request.action==='product_read')return {product:{product_ref:values.flatMap(v=>v.observation.products).find(p=>p.product_ref.goods_id===request.goods_id).product_ref}};if(request.action==='model_resolve'){const v=values.find(v=>v.model.model_id===request.model_id);return {resolution_complete:true,model:v.model,player_type:v.player_type||'normal'};}return {readings:Object.fromEntries(values.map(v=>[v.model.model_id,{status:'ok',data:v.observation}]))};},installRunner:async({input})=>{installs.push(input);const p=JSON.parse(fs.readFileSync(path.join(dir,input.proposal_id+'.json')));return {state:'installed',operation_id:input.operation_id,candidate_sha:p.candidate_sha};}});
 return {dir,service,policy,draft,values,catalog,discount,calls,installs,body:{operation_id:randomUUID(),revision:7,draft},setPolicy:x=>{bytes=Buffer.from(x);},getPolicy:()=>bytes,setClock:x=>{clock=x;}};
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
test('preparation verifies the exact live discount identity, rules, FC27 Items scope and Shanghai window',async t=>{
 const mutations=[f=>{delete f.code;},f=>f.code='WRONG',f=>f.uid=8,f=>f.type=2,f=>f.status=0,f=>f.discount='80.00',f=>f.site_id=0,f=>f.gid=['1327','456'],f=>f.cid=['1','2'],f=>f.exclude_gids=['1327'],f=>{delete f.timeend;},f=>f.timeend='2026-11-09 17:59:59',f=>f.timestart='2026-11-09 18:00:01',f=>f.timeend='2027-02-30 00:00:00'];
 for(const mutate of mutations){const f=fixture(t);mutate(f.discount.fields);const p=await f.service.prepare(f.body,'alice');assert.equal(p.can_publish,false);assert(p.blockers[0].startsWith('WEEKLY_COMMERCE_DISCOUNT_'));assert.equal(f.installs.length,0);assert.equal(f.calls.filter(r=>r.action==='model_resolve').length,0);}
 const f=fixture(t);f.discount.fields.repeat_qty=5;f.discount.fields.exclude_gids=['456'];const p=await f.service.prepare(f.body,'alice');assert.equal(p.can_publish,true);assert.equal(p.discount_verification.native_id,'6049');assert.deepEqual(f.calls[0],{action:'benefit_detail',kind:'discount',native_id:'6049',site_id:'266'});
});
test('native aid zero permits all platforms while a concrete aid must match only the selected platforms',async t=>{
 const f=fixture(t);f.discount.fields.aid=21587;assert.deepEqual((await f.service.prepare(f.body,'alice')).blockers,['WEEKLY_COMMERCE_DISCOUNT_PLATFORM_SCOPE']);
 f.draft.pages[0].product_keys=['fc-model-266-1327-22-ps'];f.draft.pages[1].product_keys=['22','23','24'].map(id=>'fc-model-266-1327-'+id+'-ps');f.draft.pages[2].product_keys=['22','23','24','25'].map(id=>'fc-model-266-1327-'+id+'-ps');
 assert.equal((await f.service.prepare(f.body,'alice')).can_publish,true);
});
test('private reviewed new-player preview reuses exact fresh proposal without reads or writes',async t=>{
 const f=fixture(t),p=await f.service.prepare(f.body,'alice'),count=f.calls.length;
 const catalog=f.service.previewCatalog(f.body,'alice');assert.equal(catalog.products.length,12);
 assert.equal(catalog.model_contracts['22'].combinations[0].price.source,'admin_current');
 const preview=createSnapshot({schema_version:1,publication_status:'published',release_id:'isolated-new-draft',source_revision:'test',config_hash:'a'.repeat(64),rule_hash:'b'.repeat(64),products:catalog.products,seasonal_model_contracts:catalog.model_contracts,native_checkout:{status:'unconfigured'},pages:[{activity_id:'fc27-season2',page_id:'fc27-weekly',path:'Weekly-Scout.html',title:'New draft',active:true,rule_version:'test',benefit_binding_version:'test',product_keys:catalog.products.map(p=>p.key)}]});
 const box={};vm.runInNewContext(fs.readFileSync(new URL('../../activity-core.js',import.meta.url),'utf8'),box);
 for(const platform of ['ps','xbox','pc']){
  const offer=box.FCActivityCore.nativeModelOffer(f.values[0].model,platform,preview,'fc27-weekly',at);
  assert.equal(offer.price.base_minor,1013);assert.equal(offer.checkout_ready,false);
 }
 assert.equal(f.policy.native_catalog.model_contracts['22'],undefined,'new model is not installed or published');

 assert.equal(f.service.previewCatalog(f.body,'bob'),null);
 assert.equal(f.service.previewCatalog({...f.body,revision:8},'alice'),null);
 assert.equal(f.service.previewCatalog({...f.body,draft:{...f.draft,copy:'unsaved'}},'alice'),null);
 assert.equal(f.calls.length,count);assert.equal(f.installs.length,0);
 f.setClock(at+300001);assert.equal(f.service.previewCatalog(f.body,'alice'),null);
 f.setClock(at);fs.writeFileSync(path.join(f.dir,p.proposal_id+'.json'),'{broken');
 assert.throws(()=>f.service.previewCatalog(f.body,'alice'),SyntaxError);
});

test('preview selects newest valid exact proposal and invalid draft shapes do not hash',async t=>{
 const f=fixture(t),first=await f.service.prepare(f.body,'alice');
 for(const draft of [undefined,null,'invalid',[],42])assert.equal(f.service.previewCatalog({revision:7,draft},'alice'),null);
 f.setClock(at+1000);for(const v of f.values)for(const product of v.observation.products)product.source_unit_price='20.00';
 const latest=await f.service.prepare({...f.body,operation_id:randomUUID()},'alice');
 assert.notEqual(first.preview_catalog.model_contracts['22'].combinations[0].price.base_minor,latest.preview_catalog.model_contracts['22'].combinations[0].price.base_minor);
 assert.deepEqual(f.service.previewCatalog(f.body,'alice'),latest.preview_catalog);
 const file=path.join(f.dir,latest.proposal_id+'.json'),expired=JSON.parse(fs.readFileSync(file));expired.valid_until=new Date(at).toISOString();fs.writeFileSync(file,JSON.stringify(expired));
 assert.deepEqual(f.service.previewCatalog(f.body,'alice'),first.preview_catalog);
});


test('one real fixed bundle creates priced native bindings on all three FC pages without installing',async t=>{
 const f=fixture(t),bundle=facts('60','bundle');f.values.push(bundle);f.draft.fc_models[bundle.model.key]=bundle.model;f.draft.fc_layout.bundles=[bundle.model.key];
 const before=Buffer.from(f.getPolicy()),p=await f.service.prepare(f.body,'alice');assert.equal(p.can_publish,true);assert.equal(p.models_count,5);assert(p.preview_catalog.model_contracts['60']);
 const candidate=JSON.parse(fs.readFileSync(p.candidate_path));for(const page_id of ['fc27-weekly','fc27-trio','fc27-sbc']){const bindings=candidate.native_checkout.bindings.filter(b=>b.page_id===page_id&&bundle.observation.products.some(p=>p.product_ref.goods_id===b.native.id));assert.equal(bindings.length,3);assert(bindings.every(b=>b.code==='FCSCOUT10'));}
 assert.deepEqual(f.getPolicy(),before);assert.equal(f.installs.length,0);
});


test('current legacy four-bundle draft needs one trusted import save before review can project approved public quotes',async t=>{
 const f=fixture(t),legacy=JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url))),selected=[['185752835','44839987'],['185752943','44839989'],['185753051','44839991'],['185753159','44839993']],players=Array.from({length:24},(_,i)=>String(11+i)),cores=Array.from({length:9},(_,i)=>String(101+i)),key=id=>'model-266-1327-'+id;
 Object.assign(f.catalog,legacy);for(const p of Object.values(f.catalog.products))for(const platform of Object.values(p.platforms||{}))delete platform.price;
 const card=value=>({...value.model,version_label:null,image_url:null,image_provenance:null,site_association:'observed',verification_scope:'catalog_identity_only',available:false,authoritative:false,checkout_enabled:false});
 f.values.splice(0,f.values.length,...players.map(id=>facts(id)),...cores.map(id=>facts(id,'sbc')));
 const originalModels=Object.fromEntries(f.values.map(value=>[value.model.key,card(value)])),bundleFacts=selected.map(([legacyKey,mid])=>{
  const value=facts(mid,'bundle');for(const [code,slot] of Object.entries(value.model.platforms)){const goods=String(legacy.products[legacyKey].platforms[code].id);slot.product_ref.goods_id=goods;value.observation.products.find(p=>p.platform_attribute_id===platforms[code]).product_ref.goods_id=goods;}return value;
 });f.values.push(...bundleFacts);
 const pool=players.slice(0,18).map(key),layout={weekly:players.slice(21,24).map(key),trio:players.slice(18,21).map(key),sbc:cores.map(key),bundles:selected.map(([old])=>old),defaultCore:key(cores[0]),routes:Object.fromEntries(cores.map((id,i)=>{const picks=pool.slice(i*2,i*2+2);return [key(id),{picks,alternatives:pool.filter(k=>!picks.includes(k))}];}))};
 const draft={...initialCenterDraft(),fc_models:structuredClone(originalModels),fc_layout:layout};for(const page of draft.pages.filter(p=>p.page_id.startsWith('fc27-')))page.benefit_refs=[{kind:'discount',native_id:'6049'}];assert(draft.pages.every(p=>!Object.hasOwn(p,'product_keys')));assert.equal(Object.keys(draft.fc_models).length,33);
 // Existing production shape: legacy cards, with native Trio bindings already installed.
 const installed=weeklyNativeCandidates({source:{observed_at:new Date(at).toISOString(),models:bundleFacts.map(v=>v.model),provider_observations:bundleFacts.map(v=>v.observation)},pricePolicy:f.policy.admin_reference_prices,now:at}).native_catalog_candidate;
 f.policy.native_catalog.products.push(...installed.products);Object.assign(f.policy.native_catalog.model_contracts,installed.model_contracts);for(const c of Object.values(f.policy.native_catalog.model_contracts))for(const row of c.combinations)delete row.price;
 for(const product of installed.products)f.policy.native_checkout.bindings.push({activity_id:'fc27-season2',page_id:'fc27-trio',product_key:product.key,quantity:{value:'1',unit:'item'},attributes:[],off_percent:10,code:'FCSCOUT10',native:{category:'new_items',id:product.product_ref.goods_id,group:'1',num:'1',attr:'',aid:product.platform.attribute_id}});
 const originalTrio=structuredClone(f.policy.native_checkout.bindings.filter(b=>b.page_id==='fc27-trio'));
 const stateDir=path.join(f.dir,'backend'),publicDir=path.join(f.dir,'public'),centerDir=path.join(f.dir,'center');for(const dir of [stateDir,centerDir,publicDir])fs.mkdirSync(dir,{mode:0o700});const policyFile=path.join(stateDir,'policy.json'),writePolicy=policy=>{const raw=JSON.stringify(policy);f.setPolicy(raw);fs.writeFileSync(policyFile,raw,{mode:0o600});};writePolicy(f.policy);fs.writeFileSync(path.join(centerDir,'state.json'),JSON.stringify({revision:27,draft,published:null}));
 const center=makeCenterStore({dir:centerDir,publicDir,sourceRevision:'legacy-shape-fixture',validateFcLayout:(layout,models)=>validateLayout(layout,effectiveFcCatalog(f.catalog,models)),seedProvider:(layout,models)=>mergeNativeCatalog(centerSeed(previewCatalog(effectiveFcCatalog(f.catalog,models),layout),{products:[]}),readNativeLaunchPolicy(stateDir,{now:at}).catalog),nativeCheckoutProvider:()=>readNativeLaunchPolicy(stateDir,{now:at}).checkout});
 const seedFor=(current,proposal)=>{const seed=mergeNativeCatalog(centerSeed(previewCatalog(effectiveFcCatalog(f.catalog,current.draft.fc_models),current.draft.fc_layout),{products:[]}),proposal.preview_catalog);Object.assign(seed.seasonal_model_contracts,structuredClone(proposal.preview_catalog.model_contracts));return seed;};
 const beforePolicy=Buffer.from(f.getPolicy()),old=await f.service.prepare({operation_id:randomUUID(),revision:27,draft},'alice');assert.equal(old.can_publish,true);assert.equal(old.models_count,37);
 const legacyPreview=center.preview({revision:27,draft},[],[],{seed:seedFor(center.read(),old)});for(const [,mid] of selected)for(const page of legacyPreview.pages.filter(p=>p.page_id.startsWith('fc27-')))assert(!page.product_keys.some(k=>old.preview_catalog.products.some(p=>p.product_ref.model_id===mid&&p.key===k)),'prepare alone cannot turn the legacy card into a native alias');
 assert.deepEqual(f.getPolicy(),beforePolicy);assert.equal(f.installs.length,0);
 // One trusted server save appends four resolved models; the request cannot contain details.
 const next=structuredClone(draft);next.fc_layout.bundles=selected.map(([,mid])=>key(mid));const operation_id=randomUUID(),imports=selected.map(([,model_id])=>({page_id:'fc27-trio',kind:'bundle',model_id})),details=bundleFacts.map(card),body={operation_id,revision:27,draft:next,model_imports:imports};
 const bridge=path.join(f.dir,'trusted-model-read.py'),bridgeLog=path.join(f.dir,'model-reads.jsonl');fs.writeFileSync(bridge,'import json,sys\nr=json.load(sys.stdin)\nmodels=json.loads('+JSON.stringify(JSON.stringify(details))+')\nif r.get("action")!="model_resolve": print(json.dumps({"status":"error","error":"FIXTURE_READ_ONLY"}));sys.exit(0)\nwith open('+JSON.stringify(bridgeLog.replaceAll('\\','/'))+',"a") as log: log.write(json.dumps(r)+"\\n")\nm=next(m for m in models if m["model_id"]==r["model_id"] and m["kind"]==r["kind"])\nprint(json.dumps({"status":"ok","data":{"model":m,"resolution_complete":True}}))\n');
 const envKeys=['CAMPAIGN_DATA','CAMPAIGN_PUBLIC_RELEASE_DIR','CAMPAIGN_ORIGIN','CAMPAIGN_PYTHON','CAMPAIGN_BACKEND_BRIDGE'],previous=Object.fromEntries(envKeys.map(k=>[k,process.env[k]])),originalFetch=globalThis.fetch;let management,saved;
 Object.assign(process.env,{CAMPAIGN_DATA:f.dir,CAMPAIGN_PUBLIC_RELEASE_DIR:publicDir,CAMPAIGN_ORIGIN:'http://127.0.0.1',CAMPAIGN_PYTHON:process.platform==='win32'?'python':'python3',CAMPAIGN_BACKEND_BRIDGE:bridge});globalThis.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':'alice','x-auth-role':'admin'}}):originalFetch(url,options);
 try{
  ({server:management}=await import('../production-server.mjs'));await new Promise(resolve=>management.listen(0,'127.0.0.1',resolve));const endpoint='http://127.0.0.1:'+management.address().port+'/dashboard/analytics/campaigns/analytics/api/center',current=await(await originalFetch(endpoint)).json();assert.equal(current.revision,27);
  const response=await originalFetch(endpoint,{method:'POST',headers:{Origin:'http://127.0.0.1','Content-Type':'application/json','X-CSRF-Token':current.csrf},body:JSON.stringify(body)});assert.equal(response.status,200);saved=center.read();assert.deepEqual(JSON.parse(fs.readFileSync(path.join(centerDir,'operations',operation_id+'.json'))).result.draft,saved.draft);
  const calls=fs.readFileSync(bridgeLog,'utf8').trim().split('\n').map(JSON.parse);assert.deepEqual(calls.map(r=>[r.action,r.kind,r.model_id]),selected.map(([,mid])=>['model_resolve','bundle',mid]));assert.equal(Object.hasOwn(body,'details'),false);
  const replay=await originalFetch(endpoint,{method:'POST',headers:{Origin:'http://127.0.0.1','Content-Type':'application/json','X-CSRF-Token':current.csrf},body:JSON.stringify(body)});assert.equal(replay.status,200);assert.equal(fs.readFileSync(bridgeLog,'utf8').trim().split('\n').length,4,'original-ID readback does not reread models or save again');
 }finally{if(management)await new Promise(resolve=>management.close(resolve));globalThis.fetch=originalFetch;for(const k of envKeys){if(previous[k]===undefined)delete process.env[k];else process.env[k]=previous[k];}}

 assert.equal(saved.revision,28);assert.equal(Object.keys(saved.draft.fc_models).length,37);for(const [id,model] of Object.entries(originalModels))assert.deepEqual(saved.draft.fc_models[id],model);for(const field of ['weekly','trio','sbc','routes'])assert.deepEqual(saved.draft.fc_layout[field],layout[field]);assert(saved.draft.pages.every(p=>!Object.hasOwn(p,'product_keys')));assert.equal(saved.published,null);
 for(const [,mid] of selected)for(const [code,slot] of Object.entries(saved.draft.fc_models[key(mid)].platforms))assert.equal(slot.product_ref.goods_id,bundleFacts.find(v=>v.model.model_id===mid).model.platforms[code].product_ref.goods_id);
 // Align other selected native bindings with the installed policy, leaving exactly the 24 bundle gaps.
 const expectedSelected=await f.service.prepare({operation_id:randomUUID(),revision:28,draft:saved.draft},'alice');assert.equal(expectedSelected.can_publish,true);const allCandidate=JSON.parse(fs.readFileSync(expectedSelected.candidate_path)),mids=new Set(selected.map(([,mid])=>mid)),bundleGoods=new Set(bundleFacts.flatMap(v=>v.observation.products.map(p=>p.product_ref.goods_id)));
 const baseline=JSON.parse(f.getPolicy());baseline.native_checkout.bindings=allCandidate.native_checkout.bindings.filter(b=>!bundleGoods.has(b.native.id)||b.page_id==='fc27-trio');baseline.native_catalog=allCandidate.native_catalog;baseline.admin_reference_prices=allCandidate.admin_reference_prices;writePolicy(baseline);const alignedBefore=Buffer.from(f.getPolicy());
 const proposal=await f.service.prepare({operation_id:randomUUID(),revision:28,draft:saved.draft},'alice');assert.equal(proposal.can_publish,true);assert.equal(proposal.models_count,37);assert.equal(proposal.diff.added.bindings,24);const candidate=JSON.parse(fs.readFileSync(proposal.candidate_path)),bundleKeys=new Set(proposal.preview_catalog.products.filter(p=>mids.has(p.product_ref.model_id)).map(p=>p.key)),bindings=candidate.native_checkout.bindings.filter(b=>bundleKeys.has(b.product_key)&&b.page_id.startsWith('fc27-'));assert.equal(bindings.length,36);assert.equal(bindings.filter(b=>b.page_id!=='fc27-trio').length,24);assert.deepEqual(candidate.native_checkout.bindings.filter(b=>bundleKeys.has(b.product_key)&&b.page_id==='fc27-trio'),originalTrio);
 const preview=center.preview({revision:28,draft:saved.draft},[],[],{seed:seedFor(saved,proposal)}),privateCatalog=projectFcCatalog(f.catalog,preview);for(const page of preview.pages.filter(p=>p.page_id.startsWith('fc27-')))for(const [,mid] of selected)for(const platform of ['ps','xbox','pc']){const offer=core.nativeModelOffer(privateCatalog.products[key(mid)],platform,preview,page.page_id,at);assert(offer?.price.base_minor>0);assert.equal(offer.checkout_ready,false,'private preview never grants checkout');}assert.deepEqual(f.getPolicy(),alignedBefore);
 // Isolated explicit-confirmation simulation. Prices come only from observation fixtures.
 const approved=structuredClone(proposal.preview_catalog);
 const offset=Date.now()-at;
 approved.valid_until=new Date(Date.parse(approved.valid_until)+offset).toISOString();
 for(const c of Object.values(approved.model_contracts))for(const row of c.combinations)row.price.expires_at=new Date(Date.parse(row.price.expires_at)+offset).toISOString();
 writePolicy(candidate);center.publish({operation_id:randomUUID(),revision:28},'alice',[],[],{approvedPrices:approved});
 const releaseFile=path.join(publicDir,'current.json'),snapshot=JSON.parse(fs.readFileSync(releaseFile));assert.equal(snapshot.native_checkout.bindings.filter(b=>bundleKeys.has(b.product_key)&&b.page_id.startsWith('fc27-')).length,36);
 assert(!Object.values(snapshot.seasonal_model_contracts).some(c=>c.combinations.some(row=>row.price)),'immutable release does not carry prices');
 let publicNow=Date.now();
 const publicServer=createPublicServer({assetRoot:path.resolve(path.dirname(releaseFile)),staticManifest:{},snapshotProvider:()=>JSON.parse(fs.readFileSync(releaseFile)),publishedDir:publicDir,releaseFile,dir:path.join(f.dir,'public-test'),origin:'http://127.0.0.1',now:()=>publicNow});
 await new Promise(resolve=>publicServer.listen(0,'127.0.0.1',resolve));
 try{
  const config=()=>fetch('http://127.0.0.1:'+publicServer.address().port+'/events/api/campaign/config').then(r=>r.json());
  const initial=await config(),product=approved.products.find(p=>bundleKeys.has(p.key)),model=product.product_ref.model_id;
  const quote=(response)=>response.seasonal_model_contracts[model].combinations.find(row=>row.product_key===product.key).price;
  assert(quote(initial)?.base_minor>0,'first public response uses the reviewed quote before the live cache is built');
  assert.equal(quote(initial).expires_at,approved.model_contracts[model].combinations.find(row=>row.product_key===product.key).price.expires_at);
  const seed=JSON.parse(fs.readFileSync(path.join(publicDir,snapshot.release_id+'-initial-prices.json')));
  assert.equal(seed.products.length,111);
  assert(!seed.products.some(p=>p.product_ref.model_id==='99'));
  const liveFile=path.join(publicDir,'admin-reference-prices.json');
  const replaceLive=value=>fs.writeFileSync(liveFile,JSON.stringify(value));
  replaceLive({...seed,status:'refreshing'});
  assert.equal(quote(await config()).base_minor,quote(initial).base_minor);
  replaceLive({...seed,status:'unavailable'});
  assert.equal(quote(await config()),undefined,'a verified source denial removes the launch fallback');
  const live=structuredClone(seed);const liveQuote=quote({seasonal_model_contracts:live.model_contracts});liveQuote.base_minor++;
  replaceLive(live);
  assert.equal(quote(await config()).base_minor,liveQuote.base_minor);
  publicNow=Date.parse(liveQuote.expires_at);
  assert.equal(quote(await config()),undefined);
 }finally{await new Promise(resolve=>publicServer.close(resolve));}
 fs.unlinkSync(path.join(publicDir,'admin-reference-prices.json'));
 // Model 99 is the fixture's original installed policy, retained through the Seasonal seed.
 // It is not one of the current 33+4 FC cards and is never a generic missing-model fallback.
 const selectedObservations=new Map(f.values.map(v=>[v.model.model_id,v.observation])),retained99=facts('99').observation;
 assert.equal(selectedObservations.size,37);assert(candidate.admin_reference_prices.entries.some(p=>p.model_ref.model_id==='99'));
 const fcKeys=new Set(snapshot.pages.filter(p=>p.page_id.startsWith('fc27-')).flatMap(p=>p.product_keys));assert(!snapshot.products.some(p=>p.product_ref.model_id==='99'&&fcKeys.has(p.key)));
 const seasonalKeys=new Set(snapshot.pages.find(p=>p.page_id==='seasonal-vault').product_keys);assert(snapshot.products.some(p=>p.product_ref.model_id==='99'&&seasonalKeys.has(p.key)));
 const prices=makeAdminPriceProvider({publicDir,readPolicy:()=>candidate.admin_reference_prices,now:()=>at,call:async request=>{
  assert.equal(request.action,'model_provider_batch');return {readings:Object.fromEntries(request.items.map(item=>{
   assert(item.model_id==='99'||selectedObservations.has(item.model_id),'unexpected model requested by price producer: '+item.model_id);
   const observation=item.model_id==='99'?retained99:selectedObservations.get(item.model_id);assert.equal(observation.model.model_id,item.model_id);assert.equal(observation.model.category_id,item.category_id);
   return [item.key,{status:'ok',data:observation}];
  }))};
 }});await prices.refresh();const cache=JSON.parse(fs.readFileSync(path.join(publicDir,'admin-reference-prices.json'))),publicSnapshot=applyPublicPriceCache(snapshot,cache,{now:at}),publicCatalog=projectFcCatalog(f.catalog,publicSnapshot);
 assert.equal(cache.status,'ready');
 for(const page of publicSnapshot.pages.filter(p=>p.page_id.startsWith('fc27-')))for(const [,mid] of selected)for(const platform of ['ps','xbox','pc']){const quote=core.nativeModelOffer(publicCatalog.products[key(mid)],platform,publicSnapshot,page.page_id,at);assert.equal(quote.price.source,'admin_current');assert.equal(quote.price.currency,'USD');assert.equal(quote.price.base_minor,1013);assert.equal(quote.checkout_ready,true);assert.equal(quote.bindings.length,1);}
 assert.equal(f.installs.length,0,'no real installer, model or business service is invoked');
});
