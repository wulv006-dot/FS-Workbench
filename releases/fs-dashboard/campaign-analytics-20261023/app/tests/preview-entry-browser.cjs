const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{createHash}=require('node:crypto');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'preview-entry-')),real=global.fetch;
 process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');
 process.env.CAMPAIGN_ORIGIN='http://127.0.0.1:8531';
 global.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':options?.headers?.Cookie==='preview-user=other'?'other-user':'fixture','x-auth-role':'admin'}}):real(url,options);
 const {initialCenterDraft}=await import('../analytics/center-store.mjs');fs.mkdirSync(path.join(dir,'center'));fs.writeFileSync(path.join(dir,'center/state.json'),JSON.stringify({revision:0,draft:initialCenterDraft(),published:null}));
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(8531,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true}),context=await browser.newContext(),page=await context.newPage(),base='http://127.0.0.1:8531/dashboard/analytics/campaigns/analytics/',writes=[];
 context.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))writes.push({method:r.method(),url:r.url(),body:r.postDataJSON()});});
 try{
  await page.goto(base);await page.locator('#open-activity').click();
  assert.equal(new URL(page.url()).pathname,'/dashboard/analytics/campaigns/analytics/products.html');
  await page.waitForFunction(()=>document.querySelector('#center-status').textContent.includes('已读取'));
  const state=path.join(dir,'center/state.json'),before=fs.readFileSync(state,'utf8');
  const files=()=>{const result={};for(const entry of fs.readdirSync(dir,{recursive:true,withFileTypes:true})){if(!entry.isFile())continue;const file=path.join(entry.parentPath||entry.path,entry.name);result[path.relative(dir,file)]=createHash('sha256').update(fs.readFileSync(file)).digest('hex');}return result;},beforeFiles=files();
  let index=0;
  for(const [id,route] of [['fc27-weekly','Weekly-Scout.html'],['fc27-sbc','Sbc-Companions.html'],['fc27-trio','Player-Trio.html'],['seasonal-vault','seasonal/index.html'],['fc27-weekly','Weekly-Scout.html'],['seasonal-vault','seasonal/index.html']]){
   await page.locator('#page-select').selectOption(id);
   const pageIndex=JSON.parse(before).draft.pages.findIndex(p=>p.page_id===id),title='Unsaved whole page preview '+(++index);
   await page.locator('#title-'+pageIndex).fill(title);
   const response=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/api/center/preview')&&r.request().method()==='POST');
   await page.locator('#preview-draft').click();const receipt=await response;assert.equal(receipt.status(),200);const result=await receipt.json();
   const url=new URL(result.preview_url,page.url());assert.equal(url.origin,new URL(base).origin);
   const previewRoot=new URL('preview/',base).pathname;assert(url.pathname.startsWith(previewRoot));
   const suffix=url.pathname.slice(previewRoot.length),token=suffix.split('/')[0];assert.match(token,/^[a-f0-9]{48}$/);assert.equal(suffix.slice(token.length+1),route);assert.equal(url.search,'');
   await page.waitForFunction(expected=>{const frame=document.querySelector('#draft-preview-frame');return !document.querySelector('#draft-preview').hidden&&frame.contentDocument?.title===expected;},title);
   assert.equal(new URL(await page.locator('#draft-preview-frame').getAttribute('src')).href,url.href);
   assert.equal(context.pages().length,1,'whole-page preview stays in the unique editor');
   const rejected=await context.request.get(url.href,{headers:{Cookie:'preview-user=other'}});assert.equal(rejected.status(),404,'private preview is concealed from a different authenticated operator');
   assert.equal(fs.readFileSync(state,'utf8'),before);assert.deepEqual(files(),beforeFiles,'preview must not persist a draft, receipt, history or release');
   assert.equal(writes.length,index);assert.equal(writes.at(-1).body.page_id,id);assert.equal(writes.at(-1).body.draft.pages[pageIndex].title,title);
  }
  assert(writes.every(r=>r.method==='POST'&&new URL(r.url).pathname===new URL('api/center/preview',base).pathname));
  assert.match(await page.locator('#preview-status').innerText(),/整页未发布预览/);
  console.log('PASS analysis entry -> unique editor -> authenticated unsaved whole-page preview for all four page mappings and repeat switches; actual renderer titles, operator-bound tokens, zero persistent writes');

 }finally{await browser.close();await new Promise(r=>server.close(r));global.fetch=real;fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});
