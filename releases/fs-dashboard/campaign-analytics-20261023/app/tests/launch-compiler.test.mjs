import test from 'node:test';import assert from 'node:assert/strict';import {verifyDiscountReadbacks} from '../analytics/launch-compiler.mjs';import {compileDiscountPlan} from '../analytics/discount-plan.mjs';
const plan=compileDiscountPlan({activity_id:'synthetic',code:'TESTCODE10',game_ids:['1327'],off_percent:10,starts_at:'2026-10-27 00:00:00',ends_at:'2026-11-10 23:59:59',repeat_qty:0});
test('launch assembly requires one matching independently read-back native code per plan',()=>{
 assert.throws(()=>verifyDiscountReadbacks([plan],null),{code:'DISCOUNT_READBACK_REQUIRED'});
 const receipt={status:'readback_verified',evidence_ref:'synthetic-only',records:[structuredClone(plan.fields)]};assert.doesNotThrow(()=>verifyDiscountReadbacks([plan],receipt));
 const nativeDecimals=structuredClone(receipt);nativeDecimals.records[0].discount='90.00';nativeDecimals.records[0].attain='0.00';assert.doesNotThrow(()=>verifyDiscountReadbacks([plan],nativeDecimals));
 for(const change of [{discount:'90.01'},{attain:'0.01'},{discount:'9e1'},{discount:' 90.00'},{discount:''}]){const bad=structuredClone(nativeDecimals);Object.assign(bad.records[0],change);assert.throws(()=>verifyDiscountReadbacks([plan],bad),{code:'DISCOUNT_READBACK_SCOPE_MISMATCH'});}
 assert.equal(plan.fields.uid,0);
 for(const [key,value] of Object.entries({discount:'10',uid:739116,site_id:267,gid:['0'],exclude_gids:['1327'],timeend:'2026-11-11 23:59:59',status:0,aid:21587})){
  const bad=structuredClone(receipt);bad.records[0][key]=value;assert.throws(()=>verifyDiscountReadbacks([plan],bad),{code:'DISCOUNT_READBACK_SCOPE_MISMATCH'});
 }
 receipt.records.push(structuredClone(plan.fields));assert.throws(()=>verifyDiscountReadbacks([plan],receipt),{code:'DISCOUNT_READBACK_AMBIGUOUS'});
});
