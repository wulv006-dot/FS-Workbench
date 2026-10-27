import test from 'node:test';import assert from 'node:assert/strict';import {compileDiscountPlan} from '../analytics/discount-plan.mjs';
const draft=()=>({activity_id:'fc27-weekly',code:'FCSCOUT10',game_ids:['1327'],off_percent:10,starts_at:'2026-10-26 00:00:00',ends_at:'2027-10-25 23:59:59',repeat_qty:0});
test('observed Admin field compiler uses payable percentage, scoped games and promoter attribution',()=>{
 for(const [off,percent] of [[8,'92'],[10,'90'],[15,'85']]){const p=compileDiscountPlan({...draft(),off_percent:off});assert.equal(p.fields.discount,percent);assert.equal(p.fields.uid,739116);assert.deepEqual(p.fields.gid,['1327']);assert.equal(p.fields.repeat_qty,0);assert.equal(p.validation.created,false);assert.equal(p.validation.server_timezone_verified,false);}
});
test('missing dates, invalid codes, all-game scope and collisions fail before any candidate write',()=>{
 for(const change of [{code:'fs-lower'}, {game_ids:['0']},{game_ids:[]},{off_percent:90},{starts_at:'2026-02-30 00:00:00'},{ends_at:null},{repeat_qty:-1}])assert.throws(()=>compileDiscountPlan({...draft(),...change}));
 assert.throws(()=>compileDiscountPlan(draft(),{existingCodes:[{code:'fcscout10'}]}),{code:'DISCOUNT_CODE_EXISTS_RECONCILE'});
});
test('multiple scoped games do not send a stale single-area restriction',()=>{assert.equal('aid' in compileDiscountPlan({...draft(),game_ids:['1327','891']}).fields,false);});
