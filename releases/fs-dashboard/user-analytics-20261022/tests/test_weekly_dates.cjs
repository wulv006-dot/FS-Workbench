const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../ui/users.js'), 'utf8');
const definitions = ['dateShift', 'reportDates'].map(name => {
  const match = source.match(new RegExp('function ' + name + '[\\s\\S]*?\\n}'));
  assert.ok(match, 'date helper missing: ' + name);
  return match[0];
});
const reportDates = Function(definitions.join('\n') + '\nreturn reportDates;')();
const origin = '2026-01-01';
assert.deepEqual(reportDates({cutoff:'2026-11-24T00:00:00+08:00'}, origin), {
  cutoff:'2026-11-24', start:'2026-11-17', end:'2026-11-23', firstMonth:'2026-01', lastMonth:'2026-10',
});
assert.deepEqual(reportDates({cutoff:'2026-01-03T00:00:00+08:00'}, origin), {
  cutoff:'2026-01-03', start:origin, end:'2026-01-02', firstMonth:'2026-01', lastMonth:'2026-01',
});
assert.equal(reportDates(null, origin), null);
assert.equal(reportDates({cutoff:'2026-01-01T00:00:00+08:00'}, origin), null);
console.log('v4 UI publication dates: four semantic checks passed');
