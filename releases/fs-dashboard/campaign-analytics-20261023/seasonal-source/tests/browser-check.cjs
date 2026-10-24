// Local browser evidence with explicit test fixtures, never a production transaction.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'../../app');
const server=http.createServer((req,res)=>{
  const file=path.resolve(root,req.url.split('?')[0].replace(/^\/events\//,''));
  if(!file.startsWith(root+path.sep)){res.writeHead(404).end();return;}
  fs.readFile(file,(e,data)=>{if(e){res.writeHead(404).end();return;}res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(data);});
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    let failure='MAIN_INTEGRATION_REQUIRED',intents=0,lookup=0;
    await page.route('**/api/campaign/**',async route=>{
      const url=route.request().url(),request=route.request();let body,status=200;
      if(url.endsWith('/config'))body={seasonal_theme:'christmas',pages:[{page_id:'seasonal-vault',activity_id:'mmoexp-seasonal',rule_version:'r1',benefit_binding_version:'b1',product_keys:['seasonal-fc-1']}],products:[{key:'seasonal-fc-1',available:true,quantity:{unit:'K',min:'100'}}]};
      else if(url.endsWith('/capabilities'))body={integration_mode:'preview',live_checkout:false};
      else if(url.endsWith('/intents')){intents++;assert.equal(request.postDataJSON().lines[0].quantity.value,'100');if(failure==='SPEC_REQUIRED'){status=422;body={code:failure};}else body={intent_id:'intent-original',operation_id:'operation-original'};}
      else if(url.endsWith('/quote')){status=503;body={code:failure};}
      else {lookup++;body={status:'unknown'};}
      await route.fulfill({status,json:body});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/events/seasonal/index.html`);
    await page.waitForFunction(()=>document.documentElement.dataset.theme==='christmas');
    assert.equal(await page.locator('#products .product').count(),8);
    for(const theme of ['halloween','thanksgiving','black-friday','christmas']){await page.selectOption('#theme-select',theme);assert.equal(await page.locator('html').getAttribute('data-theme'),theme);}
    await page.check('#skip-animation');await page.click('[data-action=reveal-all]');assert.match(await page.locator('#reveal-count').innerText(),/^8 \/ 8/);
    await page.locator('[data-keep]').first().click();assert.match(await page.locator('#kept-count').innerText(),/^1 kept/);
    await page.click('[data-action=invite]');await page.click('details.simulation summary');await page.click('[data-demo-receipt=DEMO-1]');assert.equal(await page.locator('#key-count').innerText(),'1');await page.click('[data-action=close]');
    await page.click('[data-action=refresh]');await page.click('[data-action=confirm-refresh]');assert.equal(await page.locator('#key-count').innerText(),'0');assert.equal(await page.locator('#kept-count').innerText(),'1 kept');
    await page.locator('#fixed-products [data-product=fc-1]').click();await page.click('[data-bag-add=fc-1]');
    await page.click('[data-action=store-quote]');await page.waitForFunction(()=>document.querySelector('#store-status').textContent.includes('Main-site cart integration'));
    assert.equal(await page.locator('[data-action=store-prepare]').isVisible(),false);
    failure='SPEC_REQUIRED';await page.click('[data-action=store-quote]');await page.waitForFunction(()=>document.querySelector('#store-status').textContent.includes('requires product specifications'));
    failure='NETWORK_UNKNOWN';await page.click('[data-action=store-quote]');await page.click('[data-action=store-lookup]');await page.waitForFunction(()=>document.querySelector('#store-status').textContent.includes('pending or unknown'));
    const before=intents;await page.click('[data-action=store-quote]');assert.equal(intents,before);assert.equal(lookup,1);assert.deepEqual(errors,[]);
    console.log('PASS browser: four themes, published theme, reveal, keep, demo receipt, refresh, exact base quantity, preview refusal, missing specs, original-ID lookup and pending no-resubmit; no page errors.');
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
