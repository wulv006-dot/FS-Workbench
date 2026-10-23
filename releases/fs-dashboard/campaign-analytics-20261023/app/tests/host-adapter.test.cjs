const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const config=require('./fixtures/catalog-baseline.json');
const core=require('../activity-core.js');
const fixture=require('./fixtures/cisse-live-catalog.json');
const source=fs.readFileSync(require.resolve('../host-adapter.js'),'utf8');
function setup(origin='https://www.mmoexp.com'){
 const calls=[],window={location:{origin},FCActivityCore:core,langPageUrl:path=>'/en'+path,GV:{valuta:{code:'USD',sign:'$',rate:2}},js_rate:(price,a,b,c,d,currency)=>'$'+(price*(b||100)/100*(currency?.rate??2)).toFixed(2),parseDisplayAmount:text=>Number(text.slice(1))};
 vm.runInNewContext(source,{window,AbortController,setTimeout,clearTimeout,URLSearchParams,fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>url==='/ajax/goods'?fixture:{code:1}};}});
 return {window,calls};
}
test('host adapter refuses live cart creation away from the real site',()=>{
 const {window}=setup('http://127.0.0.1:8520');assert.throws(()=>window.FCActivityHost.create(config));
});
test('activity pricing cannot silently use the old full-price cart before backend integration',()=>{
 const {window,calls}=setup();assert.throws(()=>window.FCActivityHost.create({...config,activityPricing:{enabled:true,discountPercent:10}}));assert.equal(calls.length,0);
});
test('catalog stays unprefixed; cart uses the existing language helper and native currency helpers',async()=>{
 const {window,calls}=setup(),host=window.FCActivityHost.create(config),item=core.line(config.products['185916875'],'ps');
 const [fresh]=await host.quote([item]);assert.equal(calls[0].url,'/ajax/goods');
 assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.headers['X-Requested-With'],'XMLHttpRequest');
 assert.equal(host.display(fresh).amount,1602);assert.equal(host.total(1602),'$16.02');
 assert.equal(host.cartUrl,'/en/Cart.html');
 const rows=await host.batch().run([fresh]);assert.equal(rows[0].state,'confirmed');assert.equal(calls[1].url,'/en/Cart/add.html');
 assert.equal(calls[1].options.body.get('id'),'185916875');
});
