const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../app/seasonal');
function setup({enabled=true,code,unknown=false}={}){
  const calls=[],messages=[],client={pending:unknown?{unknown:true,operation_id:'original-id'}:null,capabilities:{integration_mode:'preview'},load:async()=>({config:{seasonal_theme:'christmas'}}),describe:()=> 'Preview only',select:async lines=>{calls.push(lines);if(code)throw {code};return {quote:{status:'integration_test_quoted'}};},lookup:async()=>{calls.push('lookup-original-id');return {status:'unknown'};},prepare:async()=>{throw {code:'MAIN_INTEGRATION_REQUIRED'};}};
  const context={window:{CampaignStandalone:{enabled:()=>enabled,create:()=>client},dispatchEvent:()=>{}},document:{documentElement:{}},CustomEvent:class {constructor(type,opts){this.type=type;this.detail=opts.detail;}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'campaign-data.js'),'utf8'),context);context.window.SeasonalData=context.SeasonalData;
  vm.runInContext(fs.readFileSync(path.join(root,'runtime-bridge.js'),'utf8'),context);
  return {bridge:context.window.SeasonalCommerce,client,calls,messages,report:m=>messages.push(m)};
}
test('package order quantity excludes free bonus and original unit remains exact',()=>{
  const {bridge}=setup();const lines=bridge.lines([{id:'fc-1'},{id:'poe-1'}]);
  assert.equal(lines[0].product_key,'seasonal-fc-1');assert.equal(lines[0].quantity.value,'100');assert.equal(lines[0].quantity.unit,'K');assert.equal(lines[1].quantity.unit,'');assert.equal(lines[0].attributes.length,0);
});
test('untrusted preview performs no request and promises no real reward',async()=>{
  const x=setup({enabled:false});await x.bridge.run('quote',[{id:'fc-1'}],x.report);assert.equal(x.calls.length,0);assert.match(x.messages.at(-1),/no cart, discount or reward was changed/);
});
test('required specs fail closed; unknown operation uses lookup without new intent',async()=>{
  const x=setup({code:'SPEC_REQUIRED'});await x.bridge.run('quote',[{id:'fc-1'}],x.report);assert.match(x.messages.at(-1),/requires product specifications/);
  const y=setup({unknown:true});await y.bridge.run('quote',[{id:'fc-1'}],y.report);assert.equal(y.calls.length,0);await y.bridge.run('lookup',[],y.report);assert.deepEqual(y.calls,['lookup-original-id']);assert.match(y.messages.at(-1),/pending or unknown/);
});
test('lookup reports recovered quote and definitive result without permanent unknown state',async()=>{
  const x=setup({unknown:true});
  x.client.load=async()=>{throw {code:'PAGE_UNAVAILABLE'};};
  x.client.lookup=async()=>{x.client.pending={stage:'quoted',unknown:false};return {quote:{status:'integration_test_quoted'}};};
  await x.bridge.run('lookup',[],x.report);assert.match(x.messages.at(-1),/Original selection recovered: integration_test_quoted/);assert.equal(x.bridge.pending(),false);
  x.client.lookup=async()=>{x.client.pending={stage:'resolved',unknown:false,resolved:true};return {status:'integration_test_result'};};
  await x.bridge.run('lookup',[],x.report);assert.match(x.messages.at(-1),/Original operation resolved/);assert.equal(x.bridge.pending(),false);
});
test('known preview integration refusal is not presented as uncertain',async()=>{
  const x=setup({code:'MAIN_INTEGRATION_REQUIRED'});await x.bridge.run('quote',[{id:'fc-1'}],x.report);assert.match(x.messages.at(-1),/Main-site cart integration is still required/);assert.doesNotMatch(x.messages.at(-1),/pending or unknown/);
});
test('legacy response status cannot inject an internal language into public messages',async()=>{
  const x=setup();x.client.select=async()=>({quote:{status:'\u5185\u90e8\u72b6\u6001'}});
  await x.bridge.run('quote',[{id:'fc-1'}],x.report);assert.match(x.messages.at(-1),/Server response: unknown/);assert.doesNotMatch(x.messages.at(-1),/\p{Script=Han}/u);
});
test('known campaign schedule refusals explain quote and prepare failure without suggesting a retry',async()=>{
  for(const [code,message] of [['PROMOTION_NOT_STARTED',/has not started yet/],['PROMOTION_EXPIRED',/is paused or has ended/]]){
    const quote=setup({code});await quote.bridge.run('quote',[{id:'fc-1'}],quote.report);
    assert.match(quote.messages.at(-1),message);assert.equal(quote.calls.length,1);
    const prepare=setup();let prepares=0;prepare.client.prepare=async()=>{prepares++;throw {code};};
    await prepare.bridge.run('prepare',[],prepare.report);assert.match(prepare.messages.at(-1),message);
    assert.equal(prepares,1);assert.equal(prepare.calls.length,0);
    for(const text of [quote.messages.at(-1),prepare.messages.at(-1)]){
      assert.doesNotMatch(text,/could not verify|pending or unknown|Review a new quote|Integration test result/);
      assert.match(text,/Checkout is (?:unavailable|no longer available)/);
    }
  }
});
test('PROMOTION_EXPIRED also represents an inactive page and does not assert that its end time elapsed',async()=>{
  const x=setup({code:'PROMOTION_EXPIRED'});await x.bridge.run('quote',[{id:'fc-1'}],x.report);
  assert.equal(x.messages.at(-1),'This published activity is paused or has ended. Checkout is unavailable for this offer.');
});
test('an unresolved original operation keeps priority over campaign schedule error messages',async()=>{
  for(const code of ['PROMOTION_NOT_STARTED','PROMOTION_EXPIRED']){
    const x=setup({code});x.client.select=async lines=>{x.calls.push(lines);x.client.pending={unknown:true,operation_id:'original-id'};throw {code};};
    await x.bridge.run('quote',[{id:'fc-1'}],x.report);assert.match(x.messages.at(-1),/original operation is pending or unknown/i);
    const y=setup({unknown:true});y.client.prepare=async()=>{throw {code};};await y.bridge.run('prepare',[],y.report);
    assert.match(y.messages.at(-1),/original operation is pending or unknown/i);
    for(const text of [x.messages.at(-1),y.messages.at(-1)]){assert.match(text,/do not submit it again/);assert.doesNotMatch(text,/has not started yet|has ended/);}
  }
});
