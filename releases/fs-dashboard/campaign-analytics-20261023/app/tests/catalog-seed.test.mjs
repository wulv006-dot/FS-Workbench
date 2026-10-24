import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const root=fileURLToPath(new URL('../../../../../',import.meta.url));
const moduleRoot=path.join(root,'releases/fs-dashboard/campaign-analytics-20261023');
const fixture=JSON.parse(fs.readFileSync(path.join(root,'docs/planning/activity-center-v3/handoffs/C-CATALOG-SEED-04.json'),'utf8'));

test('real seed tool extracts all original references and hashes current source bytes without money fields',()=>{
  const python=process.env.PYTHON||(process.platform==='win32'?'python':'python3');
  const output=execFileSync(python,[path.join(root,'tools/campaign_catalog_seed.py'),'--module',moduleRoot],
    {cwd:root,encoding:'utf8',timeout:15000,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  const seed=JSON.parse(output),refs=seed.references;
  assert.equal(refs.length,96);
  assert.equal(new Set(refs.map(r=>r.reference_key)).size,96);
  assert.equal(new Set(refs.map(r=>JSON.stringify([r.product_ref.site_id,r.product_ref.game_id,r.product_ref.goods_id]))).size,86);
  assert.equal(new Set(refs.map(r=>r.game_key)).size,6);
  assert.deepEqual([seed.reference_count,seed.unique_goods_count,seed.game_count],[96,86,6]);
  assert.deepEqual(refs,fixture.references);
  assert.deepEqual(Object.keys(seed.source_artifacts).sort(),['app/catalog.json','app/seasonal/campaign-data.js']);
  // Fixture provenance describes captured bytes; current checkout hashes can differ with CRLF/LF.
  for(const [name,hash] of Object.entries(seed.source_artifacts)) {
    assert.equal(hash,createHash('sha256').update(fs.readFileSync(path.join(moduleRoot,name))).digest('hex'),name);
  }
  assert.doesNotMatch(output,/price|cost|token|order|email/i);
  assert.equal(seed.authoritative,false);
  assert.equal(seed.checkout_enabled,false);
  assert.deepEqual(refs.filter(r=>r.game_key==='diablo').map(r=>r.expected_quantity),
    ['100000','300000','600000'].map(value=>({value,source_unit:'M'})));
});
