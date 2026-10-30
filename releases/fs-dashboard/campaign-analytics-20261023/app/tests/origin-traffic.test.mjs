import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {gzipSync} from 'node:zlib';
import {makeOriginTraffic,originRange} from '../analytics/origin-traffic.mjs';

const clock=Date.parse('2026-10-30T12:00:00Z');
const params=(from='2026-10-30',to=from)=>new URLSearchParams({activity:'mmoexp-seasonal',from,to});
const line=(time='30/Oct/2026:08:00:00 +0800',url='/events/seasonal/index.html',method='GET',status=200,ua='Fixture browser')=>`192.0.2.7 - - [${time}] "${method} ${url} HTTP/1.1" ${status} 321 "https://www.mmoexp.com/" "${ua}" "198.51.100.2"\n`;
const anchor=line('30/Oct/2026:07:59:59 +0800','/health');
function fixture(t,body='',options={}){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'origin-traffic-')),logPath=path.join(dir,'access.log');fs.writeFileSync(logPath,body);t.after(()=>{assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));assert(path.basename(dir).startsWith('origin-traffic-'));fs.rmSync(dir,{recursive:true,force:true});});return {dir,logPath,query:makeOriginTraffic({logPath,now:()=>clock,...options})};}

test('only document GET200; UTC dates, exclusions, repeated refreshes and no identity/query export',async t=>{
 const same=line('30/Oct/2026:08:00:02 +0800');
 const f=fixture(t,anchor+line()+line('30/Oct/2026:08:00:01 +0800','/events/seasonal/?secret=fixture-query')+same+same+line(undefined,undefined,'GET',200,'Googlebot')+line(undefined,'/events/seasonal/index.html?analytics_test=1')+line(undefined,'/events/seasonal/event.js')+line(undefined,'/events/api/campaign/config')+line(undefined,undefined,'HEAD')+line(undefined,undefined,'POST')+line(undefined,undefined,'GET',499)+line(undefined,'/events/seasonal/index.html/utm_source=bad'));
 const r=await f.query(params());assert.equal(r.status,'available');assert.equal(r.pageRequests,4);assert.equal(r.successfulRequests,6);assert.equal(r.excludedRequests,2);assert.equal(r.estimatedVisitors,null);assert.equal(r.daily[0].date,'2026-10-30');assert.equal(r.daily[0].requests,4);
 assert(!/192\.0\.2|198\.51\.100|fixture-query|Fixture browser|access\.log/.test(JSON.stringify(r)));
});
test('a genuine zero is distinct from empty, missing, malformed, unsafe or oversized logs',async t=>{
 const zero=fixture(t,anchor+line(undefined,'/health'));assert.equal((await zero.query(params())).pageRequests,0);
 for(const body of ['',anchor+'not a complete log format\n']){const f=fixture(t,body);const r=await f.query(params());assert.equal(r.pageRequests,null);assert.notEqual(r.status,'available');}
 const limited=fixture(t,anchor+line(),{maxFileBytes:10});assert.equal((await limited.query(params())).reason,'LOG_READ_LIMIT');
 const absent=fixture(t);fs.unlinkSync(absent.logPath);assert.equal((await absent.query(params())).reason,'LOG_NOT_AVAILABLE');
 const linked=fixture(t);fs.unlinkSync(linked.logPath);fs.mkdirSync(linked.logPath+'.real');fs.symlinkSync(linked.logPath+'.real',linked.logPath,'junction');assert.equal((await linked.query(params())).reason,'UNSAFE_LOG_FILE');
});
test('partial history never becomes a full-period zero and cached returned objects are isolated',async t=>{
 const f=fixture(t,line());const r=await f.query(params('2026-10-29','2026-10-30'));assert.equal(r.status,'partial');assert.equal(r.pageRequests,null);assert.equal(r.observedPageRequests,1);
 r.daily[0].requests=999;assert.equal((await f.query(params('2026-10-29','2026-10-30'))).daily[0].requests,1);
});
test('reads sequential gzip rotations and deduplicates hard-link and byte-identical aliases',async t=>{
 for(const alias of ['hard-link','copy']){
  const f=fixture(t,line('30/Oct/2026:10:00:00 +0800'));
  if(alias==='hard-link')fs.linkSync(f.logPath,f.logPath+'.1');else fs.copyFileSync(f.logPath,f.logPath+'.1');
  fs.writeFileSync(f.logPath+'.2.gz',gzipSync(anchor+line('30/Oct/2026:08:01:00 +0800')));
  const r=await f.query(params());assert.equal(r.status,'available',alias);assert.equal(r.pageRequests,2,alias);
 }
});
test('overlapping snapshots, missing rotations, gzip limits and incomplete final lines stay incomplete',async t=>{
 const overlap=fixture(t,line('30/Oct/2026:10:00:00 +0800'));fs.writeFileSync(overlap.logPath+'.1',anchor+line('30/Oct/2026:10:00:01 +0800'));assert.equal((await overlap.query(params())).reason,'OVERLAPPING_LOG_SNAPSHOTS');assert.equal((await overlap.query(params())).pageRequests,null);
 const gap=fixture(t,line('30/Oct/2026:09:00:00 +0800'));fs.writeFileSync(gap.logPath+'.2',anchor);assert.equal((await gap.query(params())).reason,'LOG_ROTATION_GAP');
 const gzip=fixture(t,line('30/Oct/2026:09:00:00 +0800'),{maxBytes:600,maxFileBytes:1000});fs.writeFileSync(gzip.logPath+'.1.gz',gzipSync(anchor.repeat(20)));assert.equal((await gzip.query(params())).reason,'LOG_READ_LIMIT');
 const unfinished=fixture(t,anchor+line().trimEnd());const r=await unfinished.query(params());assert.equal(r.reason,'INCOMPLETE_LOG_LINE');assert.equal(r.pageRequests,null);
});
test('cache TTL and explicit refresh; inode replacement invalidates cache without double-counting',async t=>{
 let time=clock;const f=fixture(t,anchor+line(),{now:()=>time,ttlMs:600000});
 assert.equal((await f.query(params())).pageRequests,1);fs.appendFileSync(f.logPath,line());assert.equal((await f.query(params())).pageRequests,1);
 time+=600001;assert.equal((await f.query(params())).pageRequests,2);fs.appendFileSync(f.logPath,line());const force=params();force.set('refresh','1');assert.equal((await f.query(force)).pageRequests,3);
 fs.renameSync(f.logPath,f.logPath+'.1');fs.writeFileSync(f.logPath,anchor+line());assert.equal((await f.query(params())).pageRequests,1);
});
test('rejects invalid dates, future-only ranges, other activities and over31days before reading',async()=>{
 for(const p of [params('2026-02-30'),params('2026-10-31'),params('2026-09-01','2026-10-30'),new URLSearchParams({activity:'all',from:'2026-10-30',to:'2026-10-30'})])assert.throws(()=>originRange(p,clock),/INVALID_TRAFFIC_RANGE/);
});
test('concurrent UTC-day and full-period queries remain isolated; period requests sum, never IP visitors',async t=>{
 const f=fixture(t,line('29/Oct/2026:07:59:59 +0800','/health')+line('29/Oct/2026:08:10:00 +0800')+line('30/Oct/2026:08:10:00 +0800'));
 const [a,b,c]=await Promise.all([f.query(params('2026-10-29')),f.query(params('2026-10-29','2026-10-30')),f.query(params())]);
 assert.deepEqual([a.pageRequests,b.pageRequests,c.pageRequests],[1,2,1]);assert.deepEqual(b.daily.map(r=>r.requests),[1,1]);assert([a,b,c].every(r=>r.estimatedVisitors===null));
});
