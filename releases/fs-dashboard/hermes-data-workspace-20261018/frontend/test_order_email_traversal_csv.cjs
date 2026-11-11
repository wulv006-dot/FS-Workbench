const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const load = name => import('data:text/javascript;base64,' + readFileSync(join(__dirname, name)).toString('base64'));
const modules = Promise.all([load('order-email-run.js'), load('order-email-csv.js')]);

async function exhausted(emails = ['Customer@Example.com', '=x@example.com', null]) {
  const [{ OrderEmailRun }] = await modules;
  const run = new OrderEmailRun({ site_id: '266', game_ids: ['26'], start: '2026-01-01', end_exclusive: '2026-01-02' });
  const request = run.nextRequest();
  run.acceptPage({ status: 'partial', complete: false, semantics: 'live_non_snapshot',
    limitation: 'live_pagination_not_snapshot', timezone: 'Asia/Shanghai', date_field: 'paytime',
    email_field: 'user_email', deduplication: 'trim_casefold', observed_at: '2026-11-11T00:00:00Z',
    scope: { site_id: request.site_id, game_id: request.game_id },
    period: { start: request.start, end_exclusive: request.end_exclusive },
    source_reported_total: emails.length, observed_page_rows: emails.length, next_cursor: null,
    data: emails.map((email, i) => ({ order_id: String(i), email, email_key: email })) });
  return run.result();
}

test('real exhausted coordinator serializes without rewriting complete or data', async () => {
  const [, { orderEmailCsv, orderEmailTraversalCsv }] = await modules;
  const result = await exhausted(); const before = JSON.stringify(result);
  assert.equal(orderEmailTraversalCsv(result), '\uFEFFemail\r\n"Customer@Example.com"\r\n"\'=x@example.com"\r\n');
  assert.throws(() => orderEmailCsv(result), TypeError);
  assert.equal(JSON.stringify(result), before); assert.equal(result.complete, false);
  assert.equal(orderEmailTraversalCsv(await exhausted([])), '\uFEFFemail\r\n');
  assert.equal(orderEmailTraversalCsv(await exhausted([null])), '\uFEFFemail\r\n');
});

test('all traversal, window and accepted-page completion markers required', async () => {
  const [, { orderEmailTraversalCsv: csv }] = await modules; const result = await exhausted();
  for (const field of ['state', 'complete', 'traversal_exhausted', 'total_windows', 'exhausted_windows',
    'accepted_pages', 'source_reported_total', 'timezone', 'date_field']) {
    const missing = { ...result }; delete missing[field]; assert.throws(() => csv(missing), TypeError);
  }
  for (const patch of [{ state: 'active' }, { state: 'invalid' }, { complete: true },
    { traversal_exhausted: false }, { total_windows: 0, exhausted_windows: 0 },
    { total_windows: -1, exhausted_windows: -1 }, { total_windows: 1.5, exhausted_windows: 1.5 },
    { total_windows: 2 }, { accepted_pages: 0 }, { accepted_pages: 1.5 },
    { accepted_pages: '1' }, { total_windows: 2, exhausted_windows: 2, accepted_pages: 1 },
    { source_reported_total: 4 }, { source_reported_total: '3' }, { timezone: 'UTC' },
    { date_field: 'created_at' }]) assert.throws(() => csv({ ...result, ...patch }), TypeError);
  for (const bad of [null, [], undefined]) assert.throws(() => csv(bad), TypeError);
});

test('shared original schema counts and address checks remain fail closed', async () => {
  const [, { orderEmailTraversalCsv: csv }] = await modules; const result = await exhausted();
  for (const patch of [{ semantics: 'snapshot' }, { limitation: 'snapshot' },
    { email_field: 'pay_email' }, { deduplication: 'lowercase' }, { error: 'private' },
    { unique_emails: 9 }, { missing_email_orders: -1 }, { observed_orders: 1 },
    { scope: { site_id: '266', game_ids: [] } }, { scope: { site_id: '266', game_ids: ['26', '26'] } },
    { emails: ['bad', 'ok@example.com'] }, { emails: ['a\nb@example.com', 'ok@example.com'] },
    { emails: new Array(2) }]) assert.throws(() => csv({ ...result, ...patch }), TypeError);
});
