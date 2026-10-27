import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {projectNativeCatalog,readNativeLaunchPolicy,mergeNativeCatalog} from '../analytics/native-catalog.mjs';
import {halloweenFixture} from '../runtime/tests/halloween-fixture.mjs';
function fixture(){const f=halloweenFixture();return {f,c:{schema_version:1,verification_ref:'synthetic-native-catalog',observed_at:'2026-10-26T00:00:00Z',valid_until:'2026-10-28T00:00:00Z',products:f.products,model_contracts:f.seasonal_model_contracts}};}
const now=Date.parse('2026-10-27T00:00:00Z');
test('private catalog joins exact models without promoting prices or commerce flags',()=>{
 const {c}=fixture(),before=JSON.stringify(c),projected=projectNativeCatalog(c,{now});
 assert.equal(projected.products.length,12);assert(projected.products.every(p=>p.available===false));
 const seed={seedProducts:[],seasonal_model_contracts:{},pageProductKeys:{'seasonal-vault':[]}};
 const joined=mergeNativeCatalog(seed,projected);assert.equal(joined.seedProducts.length,12);assert.equal(joined.pageProductKeys['seasonal-vault'].length,12);assert.equal(seed.seedProducts.length,0);assert.equal(JSON.stringify(c),before);
 for(const contract of Object.values(joined.seasonal_model_contracts))assert(contract.combinations.every(c=>!c.price));
});
test('expired, future, wrong site and mismatched model mappings reject',()=>{
 for(const mutate of [c=>c.valid_until='2026-10-26T00:00:01Z',c=>c.observed_at='2026-10-28T00:00:00Z',c=>c.products[0].product_ref.site_id='267',c=>c.products[0].available=true,c=>delete c.model_contracts[c.products[0].product_ref.model_id]]){
  const {c}=fixture();mutate(c);assert.throws(()=>projectNativeCatalog(c,{now}));
 }
});
test('private policy checks permission, exact observed identities and does not expose unrelated fields',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'native-catalog-test-'));fs.chmodSync(dir,0o700);t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const {f,c}=fixture(),file=path.join(dir,'policy.json'),policy={native_catalog:c,native_checkout:f.native_checkout,unrelated:'must not return'};
 fs.writeFileSync(file,JSON.stringify(policy),{mode:0o600});const read=readNativeLaunchPolicy(dir,{now});assert.deepEqual(Object.keys(read).sort(),['catalog','checkout']);
 policy.native_checkout.bindings.find(b=>b.observed_serialization).observed_serialization.model_id='999';fs.writeFileSync(file,JSON.stringify(policy));assert.throws(()=>readNativeLaunchPolicy(dir,{now}),{code:'NATIVE_CATALOG_SCOPE_MISMATCH'});
 if(process.platform!=='win32'){fs.chmodSync(file,0o644);assert.throws(()=>readNativeLaunchPolicy(dir,{now}),{code:'PRIVATE_NATIVE_POLICY_REQUIRED'});}
});
test('catalog cannot overwrite same key with different source identity',()=>{
 const {c}=fixture(),catalog=projectNativeCatalog(c,{now}),seed={seedProducts:[structuredClone(catalog.products[0])],seasonal_model_contracts:{},pageProductKeys:{}};
 seed.seedProducts[0].product_ref.goods_id='999';assert.throws(()=>mergeNativeCatalog(seed,catalog),{code:'NATIVE_CATALOG_SCOPE_MISMATCH'});
});
