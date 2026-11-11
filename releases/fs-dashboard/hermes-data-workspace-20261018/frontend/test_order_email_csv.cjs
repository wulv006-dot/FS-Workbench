const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');

// Import as ESM without changing the directory's default CommonJS semantics.
const modulePromise = import('data:text/javascript;base64,' +
  readFileSync(join(__dirname, 'order-email-csv.js')).toString('base64'));
const success = (emails = ['Customer@Example.com']) => ({
  status: 'available', complete: true, semantics: 'live_non_snapshot',
  limitation: 'live_pagination_not_snapshot', email_field: 'user_email',
  deduplication: 'trim_casefold', emails, unique_emails: emails.length,
  observed_orders: emails.length + 2, missing_email_orders: 2,
  scope: { site_id: '266', game_ids: ['26', '27'] },
  period: { start: '2026-01-01', end_exclusive: '2026-11-12' },
  observed_at: '2026-11-11T00:00:00Z',
});

test('one email column, UTF-8 BOM, CRLF and customer spelling only', async () => {
  const { orderEmailCsv } = await modulePromise;
  const payload = success(['Customer+tag@Example.com', '用户@例子.中国']);
  payload.pay_email = 'payment@example.com';
  const before = JSON.stringify(payload);
  const csv = orderEmailCsv(payload);
  assert.equal(csv, '\uFEFFemail\r\n"Customer+tag@Example.com"\r\n"用户@例子.中国"\r\n');
  assert.equal(Buffer.from(csv).subarray(0, 3).toString('hex'), 'efbbbf');
  assert.equal(JSON.stringify(payload), before);
});

test('quotes punctuation and neutralizes all source-valid formula prefixes', async () => {
  const { orderEmailCsv } = await modulePromise;
  assert.equal(orderEmailCsv(success(['a,"b"@example.com', '=x@example.com',
    '+x@example.com', '-x@example.com'])),
  '\uFEFFemail\r\n"a,""b""@example.com"\r\n"\'=x@example.com"\r\n"\'+x@example.com"\r\n"\'-x@example.com"\r\n');
  // A leading @ cannot satisfy the existing source email validator: fail closed.
  assert.throws(() => orderEmailCsv(success(['@example.com'])), TypeError);
});

test('preserves every entry and server ordering without client deduplication', async () => {
  const { orderEmailCsv } = await modulePromise;
  const emails = ['Straße@example.com', 'STRASSE@example.com', 'A@example.com',
    'a@example.com', 'A@example.com', '😀@example.com'];
  assert.equal(orderEmailCsv(success(emails)), '\uFEFFemail\r\n' +
    emails.map(email => `"${email}"\r\n`).join(''));
});

test('complete empty and all-missing exports produce only the header', async () => {
  const { orderEmailCsv } = await modulePromise;
  assert.equal(orderEmailCsv(success([])), '\uFEFFemail\r\n');
  assert.equal(orderEmailCsv({ ...success([]), observed_orders: 0,
    missing_email_orders: 0 }), '\uFEFFemail\r\n');
});

test('required success markers fail closed when missing or changed', async () => {
  const { orderEmailCsv } = await modulePromise;
  for (const field of ['complete', 'status', 'email_field', 'deduplication',
    'semantics', 'limitation']) {
    for (const value of [undefined, null, false, 'true', 'pay_email', 'snapshot']) {
      assert.throws(() => orderEmailCsv({ ...success(), [field]: value }), TypeError);
    }
    const payload = success();
    delete payload[field];
    assert.throws(() => orderEmailCsv(payload), TypeError);
  }
  for (const payload of [null, undefined, [], 'available',
    { error: 'export_budget_exceeded', complete: false },
    { ...success(), error: 'source_changed_restart_required' }]) {
    assert.throws(() => orderEmailCsv(payload), TypeError);
  }
});

test('invalid entries, sparse arrays and payment-only data never produce partial CSV', async () => {
  const { orderEmailCsv } = await modulePromise;
  for (const value of ['', null, 12, {}, 'bad', 'a@@b', 'a@', '@b',
    ' a@b', 'a@b ', 'a\tb@c', 'a\rb@c', 'a\nb@c', 'a\0b@c',
    'a\u0085b@c', 'a\u007fb@c', '\ud800@b', 'x'.repeat(319) + '@b']) {
    assert.throws(() => orderEmailCsv(success(['valid@example.com', value])), TypeError);
  }
  assert.throws(() => orderEmailCsv(success(new Array(1))), TypeError);
  assert.throws(() => orderEmailCsv({ ...success(), emails: undefined,
    pay_email: ['payment@example.com'] }), TypeError);
});

test('count mismatches and malformed scopes fail closed', async () => {
  const { orderEmailCsv } = await modulePromise;
  for (const patch of [
    { emails: 'a@b' }, { unique_emails: 0 }, { unique_emails: '1' },
    { observed_orders: -1 }, { observed_orders: 2 }, { observed_orders: NaN },
    { observed_orders: Number.MAX_SAFE_INTEGER + 1 },
    { missing_email_orders: 4 }, { missing_email_orders: 0.5 },
    { missing_email_orders: undefined }, { scope: null },
    { scope: { site_id: 266, game_ids: ['26'] } },
    { scope: { site_id: '266', game_ids: [] } },
    { scope: { site_id: '266', game_ids: ['26', '26'] } },
    { scope: { site_id: '266', game_ids: [null] } },
    { scope: { site_id: '266', game_ids: new Array(1) } },
  ]) assert.throws(() => orderEmailCsv({ ...success(), ...patch }), TypeError);
  assert.throws(() => orderEmailCsv({ ...success([]), observed_orders: 3 }), TypeError);
});
