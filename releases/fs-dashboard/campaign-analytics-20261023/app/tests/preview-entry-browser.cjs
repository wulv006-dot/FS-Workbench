const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'preview-entry-')),real=global.fetch;
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');
 process.env.CAMPAIGN_ORIGIN='http://127.0.0.1:8531';
 global.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':'fixture','x-auth-role':'admin'}}):real(url,options);
 const {initialCenterDraft}=await import('../analytics/center-store.mjs');fs.mkdirSync(path.join(dir,'center'));fs.writeFileSync(path.join(dir,'center/state.json'),JSON.stringify({revision:0,draft:initialCenterDraft(),published:null}));
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(8531,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true}),context=await browser.newContext(),page=await context.newPage(),base='http://127.0.0.1:8531/dashboard/analytics/campaigns/analytics/',writes=[];
 context.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))writes.push(r.method()+' '+r.url());});
 // Public destination is a read-only fixture: assert actual clicked URL, not production content.
 await context.route('**/events/**',r=>r.fulfill({contentType:'text/html',body:'<h1>Public route fixture</h1>'}));
 try{
  await page.goto(base);await page.getByRole('link',{name:'体验活动页 ↗',exact:true}).click();
  assert.equal(new URL(page.url()).pathname,'/dashboard/analytics/campaigns/analytics/products.html');
  await page.waitForFunction(()=>document.querySelector('#center-status').textContent.includes('已读取'));
  const state=path.join(dir,'center/state.json'),before=fs.readFileSync(state,'utf8');
  for(const [id,route] of [['fc27-weekly','Weekly-Scout.html'],['fc27-sbc','Sbc-Companions.html'],['fc27-trio','Player-Trio.html'],['seasonal-vault','seasonal/index.html'],['fc27-weekly','Weekly-Scout.html'],['seasonal-vault','seasonal/index.html']]){
   await page.locator('#page-select').selectOption(id);
   const opened=context.waitForEvent('page');await page.locator('#preview-page').click();const preview=await opened;await preview.waitForLoadState();
   assert.equal(new URL(preview.url()).pathname,'/events/'+route);assert.equal(new URL(preview.url()).search,'');await preview.close();
  }
  assert.equal(fs.readFileSync(state,'utf8'),before);assert.deepEqual(writes,[]);
  assert.match(await page.locator('#page-preview').innerText(),/不会保存或发布当前草稿/);
  console.log('PASS analysis entry -> unique editor -> four selected public routes, FC/Seasonal switch, no write or draft change; public destination fixture only');
 }finally{await browser.close();await new Promise(r=>server.close(r));global.fetch=real;fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
