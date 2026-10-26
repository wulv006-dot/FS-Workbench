const {test}=require('node:test');
const assert=require('node:assert/strict');
const {coinsPayload}=require('../activity-core.js');
const selected={origin:'https://www.mmoexp.com',region:'us',currency:'USD',model_id:'41217957',goods_id:'163329311',platform:'ps',quantity:'1000',unit:'K'};
test('observed Coins tier serializes paid group, not bonus or base-unit multiplication',()=>{
 const payload=coinsPayload(selected);
 assert.equal(new URLSearchParams(payload).toString(),'category=new_gold&id=163329311&group=1000&num=1&attr=&aid=');
 assert.equal(Object.hasOwn(payload,'price'),false);
});
test('unobserved region, currency, SKU, quantity and platform cannot inherit Coins evidence',()=>{
 for(const [field,value] of Object.entries({origin:'https://47.85.224.112',region:'uk',currency:'GBP',model_id:'other',goods_id:'163329277',platform:'xbox',quantity:'1050',unit:'coins'}))assert.throws(()=>coinsPayload({...selected,[field]:value}),/unverified/);
 for(const quantity of ['1000000',1000,'1'])assert.throws(()=>coinsPayload({...selected,quantity}),/unverified/);
});
