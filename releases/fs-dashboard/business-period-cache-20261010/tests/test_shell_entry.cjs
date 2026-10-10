const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'../deploy/frontend/assets');
(async()=>{const browser=await chromium.launch({headless:true});const result=[];
 try{for(const entry of ['index.html','home.html']){const page=await browser.newPage(),errors=[];let deny=false;page.on('pageerror',e=>errors.push(e.message));await page.clock.install({time:new Date('2026-10-10T08:00:00Z')});
 await page.route('**/*',async route=>{const u=new URL(route.request().url()),name=path.basename(u.pathname);let code=200,type='application/json',body='{}',headers={};
 if(u.pathname==='/__auth/verify'){headers={'X-Auth-Groups':'dashboard','X-Auth-User':'SYNTHETIC','X-Auth-Role':'viewer'};if(deny)code=403;}
 else if(u.pathname.endsWith('/range.json')){const profile=u.searchParams.get('profile'),start=u.searchParams.get('start'),end=u.searchParams.get('end'),period={start:start+' 00:00',end:end+' 23:00'},stamp=new Date().toISOString();body=JSON.stringify({schemaVersion:1,status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',query:{profile,start,end,grain:'day'},profile:{key:profile,period,primary:{status:'available',currency:'USD',period,metrics:{profitMarginPct:{value:20,status:'available'}}},supplement:{status:'available',period,metrics:{},dimensions:{channels:[{code:'www.mmoexp.com',orders:2,revenueUsd:100}]}},metrics:{},dimensions:{}},sources:{Admin:{status:'available',capturedAt:stamp},Order:{status:'available',capturedAt:stamp}},expiresInSeconds:120});}
 else if(fs.existsSync(path.join(root,name))){body=fs.readFileSync(path.join(root,name));type=name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':name.endsWith('.json')?'application/json':'text/html';}
 else if(u.pathname.includes('/transactions/')){code=503;}
 else{type='text/html';body='<!doctype html><p>Synthetic module</p>';}
 await route.fulfill({status:code,contentType:type,body,headers});});
 await page.goto('http://127.0.0.1:8999/'+entry);if(entry==='index.html')await page.locator('#business-scope').waitFor({timeout:10000});else await page.waitForFunction(()=>document.querySelector('#orders')?.textContent==='2');
 assert.equal(errors.length,0,errors.join('\n'));assert(!(await page.locator('#status').innerText()).includes('is not defined'));deny=true;await page.clock.fastForward(61000);await page.waitForFunction(()=>document.querySelector('#status')?.textContent.includes('未获授权'));assert.equal(await page.locator('#business-scope').count(),0);result.push({entry,passed:true,independentPermissionRevocation:true});await page.close();}
 fs.writeFileSync(path.resolve(__dirname,'../evidence/shell-entry.json'),JSON.stringify({syntheticOnly:true,result},null,2));console.log('Full home and analytics entry initialization passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
