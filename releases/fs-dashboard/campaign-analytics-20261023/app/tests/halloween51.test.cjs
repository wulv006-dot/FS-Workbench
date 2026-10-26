const test=require('node:test'),assert=require('node:assert/strict');
const {create,defaultPrice}=require('../seasonal/model-selection.js');
const config=require('../seasonal/halloween-config.json');
const now=()=>1000;
function catalog(){return {schema_version:1,verified:true,catalog_version:'synthetic-v1',model_ref:{site_id:'266',game_id:'test-game',model_id:'test-model'},ordering_verified:true,ordering_evidence:'synthetic-only',fields:[{id:'server',depends_on:[],values:[{id:'first'},{id:'second'}]}],combinations:['first','second'].map((server,i)=>({product_key:'synthetic-'+server,attributes:[],choices:{server},quantity:{min:'1',max:'10',step:'1',unit:'item'},price:{source:'admin_current',base_minor:10000+i*5000,currency:'USD',minor_unit_scale:2,quantity_value:'1',expires_at:'2099-01-01T00:00:00Z'}}))};}
test('Four games, one fixed plus two random, no invented odds/products/window',()=>{
 assert.deepEqual(config.games.map(g=>g.id),['fc','aion','wow','maplestory']);
 assert.deepEqual(config.off_percent_tiers,[8,15,10]);assert.equal(config.wishing_pool,false);
 assert.equal(config.probabilities,null);assert.equal(config.tier_product_binding,null);assert.equal(config.starts_at,null);assert.equal(config.ends_at,null);
 for(const game of config.games){assert.equal(game.fixed_model,null);assert.deepEqual(game.random_models,[]);assert.equal(game.random_count,2);}
});
test('First source-ordered combination, correct discount direction, not authoritative',()=>{
 for(const [off,total] of [[8,9200],[15,8500],[10,9000]]){
  const price=defaultPrice(catalog(),off,{now});assert.equal(price.product_key,'synthetic-first');assert.equal(price.indicative_discounted_minor,total);assert.equal(price.authoritative,false);
 }
 const input=catalog();input.combinations.reverse();assert.equal(defaultPrice(input,10,{now}).base_minor,15000);
});
test('No guessing ordering, prices, quantity, or fallback to another server',()=>{
 for(const mutate of [x=>x.ordering_verified=false,x=>delete x.ordering_evidence,x=>delete x.combinations[0].price,x=>x.combinations[0].price.expires_at='invalid',x=>x.combinations[0].price.quantity_value='0']){
  const input=catalog();mutate(input);assert.throws(()=>defaultPrice(input,10,{now}));
 }
 assert.throws(()=>defaultPrice(catalog(),20,{now}));
});
test('Changing actual server invalidates prior quote; stale response is rejected',()=>{
 const s=create(catalog(),{now});s.select('server','first');s.setQuantity('1');const ticket=s.beginQuote();
 const response={authoritative:true,quote_id:'synthetic-q',currency:'USD',total_minor:9000,expires_at:'2099-01-01T00:00:00Z'};
 assert.equal(s.acceptQuote(ticket,response),true);s.select('server','second');s.setQuantity('1');assert.equal(s.quote(),null);assert.equal(s.acceptQuote(ticket,response),false);
});
test('Selected combination price changes without multiplying unverified quantity tiers',()=>{
 const {selectedPrice}=require('../seasonal/model-selection.js'),input=catalog(),s=create(input,{now});s.select('server','second');s.setQuantity('1');assert.equal(selectedPrice(input,s,10,{now}).indicative_discounted_minor,13500);s.setQuantity('2');assert.throws(()=>selectedPrice(input,s,10,{now}),/CURRENT_PRICE_UNAVAILABLE/);
});
