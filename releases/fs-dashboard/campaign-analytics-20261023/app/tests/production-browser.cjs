const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-ui-')),real=global.fetch;
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_ORIGIN='http://127.0.0.1:8523';
 global.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':'fixture','x-auth-role':options.headers.Cookie.includes('viewer')?'readonly':'admin'}}):real(url,options);
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(8523,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true}),page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));const base='http://127.0.0.1:8523/dashboard/analytics/campaigns/';
 try{
  await page.goto(base+'analytics/');await page.waitForSelector('.metric');assert.match(await page.locator('#registry-note').innerText(),/服务器/);
  await page.getByRole('link',{name:'商品编辑与预览',exact:true}).click();await page.waitForSelector('#page-select');assert.equal(page.url(),base+'analytics/products.html');assert.equal(await page.locator('#page-select option').count(),4);
  await page.locator('#page-select').selectOption('seasonal-vault');assert.equal(await page.locator('#seasonal-theme-label').isVisible(),true);assert.equal(await page.locator('#discover-search').isVisible(),true);
  assert.equal(fs.existsSync(path.join(dir,'center','state.json')),false);await page.goto(base+'analytics/center.html');await page.waitForSelector('#page-select');assert.equal(page.url(),base+'analytics/products.html');


  await page.goto(base+'analytics/products.html');await page.waitForSelector('[data-layout-list=weekly]');
  const originalCatalog=await (await real(base+'analytics/api/catalog')).json();
  const removedId=await page.locator('[data-layout-list=weekly]:checked').first().getAttribute('value');await page.locator('[data-layout-list=weekly][value="'+removedId+'"]').uncheck();await page.locator('#save-center').click();await page.waitForFunction(()=>document.querySelector('#center-status').textContent.includes('草稿已保存'));
  const before=JSON.parse(fs.readFileSync(path.join(dir,'center','state.json')));assert.equal(before.revision,1);assert.equal(fs.existsSync(path.join(dir,'state.json')),false);
  await page.reload();await page.waitForSelector('[data-layout-list=weekly]');assert.equal(await page.locator('[data-layout-list=weekly]:checked').count(),before.draft.fc_layout.weekly.length);
  assert.deepEqual((await (await real(base+'analytics/api/catalog')).json()).layout,originalCatalog.layout); // data-page legacy store not changed
  for(const width of [1440,390])for(const theme of ['light','dark']){await page.setViewportSize({width,height:900});await page.evaluate(t=>document.documentElement.dataset.fsTheme=t,theme);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  await page.context().addCookies([{name:'role',value:'viewer',url:'http://127.0.0.1:8523'}]);await page.reload();await page.waitForSelector('[data-layout-list=weekly]');assert.equal(await page.locator('#save-center').isDisabled(),true);
  assert.deepEqual(errors,[]);console.log('PASS production editor: save/read/preview, readonly, 4 responsive-theme cases; mocked authentication only');
 }finally{await browser.close();await new Promise(r=>server.close(r));global.fetch=real;fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
