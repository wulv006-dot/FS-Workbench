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
  }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, fn) { this.listeners.set(name, fn); }
  removeEventListener(name, fn) { if (this.listeners.get(name) === fn) this.listeners.delete(name); }
  fire(name, target = this) { return this.listeners.get(name)?.({ target, preventDefault() {} }); }
  click() { if (this.tag === 'a') this.ownerDocument.downloads.push({ href: this.href, name: this.download }); return this.fire('click'); }
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

test('all 14 Admin filters serialize and filter changes revoke downloaded data', async () => {
  const h = await setup();
  const names = ['progress','status','cid','content','aid','recommend_uid','discount_code','promotion_id','pid','country'];
  for (const name of [...names, 'site_id', 'game_ids', 'start', 'end']) assert.ok(h.fields[name]);
  const filters = Object.fromEntries(names.map(name => [name, name === 'content' ? 'game / server' : '1']));
  for (const name of names) { h.fields[name].disabled = false; h.fields[name].value = filters[name]; }
  assert.equal(h.fields.admin_id, undefined);
  const pending = h.form.fire('submit');
  assert.deepEqual(JSON.parse(h.requests[0].options.body).filters, filters);
  h.respond(0, { ...success(), filters }); await pending;
  h.buttons[2].click(); assert.equal(h.blobs.size, 1);
  h.fields.discount_code.value = 'another'; h.form.fire('change', h.fields.discount_code);
  assert.equal(h.blobs.size, 0); assert.equal(h.buttons[2].disabled, true);
  h.fields.status.value = '2'; h.fields.aid.value = '3';
  h.form.fire('change', h.fields.game_ids);
  assert.equal(h.fields.status.value, '2'); assert.equal(h.fields.aid.value, '');
  h.widget.dispose();
});

test('authenticated same-endpoint metadata and dependent refresh use real options', async () => {
  const h = await setup('/test-only-export', true);
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { kind: 'order_email_export_options', progress: '1' });
  assert.equal(h.requests[0].options.credentials, 'same-origin');
  const options = { sites, games };
  for (const name of ['progress','status','cid','aid','admin_id','country']) options[name] = [{value:'1',label:'Real option'}];
  options.status = [{value:'11',label:'已支付'}];
  h.respond(0, {options}); await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.fields.progress.children[1].textContent, 'Real option');
  assert.equal(h.fields.progress.value, '1'); assert.equal(h.fields.status.value, '11');
  assert.equal(h.fields.cid.disabled, true); assert.equal(h.fields.aid.disabled, true);
  h.fields.site_id.value = '266';
  h.fields.game_ids.children[0].selected = true;
  const refresh = h.form.fire('change', h.fields.game_ids);
  assert.equal(h.fields.status.value, '11');
  assert.equal(JSON.parse(h.requests[1].options.body).progress, '1');
  h.respond(1, {options: {...options, aid: []}, unavailable: {aid:'metadata_source_unavailable'}}); await refresh;
  assert.equal(h.fields.cid.disabled, false); assert.equal(h.fields.aid.disabled, true);
  assert.equal(h.buttons[0].disabled, false);
  assert.equal(h.fields.site_id.value, '266'); assert.equal(h.fields.status.value, '11');
  assert.match(text(h.root), /服务区目录暂不可用，可按其他条件查询/);
  h.fields.start.value = input.start; h.fields.end.value = input.end;
  h.fields.aid.value = 'stale';
  const query = h.form.fire('submit');
  assert.deepEqual(JSON.parse(h.requests[2].options.body).filters, {progress:'1',status:'11'});
  h.respond(2, {...success(), filters: {progress:'1',status:'11'}, scope: {site_id:'266',game_ids:['26']}}); await query;
  assert.equal(h.buttons[2].disabled, false);
  h.widget.dispose();
});

const metadata = () => ({options: {sites, games, progress:[{value:'1',label:'已支付'}],
  status:[{value:'11',label:'已支付'}], cid:[{value:'1',label:'金币'}],
  aid:[{value:'9',label:'服务器'}], admin_id:[], country:[{value:'US',label:'美国'}]}});
const tick = () => new Promise(resolve => setImmediate(resolve));
test('metadata failures stay closed; stale game directories and disposed responses cannot revive controls', async () => {
  const broken = await setup('/test-only-export', true);
  broken.respond(0, {options:{...metadata().options, country:[]}}); await tick();
  assert.equal(broken.buttons[0].disabled, true);
  await broken.form.fire('submit'); assert.equal(broken.requests.length, 1); broken.widget.dispose();
  const h = await setup('/test-only-export', true);
  h.respond(0, metadata()); await tick();
  h.fields.site_id.value = '266'; h.fields.game_ids.children[0].selected = true;
  const older = h.form.fire('change', h.fields.game_ids);
  h.fields.game_ids.children[0].selected = false; h.fields.game_ids.children[1].selected = true;
  const newer = h.form.fire('change', h.fields.game_ids);
  h.respond(2, {options:{...metadata().options, aid:[]}, unavailable:{aid:'metadata_source_unavailable'}}); await newer;
  h.respond(1, metadata()); await older;
  assert.equal(h.fields.aid.disabled, true); assert.equal(h.fields.aid.children.length, 1);
  assert.equal(h.fields.status.value, '11'); assert.equal(h.fields.site_id.value, '266');
  const late = h.form.fire('change', h.fields.game_ids); h.widget.dispose();
  h.respond(3, metadata()); await late; assert.equal(h.root.children.length, 0);
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
