const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const dataUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const csvUrl = dataUrl(readFileSync(join(__dirname, 'order-email-csv.js'), 'utf8'));
const source = readFileSync(join(__dirname, 'order-email-xlsx.js'), 'utf8');
const modulePromise = import(dataUrl(source.replace("'./order-email-csv.js'", JSON.stringify(csvUrl))));
const success = (emails = ['Customer@example.com']) => ({
  status: 'available', complete: true, semantics: 'live_non_snapshot',
  limitation: 'live_pagination_not_snapshot', email_field: 'user_email',
  deduplication: 'trim_casefold', emails, unique_emails: emails.length,
  observed_orders: emails.length, missing_email_orders: 0,
  scope: { site_id: '266', game_ids: ['26'] },
});
const traversal = emails => ({ ...success(emails), complete: false, state: 'exhausted',
  traversal_exhausted: true, total_windows: 1, exhausted_windows: 1, accepted_pages: 1,
  timezone: 'Asia/Shanghai', date_field: 'paytime', source_reported_total: emails.length });

// Independent bit-by-bit CRC and central/local reader, not implementation helpers.
function crc32(data) {
  let crc = -1;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
  }
  return (crc ^ -1) >>> 0;
}
function unzip(bytes) {
  assert.ok(bytes instanceof Uint8Array);
  const b = Buffer.from(bytes);
  const end = b.length - 22;
  assert.equal(b.readUInt32LE(end), 0x06054b50);
  assert.equal(b.readUInt32LE(end + 4), 0);
  assert.equal(b.readUInt16LE(end + 20), 0);
  const count = b.readUInt16LE(end + 10);
  assert.equal(b.readUInt16LE(end + 8), count);
  const start = b.readUInt32LE(end + 16);
  assert.equal(start + b.readUInt32LE(end + 12), end);
  let c = start, nextLocal = 0;
  const entries = {};
  for (let i = 0; i < count; i++) {
    assert.equal(b.readUInt32LE(c), 0x02014b50);
    assert.equal(b.readUInt16LE(c + 8), 0x800);
    assert.equal(b.readUInt16LE(c + 10), 0);
    const size = b.readUInt32LE(c + 24);
    assert.equal(b.readUInt32LE(c + 20), size);
    const n = b.readUInt16LE(c + 28), extra = b.readUInt16LE(c + 30), comment = b.readUInt16LE(c + 32);
    const name = b.subarray(c + 46, c + 46 + n).toString('utf8');
    const l = b.readUInt32LE(c + 42);
    assert.equal(l, nextLocal);
    assert.equal(b.readUInt32LE(l), 0x04034b50);
    assert.equal(b.readUInt16LE(l + 6), 0x800);
    assert.equal(b.readUInt16LE(l + 8), 0);
    assert.equal(b.readUInt32LE(l + 18), size);
    assert.equal(b.readUInt32LE(l + 22), size);
    assert.equal(b.readUInt16LE(l + 26), n);
    assert.equal(b.readUInt16LE(l + 28), 0);
    assert.equal(b.subarray(l + 30, l + 30 + n).toString(), name);
    const data = b.subarray(l + 30 + n, l + 30 + n + size);
    assert.equal(crc32(data), b.readUInt32LE(c + 16));
    assert.equal(crc32(data), b.readUInt32LE(l + 14));
    assert.ok(!Object.hasOwn(entries, name));
    entries[name] = data.toString('utf8');
    nextLocal = l + 30 + n + size;
    c += 46 + n + extra + comment;
  }
  assert.equal(nextLocal, start); assert.equal(c, end);
  return entries;
}
function texts(entries) {
  const strings = [...entries['xl/sharedStrings.xml'].matchAll(/<si><t xml:space="preserve">([^<]*)<\/t><\/si>/g)].map(m => m[1]);
  return [...entries['xl/worksheets/sheet1.xml'].matchAll(/<c r="(A[0-9]+)" t="s"><v>([0-9]+)<\/v><\/c>/g)].map((m, i) => {
    assert.equal(m[1], 'A' + (i + 1));
    assert.equal(Number(m[2]), i);
    return strings[Number(m[2])].replace(/&(amp|lt|gt|quot|apos);/g, (_, entity) => ({ amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" })[entity])
      .replace(/_x([0-9a-f]{4})_/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
  });
}

test('real deterministic stored OOXML ZIP, required parts and internal relationships only', async () => {
  const { orderEmailXlsx } = await modulePromise;
  const bytes = orderEmailXlsx(success());
  assert.deepEqual(bytes, orderEmailXlsx(success()));
  const entries = unzip(bytes);
  assert.deepEqual(Object.keys(entries), ['[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels', 'xl/sharedStrings.xml', 'xl/worksheets/sheet1.xml']);
  assert.match(entries['[Content_Types].xml'], /spreadsheetml.sheet.main\+xml/);
  assert.match(entries['[Content_Types].xml'], /spreadsheetml.worksheet\+xml/);
  assert.match(entries['_rels/.rels'], /Target="xl\/workbook.xml"/);
  assert.match(entries['xl/_rels/workbook.xml.rels'], /Target="worksheets\/sheet1.xml"/);
  assert.equal((entries['xl/workbook.xml'].match(/<sheet /g) || []).length, 1);
  for (const xml of Object.values(entries)) {
    assert.match(xml, /^<\?xml version="1.0" encoding="UTF-8"/);
    assert.doesNotMatch(xml, /<f(?:\s|>)|<hyperlink|TargetMode="External"|<!DOCTYPE|<!ENTITY/);
  }
  assert.deepEqual(texts(entries), ['email', 'Customer@example.com']);
});

test('original Unicode, case, ordering, duplicates, punctuation and formula-looking text survive', async () => {
  const { orderEmailXlsx, orderEmailTraversalXlsx } = await modulePromise;
  const emails = ['Customer+tag@Example.com', '用户@例子.中国', '😀@example.com', 'Straße@example.com', 'STRASSE@example.com',
    '=x@example.com', '+x@example.com', '-x@example.com', 'a,"b"&<>\'@example.com', '_x0041_@example.com', '_x005F_x0041_@example.com', 'A@example.com', 'A@example.com'];
  const payload = success(emails), before = JSON.stringify(payload);
  for (const bytes of [orderEmailXlsx(payload), orderEmailTraversalXlsx(traversal(emails))]) {
    const entries = unzip(bytes), xml = entries['xl/worksheets/sheet1.xml'];
    assert.deepEqual(texts(entries), ['email', ...emails]);
    assert.equal((xml.match(/<c /g) || []).length, emails.length + 1);
    assert.doesNotMatch(xml, /<f[ >]/);
  }
  assert.equal(JSON.stringify(payload), before);
});

test('complete empty and exhausted empty workbooks contain header only', async () => {
  const { orderEmailXlsx, orderEmailTraversalXlsx } = await modulePromise;
  for (const bytes of [orderEmailXlsx(success([])), orderEmailTraversalXlsx(traversal([]))])
    assert.deepEqual(texts(unzip(bytes)), ['email']);
});

test('full validation rejects incomplete payloads, invalid entries, counts and scopes', async () => {
  const { orderEmailXlsx, orderEmailTraversalXlsx } = await modulePromise;
  for (const value of [null, undefined, [], {}, { ...success(), error: 'failed' },
    { ...success(), unique_emails: 2 }, { ...success(), scope: null },
    { ...success(), complete: false }, { ...success(), status: 'partial' }])
    assert.throws(() => orderEmailXlsx(value), TypeError);
  for (const email of ['', null, 'bad', 'a@@b', ' a@b', 'a\nb@c', '\ud800@b', 'a\u0000@b', 'a\ufffe@b', 'a\uffff@b']) {
    assert.throws(() => orderEmailXlsx(success(['valid@example.com', email])), TypeError);
    assert.throws(() => orderEmailTraversalXlsx(traversal([email])), TypeError);
  }
  assert.throws(() => orderEmailXlsx(success(new Array(1))), TypeError);
  for (const patch of [{ state: 'running' }, { traversal_exhausted: false }, { exhausted_windows: 0 },
    { accepted_pages: 0 }, { complete: true }, { timezone: 'UTC' }, { date_field: 'created_at' }, { source_reported_total: 2 }])
    assert.throws(() => orderEmailTraversalXlsx({ ...traversal(['a@b']), ...patch }), TypeError);
});

test('Excel row limit includes header and refuses excess before costly serialization', async () => {
  const { orderEmailXlsx, orderEmailTraversalXlsx } = await modulePromise;
  const excess = new Array(1048576).fill('a@b');
  assert.throws(() => orderEmailXlsx(success(excess)), /row limit/);
  assert.throws(() => orderEmailTraversalXlsx(traversal(excess)), /row limit/);
  const bytes = orderEmailXlsx(success(excess.slice(1)));
  // Inspect only the large sheet, avoiding a million-object XML parser allocation.
  const b = Buffer.from(bytes), name = Buffer.from('xl/worksheets/sheet1.xml');
  const local = b.indexOf(name) - 30;
  const xml = b.subarray(local + 30 + name.length, local + 30 + name.length + b.readUInt32LE(local + 22)).toString();
  assert.match(xml, /<dimension ref="A1:A1048576"/);
  assert.match(xml, /<row r="1048576"><c r="A1048576" t="s">/);
  assert.equal((xml.match(/<row /g) || []).length, 1048576);
});
