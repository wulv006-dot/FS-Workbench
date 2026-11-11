const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const source = readFileSync(join(__dirname, 'data-workspace.js'), 'utf8');
const dataURL = text => 'data:text/javascript;base64,' + Buffer.from(text).toString('base64');
const tick = () => new Promise(resolve => setImmediate(resolve));

// Minimal DOM with actual parent/child ownership and text clearing, not source assertions.
class Node {
  constructor(tag, doc) { this.tagName = tag; this.ownerDocument = doc; this.children = []; this.attrs = {}; this.listeners = {}; this.value = ''; }
  set textContent(text) { this.replaceChildren(); this.text = String(text); }
  get textContent() { return (this.text || '') + this.children.map(child => child.textContent).join(''); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentNode = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const child of this.children) child.parentNode = null; this.children = []; this.text = ''; this.append(...nodes); }
  remove() { if (this.parentNode) { const parent = this.parentNode; parent.children.splice(parent.children.indexOf(this), 1); this.parentNode = null; } }
  get firstChild() { return this.children[0]; }
  get options() { return this.children; }
  closest(tag) { return this.tagName === tag ? this : this.parentNode?.closest(tag); }
  setAttribute(name, value) { this.attrs[name] = value; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
}
function dom() {
  let requests = 0;
  const doc = { defaultView: { fetch() { requests++; throw Error('Unexpected network'); } } };
  doc.createElement = tag => new Node(tag, doc);
  return { root: doc.createElement('main'), requests: () => requests };
}
let serial = 0;
async function load(stub = '') {
  const key = '__emailWorkspace' + serial++;
  const state = { imports: 0, calls: [], disposals: 0, pii: ['fixture@example.invalid'] };
  globalThis[key] = state;
  const moduleURL = dataURL(`const state = globalThis[${JSON.stringify(key)}]; state.imports++; ${stub || `
    export function mountOrderEmailExport() { throw Error('CSV entry must not be called'); }
    export function mountOrderEmailExcelExport(root, options) {
      state.calls.push({root, options});
      root.append(root.ownerDocument.createElement('form'));
      return { dispose() { state.disposals++; state.pii.length = 0; root.replaceChildren(); } };
    }`}`);
  const rewritten = source.replace("'./order-email-panel.js'", JSON.stringify(moduleURL));
  assert.notEqual(rewritten, source, 'rewrite only the real dynamic import specifier');
  const mod = await import(dataURL(rewritten + '\n// ' + key));
  return { ...mod, state, key, cleanup() { delete globalThis[key]; } };
}
// Fixture-only configuration, never a production route or directory.
function config() { return { endpoint: '/fixture-export', sites: [{ value: '71', label: 'Fixture site' }], games: [{ value: '82', label: 'Fixture game' }], fetch() { throw Error('No automatic export request'); }, paged: true }; }

test('legacy caller mounts existing panels without importing or requesting email data', async () => {
  const h = await load(), d = dom();
  try {
    const widget = h.mountDataWorkspace(d.root);
    await tick();
    assert.equal(h.state.imports, 0); assert.equal(d.requests(), 0);
    assert.match(d.root.textContent, /单品跟踪/); assert.match(d.root.textContent, /优惠摘要/);
    assert.doesNotMatch(d.root.textContent, /订单用户邮箱/);
    assert.equal(typeof widget.dispose, 'function'); widget.dispose(); assert.equal(d.root.children.length, 0);
  } finally { h.cleanup(); }
});

test('configured mount calls Excel entry with exactly explicit options and safe ready status', async () => {
  const h = await load(), d = dom(), options = config();
  try {
    const widget = h.mountDataWorkspace(d.root, { endpoint: '/unrelated', orderEmailExport: options });
    for (let n = 0; n < 20 && !h.state.calls.length; n++) await tick();
    assert.equal(h.state.imports, 1); assert.equal(h.state.calls.length, 1);
    assert.deepEqual(h.state.calls[0].options, options);
    assert.equal(h.state.calls[0].root.parentNode, d.root.firstChild);
    assert.match(d.root.textContent, /Excel 导出已就绪；尚未查询/);
    assert.equal(d.requests(), 0); widget.dispose();
  } finally { h.cleanup(); }
});

test('dispose during pending import prevents late mount', async () => {
  const h = await load('await new Promise(resolve => { state.release = resolve; }); export function mountOrderEmailExcelExport() { state.calls.push(true); }'), d = dom();
  try {
    const widget = h.mountDataWorkspace(d.root, { orderEmailExport: config() });
    widget.dispose();
    for (let n = 0; n < 20 && !h.state.release; n++) await tick();
    assert.equal(typeof h.state.release, 'function'); h.state.release(); await tick(); await tick();
    assert.equal(h.state.calls.length, 0); assert.equal(d.root.children.length, 0);
  } finally { h.cleanup(); }
});

test('dispose after mount disposes child once and clears its PII and DOM', async () => {
  const h = await load(), d = dom();
  try {
    const widget = h.mountDataWorkspace(d.root, { orderEmailExport: config() });
    for (let n = 0; n < 20 && !h.state.calls.length; n++) await tick();
    assert.equal(h.state.calls.length, 1);
    const host = h.state.calls[0].root;
    assert.equal(host.children.length, 1);
    widget.dispose(); widget.dispose();
    assert.equal(h.state.disposals, 1); assert.deepEqual(h.state.pii, []);
    assert.equal(host.children.length, 0); assert.equal(d.root.children.length, 0);
  } finally { h.cleanup(); }
});

for (const failure of ['import', 'mount']) test(`${failure} error shows only safe status and leaves legacy panels usable`, async () => {
  const secret = 'fixture@example.invalid /private/fixture-path';
  const h = await load(failure === 'import' ? `throw Error(${JSON.stringify(secret)}); export const unused = true;` : `export function mountOrderEmailExcelExport(root) { root.textContent = ${JSON.stringify(secret)}; throw Error(${JSON.stringify(secret)}); }`), d = dom();
  try {
    const widget = h.mountDataWorkspace(d.root, { orderEmailExport: config() });
    for (let n = 0; n < 20 && !d.root.textContent.includes('暂不可用'); n++) await tick();
    assert.match(d.root.textContent, /导出暂不可用/);
    assert.doesNotMatch(d.root.textContent, /fixture@example|private\/fixture|已就绪/);
    assert.match(d.root.textContent, /单品跟踪/); assert.equal(d.requests(), 0);
    widget.dispose(); assert.equal(d.root.children.length, 0);
  } finally { h.cleanup(); }
});
