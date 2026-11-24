'use strict';

const BATCH = /^FCSM_[A-F0-9]{32}$/;
const ID = /^[1-9][0-9]*$/;
const JOB = /^[A-Za-z0-9_.:-]{1,128}$/;
const EMAIL = /^[^\s@,;，；<>]+@[^\s@,;，；<>]+\.[^\s@,;，；<>]+$/;

function accepts(value, pattern) {
  return typeof value === 'string' && pattern.test(value) && !/[\r\n]/.test(value);
}

async function handle(request, coupon) {
  if (!request || typeof request !== 'object') throw Error('invalid_request');
  const {action, coupon_id: couponId, batch, email, job_id: job} = request;
  const id = typeof couponId === 'string' || Number.isSafeInteger(couponId) ? String(couponId) : '';
  if (action === 'detail' && accepts(id, ID)) return coupon.detail(id);
  if (!accepts(batch, BATCH) || !accepts(email, EMAIL) || email.length > 254
      || email !== email.trim().toLowerCase()) throw Error('invalid_batch_or_email');
  if (action === 'grant' && accepts(id, ID)) return coupon.grant(id, email, batch);
  if (action === 'reconcile' && accepts(job, JOB)) return coupon.reconcile({job_id: job, email, batch});
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
  const result = await handle(JSON.parse(input), coupon);
  process.stdout.write(JSON.stringify(result));
}

if (require.main === module) main().catch(() => {
  process.stdout.write(JSON.stringify({state: 'unknown', error_code: 'coupon_bridge_failed'}));
  process.exitCode = 1;
});

module.exports = {handle};