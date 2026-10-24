// Real active renderer and lifecycle; all API values below are fictional test data.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),base=fs.existsSync(path.join(root,'baseline/runtime.js'))?path.join(root,'baseline'):path.join(__dirname,'fixtures'),source=path.join(root,'source');
const metric=value=>({value,status:value===null?'not_provided':'available',unit:'percent',source:'primary',field:'利润率'});
const seed={b_profile:'MMOEXP',b_group:'mmoexp',b_grain:'day',b_range:'yesterday',b_metrics:'core'};
const catalogId='catalog-0123456789abcdef',profiles={RS:{key:'RS',name:'RS',primary:{filters:{gid:'506',tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}},FC27:{key:'FC27',name:'FC27',primary:{filters:{gid:'1322',tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}}};
for(const [key,gid] of [["MMOEXP", "0"], ["POE2", "552"], ["D4", "456"], ["AION2", "826"], ["FC27", "1322"], ["NBA2K27", "1306"], ["NFL27", "1258"], ["MLB26", "922"], ["CFB27", "1256"], ["FC26", "824"], ["RS", "506"], ["MAPLESTORY_CLASSIC", "1300"], ["ARC_RAIDERS", "864"], ["DARK_AND_DARKER", "588"], ["WOW_FOREVER", "1364"], ["ARENA_BREAKOUT_INFINITE", "836"], ["COD_BO7", "838"]])profiles[key]={key,name:key,primary:{filters:{gid,tid:'',status:''},normalisedScope:'all-websites'},supplement:{},period:{start:'2025-10-24 00:00',end:'2026-10-24 16:00'}};
const catalog={schemaVersion:2,catalogId,snapshotId:catalogId,scopeContractId:'all-websites-order-primary-admin-supplement-v1',timezone:'Asia/Shanghai',profiles,dashboard:{profiles:Object.fromEntries(Object.keys(profiles).map(k=>[k,{name:k,series:[],hourly:[],coverage:{from:'2025-10-24',to:'2026-10-24'}}])),groups:[{key:'mmoexp',label:'全局',profiles:['MMOEXP']},{key:'rpg',label:'RPG',profiles:['D4','AION2']},{key:'general',label:'综合游戏',profiles:['RS']},{key:'sports',label:'球类',profiles:['FC27']} ]}};
const queries=[];let deny=false,refreshRevision=0;
function reply(q){
 const rs={rs_site:q.get('rs_site')||'all',rs_server:q.get('rs_server')||'all',rs_category:q.get('rs_category')||'all'};
 const amount=({all:1000,rsorders:200,rsmalls:300,rsfast:400,mmoexp:0}[rs.rs_site])/ (rs.rs_category==='all'?1:10),count=amount?4:0;
 const key=q.get('profile'),site=q.get('profit_site')||'main',cid=q.get('profit_category')||'-1',query=Object.fromEntries(q);delete query.mode;
 if(!profiles[key])throw Error('unhandled fixture query '+q.toString());
 const period={start:q.get('start')+' 00:00',end:'2026-10-24 00:00'},when='2026-10-24T07:00:00+00:00';
 if(q.get('mode')==='rs-backlog')return {contractId:'rs-current-backlog-v1',basis:'current_no_payment_date_filter',selection:rs,asOf:'2026-10-25T00:00:00Z',metrics:{issues:{status:'available',value:3},unpaid:{status:'available',value:7}}};
 if(q.get('mode')==='profit-history'){
  const row={profileKey:key,date:q.get('start'),scope:{sites:'all-websites',orderGameId:key==='RS'?'506':'1322',orderProductType:'',orderStatus:''},profitMarginPct:20,orders:4,revenueUsd:amount,status:'available',capturedAt:when};
  if(key==='RS')Object.assign(row,{sourceContract:'order-shipping-rs-v1',currency:'CNY',scope:{sites:rs.rs_site==='all'?'all-websites':'www.'+rs.rs_site+'.com',orderGameId:'506',orderProductType:({all:'-1',currency:'1',package:'4',items:'2'})[rs.rs_category],orderStatus:'-1',orderAreaId:({all:'0',rs3:'12370',oldschool:'12368'})[rs.rs_server]},profitMarginPct:amount?23.23:null,salesCny:amount*7,profitCny:amount*2,costCny:amount*5,revenueUsd:null});
  if(key!=='RS')Object.assign(row,{sourceContract:'order-shipping-v1',currency:'CNY',scope:{sites:site==='all'?'all-websites':'www.mmoexp.com',orderGameId:profiles[key].primary.filters.gid,orderProductType:cid,orderStatus:'-1',orderAreaId:'0'},profitMarginPct:cid==='0'?null:cid==='2'?-10:25,salesCny:cid==='0'?0:1000,profitCny:cid==='0'?0:cid==='2'?-100:250,costCny:cid==='0'?0:cid==='2'?1100:750,revenueUsd:null});
  return {schemaVersion:1,status:'available',catalogId,query,history:{schemaVersion:2,contractId:'order-native-daily-margin-v2',snapshotId:catalogId,daily:[row]}};
 }
 const dims={countries:[{code:'US',name:'United States',orders:count,revenueUsd:amount}],payments:[{name:'paypal',orders:count,revenueUsd:amount}],devices:[{name:'PC',orders:count,revenueUsd:amount}],channels:[{name:rs.rs_site==='all'?'www.rsorders.com':'www.'+rs.rs_site+'.com',orders:count,revenueUsd:amount}]};
 const common={status:'available',period,capturedAt:when,currency:'USD',sourceDataAsOf:null,rows:count?[{date:q.get('start')+' 01:00',orders:count,amount}]:[],seriesGranularity:'day-or-hour',labelsVerified:true};
 const supplement={...common,rsSelection:rs,scopeLabel:Object.values(rs).join(' · '),normalisedScope:'rs-selected',filters:{game:'506'},metrics:Object.fromEntries(['orders','revenueUsd','newCustomers','payingCustomers','repeatRatePct'].map(k=>[k,{...metric(k==='revenueUsd'?amount:k==='repeatRatePct'?20:count),scope:'所选范围'}])),dimensions:dims};
 if(key!=='RS'){supplement.filters={game:key==='FC27'?'1327':key==='AION2'?'891':key==='D4'?'456':''};supplement.normalisedScope='all-websites';supplement.metrics.revenueUsd=metric(1000+refreshRevision*100);supplement.metrics.orders=metric(4);supplement.dimensions.channels=[{name:'www.mmoexp.com',orders:4,revenueUsd:1000+refreshRevision*100}];}
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
  const delay=u.searchParams.get('refresh')==='true'?800:u.searchParams.get('mode')==='summary'&&u.searchParams.get('rs_site')==='rsmalls'?450:0;
  setTimeout(()=>res.end(JSON.stringify(value)),delay);return;
 }
 if(u.pathname==='/dashboard/channel-effects/data.json'){
  const q=u.searchParams;queries.push(Object.fromEntries(q));res.setHeader('Content-Type','application/json');if(deny){res.writeHead(403);res.end('{}');return;}
  const key=q.get('profile'),site=q.get('rs_site'),category=q.get('rs_category'),selection=Object.fromEntries([...q].filter(([k])=>['profile','start','end','grain','profit_site','rs_site','rs_category','rs_server'].includes(k)));
  const zero=key==='RS'&&site==='mmoexp',loss=q.get('profit_site')==='all',factor=key==='RS'?(site==='rsorders'?2:site==='rsmalls'?3:4)*(category==='all'?1:.1):1;
  const m={orders:zero?0:4,completedOrders:zero?0:3,coveredOrders:zero?0:2,missingCostOrders:zero?0:1,legacyRevenueOrders:0,pendingOrders:zero?0:1,saleCny:zero?0:100*factor,costCny:zero?0:(loss?120:70)*factor,profitCny:zero?0:(loss?-20:30)*factor,margin:zero?null:loss?-.2:.3};
  const trend=[];for(let day=q.get('start').slice(0,10);day<=q.get('end').slice(0,10);day=new Date(Date.parse(day)+86400000).toISOString().slice(0,10))trend.push({key:day,...(trend.length?{...m,orders:0,completedOrders:0,coveredOrders:0,missingCostOrders:0,pendingOrders:0,saleCny:0,costCny:0,profitCny:0,margin:null}:m)});
  res.end(JSON.stringify({status:'available',actualContract:'same-order-actual-profit-v1',currency:'CNY',revenueBasis:'admin_order_cny',period:{start:q.get('start'),end:q.get('end')},selection,generatedAt:'2026-10-24T07:00:00Z',sources:{orders:{status:'complete'},cost:{generatedAt:'2026-10-24T07:01:00Z'}},denominator:m,trend}));return;
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
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack);});await page.addInitScript(()=>{const OriginalDate=Date;window.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:['2026-10-24T08:00:00Z']));}static now(){return new OriginalDate('2026-10-24T08:00:00Z').getTime();}};});await page.goto(url);
  const core=page.locator('#supplement-insights > .fsi-metrics > .fsi-metric'),gross=page.locator('[data-metric="profitCny"]'),margin=page.locator('[data-metric="profitMarginPct"]'),coverage=page.locator('[data-profit-coverage]');
  const waitGross=async value=>{await page.waitForFunction(v=>document.querySelector('#app').shadowRoot.querySelector('[data-metric="profitCny"] strong')?.textContent===v,value);};
  await waitGross('¥30.00');assert.equal(await core.count(),18);assert.match(await gross.innerText(),/毛利（¥）/);assert.match(await margin.innerText(),/30.00%/);
  assert.equal(await page.locator('[data-procurement-independent]').count(),0);assert.equal(await page.locator('#shipping-category').count(),0);assert.match(await coverage.textContent(),/2\/3.*待补 1.*未完成 1/);assert.equal(await coverage.isVisible(),false);
  for(const k of ['coveredOrders','missingCostOrders','pendingOrders'])assert.equal(await page.locator('[data-metric="'+k+'"]').isVisible(),false);
  const primary=['revenueUsd','orders','profitCny','profitMarginPct','newCustomers','repeatRatePct','newCustomerSharePct','averageCustomerUsd'];
  assert.deepEqual(await core.evaluateAll(cards=>cards.filter(c=>!c.hidden).sort((a,b)=>+a.style.order-+b.style.order).map(c=>c.dataset.metric)),primary);
  assert.doesNotMatch(await gross.innerText(),/已过期/);
  const revenue=page.locator('[data-metric="revenueUsd"] strong');await revenue.getByText('$1,000.00',{exact:true}).waitFor();
  refreshRevision=1;await page.evaluate(()=>window.api.update());
  await page.locator('#business-refresh-status').getByText('刷新中…',{exact:true}).waitFor();assert.equal(await revenue.innerText(),'$1,000.00');assert.match(await gross.innerText(),/¥30.00/);
  await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('[data-metric="revenueUsd"] strong').textContent==='$1,100.00');
  refreshRevision=0;
  await page.locator('[data-profit-day]').waitFor();assert.match(await page.locator('#lblProfit').innerText(),/^逐单实际成本毛利率走势/);assert.match(await page.locator('#pfPane .pane-ttl').innerText(),/逐单实际成本毛利率走势/);
  assert.doesNotMatch(await page.locator('#supplement-insights').innerText(),/发货利润|预估利润|独立核对/);
  await page.getByRole('combobox',{name:'参考展示范围'}).selectOption('all');await waitGross('¥-20.00');assert.match(await margin.innerText(),/-20.00%/);assert.match(await page.locator('#chartProfit svg').textContent(),/-20.00%/);
  for(const key of ['D4','AION2','FC27']){
   await page.evaluate(k=>window.api.apply({b_profile:k,b_group:k==='FC27'?'sports':'rpg',b_grain:'day',b_range:'yesterday',b_profit_site:'main'}),key);
   await waitGross('¥30.00');assert.match(await margin.innerText(),/30.00%/);assert.equal(await page.locator('[data-metric="coveredOrders"]').isVisible(),false);await page.locator('[data-profit-day]').waitFor({state:'visible'});
  }
  await page.evaluate(()=>window.api.apply({b_profile:'RS',b_group:'general',b_grain:'day',b_range:'yesterday',b_rs_site:'rsorders',b_rs_category:'all'}));await waitGross('¥60.00');
  assert.match(await coverage.textContent(),/2\/3/);
  await page.getByText('当前积压 · 问题单 3 · 待支付 7',{exact:true}).waitFor();
  const more=page.locator('#rs-filters details');assert.equal(await more.getAttribute('open'),null);await more.locator('summary').press('Enter');assert.equal(await page.locator('#rs_server').isVisible(),true);await more.locator('summary').press('Escape');assert.equal(await page.locator('#rs_server').isVisible(),false);
  await page.getByRole('combobox',{name:'2 · 商品类目'}).selectOption('items');await waitGross('¥6.00');
  await page.getByRole('combobox',{name:'1 · 网站来源'}).selectOption('rsmalls');await waitGross('¥9.00');
  await page.getByRole('combobox',{name:'1 · 网站来源'}).selectOption('mmoexp');await waitGross('¥0.00');assert.match(await margin.innerText(),/不适用/);
  assert.ok(queries.some(q=>q.mode==='actual-profit'&&q.profile==='RS'&&q.rs_category==='items'));assert.ok(queries.filter(q=>q.mode==='summary').every(q=>q.profit_basis==='actual'));assert.ok(!queries.some(q=>q.mode==='profit-history'));assert.ok(queries.filter(q=>q.mode==='fc-detail').every(q=>!('profit_site'in q)));
  for(const theme of ['light','dark']){await page.locator('#app').evaluate((e,t)=>{e.dataset.theme=t;e.ownerDocument.documentElement.dataset.theme=t;},theme);assert.equal(await gross.isVisible(),true);}
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  deny=true;await page.evaluate(()=>window.api.update());await page.waitForFunction(()=>!document.querySelector('#app').shadowRoot.querySelector('[data-metric="profitCny"] strong')?.textContent.includes('¥0.00'));assert.deepEqual(errors,[]);
  console.log('Actual profit UI: cards/coverage/daily, global/games/All/RS filters, zero/loss, denial, themes and mobile passed');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
