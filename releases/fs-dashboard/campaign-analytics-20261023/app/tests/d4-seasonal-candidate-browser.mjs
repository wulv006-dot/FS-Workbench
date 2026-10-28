// Local visual and native-transport evidence. Every storefront response is synthetic.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createPublicServer} from '../runtime/server.mjs';
import {digest} from '../runtime/snapshot.mjs';
import {d4SeasonalFixture} from '../runtime/tests/d4-seasonal-fixture.mjs';

const require=createRequire(import.meta.url),{chromium}=require('playwright'),root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),output=process.env.D4_SCREENSHOTS||path.join(os.tmpdir(),'d4-seasonal-candidate-evidence');
fs.mkdirSync(output,{recursive:true});
const snapshot=d4SeasonalFixture(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'d4-seasonal-browser-')),manifest={},names=['seasonal/index.html','seasonal/event.js','seasonal/event.css','seasonal/runtime-bridge.js','seasonal/model-selection.js','seasonal/campaign-data.js','standalone-adapter.js','activity-core.js','native-code-handoff.js','host-adapter.js'];
for(const name of fs.readdirSync(path.join(root,'seasonal/assets')))if(/\.(png|webp|svg|jpg|woff2)$/.test(name))names.push('seasonal/assets/'+name);
for(const name of names)manifest[name]=digest(fs.readFileSync(path.join(root,name)));
const server=createPublicServer({assetRoot:root,staticManifest:manifest,snapshot,dir,origin:'https://www.mmoexp.com',priceCacheProvider:()=>({schema_version:1,status:'ready',release_id:snapshot.release_id,config_hash:snapshot.config_hash,generated_at:new Date().toISOString(),products:snapshot.products,model_contracts:snapshot.seasonal_model_contracts})});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await chromium.launch({headless:true});const page=await browser.newPage(),posts=[],applies=[],errors=[],receipts=new Map();page.setDefaultTimeout(8000);page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());if(url.origin!=='https://www.mmoexp.com')return route.abort();
  if(url.pathname==='/Cart/add.html'){posts.push(Object.fromEntries(new URLSearchParams(request.postData())));return route.fulfill({json:{code:1}});}
  if(url.pathname==='/Cart.html')return route.fulfill({contentType:'text/html',body:'<!doctype html><title>D4 Candidate Synthetic Cart</title><p id="result">Pending simulation</p><script>const code=sessionStorage.getItem("pending_discount_code");sessionStorage.removeItem("pending_discount_code");fetch("/__fixture/apply",{method:"POST",body:code}).then(r=>r.json()).then(r=>document.querySelector("#result").textContent=r.accepted?"SIMULATED ACCEPTED":"SIMULATED REJECTED");</script>'});
  if(url.pathname==='/__fixture/apply'){applies.push(request.postData());return route.fulfill({json:{accepted:true}});}
  if(!url.pathname.startsWith('/events/'))return route.abort();
  const response=await fetch('http://127.0.0.1:'+server.address().port+url.pathname,{method:request.method(),...(request.method()==='POST'?{body:request.postData(),headers:{Origin:'https://www.mmoexp.com','Content-Type':'application/json'}}:{})}),bytes=Buffer.from(await response.arrayBuffer());
  if(url.pathname.endsWith('/halloween/reveal')){if(!response.ok)console.error('D4 reveal refused',response.status,bytes.toString());else{const receipt=JSON.parse(bytes);receipts.set(receipt.game_id,receipt);}}
  return route.fulfill({status:response.status,headers:Object.fromEntries(response.headers),body:bytes});
 });
 const open=async()=>{await page.goto('https://www.mmoexp.com/events/seasonal/');await page.waitForSelector('[data-game-card="diablo"]');};
 await page.setViewportSize({width:1366,height:1000});await open();assert.deepEqual(await page.locator('[data-game-card]').evaluateAll(nodes=>nodes.map(node=>node.dataset.gameCard)),['fc','aion','diablo','maplestory']);
 await page.screenshot({path:path.join(output,'d4-desktop-games.png'),fullPage:true});await page.locator('[data-game-card="diablo"]').click();
 await page.locator('[data-fixed-reveal]').click();await page.locator('[data-random-reveal="random-1"]').click();await page.waitForSelector('[data-offer-slot="random-1"] .is-revealed');await page.locator('[data-random-reveal="random-2"]').click();await page.waitForSelector('[data-offer-slot="random-2"] .is-revealed');await page.waitForTimeout(1650);
 assert.match(await page.locator('[data-offer-slot="fixed"]').innerText(),/Diablo IV Gold/);assert.match(await page.locator('[data-offer-slot="fixed"]').innerText(),/500000 M Gold/);assert.match(await page.locator('[data-offer-slot="fixed"]').innerText(),/\$2\.48/);
 const models=await page.locator('[data-buy-slot]').evaluateAll(nodes=>nodes.map(node=>node.dataset.modelBuy));assert.equal(models.length,2);assert.notEqual(models[0],models[1]);for(const model of models)assert(snapshot.halloween.games.find(g=>g.id==='diablo').random_models.includes(model));
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await page.locator('.card-front strong').evaluateAll(nodes=>nodes.every(node=>node.scrollWidth<=node.clientWidth+1)),true);
 await page.screenshot({path:path.join(output,'d4-desktop-offers.png'),fullPage:true});
 const slot=models[0]===receipts.get('diablo').slots[1].model_id?'random-1':'random-2',chosen=receipts.get('diablo').slots.find(row=>row.slot===slot),product=snapshot.products.find(p=>p.product_ref.model_id===chosen.model_id),binding=snapshot.native_checkout.bindings.find(b=>b.product_key===product.key&&b.off_percent===chosen.off_percent);
 await page.locator('[data-buy-slot="'+slot+'"]').click();await page.locator('#dialog-content select').selectOption('15943');assert.equal(await page.locator('#dialog-content input').inputValue(),'1');assert.match(await page.locator('#dialog-content').innerText(),/Season 15 Softcore/);assert.equal(await page.locator('#dialog-content button').isEnabled(),true);
 await page.screenshot({path:path.join(output,'d4-desktop-checkout.png'),fullPage:true});await page.locator('#dialog-content button').click();await page.waitForURL('**/Cart.html');await page.waitForFunction(()=>document.querySelector('#result').textContent==='SIMULATED ACCEPTED');assert.deepEqual(posts,[binding.native]);assert.deepEqual(applies,['D4-CANDIDATE-'+chosen.off_percent]);
 await page.setViewportSize({width:390,height:844});await open();await page.screenshot({path:path.join(output,'d4-mobile-games.png'),fullPage:true});await page.locator('[data-game-card="diablo"]').click();await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await page.locator('.card-front strong').evaluateAll(nodes=>nodes.every(node=>node.scrollWidth<=node.clientWidth+1)),true);
 await page.screenshot({path:path.join(output,'d4-mobile-offers.png'),fullPage:true});assert.deepEqual(errors,[]);assert.equal(posts.length,1);assert.equal(applies.length,1);
 console.log(JSON.stringify({status:'PASS',screenshots:output,random_models:models,random_discounts:receipts.get('diablo').slots.slice(1).map(x=>x.off_percent),native_payload:posts[0],real_cart_writes:0},null,2));
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));fs.rmSync(dir,{recursive:true,force:true});}
