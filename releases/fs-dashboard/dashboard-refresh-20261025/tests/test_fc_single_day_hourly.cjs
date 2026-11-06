// Single-day display projection over one FC snapshot. All API values are MOCK.
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {serve,server,detail}=require('./fc_rs_visual_fixture.cjs');
const failures=[];
async function check(name,run){try{await run();console.log('PASS '+name);}catch(error){failures.push(name+': '+error.message);console.error('FAIL '+name+': '+error.message);}}
function hourly(day,categories){
 return Array.from({length:24},(_,hour)=>{
  const parts=categories.map(c=>{const slots=Math.min(c.orders,24),active=hour<slots,base=Math.floor(c.orders/(slots||1)),amount=Math.floor(c.revenue_usd*100/(slots||1));return {key:c.key,label:c.label,orders:active?base+(hour<c.orders%slots?1:0):0,revenue_usd:active?(hour===slots-1?c.revenue_usd*100-amount*(slots-1):amount)/100:0};});
  return {date:day+' '+String(hour).padStart(2,'0')+':00',orders:parts.reduce((sum,c)=>sum+c.orders,0),revenue_usd:parts.reduce((sum,c)=>sum+c.revenue_usd,0),categories:parts};
 });
}
(async()=>{
 const url=await serve(),browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],queries=[];let revision=0,kind='complete',deny=false;
  page.setDefaultTimeout(5000);page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{
   const target=new URL(route.request().url()),q=Object.fromEntries(target.searchParams);
   if(target.hostname!=='127.0.0.1')return route.abort('blockedbyclient');
   if(q.mode!=='fc-detail')return route.continue();queries.push(q);
   if(deny)return route.fulfill({status:403,json:{error:'session_denied'}});
   const response=detail(q,kind==='partial');response.snapshot_id='MOCK-hourly-'+revision;response.scope_label='MOCK hourly CASE-'+revision;
   if(q.grain==='day'&&q.start===q.end){
    response.fc_dashboard.hourly_trend=hourly(q.start,response.fc_dashboard.categories);
    if(kind==='missing')delete response.fc_dashboard.hourly_trend;
    if(kind==='empty'){response.fc_dashboard.hourly_trend=[];response.fc_dashboard.totals.orders=0;response.fc_dashboard.totals.revenue_usd=0;}
    if(kind==='partial'){
     // Missing hour is unknown, never a fabricated zero. Known hours retain their
     // real numbers; either a gap or an explicit unavailable chart is acceptable.
     response.fc_dashboard.hourly_trend=hourly(q.start,detail(q).fc_dashboard.categories);
     const gap=response.fc_dashboard.hourly_trend[10];gap.orders=null;gap.revenue_usd=null;
     gap.categories=gap.categories.map(c=>({...c,orders:null,revenue_usd:null}));
    }
    if(kind==='today-cutoff'||kind==='exact-hour-cutoff'){
     response.source_period={start:q.start+' 00:00',end:q.start+(kind==='today-cutoff'?' 14:37':' 15:00')};
     response.query.period={start:q.start+' 00:00',end:q.start+' 15:00'};
     response.fc_dashboard.hourly_trend=response.fc_dashboard.hourly_trend.slice(0,15);
    }
   }
   return route.fulfill({json:response});
  });
  await page.goto(url);await page.waitForFunction(()=>window.api&&window.lastState?.b_profile==='MMOEXP');
  async function select(changes={},scenario='complete'){
   kind=scenario;revision++;
   await page.evaluate(state=>window.api.apply(state),{b_site:'all',b_profile:'FC27',b_group:'sports',b_grain:'day',b_range:'custom',b_start:'2026-10-23',b_end:'2026-10-23',b_fc_product:'all',b_fc_platform:'all',b_fc_site_group:'all',b_fc_customer:'all',b_fc_bucket:'all',...changes});
   await page.locator('[data-fc-retry]').evaluate(element=>element.click());
   await page.waitForFunction(value=>document.querySelector('#app').shadowRoot.querySelector('.fc-state')?.textContent.includes('CASE-'+value),revision);
  }
  await select();
  await check('single-day selection stays day while the order/sales chart renders 24 true hours',async()=>{
   const state=await page.evaluate(()=>window.api.state());assert.equal(state.b_grain,'day');assert.equal(state.b_start,state.b_end);
   assert.match(await page.locator('#mainTitle').innerText(),/小时/);
   assert.equal(await page.locator('#chartMain svg circle[data-i]').count(),24);
   assert.doesNotMatch(await page.locator('#chartMain').innerText(),/切换小时/);
  });
  await check('single-day category sales uses the same snapshot hourly series',async()=>{
   assert.equal(await page.locator('[data-fc-content=structure] .fc-line svg').count(),1);
   assert.equal(await page.locator('[data-fc-content=structure] .fc-line-legend > span').count(),6);
   assert.match(await page.locator('[data-fc-content=structure] .fc-line').innerText(),/00:00|03:00/);
  });
  await check('profit stays a daily result and aggregate cards retain daily totals',async()=>{
   assert.equal(await page.locator('#chartProfit svg').count(),0);
   assert.match(await page.locator('#chartProfit').innerText(),/27\.94%/);assert.match(await page.locator('#chartProfit').innerText(),/日/);
   assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'120');
   assert.equal(await page.locator('[data-metric=revenueUsd] strong').innerText(),'$6,480.00');
  });
  await check('automatic hourly charts disclose actual partial-hour source cutoff without future bins',async()=>{
   await select({b_start:'2026-10-24',b_end:'2026-10-24'},'today-cutoff');
   assert.equal(await page.locator('#chartMain svg circle[data-i]').count(),15);
   for(const text of [await page.locator('#mainHint').innerText(),await page.locator('[data-fc-content=structure] .row2 > article:last-child .hint').innerText()]){assert.match(text,/统计截至 2026-10-24 14:37/);assert.match(text,/最后小时未完整/);assert.doesNotMatch(text,/统计截至 2026-10-24 15:00/);}
   const titles=await page.locator('[data-fc-content=structure] .fc-line circle title').allTextContents();assert.ok(titles.every(text=>!text.includes('2026-10-24 15:00')));
   await page.locator('#chartMain .hz[data-i="14"]').hover();assert.match(await page.locator('#tip').getAttribute('class'),/on/);assert.match(await page.locator('#tip').innerText(),/未完整|未过完/);
  });
  await check('exact-hour cutoff does not mark the previous completed hour as partial',async()=>{
   await select({b_start:'2026-10-24',b_end:'2026-10-24'},'exact-hour-cutoff');
   assert.equal(await page.locator('#chartMain svg circle[data-i]').count(),15);
   for(const text of [await page.locator('#mainHint').innerText(),await page.locator('[data-fc-content=structure] .row2 > article:last-child .hint').innerText(),await page.locator('#mainLegend').innerText()])assert.doesNotMatch(text,/最后小时未完整|当前未结束小时/);
   await page.locator('#chartMain .hz[data-i="14"]').hover();assert.match(await page.locator('#tip').getAttribute('class'),/on/);assert.doesNotMatch(await page.locator('#tip').innerText(),/未完整|未过完/);
  });
  await check('category and platform filters apply to both automatic hourly charts',async()=>{
   await select({b_fc_product:'Players',b_fc_platform:'PC'});
   assert.equal(queries.at(-1).product,'Players');assert.equal(queries.at(-1).platform,'PC');assert.equal(queries.at(-1).grain,'day');
   assert.equal(await page.locator('#chartMain svg circle[data-i]').count(),24);
   assert.equal(await page.locator('[data-fc-content=structure] .fc-line-legend').innerText(),'球员卡');
   assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'32');assert.equal(await page.locator('#crossSec').isVisible(),false);
  });
  await check('missing hourly projection shows a clear unavailable state without daily singleton fallback',async()=>{
   await select({},'missing');assert.equal(await page.locator('#chartMain svg').count(),0);
   assert.equal(await page.locator('[data-fc-content=structure] .fc-line svg').count(),0);
   assert.match(await page.locator('#chartMain').innerText(),/小时.*(暂缺|缺失|未提供|读取)|(?:暂缺|缺失|未提供|读取).*小时/);
   assert.doesNotMatch(await page.locator('#chartMain').innerText(),/切换小时/);
  });
  await check('partial hours never fabricate zero sales or connect through the missing category hour',async()=>{
   await select({},'partial');
   const main=await page.locator('#chartMain').innerHTML(),category=await page.locator('[data-fc-content=structure]').innerHTML();
   assert.doesNotMatch(main+category,/NaN|Infinity/);
   assert.match(await page.locator('#chartMain').innerText(),/缺失|暂缺|部分|读取/);
   const gapTitles=await page.locator('[data-fc-content=structure] .fc-line circle title').allTextContents();assert.ok(gapTitles.every(text=>!text.includes('2026-10-23 10:00')));
  });
  await check('empty hourly response clears the previous curves',async()=>{
   await select({b_start:'2026-10-22',b_end:'2026-10-22'},'empty');
   assert.equal(await page.locator('#chartMain svg circle[data-i]').count(),0);
   assert.equal(await page.locator('[data-fc-content=structure] .fc-line circle').count(),0);
   assert.doesNotMatch(await page.locator('#mainHint').innerText(),/2026-10-23/);
  });
  await check('multi-day day selection keeps daily sales and profit charts',async()=>{
   await select({b_start:'2026-10-22',b_end:'2026-10-23'});
   assert.equal(await page.locator('#chartMain svg circle[data-i]').count(),2);
   assert.doesNotMatch(await page.locator('#mainTitle').innerText(),/小时/);assert.ok(await page.locator('#chartProfit svg').count()>0);
  });
  await check('automatic hourly display does not issue an independent hourly source request',async()=>{
   assert.ok(queries.length>0);assert.ok(queries.every(q=>q.grain==='day'));
  });
  await check('permission denial clears both hourly charts and retained daily profit',async()=>{
   await select();deny=true;await page.locator('[data-fc-retry]').click();
   await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelectorAll('#chartMain svg,#chartProfit svg,#fc-panel-structure .fc-line svg').length===0);
   assert.equal(await page.locator('#fc-detail .fc-donut').count(),0);
  });
  assert.deepEqual(errors,[],'real renderer page errors');
  if(failures.length)throw Error(failures.length+' automatic hourly display checks failed:\n'+failures.join('\n'));
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(error=>{console.error(error);server.closeAllConnections();server.close();process.exitCode=1;});
