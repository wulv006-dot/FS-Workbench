const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-ui-')),real=global.fetch;
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_ORIGIN='http://127.0.0.1:8523';
 global.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':'fixture','x-auth-role':options.headers.Cookie.includes('viewer')?'readonly':'admin'}}):real(url,options);
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(8523,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true}),page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));const base='http://127.0.0.1:8523/dashboard/analytics/campaigns/';
 try{
  await page.goto(base+'analytics/');await page.waitForSelector('.metric');assert.match(await page.locator('#registry-note').innerText(),/服务器/);
  await page.goto(base+'analytics/products.html');await page.waitForSelector('input[name=weekly]');
  await page.locator('input[name=weekly]:checked').first().uncheck();await page.locator('#save-products').click();await page.waitForFunction(()=>document.querySelector('#product-status').textContent.includes('已保存服务器'));
  const before=JSON.parse(fs.readFileSync(path.join(dir,'state.json')));assert.equal(before.revision,1);
  await page.reload();await page.waitForSelector('input[name=weekly]');assert.equal(await page.locator('input[name=weekly]:checked').count(),before.layout.weekly.length);
  for(const width of [1440,390])for(const theme of ['light','dark']){await page.setViewportSize({width,height:900});await page.evaluate(t=>document.documentElement.dataset.fsTheme=t,theme);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  await page.goto(base);assert.deepEqual(await page.evaluate(()=>FC_ACTIVITY_CONFIG.weekly.ids),before.layout.weekly);assert.equal(await page.evaluate(()=>FC_ACTIVITY_CONFIG.mode),'preview');
  await page.context().addCookies([{name:'role',value:'viewer',url:'http://127.0.0.1:8523'}]);await page.goto(base+'analytics/products.html');await page.waitForSelector('input[name=weekly]');assert.equal(await page.locator('#save-products').isDisabled(),true);
  assert.deepEqual(errors,[]);console.log('PASS production editor: save/read/preview, readonly, 4 responsive-theme cases; mocked authentication only');
 }finally{await browser.close();await new Promise(r=>server.close(r));global.fetch=real;fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
