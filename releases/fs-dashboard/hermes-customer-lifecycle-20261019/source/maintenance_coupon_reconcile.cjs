'use strict';

const BATCH = /^FCSM_[A-F0-9]{32}$/;
const JOB = /^[A-Za-z0-9_.:-]{1,128}$/;
const EMAIL = /^[^\s@,;，；<>]+@[^\s@,;，；<>]+\.[^\s@,;，；<>]+$/;

async function receiptData(response) {
  if (!response.ok) throw Error('coupon_receipt_http_failed');
  const raw = await response.text();
  if (raw.length >= 2000000) throw Error('coupon_receipt_response_budget');
  const {code, data} = JSON.parse(raw);
  if (code !== 1) throw Error('coupon_receipt_response_unconfirmed');
  return data;
}

function classifyReceipt(data, email, batch, grantResult, originalJob) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return {state: 'unknown'};
  const conflicts = [];
  let batchMatched = false;
  let job;
  function checkIdentity(row, prefix) {
    for (const field of ['batch_no', 'grant_batch_no']) {
      if (!Object.hasOwn(row, field)) continue;
      if (row[field] === batch) batchMatched = true;
      else conflicts.push(prefix + field);
    }
    if (Object.hasOwn(row, 'email') &&
        (typeof row.email !== 'string' || row.email.toLowerCase() !== email)) {
      conflicts.push(prefix + 'email');
    }
    if (Object.hasOwn(row, 'job_id') && (row.job_id !== null || originalJob)) {
      const value = row.job_id;
      const id = Number.isSafeInteger(value) && value > 0 ? String(value) : value;
      if (typeof id !== 'string' || !JOB.test(id) || /[\r\n]/.test(id)
          || (originalJob && id !== originalJob) || (job && id !== job)) {
        conflicts.push(prefix + 'job_id');
      } else {
        job = id;
      }
    }
  }

  checkIdentity(data, '');
  if (Object.hasOwn(data, 'rows')) {
    if (!Array.isArray(data.rows) || data.rows.length > 1
        || data.rows.some(row => !row || typeof row !== 'object' || Array.isArray(row))) {
      conflicts.push('rows');
    } else if (data.rows.length) {
      if (!Object.hasOwn(data.rows[0], 'email')) conflicts.push('rows.email');
      checkIdentity(data.rows[0], 'rows.');
    }
  }
  if (conflicts.length) return {state: 'unknown', identity_conflicts: conflicts};

  let result = grantResult(data, email, batch, originalJob);
  if (['rejected', 'limit'].includes(result.state) && (!batchMatched || (originalJob && !job))) {
    result = {state: 'unknown', error_code: 'coupon_receipt_identity_incomplete'};
  }
  // When Admin omits echoes on an async import, its response to the scoped POST binds the job.
  if (job && ['pending', 'pending_register', 'unknown'].includes(result.state)) {
    return {...result, job_id: job};
  }
  return result;
}

async function handle({job_id, email, batch}, grantResult) {
  if (typeof job_id !== 'string' || !JOB.test(job_id) || /[\r\n]/.test(job_id)
      || typeof batch !== 'string' || !BATCH.test(batch) || /[\r\n]/.test(batch)
      || typeof email !== 'string' || !EMAIL.test(email) || email.length > 254
      || email !== email.trim().toLowerCase()) throw Error('invalid_reconcile_scope');
  const response = await fetch('http://127.0.0.1:8911/admin/market.CouponGrant/jobStatus?job_id=' +
    encodeURIComponent(job_id), {
    method: 'GET', headers: {'Content-Type': 'application/json'},
    signal: AbortSignal.timeout(95000), redirect: 'error',
  });
  return classifyReceipt(await receiptData(response), email, batch, grantResult, job_id);
}

async function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 4096) throw Error('invalid_request_size');
  }
  const {grantResult} = require('/opt/mmoexp-lucky-loot/core.cjs');
  const receipt = await handle(JSON.parse(input), grantResult);
  process.stdout.write(JSON.stringify(receipt));
}

if (require.main === module) main().catch(() => {
  process.stdout.write(JSON.stringify({state: 'unknown', error_code: 'coupon_reconcile_failed'}));
  process.exitCode = 1;
});

module.exports = {handle, classifyReceipt, receiptData};
