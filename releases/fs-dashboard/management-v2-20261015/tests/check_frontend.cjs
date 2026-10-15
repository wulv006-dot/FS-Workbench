const assert=require('assert'),fs=require('fs'),path=require('path');
const app=require('../source/frontend/management-live.js');
assert.equal(app.fmt(null),'—');assert.equal(app.ratio(1,0),null);assert.equal(app.sum([1,null]),null);assert.equal(app.sum([1,2]),3);
assert.equal(app.today(new Date('2026-10-15T16:00:00Z')),'2026-10-16');
const facts={contract:'fs-management-daily-v2',snapshotId:'management-'+'a'.repeat(24),businessDate:'2026-10-15',timezone:'Asia/Shanghai',projects:[{profile:'FC27'}]};
const a={status:'succeeded',snapshotId:facts.snapshotId,businessDate:'2026-10-15',validUntil:'2026-10-16T00:00:00+08:00'};
assert(app.adviceValid(a,facts,new Date('2026-10-15T10:00:00Z')));assert(!app.adviceValid(a,facts,new Date('2026-10-15T16:00:00Z')));assert(!app.adviceValid({...a,snapshotId:'old'},facts,new Date('2026-10-15T10:00:00Z')));
assert(app.validSnapshot(facts));assert(!app.validSnapshot({...facts,projects:[{profile:'FC27'},{profile:'FC27'}]}));
assert.equal(app.health({month:{values:{rev:null}},targets:{rev:100}},40),'unknown');
assert(!app.esc('<script>"').includes('<'));
for(const f of fs.readdirSync(path.join(__dirname,'../source/frontend')).filter(x=>x.endsWith('.html'))){const s=fs.readFileSync(path.join(__dirname,'../source/frontend',f),'utf8');assert(!s.includes('__gate'));assert(!s.includes('atob('));assert(!s.includes('DEFAULT_PW'));assert(s.includes('data-management-v2'));}
console.log('management frontend: expiry, scope, nulls, rendering shells and no demo gate PASS');
(async()=>{
 let calls=0;const old={version:'old'},fresh={version:'new'},loader=async()=>{calls++;return fresh},hash=async x=>x.version;
 assert.equal((await app.ensureTargetVersion(old,'old','old',loader,hash)).config,old);assert.equal(calls,0);
 assert.equal((await app.ensureTargetVersion(old,'old','new',loader,hash)).config,fresh);assert.equal(calls,1);
 await assert.rejects(()=>app.ensureTargetVersion(old,'old','different',loader,hash),/版本不一致/);assert.equal(old.version,'old');
 console.log('management target rollover: stale config reload and mismatch rejection PASS');
})().catch(e=>{console.error(e);process.exitCode=1});

assert(app.metricNote({month:{notes:{new:'Admin 主站'}}},'new').includes('原统计范围参考'));
