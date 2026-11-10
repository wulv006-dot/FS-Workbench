import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import http from 'node:http';import {randomUUID} from 'node:crypto';

test('authenticated workflow creates linked orders and three private previews, refuses missing mappings and implicit publication',async()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'weekly-workflow-http-')),fetchOriginal=globalThis.fetch;
 process.env.CAMPAIGN_DATA=path.join(tmp,'private');process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(tmp,'public');process.env.CAMPAIGN_ORIGIN='http://localhost';
 globalThis.fetch=async(url,options)=>String(url).startsWith('http://127.0.0.1:8895/verify')?new Response(null,{status:200,headers:{'x-auth-user':options.headers.Cookie==='other'?'other':'fixture','x-auth-role':options.headers.Cookie==='reader'?'reader':'admin'}}):fetchOriginal(url,options);
 let server;
 try{
  const module=await import('../production-server.mjs');({server}=module);await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port,root=origin+'/dashboard/analytics/campaigns/analytics/';
  const initial=await(await fetchOriginal(root+'api/center',{headers:{Cookie:'admin'}})).json(),headers={Cookie:'admin',Origin:'http://localhost','Content-Type':'application/json','X-CSRF-Token':initial.csrf};
  const post=(body,extra={})=>fetchOriginal(root+'api/weekly/workflow',{method:'POST',headers:{...headers,...extra},body:JSON.stringify(body)});
  const draft=initial.draft;draft.pages.filter(p=>p.page_id.startsWith('fc27-')).forEach(p=>p.benefit_refs=[{kind:'discount',native_id:'6049'}]);
  const saved=await(await fetchOriginal(root+'api/center',{method:'POST',headers,body:JSON.stringify({revision:0,operation_id:randomUUID(),draft})})).json();assert.equal(saved.revision,1);
  const run=randomUUID(),plans=path.join(tmp,'private/center/weekly-plans');fs.mkdirSync(plans,{recursive:true});fs.writeFileSync(path.join(plans,run+'.json'),JSON.stringify({operation_id:run,owner:'fixture',created_at:'2026-11-09T10:12:00Z',draft,applied:{result:{status:'draft_saved',draft_revision:1,operation_id:run}}}));
  const url=root+'api/weekly/workflow?operation_id='+run;
  assert.equal((await fetchOriginal(url,{headers:{Cookie:'reader'}})).status,403);assert.equal((await fetchOriginal(url,{headers:{Cookie:'other'}})).status,403);
  const first=await(await fetchOriginal(url,{headers:{Cookie:'admin'}})).json();assert.equal(first.work_orders.length,3);assert.equal(first.requires_review,true);
  const body={action:'review',operation_id:randomUUID(),run_operation_id:run};assert.equal((await post(body,{'X-CSRF-Token':'bad'})).status,403);assert.equal((await post(body,{Origin:'https://other.test'})).status,403);
  const response=await post(body);assert.equal(response.status,200);const reviewed=await response.json();assert.equal(reviewed.previews.length,3);assert.equal(reviewed.work_orders.length,3);assert.equal(reviewed.can_publish,false);assert(reviewed.blockers.length);
  for(const preview of reviewed.previews){assert.equal((await fetchOriginal(origin+preview.preview_url,{headers:{Cookie:'admin'}})).status,200);assert.equal((await fetchOriginal(origin+preview.preview_url,{headers:{Cookie:'other'}})).status,404);}
  const publish={action:'publish',operation_id:randomUUID(),run_operation_id:run,revision:1,review_hash:reviewed.review_hash,confirmed:true};assert.equal((await post({...publish,confirmed:false})).status,400);assert.equal((await post(publish)).status,409);
  const restoreBody=JSON.stringify({revision:1,operation_id:randomUUID(),restore_revision:0}),beforeGate=module.weeklyWorkflow.isPublishing;
  const slowResult=new Promise((resolve,reject)=>{
   const req=http.request(root+'api/center/restore',{method:'POST',headers:{...headers,'Content-Length':Buffer.byteLength(restoreBody)}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});req.on('error',reject);req.write(restoreBody.slice(0,10));
   setTimeout(()=>{module.weeklyWorkflow.isPublishing=()=>true;req.end(restoreBody.slice(10));},25);
  });assert.equal(await slowResult,409);module.weeklyWorkflow.isPublishing=beforeGate;
  assert.equal(JSON.parse(fs.readFileSync(path.join(tmp,'private/center/state.json'))).revision,1);assert.equal(fs.existsSync(path.join(tmp,'public/current.json')),false);assert.equal(fs.existsSync(path.join(tmp,'private/backend/policy.json')),false);
 }finally{if(server)await new Promise(r=>server.close(r));globalThis.fetch=fetchOriginal;fs.rmSync(tmp,{recursive:true,force:true});}
});
