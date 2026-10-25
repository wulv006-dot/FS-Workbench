import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
test('FS authenticated persistence and secret boundary',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-http-'));process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_ORIGIN='http://127.0.0.1';
 const original=globalThis.fetch;globalThis.fetch=async(url,options)=>{if(String(url).includes(':8895/verify')){const admin=options.headers.Cookie==='fixture-admin',viewer=options.headers.Cookie==='fixture-viewer';return new Response('',{status:admin||viewer?200:401,headers:admin||viewer?{'x-auth-user':'fixture','x-auth-role':admin?'admin':'readonly'}:{}});}if(String(url).includes('posthog.com'))return new Response(JSON.stringify({results:[]}),{status:200});return original(url,options);};
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/';
 try{
  const get=(route,cookie)=>original(url+route,{headers:{Cookie:cookie||''}});assert.equal((await get('api/config')).status,401);const state=await(await get('api/config','fixture-admin')).json();
  const page=await(await get('','fixture-admin')).text();assert.doesNotMatch(page,/<option value="(?:demo|local)">|src="demo-data.js"/);assert.match(page,/<option value="live">/);assert.match(page,/<option value="test">/);
  const post=(route,body,cookie='fixture-admin',origin='http://127.0.0.1')=>original(url+route,{method:'POST',headers:{Cookie:cookie,Origin:origin,'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(body)});
  assert.equal((await post('api/config',{},'fixture-viewer')).status,403);assert.equal((await post('api/config',{},'fixture-admin','https://evil.example')).status,403);
  assert.equal((await post('api/center/backend-mutate',{action:'benefit_edit',site_id:'266'},'fixture-viewer')).status,403);
  assert.equal((await post('api/center/backend-mutate',{action:'benefit_edit',site_id:'266'},'fixture-admin','https://evil.example')).status,403);
  assert.equal((await get('api/center/backend-mutate','fixture-admin')).status,404);
  assert.equal((await post('api/center/import-product',{},'fixture-viewer')).status,403);
  assert.equal((await post('api/center/import-product',{},'fixture-admin','https://evil.example')).status,403);
  assert.equal((await get('operations.html','fixture-admin')).status,200);
  const body={revision:state.revision,operationId:randomUUID(),registry:state.registry,layout:state.layout};assert.equal((await post('api/config',body)).status,200);assert.equal((await post('api/config',{...body,operationId:randomUUID()})).status,409);
  const secret='phx_'+randomUUID().replaceAll('-','');assert.equal((await post('api/connection',{key:secret})).status,200);assert.equal(JSON.parse(fs.readFileSync(path.join(dir,'posthog-secret.json'))).key,secret);
  assert.equal((await(await get('api/connection','fixture-admin')).json()).configured,true);assert(!(await(await get('api/connection','fixture-admin')).text()).includes(secret));
  assert.equal((await get('../posthog-secret.json','fixture-admin')).status,404);assert.equal((await get('production-server.mjs','fixture-admin')).status,404);
  assert.equal((await get('api/test-event','fixture-admin')).status,404);
 }finally{await new Promise(r=>server.close(r));globalThis.fetch=original;fs.rmSync(dir,{recursive:true,force:true});}
});
