import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {halloweenFixture} from '../../runtime/tests/halloween-fixture.mjs';
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'preview-price-'));
process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');
const {previewReferencePrices,pageSeed}=await import('../production-server.mjs');
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

test('both preview callers share normalized nine-core layout while dormant routes and 18-player pool remain in draft',async()=>{
 const {initialLayout,validateLayout}=await import('../store.mjs'),{makeCenterStore,initialCenterDraft}=await import('../center-store.mjs'),{effectiveFcCatalog}=await import('../../runtime/model-cards.mjs');
 const catalog=JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url))),layout=structuredClone(initialLayout(catalog));
 const model=(n,kind)=>({key:'model-266-1327-'+n,site_id:'266',game_id:'1327',model_id:String(n),kind,title:'Fixture '+n,version_label:null,image_url:null,site_association:'observed',verification_scope:'catalog_identity_only',available:false,authoritative:false,checkout_enabled:false,platforms:Object.fromEntries(['ps','xbox','pc'].map(p=>[p,{state:'unknown',product_ref:null,observed_quantity:null}]))});
 const cores=Array.from({length:9},(_,i)=>model(990000+i,'sbc')),players=Array.from({length:18},(_,i)=>model(990100+i,'player')),models=Object.fromEntries([...cores,...players].map(m=>[m.key,m]));
 layout.sbc=cores.map(m=>m.key);layout.defaultCore=layout.sbc[0];for(let i=0;i<9;i++){const picks=players.slice(i*2,i*2+2).map(m=>m.key);layout.routes[cores[i].key]={picks,alternatives:players.map(m=>m.key).filter(k=>!picks.includes(k))};}
 const original=structuredClone(layout),seed=pageSeed(layout,models);
 assert.equal(Object.keys(seed.fc_layout.routes).length,9);assert.equal(seed.fc_layout.sbc.length,9);assert(Object.values(seed.fc_layout.routes).every(r=>r.picks.length===2&&r.alternatives.length===16));assert.deepEqual(layout,original);
 // Both workflow makePreviews and center/preview pass this same seed to the original snapshot contract.
 const store=makeCenterStore({sourceRevision:'dormant-fixture',dir:path.join(dir,'dormant-center'),publicDir:path.join(dir,'dormant-public'),seedProvider:()=>seed,validateFcLayout:(l,m)=>validateLayout(l,effectiveFcCatalog(catalog,m))});
 const snapshot=store.preview({revision:0,draft:initialCenterDraft()},[],[],{seed});
 assert.equal(snapshot.fc_layout.sbc.length,9);assert.equal(Object.keys(snapshot.fc_layout.routes).length,9);assert.deepEqual(snapshot.native_checkout,{status:'unconfigured'});assert.equal(fs.existsSync(path.join(dir,'dormant-center')),false);assert.deepEqual(layout,original);
});
