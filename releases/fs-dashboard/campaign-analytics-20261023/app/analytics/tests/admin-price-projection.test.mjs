import {test} from 'node:test';import assert from 'node:assert/strict';
import {projectAdminPrices} from '../../runtime/admin-price-projection.mjs';
import selection from '../../seasonal/model-selection.js';
import {centerSeed} from '../center-seed.mjs';
import {makeCenterStore} from '../center-store.mjs';
import {emptyHalloween} from '../../runtime/halloween-contract.mjs';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
const now=Date.parse('2026-10-26T12:00:00Z');
function fixture(){const model_ref={site_id:'266',game_id:'1327',model_id:'123'},raw_state={status:1,auto_off:0};return {
 policy:{model_ref,baseline_region:'us',regional_adjustment:'none_verified',currency:'USD',minor_unit_scale:2,source_field:'more.price',price_semantics:'current_tier_total',evidence_ref:'synthetic-only',max_age_ms:60000,quantity_value:'1000',quantity_unit:'K',ordered_goods_ids:['12','11'],ordering_evidence:'synthetic-explicit-order'},
 observation:{source:'admin_readonly',observed_at:new Date(now).toISOString(),coverage:{complete:true},model:{model_id:'123',game_id:'1327',raw_state},products:['11','12'].map((goods_id,i)=>({product_ref:{...model_ref,goods_id},raw_state,platform_attribute_id:String(i+1),region_id:'9',specification:{saleprop:{present:false}},tiers:[{quantity:'1000',unit:'K',source_price:i?'20.00':'10.00',source_discount:'100'}]}))}};}
test('trusted source -> public options -> default and selected indicative discounts',()=>{
 const f=fixture(),p=projectAdminPrices(f.observation,f.policy,{now});assert.equal(p.status,'reference_price_ready_not_checkout');const c=p.model_contracts['123'];
 assert.equal(selection.defaultPrice(c,10,{now:()=>now}).base_minor,2000);
 const s=selection.create(c,{now:()=>now});s.select('platform','1');s.select('region','9');s.setQuantity('1000');
 const price=selection.selectedPrice(c,s,8,{now:()=>now});assert.equal(price.base_minor,1000);assert.equal(price.indicative_discounted_minor,920);assert.equal(price.authoritative,false);assert.equal(s.line().quantity.group,undefined);
 s.select('platform','2');assert.equal(s.ready(),false);assert.equal(s.quote(),null);
 assert(!JSON.stringify(p).includes('raw_state'));assert(!JSON.stringify(p).includes('source_discount'));
});
test('missing currency/semantics and stale or incomplete source cannot produce public prices',()=>{
 for(const mutate of [f=>delete f.policy.currency,f=>delete f.policy.evidence_ref,f=>f.policy.price_semantics='guess',f=>f.observation.coverage.complete=false,f=>f.observation.observed_at='2020-01-01T00:00:00Z']){const f=fixture();mutate(f);assert.equal(projectAdminPrices(f.observation,f.policy,{now}).status,'blocked');}
});
test('UK or unproved regional promotions cannot be a standard reference anchor',()=>{
 for(const mutate of [f=>f.policy.baseline_region='uk',f=>f.policy.currency='GBP',f=>delete f.policy.regional_adjustment]){const f=fixture();mutate(f);assert.equal(projectAdminPrices(f.observation,f.policy,{now}).reason,'US_USD_BASELINE_REQUIRED');}
});
test('unavailable first row, unproved specs, wrong scope and excess precision fail closed',()=>{
 for(const mutate of [f=>f.observation.products[0].raw_state={status:0,auto_off:0},f=>f.observation.products[0].specification.saleprop={present:true,observed:[{id:1}]},f=>f.observation.products[0].product_ref.site_id='999',f=>f.observation.products[0].tiers[0].source_price='10.001']){const f=fixture();mutate(f);assert.equal(projectAdminPrices(f.observation,f.policy,{now}).status,'blocked');}
});
test('unknown default ordering blocks only default reference; exact selection remains valid',()=>{
 const f=fixture();delete f.policy.ordered_goods_ids;const c=projectAdminPrices(f.observation,f.policy,{now}).model_contracts['123'];assert.throws(()=>selection.defaultPrice(c,10,{now:()=>now}),/DEFAULT_ORDER/);
});
test('present but unprojectable or scalar specifications cannot become empty options',()=>{
 for(const observed of [null,false,0,'',undefined]){const f=fixture();f.observation.products[0].specification.saleprop={present:true,observed};assert.equal(projectAdminPrices(f.observation,f.policy,{now}).reason,'SPECIFICATION_MAPPING_REQUIRED');}
});
test('server seed uses safe projection and keeps unverified source out of published options',()=>{
 const f=fixture(),fc={products:{},weekly:{ids:[]},trio:{ids:[]},bundles:{ids:[]},sbc:{ids:[],routes:{}}};
 const seed=centerSeed(fc,{products:[]},{adminObservations:[f],now});assert.equal(seed.seedProducts.length,2);assert(seed.seasonal_model_contracts['123']);
 delete f.policy.currency;const blocked=centerSeed(fc,{products:[]},{adminObservations:[f],now});assert.equal(blocked.seedProducts.length,0);assert.equal(blocked.seasonal_model_contracts,undefined);assert.equal(blocked.admin_projection_status[0].status,'blocked');
});
test('import first then trusted provider publishes once without rewriting raw draft',()=>{
 for(const configured of [false,true]){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'provider55-import-'));
 try{
  let seed={seedProducts:[],pageProductKeys:{'seasonal-vault':[]}};
  const store=makeCenterStore({dir:path.join(dir,'private'),publicDir:path.join(dir,'public'),sourceRevision:'synthetic',seedProvider:()=>seed});
  const f=fixture(),ref={site_id:'266',game_id:'1327',model_id:'123',goods_id:'11'},draft=store.read().draft;
  if(configured){draft.halloween=emptyHalloween();draft.halloween.games[0].fixed_model='123';draft.halloween.games[0].fixed_off_percent=8;}
  store.importProduct({revision:0,operation_id:randomUUID(),draft,page_id:'seasonal-vault',product_ref:ref},'synthetic',{product_ref:ref,title:'Original operator title',platform_attribute_id:'1',minimum_quantity:1,unit:'K',authoritative:false,checkout_enabled:false});
  const original=structuredClone(store.read().draft),p=projectAdminPrices(f.observation,f.policy,{now});
  seed={seedProducts:p.products,pageProductKeys:{'seasonal-vault':[]},seasonal_model_contracts:p.model_contracts};
  store.publish({revision:1,operation_id:randomUUID()},'synthetic');
  const published=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json'),'utf8'));
  assert.equal(published.seasonal_model_contracts['123'].combinations.length,configured?2:1);assert.equal(published.seasonal_model_contracts['123'].ordering_verified,configured);
  assert.equal(published.products.filter(x=>x.product_ref.goods_id==='11').length,1);assert.equal(published.products.find(x=>x.product_ref.goods_id==='11').title,'Original operator title');assert.deepEqual(store.read().draft,original);assert.equal(original.imported_products[0].quantity,null);
  seed.seedProducts[0].product_ref={...ref,goods_id:'999'};assert.throws(()=>store.publish({revision:2,operation_id:randomUUID()},'synthetic'),/PROVIDER_IMPORT_IDENTITY_CONFLICT/);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
 }
});

test('observed one-item display totals avoid guessing high-precision native rounding and keep SKU fields guarded',()=>{
 const f=fixture();Object.assign(f.policy,{source_field:'full_price_format',price_semantics:'current_item_display_total',descriptive_baseprop:true,quantity_value:'1',quantity_unit:'item'});
 for(const row of f.observation.products){row.quantity={unit:null};row.source_display_price='5.43';row.source_unit_price='5.42938000';row.specification.baseprop={present:true,observed:[{name:'Version'}]};}
 let out=projectAdminPrices(f.observation,f.policy,{now});assert.equal(out.status,'reference_price_ready_not_checkout');assert.equal(out.model_contracts['123'].combinations[0].price.base_minor,543);
 f.observation.products[0].source_display_price='1.005';assert.equal(projectAdminPrices(f.observation,f.policy,{now}).reason,'PRICE_PRECISION_UNVERIFIED');
 f.observation.products[0].source_display_price='5.43';f.observation.products[0].specification.saleprop={present:true,observed:[{id:'purchase-option'}]};assert.equal(projectAdminPrices(f.observation,f.policy,{now}).reason,'SPECIFICATION_MAPPING_REQUIRED');
 f.policy.quantity_value='2';assert.equal(projectAdminPrices(f.observation,f.policy,{now}).status,'blocked');
});

test('explicit observed native one-item formatter handles missing formatted field without inventing it',()=>{
 const f=fixture();Object.assign(f.policy,{source_field:'unit_price',price_semantics:'native_item_display_total',rounding_contract:'native-js-number-format-tofixed-2',descriptive_baseprop:true,quantity_value:'1',quantity_unit:'item'});
 for(const row of f.observation.products){row.quantity={unit:'',group:'1'};row.source_display_price=null;row.specification.baseprop={present:true,observed:[{name:'Version'}]};}
 for(const [raw,cents] of [['5.61132',561],['1.15104',115],['34.9',3490],['105',10500],['2.675',267]]){
  f.observation.products[0].source_unit_price=raw;f.observation.products[1].source_unit_price='999';
  const out=projectAdminPrices(f.observation,f.policy,{now});assert.equal(out.status,'reference_price_ready_not_checkout');assert.deepEqual(new Set(out.model_contracts['123'].combinations.map(x=>x.price.base_minor)),new Set([cents,99900]));assert.equal(f.observation.products[0].source_display_price,null);
 }
 for(const mutate of [x=>delete x.policy.rounding_contract,x=>x.policy.rounding_contract='guess',x=>x.policy.quantity_value='2',x=>x.policy.minor_unit_scale=3,x=>x.observation.products[0].source_unit_price='1e2',x=>x.observation.products[0].source_unit_price=' 1',x=>x.observation.products[0].quantity.group='2',x=>x.observation.products[0].specification.saleprop={present:true,observed:[{id:'sku'}]}]){const x=structuredClone(f);mutate(x);assert.equal(projectAdminPrices(x.observation,x.policy,{now}).status,'blocked');}
});

test('explicit D4 native product discount precedes the event discount without changing other item policies',()=>{
 const f=fixture();f.policy.model_ref.game_id='456';f.observation.model.game_id='456';
 Object.assign(f.policy,{source_field:'unit_price',price_semantics:'native_discounted_item_display_total',rounding_contract:'native-js-number-format-tofixed-2',quantity_value:'1',quantity_unit:'item'});
 for(const row of f.observation.products){row.product_ref.game_id='456';row.quantity={unit:'item',group:'1'};row.source_unit_price='7.49';row.source_discount='90.00';}
 let out=projectAdminPrices(f.observation,f.policy,{now});assert.equal(out.status,'reference_price_ready_not_checkout');
 const contract=out.model_contracts['123'];assert.equal(selection.defaultPrice(contract,10,{now:()=>now}).base_minor,674);assert.equal(selection.defaultPrice(contract,10,{now:()=>now}).indicative_discounted_minor,607);
 f.observation.products[0].source_discount='100';out=projectAdminPrices(f.observation,f.policy,{now});assert.deepEqual(new Set(out.model_contracts['123'].combinations.map(x=>x.price.base_minor)),new Set([674,749]));
 const legacy=structuredClone(f);legacy.policy.price_semantics='native_item_display_total';assert(projectAdminPrices(legacy.observation,legacy.policy,{now}).model_contracts['123'].combinations.every(x=>x.price.base_minor===749));
 for(const value of [undefined,null,'0','-1','101','NaN','90x']){const bad=structuredClone(f);bad.observation.products[0].source_discount=value;assert.equal(projectAdminPrices(bad.observation,bad.policy,{now}).reason,'NATIVE_PRODUCT_DISCOUNT_UNVERIFIED');}
 const other=structuredClone(f);other.policy.model_ref.game_id='1327';assert.equal(projectAdminPrices(other.observation,other.policy,{now}).reason,'PRICE_CURRENCY_SEMANTICS_UNVERIFIED');
});
