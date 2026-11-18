const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const url = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const modulePromise = import(url(readFileSync(join(__dirname, 'order-email-panel.js'), 'utf8')
  .replace("'./order-email-csv.js'", JSON.stringify(url(readFileSync(join(__dirname, 'order-email-csv.js')))))
  .replace("'./order-email-run.js'", JSON.stringify(url(readFileSync(join(__dirname, 'order-email-run.js')))))));
class Element {
  constructor(tag, ownerDocument) { Object.assign(this, { tag, ownerDocument, children: [], listeners: {}, value: '' }); }
  append(...nodes) { this.children.push(...nodes); }
  remove() {}
  setAttribute() {}
  removeAttribute() {}
  addEventListener(name, fn) { this.listeners[name] = fn; }
  removeEventListener(name) { delete this.listeners[name]; }
  fire(name) { return this.listeners[name]?.({ preventDefault() {} }); }
  get selectedOptions() { return this.children.filter(n => n.selected); }
}

test('all-game export shows an actionable terminal error without displaying upstream data', async () => {
  const { mountOrderEmailExport } = await modulePromise;
  const doc = { createElement(tag) { return new Element(tag, this); }, defaultView: {
    location: { href: 'https://fixture.invalid/tools', origin: 'https://fixture.invalid' },
    AbortController, Blob, URL: { revokeObjectURL() {} }
  } };
  const root = new Element('root', doc), requests = [];
  const widget = mountOrderEmailExport(root, { endpoint: '/fixture-page', paged: true,
    sites: [{ value: '266', label: 'Fixture' }], games: [{ value: '0', label: 'all' }],
    fetch: async (_, options) => {
      requests.push(JSON.parse(options.body));
      return { status: 409, ok: false, json: async () => ({
        error: 'source_changed_restart_required', detail: 'customer@example.test secret-cursor' }) };
    } });
  const nodes = walk(root), form = nodes.find(n => n.tag === 'form');
  const fields = Object.fromEntries(nodes.filter(n => n.name).map(n => [n.name, n]));
  fields.site_id.value = '266'; fields.game_ids.children[0].selected = true;
  fields.start.value = '2026-01-01'; fields.end.value = '2026-06-30';
  fields.progress.disabled = false; fields.progress.value = '10';
  await form.fire('submit');
  assert.deepEqual(requests, [{ site_id: '266', game_id: '0', filters: { progress: '10' }, start: '2026-01-01',
    end_exclusive: '2026-01-08' }]);
  const output = nodes.map(n => n.textContent).join(' ');
  assert.match(output, /分页期间订单数据已变化.*名单已清除/);
  assert.doesNotMatch(output, /customer@example.test|secret-cursor/);
  assert.equal(nodes.find(n => n.textContent === '下载 CSV').disabled, true);
  widget.dispose();
});
const walk = n => [n, ...n.children.flatMap(walk)];
const tick = () => new Promise(resolve => setImmediate(resolve));
for (const [header, body, delay, code] of [[null, 120, 120000], ['60', 180, 180000],
  ['120', 30, 120000], [null, 'bad', 60000], [null, 17, 17000, 'source_rate_limited']]) {
  test(`JSON retryAfter=${body} respects longest valid server guidance (${code || '429'})`, async () => {
    const original = Date.now; let now = 1800000000000; Date.now = () => now;
    let widget;
    try {
      const { mountOrderEmailExport } = await modulePromise;
      const doc = { createElement(tag) { return new Element(tag, this); }, defaultView: {
        location: { href: 'https://fixture.invalid/tools', origin: 'https://fixture.invalid' },
        AbortController, Blob, URL: { revokeObjectURL() {} }
      } };
      const root = new Element('root', doc); const requests = [];
      widget = mountOrderEmailExport(root, { endpoint: '/fixture-page', paged: true,
        sites: [{ value: '266', label: 'Fixture' }], games: [{ value: '26', label: 'Fixture' }],
        fetch: (url, options) => new Promise(resolve => requests.push({ resolve, options })) });
      const nodes = walk(root), form = nodes.find(n => n.tag === 'form');
      const fields = Object.fromEntries(nodes.filter(n => n.name).map(n => [n.name, n]));
      fields.site_id.value = '266'; fields.game_ids.children[0].selected = true;
      fields.start.value = fields.end.value = '2026-01-01';
      const buttons = nodes.filter(n => n.tag === 'button');
      const pending = form.fire('submit');
      for (let i = 0; i < 30 && !requests.length; i++) await tick();
      assert.equal(requests.length, 1);
      requests[0].resolve({ status: code ? 503 : 429, ok: false, headers: { get: () => header },
        json: async () => ({ complete: false, retryAfter: body, error: code }) }); await pending;
      now += delay - 1; await buttons[4].fire('click'); assert.equal(requests.length, 1);
      now++; const retry = buttons[4].fire('click');
      for (let i = 0; i < 30 && requests.length < 2; i++) await tick();
      assert.equal(requests.length, 2); assert.equal(requests[0].options.body, requests[1].options.body);
      widget.dispose(); requests[1].resolve({ status: 403 }); await retry;
    } finally { widget?.dispose(); Date.now = original; }
  });
}
