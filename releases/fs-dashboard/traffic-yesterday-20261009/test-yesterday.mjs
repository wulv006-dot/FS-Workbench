import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('./assets/business.js',import.meta.url),'utf8');
const dates=source.slice(source.indexOf('function todayStr()'),source.indexOf('/* 切换项目',source.indexOf('function todayStr()')));
const handler=source.slice(source.indexOf('period.onchange='),source.indexOf('  const ha =',source.indexOf('period.onchange=')));
function run(now,value='yesterday'){
 class Clock extends Date{static now(){return new Date(now).getTime();}}
 const c={Date:Clock,pad:n=>String(n).padStart(2,'0'),period:{value},IH:false,CUSTOM:null,RANGE:30,HCUSTOM:null,HRANGE:24,refresh(){},renderToolbar(){},workspaceSync(){}};
 vm.runInNewContext(dates+handler,c);c.period.onchange();return c;
}
for(const [now,day] of [['2026-10-09T07:00:00Z','2026-10-08'],['2026-10-08T15:59:59Z','2026-10-07'],['2026-10-08T16:00:00Z','2026-10-08'],['2026-01-01T00:00:00Z','2025-12-31'],['2024-03-01T00:00:00Z','2024-02-29']]){
 const c=run(now);assert.equal(c.CUSTOM.start,day);assert.equal(c.CUSTOM.end,day);
}
assert.equal(run('2026-10-09T07:00:00Z','today').CUSTOM.start,'2026-10-09');
assert.equal(run('2026-10-09T07:00:00Z','7').RANGE,7);
assert(source.includes("{k:'yesterday',l:'昨日'}"));
assert(source.includes("cst&&!isOn({k:'today'})&&!isOn({k:'yesterday'})"));
assert(source.includes("r==='today'?todayStr():yesterdayStr()"));
console.log('10 yesterday/date-boundary and existing-preset checks passed');
