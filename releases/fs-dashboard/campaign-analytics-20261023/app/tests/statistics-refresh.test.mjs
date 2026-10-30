import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import os from 'node:os';
import {refreshPlan,runStatisticsRefresh,compactSource,readStatisticsSnapshot} from '../analytics/statistics-refresh.mjs';
const published={release_id:'campaign-preview-16',halloween:{starts_at:'2026-10-27T00:00:00+08:00'},pages:[{page_id:'seasonal-vault',activity_id:'mmoexp-seasonal'}]};
const at=Date.parse('2026-10-30T00:00:00Z'),stamp=new Date(at).toISOString();
const ids=['1327','891','1333','456'],codes=['HWFC08','HWFC10','HWFC15','HWAION08','HWAION10','HWAION15','HWMAPLE08','HWMAPLE10','HWMAPLE15','HWD408','HWD410','HWD415'];
function values(){return {
 traffic:{status:'available',pageRequests:20,observedPageRequests:20,estimatedVisitors:99,coverage:{complete:true,from:'2026-10-20T00:00:00Z',through:stamp},raw:'fixture-ip-secret'},
 behavior:{status:200,body:{status:'available',generatedAt:stamp,report:{visits:5,visitors:3,seasonalTotals:{gameViews:4,revealed:2,selected:2,reviewed:1,cart:1,unconfirmed:0},seasonalGames:[{gameId:'1327',visits:4,revealed:2,selected:2,reviewed:1,cart:1,unconfirmed:0}],raw:'fixture-user-secret'},events:[{email:'fixture@example.invalid'}]}},
 revenue:{status:200,body:{status:'available',generated_at:stamp,coverage:{complete:true},totals:{paid_orders:12,paid_usd_minor:1200},codes:codes.map((code,i)=>({code,game_id:ids[Math.floor(i/3)],off_percent:[8,10,15][i%3],paid_orders:1,paid_usd_minor:100,order_no:'fixture-order-secret'})),paid_currencies:[{currency:'USD',amount:'12.00'}],rawOrders:[{private:'fixture-order-secret'}]}}
};}
function folder(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'stats-refresh-'));t.after(()=>{assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));assert(path.basename(dir).startsWith('stats-refresh-'));fs.rmSync(dir,{recursive:true,force:true});});return dir;}
const read=(dir,slot)=>JSON.parse(fs.readFileSync(path.join(dir,slot+'.json'),'utf8'));
function readers(data=values(),calls={}){return Object.fromEntries(Object.keys(data).map(k=>[k,async()=>{calls[k]=(calls[k]||0)+1;return structuredClone(data[k]);}]));}
test('Beijing slots have exact UTC date windows;08 closes UTC yesterday and later slots catch up once',()=>{
 const p=refreshPlan(published,{},at);assert.equal(p.slot,'2026-10-30T08:00:00+08:00');assert.equal(p.metricTimezone,'UTC');assert.deepEqual(p.windows.map(w=>[w.kind,w.from,w.to]),[['today','2026-10-30','2026-10-30'],['campaign','2026-10-26','2026-10-30'],['yesterday','2026-10-29','2026-10-29']]);
 assert.equal(p.windows[2].endExclusive,'2026-10-30T00:00:00.000Z');assert.equal(p.windows[2].dateIntervalClosed,true);assert.equal(p.windows[0].dateIntervalClosed,false);
 assert.equal(refreshPlan(published,{lastCompleteDailyDate:'2026-10-29'},at+8*3600000).windows.length,2);
 assert.equal(refreshPlan(published,{},at+8*3600000).windows.length,3);
 assert.equal(refreshPlan(published,{lastCompleteDailyDate:'2026-10-29'},at+16*3600000).slot,'2026-10-31T00:00:00+08:00');
});
test('fixed slots replace same-period totals, duplicate success does not reread, only aggregates persist',async t=>{
 const dir=folder(t),calls={},r=readers(values(),calls);let now=at;
 const first=await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now,runId:'first'});assert.equal(first.status,'success');assert.deepEqual(calls,{traffic:3,behavior:3,revenue:3});
 assert.equal((await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now,runId:'duplicate'})).status,'already_completed');assert.equal(calls.traffic,3);
 now+=8*3600000;await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now,runId:'second'});assert.equal(calls.traffic,5);
 assert.deepEqual(fs.readdirSync(dir).sort(),['campaign.json','status.json','today.json','yesterday.json']);
 const today=read(dir,'today');assert.equal(today.sources.revenue.lastSuccess.summary.paidUsdMinor,1200);assert.equal(today.sources.traffic.lastSuccess.summary.estimatedVisitors,null);assert.equal(today.sources.behavior.lastSuccess.summary.sessionVisitors,3);
 const bytes=fs.readdirSync(dir).map(n=>fs.readFileSync(path.join(dir,n),'utf8')).join('');assert(!/fixture-(?:ip|user|order)-secret|fixture@example/.test(bytes));assert(Buffer.byteLength(bytes)<30000);
});
test('partial/failure retain last success with its own window and never become zero or a new-day result',async t=>{
 const dir=folder(t);let now=at;await runStatisticsRefresh({directory:dir,published,readers:readers(),now:()=>now,runId:'good'});
 const previous=read(dir,'today').sources.revenue.lastSuccess,oldRun=read(dir,'status').lastSuccessfulRunAt;
 now+=DAY;const data=values();data.traffic={status:'partial',reason:'LOG_HISTORY_GAP',pageRequests:null,observedPageRequests:2,coverage:{complete:false,from:stamp,through:stamp}};data.revenue={status:502,body:{status:'unavailable'}};
 const result=await runStatisticsRefresh({directory:dir,published,readers:readers(data),now:()=>now,runId:'partial'});assert.equal(result.status,'partial');
 const today=read(dir,'today');assert.equal(today.window.from,'2026-10-31');assert.deepEqual(today.sources.revenue.lastSuccess,previous);assert.equal(today.sources.revenue.lastSuccess.window.from,'2026-10-30');assert.equal(today.sources.revenue.lastAttempt.status,'unavailable');assert.equal(today.sources.traffic.lastAttempt.summary.pageRequests,null);assert.equal(today.sources.traffic.lastAttempt.summary.observedPageRequests,2);assert.equal(read(dir,'status').lastSuccessfulRunAt,oldRun);
});
const DAY=86400000;
test('explicit source access and filter errors remain blocked across adapter envelopes',()=>{
 for(const name of ['behavior','revenue']){
  assert.deepEqual(compactSource(name,{status:502,body:{status:'unavailable',reason:'ADMIN_ACCESS_DENIED'}}),{status:'unavailable',reason:'SOURCE_ACCESS_DENIED',blocked:true});
  assert.equal(compactSource(name,{status:400,body:{status:'invalid'}}).blocked,false);
  assert.equal(compactSource(name,{status:400,body:{status:'invalid',message:'活动未部署到服务端白名单'}}).blocked,true);
  assert.equal(compactSource(name,{status:503,body:{status:'busy'}}).blocked,false);
 }
});
test('a source 400 for one valid window cannot poison yesterday or following today',async t=>{
 const dir=folder(t),seen=[],r=readers();let now=at;r.revenue=async w=>{seen.push(w.kind);return w.kind==='campaign'?{status:400,body:{status:'invalid'}}:values().revenue;};
 await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now});assert.deepEqual(seen,['today','campaign','yesterday']);assert.deepEqual(read(dir,'status').blockedSources,{});
 now+=8*3600000;await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now});assert.deepEqual(seen,['today','campaign','yesterday','today','campaign']);
});
test('over 31 day campaign stays local; same-run yesterday and next-slot today still refresh',async t=>{
 const dir=folder(t),long={...published,halloween:{starts_at:'2026-09-01T00:00:00Z'}},seen=[];let now=at;
 const r=Object.fromEntries(Object.entries(readers()).map(([name,read])=>[name,async w=>{seen.push([name,w.kind]);return read(w);} ]));
 await runStatisticsRefresh({directory:dir,published:long,readers:r,now:()=>now});
 assert.equal(seen.length,6);assert(!seen.some(([,kind])=>kind==='campaign'));assert(seen.some(([,kind])=>kind==='yesterday'));assert.deepEqual(read(dir,'status').blockedSources,{});
 assert.equal(read(dir,'campaign').sources.behavior.lastAttempt.reason,'WINDOW_RANGE_TOO_LARGE');
 now+=8*3600000;await runStatisticsRefresh({directory:dir,published:long,readers:r,now:()=>now});assert.equal(seen.filter(([,kind])=>kind==='today').length,6);assert.deepEqual(read(dir,'status').blockedSources,{});
});
test('snapshot reader returns only matching date/release totals and next Beijing slot without collection',async t=>{
 const dir=folder(t);await runStatisticsRefresh({directory:dir,published,readers:readers(),now:()=>at});
 const v=readStatisticsSnapshot({directory:dir,published,kind:'today',at});assert.equal(v.sources.behavior.lastSuccess.summary.visits,5);assert.equal(v.nextScheduledAt,'2026-10-30T08:00:00.000Z');
 assert.equal(readStatisticsSnapshot({directory:dir,published:{...published,release_id:'changed'},kind:'today',at}).sources.behavior.lastSuccess,null);
 assert.equal(readStatisticsSnapshot({directory:dir,published,kind:'today',at:at+DAY}).sources.behavior.lastSuccess,null);
 assert.equal(readStatisticsSnapshot({directory:dir,published,kind:'yesterday',at}).window.from,'2026-10-29');
 assert.throws(()=>readStatisticsSnapshot({directory:dir,published,kind:'../../secret',at}),/INVALID_SNAPSHOT_SLOT/);
});
test('denied source stops remaining windows and future runs until explicit corrected-source retry',async t=>{
 const dir=folder(t);let now=at,attempts=0;const r=readers();r.behavior=async()=>{attempts++;throw Error('PostHog query returned 403');};
 await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now});assert.equal(attempts,1);assert.equal(read(dir,'status').blockedSources.behavior.reason,'SOURCE_ACCESS_DENIED');
 now+=8*3600000;r.behavior=async()=>{attempts++;return values().behavior;};await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now});assert.equal(attempts,1);
 const corrected=await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>now,retryBlocked:true});assert.equal(corrected.status,'success');assert.equal(attempts,4);assert.deepEqual(read(dir,'status').blockedSources,{});
});
test('new release/config/start never inherits old successes; same identity keeps same-window fallback',async t=>{
 const original={...published,config_hash:'a'.repeat(64)},variants=[
  ['release',{...original,release_id:'campaign-preview-17'}],
  ['config',{...original,config_hash:'b'.repeat(64)}],
  ['start',{...original,halloween:{starts_at:'2026-10-28T00:00:00+08:00'}}],
  ['same',original]
 ];
 for(const [name,next] of variants){
  const dir=folder(t);await runStatisticsRefresh({directory:dir,published:original,readers:readers(),now:()=>at});
  const failed=Object.fromEntries(['traffic','behavior','revenue'].map(k=>[k,async()=>{throw Error('SOURCE_READ_FAILED');}]));
  await runStatisticsRefresh({directory:dir,published:next,readers:failed,now:()=>at+8*3600000});
  const stored=read(dir,'today'),shown=readStatisticsSnapshot({directory:dir,published:next,kind:'today',at:at+8*3600000});
  for(const source of ['traffic','behavior','revenue']){
   assert.equal(!!stored.sources[source].lastSuccess,name==='same',name+' persisted '+source);
   assert.equal(!!shown.sources[source].lastSuccess,name==='same',name+' visible '+source);
  }
  if(name==='same')assert.equal(shown.sources.behavior.lastSuccess.summary.visits,5);
 }
});
test('unknown existing snapshot is preserved, malformed source becomes missing, missing configuration blocks only that source',async t=>{
 const dir=folder(t),file=path.join(dir,'status.json');fs.writeFileSync(file,'{"schemaVersion":2,"keep":true}\n');const before=fs.readFileSync(file);
 await assert.rejects(runStatisticsRefresh({directory:dir,published,readers:readers(),now:()=>at}),/INVALID_SNAPSHOT_FILE/);assert.deepEqual(fs.readFileSync(file),before);
 const other=folder(t),r=readers();r.behavior=async()=>{throw Error('SOURCE_NOT_CONFIGURED');};r.revenue=async()=>({status:200,body:{status:'available',coverage:{complete:false}}});const out=await runStatisticsRefresh({directory:other,published,readers:r,now:()=>at});assert.equal(out.status,'partial');assert.equal(read(other,'today').sources.revenue.lastSuccess,null);assert.equal(read(other,'today').sources.traffic.lastSuccess.summary.pageRequests,20);assert(read(other,'status').blockedSources.behavior);
});
test('only the transiently failed window/source retries; successful traffic and sales are reused',async t=>{
 const dir=folder(t);await runStatisticsRefresh({directory:dir,published,readers:readers(),now:()=>at});
 const calls={},r=readers(values(),calls);let campaignCalls=0;const regular=r.behavior;
 r.behavior=async w=>{if(w.kind==='campaign'&&++campaignCalls===1){calls.behavior=(calls.behavior||0)+1;throw new DOMException('deadline','TimeoutError');}return regular(w);};
 const result=await runStatisticsRefresh({directory:dir,published,readers:r,now:()=>at+8*3600000});assert.equal(result.status,'success');assert.deepEqual(calls,{traffic:2,behavior:3,revenue:2});
 const retry=read(dir,'campaign').sources.behavior.lastAttempt.retry;assert.equal(retry.attemptCount,2);assert.equal(retry.retryCount,1);assert.equal(retry.attempts[0].reason,'SOURCE_TIMEOUT');assert.equal(read(dir,'today').sources.revenue.lastAttempt.retry.retryCount,0);
});
