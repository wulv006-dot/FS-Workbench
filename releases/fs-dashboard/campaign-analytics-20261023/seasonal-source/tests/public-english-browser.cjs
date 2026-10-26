const modelFixture=require('./model-fixture.cjs');
// Isolated local fixtures only. No registration, reward or commerce mutation is sent.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict'),vm=require('node:vm');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../../app'),box={};vm.runInNewContext(fs.readFileSync(path.join(root,'seasonal/campaign-data.js'),'utf8'),box);
const keys=box.SeasonalData.products.map(p=>'seasonal-'+p.id),han='\u4e2d\u6587';
const server=http.createServer((req,res)=>{const file=path.resolve(root,req.url.split('?')[0].replace(/^\/events\//,''));if(!file.startsWith(root+path.sep)){res.writeHead(404).end();return;}fs.readFile(file,(e,b)=>{if(e){res.writeHead(404).end();return;}res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(b);});});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage(),errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
    let testStatus=200,connectionFails=false,specRequired=true;
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());if(url.hostname!=='127.0.0.1'){external.push(url.origin);await route.abort();return;}
      if(url.pathname==='/analytics/api/connection'){if(connectionFails){await route.abort();return;}await route.fulfill({json:{csrf:'fixture'}});return;}
      if(url.pathname==='/analytics/api/test-event'){await route.fulfill({status:testStatus,json:{}});return;}
      if(url.pathname.includes('/api/campaign/')){
        let data,status=200;
        if(url.pathname.endsWith('/config'))data={release_id:'english-fixture',seasonal_theme:'christmas',seasonal_model_contracts:{'seasonal-fc-1':modelFixture()},pages:[{page_id:'seasonal-vault',activity_id:'mmoexp-seasonal',rule_version:'r1',benefit_binding_version:'b1',product_keys:[...keys,'extra-preview','fixture-console-east']}],products:[{key:'fixture-console-east',available:true,quantity:{unit:'fixture-unit',min:'10'}},{key:'extra-preview',title:han,preview_only:true,available:false,product_ref:{game_id:'1327',goods_id:'999',model_id:'888'},platform:{attribute_id:'777'}}]};
        else if(url.pathname.endsWith('/capabilities'))data={integration_mode:'preview',live_checkout:false};
        else if(url.pathname.endsWith('/intents')){if(specRequired){status=422;data={code:'SPEC_REQUIRED',message:han};}else data={intent_id:'intent-original',operation_id:'operation-original'};}
        else {status=503;data={code:'NETWORK_UNKNOWN',message:han};}
        await route.fulfill({status,json:data});return;
      }
      await route.continue();
    });
    async function english(state){const text=await page.locator('body').innerText(),attrs=await page.locator('[aria-label],[alt],[title],[placeholder]').evaluateAll(els=>els.map(e=>['aria-label','alt','title','placeholder'].map(a=>e.getAttribute(a)||'').join(' ')).join(' '));assert.doesNotMatch(text+' '+attrs+' '+await page.title(),/\p{Script=Han}/u,state);}
    await page.goto(`http://127.0.0.1:${server.address().port}/events/seasonal/index.html?analytics_test=1`);
    await page.waitForSelector('[data-id="extra-preview"]');assert.match(await page.locator('[data-id="extra-preview"] h3').innerText(),/FC 27 catalog product/);
    for(const theme of Object.keys(box.SeasonalData.themes)){await page.selectOption('#theme-select',theme);await english('theme '+theme);}
    await page.click('[data-action=cart]');await english('empty bag');await page.click('[data-action=close]');
    await page.click('[data-action=pool]');for(const input of await page.locator('[name=pool-game]').all())await input.uncheck();await page.click('[data-action=save-pool]');await english('pool validation error');await page.check('[name=pool-game][value=fc]');await page.click('[data-action=save-pool]');await page.click('[data-filter=nba]');await english('empty draw');
    await page.click('[data-action=invite]');await page.click('details.simulation summary');await english('invite demo');await page.click('[data-demo-receipt=DEMO-1]');await page.click('#event-dialog [data-action=account]');await english('sign in and register panel');await page.click('[data-action=close]');
    await page.locator('#fixed-products [data-product=fc-1]').click();await english('pack');await page.selectOption('#model-option-platform','console');await page.selectOption('#model-option-server','east');await page.selectOption('#model-option-spec','normal');await page.fill('#model-quantity','20');await page.click('[data-bag-add=fc-1]');await english('bag');await page.click('[data-action=store-quote]');await page.waitForFunction(()=>document.querySelector('#store-status').textContent.includes('requires product specifications'));await english('server error');await page.click('[data-action=store-lookup]');await english('missing operation');specRequired=false;await page.click('[data-action=store-quote]');await page.waitForFunction(()=>document.querySelector('#store-status').textContent.includes('pending or unknown'));await english('unknown quote');await page.click('[data-action=store-lookup]');await english('unknown recovery');await page.click('[data-action=close]');
    await page.locator('#analytics-diagnostics').focus();await page.keyboard.press('Enter');await english('diagnostics');await page.click('[data-action=close]');
    testStatus=503;await page.selectOption('#theme-select','halloween');await page.waitForFunction(()=>document.querySelector('#analytics-test-banner').textContent.includes('unconfirmed'));await english('test banner failure');
    connectionFails=true;await page.reload();await page.waitForFunction(()=>document.querySelector('#analytics-test-banner').textContent.includes('connection unavailable'));await english('test connection failure');
    await page.goto(`http://127.0.0.1:${server.address().port}/events/seasonal/creative-kit.html`);for(const theme of Object.keys(box.SeasonalData.themes)){await page.selectOption('#kit-theme',theme);await english('creative kit '+theme);}
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);console.log('PASS English browser: four themes, legacy Chinese catalog fallback, bag/invite/register/empty/error/diagnostics/test banners, linked creative kit; no Han text or external calls.');
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
