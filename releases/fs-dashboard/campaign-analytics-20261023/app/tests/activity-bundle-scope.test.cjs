const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const activity = fs.readFileSync(path.join(__dirname, '..', 'activity.js'), 'utf8');

test('bundle ids are shared by the grid renderer and the price warmer', () => {
  assert.match(activity, /const bundleIdsForView=\(\)=>state\.view==='weekly'\?\(config\.weekly\.bundleIds\?\?config\.bundles\.ids\):config\.bundles\.ids;/);
  assert.match(activity, /scoped\(bundleIdsForView\(\)\)/);
  assert.match(activity, /\.\.\.keys,\.\.\.bundleIdsForView\(\)/);
  assert(!/\.\.\.keys,\.\.\.bundleIds\]/.test(activity), 'warmPrices must not use a free bundleIds variable');
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
