'use strict';

const BATCH = /^FCSM_[A-F0-9]{32}$/;
const ID = /^[1-9][0-9]*$/;
const JOB = /^[A-Za-z0-9_.:-]{1,128}$/;
const EMAIL = /^[^\s@,;，；<>]+@[^\s@,;，；<>]+\.[^\s@,;，；<>]+$/;

function accepts(value, pattern) {
  return typeof value === 'string' && pattern.test(value) && !/[\r\n]/.test(value);
}

async function grant(couponId, email, batch, grantResult) {
  const response = await fetch('http://127.0.0.1:8911/admin/market.CouponGrant/import', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({site_id: 266, coupon_id: couponId, grant_batch_no: batch, emails: email}),
    signal: AbortSignal.timeout(95000), redirect: 'error',
  });
  if (!response.ok) throw Error('coupon_grant_http_failed');
  const raw = await response.text();
  if (raw.length >= 2000000) throw Error('coupon_grant_response_budget');
  const {code, data} = JSON.parse(raw);
  if (code !== 1) throw Error('coupon_grant_response_unconfirmed');

  if (!data || typeof data !== 'object' || Array.isArray(data)) return {state: 'unknown'};
  for (const field of ['batch_no', 'grant_batch_no']) {
    if (Object.hasOwn(data, field) && data[field] !== batch) {
      return {state: 'unknown', error_code: 'coupon_grant_batch_mismatch'};
    }
  }
  if (Object.hasOwn(data, 'rows') && (!Array.isArray(data.rows) || data.rows.length > 1
      || data.rows.some(row => typeof row?.email !== 'string' || row.email.toLowerCase() !== email))) {
    return {state: 'unknown', error_code: 'coupon_grant_recipient_mismatch'};
  }
  const value = data.job_id;
  const job = Number.isSafeInteger(value) && value > 0 ? String(value) : value;
  if (value != null && !accepts(job, JOB)) {
    return {state: 'unknown', error_code: 'coupon_grant_invalid_job'};
  }

  // Admin may omit echoes for an asynchronous receipt. The scoped single-recipient POST
  // binds the job in that case. Keep it even when the result counters are inconclusive.
  const result = grantResult(data, email, batch);
  if (job && ['pending', 'pending_register', 'unknown'].includes(result.state)) {
    return {...result, job_id: job};
  }
  return result;
}

async function handle(request, coupon, grantResult) {
  if (!request || typeof request !== 'object') throw Error('invalid_request');
  const {action, coupon_id: couponId, batch, email} = request;
  const id = typeof couponId === 'string' || Number.isSafeInteger(couponId) ? String(couponId) : '';
  if (action === 'detail' && accepts(id, ID)) return coupon.detail(id);
  if (!accepts(batch, BATCH) || !accepts(email, EMAIL) || email.length > 254
      || email !== email.trim().toLowerCase()) throw Error('invalid_batch_or_email');
  if (action === 'grant' && accepts(id, ID)) return grant(id, email, batch, grantResult);
  throw Error('invalid_action');
}

async function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 4096) throw Error('invalid_request_size');
  }
  const coupon = require('/opt/mmoexp-lucky-loot/coupon.cjs');
  const {grantResult} = require('/opt/mmoexp-lucky-loot/core.cjs');
  const result = await handle(JSON.parse(input), coupon, grantResult);
  process.stdout.write(JSON.stringify(result));
}

if (require.main === module) main().catch(() => {
  process.stdout.write(JSON.stringify({state: 'unknown', error_code: 'coupon_bridge_failed'}));
  process.exitCode = 1;
});

module.exports = {handle};