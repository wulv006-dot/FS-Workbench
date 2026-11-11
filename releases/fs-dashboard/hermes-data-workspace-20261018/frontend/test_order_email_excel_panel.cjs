const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const dataUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const csv = dataUrl(readFileSync(join(__dirname, 'order-email-csv.js')));
const xlsx = dataUrl(readFileSync(join(__dirname, 'order-email-xlsx.js'), 'utf8').replaceAll("'./order-email-csv.js'", JSON.stringify(csv)));
const panelSource = readFileSync(join(__dirname, 'order-email-panel.js'), 'utf8')
  .replace("'./order-email-csv.js'", JSON.stringify(csv));
// Reuse the established mock DOM without modifying its metadata-protected file.
const fixtureSource = readFileSync(join(__dirname, 'test_order_email_panel.cjs'), 'utf8');
const fixture = fixtureSource.slice(fixtureSource.indexOf('// Fixture directories only;'), fixtureSource.indexOf("test('strict calendar"))
  .replaceAll('mountOrderEmailExport', 'mountOrderEmailExcelExport');
function harness(modulePromise) {
  const context = { modulePromise, AbortController, Blob };
  vm.runInNewContext(fixture + '\nthis.setup = setup;', context);
  return context.setup();
}
const writerImport = "import('./order-email-xlsx.js')";
function loadedPanel() { return import(dataUrl(panelSource.replace(writerImport, `import(${JSON.stringify(xlsx)})`))); }
async function ready(h) { const pending = h.form.fire('submit'); h.respond(0); await pending; }

test('Excel entry downloads genuine XLSX bytes with explicit MIME and .xlsx name', async () => {
  const h = await harness(loadedPanel()); await ready(h);
  assert.match(h.buttons[2].textContent, /Excel/);
  assert.equal(h.doc.downloads.length, 0);
  const pending = h.buttons[2].click();
  assert.equal(h.buttons[2].disabled, true);
  await h.buttons[2].click(); // Duplicate event cannot start another writer.
  await pending;
  assert.equal(h.doc.downloads.length, 1);
  assert.equal(h.doc.downloads[0].name, 'order-user-emails.xlsx');
  const blob = h.blobs.get(h.doc.downloads[0].href);
  assert.equal(blob.type, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  const bytes = Buffer.from(await blob.arrayBuffer());
  assert.equal(bytes.readUInt32LE(0), 0x04034b50);
  assert.ok(bytes.includes(Buffer.from('Customer@Example.com')));
  h.form.fire('change'); assert.equal(h.blobs.size, 0); h.widget.dispose();
});

for (const action of ['change', 'cancel', 'dispose']) test(`pending Excel writer cannot download after ${action}`, async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  globalThis.__orderEmailExcelGate = gate;
  try {
    const modulePromise = import(dataUrl(panelSource.replace(writerImport, 'globalThis.__orderEmailExcelGate') + '\n// ' + action));
    const h = await harness(modulePromise); await ready(h);
    const pending = h.buttons[2].click();
    if (action === 'change') h.form.fire('change');
    else if (action === 'cancel') h.buttons[1].click();
    else h.widget.dispose();
    release(await import(xlsx)); await pending;
    assert.equal(h.doc.downloads.length, 0); assert.equal(h.blobs.size, 0);
    h.widget.dispose();
  } finally { delete globalThis.__orderEmailExcelGate; }
});
