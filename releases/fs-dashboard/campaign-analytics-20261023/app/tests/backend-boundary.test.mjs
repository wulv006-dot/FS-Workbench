import test from 'node:test';import assert from 'node:assert/strict';
import {backendRead,backendMutate} from '../analytics/backend-client.mjs';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
test('backend actions cannot cross read/mutation boundary before any subprocess',()=>{
 for(const action of ['benefit_edit','benefit_restore','benefit_toggle','operation_reconcile','analysis_reconcile'])assert.throws(()=>backendRead({action,site_id:'266'}),/ACTION_NOT_ALLOWED/);
 for(const action of ['benefit_detail','operation_lookup','analysis_summary','create','grant','capabilities'])assert.throws(()=>backendMutate({action,site_id:'266'}),/ACTION_NOT_ALLOWED/);
 assert.throws(()=>backendMutate({action:'benefit_toggle',site_id:'0'}),/SITE_SCOPE_REQUIRED/);
 assert.throws(()=>backendMutate({action:'benefit_restore',site_id:'0',original_operation_id:'synthetic-edit'}),/SITE_SCOPE_REQUIRED/);
});
test('catalog child timeout is explicit; ordinary backend failures are not mislabeled',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'catalog-deadline-')),bridge=path.join(dir,'slow.cjs');
 fs.writeFileSync(bridge,'process.stdin.resume();setTimeout(()=>{},10000);');
 try{
  await assert.rejects(backendRead({action:'catalog_search',site_id:'266',game_id:'1327',keyword:'synthetic'},{python:process.execPath,bridge,timeout:200}),e=>e.code==='CATALOG_SEARCH_TIMEOUT'&&e.status===504);
  await assert.rejects(backendRead({action:'product_read',site_id:'266',game_id:'1327',goods_id:'1'},{python:process.execPath,bridge,timeout:200}),e=>e.code==='BACKEND_UNAVAILABLE'&&e.status===502);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
