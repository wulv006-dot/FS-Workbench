const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const app=path.resolve(__dirname,'..'),browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 let releaseScript,requests=0;const held=new Promise(resolve=>releaseScript=resolve),page=await browser.newPage();
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url()),name=path.basename(u.pathname);
  if(name==='products.html')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(app,'products.html'),'utf8')});
  if(name==='products.js'){await held;return route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.join(app,'products.js'),'utf8')});}
  if(u.pathname.endsWith('/api/center')){requests++;return route.fulfill({status:503,json:{message:'fixture unavailable'},headers:{'Cache-Control':'no-store'}});}
  return route.fulfill({contentType:name.endsWith('.css')?'text/css':'text/javascript',body:''});
 });
 try{
  const firstRequest=page.waitForResponse(response=>response.url().endsWith('/api/center'),{timeout:2000});
  const loaded=page.goto('http://127.0.0.1:8948/analytics/products.html');loaded.catch(()=>{});
  await firstRequest;
  assert.equal(requests,1,'initial read starts while script is still loading');releaseScript();await loaded;
  await page.locator('#center-error').filter({hasText:'fixture unavailable'}).waitFor({timeout:2000});assert.equal(requests,1,'first read is reused');
  await page.locator('#reload-center').click();await page.waitForFunction(()=>performance.getEntriesByType('resource').filter(x=>x.name.endsWith('/api/center')).length===2);assert.equal(requests,2,'reload makes a fresh request');
  console.log('PASS initial center read overlaps script and reload remains fresh');
 }finally{releaseScript();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
