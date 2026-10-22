// Fictional DOM fixtures verify the actual existing metric renderer, not live data.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),http=require('node:http');
const {chromium}=require('playwright');
const source=fs.readFileSync(path.join(__dirname,'../source',process.argv[2]||'business.js'),'utf8').replace(/\r\n/g,'\n');
const between=(a,b)=>{const start=source.indexOf(a),end=source.indexOf(b,start);assert.ok(start>=0&&end>start,'fixture section missing: '+a);return source.slice(start,end);};
const code=`const scope={referenceScope:'main'},fcDetailState={data:null};window.FSBusinessRange={select:v=>v};function fsEnsureProcurement(){return window.actualState;}`+
 between('function fsMainSite(', 'function fsOrderLabel(')+between('function fsMetricText(', '/* Preparation')+
 between('function fsProcurementNote(', 'function fsClearProcurement(')+
 between("(function(root){'use strict';\nconst nf",'const FSSupplementInsights=window.FSSupplementInsights;');
const metric=value=>({status:'available',value});
const period={start:'2026-10-15 00:00',end:'2026-10-22 00:00'};
const profile={key:'FC27',name:'FC27',period,primary:{status:'available',currency:'USD',period,metrics:{profitMarginPct:metric(25)}},
 supplement:{status:'available',period,metrics:{orders:metric(10),revenueUsd:metric(100)},dimensions:{channels:[{code:'www.mmoexp.com',orders:10,revenueUsd:100}]}}};
const state={phase:'available',data:{orders:10,completedOrders:8,coveredOrders:6,missingCostOrders:2,pendingOrders:2,saleCny:1000,costCny:700,profitCny:300,margin:.3,capturedAt:'frozen-admin',costCapturedAt:'later-cost'}};
const server=http.createServer((req,res)=>{res.setHeader('Content-Type',req.url==='/fixture.js'?'text/javascript':'text/html');res.end(req.url==='/fixture.js'?code:'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>fictional procurement fixture</title><div id="metrics"></div><script src="/fixture.js"></script></html>');});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+server.address().port+'/');assert.deepEqual(errors,[]);
  const render=async value=>page.evaluate(({profile,state})=>{window.actualState=state;window.FSSupplementInsights.render(document.getElementById('metrics'),{profiles:{FC27:profile}},'FC27');},{profile,state:value});
  await render(state);
  assert.equal(await page.locator('.fsi-metric').count(),15);assert.equal(await page.locator('.fsi-metric').nth(1).locator('strong').innerText(),'$100.00');
  assert.equal(await page.locator('.fsi-metric').nth(2).locator('strong').innerText(),'¥300');assert.equal(await page.locator('.fsi-metric').nth(3).locator('strong').innerText(),'30.00%');
  const coverage=page.locator('[data-procurement-coverage]');assert.equal(await coverage.getAttribute('role'),'status');assert.equal(await coverage.getAttribute('aria-live'),'polite');assert.match(await coverage.innerText(),/6\/8/);assert.match(await coverage.innerText(),/待补 2/);assert.match(await page.locator('#metrics').innerText(),/原参考估算：\$25\.00/);
  await render({phase:'reading',data:null});assert.match(await page.locator('.fsi-metric').nth(2).innerText(),/读取中/);assert.doesNotMatch(await page.locator('.fsi-metric').nth(2).innerText(),/¥0/);
  await render({phase:'denied',data:null});assert.match(await coverage.innerText(),/权限未开通/);assert.doesNotMatch(await page.locator('.fsi-metric').nth(2).innerText(),/¥300/);
  await render({phase:'failed',data:null});assert.match(await coverage.innerText(),/读取失败/);
  await render({...state,data:{...state.data,profitCny:-200,costCny:1200,margin:-.2}});assert.equal(await page.locator('.fsi-metric').nth(2).locator('strong').innerText(),'¥-200');assert.equal(await page.locator('.fsi-metric').nth(3).locator('strong').innerText(),'-20.00%');
  await render(null);assert.equal(await coverage.count(),0);assert.equal(await page.locator('.fsi-metric').nth(2).locator('strong').innerText(),'$25.00');
  for(const theme of ['light','dark']){await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);await render(state);assert.equal(await page.locator('.fsi-metric').nth(2).locator('strong').innerText(),'¥300');}
  console.log('procurement DOM: money currencies, 15-card layout, subset coverage, live status, reading/denied/failure, losses, fallback and theme state passed');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
