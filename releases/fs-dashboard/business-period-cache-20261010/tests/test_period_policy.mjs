import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
const text=fs.readFileSync(new URL('../period-policy.js',import.meta.url),'utf8');const policy=vm.runInNewContext(text+';fsPeriodPolicy()');
const cases=[['2026-10-10',7,'2026-10-03','2026-10-09'],['2026-10-10',14,'2026-09-26','2026-10-09'],['2026-10-10',30,'2026-09-10','2026-10-09'],['2026-01-01',7,'2025-12-25','2025-12-31'],['2024-03-01',7,'2024-02-23','2024-02-29'],['2025-03-01',7,'2025-02-22','2025-02-28']];
for(const [anchor,n,start,end] of cases){const q=policy.selection(n,null,'','',anchor);assert.equal(q.start,start);assert.equal(q.end,end);assert.equal((Date.parse(end)-Date.parse(start))/86400000+1,n);}
for(const [mode,start,end] of [['today','2026-10-10','2026-10-10'],['yesterday','2026-10-09','2026-10-09']]){const q=policy.selection(mode,null,'','','2026-10-10');assert.equal(q.start,start);assert.equal(q.end,end);}
assert.equal(policy.day(Date.parse('2026-10-10T15:59:59Z')),'2026-10-10');assert.equal(policy.day(Date.parse('2026-10-10T16:00:00Z')),'2026-10-11');
const pinned=policy.selection(7,null,'','','2026-10-10');assert.equal(pinned.end,'2026-10-09');assert.equal(policy.selection(7,null,'','','2026-10-11').end,'2026-10-10');
const now=Date.parse('2026-10-10T08:00:00Z');assert.equal(policy.ttl({start:'2026-10-03',end:'2026-10-09'},now),7200);assert.equal(policy.ttl({start:'2026-10-03',end:'2026-10-10'},now),900);
const custom=policy.selection('custom',{start:'2026-02-01',end:'2026-02-15'},'','','2026-10-10');assert.equal(custom.start,'2026-02-01');assert.equal(custom.end,'2026-02-15');
const source=fs.readFileSync(new URL('../assets/business.js',import.meta.url),'utf8');assert(source.includes('const selection=currentSelection(),snapshotId='));assert(source.includes('const allSeries=rowsInRange()'));assert(source.includes('fsPeriodPolicy().active(currentSelection())'));assert(source.includes('scope.summary=null'));assert(!source.includes('共享缓存120秒'));
console.log('D1 complete windows, timezone/month/year/leap boundaries, fixed view, custom TTL and unified consumers passed.');
