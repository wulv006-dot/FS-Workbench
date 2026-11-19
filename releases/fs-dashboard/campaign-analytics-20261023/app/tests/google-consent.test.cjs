const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{chromium}=require('playwright');
test('Google tag requires a new explicit choice; denial, withdrawal, previews and verification do not transmit',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext(),page=await context.newPage(),requests=[];
  await page.route('**/*',async route=>{const url=new URL(route.request().url());requests.push(url.origin+url.pathname);if(url.hostname==='www.mmoexp.com')return route.fulfill({contentType:'text/html',body:'<html><head></head><body><header class="site-header"></header><main id="fc-activity"></main><footer class="site-footer"></footer></body></html>'});return route.fulfill({contentType:'application/javascript',body:''});});
  await page.goto('https://www.mmoexp.com/events/seasonal/?private=private-email@example.test');
  await page.evaluate(()=>{
   localStorage.setItem('mmoexp-event-analytics-consent-v1','granted');
   window.FC_ACTIVITY_CONFIG={mode:'preview'};window.FC_ANALYTICS_CONFIG={seasonalEnabled:true,projectToken:'fixture',allowedHosts:['www.mmoexp.com'],registry:[{id:'mmoexp-seasonal',view:'seasonal'}]};
  });
  await page.addScriptTag({path:path.resolve(__dirname,'../seasonal/activity-analytics.js')});
  const publication={schema_version:1,release_id:'campaign-preview-999',config_hash:'a'.repeat(64),pages:[{page_id:'seasonal-vault',activity_id:'mmoexp-seasonal',active:true}],products:[],halloween:{status:'configured',starts_at:'2020-01-01T00:00:00Z',ends_at:'2030-01-01T00:00:00Z',games:[]}};
  await page.evaluate(detail=>window.dispatchEvent(new CustomEvent('seasonal-published-catalog',{detail})),publication);
  assert.equal(await page.locator('#seasonal-analytics-choice').isVisible(),true,'Old PostHog consent does not authorize the newly named Google service');
  assert.equal(requests.filter(u=>u.includes('googletagmanager.com')).length,0);
  await page.getByRole('button',{name:'No thanks',exact:true}).click();assert.equal(requests.filter(u=>u.includes('googletagmanager.com')).length,0);
  await page.getByRole('button',{name:'Analytics preferences',exact:true}).click();await page.getByRole('button',{name:'Allow analytics',exact:true}).click();
  await page.waitForFunction(()=>window.dataLayer?.some(a=>a[0]==='event'&&a[1]==='page_view'));
  assert.equal(requests.filter(u=>u.includes('googletagmanager.com')).length,1);
  assert.equal(await page.evaluate(()=>window['ga-disable-G-L67DEVB5XN']),false);
  assert(!await page.evaluate(()=>JSON.stringify(window.dataLayer).includes('private-email')));
  const visits=await page.evaluate(()=>window.dataLayer.filter(a=>a[0]==='event'&&a[1]==='activity_view').length);
  await page.evaluate(()=>window.dispatchEvent(new StorageEvent('storage',{key:'mmoexp-event-google-consent-v1',newValue:'granted'})));
  assert.equal(await page.evaluate(()=>window.dataLayer.filter(a=>a[0]==='event'&&a[1]==='activity_view').length),visits,'Google-only preference sync must not create another PostHog visit');
  await page.evaluate(detail=>window.dispatchEvent(new CustomEvent('seasonal-published-catalog',{detail})),publication);
  assert.equal(await page.evaluate(()=>window.dataLayer.filter(a=>a[0]==='event'&&a[1]==='page_view').length),1);
  await page.getByRole('button',{name:'Analytics preferences',exact:true}).click();await page.getByRole('button',{name:'No thanks',exact:true}).click();
  assert.equal(await page.evaluate(()=>window['ga-disable-G-L67DEVB5XN']),true);
  const count=await page.evaluate(()=>window.dataLayer.filter(a=>a[0]==='event').length);
  await page.evaluate(()=>window.FCActivityAnalytics.offer('game_select',{game_id:'456'}));assert.equal(await page.evaluate(()=>window.dataLayer.filter(a=>a[0]==='event').length),count);
  for(const url of ['https://www.mmoexp.com/events/draft/','https://www.mmoexp.com/events/seasonal/?analytics_test=1']){
   const before=requests.filter(u=>u.includes('googletagmanager.com')).length;await page.goto(url);
   await page.evaluate(()=>{localStorage.setItem('mmoexp-event-analytics-consent-v1','granted');localStorage.setItem('mmoexp-event-google-consent-v1','granted');window.FC_ACTIVITY_CONFIG={mode:'preview'};window.FC_ANALYTICS_CONFIG={seasonalEnabled:true,projectToken:'fixture',allowedHosts:['www.mmoexp.com'],registry:[{id:'mmoexp-seasonal',view:'seasonal'}]};});
   await page.addScriptTag({path:path.resolve(__dirname,'../seasonal/activity-analytics.js')});await page.evaluate(detail=>window.dispatchEvent(new CustomEvent('seasonal-published-catalog',{detail})),publication);await page.waitForTimeout(50);
   assert.equal(requests.filter(u=>u.includes('googletagmanager.com')).length,before,'Draft and marked verification never load Google');
  }
  for(const nativeTag of [false,true]){
   await page.goto('https://www.mmoexp.com/events/seasonal/');
   await page.evaluate(nativeTag=>{
    localStorage.setItem('mmoexp-event-analytics-consent-v1','denied');localStorage.setItem('mmoexp-event-google-consent-v1','denied');
    window.FC_ACTIVITY_CONFIG={mode:'preview'};window.FC_ANALYTICS_CONFIG={seasonalEnabled:true,projectToken:'fixture',allowedHosts:['www.mmoexp.com'],registry:[{id:'mmoexp-seasonal',view:'seasonal'}]};
    window.dataLayer=[];
    if(nativeTag){const tag=document.createElement('script');tag.src='https://www.googletagmanager.com/gtag/js?id=AW-18230729339&gtg_health=1';document.head.append(tag);}
    else window.gtag=function(){window.dataLayer.push(arguments);};
   },nativeTag);
   await page.addScriptTag({path:path.resolve(__dirname,'../seasonal/activity-analytics.js')});await page.evaluate(detail=>window.dispatchEvent(new CustomEvent('seasonal-published-catalog',{detail})),publication);
   await page.getByRole('button',{name:'Analytics preferences',exact:true}).click();await page.getByRole('button',{name:'Allow analytics',exact:true}).click();
   await page.waitForFunction(()=>window.dataLayer.some(a=>a[0]==='event'&&a[1]==='page_view'));
   await page.getByRole('button',{name:'Analytics preferences',exact:true}).click();await page.getByRole('button',{name:'No thanks',exact:true}).click();
   assert.equal(await page.evaluate(()=>window['ga-disable-G-L67DEVB5XN']),true);
   const consent=await page.evaluate(()=>window.dataLayer.filter(a=>a[0]==='consent').map(a=>Array.from(a)));
   assert.deepEqual(consent,[['consent','update',{analytics_storage:'granted'}]],'Existing Google function or tag retains its global defaults and withdrawal state');
  }
  await page.close();
 }finally{await browser.close();}
});


test('Carnival sends the clean Carnival URL and activity only after consent',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage(),url='https://www.mmoexp.com/events/Carnival.html';
  await page.route('**/*',route=>route.fulfill(new URL(route.request().url()).hostname==='www.mmoexp.com'
   ?{contentType:'text/html',body:'<html><head></head><body><header class="site-header"></header><main id="fc-activity"></main></body></html>'}
   :{contentType:'application/javascript',body:''}));
  await page.goto(url+'?utm_source=fixture&private=private-email@example.test');
  await page.evaluate(()=>{
   window.FC_ACTIVITY_CONFIG={mode:'preview'};
   window.FC_ANALYTICS_CONFIG={projectToken:'fixture',allowedHosts:['www.mmoexp.com']};
  });
  await page.addScriptTag({path:path.resolve(__dirname,'../seasonal/activity-analytics.js')});
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('carnival:schedule',{detail:{
   starts_at:'2020-01-01T00:00:00Z',ends_at:'2030-01-01T00:00:00Z'
  }})));
  assert.equal(await page.evaluate(()=>window.dataLayer?.length||0),0);
  await page.getByRole('button',{name:'Allow analytics',exact:true}).click();
  await page.waitForFunction(()=>window.dataLayer?.some(a=>a[0]==='event'&&a[1]==='activity_view'));
  const calls=await page.evaluate(()=>window.dataLayer.filter(a=>['event','config'].includes(a[0])).map(a=>[a[1],a[2]]));
  assert.equal(calls.filter(([name])=>name==='page_view').length,1);
  for(const name of ['G-L67DEVB5XN','page_view','activity_view']){
   const payload=calls.find(([key])=>key===name)?.[1];
   assert.equal(payload?.page_location,url);
   if(name!=='G-L67DEVB5XN')assert.equal(payload?.activity_id,'mmoexp-carnival');
  }
  assert.equal(calls[0][1].campaign_source,'fixture');
  assert(!JSON.stringify(calls).includes('private-email'));
 }finally{await browser.close();}
});
