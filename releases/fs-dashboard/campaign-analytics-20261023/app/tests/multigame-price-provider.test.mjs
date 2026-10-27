import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {halloweenFixture} from '../runtime/tests/halloween-fixture.mjs';
import {makeAdminPriceProvider} from '../analytics/admin-price-provider.mjs';
import {readPublicPriceCache,applyPublicPriceCache} from '../runtime/admin-price-cache.mjs';
test('v2 private producer refreshes four scoped models through actual projection and public cache',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'multi-price-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const now=Date.parse('2026-10-27T00:00:00Z'),snapshot=halloweenFixture();let calls=0;
 const chosen=snapshot.halloween.games.map(g=>snapshot.products.find(p=>p.product_ref.model_id===g.fixed_model));
 const config={schema_version:2,refresh_interval_ms:60000,entries:chosen.map(p=>({category_id:'900',model_ref:{site_id:p.product_ref.site_id,game_id:p.product_ref.game_id,model_id:p.product_ref.model_id},baseline_region:'us',regional_adjustment:'none_verified',currency:'USD',minor_unit_scale:2,source_field:'more.price',price_semantics:'current_tier_total',evidence_ref:'synthetic-multi',max_age_ms:120000,quantity_value:p.quantity.min,quantity_unit:p.quantity.unit,verified_goods_ids:[p.product_ref.goods_id],ordered_goods_ids:[p.product_ref.goods_id],ordering_evidence:'synthetic-source-order'}))};
 const provider=makeAdminPriceProvider({publicDir:dir,now:()=>now,readPolicy:()=>config,readSnapshot:()=>snapshot,call:async req=>{
  calls++;assert.equal(req.action,'model_provider_read');const p=chosen.find(p=>p.product_ref.model_id===req.model_id);assert(p);
  return {source:'admin_readonly',observed_at:new Date(now).toISOString(),coverage:{complete:true},model:{model_id:req.model_id,game_id:req.game_id,raw_state:{status:1,auto_off:0}},products:[{product_ref:p.product_ref,platform_attribute_id:p.platform.attribute_id,region_id:'999',raw_state:{status:1,auto_off:0},specification:{saleprop:{present:false}},tiers:[{quantity:p.quantity.min,unit:p.quantity.unit,source_price:'12.34',source_discount:'100'}]}]};
 }});
 t.after(()=>provider.stop());assert.equal((await provider.refresh()).status,'reference_price_ready_not_checkout');assert.equal(calls,4);
 const out=applyPublicPriceCache(snapshot,readPublicPriceCache(provider.cacheFile),{now});
 for(const p of chosen){const model=out.seasonal_model_contracts[p.product_ref.model_id];assert.deepEqual(model.fields,snapshot.seasonal_model_contracts[p.product_ref.model_id].fields);assert.equal(model.combinations[0].price.base_minor,1234);}
 await provider.refresh();assert.equal(calls,4);assert.equal(provider.seedOptions().adminObservations.length,0);
});

import {quantityFixture} from '../runtime/tests/quantity-fixture.mjs';
test('three amounts of the same model share one Admin read and preserve exact per-card price tiers',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tier-price-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const now=Date.parse('2026-10-27T00:00:00Z'),snapshot=quantityFixture(),g=snapshot.halloween.games.find(g=>g.id==='aion'),p=snapshot.products.find(p=>p.product_ref.model_id===g.fixed_model);let calls=0;
 const config={schema_version:2,refresh_interval_ms:60000,entries:['10','30','100'].map(value=>({category_id:'900',model_ref:{site_id:'266',game_id:g.admin_game_id,model_id:g.fixed_model},baseline_region:'us',regional_adjustment:'none_verified',currency:'USD',minor_unit_scale:2,source_field:'more.price',price_semantics:'current_tier_total',evidence_ref:'synthetic-multi',max_age_ms:120000,quantity_value:value,quantity_unit:'M',verified_goods_ids:[p.product_ref.goods_id],ordered_goods_ids:[p.product_ref.goods_id],ordering_evidence:'synthetic-order'}))};
 const provider=makeAdminPriceProvider({publicDir:dir,now:()=>now,readPolicy:()=>config,readSnapshot:()=>snapshot,call:async()=>{calls++;return {source:'admin_readonly',observed_at:new Date(now).toISOString(),coverage:{complete:true},model:{model_id:g.fixed_model,game_id:g.admin_game_id,raw_state:{status:1,auto_off:0}},products:[{product_ref:p.product_ref,platform_attribute_id:p.platform.attribute_id,region_id:'999',raw_state:{status:1,auto_off:0},specification:{saleprop:{present:false}},tiers:['10','30','100'].map(quantity=>({quantity,unit:'M',source_price:quantity,source_discount:'100'}))}]};}});
 t.after(()=>provider.stop());assert.equal((await provider.refresh()).status,'reference_price_ready_not_checkout');assert.equal(calls,1);
 const out=applyPublicPriceCache(snapshot,readPublicPriceCache(provider.cacheFile),{now}),rows=out.seasonal_model_contracts[g.fixed_model].combinations;
 assert.deepEqual(rows.map(r=>r.price.base_minor),[1000,3000,10000]);assert.deepEqual(rows.map(r=>r.choices.quantity_tier),['10','30','100']);assert.equal(out.products.find(x=>x.key===p.key).quantity.max,'100');
});
