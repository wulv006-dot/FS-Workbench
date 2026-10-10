const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),legacy=path.join(root,'deploy/frontend/assets');
let requests=[],errors=[],selectedCounts=new Map(),deny=false;
function payload(u){const d=u.searchParams.get('start'),end=u.searchParams.get('end'),key=u.searchParams.get('profile'),period={start:d+' 00:00',end:end+' 23:00'},stamp=new Date().toISOString();
 const count=(selectedCounts.get(d)||0)+1;selectedCounts.set(d,count);
 const pending=['2026-10-09','2026-10-08'].includes(d)&&count===1,failed=d==='2026-10-07',absent=d==='2026-10-06';
 return {status:'available',schemaVersion:1,query:{profile:key,start:d,end,grain:'day'},scopeContractId:'admin-main-order-labelled-supplement-v1',rangeId:'a'.repeat(64),generatedAt:stamp,expiresInSeconds:120,stale:false,profile:{key,name:key,period,primary:{period,currency:'USD',status:pending?'pending':failed?'unavailable':'available',readPhase:pending?'reading':failed?'failed':'available',capturedAt:pending?null:stamp,metrics:pending||failed||absent?{}:{profitMarginPct:{value:20,status:'available'}}},supplement:{status:'available',period,capturedAt:stamp,metrics:{},dimensions:{channels:[{code:'www.mmoexp.com',orders:2,revenueUsd:100}]}},metrics:{},dimensions:{}},sources:{Admin:{status:'available',phase:'available',capturedAt:stamp},Order:{status:pending?'pending':failed?'unavailable':'available',phase:pending?'reading':failed?'failed':'available',capturedAt:pending?null:stamp}}};}
(async()=>{const browser=await chromium.launch({headless:true}),page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const u=new URL(route.request().url());let body='',code=200,type='application/json';
  if(u.pathname==='/'){type='text/html';body=`<body><div id="host"></div><script type="module">import {mount} from '/business.js';import {lifecycle} from '/runtime.js';const scope=lifecycle(document.querySelector('#host'),()=>{},s=>window.denied=s);scope.root.innerHTML=${JSON.stringify(fs.readFileSync(path.join(legacy,'business.html'),'utf8'))};window.scope=scope;window.api=mount(scope);</script>`;}
  else if(u.pathname==='/dashboard/fs-home/range.json'){requests.push(u.search);body=JSON.stringify(payload(u));if(deny)code=403;}
  else if(u.pathname==='/__auth/verify'){body='{}';}
  else if(u.pathname.startsWith('/dashboard/fs-home/transactions/')){code=503;body='{}';}
  else if(u.pathname==='/business.js'){body=fs.readFileSync(path.join(root,'assets/business.js'));type='application/javascript';}
  else if(['/runtime.js','/business.css','/metrics.js'].includes(u.pathname)){body=fs.readFileSync(path.join(legacy,u.pathname.slice(1)));type=u.pathname.endsWith('.js')?'application/javascript':'text/css';}
  else body='{}';await route.fulfill({body,contentType:type,status:code});
 });
 const select=async day=>page.evaluate(day=>{const host=document.querySelector('#host').shadowRoot.querySelector('#supplement-insights'),selection={start:day,end:day,grain:'day'},period={start:day+' 00:00',end:day+' 23:00'},p={key:'FC27',name:'FC27',period,primary:{status:'unavailable',period,currency:'USD',metrics:{}},supplement:{status:'unavailable',period,metrics:{},dimensions:{}},metrics:{},dimensions:{}};window.scope.window.FSSupplementInsights.render(host,{profiles:{FC27:p},dashboard:{profiles:{FC27:{series:[]}}}},'FC27',selection);},day);
 const text=()=>page.evaluate(()=>document.querySelector('#host').shadowRoot.querySelector('#supplement-insights').textContent);
 const timings=[];
 try{await page.goto('http://127.0.0.1:8999');await page.waitForFunction(()=>window.api&&document.querySelector('#host').shadowRoot.querySelector('.fsi-metrics'));
  for(const day of ['2026-10-09','2026-10-08']){const at=Date.now();await select(day);
   await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.querySelector('#supplement-insights').textContent.includes('Order 读取中'));
   assert((await text()).includes('$100.00'));assert(!(await text()).includes('参考利润率源未提供'));
   await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.querySelector('#supplement-insights').textContent.includes('20.00%'),{timeout:6000});
   const seconds=(Date.now()-at)/1000;assert(seconds<6);assert.equal(selectedCounts.get(day),2);timings.push({day,coldSeconds:seconds});
  }
  const count=selectedCounts.get('2026-10-09'),at=Date.now();await select('2026-10-09');assert((await text()).includes('20.00%'));assert.equal(selectedCounts.get('2026-10-09'),count);timings.push({day:'2026-10-09',cacheHitSeconds:(Date.now()-at)/1000,additionalRequests:0});
  await select('2026-10-07');await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.querySelector('#supplement-insights').textContent.includes('Order 读取失败'));
  await select('2026-10-06');await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.querySelector('#supplement-insights').textContent.includes('源未提供'));
  deny=true;await select('2026-10-05');await page.waitForFunction(()=>window.denied===403);assert(!(await text()).includes('$100.00'));
  assert.equal(errors.length,0,errors.join('\n'));fs.writeFileSync(path.join(root,'evidence/browser-latency.json'),JSON.stringify({syntheticOnly:true,cases:6,timings,errors,requests},null,2));console.log('Two-date supplement completion/cache hit, field failure/absence and permission clearing passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
