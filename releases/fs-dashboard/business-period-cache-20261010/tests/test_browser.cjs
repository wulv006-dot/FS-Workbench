const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),legacy='E:/WorkBuddy/大超服务器/fs_traffic_explanations_20261009/stage/assets';
const base='http://127.0.0.1:8999';let status=200,stale=false,requests=[],errors=[];
function summary(u){const start=u.searchParams.get('start'),end=u.searchParams.get('end'),key=u.searchParams.get('profile');
 const period={start:start+' 00:00',end:end+' 16:30'},capturedAt=new Date().toISOString();
 return {schemaVersion:1,status:stale?'stale':'available',scopeContractId:'admin-main-order-labelled-supplement-v1',query:{profile:key,start,end,grain:'day'},rangeId:'a'.repeat(64),origin:'live-cache',stale,generatedAt:capturedAt,expiresInSeconds:stale?0:120,profile:{key,name:key,period,primary:{period,status:'unavailable',currency:'USD',metrics:{}},supplement:{period,status:'available',capturedAt,metrics:{newCustomers:{status:'available',value:8}},dimensions:{channels:[{code:'www.mmoexp.com',orders:123,revenueUsd:456.78}]}},metrics:{},dimensions:{}},sources:{Admin:{status:'available',capturedAt,sourceDataAsOf:null},Order:{status:'unavailable',capturedAt:null}}};}
(async()=>{const browser=await chromium.launch({headless:true}),page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const u=new URL(route.request().url());requests.push(u.pathname+u.search);let body='',type='text/html',code=200,headers={};
  if(u.pathname==='/'){body=`<body><div id="host"></div><script type="module">import {mount} from '/business.js';import {lifecycle} from '/runtime.js';const scope=lifecycle(document.querySelector('#host'),()=>{},s=>window.denied=s);scope.root.innerHTML=${JSON.stringify(fs.readFileSync(path.join(legacy,'business.html'),'utf8'))};window.scope=scope;window.api=mount(scope);</script>`;}
  else if(u.pathname==='/dashboard/fs-home/range.json'){assert.equal(u.searchParams.get('mode'),'summary');body=JSON.stringify(summary(u));type='application/json';code=status;}
  else if(u.pathname==='/__auth/verify'){body='{}';type='application/json';headers={'X-Auth-Groups':'dashboard','X-Auth-User':'SYNTHETIC','X-Auth-Role':'viewer'};}
  else if(u.pathname.startsWith('/dashboard/fs-home/transactions/')){code=503;body='{}';type='application/json';}
  else if(u.pathname==='/business.js'){body=fs.readFileSync(path.join(root,'assets/business.js'));type='application/javascript';}
  else if(['/runtime.js','/business.css','/metrics.js'].includes(u.pathname)){body=fs.readFileSync(path.join(legacy,u.pathname.slice(1)));type=u.pathname.endsWith('.js')?'application/javascript':'text/css';}
  else {body='{}';type='application/json';}
  await route.fulfill({body,contentType:type,status:code,headers});
 });
 try{await page.goto(base);const host=page.locator('#host').locator('.fsi-metrics');await host.waitFor();
  await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.querySelector('.fsi-metrics')?.textContent.includes('456.78'));
  const content=()=>page.evaluate(()=>document.querySelector('#host').shadowRoot.textContent);
  assert((await content()).includes('123'));assert((await content()).includes('未提供'));assert((await content()).includes('上游统计水位 未提供'));
  // Recheck with local expiry and verify explicit stale banner from the source response.
  assert.equal(errors.length,0,errors.join('\n'));stale=true;await page.evaluate(()=>{window.scope.summary.clientExpiresAt=0;return window.api.update();});
  await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.textContent.includes('已过期故障兜底'));
  status=403;await page.evaluate(()=>{window.scope.summary.clientExpiresAt=0;return window.api.update();});
  await page.waitForFunction(()=>window.denied===403);
  assert(!(await content()).includes('$456.78'));assert.equal(errors.length,0,errors.join('\n'));
  assert(requests.filter(u=>u.includes('/range.json')).every(u=>!u.includes('snapshotId=')));
  fs.writeFileSync(path.join(root,'evidence/browser.json'),JSON.stringify({passed:7,syntheticOnly:true,errors,requests},null,2));
  console.log('7 isolated browser integration checks passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
