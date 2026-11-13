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
const allNativeExpected={newCustomers:'24',repeatRatePct:'12.50%',newCustomerSharePct:'20.00%',...supplementalText};
const selection={b_site:'all',b_profile:'FC27',b_group:'sports',b_grain:'day',b_range:'custom',b_start:'2026-10-17',b_end:'2026-10-23',b_fc_product:'all',b_fc_platform:'all',b_fc_site_group:'all',b_fc_customer:'all',b_fc_bucket:'all'};
const failures=[];
async function check(name,run){try{await run();console.log('PASS '+name);}catch(error){failures.push(name+': '+error.message);console.error('FAIL '+name+': '+error.message);}}
(async()=>{
 const url=await serve(),browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage(),errors=[],cacheResponses=[];let revision=0,scenario='native';
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
    // The shared fixture's refresh=true path adds an unrelated 800ms delay.
    // These are source-contract checks; retain the request metadata but obtain
    // its fictional base envelope without that race-test delay.
    const upstreamURL=new URL(request);upstreamURL.searchParams.delete('refresh');
    const requestedRevision=revision,upstream=await route.fetch({url:upstreamURL.href}),response=await upstream.json(),p=response.profile,a=p.supplement;
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
    if(scenario==='cache-cutoff-first'||scenario==='cache-cutoff-advanced'){
     // SummaryCache.key_of excludes period. get_live returns the new request
     // cutoff while both profile.period and the cached source retain a.period.
     // This is a valid cache hit, not an arbitrary profile/source mismatch.
     const advanced=scenario==='cache-cutoff-advanced';
     response.query.period={start:'2026-10-24 13:00',end:advanced?'2026-10-24 14:39':'2026-10-24 14:37'};
     a.period={start:'2026-10-24 13:00',end:'2026-10-24 14:37'};
     p.period={...a.period};p.primary.period={...a.period};
     a.capturedAt='2026-10-24T06:37:00+00:00';a.sourceDataAsOf=null;a.asOfStatus='not_provided_by_upstream';a.stale=false;
     response.generatedAt=a.capturedAt;response.status='available';response.stale=false;
     response.origin='live-cache';response.cachePolicy='today';response.refreshSeconds=600;
     response.clientCheckSeconds=600;response.expiresInSeconds=advanced?598:600;response.consistentPeriod=true;
     response.sources.Admin={...response.sources.Admin,status:'available',stale:false,capturedAt:a.capturedAt,sourceDataAsOf:null,asOfStatus:'upstream_watermark_unknown'};
     cacheResponses.push({raw:{start:q.start,end:q.end,grain:q.grain},requestRefresh:q.refresh||null,actual:{...response.query.period},profile:{...p.period},admin:{...a.period},rangeId:response.rangeId,capturedAt:a.capturedAt});
    }
    if(scenario.startsWith('hour-boundary-')){
     response.query.period={start:'2026-10-24 14:00',end:'2026-10-24 14:37'};
     a.period={...response.query.period};
     if(scenario==='hour-boundary-wrong-start')a.period.start='2026-10-24 13:59';
     if(scenario==='hour-boundary-empty-request')response.query.period={};
     if(scenario==='hour-boundary-partial-request')response.query.period={start:'2026-10-24 14:00'};
     if(scenario==='hour-boundary-reversed-request')response.query.period.end='2026-10-24 13:59';
     if(scenario==='hour-boundary-beyond-selected-hour'){a.period.end='2026-10-24 15:01';response.query.period.end=a.period.end;}
     if(scenario==='hour-boundary-closed-no-request'){delete response.query.period;a.period.end='2026-10-24 15:00';}
     if(scenario==='hour-boundary-open-no-request')delete response.query.period;
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
    if(scenario==='split-repeat'){
     a.metrics.repeatRatePct.value=4.33;
     a.native_repeat_rate={value:4.33,status:'available'};
     a.reconciliation_status='not_aligned';
     a.effective_scope={site:main?'266':'all',game:'1327',country_code:'all',period:a.period};
     a.local_repeat_rate={value:100*13/280,numerator:13,denominator:280,status:'available',
      scope:{scope:'site',scope_id:'266',game:'1327',start:'2026-10-17T00:00:00+08:00',end_exclusive:'2026-10-24T00:00:00+08:00'}};
    }
    return route.fulfill({json:response});
   }
   return route.continue();
  });
  await page.goto(url);await page.waitForFunction(()=>window.api&&window.lastState?.b_profile==='MMOEXP');
  const values=()=>Promise.all(keys.map(key=>page.locator(`[data-metric=${key}] strong`).innerText()));
  const allNativeValues=async()=>Object.fromEntries(await Promise.all(Object.keys(allNativeExpected).map(async key=>[key,await page.locator(`[data-metric=${key}] strong`).innerText()])));
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
  await check('native rate and identified period-cohort ratio stay distinct',async()=>{
   await choose({b_site:'mmoexp',b_fc_site_group:'main'},'split-repeat');
   const card=page.locator('[data-metric=repeatRatePct]');
   assert.equal(await card.locator('span').innerText(),'Admin原生复购率');
   assert.equal(await card.locator('strong').innerText(),'4.33%');
   const audit=page.locator('.metric-audit');
   await audit.locator('summary').click();
   assert.match(await audit.innerText(),/区间复购用户占比 4.64%（13 \/ 280 人）.*MMOEXP主站.*FC 27|区间复购用户占比 4.64%（13 \/ 280 人）.*MMOEXP主站.*FC27/);
   assert.match(await audit.textContent(),/仍待对账/);
  });
  await check('FC platform and website selections cannot present a whole-game local rate as their own',async()=>{
   for(const filters of [{b_site:'mmoexp',b_fc_site_group:'main',b_fc_platform:'PC'},
                         {b_site:'all',b_fc_site_group:'all'}]){
    await choose(filters,'split-repeat');
    const audit=page.locator('.metric-audit');
    await audit.evaluate(node=>{node.open=true;});
    assert.doesNotMatch(await audit.innerText(),/4\.64%|13 \/ 280/);
   }
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
  await check('advancing request cutoff retains all eleven metrics from a valid unchanged hourly cache',async()=>{
   const raw={b_grain:'hour',b_start:'2026-10-24 13:00',b_end:'2026-10-24 14:00'};
   await choose(raw,'cache-cutoff-first');assert.deepEqual(await allNativeValues(),allNativeExpected);
   scenario='cache-cutoff-advanced';revision++;
   // Invalidate only the browser cache. An explicit api.update would send
   // refresh=true and would test an upstream reload rather than this cache hit.
   await page.evaluate(()=>{window.scope.window.FSExactRange.force(false);window.api.apply(window.api.state());});
   await page.waitForFunction(value=>window.scope.summary?.fixture_native_revision===value,revision);
   await page.waitForTimeout(120);
   const last=cacheResponses.at(-1),first=cacheResponses.find(row=>row.actual.end==='2026-10-24 14:37');
   assert.deepEqual(last.raw,first.raw);assert.equal(last.requestRefresh,null);
   assert.equal(last.rangeId,first.rangeId);assert.equal(last.capturedAt,first.capturedAt);
   assert.deepEqual(last.profile,first.profile);assert.deepEqual(last.admin,first.admin);
   assert.equal(last.actual.end,'2026-10-24 14:39');assert.equal(last.admin.end,'2026-10-24 14:37');
   assert.deepEqual(await allNativeValues(),allNativeExpected);
   for(const key of Object.keys(allNativeExpected)){
    const label=await page.locator(`[data-metric=${key}] small`).innerText();
    assert.match(label,/统计截至 2026-10-24 14:37/);assert.doesNotMatch(label,/14:39|旧采集值/);
   }
  });
  await check('actual native cutoff beyond current request cutoff is rejected',async()=>{
   await choose({b_grain:'hour',b_start:'2026-10-24 14:00',b_end:'2026-10-24 14:00'},'wrong-hour-actual-period');
   assert.deepEqual(await allNativeValues(),Object.fromEntries(Object.keys(allNativeExpected).map(key=>[key,'暂缺'])));
  });
  for(const kind of ['wrong-start','empty-request','partial-request','reversed-request','beyond-selected-hour','open-no-request'])await check('hour boundary '+kind+' rejects all native metrics',async()=>{
   await choose({b_grain:'hour',b_start:'2026-10-24 14:00',b_end:'2026-10-24 14:00'},'hour-boundary-'+kind);
   assert.deepEqual(await allNativeValues(),Object.fromEntries(Object.keys(allNativeExpected).map(key=>[key,'暂缺'])));
  });
  await check('missing request.period accepts only the exact closed final hour',async()=>{
   await choose({b_grain:'hour',b_start:'2026-10-24 14:00',b_end:'2026-10-24 14:00'},'hour-boundary-closed-no-request');
   assert.deepEqual(await allNativeValues(),allNativeExpected);
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
   assert.equal(await page.locator('[data-metric=orders] strong').innerText(),'120','unfiltered order total uses native summary');
   assert.equal(await page.locator('[data-metric=revenueUsd] strong').innerText(),'$1,000.00','unfiltered sales use native summary independently of detail totals');
  });
  assert.deepEqual(errors,[],'real renderer page errors');
  if(failures.length)throw new Error(failures.length+' native customer KPI checks failed:\n'+failures.join('\n'));
  console.log('FC Admin-native customer KPIs: exact scope, native definitions, zero/missing values and unverified list history passed');
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(error=>{console.error(error);server.closeAllConnections();server.close();process.exitCode=1;});
