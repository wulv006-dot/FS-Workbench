// The real business renderer; every API value is fictional and all routes are local.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {start,server}=require('./test_browser.cjs');
const repo=path.resolve(__dirname,'../../../..');
let deny=false,revision=0,partial=false,failRefresh=false;
function fixture(q){
 const product=q.product||'all',n=product==='Other'?0:product==='all'?10:product==='Coins'?7:3;
 const row={orders:n,revenue_usd:n*20,shipping_sales_cny:null,cost_cny:null,gross_profit_cny:null,gross_margin_pct:null};
 const categories=(product==='all'?['Coins','Players']:[product]).map((key,i)=>({key,label:key==='Coins'?'金币':'球员卡',...row,orders:product==='all'?(i?3:7):n,revenue_usd:product==='all'?(i?60:140):n*20}));
 const trend=q.grain==='hour'?[0,1,2].map((i)=>{const date=new Date(Date.parse(q.start.replace(' ','T')+':00Z')+i*3600000).toISOString().slice(0,16).replace('T',' ');const parts=categories.map(c=>({...c,orders:i===0?c.orders-2*Math.floor(c.orders/3):Math.floor(c.orders/3),revenue_usd:(i===0?c.orders-2*Math.floor(c.orders/3):Math.floor(c.orders/3))*20}));return {...row,date,orders:parts.reduce((n,c)=>n+c.orders,0),revenue_usd:parts.reduce((n,c)=>n+c.revenue_usd,0),categories:parts};}):[{date:q.start,...row,categories}];
 const buckets=[{key:'20-40',label:'20–40',orders:n,revenue_usd:n*20,new:0,returning:0,unknown:n,issues:1}];
 return {contractId:'fc27-detail-analytics-v1',query:{...q},snapshot_id:'fictional-'+product+'-'+revision,as_of:'2026-10-24T08:00:00Z',refreshSeconds:900,scope_label:'模拟 FC27',data_status:partial?'partial':'complete',customer_status:'unavailable',customer_basis:'站内客户ID；历史首次购买未验证',orders_without_customer_id:1,coverage:{paid_complete:!partial,missing_days:partial?['2026-10-22']:[],backlog_status:'complete'},totals:{...row,new:0,returning:0,unknown:n,unpriced_orders:0,issues:1,unfinished:2,funding:1},site_groups:[{key:'main',orders:n,revenue_usd:n*20},{key:'satellite',orders:0,revenue_usd:0}],signals:[],buckets,user_buckets:[{key:'20-40',label:'20–40',users:2,revenue_usd:60}],dimensions:{platform:[{key:'PS',...row,issues:1}],product:categories},backlog_summary:{orders:2,issues:1,unfinished:2,funding:1,revenue_usd:40},slow_orders:1,trend,orders:[{id:'fictional-1',site_id:'266',site_group:'main',platform:'PS',product:'Items',category:product,amount_usd:20,customer:'unknown',age_hours:1,status:'处理中',reason:'待确认'}],page:1,list_total:1,fc_dashboard:{contractId:'fc-dashboard-category-v1-20261106',categories,trend,totals:{...row,...(partial?{orders:null,revenue_usd:null}:{}),paying_customers:2,new_customers:null,repeat_rate_pct:null,new_customer_share_pct:null},coverage:{classification_status:partial?'partial':'complete'}}};
}
(async()=>{
 const url=await start(),browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],queries=[];
  page.on('pageerror',e=>errors.push(e.stack));
  await page.addInitScript(()=>{const OriginalDate=Date;window.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:['2026-10-24T08:00:00Z']));}static now(){return new OriginalDate('2026-10-24T08:00:00Z').getTime();}};});
  await page.route('**/business.css',route=>route.fulfill({contentType:'text/css',body:fs.readFileSync(path.join(repo,'ui-system/modules/native/business.css'),'utf8')}));
  await page.route('**/dashboard/fs-home/range.json?**',async route=>{
   const q=Object.fromEntries(new URL(route.request().url()).searchParams);
   if(q.mode!=='fc-detail')return route.continue();queries.push(q);
   if(deny)return route.fulfill({status:403,json:{error:'denied'}});
   if(failRefresh)return route.fulfill({status:503,json:{error:'temporary_unavailable'}});
   const data=fixture(q);if(q.product==='Coins')await new Promise(r=>setTimeout(r,150));
   return route.fulfill({json:q.format==='csv'?{...data,csv:'product,orders\n'+q.product+',1'}:data});
  });
  await page.goto(url);await page.waitForFunction(()=>window.api&&window.lastState?.b_profile==='MMOEXP');
  await page.evaluate(()=>window.api.apply({b_site:'mmoexp',b_profile:'FC27',b_group:'sports',b_grain:'day',b_range:'yesterday'}));
  const host=page.locator('#fc-detail'),product=host.locator('[data-fc-filter=product]');
  await host.locator('.fc-donut').first().waitFor();
  assert.equal(await host.locator('[role=tablist]').count(),0);
  assert.deepEqual(await product.locator('option').allTextContents(),['全部商品','金币','球员卡','SBC','Packs','其他']);
  assert.equal(await host.locator('#fc-panel-structure').isVisible(),true);assert.equal(await host.locator('#fc-panel-consumption').isVisible(),true);
  assert.equal(await page.locator('#crossSec').isVisible(),true);
  assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'10');
  assert.equal(await page.locator('[data-metric=profitCny] strong').innerText(),'暂缺');
  await product.selectOption('Coins');await product.selectOption('Players');
  await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('[data-metric=orders] strong')?.textContent==='3');
  await page.waitForTimeout(250);assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'3');
  assert.equal(await page.locator('#crossSec').isVisible(),false);
  assert.equal(await host.locator('[data-fc-content=structure] .fc-line-legend').first().innerText(),'球员卡');
  await host.locator('[data-fc-view=user]').click();assert.match(await host.locator('[data-fc-content=consumption]').innerText(),/用户累计消费/);
  await host.locator('[data-fc-view=order]').click();await host.locator('[data-fc-drill]').first().click();
  await host.locator('.fc-drawer-content [data-fc-order]').waitFor();assert.equal(queries.at(-1).product,'Players');
  await host.locator('[data-fc-order]').click();await host.locator('[data-fc-return]').click();assert.equal(await host.locator('[data-fc-order]').count(),1);await host.locator('[data-fc-close]').click();
  await page.evaluate(()=>window.api.apply({...window.api.state(),b_fc_product:'Coins',b_fc_platform:'PC'}));
  await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('[data-metric=orders] strong')?.textContent==='7');
  assert.equal(await product.inputValue(),'Coins');assert.equal(queries.at(-1).platform,'PC');
  await page.evaluate(()=>window.api.apply({...window.api.state(),b_fc_product:'all',b_fc_platform:'all',b_grain:'hour',b_range:'24'}));
  await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('[data-metric=orders] strong')?.textContent==='10');
  assert.equal(queries.at(-1).grain,'hour');assert.match(queries.at(-1).start,/ \d\d:00$/);
  const themeColors=[];for(const theme of ['light','dark']){await page.locator('#app').evaluate((e,t)=>{e.dataset.theme=t;e.dataset.fsTheme=t;e.ownerDocument.documentElement.dataset.theme=t;e.ownerDocument.documentElement.dataset.fsTheme=t;},theme);assert.equal(await host.locator('.fc-donut').first().isVisible(),true);themeColors.push(await host.locator('.fc-card').first().evaluate(e=>[getComputedStyle(e).backgroundColor,getComputedStyle(e).color]));}assert.notDeepEqual(themeColors[0],themeColors[1]);
  if(process.env.FC_DASHBOARD_EVIDENCE){
   const dir=process.env.FC_DASHBOARD_EVIDENCE;fs.mkdirSync(dir,{recursive:true});
   for(const theme of ['light','dark']){await page.locator('#app').evaluate((e,t)=>{e.dataset.theme=t;e.dataset.fsTheme=t;e.ownerDocument.documentElement.dataset.theme=t;e.ownerDocument.documentElement.dataset.fsTheme=t;},theme);for(const section of ['structure','consumption']){const box=host.locator('#fc-panel-'+section);await box.locator('h2').evaluate(e=>{e.querySelector('[data-fixture]')?.remove();const note=document.createElement('span');note.dataset.fixture='true';note.textContent='模拟数据 · 本地行为验收';note.style.cssText='font-size:11px;font-weight:400;margin-left:auto';e.append(note);});await box.screenshot({path:path.join(dir,`fc-${theme}-desktop-${section}-simulated.png`)});}}
  }
  await page.setViewportSize({width:390,height:844});await host.locator('.fc-more-filters summary').click();
  assert.ok(await host.locator('.fc-more').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=10&&r.right<=innerWidth-10;}));
  await host.locator('.fc-more-filters summary').press('Escape');assert.ok(await host.locator('.fc-line svg text').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize)*e.getScreenCTM().a>=10));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  if(process.env.FC_DASHBOARD_EVIDENCE)for(const section of ['structure','consumption'])await host.locator('#fc-panel-'+section).screenshot({path:path.join(process.env.FC_DASHBOARD_EVIDENCE,`fc-dark-390-${section}-simulated.png`)});
  partial=true;revision++;await host.locator('[data-fc-retry]').click();await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('[data-metric=orders] strong')?.textContent==='暂缺');
  assert.match(await host.locator('.fc-state').innerText(),/分类未完整/);assert.match(await host.locator('[data-fc-content=consumption]').innerText(),/已知子集/);
  partial=false;revision++;await host.locator('[data-fc-retry]').click();await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('[data-metric=orders] strong')?.textContent==='10');
  failRefresh=true;await host.locator('[data-fc-retry]').click();await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('.fc-state')?.textContent.includes('FC明细暂不可用'));assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'10');failRefresh=false;
  deny=true;await host.locator('[data-fc-retry]').click();await page.waitForFunction(()=>!document.querySelector('#app').shadowRoot.querySelector('#fc-detail .fc-donut'));
  assert.equal(await host.locator('.fc-donut').count(),0);assert.deepEqual(errors,[]);
  console.log('FC continuous dashboard: filters, race, scoped cards, missing CNY, consumption/drill return, state restore, hourly precision, themes, narrow screen and permission clearing passed');
 }catch(error){console.error(error);throw error;}finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
