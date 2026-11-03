import test from 'node:test';import assert from 'node:assert/strict';
import {backendRead,backendMutate} from '../analytics/backend-client.mjs';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
test('backend actions cannot cross read/mutation boundary before any subprocess',()=>{
 for(const action of ['benefit_edit','benefit_restore','benefit_toggle','operation_reconcile','analysis_reconcile'])assert.throws(()=>backendRead({action,site_id:'266'}),/ACTION_NOT_ALLOWED/);
 for(const action of ['benefit_detail','coupon_candidates','operation_lookup','analysis_summary','create','grant','capabilities'])assert.throws(()=>backendMutate({action,site_id:'266'}),/ACTION_NOT_ALLOWED/);
 assert.throws(()=>backendMutate({action:'benefit_toggle',site_id:'0'}),/SITE_SCOPE_REQUIRED/);
 assert.throws(()=>backendMutate({action:'benefit_restore',site_id:'0',original_operation_id:'synthetic-edit'}),/SITE_SCOPE_REQUIRED/);
});
test('coupon single-page arguments reach the original read subprocess unchanged',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'coupon-page-')),bridge=path.join(dir,'echo.cjs');
 fs.writeFileSync(bridge,"let raw='';process.stdin.on('data',x=>raw+=x).on('end',()=>process.stdout.write(JSON.stringify({status:'ok',data:JSON.parse(raw)}))); ");
 try{
  const request={action:'coupon_candidates',site_id:'266',page:1,limit:1};
  assert.deepEqual(await backendRead(request,{python:process.execPath,bridge}),request);
 }finally{fs.unlinkSync(bridge);fs.rmdirSync(dir);}
});
test('catalog child timeout is explicit; ordinary backend failures are not mislabeled',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'catalog-deadline-')),bridge=path.join(dir,'slow.cjs');
 fs.writeFileSync(bridge,'process.stdin.resume();setTimeout(()=>{},10000);');
 try{
  await assert.rejects(backendRead({action:'catalog_search',site_id:'266',game_id:'1327',keyword:'synthetic'},{python:process.execPath,bridge,timeout:200}),e=>e.code==='CATALOG_SEARCH_TIMEOUT'&&e.status===504);
  await assert.rejects(backendRead({action:'product_read',site_id:'266',game_id:'1327',goods_id:'1'},{python:process.execPath,bridge,timeout:200}),e=>e.code==='BACKEND_UNAVAILABLE'&&e.status===502);
  await assert.rejects(backendRead({action:'discount_revenue',site_id:'266'},{python:process.execPath,bridge,timeout:200}),e=>e.code==='BACKEND_READ_TIMEOUT');
  fs.writeFileSync(bridge,"process.stdin.resume();process.stdout.write('x'.repeat(2100000));setTimeout(()=>{},10000);");
  await assert.rejects(backendRead({action:'discount_revenue',site_id:'266'},{python:process.execPath,bridge,timeout:3000}),e=>e.code==='BACKEND_UNAVAILABLE','Output cap failure is not a retryable timeout');
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
