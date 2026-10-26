const test=require('node:test'),assert=require('node:assert/strict'),{create}=require('../../app/seasonal/model-selection.js'),fixture=require('./model-fixture.cjs');
function complete(state){state.select('platform','console');state.select('server','east');state.select('spec','normal');state.setQuantity('20');return state;}
test('no contract, unverified model and ambiguous combinations fail closed',()=>{
  for(const c of [null,{}, {...fixture(),verified:false},{...fixture(),model_ref:{}},{...fixture(),combinations:[fixture().combinations[0],fixture().combinations[0]]}])assert.throws(()=>create(c),/MODEL_OPTIONS_UNAVAILABLE/);
});
test('dependent options and explicit quantity resolve the chosen combination only',()=>{
  const s=create(fixture());assert.equal(s.ready(),false);assert.deepEqual(s.options('server'),[]);assert.throws(()=>s.select('server','east'),/SPEC_INVALID/);
  complete(s);assert.equal(s.line().product_key,'fixture-console-east');assert.equal(s.line().quantity.value,'20');assert.equal(s.line().attributes[0].value_id,'normal');
  s.select('server','west');assert.equal(s.ready(),false);assert.deepEqual(s.choices(),{platform:'console',server:'west'});assert.deepEqual(s.options('spec').map(v=>v.id),['extra']);s.select('spec','extra');s.setQuantity('21');assert.equal(s.ready(),false);s.setQuantity('30');assert.equal(s.line().product_key,'fixture-console-west');
});
test('changes discard quotes, expired and delayed responses are rejected, test prices never become authoritative',async()=>{
  let clock=1000;const s=complete(create(fixture(),{now:()=>clock}));const ticket=s.beginQuote(),quote={quote_id:'fixture-quote',authoritative:true,test_only:false,currency:'USD',total_minor:1234,expires_at:new Date(2000).toISOString()};
  assert.equal(s.acceptQuote(ticket,{...quote,authoritative:false,test_only:true}),false);assert.equal(s.quote(),null);
  assert.equal(s.acceptQuote(ticket,quote),true);s.setQuantity('30');assert.equal(s.quote(),null);assert.equal(s.acceptQuote(ticket,quote),false);
  const current=s.beginQuote();assert.equal(s.acceptQuote(current,quote),true);clock=2000;assert.equal(s.quote(),null);assert.equal(s.acceptQuote(current,quote),false);
  const pending=s.beginQuote();s.select('platform','desktop');await Promise.resolve();assert.equal(s.acceptQuote(pending,quote),false);
});
