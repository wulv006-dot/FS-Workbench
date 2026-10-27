import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {backendRead} from '../analytics/backend-client.mjs';
test('management subprocess reads actual mapping and empty analysis without creating state or acquiring a session',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-bridge-')),state=path.join(root,'private-state');
 const previous=process.env.CAMPAIGN_BACKEND_STATE_DIR;process.env.CAMPAIGN_BACKEND_STATE_DIR=state;
 const python=process.env.CAMPAIGN_TEST_PYTHON||(process.platform==='win32'?'python':'python3');
 try{
  const mapping=await backendRead({action:'catalog_mapping_read',site_id:'266'},{python});
  assert(mapping.summary.reference_count>=96);assert(mapping.summary.unique_goods_count>=86);assert.equal(mapping.summary.reference_count,Object.values(mapping.mappings).length);
  assert.equal(mapping.checkout_enabled,false);assert(Object.values(mapping.mappings).every(row=>row.available===false&&row.product_ref.site_id==='266'));
  const summary=await backendRead({action:'analysis_summary',site_id:'266'},{python});
  assert.equal(summary.status,'blocked');assert.deepEqual(summary.totals,[]);assert(summary.warnings.includes('ORDER_READ_NOT_PERFORMED'));
  assert.equal(fs.existsSync(state),false);
  await assert.rejects(backendRead({action:'catalog_mapping_read',site_id:'266',path:'arbitrary.json'},{python}),/CATALOG_MAPPING_SCOPE_REQUIRED/);
 }finally{if(previous===undefined)delete process.env.CAMPAIGN_BACKEND_STATE_DIR;else process.env.CAMPAIGN_BACKEND_STATE_DIR=previous;fs.rmSync(root,{recursive:true,force:true});}
});
