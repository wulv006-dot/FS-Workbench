// Existing business renderer, synthetic collector snapshot, no real sessions or data.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),assets=path.join(root,'frontend','assets');
const rows=JSON.parse(fs.readFileSync(path.join(root,'evidence/game-map.json'))).profiles;
const snapshot=JSON.parse(fs.readFileSync(path.join(root,'tests/synthetic-snapshot.json')));
let requests=[],errors=[],denied=false;
const bytes=JSON.stringify(snapshot),manifest={schemaVersion:2,snapshotId:snapshot.snapshotId,scopeContractId:snapshot.scopeContractId,path:'snapshots/'+snapshot.snapshotId+'/snapshot.json',sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
function summary(u){const key=u.searchParams.get('profile'),start=u.searchParams.get('start'),end=u.searchParams.get('end'),period={start:start+' 00:00',end:end+' 23:00'},stamp=new Date().toISOString();return {schemaVersion:1,status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',query:{profile:key,start,end,grain:'day'},rangeId:'a'.repeat(64),generatedAt:stamp,expiresInSeconds:7200,cachePolicy:'historical',profile:{key,name:rows.find(r=>r.key===key)?.name||key,period,primary:{period,status:'available',currency:'USD',capturedAt:stamp,metrics:{profitMarginPct:{status:'available',value:20}}},supplement:{period,status:'available',capturedAt:stamp,normalisedScope:'all-websites',filters:{site:''},metrics:{orders:{value:11,status:'available'},revenueUsd:{value:430,status:'available'},newCustomers:{value:4,status:'available'}},dimensions:{channels:[{code:'www.mmoexp.com',orders:2,revenueUsd:100}]}},metrics:{},dimensions:{}},sources:{Admin:{status:'available',capturedAt:stamp},Order:{status:'available',capturedAt:stamp}}};}
(async()=>{const browser=await chromium.launch({headless:true}),page=await browser.newPage();page.setDefaultTimeout(5000);page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',async route=>{const u=new URL(route.request().url()),name=path.basename(u.pathname);let body='{}',type='application/json',status=200;
if(u.pathname==='/'){type='text/html; charset=utf-8';body=`<meta charset="utf-8"><body style="background:#f4f6fc"><div id="host"></div><script type="module">import {mount} from '/business.js';import {lifecycle} from '/runtime.js';window.scope=lifecycle(document.querySelector('#host'),()=>{},()=>{});scope.root.innerHTML='<style>'+${JSON.stringify(fs.readFileSync(path.join(assets,'business.css'),'utf8'))}+'</style>'+${JSON.stringify(fs.readFileSync(path.join(assets,'business.html'),'utf8'))};window.api=mount(scope);</script>`;}
else if(u.pathname.endsWith('/range.json')){if(denied)status=403;else if(u.searchParams.get('mode')==='summary'){requests.push(Object.fromEntries(u.searchParams));body=JSON.stringify(summary(u));}else status=503;}
else if(name==='current.json')body=JSON.stringify(manifest);
else if(name==='attempt.json')body=JSON.stringify({status:'success',snapshotId:snapshot.snapshotId});
else if(name==='snapshot.json')body=bytes;
else if(name==='business.js'||fs.existsSync(path.join(assets,name))){body=fs.readFileSync(path.join(assets,name));type=name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html';}
await route.fulfill({status,contentType:type,body});});
try{await page.goto('http://127.0.0.1:8999/');await page.getByLabel('经营范围').waitFor({timeout:5000});await page.waitForFunction(()=>window.scope.summary?.profile?.key==='MMOEXP');
const selector=page.getByLabel('经营范围');
assert.equal(await selector.locator('option').count(),17);
assert.equal(await selector.locator('optgroup[label="综合游戏 · 全部状态"] option').count(),5);
assert.equal(await selector.locator('optgroup[label="RPG · 已完成"] option').count(),5);
for(const row of rows){console.log('Checking',row.key);await selector.selectOption(row.key);await page.waitForFunction(key=>window.scope.summary?.profile?.key===key,row.key);
const state=await page.evaluate(()=>window.api.state());assert.equal(state.b_group,row.group);assert.equal(state.b_profile,row.key);
await page.locator('#dStart').fill('2026-10-01');await page.locator('#dEnd').fill('2026-10-03');await page.locator('#btnApply').click();
await page.waitForFunction(key=>window.scope.summary?.profile?.key===key&&window.scope.summary.query.start==='2026-10-01',row.key);
assert(requests.some(q=>q.profile===row.key&&q.start==='2026-10-01'&&q.end==='2026-10-03'));
assert((await selector.locator('option:checked').innerText()).includes(row.name));
assert.deepEqual((await page.evaluate(()=>window.api.state())).period,{start:'2026-10-01',end:'2026-10-03',grain:'day'});
}
for(const key of ['FC27','D4']){await selector.selectOption(key);await page.waitForFunction(key=>window.scope.summary?.profile?.key===key,key);assert.equal((await page.evaluate(()=>window.api.state())).b_profile,key);}
await selector.selectOption('MAPLESTORY_CLASSIC');await page.waitForFunction(()=>window.scope.summary?.profile?.key==='MAPLESTORY_CLASSIC');
await page.getByLabel('参考展示范围').selectOption('all');
await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.querySelector('.fsi-metrics').textContent.includes('$430.00'));
const card=label=>page.locator('.fsi-metric').filter({has:page.locator('span',{hasText:label})});
assert.equal(await card('全部网站订单数').locator('strong').innerText(),'11');
assert.equal(await card('全部网站销售额').locator('strong').innerText(),'$430.00');
assert.equal(await card('预估利润（全部网站）').locator('strong').innerText(),'$86.00');
assert.equal(await card('参考利润率').locator('strong').innerText(),'20.00%');
assert(!(await page.getByLabel('参考展示范围').innerText()).includes('ELD'));
assert.equal(await page.locator('.fsi-heading h3').textContent(),'全部网站');
await page.screenshot({path:path.join(root,'evidence/synthetic-board.png'),fullPage:false});
await page.getByLabel('参考展示范围').selectOption('main');
await page.waitForFunction(()=>document.querySelector('#host').shadowRoot.querySelector('.fsi-metrics').textContent.includes('$100.00'));
assert.equal(await card('主站销售额').locator('strong').innerText(),'$100.00');

denied=true;await page.evaluate(()=>window.api.update());await page.waitForFunction(()=>!document.querySelector('#host').shadowRoot.querySelector('#supplement-insights').textContent.includes('$100.00'));assert(!(await page.locator('#supplement-insights').innerText()).includes('$100.00'));
assert.deepEqual(errors,[]);
fs.writeFileSync(path.join(root,'evidence/browser.json'),JSON.stringify({syntheticOnly:true,checks:['17 profile options','RPG/general category','seven game switching','seven exact custom ranges','legacy FC/D4 selections','All Admin original totals/estimate/labels','main scope restored','denial clears metrics'],requests,errors},null,2));console.log('Existing business renderer: seven-game/category/custom-range/permission checks passed.');
}catch(e){console.error(JSON.stringify({errors,dom:await page.evaluate(()=>({url:location.href,body:document.body.outerHTML.slice(0,220),scope:!!window.scope,host:document.querySelector('#host')?.shadowRoot?.innerHTML.slice(-800)}))}));throw e;}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
