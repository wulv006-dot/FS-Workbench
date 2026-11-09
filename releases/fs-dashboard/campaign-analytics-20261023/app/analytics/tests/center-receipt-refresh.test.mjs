import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
test('completed receipts bypass hanging prices; fresh writes and auth/hash guards remain',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'receipt-http-')),originalFetch=globalThis.fetch;
 process.env.CAMPAIGN_DATA=path.join(dir,'private');process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');process.env.CAMPAIGN_ORIGIN='http://localhost';
 globalThis.fetch=async(url,options)=>String(url).startsWith('http://127.0.0.1:8895/verify')?new Response(null,{status:200,headers:{'x-auth-user':'fixture','x-auth-role':options.headers.Cookie==='admin'?'admin':'reader'}}):originalFetch(url,options);
 let server,provider,refresh,unblock;
 try{
  const mod=await import('../production-server.mjs');server=mod.server;provider=mod.adminPrices;refresh=provider.refresh;
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/api/center';
  const state=await(await originalFetch(url,{headers:{Cookie:'admin'}})).json(),headers={Cookie:'admin',Origin:'http://localhost','Content-Type':'application/json','X-CSRF-Token':state.csrf};
  const post=(endpoint,body,extra={})=>originalFetch(endpoint,{method:'POST',headers:{...headers,...extra},body:JSON.stringify(body),signal:AbortSignal.timeout(1500)});
  const save={revision:0,operation_id:randomUUID(),draft:state.draft},publish={revision:1,operation_id:randomUUID()};
  assert.equal((await post(url,save)).status,200);assert.equal((await post(url+'/publish',publish)).status,200);
  const before=fs.readFileSync(path.join(dir,'public/current.json'),'utf8');let calls=0;provider.refresh=()=>{calls++;return new Promise(r=>{unblock=r;});};
  for(const [endpoint,body,revision] of [[url,save,1],[url+'/publish',publish,2]]){const res=await post(endpoint,body);assert.equal(res.status,200);assert.equal((await res.json()).revision,revision);}
  assert.equal(calls,0);assert.equal(fs.readFileSync(path.join(dir,'public/current.json'),'utf8'),before);
  assert.equal((await post(url+'/publish',{...publish,revision:0})).status,409);assert.equal((await post(url,save,{'X-CSRF-Token':'bad'})).status,403);assert.equal((await post(url,save,{Cookie:'reader'})).status,403);assert.equal(calls,0);
  const fresh=post(url,{revision:2,operation_id:randomUUID(),draft:state.draft});for(let i=0;i<30&&!unblock;i++)await new Promise(r=>setTimeout(r,5));assert.equal(calls,1);unblock();assert.equal((await fresh).status,200);
 }finally{unblock?.();if(provider)provider.refresh=refresh;if(server)await new Promise(r=>server.close(r));globalThis.fetch=originalFetch;fs.rmSync(dir,{recursive:true,force:true});}
});
