import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {createCommerce} from '../commerce.mjs';
import {projectRelease,digest} from '../snapshot.mjs';
import {createPublicServer} from '../server.mjs';
import handoff from '../../native-code-handoff.js';
import {halloweenFixture} from './halloween-fixture.mjs';
function setup(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'halloween61-')),snapshot=halloweenFixture();t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return {dir,snapshot,create:options=>createCommerce({snapshotProvider:()=>snapshot,dir,...options})};}
test('four games reveal one fixed + two distinct server picks; zero-weight tiers never selected; reload keeps receipt',t=>{
 const f=setup(t),c=f.create();
 for(const game of f.snapshot.halloween.games){
  const body={request_id:randomUUID(),game_id:game.id},receipt=c.halloweenReveal(body);
  assert.equal(receipt.slots.length,3);assert.deepEqual(receipt.slots[0],{slot:'fixed',model_id:game.fixed_model,off_percent:10});
  assert.equal(new Set(receipt.slots.map(s=>s.model_id)).size,3);assert(receipt.slots.slice(1).every(s=>s.off_percent===8&&game.random_models.includes(s.model_id)));
  assert.deepEqual(f.create().halloweenReveal(body),receipt);
  const selected=receipt.slots[1],query={request_id:body.request_id,game_id:body.game_id,...selected};
  assert.equal(c.halloweenResolve(query).status,'selection_confirmed');assert.throws(()=>c.halloweenResolve({...query,off_percent:15}),{code:'HALLOWEEN_REVEAL_MISMATCH'});
  assert.throws(()=>c.halloweenReveal({...body,game_id:game.id==='fc'?'aion':'fc'}),{code:'REQUEST_CONFLICT'});
 }
});
test('incomplete pool, no observed serialization, unconfigured or ended event cannot draw',t=>{
 for(const mutation of [s=>s.native_checkout={status:'unconfigured'},s=>s.halloween.probabilities=null,s=>s.halloween.ends_at='2021-01-01T00:00:00Z',s=>s.native_checkout.bindings=s.native_checkout.bindings.filter(b=>b.product_key!=='synthetic61-'+s.halloween.games[0].random_models[1])]){
  const f=setup(t);mutation(f.snapshot);assert.throws(()=>f.create().halloweenReveal({request_id:randomUUID(),game_id:'fc'}));
 }
});
test('unknown reservation never rerolls; changed publication does not reuse old receipt',t=>{
 const f=setup(t),c=f.create(),body={request_id:randomUUID(),game_id:'wow'},receipt=c.halloweenReveal(body),file=path.join(f.dir,'preview/halloween-reveals',body.request_id+'.json');
 const original=fs.readFileSync(file);fs.writeFileSync(file,'{"status":"unknown"}');assert.throws(()=>c.halloweenReveal(body),{code:'HALLOWEEN_REVEAL_UNKNOWN'});assert.equal(fs.readFileSync(file,'utf8'),'{"status":"unknown"}');
 fs.writeFileSync(file,original);f.snapshot.config_hash='c'.repeat(64);assert.throws(()=>c.halloweenRead(receipt.request_id),{code:'RULE_VERSION_CONFLICT'});
});
test('dynamic mode requires a fresh complete trusted observation and excludes duplicate/fixed/unavailable models',t=>{
 const f=setup(t),game=f.snapshot.halloween.games[1],models=[...game.random_models];game.random_source={mode:'category_dynamic',category_id:'950000',snapshot_complete:false};game.random_models=[];
 let observation={observed_at:new Date().toISOString(),expires_at:new Date(Date.now()+60000).toISOString(),complete:true,models:[game.fixed_model,...models,models[0]].map(model_id=>({site_id:'266',game_id:game.admin_game_id,category_id:'950000',model_id,sellable:true}))};
 assert.throws(()=>f.create().halloweenReveal({request_id:randomUUID(),game_id:game.id}),{code:'HALLOWEEN_CATALOG_STALE'});
 const c=f.create({halloweenCatalogProvider:()=>observation});assert.equal(c.halloweenReveal({request_id:randomUUID(),game_id:game.id}).slots.length,3);
 observation.complete=false;assert.throws(()=>c.halloweenReveal({request_id:randomUUID(),game_id:game.id}),{code:'HALLOWEEN_POOL_INCOMPLETE'});
 observation.complete=true;observation.expires_at='2020-01-01T00:00:00Z';assert.throws(()=>c.halloweenReveal({request_id:randomUUID(),game_id:game.id}),{code:'HALLOWEEN_CATALOG_STALE'});
});
test('random checkout checks server receipt before any native mutation; observed quantity/spec fields stay exact',async t=>{
 const f=setup(t),c=f.create(),receipt=c.halloweenReveal({request_id:randomUUID(),game_id:'wow'}),slot=receipt.slots.find(s=>s.model_id===f.snapshot.halloween.games[2].random_models[0]),product=f.snapshot.products.find(p=>p.product_ref.model_id===slot.model_id),binding=f.snapshot.native_checkout.bindings.find(b=>b.product_key===product.key&&b.off_percent===slot.off_percent),snapshot=projectRelease(f.snapshot);
 const selection={activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',game_id:product.product_ref.game_id,...slot,reveal_request_id:receipt.request_id,lines:[{product_key:product.key,quantity:{...binding.quantity},attributes:binding.attributes}]},data=new Map(),storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};let calls=0;
 const host={verifySelection:async b=>c.halloweenResolve(b),batch:()=>({run:async items=>{calls++;assert.deepEqual(items[0].native_payload,binding.native);return [{id:Number(binding.native.id),state:'confirmed'}];}})};
 await assert.rejects(handoff.checkoutPublished({snapshot,selection:{...selection,slot:selection.slot==='random-1'?'random-2':'random-1'},storage,host,origin:snapshot.native_checkout.origin,navigate:()=>{}}),/HALLOWEEN_REVEAL_MISMATCH/);assert.equal(calls,0);assert.equal(data.size,0);
 const result=await handoff.checkoutPublished({snapshot,selection,storage,host,origin:snapshot.native_checkout.origin,navigate:()=>{}});assert.equal(result.state,'navigation_attempted_not_applied');assert.equal(calls,1);assert.equal(data.get('pending_discount_code'),'SYNTHETIC61-8');
 await handoff.checkoutPublished({snapshot,selection,storage,host,origin:snapshot.native_checkout.origin,navigate:()=>{}});assert.equal(calls,1);
 const invalid=structuredClone(f.snapshot);invalid.native_checkout.bindings.find(b=>b.observed_serialization).observed_serialization.model_id='123';assert.throws(()=>projectRelease(invalid),{code:'NATIVE_CONFIGURATION_INVALID'});
 const gift=structuredClone(f.snapshot);gift.native_checkout.bindings[0].native.group='1050';assert.throws(()=>projectRelease(gift),{code:'NATIVE_CONFIGURATION_INVALID'});
});
test('actual HTTP reveal/resolve routes enforce Origin and expose only bounded receipt fields',async t=>{
 const f=setup(t),file=path.join(f.dir,'index.html');fs.writeFileSync(file,'public');const server=createPublicServer({assetRoot:f.dir,staticManifest:{'index.html':digest('public')},snapshot:f.snapshot,dir:f.dir,origin:'https://www.mmoexp.com',priceCacheProvider:()=>({schema_version:1,status:'ready',release_id:f.snapshot.release_id,config_hash:f.snapshot.config_hash,generated_at:new Date().toISOString(),products:f.snapshot.products,model_contracts:f.snapshot.seasonal_model_contracts})});await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
 const url='http://127.0.0.1:'+server.address().port+'/events/api/campaign/halloween/',body={request_id:randomUUID(),game_id:'fc'},post=(route,data,origin='https://www.mmoexp.com')=>fetch(url+route,{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify(data)});
 assert.equal((await post('reveal',body,'https://wrong.invalid')).status,403);const response=await post('reveal',body);assert.equal(response.status,200);const receipt=await response.json();assert.doesNotMatch(JSON.stringify(receipt),/SYNTHETIC61-8|observed_serialization|native_checkout/);
 const publicConfig=await(await fetch('http://127.0.0.1:'+server.address().port+'/events/api/campaign/config')).json();assert.equal(publicConfig.native_checkout_claim_required,true);assert.doesNotMatch(JSON.stringify(publicConfig),/SYNTHETIC61-(8|10|15)/);
 const slot=receipt.slots[1],product=f.snapshot.products.find(p=>p.product_ref.model_id===slot.model_id),binding=f.snapshot.native_checkout.bindings.find(b=>b.product_key===product.key&&b.off_percent===slot.off_percent);
 const selection={activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',game_id:product.product_ref.game_id,...slot,reveal_request_id:receipt.request_id,lines:[{product_key:product.key,quantity:binding.quantity,attributes:binding.attributes}]};
 const nativeUrl='http://127.0.0.1:'+server.address().port+'/events/api/campaign/native_plan',nativePost=value=>fetch(nativeUrl,{method:'POST',headers:{Origin:'https://www.mmoexp.com','Content-Type':'application/json'},body:JSON.stringify(value)});
 const selected=await(await nativePost(selection)).json();assert.equal(selected.native_checkout.bindings.length,1);assert.equal(selected.native_checkout.bindings[0].code,'SYNTHETIC61-8');assert.notEqual((await nativePost({...selection,off_percent:15})).status,200);
 assert.deepEqual(await(await fetch(url+'reveals/'+body.request_id)).json(),receipt);assert.equal((await post('resolve',{request_id:body.request_id,game_id:'fc',...receipt.slots[1]})).status,200);
});
