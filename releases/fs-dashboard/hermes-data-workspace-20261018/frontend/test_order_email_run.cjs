const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const modulePromise = import('data:text/javascript;base64,' +
  readFileSync(join(__dirname, 'order-email-run.js')).toString('base64'));
const input = () => ({ site_id: '266', game_ids: ['26'], start: '2024-02-01', end_exclusive: '2024-02-09' });
const shortInput = () => ({ ...input(), end_exclusive: '2024-02-02' });
const row = (order_id, email = 'First@example.com', email_key = 'first@example.com') => ({ order_id, email, email_key });
function page(request, data = [], total = data.length, next_cursor = null) {
  return { status: 'partial', complete: false, semantics: 'live_non_snapshot',
    limitation: 'live_pagination_not_snapshot',
    scope: { site_id: request.site_id, game_id: request.game_id },
    period: { start: request.start, end_exclusive: request.end_exclusive },
    timezone: 'Asia/Shanghai', date_field: 'paytime', email_field: 'user_email',
    deduplication: 'trim_casefold', observed_at: '2026-11-11T00:00:00Z',
    source_reported_total: total, observed_page_rows: data.length, data, next_cursor };
}

test('per-game servers expand locally without global leakage and preserve export metadata', async () => {
  const { OrderEmailRun, buildOrderEmailRequests } = await modulePromise;
  const selected = { ...input(), game_ids:['26','27','28'], filters:{country:'US'}, server_ids:{'26':'261','27':'271'} };
  const requests = buildOrderEmailRequests(selected);
  assert.deepEqual(requests.map(r => r.filters), [{country:'US',aid:'261'},{country:'US',aid:'261'},
    {country:'US',aid:'271'},{country:'US',aid:'271'},{country:'US'},{country:'US'}]);
  assert.ok(requests.every(r => !('server_ids' in r)));
  const run = new OrderEmailRun(selected); selected.server_ids['26'] = '999';
  let req = run.nextRequest();
  run.acceptPage({...page(req,[row('a')],2,'cursor'), filters:req.filters});
  req = run.nextRequest(); assert.equal(req.cursor,'cursor'); assert.equal(req.filters.aid,'261');
  run.acceptPage({...page(req,[row('b')],2),filters:req.filters});
  while (run.snapshot().state === 'active') {
    req = run.nextRequest(); assert.equal(req.cursor,undefined);
    run.acceptPage({...page(req),filters:req.filters});
  }
  const result = run.result();
  const load = name => import('data:text/javascript;base64,' + readFileSync(join(__dirname,name)).toString('base64'));
  const csvModule = await load('order-email-csv.js');
  assert.ok(csvModule.orderEmailTraversalCsv(result).includes('First@example.com'));
  const csvUrl = 'data:text/javascript;base64,' + readFileSync(join(__dirname,'order-email-csv.js')).toString('base64');
  const xlsxModule = await import('data:text/javascript;base64,' + Buffer.from(readFileSync(join(__dirname,'order-email-xlsx.js'),'utf8')
    .replace("'./order-email-csv.js'",JSON.stringify(csvUrl))).toString('base64'));
  assert.ok(xlsxModule.orderEmailTraversalXlsx(result).byteLength > 0);
  assert.deepEqual(result.filters,{country:'US'}); assert.deepEqual(result.server_ids,{'26':'261','27':'271'});
  result.server_ids['26']='changed'; assert.equal(run.result().server_ids['26'],'261');
  for (const server_ids of [null,[],{'99':'1'},{'26':''},{'26':1},{'26':'１'},{'26':'1'.repeat(21)}])
    assert.throws(() => buildOrderEmailRequests({...shortInput(),server_ids}),TypeError);
  assert.throws(() => buildOrderEmailRequests({...shortInput(),filters:{aid:'1'},server_ids:{}}),TypeError);
  assert.equal(buildOrderEmailRequests({...shortInput(),server_ids:{}})[0].filters,undefined);
  const invalid = new OrderEmailRun({...shortInput(),server_ids:{'26':'261'}});
  req = invalid.nextRequest();
  assert.throws(() => invalid.acceptPage({...page(req),filters:{aid:'271'}}),TypeError);
  const unfiltered = new OrderEmailRun(shortInput()); req = unfiltered.nextRequest();
  assert.throws(() => unfiltered.acceptPage({...page(req),filters:{aid:'261'}}),TypeError);
});

test('ordinary filter strings, including literal escape text, are preserved', async () => {
  const { buildOrderEmailRequests } = await modulePromise;
  for (const key of ['country', 'discount_code']) {
    for (const value of ['US', 'ExactCode', 'save10', 'u', 'f', '\\u0000', '中国']) {
      const filters = { [key]: value };
      for (const request of buildOrderEmailRequests({ ...input(), filters })) {
        assert.deepEqual(request.filters, filters);
      }
    }
  }
});

test('filter strings reject actual NUL, newline and DEL characters', async () => {
  const { buildOrderEmailRequests } = await modulePromise;
  for (const key of ['country', 'discount_code']) {
    for (const control of ['\u0000', '\n', '\u007f']) {
      assert.throws(() => buildOrderEmailRequests({ ...shortInput(),
        filters: { [key]: 'x' + control + 'z' } }), TypeError);
    }
  }
});

test('filters bind every traversal page and altered response filters erase PII', async () => {
  const { OrderEmailRun } = await modulePromise;
  const filters = {progress:'1',status:'2',country:'US',discount_code:'ExactCode'};
  const run = new OrderEmailRun({...input(), filters});
  filters.progress = 'changed';
  while (run.snapshot().state === 'active') {
    const request = run.nextRequest(); assert.equal(request.filters.progress, '1');
    const response = {...page(request), filters: {...request.filters}};
    request.filters.progress = 'mutated';
    run.acceptPage(response);
  }
  assert.equal(run.result().filters.progress, '1');
  const invalid = new OrderEmailRun({...shortInput(), filters:{progress:'1'}});
  const request = invalid.nextRequest();
  assert.throws(() => invalid.acceptPage({...page(request),filters:{progress:'2'}}), TypeError);
  assert.equal(invalid.snapshot().state, 'invalid');
  assert.equal(invalid.snapshot().unique_emails, 0);
});

test('strict dates, leap day and game-major windows cover exactly 366 days', async () => {
  const { buildOrderEmailRequests } = await modulePromise;
  const annual = { ...input(), game_ids: ['26', '27'], start: '2024-01-01', end_exclusive: '2025-01-01' };
  const requests = buildOrderEmailRequests(annual);
  assert.equal(requests.length, 106);
  for (const game of annual.game_ids) {
    const windows = requests.filter(r => r.game_id === game);
    assert.equal(windows[0].start, annual.start);
    assert.equal(windows.at(-1).end_exclusive, annual.end_exclusive);
    let days = 0;
    windows.forEach((w, i) => {
      const length = (Date.parse(w.end_exclusive) - Date.parse(w.start)) / 86400000;
      assert.ok(length > 0 && length <= 7);
      if (i) assert.equal(w.start, windows[i - 1].end_exclusive);
      days += length;
    });
    assert.equal(days, 366);
  }
  assert.deepEqual(buildOrderEmailRequests({ ...input(), end_exclusive: '2024-03-01' }).map(r => [r.start, r.end_exclusive]),
    [['2024-02-01', '2024-02-08'], ['2024-02-08', '2024-02-15'], ['2024-02-15', '2024-02-22'],
      ['2024-02-22', '2024-02-29'], ['2024-02-29', '2024-03-01']]);
  assert.equal(buildOrderEmailRequests({ ...shortInput(), start: '0099-01-01', end_exclusive: '0099-01-02' }).length, 1);
});

test('invalid annual inputs are rejected without coercion or ignored filters', async () => {
  const { OrderEmailRun } = await modulePromise;
  const invalid = [null, [], {}, { ...input(), extra: true }, { ...input(), filters: { unknown: '1' } },
    ...[266, '', ' 266', '266 ', '2.1', '-1', '1e2', '１', '1'.repeat(21)].map(site_id => ({ ...input(), site_id })),
    ...[[], Array(1), ['26', '26'], [26], [''], Array(101).fill('26'), '26'].map(game_ids => ({ ...input(), game_ids })),
    ...['2023-02-29', '2024-02-30', '2024-13-01', '2024-2-01', ' 2024-02-01',
      '2024-02-01T00:00:00Z', '0000-01-01', 20240201].map(start => ({ ...input(), start })),
    { ...input(), end_exclusive: input().start }, { ...input(), end_exclusive: '2024-01-31' },
    { ...input(), start: '2024-01-01', end_exclusive: '2025-01-02' }];
  for (const value of invalid) assert.throws(() => new OrderEmailRun(value), TypeError);
});

test('cross-game/window traversal uses Python casefold keys and first spelling', async () => {
  const { OrderEmailRun } = await modulePromise;
  const original = { ...input(), game_ids: ['26', '27'] };
  const run = new OrderEmailRun(original);
  original.game_ids.push('99');
  const values = [row('1', 'Straße@example.com', 'strasse@example.com'),
    row('2', 'STRASSE@example.com', 'strasse@example.com'), row('3', null, null),
    row('4', 'Other@example.com', 'other@example.com')];
  values.forEach((value, i) => {
    assert.throws(() => run.result(), TypeError);
    const request = run.nextRequest();
    assert.equal('cursor' in request, false);
    const progress = run.acceptPage(page(request, [value]));
    assert.equal(progress.complete, false);
    assert.equal(progress.traversal_exhausted, i === 3);
    assert.equal('emails' in progress, false);
    assert.equal('cursor' in progress, false);
  });
  assert.equal(run.nextRequest(), null);
  const result = run.result();
  assert.equal(result.traversal_exhausted, true);
  assert.equal(result.complete, false);
  assert.equal(result.semantics, 'live_non_snapshot');
  assert.equal(result.observed_orders, 4);
  assert.equal(result.source_reported_total, 4);
  assert.equal(result.missing_email_orders, 1);
  assert.equal(result.unique_emails, 2);
  assert.deepEqual(result.emails, ['Straße@example.com', 'Other@example.com']);
  assert.deepEqual(result.scope, { site_id: '266', game_ids: ['26', '27'] });
  assert.deepEqual(result.period, { start: input().start, end_exclusive: input().end_exclusive });
  result.emails.length = 0; result.scope.game_ids.length = 0; result.period.start = 'changed';
  assert.equal(run.result().emails.length, 2);
  assert.equal(run.result().scope.game_ids.length, 2);
  assert.equal(run.result().period.start, input().start);
  assert.deepEqual(Object.keys(run), []);
});

test('network pause retries identical pending page, defensive request copies, 20-row boundary', async () => {
  const { OrderEmailRun } = await modulePromise;
  const run = new OrderEmailRun(shortInput());
  const first = run.nextRequest();
  assert.deepEqual(run.nextRequest(), first);
  run.nextRequest().game_id = '999';
  assert.deepEqual(run.nextRequest(), first);
  run.acceptPage(page(first, Array.from({ length: 20 }, (_, i) => row(String(i))), 21, 'opaque-A'));
  const next = run.nextRequest();
  assert.equal(next.cursor, 'opaque-A');
  assert.deepEqual(run.nextRequest(), next);
  assert.throws(() => run.result(), TypeError);
  run.acceptPage(page(next, [row('last')], 21));
  assert.equal(run.result().observed_orders, 21);
  assert.equal(run.result().accepted_pages, 2);
});

test('empty totals and all-missing rows are valid, totals may differ between windows', async () => {
  const { OrderEmailRun } = await modulePromise;
  const run = new OrderEmailRun(input());
  run.acceptPage(page(run.nextRequest()));
  assert.throws(() => run.result(), TypeError);
  run.acceptPage(page(run.nextRequest(), [row('m1', null, null), row('m2', null, null)]));
  const result = run.result();
  assert.deepEqual(result.emails, []);
  assert.equal(result.observed_orders, 2);
  assert.equal(result.missing_email_orders, 2);
  const empty = new OrderEmailRun(shortInput());
  empty.acceptPage(page(empty.nextRequest()));
  assert.equal(empty.result().observed_orders, 0);
});

test('every malformed envelope/row invalidates with no partial page commit', async () => {
  const { OrderEmailRun } = await modulePromise;
  const mutations = [
    p => { p.status = 'available'; }, p => { p.complete = true; },
    p => { p.semantics = 'snapshot'; }, p => { p.limitation = ''; },
    p => { p.timezone = 'UTC'; }, p => { p.date_field = 'created'; },
    p => { p.email_field = 'pay_email'; }, p => { p.deduplication = 'lowercase'; },
    p => { p.observed_at = ''; }, p => { p.error = 'changed policy'; },
    p => { p.scope.site_id = '999'; }, p => { p.scope.game_id = '27'; },
    p => { p.scope.game_id = 26; }, p => { p.scope.extra = true; },
    p => { p.period.start = '2024-02-02'; }, p => { p.period.end_exclusive = '2024-02-03'; },
    p => { p.source_reported_total = 4; }, p => { p.source_reported_total = -1; },
    p => { p.source_reported_total = '3'; }, p => { p.source_reported_total = NaN; },
    p => { p.source_reported_total = Number.MAX_SAFE_INTEGER + 1; },
    p => { p.observed_page_rows = 1; }, p => { p.observed_page_rows = '2'; },
    p => { p.next_cursor = ''; }, p => { p.next_cursor = ' '; },
    p => { p.next_cursor = 2; }, p => { delete p.next_cursor; },
    p => { p.next_cursor = 'more-after-total'; },
    p => { p.data[1].order_id = 'first'; }, p => { p.data[1].order_id = 'second'; },
    p => { p.data[1].order_id = ''; }, p => { p.data[1].order_id = 3; },
    p => { p.data[1].email = null; }, p => { p.data[1].email_key = null; },
    p => { p.data[1].email = ''; }, p => { p.data[1].email_key = ''; },
    p => { p.data[1].email = 1; }, p => { p.data[1].email_key = 1; },
    p => { delete p.data[1].email; }, p => { p.data[1].payment_email = 'ignored@example.com'; },
  ];
  for (const mutate of mutations) {
    const run = new OrderEmailRun(shortInput());
    run.acceptPage(page(run.nextRequest(), [row('first')], 3, 'a'));
    const before = run.snapshot();
    const payload = page(run.nextRequest(), [row('second', 'New@example.com', 'new@example.com'), row('third')], 3);
    mutate(payload);
    assert.throws(() => run.acceptPage(payload), TypeError);
    assert.deepEqual(run.snapshot(), { ...before, state: 'invalid' });
    assert.throws(() => run.result(), TypeError);
    assert.throws(() => run.nextRequest(), TypeError);
  }
});

test('missing required fields, nonobjects and invalid page sizes fail closed', async () => {
  const { OrderEmailRun } = await modulePromise;
  const valid = page({ site_id: '266', game_id: '26', start: '2024-02-01', end_exclusive: '2024-02-02' });
  const malformed = [null, [], 'partial', ...Object.keys(valid).map(key => {
    const p = { ...valid }; delete p[key]; return p;
  }), { ...valid, data: {}, observed_page_rows: 0 },
  { ...valid, source_reported_total: 1 }, { ...valid, next_cursor: 'a' },
  { ...valid, data: Array.from({ length: 21 }, (_, i) => row(String(i))), observed_page_rows: 21, source_reported_total: 21 }];
  for (const payload of malformed) {
    const run = new OrderEmailRun(shortInput()); run.nextRequest();
    assert.throws(() => run.acceptPage(payload), TypeError);
    assert.equal(run.snapshot().observed_orders, 0);
    assert.equal(run.snapshot().state, 'invalid');
  }
});

test('cursor self-loop and longer cycles are rejected', async () => {
  const { OrderEmailRun } = await modulePromise;
  for (const cycle of ['a', 'b']) {
    const run = new OrderEmailRun(shortInput());
    run.acceptPage(page(run.nextRequest(), [row('1')], 4, 'a'));
    run.acceptPage(page(run.nextRequest(), [row('2')], 4, 'b'));
    assert.throws(() => run.acceptPage(page(run.nextRequest(), [row('3')], 4, cycle)), TypeError);
    assert.equal(run.snapshot().observed_orders, 2);
  }
});

test('empty continuation, premature end and changed totals cannot finish traversal', async () => {
  const { OrderEmailRun } = await modulePromise;
  for (const [data, total, cursor] of [
    [[], 2, null], [[], 2, 'b'], [[row('2')], 3, null], [[row('2')], 1, null],
  ]) {
    const run = new OrderEmailRun(shortInput());
    run.acceptPage(page(run.nextRequest(), [row('1')], 2, 'a'));
    assert.throws(() => run.acceptPage(page(run.nextRequest(), data, total, cursor)), TypeError);
    assert.equal(run.snapshot().observed_orders, 1);
    assert.throws(() => run.result(), TypeError);
  }
});

test('replayed/stale pages and cross-window/game duplicate order IDs invalidate', async () => {
  const { OrderEmailRun } = await modulePromise;
  const run = new OrderEmailRun(shortInput());
  const first = page(run.nextRequest(), [row('1')], 2, 'a');
  run.acceptPage(first); run.nextRequest();
  assert.throws(() => run.acceptPage(first), TypeError);
  for (const options of [input(), { ...shortInput(), game_ids: ['26', '27'] }]) {
    const duplicate = new OrderEmailRun(options);
    const previous = page(duplicate.nextRequest(), [row('same')]);
    duplicate.acceptPage(previous);
    const current = duplicate.nextRequest();
    assert.throws(() => duplicate.acceptPage(page(current, [row('same')])), TypeError);
    const stale = new OrderEmailRun(options);
    stale.acceptPage(page(stale.nextRequest(), [row('old')]));
    stale.nextRequest();
    assert.throws(() => stale.acceptPage(previous), TypeError);
  }
});

test('accept requires an issued request; late response after exhaustion invalidates', async () => {
  const { OrderEmailRun } = await modulePromise;
  const run = new OrderEmailRun(shortInput());
  assert.throws(() => run.acceptPage({}), TypeError);
  const done = new OrderEmailRun(shortInput());
  const response = page(done.nextRequest());
  done.acceptPage(response);
  assert.throws(() => done.acceptPage(response), TypeError);
  assert.throws(() => done.result(), TypeError);
});

test('clear cancels active/exhausted/invalid instances, erases PII and is idempotent', async () => {
  const { OrderEmailRun } = await modulePromise;
  for (const state of ['active', 'exhausted', 'invalid']) {
    const run = new OrderEmailRun(state === 'active' ? input() : shortInput());
    const response = page(run.nextRequest(), [row('private-id', 'Private@example.com', 'private@example.com')]);
    run.acceptPage(response);
    if (state === 'invalid') assert.throws(() => run.acceptPage(response));
    run.clear(); run.clear();
    assert.equal(run.snapshot().state, 'cleared');
    assert.equal(run.snapshot().observed_orders, 0);
    assert.equal(run.snapshot().unique_emails, 0);
    assert.equal(JSON.stringify(run).includes('Private'), false);
    assert.throws(() => run.result(), TypeError);
    assert.throws(() => run.nextRequest(), TypeError);
    assert.throws(() => run.acceptPage(response), TypeError);
    const restart = new OrderEmailRun(shortInput());
    restart.acceptPage(page(restart.nextRequest(), [row('private-id')]));
    assert.equal(restart.result().observed_orders, 1);
  }
});

test('weekly windows avoid the reproduced slow 28-day tail without gaps', async () => {
  const { buildOrderEmailRequests } = await modulePromise;
  const request = { site_id: '266', game_ids: ['1307'], start: '2026-09-26', end_exclusive: '2026-10-24', filters: { progress: '10' } };
  const pages = buildOrderEmailRequests(request);
  assert.deepEqual(pages.map(p => [p.start, p.end_exclusive]), [
    ['2026-09-26', '2026-10-03'], ['2026-10-03', '2026-10-10'],
    ['2026-10-10', '2026-10-17'], ['2026-10-17', '2026-10-24']]);
  assert.ok(pages.every(p => p.site_id === '266' && p.game_id === '1307' && p.filters.progress === '10'));
});
