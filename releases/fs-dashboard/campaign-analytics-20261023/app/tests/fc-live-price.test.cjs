const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const core=require('../activity-core.js');
const config=require('../catalog.json');
const source=fs.readFileSync(require.resolve('../host-adapter.js'),'utf8');
const key=config.weekly.ids[0];
const line=()=>core.line(config.products[key],'ps');
const row=(title=config.products[key].title,over={})=>({id:line().offer.id,aid:21587,cid:config.products[key].cid,gid:1327,title,status:1,auto_off:0,has_sku:false,min_qty:1,num:1,price_discount_format:'1.32',saleprop:[],...over});
function setup(origin='https://www.mmoexp.com',rows=[row()]){
 const calls=[],window={location:{origin},FCActivityCore:core,fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({goods:{index:{list:rows,perpage:20,total:rows.length}}})};}};
 vm.runInNewContext(source,{window,AbortController,setTimeout,clearTimeout,URLSearchParams,Intl});
 return {window,calls};
}
test('live price is limited to the existing site origin and its same-origin catalog route',()=>{
 const offsite=setup('http://127.0.0.1:8520');
 assert.throws(()=>offsite.window.FCActivityHost.createLivePrice(config),/existing MMOEXP origin/);
 const {window}=setup();
 assert.throws(()=>window.FCActivityHost.createLivePrice({...config,api:{...config.api,catalog:'https://admin.example/goods'}}),/same-origin catalog route/);
 assert.throws(()=>window.FCActivityHost.createLivePrice({...config,activityPricing:{enabled:true}}),/not configured/);
});
test('platform selection reads the current main-store price and projects the 10 percent activity price',async()=>{
 const {window,calls}=setup(),host=window.FCActivityHost.createLivePrice(config);
 const [quoted]=await host.quote([line()]);
 assert.equal(calls.length,1);assert.equal(calls[0].url,'/ajax/goods');
 assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.headers['X-Requested-With'],'XMLHttpRequest');
 const body=calls[0].options.body;
 assert.equal(body.get('site_id'),'266');assert.equal(body.get('Game_id'),'1327');assert.equal(body.get('aid'),'21587');assert.equal(body.get('category_id'),'9627');
 assert.equal(quoted.amount,132);
 assert.deepEqual(JSON.parse(JSON.stringify(host.display(quoted))),{text:'$1.19',amount:119,baseAmount:132,discountAmount:13,currency:'USD'});
});
test('a retitled live listing stays in scope only while the pinned player and platform still match',async()=>{
 let {window}=setup('https://www.mmoexp.com',[row(config.products[key].title+' (TOTW)')]);
 assert.equal((await window.FCActivityHost.createLivePrice(config).quote([line()]))[0].amount,132);
 ({window}=setup('https://www.mmoexp.com',[row('Someone Else/85/ST++/Team of the Week')]));
 await assert.rejects(()=>window.FCActivityHost.createLivePrice(config).quote([line()]),/scope or availability changed/);
 ({window}=setup('https://www.mmoexp.com',[row(config.products[key].title,{aid:21585})]));
 await assert.rejects(()=>window.FCActivityHost.createLivePrice(config).quote([line()]),/scope or availability changed/);
 ({window}=setup('https://www.mmoexp.com',[row(config.products[key].title,{auto_off:10})]));
 await assert.rejects(()=>window.FCActivityHost.createLivePrice(config).quote([line()]),/scope or availability changed/);
});
test('an unreadable live price never fabricates a zero amount',async()=>{
 const {window}=setup('https://www.mmoexp.com',[row(config.products[key].title,{price_discount_format:'0.00'})]);
 await assert.rejects(()=>window.FCActivityHost.createLivePrice(config).quote([line()]),/Invalid current offer/);
});
