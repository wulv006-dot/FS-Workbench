const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../ui/users.js'),'utf8');
const definitions=['localDay','addDay'].map(name=>{
  const line=source.split(/\r?\n/).find(s=>s.startsWith('const '+name+'='));
  assert.ok(line,'actual date definition missing: '+name);return line;
});
const match=source.match(/function reportDates\(info,now=new Date\(\)\)\{[\s\S]*?\n\}/);
assert.ok(match,'actual report date helper missing');
const reportDates=Function(definitions.join('\n')+'\n'+match[0]+'\nreturn reportDates;')();
const info={cutoff:'2026-10-26T00:00:00+08:00',default_start:'2026-10-19T00:00:00+08:00'};
const expected={cutoff:'2026-10-26',start:'2026-10-19',end:'2026-10-25'};
assert.deepEqual(reportDates(info,new Date('2026-10-30T22:00:00Z')),expected);
assert.deepEqual(reportDates(info,new Date('2026-11-01T22:00:00Z')),expected);
assert.equal(reportDates(null,new Date('2026-10-30T23:00:00Z')).cutoff,'2026-10-31');
assert.deepEqual(reportDates({cutoff:'2026-11-02T00:00:00+08:00',default_start:'2026-10-26T00:00:00+08:00'}),
  {cutoff:'2026-11-02',start:'2026-10-26',end:'2026-11-01'});
console.log('weekly UI date helper: four semantic checks passed');
