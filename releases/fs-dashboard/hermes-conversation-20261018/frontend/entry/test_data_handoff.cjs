'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'brain.js'), 'utf8');
const begin = source.indexOf('  const dataKind=initial.get');
const end = source.indexOf('  refresh().then', begin);
assert(begin >= 0 && end > begin);
const handoff = new Function('initial', '$', 'message', 'let dataRequest=null;' + source.slice(begin, end) + ';return dataRequest;');
function query(kind, fields) {
  const initial = new URLSearchParams({data_kind: kind, data_evidence: 'ws_0123456789abcdef01234567', start: '2026-10-17', end: '2026-10-17', profile: 'D4', ...fields});
  const nodes = {};
  return handoff(initial, id => nodes[id] || (nodes[id] = {}), () => {})?.query;
}
const product = query('product_orders', {product_id: '123', model_id: '456', platform: 'PS'});
assert.equal(product.product_id, 123);
assert.equal(product.profile, 'D4');
assert(!('model_id' in product) && !('platform' in product));
const old = query('product_orders', {model_id: '456', platform: 'PS'});
assert.equal(old.model_id, 456);
assert.equal(old.platform, 'PS');
assert(!('product_id' in old));
assert(!('product_id' in query('cohort', {product_id: '123', window_days: '30'})));
console.log('PASS new product_id handoff and legacy model_id compatibility');
