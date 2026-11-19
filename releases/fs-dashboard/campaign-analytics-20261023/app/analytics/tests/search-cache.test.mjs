import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
test('repeated searches reuse only recent same-user results; permissions, filters and failures remain separate',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-search-cache-')),log=path.join(dir,'calls'),bridge=path.join(dir,'bridge.cjs');
 fs.writeFileSync(bridge,`const fs=require('node:fs');let raw='';process.stdin.on('data',x=>raw+=x).on('end',()=>{const body=JSON.parse(raw);fs.appendFileSync(${JSON.stringify(log)},body.action+'\\n');setTimeout(()=>console.log(JSON.stringify(body.keyword==='error'?{status:'error',error:'SYNTHETIC_FAILURE'}:{status:'ok',data:{items:[],keyword:body.keyword}})),100);});`);
 Object.assign(process.env,{CAMPAIGN_DATA:path.join(dir,'private'),CAMPAIGN_PUBLIC_RELEASE_DIR:path.join(dir,'public'),CAMPAIGN_ORIGIN:'http://localhost',CAMPAIGN_PYTHON:process.execPath,CAMPAIGN_BACKEND_BRIDGE:bridge});
 const original=globalThis.fetch,now=Date.now;let tick=1700000000000;
 globalThis.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:options.headers.Cookie==='denied'?403:200,headers:{'x-auth-user':options.headers.Cookie||'none','x-auth-role':'admin'}}):original(url,options);Date.now=()=>tick;
 let server;
 try{
  ({server}=await import('../production-server.mjs'));await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const root='http://127.0.0.1:'+server.address().port+'/dashboard/analytics/campaigns/analytics/',get=async cookie=>(await original(root+'api/center',{headers:{Cookie:cookie}})).json();
  const csrf=(await get('alice')).csrf,post=(cookie,body)=>original(root+'api/center/backend-read',{method:'POST',headers:{Cookie:cookie,Origin:'http://localhost','Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
  const q={action:'model_search',site_id:'266',game_id:'1327',kind:'player',keyword:'hello',page:1,page_size:10},count=()=>fs.readFileSync(log,'utf8').trim().split('\n').length;
  let r=await post('alice',q);assert.equal(r.status,200);assert.equal((await r.json()).cached,undefined);r=await post('alice',q);assert.equal(r.status,200);assert.equal((await r.json()).cached,true);assert.equal(count(),1,'repeat uses cached successful search');
  assert.equal((await post('denied',q)).status,403);assert.equal(count(),1);
  assert.equal((await post('bob',q)).status,200);assert.equal(count(),2,'different account does not share results');
  assert.equal((await post('alice',{...q,page:2})).status,200);assert.equal(count(),3,'filters and pagination are distinct');
  tick+=16000;assert.equal((await post('alice',q)).status,200);assert.equal(count(),4,'expired results are refreshed');
  const failed={...q,keyword:'error'};assert.equal((await post('alice',failed)).status,502);assert.equal((await post('alice',failed)).status,502);assert.equal(count(),6,'failures are never cached');
  const catalog={action:'catalog_search',site_id:'266',game_id:'1327',keyword:'catalog',page:1,page_size:20};assert.equal((await post('alice',catalog)).status,200);assert.equal((await post('alice',catalog)).status,200);assert.equal(count(),7);
  const concurrent={...q,keyword:'parallel'};const pair=await Promise.all([post('alice',concurrent),post('alice',concurrent)]);assert(pair.every(x=>x.status===200));assert.equal(count(),8,'simultaneous identical queries share one read');
  const detail={action:'model_resolve',site_id:'266',game_id:'1327',kind:'player',model_id:'42'};assert.equal((await post('alice',detail)).status,200);assert.equal((await post('alice',detail)).status,200);assert.equal(count(),10,'identity details are always fresh');
 }finally{Date.now=now;globalThis.fetch=original;if(server)await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
});
