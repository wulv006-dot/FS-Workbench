import test from 'node:test';import assert from 'node:assert/strict';
import {retryAfterMs,transientFailure,retrySource} from '../analytics/statistics-retry.mjs';
const failed=reason=>({status:'unavailable',reason}),good={status:'available',data:{visits:5}};
function clock(){let t=0;const waits=[];return {now:()=>t,advance:n=>t+=n,waits,sleep:async ms=>{waits.push(ms);t+=ms;}};}
test('transient classifier is allowlisted, Retry-After parses seconds and HTTP date safely',()=>{
 assert.equal(transientFailure(new DOMException('private text','TimeoutError')).reason,'SOURCE_TIMEOUT');
 assert.equal(transientFailure(Object.assign(Error('fetch failed'),{cause:{code:'ECONNRESET'}})).reason,'SOURCE_NETWORK_ECONNRESET');
 for(const status of [408,429,500,502,503,504])assert.equal(transientFailure(Error('PostHog query returned '+status)).reason,'SOURCE_HTTP_'+status);
 for(const message of ['SOURCE_READ_FAILED','LOG_HISTORY_GAP','LOG_READ_LIMIT','INVALID_AGGREGATE','PostHog query returned 401','PostHog query returned 403','SOURCE_HTTP_400'])assert.equal(transientFailure(Error(message)),null,message);
 assert.equal(transientFailure(Object.assign(Error('fetch failed'),{cause:{code:'ENOTFOUND'}})),null);
 assert.equal(retryAfterMs('7'),7000);assert.equal(retryAfterMs('Thu, 01 Jan 1970 00:00:09 GMT',1000),8000);
 assert.equal(retryAfterMs('0'),0);for(const value of ['bad','1.5','-1',''])assert.equal(retryAfterMs(value),null);
 assert(Number.isFinite(retryAfterMs('9'.repeat(400))));
});
test('one failure recovers, strictly sequential attempts and successful read never repeats',async()=>{
 const c=clock();let calls=0,active=0,max=0;
 const result=await retrySource(async()=>{active++;max=Math.max(max,active);calls++;c.advance(10);await Promise.resolve();active--;return calls===1?failed('SOURCE_TIMEOUT'):good;},{deadline:60000,attemptTimeoutMs:15000,clock:c.now,sleep:c.sleep});
 assert.equal(result.status,'available');assert.equal(calls,2);assert.equal(max,1);assert.deepEqual(c.waits,[2000]);assert.equal(result.retry.retryCount,1);assert.equal(result.retry.elapsedMs,2020);
 const once=await retrySource(async()=>{calls++;return good;},{deadline:60000,attemptTimeoutMs:15000,clock:c.now,sleep:c.sleep});assert.equal(once.retry.attemptCount,1);assert.equal(calls,3);
});
test('continuous failure stops at three, sleeps 2s then 5s, retains classified final reason',async()=>{
 const c=clock();let calls=0;const r=await retrySource(async()=>{calls++;c.advance(15000);return failed('SOURCE_TIMEOUT');},{deadline:100000,attemptTimeoutMs:15000,clock:c.now,sleep:c.sleep});
 assert.equal(calls,3);assert.deepEqual(c.waits,[2000,5000]);assert.equal(r.reason,'SOURCE_TIMEOUT');assert.equal(r.retry.stopReason,'attempt_limit');assert.equal(r.retry.elapsedMs,52000);
});
test('429 respects Retry-After and total budget; never clamps a long wait into an early retry',async()=>{
 const c=clock();let calls=0;const r=await retrySource(async()=>{calls++;return calls===1?{...failed('SOURCE_HTTP_429'),retryAfterMs:9000}:good;},{deadline:60000,attemptTimeoutMs:15000,clock:c.now,sleep:c.sleep});assert.equal(r.status,'available');assert.deepEqual(c.waits,[9000]);
 const d=clock();calls=0;const limited=await retrySource(async()=>{calls++;return {...failed('SOURCE_HTTP_429'),retryAfterMs:70000};},{deadline:60000,attemptTimeoutMs:15000,clock:d.now,sleep:d.sleep});assert.equal(calls,1);assert.deepEqual(d.waits,[]);assert.equal(limited.retry.stopReason,'run_budget');
});
test('unknown, permission, filter and partial gaps only attempt once',async()=>{
 for(const result of [failed('SOURCE_READ_FAILED'),{...failed('SOURCE_ACCESS_DENIED'),blocked:true},failed('WINDOW_FILTER_INVALID'),{status:'partial',reason:'LOG_HISTORY_GAP'}]){
  const c=clock();let calls=0;const r=await retrySource(async()=>{calls++;return result;},{deadline:60000,attemptTimeoutMs:15000,clock:c.now,sleep:c.sleep});assert.equal(calls,1);assert.deepEqual(c.waits,[]);assert.equal(r.retry.stopReason,'not_retryable');
 }
});
test('budget reserves source timeout; expired budget skips calls and cannot start a late retry',async()=>{
 const c=clock();let calls=0;const r=await retrySource(async()=>{calls++;c.advance(15000);return failed('SOURCE_TIMEOUT');},{deadline:17000,attemptTimeoutMs:15000,clock:c.now,sleep:c.sleep});assert.equal(calls,1);assert.equal(r.retry.stopReason,'run_budget');assert.deepEqual(c.waits,[]);
 const none=await retrySource(async()=>{throw Error('must not run');},{deadline:100,attemptTimeoutMs:15000,clock:c.now,sleep:c.sleep});assert.equal(none.retry.attemptCount,0);assert.equal(none.reason,'RUN_TIME_BUDGET_EXHAUSTED');
});
test('day/config context change during wait or successful response blocks old result and later calls',async()=>{
 for(const where of ['sleep','response']){const c=clock();let current=true,calls=0;
  const r=await retrySource(async()=>{calls++;if(where==='response'){current=false;return good;}return failed('SOURCE_TIMEOUT');},{deadline:60000,attemptTimeoutMs:15000,clock:c.now,sleep:async ms=>{await c.sleep(ms);current=false;},isCurrent:()=>current});assert.equal(calls,1);assert.equal(r.reason,'SOURCE_CONTEXT_CHANGED');assert.equal(r.status,'unavailable');assert.equal(r.data,undefined);
 }
});
