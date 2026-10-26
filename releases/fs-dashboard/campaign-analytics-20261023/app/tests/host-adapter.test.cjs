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

test('native cart timeout covers a hanging response body and leaves an unknown receipt without retry',async()=>{
 const handoff=require('../native-code-handoff.js'),native={category:'new_items',id:'900059',group:'1',num:'1',attr:'',aid:'21587'},selection={activity_id:'fc27-season2',page_id:'fc27-weekly',off_percent:10,lines:[{product_key:'synthetic59',quantity:{value:'1',unit:'item'},attributes:[]}]};
 const snapshot={release_id:'synthetic59',config_hash:'synthetic59',pages:[{activity_id:'fc27-season2',page_id:'fc27-weekly',active:true,product_keys:['synthetic59']}],products:[{key:'synthetic59',product_ref:{site_id:'266',game_id:'1327',goods_id:'900059'},platform:{attribute_id:'21587'},quantity:{min:'1',max:'1',step:'1',unit:'item',group:'1'},attributes:[]}],native_checkout:{status:'configured',verification_ref:'synthetic59',valid_from:'2020-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z',origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,bindings:[{...selection.lines[0],activity_id:selection.activity_id,page_id:selection.page_id,off_percent:10,code:'SYNTHETIC59',native}]}};
 let timeout,startedBody,posts=0;const bodyStarted=new Promise(resolve=>startedBody=resolve),cleared=[];
 const window={location:{origin:'https://www.mmoexp.com'},FCActivityCore:core,CampaignNativeCodeHandoff:handoff,fetch:async(_url,{signal})=>{posts++;return {ok:true,json:()=>new Promise((_resolve,reject)=>{signal.addEventListener('abort',()=>reject(Error('synthetic response-body AbortError')),{once:true});startedBody();})};}};
 vm.runInNewContext(source,{window,AbortController,URLSearchParams,setTimeout(callback,delay){assert.equal(delay,15000);timeout=callback;return 'synthetic-timer';},clearTimeout:id=>cleared.push(id)});
 const approved=handoff.publishedPlan(snapshot,selection,{origin:window.location.origin}),batch=window.FCActivityHost.createNative(snapshot,selection).batch(),running=batch.run(approved.items);
 await bodyStarted;assert.deepEqual(cleared,[],'headers alone must not cancel the response-body deadline');timeout();
 const rows=await running;assert.equal(rows.length,1);assert.equal(rows[0].state,'unknown');assert.deepEqual(cleared,['synthetic-timer']);assert.equal(posts,1);
 await assert.rejects(batch.run(approved.items),/already started/);assert.equal(posts,1);
});
