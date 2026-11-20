// Carnival landing page browser checks (run as its own script by pr_fast; see carnival-browser-harness.mjs).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createCarnival} from '../runtime/carnival.mjs';
import {mainSite,open,app,types,chromium,lobbyCatalog,lobbyOffers} from './carnival-browser-harness.mjs';

test('mystery shop: live prices, one server draw that survives reload, coupon handed to the cart',async t=>{
 const {page,site,errors,carnival}=await open(t);
 await page.waitForFunction(()=>[...document.querySelectorAll('#msPool .pprice')].some(p=>/\$\d/.test(p.textContent)));
 assert.equal(await page.locator('#mysteryDemoNotice').count(),0,'demo notice removed');
 await page.locator('a[href="#mystery"]').first().click(); // on Nov 28 the page opens on Black Friday
 for(const i of [0,1,2])await page.locator('#msPool .pcard').nth(i).click();
 await page.locator('.drawdeal-btn').click();
 await page.waitForFunction(()=>document.querySelectorAll('#msResult .fcard.open').length===3);
 const offs=await page.locator('#msResult .rv-off').allTextContents();
 const saved=carnival.state(new URLSearchParams({uid:'123456'})).games.fc27.current;
 assert.deepEqual(offs,saved.picks.map(p=>p.off+'% OFF'));
 await page.reload();await page.waitForFunction(()=>document.querySelectorAll('#msResult .fcard').length===3);
 assert.deepEqual(await page.locator('#msResult .rv-off').allTextContents(),offs,'reload shows the stored round');
 assert.match(await page.locator('#msTimer').textContent(),/AFTER PAYMENT/);
 await page.locator('a[href="#mystery"]').first().click();
 await page.locator('#msResult .buybtn').first().click();
 await page.waitForSelector('#mysteryFlowMask.show [data-carnival-buy]');
 assert.deepEqual(site.claims,[{slot:'ms_fc27',coupon_id:saved.picks[0].coupon_id}]);
 assert.equal(await page.evaluate(()=>sessionStorage.getItem('pending_member_coupon_id')),'9001');
 assert.equal(await page.locator('#mysteryFlowMask a[href]').count(),0,'no product-page link');
 assert.deepEqual(errors,[]);
 // Checkout now: the cart is emptied, the drawn item is added once and the cart page opens.
 await page.locator('#mysteryFlowMask.show [data-carnival-buy]').click();
 await page.waitForURL('**/Cart.html');
 assert.equal(site.cart.clears,1);
 assert.equal(site.cart.adds.length,1);
});

test('mystery shop: the verify button checks the order once per press and resets the round when paid',async t=>{
 const {page,errors,tick,paidUses,verifies}=await open(t);
 await page.locator('a[href="#mystery"]').first().click();
 for(const i of [0,1,2])await page.locator('#msPool .pcard').nth(i).click();
 await page.locator('.drawdeal-btn').click();
 await page.waitForFunction(()=>document.querySelectorAll('#msResult .fcard.open').length===3);
 const offs=await page.locator('#msResult .rv-off').allTextContents();
 assert.ok(offs.includes('15% OFF'),'first round shows a 15% card');
 await page.waitForSelector('#msVerifyBtn');
 // Not paid yet.
 await page.locator('#msVerifyBtn').click();
 await page.waitForFunction(()=>/not completed/.test(document.getElementById('mysteryFlowTitle')?.textContent||''));
 assert.equal(verifies(),1);
 await page.evaluate(()=>closeMysteryFlow());
 // Paid with this round's coupon; pressed again after the 30-second spacing.
 tick.ms+=31000;paidUses.push({uid:'123456',set:'fc27',used_at:new Date(tick.ms-1000).toISOString()});
 await page.locator('#msVerifyBtn').click();
 await page.waitForFunction(()=>/verified/.test(document.getElementById('mysteryFlowTitle')?.textContent||''));
 assert.equal(verifies(),2);
 await page.evaluate(()=>closeMysteryFlow());
 assert.equal(await page.locator('#msPool').isVisible(),true,'a fresh pick is open');
 assert.equal(await page.locator('#msVerifyBtn').count(),0);
 assert.match(await page.locator('#msTimer').textContent(),/READY/);
 assert.deepEqual(errors,[]);
});

test('guests are asked to sign in before drawing and nothing is written',async t=>{
 const {page,site,carnival}=await open(t,{signedIn:false});
 await page.locator('a[href="#mystery"]').first().click(); // on Nov 28 the page opens on Black Friday
 for(const i of [0,1,2])await page.locator('#msPool .pcard').nth(i).click();
 await page.locator('.drawdeal-btn').click();
 await page.waitForSelector('#loginRequiredMask.show form.carnival-login');
 assert.deepEqual(site.claims,[]);
 assert.equal(carnival.state(new URLSearchParams({uid:'123456'})).games.fc27.rounds_drawn,0);
});

for(const [platform,{aid,goods,skuIds}] of Object.entries(lobbyCatalog)){
 test(`COD ${platform}: each lobby quote adds its own SKU without placing an order`,async t=>{
  const {page,site,errors}=await open(t);
  const openCod=async()=>{
   await page.locator('a[href="#mystery"]').first().click();
   await page.locator('.gtab.game-codmw4').click();
  };
  await openCod();
  await page.locator('#marketChoiceSelect').selectOption(platform);
  for(const offer of lobbyOffers){
   const card=page.locator('#msPool .pcard').filter({hasText:offer.name});
   await page.waitForFunction(({name,price})=>[...document.querySelectorAll('#msPool .pcard')].some(card=>
    card.querySelector('h4').textContent===name&&card.querySelector('.pprice').textContent==='$'+price),offer);
   await card.click();
  }
  await page.locator('#msPool .pcard').nth(1).click();
  await page.locator('.drawdeal-btn').click();
  await page.waitForSelector('#msVerifyBtn');
  for(const [index,offer] of lobbyOffers.entries()){
   if(index){
    await page.goto('https://www.mmoexp.com/events/Carnival.html');
    await openCod();
   }
   const card=page.locator('#msResult .fcard').filter({hasText:offer.name});
   await card.getByText('$'+offer.price,{exact:true}).first().waitFor();
   await card.locator('.buybtn').click();
   await page.waitForSelector('#mysteryFlowMask.show [data-carnival-buy]');
   assert.ok((await page.locator('#mysteryFlowMask .mystery-flow-box').textContent()).includes('$'+offer.price+' →'));
   // A price-only update keeps the advertised cart line valid.
   if(!index)site.firstLobbySku={price:'4.25'};
   await page.locator('#mysteryFlowMask.show [data-carnival-buy]').click();
   await page.waitForURL('**/Cart.html');
   assert.deepEqual(site.cart.adds,[{category:'new_items',id:String(goods),group:'1',num:'1',attr:skuIds[index]+'-'+offer.name,aid:String(aid)}]);
  }
  assert.equal(site.cart.clears,2);
  assert.deepEqual(errors,[]);
 });
}

test('a missing lobby SKU does not use the parent price or modify the cart',async t=>{
 const {page,site,carnival}=await open(t);
 site.missingLobbySku=lobbyCatalog.PC.skuIds[0];
 carnival.draw({uid:'123456',game:'codmw4',items:[0,1,3]});
 await page.reload();
 await page.locator('a[href="#mystery"]').first().click();
 await page.locator('.gtab.game-codmw4').click();
 await page.locator('#msResult .fcard').filter({hasText:lobbyOffers[1].name}).getByText('$23.98',{exact:true}).first().waitFor();
 const missing=page.locator('#msResult .fcard').filter({hasText:lobbyOffers[0].name});
 assert.equal(await missing.locator('.price-row').textContent(),'PRICE PENDING');
 await missing.locator('.buybtn').click();
 await page.locator('#mysteryFlowMask.show [data-carnival-buy]').click();
 await page.locator('#toast.show').getByText('This item cannot be added right now. Please try again in a moment.').waitFor();
 assert.equal(site.cart.clears,0);
 assert.deepEqual(site.cart.adds,[]);
});

for(const [change,catalogChange] of [
 ['sells out',{firstLobbySku:{stock:0}}],
 ['requires a higher purchase quantity',{lobbyMinQty:5}],
 ['changes to a same-name replacement SKU',{firstLobbySku:{id:999999}}],
]){
 test(`a lobby offer that ${change} after the quote leaves the existing cart untouched`,async t=>{
  const {page,site,carnival}=await open(t);
  carnival.draw({uid:'123456',game:'codmw4',items:[0,1,3]});
  await page.reload();
  await page.locator('a[href="#mystery"]').first().click();
  await page.locator('.gtab.game-codmw4').click();
  const offer=lobbyOffers[0],card=page.locator('#msResult .fcard').filter({hasText:offer.name});
  await card.getByText('$'+offer.price,{exact:true}).first().waitFor();
  await card.locator('.buybtn').click();
  const checkout=page.locator('#mysteryFlowMask.show [data-carnival-buy]');
  await checkout.waitFor();
  const existingLine={category:'new_items',id:'185981107',group:'1',num:'1',attr:'',aid:'19835'};
  site.cart.adds.push(existingLine);
  Object.assign(site,catalogChange);
  const unavailable=page.locator('#toast.show').getByText('This item cannot be added right now. Please try again in a moment.');
  await checkout.click();
  await Promise.race([unavailable.waitFor(),page.waitForURL('**/Cart.html')]);
  assert.equal(site.cart.clears,0);
  assert.deepEqual(site.cart.adds,[existingLine]);
  assert.equal(await unavailable.isVisible(),true);
 });
}

test('a localized formatted price cannot be quoted as USD or reach the cart',async t=>{
 const {page,site,carnival}=await open(t);
 site.formattedOnlyGoods=185981107;
 carnival.draw({uid:'123456',game:'arc',items:[0,1,7]});
 await page.goto('https://www.mmoexp.com/events/Carnival.html?price_debug=1');
 await page.addStyleTag({content:'#priceDebug{display:none!important}'});
 await page.locator('a[href="#mystery"]').first().click();
 await page.locator('.gtab.game-arc').click();
 const card=page.locator('#msResult .fcard').filter({hasText:'Stencil Parts'});
 await page.waitForFunction(()=>/185981107 q1 a19835: (ok|no price)/.test(document.getElementById('priceDebug')?.textContent||''));
 assert.match(await page.locator('#priceDebug').textContent(),/185981107 q1 a19835: no price/);
 assert.equal(await card.locator('.price-row').textContent(),'PRICE PENDING');
 await card.locator('.buybtn').click();
 const checkout=page.locator('#mysteryFlowMask.show [data-carnival-buy]');
 const unavailable=page.locator('#toast.show').getByText('This item cannot be added right now. Please try again in a moment.');
 await checkout.click();
 await Promise.race([unavailable.waitFor(),page.waitForURL('**/Cart.html')]);
 assert.equal(site.cart.clears,0);
 assert.deepEqual(site.cart.adds,[]);
 assert.equal(await unavailable.isVisible(),true);
});
