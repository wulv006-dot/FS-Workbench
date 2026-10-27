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

test('trio hero renders the series name instead of a code literal', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'Player-Trio.html'), 'utf8');
  const body = html.match(/<p id="hero-body"[^>]*>([^<]+)<\/p>/);
  assert(body, 'hero body exists');
  assert(!body[1].includes('config.trio.series'), 'no JS source may leak into the hero body');
  assert(body[1].includes('Ultimate Scream'));
});
