// Real active renderer and lifecycle; all API values below are fictional test data.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),base=fs.existsSync(path.join(root,'baseline/runtime.js'))?path.join(root,'baseline'):path.join(__dirname,'fixtures'),source=path.join(root,'source');
const metric=value=>({value,status:value===null?'not_provided':'available',unit:'percent',source:'primary',field:'利润率'});
const seed={b_profile:'RS',b_group:'general',b_grain:'day',b_range:'yesterday',b_metrics:'core'};
const catalogId='catalog-0123456789abcdef',profiles={RS:{key:'RS',name:'RS',primary:{filters:{gid:'506',tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}},FC27:{key:'FC27',name:'FC27',primary:{filters:{gid:'1322',tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}}};
const catalog={schemaVersion:2,catalogId,snapshotId:catalogId,scopeContractId:'all-websites-order-primary-admin-supplement-v1',timezone:'Asia/Shanghai',profiles,dashboard:{profiles:Object.fromEntries(Object.keys(profiles).map(k=>[k,{name:k,series:[],hourly:[],coverage:{from:'2025-10-24',to:'2026-10-24'}}])),groups:[{key:'general',label:'综合游戏',profiles:['RS']},{key:'sports',label:'球类',profiles:['FC27']} ]}};
const queries=[];let deny=false;
function reply(q){
 const rs={rs_site:q.get('rs_site')||'all',rs_server:q.get('rs_server')||'all',rs_category:q.get('rs_category')||'all'};
 const amount=({all:1000,rsorders:200,rsmalls:300,rsfast:400,mmoexp:0}[rs.rs_site])/ (rs.rs_category==='all'?1:10),count=amount?4:0;
 const key=q.get('profile'),query=Object.fromEntries(q);delete query.mode;
 const period={start:q.get('start')+' 00:00',end:'2026-10-24 00:00'},when='2026-10-24T07:00:00+00:00';
 if(q.get('mode')==='profit-history'){
  const row={profileKey:key,date:q.get('start'),scope:{sites:'all-websites',orderGameId:key==='RS'?'506':'1322',orderProductType:'',orderStatus:''},profitMarginPct:20,orders:4,revenueUsd:amount,status:'available',capturedAt:when};
  if(key==='RS')Object.assign(row,{sourceContract:'order-shipping-rs-v1',currency:'CNY',scope:{sites:rs.rs_site==='all'?'all-websites':'www.'+rs.rs_site+'.com',orderGameId:'506',orderProductType:({all:'-1',currency:'1',package:'4',items:'2'})[rs.rs_category],orderStatus:'-1',orderAreaId:({all:'0',rs3:'12370',oldschool:'12368'})[rs.rs_server]},profitMarginPct:amount?23.23:null,salesCny:amount*7,profitCny:amount*2,costCny:amount*5,revenueUsd:null});
  return {schemaVersion:1,status:'available',catalogId,query,history:{schemaVersion:2,contractId:'order-native-daily-margin-v2',snapshotId:catalogId,daily:[row]}};
 }
 const dims={countries:[{code:'US',name:'United States',orders:count,revenueUsd:amount}],payments:[{name:'paypal',orders:count,revenueUsd:amount}],devices:[{name:'PC',orders:count,revenueUsd:amount}],channels:[{name:rs.rs_site==='all'?'www.rsorders.com':'www.'+rs.rs_site+'.com',orders:count,revenueUsd:amount}]};
 const common={status:'available',period,capturedAt:when,currency:'USD',sourceDataAsOf:null,rows:count?[{date:q.get('start')+' 01:00',orders:count,amount}]:[],seriesGranularity:'day-or-hour',labelsVerified:true};
 const supplement={...common,rsSelection:rs,scopeLabel:Object.values(rs).join(' · '),normalisedScope:'rs-selected',filters:{game:'506'},metrics:Object.fromEntries(['orders','revenueUsd','newCustomers','payingCustomers','repeatRatePct'].map(k=>[k,{...metric(k==='revenueUsd'?amount:k==='repeatRatePct'?20:count),scope:'所选范围'}])),dimensions:dims};
 const primary={...common,normalisedScope:'all-websites',filters:{gid:key==='RS'?'506':'1322',tid:'',status:''},metrics:{profitMarginPct:metric(20)},dimensions:{},scopeLabel:'Order 全部网站参考'};
 if(key==='RS')Object.assign(primary,{currency:'CNY',sourceContract:'order-shipping-rs-v1',rsSelection:rs,metrics:{profitMarginPct:metric(amount?23.23:null),profitCny:metric(amount*2),shippingSalesCny:metric(amount*7),shippingCostCny:metric(amount*5)}});
 return {schemaVersion:1,status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',query,profile:{key,name:key,period,primary,supplement,metrics:primary.metrics,dimensions:{}},rangeId:'a'.repeat(64),baseSnapshotId:catalogId,generatedAt:when,expiresInSeconds:7200,refreshSeconds:7200,stale:false,cachePolicy:'historical',sources:{Admin:{status:'available',capturedAt:when},Order:{status:'available',capturedAt:when}}};
}
const boot=`import {lifecycle} from '/runtime.js'; import {mount} from '/business.js'; const host=document.getElementById('app'); let restored=false; const seed=${JSON.stringify(seed)}; const scope=lifecycle(host,q=>{if(!restored&&window.api){restored=window.api.apply(seed);}window.lastState=q;},()=>{}); scope.seed=seed;for(const name of ['fs-ui.css','native-alias.css','business.css']){const style=document.createElement('style');style.textContent=await(await fetch('/'+name)).text();scope.root.append(style);}const template=document.createElement('template');template.innerHTML=await(await fetch('/business.html')).text();scope.root.append(template.content);window.api=mount(scope);window.scope=scope;`;
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname==='/dashboard/fs-home/range.json'){
  queries.push(Object.fromEntries(u.searchParams));res.setHeader('Content-Type','application/json');
  if(deny){res.writeHead(403);res.end('{}');return;}
  const value=u.searchParams.get('mode')==='catalog'?catalog:reply(u.searchParams);
  const delay=u.searchParams.get('mode')==='summary'&&u.searchParams.get('rs_site')==='rsmalls'?450:0;
  setTimeout(()=>res.end(JSON.stringify(value)),delay);return;
 }
 if(u.pathname==='/__auth/verify'){res.writeHead(200,{'X-Auth-Groups':'dashboard','X-Auth-User':'fictional-test'});res.end();return;}
 if(u.pathname==='/boot.js'){res.setHeader('Content-Type','text/javascript');res.end(boot);return;}
 const file={'/fs-tokens.css':path.join(base,'fs-tokens.css'),'/fs-ui.css':path.join(base,'fs-ui.css'),'/native-alias.css':path.join(base,'native-alias.css'),'/runtime.js':path.join(base,'runtime.js'),'/business.html':path.join(base,'business.html'),'/business.css':path.join(base,'business.css'),'/business.js':path.join(source,process.env.RS_VARIANT||'business.js')}[u.pathname];
 if(file){res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));return;}
 res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="zh-CN" data-theme="light"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RS 交互验收 · 模拟数据</title><link rel="stylesheet" href="/fs-tokens.css"><body class="fs-ui-page" style="margin:0;padding:20px;background:var(--fs-bg);font-family:var(--fs-font)"><p style="margin:0 0 16px;padding:10px;background:var(--fs-brand-soft)">RS适配离线验收 · 本页全部为模拟数据</p><div id="app" class="native-content" data-theme="light"></div><script type="module" src="/boot.js"></script></body></html>');
});
async function start(){await new Promise(r=>server.listen(0,'127.0.0.1',r));return 'http://127.0.0.1:'+server.address().port;}
module.exports={start,server};
if(require.main===module)(async()=>{
 const url=await start(),browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});await page.goto(url);
  const site=page.locator('#rs_site'),category=page.locator('#rs_category'),area=page.locator('#rs_server'),core=page.locator('#supplement-insights .fsi-metric');
  await site.waitFor({state:'visible'});await page.waitForFunction(()=>window.lastState?.phase==='available');
  assert.equal(await category.isVisible(),true);assert.equal(await area.isVisible(),false);assert.equal(await site.inputValue(),'all');
  await site.selectOption('rsorders');await page.waitForFunction(()=>window.lastState?.phase==='available'&&window.lastState?.b_rs_site==='rsorders');
  await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metric:nth-child(2) strong')?.textContent==='$200.00');
  assert.match(await core.nth(1).innerText(),/200\.00/);assert.match(await page.locator('#geoRank').innerText(),/200/);
  await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metric:nth-child(3) strong')?.textContent==='¥400.00');
  assert.match(await core.nth(2).innerText(),/Order发货统计/);assert.match(await core.nth(3).innerText(),/23\.2/);
  assert.match(await page.locator('#kpisProfit').innerText(),/¥400\.00/);
  await page.locator('[data-profit-day]').waitFor();assert.match(await page.locator('#lblProfit').innerText(),/Order发货统计/);
  await category.selectOption('items');await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metric:nth-child(2) strong')?.textContent==='$20.00');
  assert.ok(queries.some(q=>q.mode==='summary'&&q.rs_site==='rsorders'&&q.rs_category==='items'));
  await site.selectOption('rsmalls');await site.selectOption('rsfast');await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metric:nth-child(2) strong')?.textContent==='$40.00');
  await page.waitForTimeout(650);assert.match(await core.nth(1).innerText(),/40\.00/);assert.doesNotMatch(await core.nth(1).innerText(),/30\.00/);
  await site.selectOption('mmoexp');await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metric:nth-child(2) strong')?.textContent==='$0.00');
  assert.match(await core.nth(2).innerText(),/¥0\.00/);assert.doesNotMatch(await core.nth(3).innerText(),/23\.2/);
  await site.selectOption('rsorders');await category.selectOption('all');await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metric:nth-child(2) strong')?.textContent==='$200.00');
  for(const theme of ['light','dark']){await page.locator('#app').evaluate((e,t)=>{e.dataset.theme=t;e.ownerDocument.documentElement.dataset.theme=t;},theme);assert.equal(await site.isVisible(),true);assert.notEqual(await core.nth(0).evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');}
  await page.locator('#app').evaluate(e=>{e.dataset.theme='light';e.ownerDocument.documentElement.dataset.theme='light';});
  fs.mkdirSync(path.join(root,'../docs/planning/rs-business-adapter-20261024/evidence'),{recursive:true});
  await page.screenshot({path:path.join(root,'../docs/planning/rs-business-adapter-20261024/evidence/rs-preview.png'),fullPage:false});
  await page.setViewportSize({width:390,height:844});assert.equal(await site.isVisible(),true);assert.equal(await category.isVisible(),true);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),'page must fit narrow viewport');
  await page.evaluate(()=>window.api.apply({b_profile:'FC27',b_group:'sports',b_grain:'day',b_range:'yesterday'}));await page.waitForFunction(()=>window.lastState?.b_profile==='FC27');
  assert.equal(await page.locator('#rs-filters').isVisible(),false);assert.ok(queries.filter(q=>q.profile==='FC27').every(q=>!('rs_site' in q)));
  assert.deepEqual(errors,[]);console.log('RS native UI: primary site/category controls, collapsed area, scoped cards/dimensions, zero, fast switch, cache, themes, narrow viewport, FC isolation passed');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
