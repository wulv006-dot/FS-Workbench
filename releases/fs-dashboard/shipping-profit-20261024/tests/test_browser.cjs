// Real active renderer and lifecycle; all API values below are fictional test data.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),base=fs.existsSync(path.join(root,'baseline/runtime.js'))?path.join(root,'baseline'):path.join(__dirname,'fixtures'),source=path.join(root,'source');
const metric=value=>({value,status:value===null?'not_provided':'available',unit:'percent',source:'primary',field:'利润率'});
const seed={b_profile:'MMOEXP',b_group:'mmoexp',b_grain:'day',b_range:'yesterday',b_metrics:'core'};
const catalogId='catalog-0123456789abcdef',profiles={RS:{key:'RS',name:'RS',primary:{filters:{gid:'506',tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}},FC27:{key:'FC27',name:'FC27',primary:{filters:{gid:'1322',tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}}};
for(const [key,gid] of [["MMOEXP", "0"], ["POE2", "552"], ["D4", "456"], ["AION2", "826"], ["FC27", "1322"], ["NBA2K27", "1306"], ["NFL27", "1258"], ["MLB26", "922"], ["CFB27", "1256"], ["FC26", "824"], ["RS", "506"], ["MAPLESTORY_CLASSIC", "1300"], ["ARC_RAIDERS", "864"], ["DARK_AND_DARKER", "588"], ["WOW_FOREVER", "1364"], ["ARENA_BREAKOUT_INFINITE", "836"], ["COD_BO7", "838"]])profiles[key]={key,name:key,primary:{filters:{gid,tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}};
const catalog={schemaVersion:2,catalogId,snapshotId:catalogId,scopeContractId:'all-websites-order-primary-admin-supplement-v1',timezone:'Asia/Shanghai',profiles,dashboard:{profiles:Object.fromEntries(Object.keys(profiles).map(k=>[k,{name:k,series:[],hourly:[],coverage:{from:'2025-10-24',to:'2026-10-24'}}])),groups:[{key:'mmoexp',label:'全局',profiles:['MMOEXP']},{key:'rpg',label:'RPG',profiles:['D4','AION2']},{key:'general',label:'综合游戏',profiles:['RS']},{key:'sports',label:'球类',profiles:['FC27']} ]}};
const queries=[];let deny=false;
function reply(q){
 const rs={rs_site:q.get('rs_site')||'all',rs_server:q.get('rs_server')||'all',rs_category:q.get('rs_category')||'all'};
 const amount=({all:1000,rsorders:200,rsmalls:300,rsfast:400,mmoexp:0}[rs.rs_site])/ (rs.rs_category==='all'?1:10),count=amount?4:0;
 const key=q.get('profile'),site=q.get('profit_site')||'main',cid=q.get('profit_category')||'-1',query=Object.fromEntries(q);delete query.mode;
 if(!profiles[key])throw Error('unhandled fixture query '+q.toString());
 const period={start:q.get('start')+' 00:00',end:'2026-10-24 00:00'},when='2026-10-24T07:00:00+00:00';
 if(q.get('mode')==='profit-history'){
  const row={profileKey:key,date:q.get('start'),scope:{sites:'all-websites',orderGameId:key==='RS'?'506':'1322',orderProductType:'',orderStatus:''},profitMarginPct:20,orders:4,revenueUsd:amount,status:'available',capturedAt:when};
  if(key==='RS')Object.assign(row,{sourceContract:'order-shipping-rs-v1',currency:'CNY',scope:{sites:rs.rs_site==='all'?'all-websites':'www.'+rs.rs_site+'.com',orderGameId:'506',orderProductType:({all:'-1',currency:'1',package:'4',items:'2'})[rs.rs_category],orderStatus:'-1',orderAreaId:({all:'0',rs3:'12370',oldschool:'12368'})[rs.rs_server]},profitMarginPct:amount?23.23:null,salesCny:amount*7,profitCny:amount*2,costCny:amount*5,revenueUsd:null});
  if(key!=='RS')Object.assign(row,{sourceContract:'order-shipping-v1',currency:'CNY',scope:{sites:site==='all'?'all-websites':'www.mmoexp.com',orderGameId:profiles[key].primary.filters.gid,orderProductType:cid,orderStatus:'-1',orderAreaId:'0'},profitMarginPct:cid==='0'?null:cid==='2'?-10:25,salesCny:cid==='0'?0:1000,profitCny:cid==='0'?0:cid==='2'?-100:250,costCny:cid==='0'?0:cid==='2'?1100:750,revenueUsd:null});
  return {schemaVersion:1,status:'available',catalogId,query,history:{schemaVersion:2,contractId:'order-native-daily-margin-v2',snapshotId:catalogId,daily:[row]}};
 }
 const dims={countries:[{code:'US',name:'United States',orders:count,revenueUsd:amount}],payments:[{name:'paypal',orders:count,revenueUsd:amount}],devices:[{name:'PC',orders:count,revenueUsd:amount}],channels:[{name:rs.rs_site==='all'?'www.rsorders.com':'www.'+rs.rs_site+'.com',orders:count,revenueUsd:amount}]};
 const common={status:'available',period,capturedAt:when,currency:'USD',sourceDataAsOf:null,rows:count?[{date:q.get('start')+' 01:00',orders:count,amount}]:[],seriesGranularity:'day-or-hour',labelsVerified:true};
 const supplement={...common,rsSelection:rs,scopeLabel:Object.values(rs).join(' · '),normalisedScope:'rs-selected',filters:{game:'506'},metrics:Object.fromEntries(['orders','revenueUsd','newCustomers','payingCustomers','repeatRatePct'].map(k=>[k,{...metric(k==='revenueUsd'?amount:k==='repeatRatePct'?20:count),scope:'所选范围'}])),dimensions:dims};
 if(key!=='RS'){supplement.filters={game:key==='FC27'?'1327':key==='AION2'?'891':key==='D4'?'456':''};supplement.normalisedScope='all-websites';supplement.metrics.revenueUsd=metric(1000);supplement.metrics.orders=metric(4);supplement.dimensions.channels=[{name:'www.mmoexp.com',orders:4,revenueUsd:1000}];}
 const primary={...common,normalisedScope:'all-websites',filters:{gid:key==='RS'?'506':'1322',tid:'',status:''},metrics:{profitMarginPct:metric(20)},dimensions:{},scopeLabel:'Order 全部网站参考'};
 if(key==='RS')Object.assign(primary,{currency:'CNY',sourceContract:'order-shipping-rs-v1',rsSelection:rs,metrics:{profitMarginPct:metric(amount?23.23:null),profitCny:metric(amount*2),shippingSalesCny:metric(amount*7),shippingCostCny:metric(amount*5)}});
 const shipping=key==='RS'?null:{...common,currency:'CNY',sourceContract:'order-shipping-v1',profileKey:key,scopeLabel:site+' · '+key+' · '+cid,shippingSelection:{site,cid,gid:profiles[key].primary.filters.gid},metrics:{profitMarginPct:cid==='0'?{value:null,status:'not_applicable'}:metric(cid==='2'?-10:25),profitCny:metric(cid==='0'?0:cid==='2'?-100:site==='all'?500:250),shippingSalesCny:metric(cid==='0'?0:1000),shippingCostCny:metric(cid==='0'?0:750)}};
 return {schemaVersion:1,status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',query,profile:{key,name:key,period,primary,supplement,shipping,metrics:primary.metrics,dimensions:{}},rangeId:'a'.repeat(64),baseSnapshotId:catalogId,generatedAt:when,expiresInSeconds:7200,refreshSeconds:7200,stale:false,cachePolicy:'historical',sources:{Admin:{status:'available',capturedAt:when},Order:{status:'available',capturedAt:when}}};
}
const boot=`import {lifecycle} from '/runtime.js'; import {mount} from '/business.js'; const host=document.getElementById('app'); let restored=false; const seed=${JSON.stringify(seed)}; const scope=lifecycle(host,q=>{if(!restored&&window.api){restored=window.api.apply(seed);}window.lastState=q;},()=>{}); scope.seed=seed;for(const name of ['fs-ui.css','native-alias.css','business.css']){const style=document.createElement('style');style.textContent=await(await fetch('/'+name)).text();scope.root.append(style);}const template=document.createElement('template');template.innerHTML=await(await fetch('/business.html')).text();scope.root.append(template.content);window.api=mount(scope);window.scope=scope;`;
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname==='/dashboard/fs-home/range.json'){
  queries.push(Object.fromEntries(u.searchParams));res.setHeader('Content-Type','application/json');
  if(u.searchParams.get('mode')==='fc-daily'){res.writeHead(503);res.end('{}');return;}
  if(deny){res.writeHead(403);res.end('{}');return;}
  const value=u.searchParams.get('mode')==='catalog'?catalog:reply(u.searchParams);
  const delay=u.searchParams.get('mode')==='summary'&&u.searchParams.get('rs_site')==='rsmalls'?450:0;
  setTimeout(()=>res.end(JSON.stringify(value)),delay);return;
 }
 if(u.pathname==='/dashboard/channel-effects/data.json'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({status:'available',revenueBasis:'admin_order_cny',period:{start:'2026-10-23',end:'2026-10-23'},generatedAt:'2026-10-24T07:00:00Z',sources:{cost:{generatedAt:'2026-10-24T07:01:00Z'}},denominator:{orders:4,completedOrders:3,coveredOrders:2,missingCostOrders:1,legacyRevenueOrders:0,pendingOrders:1,saleCny:100,costCny:70,profitCny:30,margin:.3}}));return;}
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
  const category=page.locator('#shipping-category'),core=page.locator('#supplement-insights > .fsi-metrics > .fsi-metric'),separate=page.locator('[data-procurement-independent]');
  await category.waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metrics > .fsi-metric:nth-child(3) strong')?.textContent==='¥250.00');
  assert.match(await core.nth(1).innerText(),/1,000.00/);assert.match(await core.nth(2).innerText(),/Order发货统计/);assert.match(await core.nth(3).innerText(),/25.00/);
  await separate.waitFor();assert.match(await separate.innerText(),/¥30/);assert.match(await separate.innerText(),/覆盖/);assert.equal(await core.count(),15);
  await page.locator('[data-profit-day]').waitFor();assert.match(await page.locator('#lblProfit').innerText(),/Order发货统计/);
  await category.selectOption('2');await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metrics > .fsi-metric:nth-child(3) strong')?.textContent==='¥-100.00');
  assert.match(await core.nth(3).innerText(),/-10.00/);assert.match(await core.nth(1).innerText(),/1,000.00/);assert.match(await separate.innerText(),/¥30/);
  await page.getByRole('combobox',{name:'参考展示范围'}).selectOption('all');await category.selectOption('-1');await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metrics > .fsi-metric:nth-child(3) strong')?.textContent==='¥500.00');
  assert.equal(await separate.count(),0);assert.ok(queries.some(q=>q.mode==='summary'&&q.profit_site==='all'&&q.profit_category==='-1'));
  await category.selectOption('0');await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metrics > .fsi-metric:nth-child(3) strong')?.textContent==='¥0.00');assert.match(await core.nth(3).innerText(),/不适用/);
  for(const key of ['D4','AION2','FC27']){
   await page.evaluate(k=>window.api.apply({b_profile:k,b_group:k==='FC27'?'sports':'rpg',b_grain:'day',b_range:'yesterday',b_profit_category:'-1',b_profit_site:'main'}),key);
   await page.waitForFunction(k=>window.lastState?.b_profile===k&&window.lastState?.phase==='available',key);await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metrics > .fsi-metric:nth-child(3) strong')?.textContent==='¥250.00');
   if(key==='FC27'){await page.locator('[data-profit-day]').waitFor({state:'visible'});assert.equal(await separate.locator('.fsi-metric').first().isVisible(),true);}
  }
  assert.ok(queries.some(q=>q.mode==='profit-history'&&q.profile==='FC27'&&q.profit_site==='main'));assert.ok(queries.filter(q=>q.mode==='fc-detail').every(q=>!('profit_site'in q)));
  await page.evaluate(()=>window.api.apply({b_profile:'RS',b_group:'general',b_grain:'day',b_range:'yesterday',b_rs_site:'rsorders',b_rs_category:'all'}));await page.waitForFunction(()=>window.lastState?.b_profile==='RS'&&window.lastState?.phase==='available');
  assert.equal(await category.isVisible(),false);await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fsi-metrics > .fsi-metric:nth-child(3) strong')?.textContent==='¥400.00');
  assert.ok(queries.filter(q=>q.profile==='RS').every(q=>!('profit_site'in q)));
  for(const theme of ['light','dark'])await page.locator('#app').evaluate((e,t)=>{e.dataset.theme=t;e.ownerDocument.documentElement.dataset.theme=t;},theme);
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
  console.log('Unified shipping UI: global/game/site/category/daily rates, zero/loss, separate same-order margin, FC daily, RS regression and themes/narrow viewport passed');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
