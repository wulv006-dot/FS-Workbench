'use strict';

const assert = require('node:assert/strict');
const {test} = require('node:test');
const {handle} = require('../source/maintenance_coupon_bridge.cjs');
const {handle: readJob} = require('../source/maintenance_coupon_reconcile.cjs');
const coupon = require('../../../../opt/mmoexp-lucky-loot/coupon.cjs');
const {grantResult} = require('../../../../opt/mmoexp-lucky-loot/core.cjs');

async function submit({coupon_id, email, batch, job, overrides = {}}) {
  const originalFetch = global.fetch;
  let calls = 0;
  global.fetch = async (url, options) => {
    calls++;
    assert.equal(url, 'http://127.0.0.1:8911/admin/market.CouponGrant/import');
    assert.equal(options.method, 'POST');
    assert.equal(options.redirect, 'error');
    assert.deepEqual(JSON.parse(options.body), {
      site_id: 266, coupon_id: String(coupon_id), grant_batch_no: batch, emails: email,
    });
    const data = {
      mode: 'sync', batch_no: batch, success: 0, pending_register: 1, processed: 1, total: 1,
      rows: [{email, status: 'pending_register'}],
      ...(job === undefined ? {} : {job_id: job}), ...overrides,
    };
    return {ok: true, text: async () => JSON.stringify({code: 1, data})};
  };
  try {
    const result = await handle({action: 'grant', coupon_id, email, batch}, coupon, grantResult);
    assert.equal(calls, 1);
    return result;
  } finally {
    global.fetch = originalFetch;
  }
}

async function readReceipt({email, batch, job, overrides = {}}) {
  const originalFetch = global.fetch;
  let calls = 0;
  global.fetch = async (url, options) => {
    calls++;
    assert.equal(url, 'http://127.0.0.1:8911/admin/market.CouponGrant/jobStatus?job_id=' + job);
    assert.equal(options.method, 'GET');
    assert.equal(options.body, undefined);
    const data = {
      job_id: job, grant_batch_no: batch, status: 'done', success: 0, failed: 1,
      total: 1, processed: 1, rows: [{email}], ...overrides,
    };
    return {ok: true, text: async () => JSON.stringify({code: 1, data})};
  };
  try {
    const result = await readJob({job_id: job, email, batch}, grantResult);
    assert.equal(calls, 1);
    return result;
  } finally {
    global.fetch = originalFetch;
  }
}

if (require.main === module) {
  test('keeps the scoped native job even when classification is pending registration', async () => {
    const args = {coupon_id: 123, email: 'buyer@example.net', batch: 'FCSM_' + 'A'.repeat(32)};
    const known = await submit({...args, job: 'admin-77'});
    assert.equal(known.state, 'pending_register');
    assert.equal(known.job_id, 'admin-77');
    const noEcho = await submit({...args, job: 'admin-77', overrides: {batch_no: undefined}});
    assert.equal(noEcho.job_id, 'admin-77');
    const missing = await submit(args);
    assert.equal(missing.state, 'pending_register');
    assert.equal(missing.job_id, undefined);
    for (const overrides of [{batch_no: 'different'}, {batch_no: ''}, {rows: [{email: 'other@example.net'}]}]) {
      const foreign = await submit({...args, job: 'foreign-77', overrides});
      assert.equal(foreign.state, 'unknown');
      assert.equal(foreign.job_id, undefined);
    }
  });

  test('rejects foreign recipients even when Admin marks the grant asynchronous', async () => {
    const args = {coupon_id: 123, email: 'buyer@example.net', batch: 'FCSM_' + 'C'.repeat(32), job: 'foreign-77'};
    for (const overrides of [
      {mode: 'async', rows: [{email: 'other@example.net'}]},
      {mode: 'async', batch_no: 'FCSM_' + 'D'.repeat(32), rows: []},
    ]) {
      const foreign = await submit({...args, overrides});
      assert.equal(foreign.state, 'unknown');
      assert.equal(foreign.job_id, undefined);
    }
  });

  test('keeps a scoped job from Admin when counters cannot confirm the result', async () => {
    const args = {coupon_id: 123, email: 'buyer@example.net', batch: 'FCSM_' + 'E'.repeat(32)};
    const receipt = await submit({...args, job: 77, overrides: {processed: 0, pending_register: undefined}});
    assert.equal(receipt.state, 'unknown');
    assert.equal(receipt.job_id, '77');
    const malformed = await submit({...args, job: '../77', overrides: {mode: 'async', rows: []}});
    assert.equal(malformed.state, 'unknown');
    assert.equal(malformed.job_id, undefined);
  });

  test('an incomplete receipt cannot release quotas', async () => {
    const args = {email: 'buyer@example.net', batch: 'FCSM_' + 'F'.repeat(32), job: 'job-88'};
    for (const overrides of [
      {grant_batch_no: undefined},
      {job_id: undefined},
      {grant_batch_no: undefined, failed: 0, skipped_limit: 1},
    ]) {
      assert.equal((await readReceipt({...args, overrides})).state, 'unknown');
    }
    const rejection = {pending_register: 0, failed: 1, rows: [{email: args.email}]};
    const grant = {...args, coupon_id: 123};
    const unbound = await submit({...grant, overrides: {...rejection, batch_no: undefined}});
    assert.equal(unbound.state, 'unknown');
    assert.equal(unbound.job_id, args.job);
    const matched = await submit({...grant, overrides: {...rejection, job_id: null}});
    assert.equal(matched.state, 'rejected');
  });

  test('reconciliation uses only GET by the original job and verifies recipient', async () => {
    const batch = 'FCSM_' + 'B'.repeat(32);
    const email = 'buyer@example.net';
    const originalFetch = global.fetch;
    let requests = 0;
    global.fetch = async (url, options) => {
      requests++;
      assert.equal(url, 'http://127.0.0.1:8911/admin/market.CouponGrant/jobStatus?job_id=job-88');
      assert.equal(options.method, 'GET');
      assert.equal(options.body, undefined);
      return {ok: true, text: async () => JSON.stringify({
        code: 1, data: {job_id: 'job-88', batch_no: batch, status: 'done', success: 1,
          rows: [{email, member_coupon_id: 222}]},
      })};
    };
    try {
      const request = {job_id: 'job-88', email, batch};
      assert.equal((await readJob(request, grantResult)).member_coupon_id, '222');
      assert.equal((await readJob({...request, email: 'other@example.net'}, grantResult)).state, 'unknown');
      await assert.rejects(readJob({...request, job_id: ''}, grantResult), /invalid_reconcile_scope/);
      assert.equal(requests, 2);
    } finally {
      global.fetch = originalFetch;
    }
  });
}

module.exports = {submit, readReceipt};
