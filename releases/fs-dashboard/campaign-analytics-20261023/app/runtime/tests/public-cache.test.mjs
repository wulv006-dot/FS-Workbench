import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import {fileURLToPath} from 'node:url';
import {publicConfigCache} from '../public-config-cache.mjs';import {createPublicServer} from '../server.mjs';import {digest} from '../snapshot.mjs';import {halloweenFixture} from './halloween-fixture.mjs';

test('public cache expires by TTL, source stamp and price deadline; clock rollback and changing generation never reuse stale data',()=>{
 let clock=1000,version='v1',renders=0,deadline=2500;
 const get=publicConfigCache({ttlMs:2000,now:()=>clock,stamp:()=>version,render:()=>({body:String(++renders),expiresAt:deadline})});
 assert.equal(get(),'1');clock=2000;assert.equal(get(),'1');version='v2';assert.equal(get(),'2');clock=2500;assert.equal(get(),'3');clock=2400;assert.equal(get(),'4');
 deadline=10000;clock=3000;assert.equal(get(),'5');clock=5000;assert.equal(get(),'6');clock=2000;assert.equal(get(),'7');
 const changing=publicConfigCache({ttlMs:2000,now:()=>clock,stamp:()=>version,render:()=>{version+='x';return {body:String(++renders)};}});changing();changing();assert.equal(renders,9);
 const off=publicConfigCache({render:()=>({body:String(++renders)})});off();off();assert.equal(renders,11);
 assert.throws(()=>publicConfigCache({ttlMs:5001,stamp:()=>'',render:()=>({body:''})}),/INVALID_PUBLIC_CACHE_OPTIONS/);
});

test('actual runtime cache masks codes, invalidates on release/price stamps and never outlives a reference price',async()=>{
 const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'public-cache-')),snapshot=halloweenFixture();
 let clock=Date.parse('2026-10-29T09:00:00Z'),version='release1-price1',reads=0;
 for(const c of Object.values(snapshot.seasonal_model_contracts))for(const row of c.combinations)row.price.expires_at=new Date(clock+1000).toISOString();
 const server=createPublicServer({assetRoot:app,staticManifest:{'seasonal/event.js':digest(fs.readFileSync(path.join(app,'seasonal/event.js')))},snapshotProvider:()=>{reads++;return snapshot;},priceCacheProvider:()=>({schema_version:1,status:'ready',release_id:snapshot.release_id,config_hash:snapshot.config_hash,generated_at:new Date(clock).toISOString(),products:snapshot.products,model_contracts:snapshot.seasonal_model_contracts}),dir,origin:'http://127.0.0.1',now:()=>clock,configCacheMs:2000,configStampProvider:()=>version});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port,get=()=>fetch(base+'/events/api/campaign/config');
 try{
  const first=await get(),a=await first.json();assert.equal(first.headers.get('cache-control'),'no-store');assert(a.native_checkout.bindings.every(b=>b.code==='CLAIM_REQUIRED'));const count=reads;
  await (await get()).text();assert.equal(reads,count);
  snapshot.release_id='synthetic-cache-v2';version='release2-price1';assert.equal((await (await get()).json()).release_id,snapshot.release_id);assert(reads>count);const afterRelease=reads;
  version='release2-price2';await (await get()).text();assert(reads>afterRelease);const afterPrice=reads;
  clock+=1000;const expired=await (await get()).json();assert(reads>afterPrice);assert(Object.values(expired.seasonal_model_contracts).every(c=>c.combinations.every(x=>!x.price)));
  // Cache state never changes POST Origin/receipt requirements.
  const refused=await fetch(base+'/events/api/campaign/halloween/reveal',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://elsewhere.invalid'},body:'{}'});assert.equal(refused.status,403);assert.equal((await refused.json()).code,'ORIGIN_REQUIRED');
 }finally{await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
});

test('versioned static caching is opt-in; HTML/dynamic data stay no-store and mismatched versions revalidate',async()=>{
 const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'public-static-cache-')),name='seasonal/event.js',hash=digest(fs.readFileSync(path.join(app,name))),manifest=Object.fromEntries([name,'seasonal/index.html','catalog.js'].map(n=>[n,digest(fs.readFileSync(path.join(app,n)))]));
 for(const enabled of [false,true]){
  const server=createPublicServer({assetRoot:app,staticManifest:manifest,snapshotProvider:halloweenFixture,dir,origin:'http://127.0.0.1',staticCacheEnabled:enabled});await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port+'/events/';
  try{
   const exact=await fetch(base+name+'?v='+hash);assert.equal(exact.status,200);assert.equal(exact.headers.get('cache-control'),enabled?'public, max-age=31536000, immutable':'no-store');await exact.arrayBuffer();
   const old=await fetch(base+name+'?v=old');assert.equal(old.headers.get('cache-control'),enabled?'no-cache':'no-store');await old.arrayBuffer();
   const duplicate=await fetch(base+name+'?v='+hash+'&v=old');assert.equal(duplicate.headers.get('cache-control'),enabled?'no-cache':'no-store');await duplicate.arrayBuffer();
   const conditional=await fetch(base+name,{headers:{'If-None-Match':'"'+hash+'"'}});assert.equal(conditional.status,enabled?304:200);if(!enabled)await conditional.arrayBuffer();
   const config=await fetch(base+'api/campaign/config');assert.equal(config.headers.get('cache-control'),'no-store');await config.arrayBuffer();
   const html=await fetch(base+'seasonal/');assert.equal(html.status,200);assert.equal(html.headers.get('cache-control'),'no-store');await html.arrayBuffer();
   const catalog=await fetch(base+'catalog.js?v='+manifest['catalog.js']);assert.equal(catalog.status,200);assert.equal(catalog.headers.get('cache-control'),'no-store');await catalog.arrayBuffer();
  }finally{await new Promise(r=>server.close(r));}
 }
 fs.rmSync(dir,{recursive:true,force:true});
});

test('real published/price file replacement invalidates warm cache and a missing release cannot serve stale data',async()=>{
 const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'public-cache-files-')),releaseFile=path.join(dir,'current.json'),priceFile=path.join(dir,'admin-reference-prices.json'),snapshot=halloweenFixture();
 const put=(file,value)=>{fs.writeFileSync(file+'.next',JSON.stringify(value));fs.renameSync(file+'.next',file);};
 const prices={schema_version:1,status:'ready',release_id:snapshot.release_id,config_hash:snapshot.config_hash,generated_at:new Date().toISOString(),products:snapshot.products,model_contracts:structuredClone(snapshot.seasonal_model_contracts)};put(releaseFile,snapshot);put(priceFile,prices);
 const server=createPublicServer({assetRoot:app,staticManifest:{},snapshotProvider:()=>JSON.parse(fs.readFileSync(releaseFile)),publishedDir:dir,releaseFile,configCacheMs:2000,dir:path.join(dir,'runtime'),origin:'http://127.0.0.1'});await new Promise(r=>server.listen(0,'127.0.0.1',r));const get=()=>fetch('http://127.0.0.1:'+server.address().port+'/events/api/campaign/config');
 try{
  const first=await (await get()).json(),id=Object.keys(prices.model_contracts)[0];assert.equal(first.seasonal_model_contracts[id].combinations[0].price.base_minor,1000);
  prices.model_contracts[id].combinations[0].price.base_minor=2222;put(priceFile,prices);const changedPrice=await (await get()).json();assert.equal(changedPrice.seasonal_model_contracts[id].combinations[0].price.base_minor,2222);
  snapshot.release_id='replaced-release';put(releaseFile,snapshot);assert.equal((await (await get()).json()).release_id,'replaced-release');
  fs.unlinkSync(releaseFile);const missing=await get();assert.equal(missing.status,500);assert.equal((await missing.json()).code,'RUNTIME_UNAVAILABLE');
 }finally{await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
});
