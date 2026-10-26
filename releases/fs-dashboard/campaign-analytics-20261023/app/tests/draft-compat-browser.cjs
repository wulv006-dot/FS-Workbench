const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{randomUUID}=require('node:crypto');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'draft-compat-')),real=global.fetch;
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');process.env.CAMPAIGN_ORIGIN='http://127.0.0.1:8524';
 const {initialCenterDraft}=await import('../analytics/center-store.mjs');const original=initialCenterDraft();
 for(const p of original.pages){delete p.default_language;delete p.social_image;}
 original.pages[0].starts_at='2026-11-01T12:30:45.123Z';original.pages[0].description='  untouched text  ';original.pages[1].starts_at='2026-10-25T12:00:00+08:00';original.pages[1].ends_at='2026-10-25T05:00:00Z';
 fs.mkdirSync(path.join(dir,'center'));const statePath=path.join(dir,'center/state.json');
 fs.writeFileSync(statePath,JSON.stringify({revision:2,draft:original,published:null,updated_by:'fixture',updated_at:'2026-10-01T00:00:00Z'}));
 global.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':'fixture','x-auth-role':'admin'}}):real(url,options);
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(8524,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.FC_TEST_BROWSER_CHANNEL?{channel:process.env.FC_TEST_BROWSER_CHANNEL}:{})}),page=await browser.newPage(),base='http://127.0.0.1:8524/dashboard/analytics/campaigns/analytics/',writes=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')writes.push({path:new URL(r.url()).pathname,body:r.postDataJSON()});});
 const read=()=>JSON.parse(fs.readFileSync(statePath));const wait=txt=>page.waitForFunction(t=>document.querySelector('#center-status').textContent.includes(t),txt);
 let dropSave=false,dropRestore=false;
 await page.route('**/api/center{,/restore}',async route=>{const req=route.request();if(req.method()==='POST'&&((req.url().endsWith('/restore')&&dropRestore)||(!req.url().endsWith('/restore')&&dropSave))){if(req.url().endsWith('/restore'))dropRestore=false;else dropSave=false;await route.fetch();return route.abort();}return route.continue();});
 try{
  await page.goto(base+'products.html');await wait('已读取');assert.deepEqual(read().draft,original);assert.equal(await page.locator('[data-model-card]').count()>0,true);const baseline=await (await real(base+'api/center')).json();
  for(const id of ['seasonal-vault','fc27-sbc','fc27-trio','fc27-weekly'])await page.locator('#page-select').selectOption(id);
  assert.match(await page.locator('#draft-changes').innerText(),/未修改配置/);await page.locator('#save-center').click();assert.equal(writes.length,0);assert.equal(read().revision,2);
  // Cancellation before save leaves original omitted properties and precise dates intact.
  await page.locator('#title-0').fill('cancel me');await page.locator('#reload-center').click();await wait('已读取');assert.equal(read().revision,2);assert.equal(await page.locator('#title-0').inputValue(),original.pages[0].title);
  await page.locator('[data-card-up="1"]').click();assert.match(await page.locator('#draft-changes').innerText(),/从继承改为明确配置/);
  dropSave=true;await page.locator('#save-center').click();await page.waitForFunction(()=>document.querySelector('#center-error').textContent.includes('原操作'));
  assert.equal(read().revision,3);const saveId=writes.at(-1).body.operation_id;assert.equal(Object.hasOwn(read().draft,'fc_layout'),true);assert.deepEqual(read().draft.fc_layout.weekly,[baseline.effective_fc_layout.weekly[1],baseline.effective_fc_layout.weekly[0],...baseline.effective_fc_layout.weekly.slice(2)]);assert.deepEqual(read().draft.fc_layout.sbc,baseline.effective_fc_layout.sbc);assert.deepEqual(read().draft.fc_layout.trio,baseline.effective_fc_layout.trio);assert.deepEqual(read().draft.pages.slice(1),original.pages.slice(1));
  assert.equal(read().draft.pages[0].starts_at,original.pages[0].starts_at);assert.equal(read().draft.pages[0].description,original.pages[0].description);assert.equal(Object.hasOwn(read().draft.pages[0],'default_language'),false);
  await page.reload();await wait('原操作已确认');assert.equal(read().revision,3);assert.equal(writes.at(-1).body.operation_id,saveId);
  await page.locator('#restore-draft').click();assert.match(await page.locator('#restore-summary').innerText(),/修订 2/);const beforeCancel=writes.length;await page.locator('#cancel-restore').click();assert.equal(writes.length,beforeCancel);
  await page.locator('#restore-draft').click();dropRestore=true;await page.locator('#confirm-restore').click();await page.waitForFunction(()=>document.querySelector('#center-error').textContent.includes('原操作'));assert.equal(read().revision,4);const restoreId=writes.at(-1).body.operation_id;
  await page.reload();await wait('原操作已确认');assert.equal(writes.at(-1).body.operation_id,restoreId);assert.equal(read().revision,4);assert.deepEqual(read().draft,original);assert.equal(fs.existsSync(path.join(dir,'public')),false);
  // Explicit choice affects only one page, then exact server-history restoration.
  const option=Object.values(baseline.fc_catalog.products).find(p=>p.kind==='player'&&!baseline.effective_fc_layout.weekly.includes(p.key));
  await page.route('**/api/center/backend-read',route=>route.fulfill({json:{status:'ok',data:{model:{key:'model-266-1327-999991',model_id:'999991',title:option.title,version_label:option.version,kind:'player',platforms:Object.fromEntries(['ps','xbox','pc'].map(code=>[code,{state:'verified',product_ref:{goods_id:baseline.catalog_products.find(row=>row.key==='fc-'+option.key+'-'+code).product_ref.goods_id}}]))}}}}));
  await page.locator('[data-layout-remove="weekly:'+baseline.effective_fc_layout.weekly[0]+'"]').click();await page.locator('#model-query').fill('999991');await page.locator('#search-model').click();await page.waitForSelector('#choose-model');await page.locator('#choose-model').click();await page.locator('#save-center').click();await wait('草稿已保存');assert.equal(read().draft.fc_layout.weekly[0],option.key);for(const code of ['ps','xbox','pc'])assert(read().draft.pages[0].product_keys.includes('fc-'+option.key+'-'+code));assert.deepEqual(read().draft.pages.slice(1),original.pages.slice(1));
  await page.locator('#restore-draft').click();await page.locator('#confirm-restore').click();await wait('已恢复上一份');assert.deepEqual(read().draft,original);
  // Concurrent authorized save must win; stale UI edit gets CAS conflict and reloads.
  const snapshot=await (await real(base+'api/center')).json(),other=structuredClone(snapshot.draft);other.pages[3].title='Concurrent seasonal title';
  const response=await real(base+'api/center',{method:'POST',headers:{Cookie:'fixture',Origin:process.env.CAMPAIGN_ORIGIN,'Content-Type':'application/json','X-CSRF-Token':snapshot.csrf},body:JSON.stringify({revision:snapshot.revision,operation_id:randomUUID(),draft:other})});assert.equal(response.status,200);
  await page.locator('#title-0').fill('stale local title');await page.locator('#save-center').click();await page.waitForFunction(()=>document.querySelector('#center-error').textContent.includes('REVISION_CONFLICT'));assert.deepEqual(read().draft,other);
  assert.deepEqual(errors,[]);console.log('PASS legacy raw shape, inherited reads, no-op/page switch/cancel, sort and choose, same-ID lost responses, exact restore, cross-page and CAS; isolated real service');
 }finally{await browser.close();await new Promise(r=>server.close(r));global.fetch=real;fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
