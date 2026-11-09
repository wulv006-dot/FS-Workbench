import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {halloweenFixture} from '../../runtime/tests/halloween-fixture.mjs';
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'preview-price-'));
process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');
const {previewReferencePrices}=await import('../production-server.mjs');
test.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
function setup(){
 const now=Date.now(),published=halloweenFixture(),preview=structuredClone(published);
 preview.native_checkout={status:'unconfigured'};preview.pages[0].title='Unsaved title';
 for(const c of Object.values(preview.seasonal_model_contracts))for(const row of c.combinations)delete row.price;
 const cache={schema_version:1,status:'ready',release_id:published.release_id,config_hash:published.config_hash,generated_at:new Date(now).toISOString(),products:structuredClone(published.products),model_contracts:structuredClone(published.seasonal_model_contracts)};
 return {now,published,preview,cache};
}
test('private preview gets fresh prices without checkout or draft changes',()=>{
 const f=setup(),out=previewReferencePrices(f.preview,f.published,f.cache,{now:f.now});
 assert.equal(out.seasonal_model_contracts['41217957'].combinations[0].price.base_minor,1000);
 assert.deepEqual(out.native_checkout,{status:'unconfigured'});assert.equal(out.pages[0].title,'Unsaved title');
 assert.equal(f.preview.seasonal_model_contracts['41217957'].combinations[0].price,undefined);
});
test('expiry, release, identity, platform and option mismatches cannot fill a preview',()=>{
 for(const mutate of [f=>f.cache.release_id='wrong',f=>{for(const c of Object.values(f.cache.model_contracts))for(const r of c.combinations)r.price.expires_at=new Date(f.now).toISOString();},f=>f.preview.products[0].product_ref.goods_id='123',f=>f.preview.products[0].platform.attribute_id='123',f=>f.preview.seasonal_model_contracts['41217957'].combinations[0].quantity.min='2']){
  const f=setup();mutate(f);const out=previewReferencePrices(f.preview,f.published,f.cache,{now:f.now});assert.equal(out.seasonal_model_contracts['41217957'].combinations[0].price,undefined);
 }
});
test('reviewed current proposal price takes precedence',()=>{
 const f=setup(),row=f.preview.seasonal_model_contracts['41217957'].combinations[0];row.price={...f.cache.model_contracts['41217957'].combinations[0].price,base_minor:999};
 assert.equal(previewReferencePrices(f.preview,f.published,f.cache,{now:f.now}).seasonal_model_contracts['41217957'].combinations[0].price.base_minor,999);
});
