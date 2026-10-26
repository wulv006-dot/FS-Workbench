const assert=require('node:assert/strict');
const {referenceLines,pageToUnit}=require('../source/fc27-quote-cloud.js');
const ref={anchor_usd:'9.30',sources:{ItemD2R:{status:'unavailable',reason:'missing'}},raw_offset:'0',raw_weighted_usd:'9.30'};
for(const level of ['normal','warning','urgent']){
 const lines=referenceLines({reference_adjustment:ref,position_policy_version:'fc-owner-position-20261026-v1',position_ceiling_usd:'9.30',margin_review:{level}},{});
 assert(lines.some(r=>r[0]==='品牌定位上限'&&r[1].includes('$9.30')));
 assert(lines.some(r=>r[0]==='平均毛利复核'&&r[1].length>0));
}
assert(!referenceLines({reference_adjustment:ref},{}).some(r=>r[0]==='品牌定位上限'));
assert.equal(pageToUnit('7.39'),'0.0739');
console.log('8 UI assertions passed');
