import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {prepareWeeklyRequest,recommendWeekly} from '../weekly-hermes.mjs';
import {initialCenterDraft} from '../center-store.mjs';
import {centerSeed,effectivePageBindings} from '../center-seed.mjs';
import {initialLayout,previewCatalog} from '../store.mjs';

const now=Date.parse('2026-11-09T10:00:00Z');
function fixture(){
 const product=(key,goods)=>({key,title:key,product_ref:{site_id:'266',game_id:'1327',goods_id:goods},platform:{code:'ps',attribute_id:'21587'},available:false,secret:'never forward',price:'never forward'});
 return {enabled:true,source_revision:'fixture-source-r7',now,
  draft:{pages:[{page_id:'fc27-weekly'},{page_id:'fc27-trio'},{page_id:'fc27-sbc',product_roles:{'fc-core-ps':'core'}}]},
  catalog_products:[product('fc-core-ps','1'),product('fc-player-ps','2')],
  page_bindings:{'fc27-weekly':{product_keys:['fc-player-ps']},'fc27-trio':{product_keys:['fc-player-ps']},'fc27-sbc':{product_keys:['fc-core-ps','fc-player-ps']}},
  sbc_update:{id:'sbc-20261109',observed_at:'2026-11-09T09:00:00Z',expires_at:'2026-11-16T09:00:00Z',context:'Fixture SBC update',sources:[{url:'https://www.ea.com/games/ea-sports-fc/news/fixture',title:'Fixture source',observed_at:'2026-11-09T09:00:00Z'}]}};
}
const reply=(request,rows=[{page_id:'fc27-sbc',product_key:'fc-player-ps',core_product_key:'fc-core-ps',reason:'Fixture association',evidence_indices:[0]}])=>({model:request.model,source_revision:request.input.source_revision,sbc_update_id:request.input.sbc_update.id,recommendations:rows});

test('disabled and disconnected states never call a provider or pretend to run',async()=>{
 let calls=0;const provider=async request=>{calls++;return reply(request);};
 assert.equal((await recommendWeekly({...fixture(),enabled:false,provider})).status,'disabled');
 assert.equal((await recommendWeekly(fixture())).status,'unavailable');
 assert.equal(calls,0);
});

test('request projects only real FC catalog identity and binds event/content revision for deduplication',()=>{
 const input=fixture(),before=structuredClone(input),request=prepareWeeklyRequest(input);
 assert.equal(request.model,'gpt-6.1-sol');assert.equal(request.reasoning_effort,'high');
 assert.doesNotMatch(JSON.stringify(request),/never forward|secret|"price"/);
 assert.equal(request.dedupe_key,prepareWeeklyRequest(input).dedupe_key);
 input.sbc_update.id='sbc-next';assert.notEqual(request.dedupe_key,prepareWeeklyRequest(input).dedupe_key);
 input.sbc_update=before.sbc_update;input.source_revision='changed';assert.notEqual(request.dedupe_key,prepareWeeklyRequest(input).dedupe_key);
 assert.deepEqual(before,fixture());
});

test('recommendations remain candidates with host-derived unknowns and never mutate the draft',async()=>{
 const input=fixture(),before=structuredClone(input);
 const result=await recommendWeekly({...input,provider:async request=>reply(request)});
 assert.equal(result.status,'completed');assert.equal(result.publication,false);assert.equal(result.verification_scope,'recommendation_only');
 assert.equal(result.candidates[0].core_product_key,'fc-core-ps');
 assert(result.candidates[0].pending_verification.includes('sellability_unverified'));
 assert(result.candidates[0].pending_verification.includes('product_freshness_unknown'));
 assert.deepEqual(input,before);
});

test('foreign keys, wrong model, wrong revision and forged verification fields fail without exposing provider errors',async()=>{
 for(const mutate of [r=>r.recommendations[0].product_key='invented',r=>r.model='other-model',r=>r.source_revision='old',r=>r.sbc_update_id='old',r=>r.recommendations[0].verified=true,r=>r.recommendations[0].core_product_key='fc-player-ps',r=>r.recommendations[0].evidence_indices=[99]]){
  const result=await recommendWeekly({...fixture(),provider:async request=>{const result=reply(request);mutate(result);return result;}});
  assert.equal(result.status,'failed');assert.deepEqual(result.candidates,[]);
 }
 const failed=await recommendWeekly({...fixture(),provider:async()=>{throw new Error('private provider credentials');}});
 assert.equal(failed.status,'failed');assert.doesNotMatch(JSON.stringify(failed),/private provider credentials/);
});

test('expired or missing source evidence is visibly pending rather than a verified match',async()=>{
 const input=fixture();input.sbc_update.expires_at='2026-11-09T09:01:00Z';input.sbc_update.sources=[];
 const result=await recommendWeekly({...input,provider:async request=>reply(request,[{page_id:'fc27-weekly',product_key:'fc-player-ps',reason:'Fixture',evidence_indices:[]}])});
 assert.equal(result.status,'completed');assert(result.candidates[0].pending_verification.includes('update_expired'));
 assert(result.candidates[0].pending_verification.includes('source_evidence_missing'));
});

test('invalid input is rejected before provider dispatch and unknown platform identity is pending',async()=>{
 let called=false;const input=fixture();input.catalog_products.push({...input.catalog_products[0]});
 assert.equal((await recommendWeekly({...input,provider:async()=>{called=true;}})).error,'INVALID_WEEKLY_HERMES_INPUT');assert.equal(called,false);
 const unknown=fixture();unknown.catalog_products[1].platform={code:'unknown'};delete unknown.catalog_products[1].product_ref.goods_id;
 const result=await recommendWeekly({...unknown,provider:async request=>reply(request)});
 assert(result.candidates[0].pending_verification.includes('platform_unverified'));assert(result.candidates[0].pending_verification.includes('identity_unverified'));
});

test('logical core bindings are reused and empty catalogs do not consume a model call',async()=>{
 const input=fixture();delete input.draft.pages[2].product_roles;input.draft.fc_layout={sbc:['core']};
 assert.deepEqual(prepareWeeklyRequest(input).input.pages.find(page=>page.page_id==='fc27-sbc').core_product_keys,['fc-core-ps']);
 input.catalog_products=[];Object.values(input.page_bindings).forEach(binding=>binding.product_keys=[]);
 let calls=0;const result=await recommendWeekly({...input,provider:async()=>{calls++;}});
 assert.equal(result.status,'unavailable');assert.equal(result.error,'WEEKLY_HERMES_CATALOG_EMPTY');assert.equal(calls,0);
 const request=prepareWeeklyRequest(input);assert.equal(request.response_schema.properties.recommendations.maxItems,0);
});

test('actual center seed and inherited page bindings support all three pages without elevating sale state',async()=>{
 const catalog=JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url),'utf8'));
 const seed=centerSeed(previewCatalog(catalog,initialLayout(catalog)),{products:[]}),draft=initialCenterDraft();
 draft.fc_layout=seed.fc_layout;
 const input={...fixture(),source_revision:String(7),draft,catalog_products:seed.seedProducts,
  page_bindings:Object.fromEntries(draft.pages.filter(page=>page.page_id.startsWith('fc27-')).map(page=>[page.page_id,effectivePageBindings(draft,seed,page.page_id)]))};
 const request=prepareWeeklyRequest(input);assert.equal(request.input.pages.length,3);
 const coreKey=request.input.pages.find(page=>page.page_id==='fc27-sbc').core_product_keys[0];assert(coreKey);
 const core=request.input.catalog.find(product=>product.key===coreKey),player=request.input.catalog.find(product=>product.key!==coreKey&&product.platform.code===core.platform.code);
 const result=await recommendWeekly({...input,provider:async request=>reply(request,[{page_id:'fc27-sbc',core_product_key:coreKey,product_key:player.key,reason:'Fixture real catalog contract',evidence_indices:[0]}])});
 assert.equal(result.status,'completed');assert(result.candidates[0].pending_verification.includes('sellability_unverified'));
 assert.equal(result.source_revision,'7');assert.equal(result.candidates[0].verification_scope,'recommendation_only');
});

test('a stalled provider aborts locally with an unknown outcome and no retry',async()=>{
 let calls=0,signal;
 const result=await recommendWeekly({...fixture(),timeout_ms:5,provider:async(request,options)=>{calls++;signal=options.signal;return new Promise(()=>{});}});
 assert.equal(calls,1);assert.equal(signal.aborted,true);assert.equal(result.status,'failed');assert.equal(result.error,'WEEKLY_HERMES_PROVIDER_TIMEOUT');assert.equal(result.provider_outcome,'unknown');
});
