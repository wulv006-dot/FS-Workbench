const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const dataUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const serializer = dataUrl(readFileSync(join(__dirname, 'order-email-csv.js')));
const coordinator = dataUrl(readFileSync(join(__dirname, 'order-email-run.js')));
const modulePromise = import(dataUrl(readFileSync(join(__dirname, 'order-email-panel.js'), 'utf8')
  .replace("'./order-email-csv.js'", JSON.stringify(serializer))
  .replace("'./order-email-run.js'", JSON.stringify(coordinator))));
// Fixture directories only; the production module contains no directory defaults.
const sites = [{ value: '266', label: 'Fixture site' }];
const games = [{ value: '26', label: 'Fixture A' }, { value: '27', label: 'Fixture B' }];
const input = { site_id: '266', game_ids: ['26', '27'], start: '2026-01-01', end: '2026-01-08' };

class Element {
  constructor(tag, doc) {
    this.tag = tag; this.ownerDocument = doc; this.children = []; this.listeners = new Map();
    this.attributes = {}; this.value = ''; this.textContent = ''; this.disabled = false;
  }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, fn) { this.listeners.set(name, fn); }
  removeEventListener(name, fn) { if (this.listeners.get(name) === fn) this.listeners.delete(name); }
  fire(name) { return this.listeners.get(name)?.({ preventDefault() {} }); }
  click() { if (this.tag === 'a') this.ownerDocument.downloads.push({ href: this.href, name: this.download }); return this.fire('click'); }
  get selectedOptions() { return this.children.filter(node => node.selected); }
}
const walk = node => [node, ...node.children.flatMap(walk)];
const text = node => walk(node).map(item => item.textContent).join(' ');
async function setup(endpoint = '/test-only-page') {
  const { mountOrderEmailExport } = await modulePromise;
  const requests = [], blobs = new Map(), revoked = [];
  let nextUrl = 0;
  const doc = { downloads: [], createElement(tag) { return new Element(tag, this); }, defaultView: {
    location: { href: 'https://fixture.invalid/tools', origin: 'https://fixture.invalid' },
    AbortController, Blob, URL: {
      createObjectURL(blob) { const url = 'blob:fixture-' + ++nextUrl; blobs.set(url, blob); return url; },
      revokeObjectURL(url) { revoked.push(url); blobs.delete(url); },
    },
  } };
  const root = new Element('root', doc);
  const widget = mountOrderEmailExport(root, { endpoint, sites, games, paged: true,
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })) });
  const nodes = walk(root), form = nodes.find(node => node.tag === 'form');
  const fields = Object.fromEntries(nodes.filter(node => node.name).map(node => [node.name, node]));
  fields.site_id.value = input.site_id; fields.start.value = input.start; fields.end.value = '2026-01-01';
  fields.game_ids.children.forEach(node => { node.selected = node.value === '26'; });
  const buttons = nodes.filter(node => node.tag === 'button');
  const respond = (index, payload, ok = true) => requests[index].resolve({ ok, status: 206, json: async () => payload });
  return { root, doc, widget, requests, blobs, revoked, form, fields, buttons, respond };
}

const tick = () => new Promise(resolve => setImmediate(resolve));
async function requested(h, count) {
  for (let i = 0; i < 30 && h.requests.length < count; i++) await tick();
  assert.equal(h.requests.length, count);
  return h.requests[count - 1];
}
function page(request, offset = 0, size = 1, total = size, cursor = null) {
  const r = JSON.parse(request.options.body);
  return { status: 'partial', complete: false, semantics: 'live_non_snapshot',
    limitation: 'live_pagination_not_snapshot', timezone: 'Asia/Shanghai', date_field: 'paytime',
    email_field: 'user_email', deduplication: 'trim_casefold', observed_at: '2026-11-11T00:00:00Z',
    scope: { site_id: r.site_id, game_id: r.game_id },
    period: { start: r.start, end_exclusive: r.end_exclusive },
    source_reported_total: total, observed_page_rows: size, next_cursor: cursor,
    data: Array.from({ length: size }, (_, i) => ({ order_id: String(offset + i),
      email: `Customer${offset + i}@example.com`, email_key: `customer${offset + i}@example.com` })) };
}

test('20 plus last page and all game/date windows required before CSV', async () => {
  const h = await setup(); h.fields.end.value = '2026-01-08';
  h.fields.game_ids.children.forEach(n => { n.selected = true; });
  const pending = h.form.fire('submit');
  const first = await requested(h, 1);
  h.respond(0, page(first, 0, 20, 21, 'opaque-next'));
  const last = await requested(h, 2);
  assert.equal(JSON.parse(last.options.body).cursor, 'opaque-next');
  h.buttons[2].click(); assert.equal(h.doc.downloads.length, 0);
  h.respond(1, page(last, 20, 1, 21));
  for (let i = 2; i < 5; i++) {
    const r = await requested(h, i + 1);
    assert.equal(h.buttons[2].disabled, true);
    h.respond(i, page(r, 20 + i));
  }
  await pending;
  assert.equal(h.buttons[2].disabled, false);
  assert.match(text(h.root), /5 页.*4\/4/);
  assert.match(text(h.root), /进程重启后游标失效/);
  assert.doesNotMatch(text(h.root), /Customer/);
  h.buttons[2].click();
  const bytes = Buffer.from(await [...h.blobs.values()][0].arrayBuffer()).toString('utf8');
  assert.match(bytes, /Customer20@example.com/);
  h.form.fire('change'); assert.equal(h.blobs.size, 0);
  assert.equal(h.buttons[2].disabled, true); h.widget.dispose();
});

for (const stage of ['fetch', 'json']) test(`pause during ${stage}, resume same cursor, ignore stale JSON`, async () => {
  const h = await setup(); const initial = h.form.fire('submit');
  const first = await requested(h, 1);
  h.respond(0, page(first, 0, 20, 21, 'same-cursor'));
  const old = await requested(h, 2); let resolveJson;
  if (stage === 'json') {
    old.resolve({ ok: true, status: 206, json: () => new Promise(resolve => { resolveJson = resolve; }) });
    await tick();
  }
  h.buttons[3].click(); assert.equal(old.options.signal.aborted, true);
  const resumed = h.buttons[4].click(); const replacement = await requested(h, 3);
  assert.equal(replacement.options.body, old.options.body);
  h.respond(2, page(replacement, 20, 1, 21)); await resumed;
  if (stage === 'json') resolveJson({ error: 'private@example.com' });
  else h.respond(1, { error: 'private@example.com' });
  await initial;
  assert.equal(h.buttons[2].disabled, false);
  assert.match(text(h.root), /2 页/); assert.doesNotMatch(text(h.root), /private@/);
  h.widget.dispose();
});

test('network failure retries the uncommitted cursor manually', async () => {
  const h = await setup(); const initial = h.form.fire('submit');
  const first = await requested(h, 1);
  h.respond(0, page(first, 0, 20, 21, 'retry-cursor'));
  const failed = await requested(h, 2); failed.reject(new Error('private@example.com'));
  await initial; assert.equal(h.buttons[2].disabled, true);
  const resumed = h.buttons[4].click(); const r = await requested(h, 3);
  assert.equal(r.options.body, failed.options.body);
  h.respond(2, page(r, 20, 1, 21)); await resumed;
  assert.equal(h.buttons[2].disabled, false); h.widget.dispose();
});

for (const [code, header, delay] of [[429, '120', 120000], [503, null, 60000],
  [429, new Date(1800000060000).toUTCString(), 60000]]) {
  test(`${code} Retry-After ${header} blocks manual retry until deadline`, async () => {
    const original = Date.now; let now = 1800000000000; Date.now = () => now;
    try {
      const h = await setup(); const pending = h.form.fire('submit');
      const first = await requested(h, 1);
      first.resolve({ ok: false, status: code, headers: { get: () => header } }); await pending;
      await h.buttons[4].click(); assert.equal(h.requests.length, 1);
      await h.form.fire('submit'); assert.equal(h.requests.length, 1);
      now += delay - 1; await h.buttons[4].click(); assert.equal(h.requests.length, 1);
      now++; const retry = h.buttons[4].click(); const r = await requested(h, 2);
      assert.equal(r.options.body, first.options.body);
      h.respond(1, page(r)); await retry; assert.equal(h.buttons[2].disabled, false);
      h.widget.dispose();
    } finally { Date.now = original; }
  });
}

for (const failure of [401, 403, 409, 422, 'scope', 'period', 'json', 'shape', 'address', 'source-schema']) {
  test(`invalidates and erases on ${failure}, cannot resume or export`, async () => {
    const h = await setup(); const pending = h.form.fire('submit');
    const first = await requested(h, 1);
    h.respond(0, page(first, 0, 20, 21, 'cursor'));
    const r = await requested(h, 2); const p = page(r, 20, 1, 21);
    if (typeof failure === 'number') r.resolve({ ok: false, status: failure });
    else if (failure === 'source-schema') r.resolve({ ok: false, status: 503, json: async () => ({ error: 'source_schema_changed' }) });
    else if (failure === 'json') r.resolve({ ok: true, status: 206, json: async () => { throw new Error('private@example.com'); } });
    else {
      if (failure === 'scope') p.scope.site_id = '999';
      if (failure === 'period') p.period.start = '2026-01-02';
      if (failure === 'shape') p.data = null;
      if (failure === 'address') p.data[0].email = 'malformed';
      h.respond(1, p);
    }
    await pending; await h.buttons[4].click(); h.buttons[2].click();
    assert.equal(h.requests.length, 2); assert.equal(h.doc.downloads.length, 0);
    assert.equal(h.buttons[2].disabled, true); assert.equal(h.buttons[4].disabled, true);
    assert.match(text(h.root), /名单已清除/); assert.doesNotMatch(text(h.root), /private@/);
    h.widget.dispose();
  });
}

for (const action of ['input', 'change', 'cancel', 'dispose']) {
  test(`${action} clears paused state and ignores late JSON`, async () => {
    const h = await setup(); const pending = h.form.fire('submit');
    const r = await requested(h, 1); let resolveJson;
    r.resolve({ ok: true, status: 206, json: () => new Promise(resolve => { resolveJson = resolve; }) });
    await tick(); h.buttons[3].click();
    if (action === 'dispose') h.widget.dispose();
    else if (action === 'cancel') h.buttons[1].click();
    else h.form.fire(action);
    resolveJson(page(r)); await pending; await h.buttons[4].click();
    assert.equal(h.requests.length, 1); assert.equal(h.buttons[2].disabled, true);
    assert.equal(h.blobs.size, 0); h.widget.dispose();
  });
}

test('cancel and dispose revoke finished CSV blobs', async () => {
  for (const action of ['cancel', 'dispose']) {
    const h = await setup(); const pending = h.form.fire('submit');
    const r = await requested(h, 1); h.respond(0, page(r)); await pending;
    h.buttons[2].click(); assert.equal(h.blobs.size, 1);
    if (action === 'cancel') h.buttons[1].click(); else h.widget.dispose();
    assert.equal(h.blobs.size, 0); assert.equal(h.revoked.length, 1); h.widget.dispose();
  }
});


test('source_timeout retains accepted windows and retries only the pending page', async () => {
  const original = Date.now; let now = 1800000000000; Date.now = () => now;
  const h = await setup();
  try {
    h.fields.end.value = '2026-01-08';
    h.fields.game_ids.children.forEach(n => { n.selected = true; });
    const initial = h.form.fire('submit');
    const first = await requested(h, 1); h.respond(0, page(first, 1));
    const next = await requested(h, 2); h.respond(1, page(next, 2, 20, 21, 'timeout-cursor'));
    const failed = await requested(h, 3);
    failed.resolve({ ok: false, status: 503, headers: { get: () => null },
      json: async () => ({ complete: false, error: 'source_timeout' }) });
    await initial;
    assert.equal(h.buttons[4].disabled, false);
    assert.equal(h.buttons[2].disabled, true);
    assert.match(text(h.root), /2 页.*1\/4/);
    assert.match(text(h.root), /本页读取超时/);
    assert.doesNotMatch(text(h.root), /名单已清除/);
    await h.buttons[4].click(); assert.equal(h.requests.length, 3);
    now += 60000;
    const resumed = h.buttons[4].click();
    const retry = await requested(h, 4);
    assert.equal(retry.options.body, failed.options.body);
    h.respond(3, page(retry, 22, 1, 21));
    for (let i = 4; i < 6; i++) {
      const r = await requested(h, i + 1); h.respond(i, page(r, 19 + i));
    }
    await resumed;
    assert.equal(h.buttons[2].disabled, false);
    assert.match(text(h.root), /5 页.*4\/4/);
    h.buttons[2].click();
    const csv = Buffer.from(await [...h.blobs.values()][0].arrayBuffer()).toString('utf8');
    assert.match(csv, /Customer1@example.com/);
    assert.match(csv, /Customer22@example.com/);
    assert.equal(csv.split('\r\n').length - 2, 24);
  } finally { h.widget.dispose(); Date.now = original; }
});
