const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'provider54-')),real=global.fetch;
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');process.env.CAMPAIGN_ORIGIN='http://127.0.0.1:8534';
 global.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':'synthetic','x-auth-role':'admin'}}):real(url,options);
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(8534,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:'chrome'}),page=await browser.newPage(),requests=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')requests.push(r.postDataJSON());});
 let fail=false;
 await page.route('**/api/center/backend-read',route=>route.fulfill(fail?{status:504,json:{code:'CATALOG_SEARCH_TIMEOUT'}}:{json:{status:'ok',data:{items:[{model_id:'123',title:'Synthetic only'}],coverage:{complete:false,reason:'bounded'},available:false}}}));
 try{
  const base='http://127.0.0.1:8534/dashboard/analytics/campaigns/analytics/';
  await page.goto(base+'products.html');await page.waitForFunction(()=>document.querySelector('#page-select').disabled===false);
  const before=await(await real(base+'api/center')).json();
  await page.locator('#page-select').selectOption('seasonal-vault');assert.equal(await page.locator('[data-h-read]').count(),8);
  await page.locator('[data-h-category="0"]').fill('9623');await page.locator('[data-h-read="pool"][data-h-index="0"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-h-observation="0"]').textContent.includes('Synthetic only'));
  assert.deepEqual(requests[0],{action:'model_category_pool',site_id:'266',game_id:'1327',category_id:'9623',max_pages:1,page_size:10,resolve_associations:true,exclude_model_ids:[]});
  fail=true;await page.locator('[data-h-read="pool"][data-h-index="0"]').click();await page.waitForFunction(()=>document.querySelector('[data-h-observation="0"]').textContent.includes('CATALOG_SEARCH_TIMEOUT'));
  const after=await(await real(base+'api/center')).json();assert.deepEqual(after.draft,before.draft);assert.equal(after.revision,before.revision);assert(requests.every(r=>r.action==='model_category_pool'));assert.deepEqual(errors,[]);
  console.log('PASS synthetic editor readonly provider/pool request, bounded scope, visible failure, unchanged draft/revision; no Admin network');
 }finally{await browser.close();await new Promise(r=>server.close(r));global.fetch=real;}
})().catch(e=>{console.error(e);process.exitCode=1;});
