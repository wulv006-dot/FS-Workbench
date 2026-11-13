'use strict';
// Offline probes of the recorded pure editor handlers, never the bundle bootstrap.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const record = JSON.parse(fs.readFileSync(path.join(__dirname, 'f0-native-editor-static.json'), 'utf8'));
assert.equal(crypto.createHash('sha256').update(record.handler_excerpt).digest('hex'), record.handler_excerpt_sha256);
function run(expression, overrides = {}) {
  const items = {unit_price: 0.1, more: {gold: [100, 200, 500], discount: [100, 95, 90], price: [10, 19, 45], give: [5, 10, 25]}, ...overrides};
  const context = {o: {form: {items}}, Q: {value: 20}, ee: {value: 100}};
  vm.runInNewContext(record.handler_excerpt + ';' + expression, context, {timeout: 1000});
  return items;
}
let items = run('o.form.items.unit_price=.2;je()');
assert.deepEqual(items.more.price, [20, 38, 90]);
assert.deepEqual(items.more.give, [5, 10, 25]);
items = run('o.form.items.more.gold[1]=300;qe(1)');
assert.deepEqual(items.more.price, [10, 28.5, 45]);
items = run('o.form.items.more.discount[1]=80;Je(1)');
assert.deepEqual(items.more.discount, [100, 80, 80]);
assert.deepEqual(items.more.price, [10, 16, 40]);
items = run('o.form.items.more.price[1]=16;Ke(1)');
assert.deepEqual(items.more.discount, [100, 80, 80]);
assert.deepEqual(items.more.price, [10, 16, 40]);
items = run('o.form.items.more.price[1]=19.004;Ke(1)');
assert.deepEqual(items.more.discount, [100, 95, 90]);
assert.equal(items.more.price[1], 19.004);
items = run('ge()');
assert.equal(items.unit_price, 0.2);
assert.deepEqual(items.more.price, [20, 38, 90]);
items = run('o.form.items.more.discount[1]=100.04;Je(1)');
assert.deepEqual(items.more.discount, [100, 100, 100]);
items = run('o.form.items.unit_price=1.005;o.form.items.more.gold[0]=1;qe(0)');
assert.equal(items.more.price[0], 1); // Native Number/toFixed, not Decimal HALF_UP.
console.log('PASS: excerpt digest and 8 synthetic native editor scenarios; no backend acceptance');
