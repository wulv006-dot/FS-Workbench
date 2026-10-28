// Actual local runtime/pages/receipt routes. All external requests are blocked;
// native cart and Apply are explicit synthetic responses, never live evidence.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{pathToFileURL}=require('node:url');
(async()=>{
 const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'halloween61-browser-')),load=name=>import(pathToFileURL(path.join(root,name)).href);
 const [{createPublicServer},{digest},{quantityFixture}]=await Promise.all(['runtime/server.mjs','runtime/snapshot.mjs','runtime/tests/quantity-fixture.mjs'].map(load));
 const snapshot=quantityFixture(),manifest={},names=['seasonal/index.html','seasonal/event.js','seasonal/event.css','seasonal/runtime-bridge.js','seasonal/model-selection.js','seasonal/campaign-data.js','standalone-adapter.js','activity-core.js','native-code-handoff.js','host-adapter.js'];
 for(const name of fs.readdirSync(path.join(root,'seasonal/assets')))if(/\.(png|webp|svg|jpg|woff2)$/.test(name))names.push('seasonal/assets/'+name);
 for(const name of names)manifest[name]=digest(fs.readFileSync(path.join(root,name)));
 let expiryTest=0;
 const server=createPublicServer({assetRoot:root,staticManifest:manifest,snapshotProvider:()=>snapshot,dir,origin:'https://www.mmoexp.com',priceCacheProvider:()=>{const contracts=structuredClone(snapshot.seasonal_model_contracts);for(const c of Object.values(contracts))for(const row of c.combinations){if(expiryTest)row.price.base_minor=expiryTest===1?1000:1200;row.price.expires_at=new Date(Date.now()+(expiryTest===1?1500:600000)).toISOString();}return {schema_version:1,status:'ready',release_id:snapshot.release_id,config_hash:snapshot.config_hash,generated_at:new Date().toISOString(),products:snapshot.products,model_contracts:contracts};}});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 let browser;try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage(),posts=[],applies=[],errors=[],revealIds=new Map(),revealReceipts=new Map();page.setDefaultTimeout(8000);page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());if(url.origin!=='https://www.mmoexp.com')return route.abort();
   if(url.pathname==='/Cart/add.html'){posts.push(Object.fromEntries(new URLSearchParams(req.postData())));return route.fulfill({json:{code:1}});}
   if(url.pathname==='/Cart.html')return route.fulfill({contentType:'text/html',body:'<!doctype html><title>Synthetic Cart</title><p id="result">Pending simulation</p><script>const code=sessionStorage.getItem("pending_discount_code");sessionStorage.removeItem("pending_discount_code");fetch("/__fixture/apply",{method:"POST",body:code}).then(r=>r.json()).then(r=>document.querySelector("#result").textContent=r.accepted?"SIMULATED ACCEPTED":"SIMULATED REJECTED");</script>'});
   if(url.pathname==='/__fixture/apply'){applies.push(req.postData());return route.fulfill({json:{accepted:applies.length%2===1}});}
   if(!url.pathname.startsWith('/events/'))return route.abort();
   const response=await fetch('http://127.0.0.1:'+server.address().port+url.pathname,{method:req.method(),...(req.method()==='POST'?{body:req.postData(),headers:{Origin:'https://www.mmoexp.com','Content-Type':'application/json'}}:{})});
   const bytes=Buffer.from(await response.arrayBuffer());if(url.pathname.endsWith('/halloween/reveal')&&response.ok){const r=JSON.parse(bytes);const old=revealIds.get(r.game_id);if(old)assert.equal(old,r.request_id);revealIds.set(r.game_id,r.request_id);revealReceipts.set(r.game_id,r);}
   if(url.pathname.endsWith('/api/campaign/config')&&expiryTest===1)expiryTest=2;
   return route.fulfill({status:response.status,headers:Object.fromEntries(response.headers),body:bytes});
  });
  const open=async game=>{await page.goto('https://www.mmoexp.com/events/seasonal/');await page.locator('[data-game-card="'+game+'"]').click();};
  for(const game of snapshot.halloween.games){
   await open(game.id);assert.equal(await page.locator('#campaign-published-details').count(),0);
   if(game.id==='diablo'){
    assert.equal(await page.locator('[data-game-card="diablo"] .game-art').getAttribute('src'),'assets/game-diablo-background.png');
    assert.equal(await page.locator('[data-game-card="diablo"] .game-logo').getAttribute('src'),'assets/game-diablo-logo.png');
    const shades=await page.locator('.game-card').evaluateAll(cards=>cards.map(card=>({count:card.querySelectorAll('.game-shade').length,background:getComputedStyle(card.querySelector('.game-shade')).backgroundImage})));
    assert(shades.every(s=>s.count===1&&s.background===shades[0].background));
   }
   await page.locator('[data-random-reveal="random-1"]').click();await page.waitForSelector('[data-offer-slot="random-1"] .is-revealed');
   const model=await page.locator('[data-buy-slot="random-1"]').getAttribute('data-model-buy');if(game.random_source.mode==='quantity_tiers')assert.equal(model,game.fixed_model);else{assert(game.random_models.includes(model));assert.notEqual(model,game.fixed_model);}
   await page.locator('[data-buy-slot="random-1"]').click();await page.locator('#dialog-content select').selectOption('1');assert.equal(await page.locator('#dialog-content button').isEnabled(),true);
   await page.locator('#dialog-content button').click();await page.waitForURL('**/Cart.html');await page.waitForFunction(()=>document.querySelector('#result').textContent.startsWith('SIMULATED '));assert.equal(applies.at(-1),'SYNTHETIC61-8');
   const chosen=revealReceipts.get(game.id).slots.find(s=>s.slot==='random-1');const expected=snapshot.native_checkout.bindings.find(b=>b.product_key==='synthetic61-'+model&&b.off_percent===8&&(!chosen.quantity||b.quantity.value===chosen.quantity.value)).native;assert.deepEqual(posts.at(-1),expected);
   // A consumed pending code and reload cannot repeat the same native operation.
   const count=posts.length,applyCount=applies.length;await open(game.id);await page.locator('[data-random-reveal="random-1"]').click();await page.waitForSelector('[data-offer-slot="random-1"] .is-revealed');assert.equal(await page.locator('[data-buy-slot="random-1"]').getAttribute('data-model-buy'),model);
   await page.locator('[data-buy-slot="random-1"]').click();await page.locator('#dialog-content select').selectOption('1');await page.locator('#dialog-content button').click();await page.waitForFunction(()=>document.querySelector('#dialog-content').textContent.includes('Apply and final totals remain unconfirmed'));assert.equal(posts.length,count);assert.equal(applies.length,applyCount);
   await page.locator('[data-action="close"]').click();await page.locator('[data-random-reveal="random-2"]').click();await page.waitForSelector('[data-offer-slot="random-2"] .is-revealed');if(game.random_source.mode==='quantity_tiers'){const slots=revealReceipts.get(game.id).slots;assert.notEqual(slots[1].quantity.value,slots[2].quantity.value);}else assert.notEqual(await page.locator('[data-buy-slot="random-2"]').getAttribute('data-model-buy'),model);
  }
  assert.equal(posts.length,4);assert.equal(applies.length,4);assert.equal(revealIds.size,4);assert.deepEqual(errors,[]);
  // Price expiry refreshes the open dialog without changing its amount/server.
  expiryTest=1;await open('aion');await page.locator('[data-fixed-reveal]').click();await page.locator('[data-offer-slot="fixed"] [data-model-buy]').click();await page.locator('#dialog-content select').selectOption('1');
  await page.waitForFunction(()=>document.querySelector('#dialog-content').textContent.includes('$10.80'));
  assert.equal(await page.locator('#dialog-content input').inputValue(),'10');assert.equal(await page.locator('#dialog-content select').inputValue(),'1');assert.equal(posts.length,4);assert.equal(applies.length,4);

  console.log('PASS Halloween61: four actual game pages -> distinct server mystery cards or quantity tiers -> exact option/quantity/native payload -> same-tab synthetic Cart + accepted/rejected Apply; reload never reposts; no live calls.');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
