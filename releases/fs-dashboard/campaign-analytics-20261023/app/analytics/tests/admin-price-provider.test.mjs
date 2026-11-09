import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
import {makeAdminPriceProvider,readAdminPricePolicy} from '../admin-price-provider.mjs';
import {makeCenterStore} from '../center-store.mjs';import {centerSeed} from '../center-seed.mjs';
import {applyPublicPriceCache,readPublicPriceCache} from '../../runtime/admin-price-cache.mjs';
import {createPublicServer} from '../../runtime/server.mjs';
import selection from '../../seasonal/model-selection.js';
const REF={site_id:'266',game_id:'1327',model_id:'41217957'},PS='163329311';
const FC={products:{},weekly:{ids:[]},trio:{ids:[]},bundles:{ids:[]},sbc:{ids:[],routes:{}}};
function fixture(){
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'admin-reference-cache-')),publicDir=path.join(tmp,'public');
 let clock=Date.parse('2026-01-02T03:04:05Z'),calls=0,fail=false,extraCall=null;
 let config={schema_version:1,refresh_interval_ms:60000,entries:[{category_id:'9623',model_ref:REF,
  baseline_region:'us',regional_adjustment:'none_verified',currency:'USD',minor_unit_scale:2,source_field:'more.price',
  price_semantics:'current_tier_total',evidence_ref:'synthetic-approved-ps-only',max_age_ms:120000,
  quantity_value:'1000',quantity_unit:'K',verified_goods_ids:[PS]}]};
 const state={status:1,auto_off:0};
 const observe=()=>({source:'admin_readonly',observed_at:new Date(clock).toISOString(),coverage:{complete:true},
  model:{model_id:REF.model_id,game_id:REF.game_id,raw_state:state,secret:'PRIVATE_SENTINEL'},
  products:[[PS,'21587'],['900000001','21585'],['900000002','21589']].map(([goods_id,aid])=>({
   product_ref:{...REF,goods_id},raw_state:goods_id===PS?state:{status:0,auto_off:1},platform_attribute_id:aid,region_id:'7645',
   specification:{saleprop:{present:false}},tiers:[{quantity:'1000',unit:'K',source_price:'20.00',source_discount:'80'}],token:'PRIVATE_SENTINEL'}))});
 let provider;
 const store=makeCenterStore({dir:path.join(tmp,'private'),publicDir,sourceRevision:'synthetic',
  seedProvider:()=>centerSeed(FC,{products:[]},provider?.seedOptions()||{})});
 const ref={...REF,goods_id:PS},draft=store.read().draft;
 store.importProduct({revision:0,operation_id:randomUUID(),draft,page_id:'seasonal-vault',product_ref:ref},'synthetic',
  {product_ref:ref,title:'Synthetic Coins',platform_attribute_id:'21587',minimum_quantity:1,unit:'K',authoritative:false,checkout_enabled:false});
 store.publish({revision:1,operation_id:randomUUID()},'synthetic');
 const original=fs.readFileSync(path.join(publicDir,'current.json'),'utf8'),originalDraft=structuredClone(store.read().draft);
 const options={publicDir,readPolicy:()=>config,now:()=>clock,
  readSnapshot:()=>JSON.parse(fs.readFileSync(path.join(publicDir,'current.json'),'utf8')),
  call:async(req,opts)=>{calls++;assert.equal(req.action,'model_provider_batch');assert.equal(req.site_id,'266');
   assert.equal(opts.timeout,300000);assert.equal(req.items.length,1);
   const [item]=req.items;assert.equal(item.site_id,REF.site_id);assert.equal(item.game_id,REF.game_id);
   assert.equal(item.model_id,REF.model_id);assert.equal(item.category_id,'9623');
   const readings={};
   try{const value=extraCall?await extraCall():(fail?(()=>{throw Error('upstream PRIVATE_SENTINEL');})():observe());
    for(const row of req.items)readings[row.key]={status:'ok',data:value};}
   catch{for(const row of req.items)readings[row.key]={status:'error',error:'UPSTREAM_UNAVAILABLE'};}
   return {readings};}};
 provider=makeAdminPriceProvider(options);
 return {tmp,publicDir,store,provider,options,original,originalDraft,observe,
  get config(){return config;},set config(v){config=v;},get calls(){return calls;},set fail(v){fail=v;},set extraCall(v){extraCall=v;},
  get now(){return clock;},advance:n=>{clock+=n;},
  release:()=>JSON.parse(original),clean:()=>{provider.stop();fs.rmSync(tmp,{recursive:true,force:true});}};
}

test('actual private refresh -> safe file -> public HTTP config, independent of configuration/history',async()=>{
 const f=fixture();let server;
 try{
  assert.equal((await f.provider.refresh()).status,'reference_price_ready_not_checkout');assert.equal(f.calls,1);
  const cache=readPublicPriceCache(f.provider.cacheFile);assert.equal(cache.products.length,1);
  assert(!JSON.stringify(cache).includes('PRIVATE_SENTINEL'));assert(!JSON.stringify(cache).includes('raw_state'));
  assert(!JSON.stringify(cache).includes('source_discount'));assert(!JSON.stringify(cache).includes('evidence_ref'));
  assert.equal(cache.model_contracts[REF.model_id].ordering_verified,false);
  assert.equal(fs.readFileSync(path.join(f.publicDir,'current.json'),'utf8'),f.original);assert.deepEqual(f.store.read().draft,f.originalDraft);
  const seed=centerSeed(FC,{products:[]},f.provider.seedOptions());assert.equal(seed.seedProducts.length,1);
  server=createPublicServer({assetRoot:f.publicDir,staticManifest:{},snapshotProvider:f.release,publishedDir:f.publicDir,
   dir:path.join(f.tmp,'runtime'),origin:'http://127.0.0.1',now:()=>f.now});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const read=()=>fetch('http://127.0.0.1:'+server.address().port+'/events/api/campaign/config?model_id=arbitrary-untrusted-id').then(r=>r.json());
  let result=await read();const contract=result.seasonal_model_contracts[REF.model_id];
  assert.equal(contract.combinations[0].price.base_minor,2000);assert.equal(contract.combinations[0].price.currency,'USD');
  assert.equal(contract.combinations.length,1);assert.equal(result.live_checkout,false);assert.equal(f.calls,1);
  assert.throws(()=>selection.defaultPrice(contract,8,{now:()=>f.now}),/DEFAULT_ORDER/);
  const chosen=selection.create(contract,{now:()=>f.now});chosen.select('platform','21587');chosen.select('region','7645');chosen.setQuantity('1000');
  assert.equal(selection.selectedPrice(contract,chosen,8,{now:()=>f.now}).base_minor,2000);
  assert.equal(result.products.find(p=>p.product_ref.goods_id===PS).available,false);
  f.advance(120001);result=await read();assert.equal(result.seasonal_model_contracts,undefined);assert.equal(f.calls,1);
  f.fail=true;await f.provider.refresh();assert.equal(f.calls,2);assert.equal(readPublicPriceCache(f.provider.cacheFile).status,'unavailable');
  assert.equal(f.provider.seedOptions().adminObservations.length,0);
  f.fail=false;await f.provider.refresh();assert.equal(f.calls,2); // bounded failure backoff, no read storm
  f.advance(60000);await f.provider.refresh();assert.equal(f.calls,3);
  result=await read();assert.equal(result.seasonal_model_contracts[REF.model_id].combinations[0].price.base_minor,2000);
  assert.equal(fs.readFileSync(path.join(f.publicDir,'current.json'),'utf8'),f.original);
 }finally{if(server)await new Promise(r=>server.close(r));f.clean();}
});

test('singleflight and explicit bounded timer; cached freshness avoids duplicate Admin reads',async()=>{
 const f=fixture();let timer,cleared=0,release;
 try{
  f.extraCall=()=>new Promise(r=>{release=()=>r(f.observe());});
  const service=makeAdminPriceProvider({...f.options,setTimer:(fn,ms)=>{assert.equal(ms,60000);timer=fn;return {unref(){}};},clearTimer:()=>{cleared++;}});
  const a=service.start(),b=service.refresh();assert.equal(f.calls,1);release();await Promise.all([a,b]);
  await service.refresh();assert.equal(f.calls,1);assert.equal(typeof timer,'function');
  service.stop();assert.equal(cleared,1);
 }finally{f.clean();}
});

test('no policy, wrong goods/model/region/currency or unsafe TTL means zero Admin requests',async()=>{
 for(const change of [()=>null,c=>({...c,refresh_interval_ms:1000}),c=>({...c,entries:[{...c.entries[0],max_age_ms:3600001}]}),
  c=>({...c,entries:[{...c.entries[0],currency:'GBP'}]}),c=>({...c,entries:[{...c.entries[0],verified_goods_ids:['900000001']}]}),
  c=>({...c,entries:[{...c.entries[0],model_ref:{...REF,model_id:'999'}}]})]){
  const f=fixture();try{f.config=change(f.config);await f.provider.refresh();assert.equal(f.calls,0);assert.equal(f.provider.seedOptions().adminObservations.length,0);
   assert.equal(readPublicPriceCache(f.provider.cacheFile).status,'unavailable');}finally{f.clean();}
 }
});

test('policy/release changes invalidate success and cannot commit an inflight old response',async()=>{
 const f=fixture();try{
  await f.provider.refresh();const first=readPublicPriceCache(f.provider.cacheFile);
  const changed=f.release();changed.release_id='synthetic-new-release';changed.config_hash='c'.repeat(64);
  assert.equal(applyPublicPriceCache(changed,first,{now:f.now}).seasonal_model_contracts,undefined);
  f.config=null;await f.provider.refresh();assert.equal(f.calls,1);assert.equal(readPublicPriceCache(f.provider.cacheFile).status,'unavailable');
 }finally{f.clean();}
 const g=fixture();try{let done;g.extraCall=()=>new Promise(r=>{done=r;});const pending=g.provider.refresh();g.config=null;done(g.observe());
  await pending;assert.equal(readPublicPriceCache(g.provider.cacheFile).status,'unavailable');assert.equal(g.provider.seedOptions().adminObservations.length,0);
 }finally{g.clean();}
});

test('late old-generation response cannot invalidate a newer successful policy refresh',async()=>{
 const f=fixture();try{
  const replies=[];f.extraCall=()=>new Promise(resolve=>replies.push(resolve));
  const old=f.provider.refresh();
  f.config={...f.config,entries:[{...f.config.entries[0],evidence_ref:'synthetic-new-approval'}]};
  const newer=f.provider.refresh();assert.equal(f.calls,2);
  replies[1](f.observe());await newer;
  const newCache=fs.readFileSync(f.provider.cacheFile,'utf8');assert.equal(JSON.parse(newCache).status,'ready');
  replies[0](f.observe());await old;
  assert.equal(fs.readFileSync(f.provider.cacheFile,'utf8'),newCache);
  assert.equal(f.provider.status().status,'reference_price_ready_not_checkout');
  assert.equal(f.provider.seedOptions().adminObservations[0].policy.evidence_ref,'synthetic-new-approval');
 }finally{f.clean();}
});

test('public cache rejects extra/private fields, wrong bindings and expired embedded historical prices',async()=>{
 const f=fixture();try{
  await f.provider.refresh();const cache=readPublicPriceCache(f.provider.cacheFile),original=f.release();
  for(const mutate of [c=>c.secret='PRIVATE_SENTINEL',c=>c.config_hash='d'.repeat(64),
   c=>c.products[0].product_ref.goods_id='999',c=>c.model_contracts[REF.model_id].combinations[0].price.currency='GBP']){
   const bad=structuredClone(cache);mutate(bad);assert.equal(applyPublicPriceCache(original,bad,{now:f.now}).seasonal_model_contracts,undefined);
  }
  const withOld=applyPublicPriceCache(original,cache,{now:f.now});
  const missing=applyPublicPriceCache(withOld,null,{now:f.now});assert.equal(missing.seasonal_model_contracts[REF.model_id].combinations[0].price,undefined);
  const expired=applyPublicPriceCache(original,cache,{now:f.now+120001});assert.equal(expired.seasonal_model_contracts,undefined);
 }finally{f.clean();}
});

test('private policy reader rejects public permissions/symlink; timer cache-write failures have safe status',async()=>{
 const f=fixture();try{
  const state=path.join(f.tmp,'backend');fs.mkdirSync(state,{mode:0o700});const policyFile=path.join(state,'policy.json');
  fs.writeFileSync(policyFile,JSON.stringify({admin_reference_prices:f.config}),{mode:0o600});
  assert.deepEqual(readAdminPricePolicy(state),f.config);
  if(process.platform!=='win32'){fs.chmodSync(policyFile,0o644);assert.throws(()=>readAdminPricePolicy(state),/PRIVATE_PRICE_POLICY_REQUIRED/);}
  let timer;const service=makeAdminPriceProvider({...f.options,setTimer:fn=>{timer=fn;return {unref(){}};},clearTimer:()=>{}});
  await service.start();fs.unlinkSync(service.cacheFile);fs.mkdirSync(service.cacheFile);
  f.advance(120001);timer();await new Promise(r=>setTimeout(r,25));
  assert.equal(service.status().reason,'PUBLIC_PRICE_CACHE_WRITE_FAILED');service.stop();
 }finally{f.clean();}
});

test('current FC pages use the same producer and public price overlay',async()=>{
 const f=fixture();let provider;
 try{
  const release=f.release(),seasonal=release.pages.find(p=>p.page_id==='seasonal-vault'),weekly=release.pages.find(p=>p.page_id==='fc27-weekly');weekly.product_keys=[...seasonal.product_keys];seasonal.product_keys=[];delete seasonal.product_roles;
  provider=makeAdminPriceProvider({...f.options,readSnapshot:()=>release});
  const refreshed=await provider.refresh();assert.equal(refreshed.status,'reference_price_ready_not_checkout',JSON.stringify(refreshed));
  const projected=applyPublicPriceCache(release,readPublicPriceCache(provider.cacheFile),{now:f.now});
  assert.equal(projected.seasonal_model_contracts[REF.model_id].combinations[0].price.base_minor,2000);
 }finally{provider?.stop();f.clean();}
});
test('approved 88-model union fits bounded policy without admitting unlimited entries',async()=>{
 const f=fixture();
 try{
  const entry=f.config.entries[0];f.config={schema_version:2,refresh_interval_ms:60000,entries:Array.from({length:88},(_,i)=>({...entry,model_ref:{...REF,model_id:String(1000+i)}}))};
  assert.equal((await f.provider.refresh()).reason,'PUBLISHED_SELECTION_REQUIRED');assert.equal(f.calls,0);
  f.config.entries=Array.from({length:101},(_,i)=>({...entry,model_ref:{...REF,model_id:String(1000+i)}}));
  assert.equal((await f.provider.refresh()).reason,'PRIVATE_PRICE_POLICY_REQUIRED');assert.equal(f.calls,0);
 }finally{f.clean();}
});
