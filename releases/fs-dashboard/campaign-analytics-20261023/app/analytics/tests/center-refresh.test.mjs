import test from 'node:test';import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {halloweenFixture} from '../../runtime/tests/halloween-fixture.mjs';

test('authenticated editor GET responds while an Admin price batch is still pending',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'center-refresh-')),publicDir=path.join(dir,'public'),backend=path.join(dir,'backend'),release=path.join(dir,'release');
 fs.mkdirSync(publicDir);fs.mkdirSync(backend,{mode:0o700});
 const snapshot=halloweenFixture(),p=snapshot.products[0];fs.writeFileSync(path.join(publicDir,'current.json'),JSON.stringify(snapshot));
 fs.writeFileSync(path.join(backend,'policy.json'),JSON.stringify({admin_reference_prices:{schema_version:2,refresh_interval_ms:60000,entries:[{category_id:'900',model_ref:{site_id:'266',game_id:'1327',model_id:p.product_ref.model_id},baseline_region:'us',regional_adjustment:'none_verified',currency:'USD',minor_unit_scale:2,source_field:'more.price',price_semantics:'current_tier_total',evidence_ref:'synthetic-pending',max_age_ms:120000,quantity_value:p.quantity.min,quantity_unit:p.quantity.unit,verified_goods_ids:[p.product_ref.goods_id],ordered_goods_ids:[p.product_ref.goods_id],ordering_evidence:'synthetic-order'}]}}),{mode:0o600});
 // Poll the release condition itself: a file created between existsSync and
 // watchFile's initial stat can become the watcher's unchanged baseline forever.
 const bridge=path.join(dir,'pending.cjs');fs.writeFileSync(bridge,`const fs=require('node:fs');process.stdin.resume();const file=${JSON.stringify(release)};let timer;function done(){if(fs.existsSync(file)){if(timer)clearInterval(timer);console.log(JSON.stringify({status:'error',error:'SYNTHETIC_UNAVAILABLE'}));return true;}}if(!done())timer=setInterval(done,20);`);
 Object.assign(process.env,{CAMPAIGN_DATA:dir,CAMPAIGN_PUBLIC_RELEASE_DIR:publicDir,CAMPAIGN_BACKEND_STATE_DIR:backend,CAMPAIGN_PYTHON:process.execPath,CAMPAIGN_BACKEND_BRIDGE:bridge});
 const real=globalThis.fetch;globalThis.fetch=(url,options)=>String(url).includes(':8895/verify')?Promise.resolve(new Response('',{status:200,headers:{'x-auth-user':'synthetic','x-auth-role':'admin'}})):real(url,options);
 const {server}=await import('../production-server.mjs');await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  const response=await real('http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/api/center',{signal:AbortSignal.timeout(2000)});
  assert.equal(response.status,200);assert.equal((await response.json()).canEdit,true);assert.equal(fs.existsSync(release),false);
 }finally{fs.writeFileSync(release,'release synthetic batch');await new Promise(resolve=>server.close(resolve));globalThis.fetch=real;}
});
