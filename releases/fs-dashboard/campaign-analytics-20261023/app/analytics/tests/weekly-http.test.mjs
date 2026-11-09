import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';

test('weekly console uses real center fixtures, FS role, origin and CSRF without publishing',async()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-http-')),originalFetch=globalThis.fetch;
 let hostMode='unavailable',hostCalls=[];
 process.env.CAMPAIGN_DATA=path.join(tmp,'private');process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(tmp,'public');process.env.CAMPAIGN_ORIGIN='http://localhost';
 globalThis.fetch=async(url,options)=>{
  if(String(url)==='http://127.0.0.1:8895/verify?group=dashboard'){
   const role=options.headers.Cookie==='admin'?'admin':options.headers.Cookie==='reader'?'reader':null;
   return new Response(null,{status:role?200:401,headers:role?{'x-auth-user':'fixture','x-auth-role':role}:{}});
  }if(String(url).startsWith('http://127.0.0.1:8931/internal/hermes/campaign-recommendations')){
   assert.equal(options.headers['X-FS-Actor'],'fixture');assert.equal(options.headers.Cookie,'admin');hostCalls.push({url:String(url),method:options.method,body:options.body});
   if(hostMode==='pending')return new Response(JSON.stringify({status:'pending',operation_id:JSON.parse(options.body).operation_id}),{status:202});
   if(hostMode==='completed'){const operation_id=new URL(url).searchParams.get('operation_id');return new Response(JSON.stringify({status:'completed',result:{model:'gpt-6.1-sol',source_revision:'0',sbc_update_id:'sbc-async-test',recommendations:[]},receipt:{operation_id,task_id:'task1',run_id:'run1',model:'gpt-6.1-sol'}}));}
   return new Response(JSON.stringify({operation_id:JSON.parse(options.body).operation_id,status:'unavailable',error:'WEEKLY_HERMES_PROVIDER_UNAVAILABLE',provider_outcome:'not_dispatched'}));
  }return originalFetch(url,options);
 };
 let server;
 try{
  ({server}=await import('../production-server.mjs'));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const root='http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/',url=root+'api/weekly';
  assert.equal((await originalFetch(url)).status,401);
  const reader=await (await originalFetch(url,{headers:{Cookie:'reader'}})).json();assert.equal(reader.canEdit,false);assert.equal(reader.csrf,null);assert.equal(reader.pages.length,3);assert(reader.pages.every(p=>p.products.length>0));
  const admin=await (await originalFetch(url,{headers:{Cookie:'admin'}})).json(),headers={Cookie:'admin','Content-Type':'application/json',Origin:'http://localhost','X-CSRF-Token':admin.csrf};
  const body={revision:0,operation_id:randomUUID(),action:'create',id:'2026-W46',page_id:'fc27-sbc'},post=extra=>originalFetch(url,{method:'POST',headers:{...headers,...extra},body:JSON.stringify(body)});
  assert.equal((await post({Cookie:'reader'})).status,403);assert.equal((await post({Origin:'https://invalid.test'})).status,403);assert.equal((await post({'X-CSRF-Token':'bad'})).status,403);
  let response=await post({});assert.equal(response.status,200);const saved=await response.json();assert.equal(saved.weeks.length,1);assert.equal(saved.weeks[0].checks_scope,'current_center');assert(saved.weeks[0].check_snapshot.checks.length>0);
  assert.equal((await (await post({})).json()).revision,1);
  const existing=await (await originalFetch(root+'api/center',{headers:{Cookie:'reader'}})).json();assert.equal(existing.revision,0);assert.equal(existing.published,null);assert.equal(fs.existsSync(path.join(tmp,'public/current.json')),false);
  response=await originalFetch(url,{method:'POST',headers,body:JSON.stringify({revision:1,operation_id:randomUUID(),action:'publish'})});assert.equal(response.status,400);
  const update={id:'sbc-test-update',observed_at:new Date().toISOString(),context:'Test only',sources:[{url:'https://www.ea.com/games/ea-sports-fc',title:'Test source',observed_at:new Date().toISOString()}]};
  const legacyBody={revision:0,operation_id:randomUUID(),sbc_update:update};
  response=await originalFetch(url+'/recommend',{method:'POST',headers,body:JSON.stringify(legacyBody)});assert.equal(response.status,410);assert.match((await response.json()).message,/按当前规则取品并生成草稿/);assert.equal(hostCalls.length,0);
  assert.equal((await originalFetch(url+'/recommend',{method:'POST',headers:{...headers,Cookie:'reader'},body:'{}'})).status,403);
  const historyDir=path.join(tmp,'private/center/weekly-recommendations');fs.mkdirSync(historyDir,{recursive:true});
  const {canonical,digest}=await import('../../runtime/snapshot.mjs');
  const record={operation_id:legacyBody.operation_id,submitted_by:'fixture',sbc_update:update,prepared:{model:'gpt-6.1-sol',dedupe_key:'history',input:{source_revision:'0',sbc_update:{...update,id:'sbc-async-test'},catalog:[],pages:[]}},result:{status:'pending',source_revision:'0',candidates:[]}};
  fs.writeFileSync(path.join(historyDir,'weekly-recommendations.json'),JSON.stringify({operations:[{id:legacyBody.operation_id,hash:digest(canonical(legacyBody)),request_id:legacyBody.operation_id}],requests:[record]}));
  response=await originalFetch(url+'/recommend',{method:'POST',headers,body:JSON.stringify(legacyBody)});assert.equal(response.status,200);assert.equal((await response.json()).status,'pending');assert.equal(hostCalls.length,0);
  hostMode='completed';response=await originalFetch(url+'/reconcile',{method:'POST',headers,body:JSON.stringify({operation_id:legacyBody.operation_id})});assert.equal(response.status,200);assert.equal((await response.json()).status,'completed');assert.deepEqual(hostCalls.map(call=>call.method),['GET']);
  const recommendations=await (await originalFetch(url+'/recommend',{headers:{Cookie:'reader'}})).json();assert.equal(recommendations.last.status,'completed');
  for(const name of ['weekly.html','weekly.js','weekly.css'])assert.equal((await originalFetch(root+name,{headers:{Cookie:'reader'}})).status,200);
 }finally{if(server)await new Promise(resolve=>server.close(resolve));globalThis.fetch=originalFetch;fs.rmSync(tmp,{recursive:true,force:true});}
});
