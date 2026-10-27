const {test}=require('node:test');
const assert=require('node:assert/strict');
const core=require('../activity-core.js');
const config=require('../catalog.json');
const baseline=require('./fixtures/catalog-baseline.json');
test('published native code pricing shows the 10 percent activity price and never stacks',()=>{
 assert.equal(config.activityPricing.discountPercent,10);assert.deepEqual(config.activityPricing.stackWith,[]);assert.deepEqual(config.activityPricing.mutuallyExclusiveWith,['coupon','points']);assert.equal(config.activityPricing.enabled,true);assert.equal(config.activityPricing.status,'configured');assert.equal(config.activityPricing.promoterUid,'0');
 assert.deepEqual(core.activityPrice(801,config),{amount:721,baseAmount:801,discountAmount:80,percent:10});
 const fixture={activityPricing:{enabled:true,discountPercent:10}};
 for(const value of [1,5,15,68,624,2728,16316])assert.equal(core.activityPrice(value,fixture).amount,Math.floor((value*90+50)/100));
});
test('owned SBC is excluded; isolated arithmetic fixture reduces each selected line once',()=>{
 const route=baseline.sbc.routes[baseline.sbc.defaultId];
 const rows=route.picks.map(id=>core.line(baseline.products[id],'ps'));
 assert.equal(rows.reduce((n,row)=>n+core.activityPrice(row.amount,{activityPricing:{enabled:true,discountPercent:10}}).amount,0),3176);
 rows.unshift(core.line(baseline.products[baseline.sbc.defaultId],'ps'));
 assert.equal(rows.reduce((n,row)=>n+core.activityPrice(row.amount,{activityPricing:{enabled:true,discountPercent:10}}).amount,0),3738);
});
test('invalid discounts and unsafe arithmetic fail instead of displaying fabricated activity amounts',()=>{
 for(const value of [-1,100,NaN,10.5])assert.throws(()=>core.activityPrice(100,{activityPricing:{enabled:true,discountPercent:value}}));
 assert.throws(()=>core.activityPrice(Number.MAX_SAFE_INTEGER,config));
 assert.equal(core.activityPrice(801,{}).amount,801);
});
