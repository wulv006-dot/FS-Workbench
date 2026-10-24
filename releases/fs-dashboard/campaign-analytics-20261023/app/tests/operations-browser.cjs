const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true}),page=await browser.newPage();page.setDefaultTimeout(5000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const app=path.resolve(__dirname,'..');
 let readonly=false,allowed=false,drop=true,writeIDs=[],reconcileIDs=[],title='Original',summaryCount=0;
 await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());if(url.origin!=='http://127.0.0.1:8597')return route.abort();
  if(url.pathname==='/analytics/api/center')return route.fulfill({json:{csrf:'fixture',canEdit:!readonly}});
  if(url.pathname.includes('/api/center/backend-')){const body=req.postDataJSON();assert.equal(req.headers()['x-csrf-token'],'fixture');assert.equal(body.site_id,'266');
   if(body.action==='benefit_detail')return route.fulfill({json:{status:'ok',data:{kind:'coupon',native_id:body.native_id,before_hash:'abc',fields:{title,brief:'No customer data',status:0},editability:{allowed_changes:allowed?['title','brief']:[],can_disable:allowed,blocked_reasons:allowed?[]:['EXCLUSIVE_OBJECT_REQUIRED']}}}});
   if(body.action==='benefit_edit'){writeIDs.push(body.operation_id);title=body.changes.title;if(drop){drop=false;return route.abort();}return route.fulfill({json:{status:'ok',data:{operation_id:body.operation_id,state:'confirmed'}}});}
   if(body.action==='operation_reconcile'){reconcileIDs.push(body.operation_id);return route.fulfill({json:{status:'ok',data:{operation_id:body.operation_id,state:'confirmed'}}});}
   if(body.action==='analysis_summary'){summaryCount++;return route.fulfill({json:{status:'ok',data:{status:'partial',totals:[{currency:'USD',scale:2,paid_orders:1,associated_paid_minor:8550,activity_paid_minor:null,refund_minor:null,net_minor:null}],warnings:['LINE_ALLOCATION_UNKNOWN','<img src=x onerror=alert(1)>']}}});}
   if(body.action==='analysis_reconcile')return route.fulfill({json:{status:'ok',data:{status:'partial'}}});
   throw Error('unexpected '+body.action);
  }
  const file=path.join(app,url.pathname);if(!file.startsWith(app)||!fs.existsSync(file))return route.fulfill({status:404,body:''});return route.fulfill({body:fs.readFileSync(file),contentType:{'.html':'text/html','.js':'text/javascript','.css':'text/css'}[path.extname(file)]||'text/plain'});
 });
 try{
  await page.goto('http://127.0.0.1:8597/analytics/operations.html');await page.waitForFunction(()=>!document.querySelector('#query-fields').disabled);
  await page.locator('#benefit-id').fill('123');await page.locator('#benefit-query button').click();await page.waitForFunction(()=>document.querySelector('#benefit-state').textContent.includes('123'));assert.equal(await page.locator('#save-benefit').isDisabled(),true);
  allowed=true;await page.locator('#benefit-query button').click();await page.waitForFunction(()=>!document.querySelector('#save-benefit').disabled);
  await page.locator('#benefit-title').fill('New title');await page.locator('#save-benefit').click();await page.waitForFunction(()=>document.querySelector('#ops-error').textContent.length>0);assert.equal(writeIDs.length,1);assert.equal(await page.locator('#benefit-title').isDisabled(),true);
  await page.reload();await page.waitForFunction(()=>!document.querySelector('#reconcile-operation').disabled);assert.equal(writeIDs.length,1);
  await page.locator('#reconcile-operation').click();await page.waitForFunction(()=>document.querySelector('#pending-state').textContent==='没有待核对操作。');assert.equal(reconcileIDs[0],writeIDs[0]);assert.equal(writeIDs.length,1);assert.equal(await page.locator('#benefit-title').inputValue(),'New title');
  await page.locator('#read-summary').click();await page.waitForFunction(()=>document.querySelector('#analysis-totals').textContent.includes('85.50'));assert.match(await page.locator('#analysis-totals').innerText(),/未知/);assert.equal(await page.locator('#analysis-warnings img').count(),0);
  await page.setViewportSize({width:390,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  readonly=true;await page.reload();await page.waitForFunction(()=>document.querySelector('#ops-status').textContent.includes('无后台'));await page.locator('#read-summary').evaluate(el=>el.dispatchEvent(new MouseEvent('click',{bubbles:true})));assert.equal(summaryCount,1);
  assert.deepEqual(errors,[]);console.log('PASS native operation unknown-state survives reload, original-ID reconcile without repost, verified-object gate, aggregate unknown amounts, escaping, readonly, mobile');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
