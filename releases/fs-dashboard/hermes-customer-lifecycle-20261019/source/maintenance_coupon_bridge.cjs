'use strict';

const {classifyReceipt, receiptData} = require('./maintenance_coupon_reconcile.cjs');

const BATCH = /^FCSM_[A-F0-9]{32}$/;
const ID = /^[1-9][0-9]*$/;
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
  return classifyReceipt(await receiptData(response), email, batch, grantResult);
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