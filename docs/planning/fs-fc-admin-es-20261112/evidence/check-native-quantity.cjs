'use strict';
// Offline evidence. Parse pinned bytes and execute only named arithmetic and the custom-band excerpt.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {parse} = require('internal/deps/acorn/acorn/dist/acorn');

const root = path.resolve(__dirname, '../../../..');
const scriptPath = process.argv[2] || path.join(root, '.agent_runtime/native-quantity-20261113.js');
const bytes = fs.readFileSync(scriptPath);
assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),
  '77a707f72b3debdf880529fe76d85276f1902a8e0ede4ed0beff37ddb141e618');
const source = bytes.toString('utf8');
const ast = parse(source, {ecmaVersion: 'latest'});
const names = ['getGoldGift', 'fc27ParsePriceText', 'fc27NormalizePrice',
  'fc27PresentmentFromUsd', 'fc27ApplyPctOff'];
const functions = ast.body.filter(node => node.type === 'FunctionDeclaration' && names.includes(node.id.name));
assert.equal(functions.length, names.length);
const excerpts = functions.map(node => source.slice(node.start, node.end));
const start = source.indexOf('let e=0,r=0;for(let i in o)');
const end = source.indexOf('let s=Number(o[e].discount)', start);
assert.ok(start >= 0 && end > start);
const band = source.slice(start, end);
assert.equal(band,
  'let e=0,r=0;for(let i in o){if(r=100*o[i].price/(i*o[i].discount),r=r>0?r.toFixed(8):0,parseInt(i)>parseInt(t))break;e=i}if(e>0){r=r>i?r:i;');

const sandbox = vm.createContext(Object.create(null), {codeGeneration: {strings: false, wasm: false}});
const run = text => vm.runInContext(text, sandbox, {timeout: 1000});
run(excerpts.join('\n') + '\nfunction custom(o,t,i){' + band +
  'return {lower:e,derived:r,base:r*t,tiered:r*t*(.01*Number(o[e].discount)),gift:getGoldGift(o,t)}}return null}');

const synthetic = {
  10: {price: 100, discount: 100, give: 2},
  100: {price: 200, discount: 80, give: 0},
  1000: {price: 12500, discount: 50, give: 30},
};
sandbox.bands = synthetic;
assert.equal(run('getGoldGift(bands, 100)'), 2);
assert.equal(run('getGoldGift(bands, 1000)'), 30);
assert.equal(run('custom(bands, 9, 8)'), null);
assert.equal(run('custom(bands, 99, 8).lower'), '10');
assert.equal(run('custom(bands, 99, 8).derived'), 8);
assert.equal(run('custom(bands, 101, 8).lower'), '100');
assert.equal(run('custom(bands, 101, 8).derived'), '25.00000000');
assert.equal(run("custom(bands, 101, '8').derived"), '8');
assert.equal(run('custom(bands, 101, 8).tiered'), 2020);
assert.equal(run('custom(bands, 100000, 8).tiered'), 1250000);
assert.equal(run('fc27PresentmentFromUsd(1.005, 1.5)'), '1.52');
assert.equal(run("fc27ApplyPctOff('1.52', 7.5).final"), '1.41');
assert.equal(run("fc27ApplyPctOff('1.52', 100)"), null);

const historical = JSON.parse(fs.readFileSync(path.join(root,
  'releases/fc-coins/fc-pricing-v3-20261026/tests/fixtures/d8-lowest-anchor.json'), 'utf8'));
const observed = historical.evidence.region_rules[0].public_rule_trace.offers.PS;
assert.equal(observed.selection_context.code, 'ar');
assert.equal(observed.selection_context.currency, 'USD');
assert.match(observed.checked_at, /^2026-10-28T/);
sandbox.oldTiers = Object.fromEntries(observed.tiers.map(row => [row.num, row]));
assert.equal(run('oldTiers[80].discount'), 100);
assert.equal(run('oldTiers[80].full_price_format'), '5.73');
assert.equal(run('fc27NormalizePrice(oldTiers[80].price_discount_format)'), '5.72');
assert.equal(run('oldTiers[200].give'), 0);
assert.equal(run('getGoldGift(oldTiers, 200)'), 5);
console.log('PASS: pinned source, 13 synthetic and 8 historical fixture assertions; display logic only');

if (process.argv[3]) {
  const directory = process.argv[3];
  const capture = JSON.parse(fs.readFileSync(path.join(__dirname, 'f0-native-quantity-ps-usd-20261113.json')));
  const receipt = JSON.parse(fs.readFileSync(path.join(directory, 'receipt.json')));
  assert.equal(receipt.status, capture.capture_status);
  assert.equal(receipt.error, capture.capture_error);
  const originals = {};
  for (const [index, item] of capture.requests.entries()) {
    const original = fs.readFileSync(path.join(directory, item.file));
    assert.equal(original.length, item.bytes);
    assert.equal(crypto.createHash('sha256').update(original).digest('hex'), item.sha256);
    assert.equal(receipt.requests[index].final_url, item.url);
    assert.equal(receipt.requests[index].http_status, item.status);
    originals[item.file] = original.toString('utf8');
  }
  assert.equal(originals['quantity-script.js'], source);
  checkCapturedBlur(originals, capture);
}

function checkCapturedBlur(originals, capture) {
  const markup = originals['landing.html'];
  const inlines = Array.from(markup.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi), match => match[1]);
  const inline = inlines.find(script => /\bvar\s+plConfig\s*=/.test(script));
  assert.ok(inline?.includes('getMount(plConfig)'));
  const config = parse(inline, {ecmaVersion: 'latest'}).body
    .flatMap(node => node.declarations || []).find(node => node.id.name === 'plConfig').init;
  function property(key) {
    const node = config.properties.find(item => (item.key.name ?? item.key.value) === key).value;
    return JSON.parse(inline.slice(node.start, node.end));
  }
  const pageGoods = property('goods').index.list;
  const currency = property('common').currency.current;
  assert.deepEqual({code: currency.code, rate: currency.rate, sign: currency.sign}, capture.page.currency);
  const ajax = JSON.parse(originals['goods.json']);
  assert.deepEqual(Object.keys(ajax), capture.ajax.root_keys);
  assert.deepEqual(Object.keys(ajax.common), capture.ajax.common_keys);
  assert.equal(ajax.goods.index.coupon_display[0].currency, capture.ajax.coupon_display_currency);
  assert.equal(pageGoods.length, 1);
  assert.equal(ajax.goods.index.list.length, 1);
  const [row] = pageGoods;
  const [responseRow] = ajax.goods.index.list;
  for (const [key, value] of Object.entries(capture.product.identity)) {
    assert.equal(row[key], value);
    assert.equal(responseRow[key], value);
  }
  assert.equal(row.unit_price, capture.product.unit_price);
  assert.equal(row.unit_price, responseRow.unit_price);
  assert.equal(row._region_factor, capture.product.region_factor);
  assert.equal(row._region_factor, responseRow._region_factor);
  assert.equal(JSON.stringify(row.goods_list), JSON.stringify(responseRow.goods_list));
  assert.deepEqual(Object.keys(row.goods_list), capture.product.tier_keys);

  const blur = ast.body.filter(node => node.type === 'ExpressionStatement')
    .flatMap(node => node.expression.expressions || [node.expression])
    .find(node => source.startsWith('$("#inputNum").on("blur",', node.start));
  assert.ok(blur);
  const blurNames = new Set([...names, ...[
    'fc27GetStaticPromo', 'fc27GetStaticClaimCode', 'fc27SyncBuyDiscountCode',
    'escapeGoldHtml', 'getDiscountOff', 'formatDiscountOff', 'getDiscountOffByRow',
    'formatDiscountOffByRow', 'getCouponDiscountOffByRow', 'formatCouponDiscountOffByRow',
    'getDiscountCodeOffByRow', 'formatDiscountCodeOffByRow', 'fc27UpdateDiscountRows',
    'fc27GetPromoOff', 'fc27IsClaimed', 'fc27SetPlainBuyPrice', 'fc27WriteTierBuyPrice', 'numRegular',
  ]]);
  const definitions = ast.body.filter(node => node.type === 'FunctionDeclaration' && blurNames.has(node.id.name))
    .map(node => source.slice(node.start, node.end));
  assert.equal(definitions.length, blurNames.size);

  function replay(value) {
    const input = {value};
    const output = {};
    const promo = {
      fields: {'data-off': capture.page.initial_static_promo_off, 'data-code': 'present'},
      getAttribute(key) {return this.fields[key] ?? null;},
      setAttribute(key, next) {this.fields[key] = next;},
      querySelector() {return null;},
    };
    const buy = {setAttribute() {}, removeAttribute() {}};
    const document = {
      getElementById(key) {return key === 'inputNum' ? input : key === 'buy_price' ? buy : null;},
      querySelector(selector) {return selector === '.fc27-page .fc27-order-promo' ? promo : null;},
      querySelectorAll() {return [];},
    };
    function $(selector) {
      return {
        length: selector === '.fc27-page' ? 1 : 0,
        attr(key) {return key === 'data-min' ? capture.page.input_data_min : this;},
        val(...args) {
          if (!args.length) return String(input.value);
          input.value = String(args[0]);
          return this;
        },
        text(next) {output[selector] = String(next); return this;},
        css() {return this;}, prop() {return this;}, not() {return this;}, each() {return this;},
        on(event, handler) {
          assert.equal(event, 'blur');
          handler.call(input);
          return this;
        },
      };
    }
    const context = vm.createContext({tableData: pageGoods, listRate: currency.rate, document, $, fc27StaticPromo: null},
      {codeGeneration: {strings: false, wasm: false}});
    vm.runInContext([...definitions, source.slice(blur.start, blur.end)].join('\n'), context, {timeout: 1000});
    return [value, String(input.value), output['#s_price'], buy.textContent,
      Number(output['#give,.give']), Number(promo.fields['data-off'])];
  }
  assert.deepEqual(capture.replay.samples.map(([value]) => replay(value)), capture.replay.samples);
  console.log('PASS: capture hashes and status, page USD initialization, exact AJAX catalogue equality, 16 native blur samples');
}
