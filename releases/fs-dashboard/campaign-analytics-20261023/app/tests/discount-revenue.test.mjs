import test from 'node:test';
import assert from 'node:assert/strict';
import {makeDiscountRevenue} from '../analytics/discount-revenue.mjs';
const params=()=>new URLSearchParams({activity:'mmoexp-seasonal',mode:'live',from:'2026-10-30',to:'2026-10-30',game:'all'});
test('paid orders use separate 600s cache, exact request, refresh and no failures as zero',async()=>{
 let now=1000,calls=0,fail=false;
 const report=makeDiscountRevenue(async request=>{calls++;assert.deepEqual(request,{action:'discount_revenue',site_id:'266',from:'2026-10-30',to:'2026-10-30',game:'all'});if(fail)throw Error('UPSTREAM_UNAVAILABLE');return {status:'available',coverage:{complete:true},totals:{paid_orders:2,paid_usd_minor:30725}};},()=>now);
 assert.equal((await report(params())).body.totals.paid_orders,2);await report(params());assert.equal(calls,1);
 now+=600000;await report(params());assert.equal(calls,2);
 const force=params();force.set('refresh','1');await report(force);assert.equal(calls,3);
 fail=true;const failed=await report(force);assert.equal(failed.status,502);assert.equal(failed.body.status,'unavailable');assert.equal(failed.body.totals,undefined);
});
test('test data, arbitrary codes, invalid dates never read production orders',async()=>{
 let calls=0;const report=makeDiscountRevenue(()=>{calls++;throw Error('must not read')});
 for(const [key,val] of [['mode','test'],['code','OTHER'],['activity','all'],['to','2026-11-31'],['game','0'],['from','2026-01-01']]){const p=params();p.set(key,val);assert.equal((await report(p)).status,400);}
 assert.equal(calls,0);
});
test('same-window callers coalesce; sync errors release pending state',async()=>{
 let resolve,calls=0;const report=makeDiscountRevenue(()=>{calls++;return new Promise(r=>resolve=r)});
 const a=report(params()),b=report(params());await Promise.resolve();assert.equal(calls,1);
 resolve({status:'available',coverage:{complete:true}});assert.equal((await a).status,200);assert.equal((await b).status,200);
 const broken=makeDiscountRevenue(()=>{throw Error('UPSTREAM_UNAVAILABLE')});assert.equal((await broken(params())).status,502);assert.equal((await broken(params())).status,502);
});
