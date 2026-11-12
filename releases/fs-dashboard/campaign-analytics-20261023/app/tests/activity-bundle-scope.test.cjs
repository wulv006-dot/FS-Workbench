const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const activity = fs.readFileSync(path.join(__dirname, '..', 'activity.js'), 'utf8');

test('bundle grid and warmer use each page pool without leaking unbound platform variants', async () => {
  const definition=activity.match(/const bundleIdsForView=([^;]+);/);assert(definition,'shared bundle selector exists');
  assert.match(activity, /scoped\(bundleIdsForView\(\)\)/);
  assert.match(activity, /\.\.\.keys,\.\.\.bundleIdsForView\(\)/);
  assert(!/\.\.\.keys,\.\.\.bundleIds\]/.test(activity), 'warmPrices must not use a free bundleIds variable');
  const original=JSON.parse(fs.readFileSync(path.join(__dirname,'..','catalog.json'),'utf8')),
    cases=[['weekly','Weekly-Scout.html',original.bundles.ids[0],'ps'],['sbc','Sbc-Companions.html',original.bundles.ids[1],'xbox'],['trio','Player-Trio.html',original.bundles.ids[2],'pc']];
  const published={pages:cases.map(([view,path,key,platform])=>({page_id:'fc27-'+view,activity_id:'fc27-season2',path,active:true,product_keys:['fc-'+key+'-'+platform]}))};
  const {projectFcCatalog}=await import('../runtime/presentation.mjs'),config=projectFcCatalog(original,published);
  const scopedSource=activity.slice(activity.indexOf('  function scoped('),activity.indexOf('  function pageMessage('));assert(scopedSource.startsWith('  function scoped('));
  for(const [view,,key,boundPlatform] of cases)for(const platform of ['ps','xbox','pc']){
    const state={view,platform},scope={state,config,standalone:true,published,pageState:()=> 'active',product:id=>config.products[id]};
    const ids=vm.runInNewContext('('+definition[1]+')()',scope);assert.deepEqual(Array.from(ids),[key],'the page consumes its own exact projected bundle IDs');
    const visible=vm.runInNewContext(scopedSource+'\nscoped(candidate)',{...scope,candidate:[...ids,original.bundles.ids[3],'unknown-bundle']});
    assert.deepEqual(Array.from(visible),platform===boundPlatform?[key]:[],'unbound platform and other page variants never become visible');
  }
  assert.deepEqual(Array.from(vm.runInNewContext('('+definition[1]+')()',{state:{view:'sbc'},config:{...config,sbc:{...config.sbc,bundleIds:[]}}})),[],'an explicitly empty SBC pool never borrows Trio bundles');
});

test('trio output accepts independently selected Newest candidates without a fixed card series', async () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'Player-Trio.html'), 'utf8');
  const body = html.match(/<p id="hero-body"[^>]*>([^<]+)<\/p>/);
  assert(body, 'hero body exists');
  assert(!body[1].includes('config.trio.series'), 'no JS source may leak into the hero body');
  const expected = 'Compare the selected player cards, exact versions and current prices.';
  assert.equal(body[1], expected);
  const config = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'catalog.json'), 'utf8'));
  config.trio.ids.forEach((key, i) => { config.products[key].version = ['Gold', 'Team of the Week', 'UCL RTTK'][i]; });
  const {buildOutputs} = await import('../build-seo.mjs');
  // Selection is upstream: these three distinct fixture candidates carry independent versions.
  config.trio.series = 'Obsolete fixed series';
  const mixed = buildOutputs(config)['Player-Trio.html'];
  const mixedBody = mixed.match(/<p id="hero-body"[^>]*>([^<]+)<\/p>/);
  assert(mixedBody, 'cross-series hero body exists');
  assert(!mixed.includes('Obsolete fixed series'), 'legacy fixed series does not control the selected cards');
  for(const key of config.trio.ids)assert(mixed.includes('data-product="'+key+'"'), 'selected candidate remains visible');
  const invalid=structuredClone(config);invalid.products[invalid.trio.ids[0]].kind='sbc';
  assert.throws(()=>buildOutputs(invalid), /three existing player cards/);
  const duplicate=structuredClone(config);duplicate.trio.ids[1]=duplicate.trio.ids[0];
  assert.throws(()=>buildOutputs(duplicate), /three distinct cards/);
  assert.equal(mixedBody[1], expected);
  assert(!mixedBody[1].includes('config.trio.series'), 'cross-series copy contains no JS source');
});
