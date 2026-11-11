import { orderEmailCsv, orderEmailTraversalCsv } from './order-email-csv.js';

/** Browser-only OOXML bytes. Reuse the authoritative validation, not CSV rewriting. */
export function orderEmailXlsx(payload) {
  checkRowLimit(payload);
  orderEmailCsv(payload);
  return workbook(payload.emails);
}

export function orderEmailTraversalXlsx(payload) {
  checkRowLimit(payload);
  orderEmailTraversalCsv(payload);
  return workbook(payload.emails);
}

function checkRowLimit(payload) {
  if (Array.isArray(payload?.emails) && payload.emails.length > 1048575)
    throw new RangeError('Email export exceeds Excel row limit (1048576 including header)');
}

function xmlText(value) {
  // XML 1.0 cannot represent these characters, even as numeric references.
  if (/[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\u{10000}-\u{10ffff}]/u.test(value))
    throw new TypeError('Email contains invalid XML characters');
  // SpreadsheetML decodes _xHHHH_; escape a literal sequence's underscore first.
  return value.replace(/_(?=x[0-9a-f]{4}_)/gi, '_x005F_')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

const declaration = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
function workbook(emails) {
  const row = number => `<row r="${number}"><c r="A${number}" t="s"><v>${number - 1}</v></c></row>`;
  const strings = ['<si><t xml:space="preserve">email</t></si>'];
  const rows = [row(1)];
  for (let index = 0; index < emails.length; index++) {
    strings.push(`<si><t xml:space="preserve">${xmlText(emails[index])}</t></si>`);
    rows.push(row(index + 2));
  }
  return zip([
    ['[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>'],
    ['_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'],
    ['xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="emails" sheetId="1" r:id="rId1"/></sheets></workbook>'],
    ['xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>'],
    ['xl/sharedStrings.xml', `<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="${strings.length}">${strings.join('')}</sst>`],
    ['xl/worksheets/sheet1.xml', `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:A${emails.length + 1}"/><sheetData>${rows.join('')}</sheetData></worksheet>`],
  ]);
}

const crcTable = Uint32Array.from({ length: 256 }, (_, value) => {
  for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ ((value & 1) ? 0xedb88320 : 0);
  return value >>> 0;
});
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = (crc >>> 8) ^ crcTable[(crc ^ byte) & 255];
  return (crc ^ 0xffffffff) >>> 0;
}

// shortcut: fixed six-entry stored ZIP (no ZIP64), upgrade if export scope grows.
function zip(entries) {
  const encoder = new TextEncoder();
  const files = entries.map(([path, xml]) => ({ name: encoder.encode(path), data: encoder.encode(declaration + xml) }));
  const localSize = files.reduce((size, file) => size + 30 + file.name.length + file.data.length, 0);
  const centralSize = files.reduce((size, file) => size + 46 + file.name.length, 0);
  if (localSize + centralSize + 22 > 0xffffffff) throw new RangeError('Email workbook exceeds ZIP size limit');
  const bytes = new Uint8Array(localSize + centralSize + 22);
  const view = new DataView(bytes.buffer);
  const u16 = (offset, value) => view.setUint16(offset, value, true);
  const u32 = (offset, value) => view.setUint32(offset, value, true);
  let local = 0;
  let central = localSize;
  for (const { name, data } of files) {
    const crc = crc32(data);
    u32(local, 0x04034b50); u16(local + 4, 20); u16(local + 6, 0x0800);
    u16(local + 12, 33); // Fixed DOS date: 1980-01-01, midnight.
    u32(local + 14, crc); u32(local + 18, data.length); u32(local + 22, data.length);
    u16(local + 26, name.length);
    bytes.set(name, local + 30); bytes.set(data, local + 30 + name.length);
    u32(central, 0x02014b50); u16(central + 4, 20); u16(central + 6, 20);
    u16(central + 8, 0x0800); u16(central + 14, 33);
    u32(central + 16, crc); u32(central + 20, data.length); u32(central + 24, data.length);
    u16(central + 28, name.length); u32(central + 42, local);
    bytes.set(name, central + 46);
    local += 30 + name.length + data.length;
    central += 46 + name.length;
  }
  u32(central, 0x06054b50); u16(central + 8, files.length); u16(central + 10, files.length);
  u32(central + 12, centralSize); u32(central + 16, localSize);
  return bytes;
}
