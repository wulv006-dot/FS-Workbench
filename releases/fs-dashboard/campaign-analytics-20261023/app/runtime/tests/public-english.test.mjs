import test from 'node:test';
import assert from 'node:assert/strict';
import {publicEnglishRelease,presentPage} from '../presentation.mjs';
import {projectPreviewProduct} from '../snapshot.mjs';
const paths=['Weekly-Scout.html','Sbc-Companions.html','Player-Trio.html','seasonal/index.html'];
const fixture=()=>({schema_version:1,publication_status:'published',release_id:'fixture',config_hash:'a'.repeat(64),rule_hash:'b'.repeat(64),pages:paths.map((path,i)=>({page_id:'page-'+i,path,title:'演示活动',description:'中文后台说明',active:true,product_keys:[],default_language:'zh',starts_at:null,ends_at:null})),products:[]});
const source='<!doctype html><html lang="en"><head><title>Original English title</title><meta name="description" content="Original English description"><meta property="og:locale" content="en_US"><script type="application/ld+json">{"@type":"CollectionPage","name":"Original English title","description":"Original English description"}</script></head><body><main>Original English content</main></body></html>';
test('all four public active/upcoming/ended pages reject Chinese management copy without changing the release',()=>{
 for(const state of ['active','upcoming','ended']){
  const s=fixture();if(state==='upcoming')s.pages.forEach(p=>p.starts_at='2099-01-01T00:00:00Z');if(state==='ended')s.pages.forEach(p=>p.ends_at='2000-01-01T00:00:00Z');const before=structuredClone(s);
  for(const path of paths){const r=presentPage({name:path,body:source,snapshot:s,now:'2026-10-25T00:00:00Z'});assert(!/\p{Script=Han}/u.test(r.body));assert.match(r.body,/<html lang="en">/);assert(!r.body.includes('zh_CN'));}
  assert.deepEqual(s,before);
 }
});
test('public response retains IDs, hashes, selection and gates while using explicit product identity fallback',()=>{
 const s=fixture(),product={key:'admin-266-1327-900000001-unknown',title:'商品ID 900000001',title_source:'identity_fallback',product_ref:{site_id:'266',game_id:'1327',goods_id:'900000001',model_id:'900000002'},platform:{code:'unknown'},preview_only:true,available:false,quantity:null,attributes:[],observed_quantity:{minimum:null,unit:'金币',group:null},preview_reason:'PURCHASE_MAPPING_UNVERIFIED'};
 s.products=[product];s.pages[0].product_keys=[product.key];s.fc_layout={routes:{core:{picks:[],alternatives:[],label:{zh:'中文',en:'中文英文栏'}}}};const before=structuredClone(s),result=publicEnglishRelease(s);
 assert.equal(result.products[0].title,'Product ID 900000001');assert.equal(result.products[0].observed_quantity.unit,null);assert.equal(result.products[0].available,false);assert.deepEqual(result.products[0].product_ref,product.product_ref);assert.equal(result.config_hash,s.config_hash);assert.deepEqual(result.pages[0].product_keys,s.pages[0].product_keys);assert.equal(result.pages[0].default_language,'en');assert.equal(result.fc_layout.routes.core.label.en,'Companion ideas');assert.deepEqual(s,before);assert.doesNotThrow(()=>projectPreviewProduct(result.products[0]));
 const html=presentPage({name:paths[0],body:source,snapshot:s}).body;assert(!/\p{Script=Han}/u.test(html));assert.match(html,/Product ID 900000001/);assert.match(html,/English product title is unavailable/);
});
test('already-English customer copy remains intact including accented player names',()=>{
 const s=fixture();s.pages[0].title='My weekly picks';s.pages[0].description='Choose your lineup.';s.products=[{title:'Alphadjo Cissè',product_ref:{goods_id:'1'},available:false}];const r=publicEnglishRelease(s);assert.equal(r.pages[0].title,s.pages[0].title);assert.equal(r.pages[0].description,s.pages[0].description);assert.equal(r.products[0].title,'Alphadjo Cissè');
});

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createPublicServer} from '../server.mjs';
import {digest} from '../snapshot.mjs';
test('real public HTTP projects legacy Chinese config and HTML without altering immutable input or enabling checkout',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'english-policy-')),s=fixture();s.source_revision='fixture';s.pages[3].default_language='en';s.pages.forEach((p,i)=>{p.activity_id='activity-'+i;p.rule_version='fixture';p.benefit_binding_version='fixture';});const before=JSON.stringify(s);fs.writeFileSync(path.join(dir,'Weekly-Scout.html'),source);
 const server=createPublicServer({assetRoot:dir,staticManifest:{'Weekly-Scout.html':digest(source)},snapshot:s,dir:path.join(dir,'data'),mode:'preview',origin:'http://localhost'});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{const base='http://127.0.0.1:'+server.address().port+'/events/';const cfg=await(await fetch(base+'api/campaign/config')).json();assert.equal(cfg.pages[0].title,'Weekly Player Picks');assert.equal(cfg.pages[0].default_language,'en');assert.equal(cfg.live_checkout,false);assert(!/\p{Script=Han}/u.test(JSON.stringify(cfg)));const html=await(await fetch(base+'Weekly-Scout.html')).text();assert(!/\p{Script=Han}/u.test(html));const caps=await(await fetch(base+'api/campaign/capabilities')).json();assert.equal(caps.capabilities.cart_handoff,false);assert.equal(JSON.stringify(s),before);}finally{await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
});
