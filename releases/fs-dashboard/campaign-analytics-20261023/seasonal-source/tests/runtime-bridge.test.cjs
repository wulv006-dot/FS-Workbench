const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../app/seasonal');
function setup({enabled=true,code,unknown=false}={}){
  const calls=[],messages=[],client={pending:unknown?{unknown:true,operation_id:'original-id'}:null,capabilities:{integration_mode:'preview'},load:async()=>({config:{seasonal_theme:'christmas'}}),describe:()=> 'Preview only',select:async lines=>{calls.push(lines);if(code)throw {code};return {quote:{status:'integration_test_quoted'}};},lookup:async()=>{calls.push('lookup-original-id');return {status:'unknown'};},prepare:async()=>{throw {code:'MAIN_INTEGRATION_REQUIRED'};}};
  const context={window:{CampaignStandalone:{enabled:()=>enabled,create:()=>client},dispatchEvent:()=>{}},document:{documentElement:{}},CustomEvent:class {constructor(type,opts){this.type=type;this.detail=opts.detail;}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'campaign-data.js'),'utf8'),context);context.window.SeasonalData=context.SeasonalData;
  vm.runInContext(fs.readFileSync(path.join(root,'runtime-bridge.js'),'utf8'),context);
  return {bridge:context.window.SeasonalCommerce,calls,messages,report:m=>messages.push(m)};
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
