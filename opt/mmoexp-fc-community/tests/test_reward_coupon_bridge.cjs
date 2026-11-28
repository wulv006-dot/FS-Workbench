'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'reward_coupon_bridge.cjs'), 'utf8');

async function runBridge(request) {
  const calls = [];
  let output = '';
  const process = {stdout: {write: value => { output += value; }}, exitCode: 0};
  const coupon = {
    grant: async (...args) => { calls.push(['grant', ...args]); return {state: 'confirmed'}; },
    reconcile: async args => { calls.push(['reconcile', args]); return {state: 'confirmed'}; },
  };
  vm.runInNewContext(source, {
    require: name => name === 'node:fs'
      ? {readFileSync: () => JSON.stringify(request)}
      : name === '../mmoexp-lucky-loot/coupon.cjs' ? coupon : null,
    process,
  });
  await new Promise(resolve => setImmediate(resolve));
  return {result: JSON.parse(output), calls, exitCode: process.exitCode};
}

test('grant accepts both the existing points claim and weekly prize batch formats', async () => {
  for (const prefix of ['FC27R_', 'FC27W_']) {
    const batch = prefix + 'A'.repeat(32);
    const response = await runBridge({action: 'grant', coupon_id: 2001,
      email: 'PLAYER@example.com', batch_no: batch});
    assert.equal(response.result.ok, true);
    assert.deepEqual(response.calls, [['grant', 2001, 'player@example.com', batch]]);
  }
});

test('weekly prize batch can reconcile its original grant job', async () => {
  const batch = 'FC27W_' + 'B'.repeat(32);
  const response = await runBridge({action: 'reconcile', job_id: 'job-7',
    email: 'PLAYER@example.com', batch_no: batch});
  assert.equal(response.result.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(response.calls)), [['reconcile',
    {job_id: 'job-7', email: 'player@example.com', batch}]]);
});

test('malformed batch cannot call the coupon adapter', async () => {
  for (const batch_no of ['FC27X_' + 'A'.repeat(32), 'FC27W_short',
    'FC27W_' + 'g'.repeat(32)]) {
    const response = await runBridge({action: 'grant', coupon_id: 2001,
      email: 'player@example.com', batch_no});
    assert.equal(response.result.ok, false);
    assert.equal(response.exitCode, 1);
    assert.deepEqual(response.calls, []);
  }
});
