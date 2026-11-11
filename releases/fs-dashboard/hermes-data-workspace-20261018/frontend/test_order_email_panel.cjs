const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const dataUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const serializer = dataUrl(readFileSync(join(__dirname, 'order-email-csv.js')));
const modulePromise = import(dataUrl(readFileSync(join(__dirname, 'order-email-panel.js'), 'utf8')
  .replace("'./order-email-csv.js'", JSON.stringify(serializer))));
// Fixture directories only; the production module contains no directory defaults.
const sites = [{ value: '266', label: 'Fixture site' }];
const games = [{ value: '26', label: 'Fixture A' }, { value: '27', label: 'Fixture B' }];
const input = { site_id: '266', game_ids: ['26', '27'], start: '2026-01-01', end: '2026-01-31' };
const success = () => ({ status: 'available', complete: true, semantics: 'live_non_snapshot',
  limitation: 'live_pagination_not_snapshot', email_field: 'user_email', deduplication: 'trim_casefold',
  emails: ['Customer@Example.com'], unique_emails: 1, observed_orders: 2, missing_email_orders: 1,
  scope: { site_id: '266', game_ids: ['26', '27'] },
  period: { start: '2026-01-01', end_exclusive: '2026-02-01' } });

class Element {
  constructor(tag, doc) {
    this.tag = tag; this.ownerDocument = doc; this.children = []; this.listeners = new Map();
    this.attributes = {}; this.value = ''; this.textContent = ''; this.disabled = false;
    this.selected = this.checked = this.hidden = this.open = false;
  }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); }
  setAttribute(key, value) { this.attributes[key] = value; }
  focus() { this.ownerDocument.activeElement = this; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, fn) { this.listeners.set(name, fn); }
  removeEventListener(name, fn) { if (this.listeners.get(name) === fn) this.listeners.delete(name); }
  fire(name, target = this) {
    const event = { target, preventDefault() {} };
    let result;
    for (let node = this; node; node = node.parent) {
      const listener = node.listeners.get(name);
      if (listener) result = listener(event);
    }
    return result;
  }
  click() {
    if (this.disabled) return;
    if (this.tag === 'a') this.ownerDocument.downloads.push({ href: this.href, name: this.download });
    if (this.tag === 'summary') this.parent.open = !this.parent.open;
    if (this.tag === 'input' && this.type === 'checkbox') {
      this.checked = !this.checked; this.fire('input'); return this.fire('change');
    }
    return this.fire('click');
  }
  get selectedOptions() { return this.children.filter(node => node.selected); }
}
const walk = node => [node, ...node.children.flatMap(walk)];
const text = node => walk(node).map(item => item.textContent).join(' ');
async function setup(endpoint = '/test-only-export', remote = false) {
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
  const widget = mountOrderEmailExport(root, { endpoint, ...(remote ? {} : { sites, games }),
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })) });
  const nodes = walk(root), form = nodes.find(node => node.tag === 'form');
  const fields = Object.fromEntries(nodes.filter(node => node.name).map(node => [node.name, node]));
  fields.site_id.value = input.site_id; fields.start.value = input.start; fields.end.value = input.end;
  fields.game_ids.children.forEach(node => { node.selected = true; });
  const buttons = nodes.filter(node => node.tag === 'button');
  const respond = (index, payload = success(), ok = true) => requests[index].resolve({ ok, json: async () => payload });
  return { root, doc, widget, requests, blobs, revoked, form, fields, buttons, respond };
}

// Shared fixture extraction boundary: test('all 14 Admin
 test('available Admin filters serialize and filter changes revoke downloaded data', async () => {
  const h = await setup();
  const names = ['progress','status','cid','content','aid','recommend_uid','discount_code','promotion_id','pid','country'];
  for (const name of [...names, 'site_id', 'game_ids', 'start', 'end']) assert.ok(h.fields[name]);
  const unavailable = ['progress', 'status', 'cid', 'aid'];
  const filters = Object.fromEntries(names.filter(name => !unavailable.includes(name)).map(name => [name, name === 'content' ? 'game / server' : '1']));
  for (const name of names) h.fields[name].value = filters[name] || 'stale';
  for (const name of unavailable) {
    assert.equal(h.fields[name].disabled, true);
    assert.equal(h.fields[name].children.length, 1);
    h.fields[name].disabled = false; // Even DOM tampering must not add unavailable conditions.
  }
  assert.equal(h.fields.admin_id, undefined);
  const pending = h.form.fire('submit');
  assert.deepEqual(JSON.parse(h.requests[0].options.body).filters, filters);
  h.respond(0, { ...success(), filters }); await pending;
  h.buttons[2].click(); assert.equal(h.blobs.size, 1);
  h.fields.discount_code.value = 'another'; h.form.fire('change', h.fields.discount_code);
  assert.equal(h.blobs.size, 0); assert.equal(h.buttons[2].disabled, true);
  h.fields.status.value = '2'; h.fields.aid.value = '3';
  h.form.fire('change', h.fields.game_ids);
  assert.equal(h.fields.status.value, '2'); assert.equal(h.fields.aid.value, '3');
  h.widget.dispose();
});

const metadata = () => ({options: {sites, games, progress:[], status:[], cid:[], aid:[],
  country:[{value:'US',label:'美国'}]}});
const tick = () => new Promise(resolve => setImmediate(resolve));
test('authenticated metadata loads actual three directories only; unavailable filters stay gray and omitted', async () => {
  for (const legacyChoices of [false, true]) {
    const h = await setup('/test-only-export', true);
    assert.deepEqual(JSON.parse(h.requests[0].options.body), {kind:'order_email_export_options'});
    assert.equal(h.requests[0].options.credentials, 'same-origin');
    const data = metadata();
    if (legacyChoices) for (const name of ['progress','status','cid','aid'])
      data.options[name] = [{value:'99',label:'Legacy choice'}];
    h.respond(0, data); await tick();
    assert.equal(h.fields.country.children[1].value, 'US');
    for (const name of ['progress','status','cid','aid']) {
      assert.equal(h.fields[name].disabled, true);
      assert.equal(h.fields[name].value, '');
      assert.equal(h.fields[name].children.length, 1);
      h.fields[name].value = 'stale';
      await h.form.fire('change', h.fields[name]);
    }
    h.fields.site_id.value = '266'; h.fields.game_ids.children[0].selected = true;
    await h.form.fire('change', h.fields.game_ids);
    assert.equal(h.requests.length, 1);
    assert.match(text(h.root), /查询不传这四项条件，使用 Admin API 源默认范围/);
    assert.doesNotMatch(text(h.root), /默认为已支付|均为已支付|默认为已完成/);
    h.fields.country.value = 'US';
    const pending = h.form.fire('submit');
    assert.deepEqual(JSON.parse(h.requests[1].options.body).filters, {country:'US'});
    h.respond(1, {...success(), filters:{country:'US'}, scope:{site_id:'266',game_ids:['26']}}); await pending;
    assert.equal(h.buttons[2].disabled, false);
    h.widget.dispose();
  }
});

test('native id-prefixed game labels are not prefixed twice', async () => {
  const h = await setup('/test-only-export', true);
  h.respond(0, {options:{...metadata().options,games:[{value:'1327',label:'1327 | FC 27'}]}}); await tick();
  const checkbox = walk(h.root).find(node => node.type === 'checkbox');
  assert.equal(text(checkbox.parent).trim(), '1327 | FC 27');
  h.widget.dispose();
});
test('metadata failures stay closed and disposed responses cannot revive controls', async () => {
  const broken = await setup('/test-only-export', true);
  broken.respond(0, {options:{...metadata().options, country:[]}}); await tick();
  assert.equal(broken.buttons[0].disabled, true);
  await broken.form.fire('submit'); assert.equal(broken.requests.length, 1); broken.widget.dispose();
  const h = await setup('/test-only-export', true);
  h.widget.dispose();
  h.respond(0, metadata()); await tick();
  assert.equal(h.root.children.length, 0);
  for (const name of ['progress','status','cid','aid']) assert.equal(h.fields[name].disabled, true);
});

test('clickable game dropdown searches by name/ID and preserves multi-selection across searches', async () => {
  const h = await setup();
  h.fields.game_ids.children.forEach(option => { option.selected = false; });
  h.form.fire('change', h.fields.game_ids);
  const nodes = walk(h.root), picker = nodes.find(node => node.tag === 'details');
  const summary = picker.children[0], search = nodes.find(node => node.type === 'search');
  const checks = nodes.filter(node => node.type === 'checkbox');
  assert.equal(h.fields.game_ids.hidden, true); assert.equal(h.fields.game_ids.required, undefined);
  for (const name of ['site_id', 'progress', 'status', 'cid', 'aid', 'country']) {
    assert.match(h.fields[name].attributes.style, /width:100%/);
    assert.match(h.fields[name].parent.attributes.style, /flex:1 1 200px/);
  }
  assert.match(picker.parent.attributes.style, /flex:1 1 320px/);
  summary.click(); assert.equal(picker.open, true);
  let prevented = false;
  search.listeners.get('keydown')({key:'Enter',preventDefault() { prevented = true; }});
  assert.equal(prevented, true); assert.equal(h.requests.length, 0);
  search.listeners.get('keydown')({key:'Escape'});
  assert.equal(picker.open, false); assert.equal(h.doc.activeElement, summary);
  summary.click(); assert.equal(picker.open, true);
  search.value = 'fIXture b'; search.fire('input');
  assert.equal(checks[0].parent.hidden, true); assert.equal(checks[1].parent.hidden, false);
  checks[1].click();
  assert.deepEqual(h.fields.game_ids.selectedOptions.map(option => option.value), ['27']);
  assert.match(summary.textContent, /已选 1 款/); assert.match(text(picker.parent), /Fixture B/);
  search.value = '26'; search.fire('input'); checks[0].click();
  assert.deepEqual(h.fields.game_ids.selectedOptions.map(option => option.value), ['26', '27']);
  assert.match(summary.textContent, /已选 2 款/);
  search.value = 'not-present'; search.fire('input');
  assert.ok(checks.every(check => check.parent.hidden)); assert.match(text(picker), /没有匹配的游戏/);
  search.value = ''; search.fire('input');
  assert.ok(checks.every(check => !check.parent.hidden && check.checked));
  summary.click(); assert.equal(picker.open, false);
  const pending = h.form.fire('submit');
  assert.deepEqual(JSON.parse(h.requests[0].options.body).game_ids, ['26','27']);
  h.respond(0); await pending; h.buttons[2].click(); assert.equal(h.blobs.size, 1);
  search.value = 'Fixture'; search.fire('input'); search.fire('change');
  assert.equal(h.blobs.size, 1); assert.equal(h.buttons[2].disabled, false);
  checks[0].click(); assert.equal(h.blobs.size, 0); assert.equal(h.buttons[2].disabled, true);
  checks[1].click(); assert.match(summary.textContent, /请选择/);
  await h.form.fire('submit'); assert.equal(h.requests.length, 1);
  h.widget.dispose(); checks[0].click(); assert.equal(h.fields.game_ids.selectedOptions.length, 0);
  assert.equal(search.listeners.size, 0);
});

test('full remote game directory is searchable without truncation or dependent fetches', async () => {
  const h = await setup('/test-only-export', true);
  const allGames = Array.from({length:583}, (_, i) => ({value:String(1000+i), label:`Fixture game ${i}`}));
  h.respond(0, {options:{...metadata().options, games:allGames}}); await tick();
  const nodes = walk(h.root), search = nodes.find(node => node.type === 'search');
  const checks = nodes.filter(node => node.type === 'checkbox');
  assert.equal(checks.length, 583); assert.equal(h.fields.game_ids.children.length, 583);
  search.value = '1582'; search.fire('input');
  assert.equal(checks.filter(check => !check.parent.hidden).length, 1);
  assert.equal(text(checks[582].parent).trim(), '1582 | Fixture game 582');
  await checks[582].click();
  assert.equal(h.requests.length, 1);
  assert.equal(h.fields.cid.disabled, true); assert.equal(h.fields.aid.disabled, true);
  assert.equal(h.buttons[0].disabled, false);
  assert.equal(h.fields.progress.value, ''); assert.equal(h.fields.status.value, '');
  assert.equal(checks[582].checked, true);
  search.value = 'Fixture game 0'; search.fire('input');
  await checks[0].click();
  assert.deepEqual(h.fields.game_ids.selectedOptions.map(option => option.value), ['1000', '1582']);
  assert.equal(h.requests.length, 1);
  h.widget.dispose();
  assert.equal(h.root.children.length, 0);
});

test('game picker enforces existing 100-game request limit without losing selected hidden matches', async () => {
  const h = await setup('/test-only-export', true);
  const allGames = Array.from({length:101}, (_, i) => ({value:String(i+1),label:`Fixture ${i}`}));
  h.respond(0, {options:{...metadata().options,games:allGames}}); await tick();
  h.fields.game_ids.children.forEach((option, i) => { option.selected = i < 100; });
  await h.form.fire('change', h.fields.game_ids);
  const checks = walk(h.root).filter(node => node.type === 'checkbox');
  assert.equal(checks[100].disabled, true); checks[100].click(); assert.equal(h.requests.length, 1);
  await checks[0].click();
  assert.equal(checks[100].disabled, false);
  await checks[100].click();
  assert.equal(h.fields.game_ids.selectedOptions.length, 100);
  assert.equal(checks[0].disabled, true); assert.equal(checks[100].checked, true);
  h.widget.dispose();
});

test('strict calendar validation, inclusive UTC conversion and source range limit', async () => {
  const { orderEmailRequest: build } = await modulePromise;
  assert.deepEqual(build(input, sites, games), { site_id: '266', game_ids: ['26', '27'], start: '2026-01-01', end_exclusive: '2026-02-01' });
  for (const [start, end, expected] of [['2024-02-29', '2024-02-29', '2024-03-01'],
    ['2026-12-31', '2026-12-31', '2027-01-01'], ['2026-03-08', '2026-03-08', '2026-03-09'],
    ['0099-12-31', '0099-12-31', '0100-01-01'], ['2024-01-01', '2024-12-31', '2025-01-01']]) {
    assert.equal(build({ ...input, start, end }, sites, games).end_exclusive, expected);
  }
  for (const patch of [{ start: '2026-02-29' }, { end: '2026-04-31' }, { start: '20260101' },
    { start: '2026-1-01' }, { start: '0000-01-01' }, { start: '2026-01-01T00:00:00Z' },
    { end: '2025-12-31' }, { end: '2027-01-02' }, { start: '9999-12-31', end: '9999-12-31' },
    { site_id: '999' }, { game_ids: [] }, { game_ids: ['26', '26'] }, { game_ids: ['999'] },
    { game_ids: new Array(1) }]) assert.throws(() => build({ ...input, ...patch }, sites, games), TypeError);
  assert.throws(() => build(input, [], games), TypeError);
});

test('endpoint is explicit, same-origin, query-free and credential-free', async () => {
  for (const endpoint of [undefined, '', 'https://elsewhere.invalid/export', '//elsewhere.invalid/export',
    'javascript:alert(1)', '/export?email=private', '/export#fragment', '/export?',
    'https://user:pass@fixture.invalid/export']) await assert.rejects(setup(endpoint === undefined ? null : endpoint), TypeError);
});

test('POST and validated download; no email in DOM, URL, or automatic download', async () => {
  const h = await setup();
  assert.match(text(h.root), /45 秒/); assert.match(text(h.root), /全年导出尚未验收/);
  const pending = h.form.fire('submit');
  const { url, options } = h.requests[0];
  assert.equal(url, 'https://fixture.invalid/test-only-export');
  assert.equal(options.method, 'POST'); assert.equal(options.credentials, 'same-origin');
  assert.equal(options.redirect, 'error'); assert.equal(options.cache, 'no-store');
  assert.equal(options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(options.body), { site_id: '266', game_ids: ['26', '27'], start: '2026-01-01', end_exclusive: '2026-02-01' });
  assert.equal(h.fields.cid.disabled, true); assert.equal(h.fields.aid.disabled, true);
  assert.equal(h.buttons[2].disabled, true);
  h.respond(0); await pending;
  assert.equal(h.buttons[2].disabled, false); assert.equal(h.doc.downloads.length, 0);
  assert.doesNotMatch(text(h.root), /Customer@/);
  h.buttons[2].click();
  const blob = h.blobs.get(h.doc.downloads[0].href);
  assert.equal(blob.type, 'text/csv;charset=utf-8');
  const bytes = Buffer.from(await blob.arrayBuffer());
  assert.equal(bytes.toString('utf8'), '\uFEFFemail\r\n"Customer@Example.com"\r\n');
  h.buttons[2].click(); assert.equal(h.revoked.length, 1);
  h.form.fire('input'); assert.equal(h.blobs.size, 0); assert.equal(h.buttons[2].disabled, true);
  h.buttons[2].click(); assert.equal(h.doc.downloads.length, 2);
  h.widget.dispose();
});

test('input and change abort; stale responses cannot replace newer results', async () => {
  const h = await setup();
  const old = h.form.fire('submit'); h.form.fire('change');
  assert.equal(h.requests[0].options.signal.aborted, true);
  const newer = h.form.fire('submit'); h.respond(1); await newer;
  h.respond(0, { error: 'private@example.com' }); await old;
  assert.equal(h.buttons[2].disabled, false); assert.match(text(h.root), /完整读取完成/);
  const pending = h.form.fire('submit'); h.form.fire('input'); h.respond(2); await pending;
  assert.equal(h.buttons[2].disabled, true); assert.doesNotMatch(text(h.root), /private@/);
  h.widget.dispose();
});

test('cancel during JSON parsing and dispose ignore late completion and release resources', async () => {
  const h = await setup(); let resolveJson;
  const pending = h.form.fire('submit');
  h.requests[0].resolve({ ok: true, json: () => new Promise(resolve => { resolveJson = resolve; }) });
  await Promise.resolve(); h.buttons[1].click(); resolveJson(success()); await pending;
  assert.equal(h.buttons[2].disabled, true); assert.match(text(h.root), /已取消/);
  const next = h.form.fire('submit'); h.respond(1); await next; h.buttons[2].click();
  h.buttons[1].click(); assert.equal(h.blobs.size, 0);
  const final = h.form.fire('submit'); h.widget.dispose(); h.widget.dispose();
  assert.equal(h.requests[2].options.signal.aborted, true);
  h.respond(2); await final;
  assert.equal(h.root.children.length, 0); assert.equal(h.form.listeners.size, 0);
  assert.equal(h.buttons[2].listeners.size, 0); assert.equal(h.blobs.size, 0);
});

test('partial, malformed, wrong scope/period, HTTP and network failures never enable export or expose errors', async () => {
  for (const result of [{ ...success(), complete: false }, { ...success(), emails: ['bad'] },
    { ...success(), scope: { site_id: '999', game_ids: ['26', '27'] } },
    { ...success(), scope: { site_id: '266', game_ids: ['26'] } },
    { ...success(), period: { start: '2026-01-02', end_exclusive: '2026-02-01' } },
    { ...success(), error: 'private@example.com' }, null, 'http', 'network', 'json', 'redirect']) {
    const h = await setup(); const pending = h.form.fire('submit');
    if (result === 'network') h.requests[0].reject(new Error('private@example.com'));
    else if (result === 'json') h.requests[0].resolve({ ok: true, json: async () => { throw new Error('private@example.com'); } });
    else if (result === 'redirect') h.requests[0].resolve({ ok: true, redirected: true });
    else h.respond(0, result, result !== 'http');
    await pending;
    assert.equal(h.buttons[2].disabled, true); assert.equal(h.buttons[0].disabled, false);
    assert.match(text(h.root), /无法导出/); assert.doesNotMatch(text(h.root), /private@/);
    h.buttons[2].click(); assert.equal(h.doc.downloads.length, 0); h.widget.dispose();
  }
});

test('invalid form does not fetch; disposal revokes a completed download URL', async () => {
  const h = await setup(); h.fields.start.value = '2026-02-30';
  await h.form.fire('submit'); assert.equal(h.requests.length, 0);
  h.fields.start.value = input.start;
  const pending = h.form.fire('submit'); h.respond(0); await pending; h.buttons[2].click();
  h.widget.dispose(); assert.equal(h.blobs.size, 0); assert.equal(h.revoked.length, 1);
});
