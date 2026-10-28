import test from 'node:test';
import assert from 'node:assert/strict';
import {halloweenFixture} from '../runtime/tests/halloween-fixture.mjs';
import {applyPublicPriceCache} from '../runtime/admin-price-cache.mjs';
const now=Date.parse('2026-10-27T00:00:00Z');
function setup(){const snapshot=halloweenFixture();const cache={schema_version:1,status:'ready',release_id:snapshot.release_id,config_hash:snapshot.config_hash,generated_at:new Date(now).toISOString(),products:structuredClone(snapshot.products),model_contracts:structuredClone(snapshot.seasonal_model_contracts)};for(const c of Object.values(cache.model_contracts))for(const row of c.combinations)row.price={source:'admin_current',base_minor:1234,currency:'USD',minor_unit_scale:2,quantity_value:row.quantity.min,expires_at:new Date(now+60000).toISOString()};return {snapshot,cache};}
test('four-game price overlay accepts only published identities and exact combination quantities',()=>{
 const {snapshot,cache}=setup(),out=applyPublicPriceCache(snapshot,cache,{now});
 assert.equal(Object.keys(out.seasonal_model_contracts).length,12);
 for(const c of Object.values(out.seasonal_model_contracts))assert.equal(c.combinations[0].price.base_minor,1234);
 assert(out.products.every(p=>p.available===false));assert.equal(snapshot.seasonal_model_contracts['41217957'].combinations[0].price.base_minor,1000);
});
test('new price projection cannot invent server options, SKU identity, currency or quantity conversion',()=>{
 for(const mutate of [c=>c.products[0].product_ref.goods_id='999',c=>c.model_contracts['41217957'].fields[0].label='Different field',c=>c.model_contracts['41217957'].combinations[0].price.quantity_value='1050',c=>c.model_contracts['41217957'].combinations[0].price.currency='GBP']){
  const {snapshot,cache}=setup();mutate(cache);const out=applyPublicPriceCache(snapshot,cache,{now});for(const c of Object.values(out.seasonal_model_contracts))assert.equal(c.combinations[0].price,undefined);
 }
});
test('expiry drops only the expired combination, including the exact expiry instant',()=>{
 const {snapshot,cache}=setup();cache.model_contracts['41217957'].combinations[0].price.expires_at=new Date(now).toISOString();
 const out=applyPublicPriceCache(snapshot,cache,{now});assert.equal(out.seasonal_model_contracts['41217957'].combinations[0].price,undefined);
 for(const [id,c] of Object.entries(out.seasonal_model_contracts))if(id!=='41217957')assert.equal(c.combinations[0].price.base_minor,1234);
});

test('partial fresh price set preserves every unpriced published product and option',()=>{
 const {snapshot,cache}=setup();cache.products=cache.products.slice(0,1);cache.model_contracts={'41217957':cache.model_contracts['41217957']};
 const out=applyPublicPriceCache(snapshot,cache,{now});assert.equal(Object.keys(out.seasonal_model_contracts).length,12);assert.equal(out.products.length,12);assert.equal(out.seasonal_model_contracts['41217957'].combinations[0].price.base_minor,1234);
 const stale=applyPublicPriceCache(out,null,{now});assert.equal(stale.seasonal_model_contracts['41217957'].combinations[0].price,undefined);
});
