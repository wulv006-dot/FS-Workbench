// Existing Admin-native summary metrics must survive FC's detail-card projection.
// All sources are fictional local responses; customer list history stays unverified.
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {serve,server,detail}=require('./fc_rs_visual_fixture.cjs');
const keys=['newCustomers','repeatRatePct','newCustomerSharePct'];
const native={newCustomers:24,repeatRatePct:12.5,newCustomerSharePct:20};
const supplemental={payingCustomers:43,newCustomerRevenueUsd:4800,pureSalesUsd:6400,refundAmountUsd:80,refundOrders:2,fulfillmentRatePct:93.75,paymentSuccessRatePct:88.2,averageCustomerUsd:150.7};
const supplementalText={payingCustomers:'43',newCustomerRevenueUsd:'$4,800.00',pureSalesUsd:'$6,400.00',refundAmountUsd:'$80.00',refundOrders:'2',fulfillmentRatePct:'93.75%',paymentSuccessRatePct:'88.20%',averageCustomerUsd:'$150.70'};
const expected=['24','12.50%','20.00%'];
const selection={b_site:'all',b_profile:'FC27',b_group:'sports',b_grain:'day',b_range:'custom',b_start:'2026-10-17',b_end:'2026-10-23',b_fc_product:'all',b_fc_platform:'all',b_fc_site_group:'all',b_fc_customer:'all',b_fc_bucket:'all'};
const failures=[];
async function check(name,run){try{await run();console.log('PASS '+name);}catch(error){failures.push(name+': '+error.message);console.error('FAIL '+name+': '+error.message);}}
(async()=>{
 const url=await serve(),browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage(),errors=[];let revision=0,scenario='native';
  page.setDefaultTimeout(5000);page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{
   const request=new URL(route.request().url()),q=Object.fromEntries(request.searchParams);
   if(request.hostname!=='127.0.0.1')return route.abort('blockedbyclient');
   if(q.mode==='fc-detail'){
    const response=detail(q);response.snapshot_id='native-customer-fixture-'+revision;
    response.scope_label='MOCK native customer CASE-'+revision;
    // Explicitly retain the deployed distinction: Admin summary known; list
    // history unavailable; the FC detail's derived customer totals are null.
    response.customer_status='unavailable';
    Object.assign(response.fc_dashboard.totals,{new_customers:null,repeat_rate_pct:null,new_customer_share_pct:null});
    return route.fulfill({json:response});
   }
   if(q.mode==='summary'&&q.profile==='FC27'){
    const requestedRevision=revision,upstream=await route.fetch(),response=await upstream.json(),p=response.profile,a=p.supplement;
    response.fixture_native_revision=requestedRevision;
    const main=q.profit_site!=='all';
    a.status='available';a.normalisedScope=main?'main-website':'all-websites';a.system='admin.p2pah.cn';a.currency='USD';
    a.endpoint='/admin/order.Order/orderStaticsDetailByEs';
    a.filters={game:'1327',site:main?266:'',pay_status:1,order_status:'',date:[q.start,q.end]};
    a.scopeLabel=main?'MOCK Admin MMOEXP main native summary':'MOCK Admin all-websites native summary';
    const next=new Date(Date.parse(q.end.slice(0,10)+'T00:00:00Z')+86400000).toISOString().slice(0,10);
    a.period={start:q.start.slice(0,10)+' 00:00',end:next+' 00:00'};
    p.period={...a.period};p.primary.period={...a.period};
    if(scenario==='open-hour'||scenario==='wrong-hour-actual-period'){
     response.query.period={start:'2026-10-24 14:00',end:'2026-10-24 14:37'};
     a.period={...response.query.period};
     if(scenario==='wrong-hour-actual-period')a.period.end='2026-10-24 14:38';
     p.period={...a.period};p.primary.period={...a.period};
    }
    a.filters.date=[a.period.start,a.period.end];
    const number=key=>scenario==='zero'?0:native[key];
    for(const key of keys)a.metrics[key]={value:number(key),status:'available',source:'supplement',
     scope:a.scopeLabel,field:{newCustomers:'new_people',repeatRatePct:'repeat_rete',newCustomerSharePct:'new_people / total * 100'}[key],
     unit:key==='newCustomers'?'people':'percent',definition:key==='repeatRatePct'?'Admin native percentage; upstream numerator and denominator not published':key==='newCustomerSharePct'?'Admin new_people / Admin paid-order total * 100':'Admin native new_people'};
    a.metrics.orders={value:120,status:'available',source:'Admin',scope:a.scopeLabel};
    for(const [key,value]of Object.entries(supplemental))a.metrics[key]={value,status:'available',source:'supplement',scope:a.scopeLabel,unit:key.endsWith('Pct')?'percent':key.endsWith('Usd')?'USD':'people',field:'mock-native-'+key};
    if(scenario==='wrong-period')a.period={start:'2026-10-16 00:00',end:'2026-10-23 00:00'};
    if(scenario==='wrong-site'){a.normalisedScope='all-websites';a.filters.site='';a.scopeLabel='MOCK Admin whole-game native summary';}
    if(scenario==='unavailable')a.status='unavailable';
    if(scenario==='wrong-game')a.filters.game='506';
    if(scenario==='wrong-paid-status')a.filters.pay_status=0;
    if(scenario==='wrong-order-status')a.filters.order_status='3';
    if(scenario==='wrong-endpoint')a.endpoint='/admin/order.Order/unrelated';
    if(scenario==='missing-share')a.metrics.newCustomerSharePct={value:null,status:'not_provided',source:'Admin',scope:a.scopeLabel};
    return route.fulfill({json:response});
   }
   return route.continue();
  });
  await page.goto(url);await page.waitForFunction(()=>window.api&&window.lastState?.b_profile==='MMOEXP');
  const values=()=>Promise.all(keys.map(key=>page.locator(`[data-metric=${key}] strong`).innerText()));
  async function choose(changes={},kind='native'){
   scenario=kind;revision++;
   await page.evaluate(state=>window.api.apply(state),{...selection,...changes});
   // Force a fresh native summary even when only a detail filter changed; the
   // endpoint deliberately remains whole-game in the restricted-scope tests.
   await page.evaluate(()=>window.api.update());
   await page.waitForFunction(value=>document.querySelector('#app').shadowRoot.querySelector('.fc-state')?.textContent.includes('CASE-'+value),revision);
   await page.waitForFunction(value=>window.scope.summary?.profile?.key==='FC27'&&window.scope.summary.fixture_native_revision===value,revision);
   await page.waitForTimeout(120);
  }
  await check('all products and matching all-site period retain three Admin-native customer KPIs',async()=>{
   await choose();assert.deepEqual(await values(),expected);
   for(const key of keys){assert.match(await page.locator(`[data-metric=${key}] small`).innerText(),/Admin/);assert.doesNotMatch(await page.locator(`[data-metric=${key}] small`).innerText(),/站内客户ID.*未验证/);}
  });
  await check('matching MMOEXP main-site period retains three Admin-native customer KPIs',async()=>{
   await choose({b_site:'mmoexp',b_fc_site_group:'main'});assert.deepEqual(await values(),expected);
  });
  for(const [label,changes]of [
   ['specified product',{b_fc_product:'Players'}],['specified platform',{b_fc_platform:'PC'}],
   ['specified customer cohort',{b_fc_customer:'new'}],['specified amount bucket',{b_fc_bucket:'20-50'}],
   ['independent-site subset',{b_fc_site_group:'satellite'}]
  ])await check(label+' never borrows whole-game Admin-native totals',async()=>{
   await choose(changes);assert.deepEqual(await values(),['暂缺','暂缺','暂缺']);
   for(const [key,value]of Object.entries(supplementalText))assert.notEqual(await page.locator(`[data-metric=${key}] strong`).innerText(),value,key+' cannot borrow its native whole-game value');
  });
  await check('native summary from a different period cannot fill current FC cards',async()=>{
   await choose({},'wrong-period');assert.deepEqual(await values(),['暂缺','暂缺','暂缺']);
  });
  await check('all-site native summary cannot fill an MMOEXP-main selection',async()=>{
   await choose({b_site:'mmoexp',b_fc_site_group:'main'},'wrong-site');assert.deepEqual(await values(),['暂缺','暂缺','暂缺']);
  });
  await check('unavailable native source cannot revive its stored numeric fields',async()=>{
   await choose({},'unavailable');assert.deepEqual(await values(),['暂缺','暂缺','暂缺']);
  });
  for(const kind of ['wrong-game','wrong-paid-status','wrong-order-status','wrong-endpoint'])await check(kind+' native metadata cannot fill FC cards',async()=>{
   await choose({},kind);assert.deepEqual(await values(),['暂缺','暂缺','暂缺']);
  });
  await check('native zero values remain known zero rather than missing',async()=>{
   await choose({},'zero');assert.deepEqual(await values(),['0','0.00%','0.00%']);
  });
  await check('open hour ending at native 14:37 retains matching server-window metrics',async()=>{
   await choose({b_grain:'hour',b_start:'2026-10-24 14:00',b_end:'2026-10-24 14:00'},'open-hour');
   assert.deepEqual(await values(),expected);
  });
  await check('same raw hourly selection rejects mismatched actual native period',async()=>{
   await choose({b_grain:'hour',b_start:'2026-10-24 14:00',b_end:'2026-10-24 14:00'},'wrong-hour-actual-period');
   assert.deepEqual(await values(),['暂缺','暂缺','暂缺']);
  });
  await check('missing native share stays unknown and is not divided by identified customers',async()=>{
   await choose({},'missing-share');assert.deepEqual(await values(),['24','12.50%','暂缺']);
  });
  await check('native summary knowledge does not enable unverified list-level new/repeat cohorts',async()=>{
   await choose();
   assert.equal(await page.locator('[data-fc-content=consumption] .fc-consumption-legend').count(),0);
   assert.equal(await page.locator('[data-fc-content=consumption] .fc-bar-track [data-customer=new], [data-fc-content=consumption] .fc-bar-track [data-customer=returning]').count(),0);
  });
  await check('same-scope native supplemental metrics are preserved and retain units',async()=>{
   await choose();
   for(const [key,value]of Object.entries(supplementalText))assert.equal(await page.locator(`[data-metric=${key}] strong`).innerText(),value,key);
   assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'120','native fallback must not replace FC category order totals');
   assert.equal(await page.locator('[data-metric=revenueUsd] strong').innerText(),'$6,480.00','native fallback must not replace FC category sales');
  });
  assert.deepEqual(errors,[],'real renderer page errors');
  if(failures.length)throw new Error(failures.length+' native customer KPI checks failed:\n'+failures.join('\n'));
  console.log('FC Admin-native customer KPIs: exact scope, native definitions, zero/missing values and unverified list history passed');
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(error=>{console.error(error);server.closeAllConnections();server.close();process.exitCode=1;});
