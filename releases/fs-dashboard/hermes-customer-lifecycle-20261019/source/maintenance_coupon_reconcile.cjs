'use strict';

const BATCH = /^FCSM_[A-F0-9]{32}$/;
const JOB = /^[A-Za-z0-9_.:-]{1,128}$/;
const EMAIL = /^[^\s@,;，；<>]+@[^\s@,;，；<>]+\.[^\s@,;，；<>]+$/;

async function handle({job_id, email, batch}, reconcile) {
  if (typeof job_id !== 'string' || !JOB.test(job_id) || /[\r\n]/.test(job_id)
      || typeof batch !== 'string' || !BATCH.test(batch) || /[\r\n]/.test(batch)
      || typeof email !== 'string' || !EMAIL.test(email) || email.length > 254
      || email !== email.trim().toLowerCase()) throw Error('invalid_reconcile_scope');
  return reconcile({job_id, email, batch});
}

async function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 4096) throw Error('invalid_request_size');
  }
  const {reconcile} = require('/opt/mmoexp-lucky-loot/coupon.cjs');
  const receipt = await handle(JSON.parse(input), reconcile);
  process.stdout.write(JSON.stringify(receipt));
}

if (require.main === module) main().catch(() => {
  process.stdout.write(JSON.stringify({state: 'unknown', error_code: 'coupon_reconcile_failed'}));
  process.exitCode = 1;
});

module.exports = {handle};
