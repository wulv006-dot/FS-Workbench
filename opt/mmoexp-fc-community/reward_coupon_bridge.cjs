'use strict';

// One-request CLI bridge to the existing 187 HMAC coupon adapter. No credentials
// or player email are written to argv, stdout logs, or Discord.
const fs = require('node:fs');
const coupon = require('../mmoexp-lucky-loot/coupon.cjs');

function validId(value) {
  if (!Number.isSafeInteger(value) || value <= 0) throw Error('invalid_coupon_id');
  return value;
}
function validEmail(value) {
  if (typeof value !== 'string' || value.length > 254 ||
      !/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(value)) throw Error('invalid_email');
  return value.trim().toLowerCase();
}
function validBatch(value) {
  if (typeof value !== 'string' || !/^FC27R_[A-F0-9]{32}$/.test(value))
    throw Error('invalid_batch');
  return value;
}
function validJob(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9:_-]{1,128}$/.test(value))
    throw Error('invalid_job');
  return value;
}

async function main() {
  const raw = fs.readFileSync(0, 'utf8');
  if (raw.length > 4096) throw Error('oversized_request');
  const request = JSON.parse(raw);
  let result;
  if (request.action === 'detail') {
    result = coupon.validate(await coupon.detail(validId(request.coupon_id)));
  } else if (request.action === 'grant') {
    result = await coupon.grant(validId(request.coupon_id),
      validEmail(request.email), validBatch(request.batch_no));
  } else if (request.action === 'reconcile') {
    result = await coupon.reconcile({job_id:validJob(request.job_id),
      email:validEmail(request.email),batch:validBatch(request.batch_no)});
  } else {
    throw Error('invalid_action');
  }
  process.stdout.write(JSON.stringify({ok:true,result}) + '\n');
}

main().catch(() => {
  process.stdout.write('{"ok":false,"error":"coupon_adapter_unavailable"}\n');
  process.exitCode = 1;
});
