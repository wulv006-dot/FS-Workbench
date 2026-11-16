import test from 'node:test';
import assert from 'node:assert/strict';
import {makeCouponUsage} from '../analytics/coupon-usage.mjs';

const params=(extra={})=>new URLSearchParams({activity:'fc27-trio',mode:'live',from:'2026-11-16',to:'2026-11-16',...extra});
const body=(changes={})=>({status:'available',activity_id:'fc27-season2',basis:'activity_coupon_use_log',coupon:{coupon_id:'1395',issued_total:16,used_total:4},
 totals:{used_orders:3,paid_orders:2,refunded_orders:0,unpaid_orders:1,paid_usd_minor:17502,discount_usd_minor:1508,repurchase_orders:0,repurchase_usd_minor:0,unique_buyers:2},
 daily:[],conversion:{claim_to_use:0.25},coverage:{complete:true},...changes});

test('any FC page reads the one shared coupon, with the exact backend request',async()=>{
 const seen=[];const usage=makeCouponUsage(async request=>{seen.push(request);return body();});
 for(const activity of ['fc27-weekly','fc27-trio','fc27-sbc','fc27-season2']){const r=await usage(params({activity,refresh:'1'}));assert.equal(r.status,200);}
 assert.deepEqual(seen[0],{action:'coupon_usage',site_id:'266',from:'2026-11-16',to:'2026-11-16',activity:'fc27-season2'});
 assert.equal(seen.length,4,'refresh=1 always reads again');
});

test('filters that are not exactly a live FC window are rejected before any read',async()=>{
 let calls=0;const usage=makeCouponUsage(()=>{calls++;return body();});
 for(const [key,val] of [['mode','test'],['activity','mmoexp-seasonal'],['activity','all'],['to','2026-11-31'],['from','2026-01-01'],['refresh','2'],['code','FCSCOUT10'],['game','1327']]){
  const p=params();p.set(key,val);assert.equal((await usage(p)).status,400,key+'='+val);}
 const reversed=params({from:'2026-11-17',to:'2026-11-16'});assert.equal((await usage(reversed)).status,400);
 assert.equal(calls,0);
});

test('a result is cached for ten minutes and then read again',async()=>{
 let now=1000,calls=0;const usage=makeCouponUsage(async()=>{calls++;return body();},()=>now);
 await usage(params());await usage(params());assert.equal(calls,1);
 now+=599999;await usage(params());assert.equal(calls,1);now+=2;await usage(params());assert.equal(calls,2);
});

test('an incomplete or mismatched result is unavailable and never zero or cached',async()=>{
 for(const bad of [{coverage:{complete:false}},{status:'partial'},{coupon:{coupon_id:'1241',issued_total:1,used_total:0}},{totals:{used_orders:-1}},{totals:{}},{daily:null},{activity_id:'mmoexp-seasonal'}]){
  let calls=0;const usage=makeCouponUsage(async()=>{calls++;return body(bad);});
  const r=await usage(params());assert.equal(r.status,502,JSON.stringify(bad));assert.equal(r.body.status,'unavailable');assert.match(r.body.message,/不记为零/);
  await usage(params());assert.equal(calls,2,'failure is not cached');
 }
 const down=makeCouponUsage(()=>{throw Error('BACKEND_UNAVAILABLE');});const r=await down(params());
 assert.equal(r.status,502);assert.equal(r.body.reason,'BACKEND_UNAVAILABLE');
 const odd=await makeCouponUsage(()=>{throw Error('some raw upstream text with details');})(params());assert.equal(odd.body.reason,'COUPON_SOURCE_UNAVAILABLE');
});

test('the same window shares one read and a different window waits instead of queueing',async()=>{
 let release,calls=0;const usage=makeCouponUsage(()=>{calls++;return new Promise(r=>release=r);});
 const first=usage(params()),second=usage(params());
 const other=await usage(params({from:'2026-11-15'}));assert.equal(other.status,503);
 release(body());assert.equal((await first).status,200);assert.equal((await second).status,200);assert.equal(calls,1);
});
