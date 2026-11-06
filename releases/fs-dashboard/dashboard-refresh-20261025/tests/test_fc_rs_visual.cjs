// Real renderer, rich local-only API fixture. No production request is allowed.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {serve,server,detail}=require('./fc_rs_visual_fixture.cjs');
const evidence=process.env.FC_RS_VISUAL_EVIDENCE||path.resolve(__dirname,'../../../../../evidence/rs-visual-correction');
const failures=[];
async function check(name,run){try{await run();console.log('PASS '+name);}catch(error){failures.push(name+': '+error.message);console.error('FAIL '+name+': '+error.message);}}
async function waitData(page){await page.waitForFunction(()=>document.querySelector('#app')?.shadowRoot.querySelector('#fc-detail [data-fc-filter=product]')&&!document.querySelector('#app').shadowRoot.querySelector('.fc-state')?.textContent.includes('正在读取'),null,{timeout:10000});}
async function choose(page,state){await page.evaluate(s=>window.api.apply({...window.api.state(),...s}),state);await waitData(page);await page.waitForTimeout(120);}
async function theme(page,value){await page.locator('#app').evaluate((host,t)=>{for(const element of [host,document.documentElement]){element.dataset.theme=t;element.dataset.fsTheme=t;}},value);}
async function permissionCase(browser,url,status,format){
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];let deny=false;page.setDefaultTimeout(5000);
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',route=>{const request=new URL(route.request().url());if(request.hostname!=='127.0.0.1')return route.abort('blockedbyclient');if(request.pathname==='/mock-login')return route.fulfill({status:200,contentType:'text/html',body:'<html><h1>Expired mock session</h1></html>'});if(deny&&request.searchParams.get('mode')==='fc-detail'){if(format==='redirect')return route.fulfill({status:302,headers:{location:'/mock-login'},body:''});return route.fulfill({status,contentType:format==='html'?'text/html':'application/json',body:format==='html'?'<html><h1>Expired mock session</h1></html>':JSON.stringify({error:'session_denied'})});}return route.continue();});
 try{
  await page.goto(url+'/?preview=1');await page.locator('#fc-detail .fc-donut').first().waitFor();
  await page.locator('[data-fc-backlog]').click();await page.locator('.fc-drawer-content [data-fc-order]').first().waitFor();
  if(format==='event')await page.evaluate(code=>window.scope.window.dispatchEvent(new CustomEvent('fs-exact-permission-denied',{detail:{status:code}})),status);
  else{deny=true;await page.locator('[data-fc-retry]').evaluate(element=>element.click());}
  await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelectorAll('#chartMain svg,#chartProfit svg,#worldMap svg,#fc-detail .fc-donut').length===0,null,{timeout:5000});
  assert.equal(await page.locator('[data-fc-content=consumption] .fc-bar-row').count(),0);
  assert.equal(await page.locator('.fc-drawer-content [data-fc-order]').count(),0);
  assert.equal(await page.locator('#fc-detail dialog').evaluate(element=>element.open),false);
  assert.ok((await page.locator('#supplement-insights [data-metric]:visible strong').allTextContents()).every(text=>text==='读取失败'));
  assert.deepEqual(errors,[],'permission event must not cause render recursion or TDZ');
 }finally{await page.close();}
}
(async()=>{
 const url=await serve(),browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];let partial=false;page.setDefaultTimeout(5000);
  page.on('pageerror',error=>{errors.push(error.message);console.error('Renderer error: '+error.stack);});
  await page.route('**/*',route=>{const request=new URL(route.request().url());if(request.hostname!=='127.0.0.1')return route.abort('blockedbyclient');if(partial&&request.searchParams.get('mode')==='fc-detail'){request.searchParams.set('fixture_partial','1');return route.continue({url:request.href});}return route.continue();});
  await page.goto(url+'/?preview=1');await waitData(page);
  await page.locator('#fc-detail .fc-donut').first().waitFor();
  await check('overview has eight common metrics and no FC source/ops card grid',async()=>{
   assert.equal(await page.locator('#fc-detail .fc-overview-grid:visible').count(),0);
   assert.equal(await page.locator('#supplement-insights [data-metric]:visible').count(),8);
  });
  await check('fulfillment and review remain compact entry points',async()=>{
   assert.equal(await page.locator('#fc-panel-fulfillment:visible,#fc-panel-review:visible').count(),0);
   assert.ok(await page.locator('[data-fc-backlog]').count()>0);
   assert.ok(await page.locator('a[href="/dashboard/fs-home/brain/index.html?report_kind=daily#reports"]').count()>0);
  });
  await check('FC displays original RS country ranking and world map',async()=>{
   assert.equal(await page.locator('#geoCard').isVisible(),true);
   assert.equal(await page.locator('#geoRank .ritem').count(),8);
   assert.equal(await page.locator('#worldMap svg .wm-c').count(),8);
   assert.equal(await page.locator('#worldMap svg .wm-b').count(),8);
   assert.match(await page.locator('#geoRank').innerText(),/US/);assert.match(await page.locator('#geoRank').innerText(),/GB/);
  });
  await check('FC displays original RS payment ranking and device proportions',async()=>{
   assert.equal(await page.locator('#payRow').isVisible(),true);
   assert.ok(await page.locator('#payStyleList > *').count()>=4);
   assert.equal(await page.locator('#payDevBox .devtile').count(),3);
   assert.match(await page.locator('#payStyleList').innerText(),/PayPal/i);
   assert.match(await page.locator('#payDevBox').innerText(),/PC/);
  });
  await check('FC uses original paired chart panes rather than two bespoke trend canvases',async()=>{
   assert.equal(await page.locator('#trendCard').isVisible(),true);
   assert.equal(await page.locator('#pfPane').isVisible(),true);
   assert.ok(await page.locator('#chartProfit svg').count()>0);assert.ok(await page.locator('#chartMain svg').count()>0);
   assert.equal(await page.locator('[data-fc-content=trend] .fc-line:visible').count(),0);
   const box=await page.locator('#trendCard').boundingBox();assert.ok(box.height<780,'paired chart card must not become two full-page canvases: '+box.height);
  });
  await check('consumption combines bars and ring with details collapsed',async()=>{
   const consumption=page.locator('[data-fc-content=consumption]');
   assert.ok(await consumption.locator('.fc-bars').count()>0);assert.ok(await consumption.locator('.fc-donut').count()>0);
   assert.ok(await consumption.locator('details table').count()>0);
   assert.equal(await consumption.locator('details[open]').count(),0);
   assert.equal(await consumption.locator('table:visible').count(),0);
   assert.equal(await consumption.locator('.fc-consumption-legend').count(),0,'unverified customer history cannot display a new/repeat legend');
   assert.equal(await consumption.locator('.fc-bar-track [data-customer=new],.fc-bar-track [data-customer=returning]').count(),0);
  });
  await check('category ring metric and six-series trend follow the current selection',async()=>{
   const structure=page.locator('[data-fc-content=structure]');
   assert.equal(await structure.locator('.fc-line-legend > span').count(),6);
   await structure.locator('[data-fc-metric=orders]').click();assert.match(await structure.locator('.fc-donut').innerText(),/120/);
   await structure.locator('[data-fc-metric=revenue_usd]').click();assert.match(await structure.locator('.fc-donut').innerText(),/6,480/);
  });
  await check('user cumulative ring is informational and never sends unsupported user filters',async()=>{
   const invalid=[];const watch=request=>{if(new URL(request.url()).searchParams.has('user'))invalid.push(request.url());};page.on('request',watch);
   await page.locator('[data-fc-view=user]').click();
   assert.equal(await page.locator('[data-fc-content=consumption] button[data-fc-chart-dimension=user]').count(),0);
   assert.ok(await page.locator('[data-fc-content=consumption] [data-fc-chart-dimension=user]').count()>0);
   assert.deepEqual(invalid,[]);page.off('request',watch);await page.locator('[data-fc-view=order]').click();
  });
  await check('specified category hides group comparison',async()=>{
   await page.locator('[data-fc-filter=product]').selectOption('Players');await page.waitForTimeout(160);
   assert.equal(await page.locator('#crossSec').isVisible(),false);
   await page.locator('[data-fc-filter=product]').selectOption('all');await page.waitForTimeout(160);
   assert.equal(await page.locator('#crossSec').isVisible(),true);
  });
  fs.mkdirSync(evidence,{recursive:true});
  const themePaint={};for(const [name,width,mode,single]of [['desktop-light-multiday',1920,'light',false],['desktop-dark-multiday',1920,'dark',false],['desktop-light-1280-multiday',1280,'light',false],['mobile-light-multiday',390,'light',false],['mobile-dark-single-day',390,'dark',true],['desktop-light-single-day',1920,'light',true]]){
   await page.setViewportSize({width,height:width===390?844:1080});await theme(page,mode);
   await choose(page,{b_grain:'day',b_range:'custom',b_start:single?'2026-10-23':'2026-10-17',b_end:'2026-10-23'});
   await check(name+' readable width and bounded charts',async()=>{
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflows horizontally');
    const charts=await page.locator('#chartMain,#chartProfit').evaluateAll(elements=>elements.map(e=>e.getBoundingClientRect().height));assert.ok(charts.every(height=>height>20&&height<450),'single/day chart heights '+charts.join(','));
    if((width===390||width===1280)&&!single){const sizes=await page.locator('#chartMain svg text,#chartProfit svg text,#fc-panel-structure .fc-line svg text').evaluateAll(elements=>elements.filter(e=>e.getClientRects().length).map(e=>parseFloat(getComputedStyle(e).fontSize)*e.getScreenCTM().a));assert.ok(sizes.length&&Math.min(...sizes)>=9.9,'chart label effective font sizes '+sizes.join(','));}
    if(width===390){const lines=await page.locator('#secCross .sec-title').evaluate(element=>{const range=document.createRange();range.selectNodeContents(element);return range.getClientRects().length;});assert.equal(lines,1,'narrow-screen comparison title stays on one readable line');}
   });
   if(width===1920&&!single)themePaint[mode]=await page.locator('#geoCard').evaluate(e=>[getComputedStyle(e).backgroundColor,getComputedStyle(e).color]);
   if(name==='desktop-light-multiday'){await page.locator('#fc-panel-structure > h2').evaluate(element=>{const note=document.createElement('span');note.textContent='MOCK DATA · 本地模拟数据';note.style.cssText='margin-left:auto;font-size:12px;font-weight:400';element.append(note);});await page.locator('#fc-panel-structure').screenshot({path:path.join(evidence,'structure-desktop-light-MOCK.png')});}
   await page.screenshot({path:path.join(evidence,name+'-MOCK.png'),fullPage:true});
  }
  await check('real token theme changes card background and foreground',async()=>assert.notDeepEqual(themePaint.light,themePaint.dark));
  await check('partial categories disclose known subset without complete totals',async()=>{
   partial=true;await page.locator('[data-fc-retry]').click();
   await page.waitForFunction(()=>document.querySelector('#app').shadowRoot.querySelector('[data-fc-content=structure] [data-fc-incomplete-chart]'));
   assert.match(await page.locator('[data-fc-content=structure]').innerText(),/已知|缺失|待核/);
   assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'暂缺');
   await page.screenshot({path:path.join(evidence,'desktop-light-partial-MOCK.png'),fullPage:true});partial=false;
  });
  await check('single hour uses hourly wording and known USD value',async()=>{
   const start='2026-10-23 12:00',end=start;
   await choose(page,{b_grain:'hour',b_range:'custom',b_start:start,b_end:end});
   assert.match(await page.locator('#mainTitle').innerText(),/(本|单)小时/);
   const amount=detail({product:'all',start,end,grain:'hour'}).fc_dashboard.trend[0].revenue_usd;
   assert.match(await page.locator('#chartMain').innerText(),new RegExp(amount.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
   assert.doesNotMatch(await page.locator('#chartMain').innerText(),/切换小时/);
  });
  await check('FC to RS restores original node parents and contains no duplicate IDs',async()=>{
   await choose(page,{b_site:'rsorders',b_profile:'RS',b_group:'general',b_grain:'day',b_range:'yesterday'});
   const expectedFold=process.env.RS_VARIANT&&process.env.RS_VARIANT!=='business.js'?'false':'true';
   assert.equal(await page.locator('#secStruct').getAttribute('aria-expanded'),expectedFold,'RS retains this entry point original folding preference');
   if(expectedFold==='false')await page.locator('#secStruct').click();
   await page.locator('#geoCard').waitFor({state:'visible'});
   const result=await page.locator('#app').evaluate(host=>{const root=host.shadowRoot,seen=new Set(),duplicates=[];for(const element of root.querySelectorAll('[id]')){if(seen.has(element.id))duplicates.push(element.id);seen.add(element.id);}return {duplicates,insideFC:['geoCard','payRow','trendCard'].filter(id=>root.getElementById(id)?.closest('#fc-detail')),next:['geoCard','payRow','trendCard'].map(id=>root.getElementById(id)?.nextElementSibling?.id)};});
   assert.deepEqual(result,{duplicates:[],insideFC:[],next:['payRow','secDetail','calCard']});
   assert.equal(await page.locator('#fc-detail').isVisible(),false);assert.equal(await page.locator('#pfPane').isVisible(),true);
  });
  const variantBefore=process.env.RS_VARIANT;
  for(const variant of ['business.js','home-business.js','legacy-business.js']){
   process.env.RS_VARIANT=variant;
   for(const status of [401,403])for(const format of ['json','html'])await check(variant+' '+format+' '+status+' clears cached KPI, charts, consumption and open drawer',()=>permissionCase(browser,url,status,format));
   await check(variant+' 302 to 200 HTML login clears all cached views',()=>permissionCase(browser,url,302,'redirect'));
   await check(variant+' external permission event clears all cached views',()=>permissionCase(browser,url,403,'event'));
  }
  if(variantBefore===undefined)delete process.env.RS_VARIANT;else process.env.RS_VARIANT=variantBefore;
  assert.deepEqual(errors,[],'renderer page errors');
  if(failures.length)throw new Error(failures.length+' visual/behavior checks failed:\n'+failures.join('\n'));
  console.log('FC/RS visual correction passed with real local renderer. Evidence: '+evidence);
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(error=>{console.error(error);server.closeAllConnections();server.close();process.exitCode=1;});
