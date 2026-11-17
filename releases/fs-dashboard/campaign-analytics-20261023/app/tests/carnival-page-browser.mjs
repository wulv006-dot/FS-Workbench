// Carnival landing page browser checks (run as its own script by pr_fast; see carnival-browser-harness.mjs).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createCarnival} from '../runtime/carnival.mjs';
import {mainSite,open,app,types,chromium} from './carnival-browser-harness.mjs';

test('home coupon, Black Friday session and gacha spend',async t=>{
 const {page,site,errors}=await open(t);
 await page.locator('#heroEarlyBtn').click();await page.locator('#couponClaimBtn').click();
 await page.waitForFunction(()=>document.getElementById('heroEarlyBtn').classList.contains('claimed'));
 assert.deepEqual(site.claims.at(-1),{slot:'carnival_home',coupon_id:1399});
 // Session 4 (Nov 28, 12:00–16:00 ET) is live: products and vouchers are released.
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid [data-carnival-product]').length===4);
 await page.waitForFunction(()=>!document.querySelector('#flashGrid [data-carnival-product]:disabled'));
 await page.locator('.store-categories [data-category="voucher"]').click();
 await page.locator('#flashGrid [data-carnival-voucher]').first().click();
 await page.waitForFunction(n=>document.querySelectorAll('#flashGrid [data-carnival-voucher]:not(:disabled)').length===4,null);
 assert.deepEqual(site.claims.at(-1),{slot:'bf_vouchers_1128',coupon_id:1469});
 // A product coupon is claimed and the page stays put; checkout is the member's click.
 await page.locator('.store-categories [data-category="currency"]').click();
 await page.locator('#flashGrid [data-carnival-product]').first().click();
 await page.waitForSelector('#mysteryFlowMask.show [data-carnival-buy]');
 assert.deepEqual(site.claims.at(-1),{slot:'bf_items',coupon_id:1513});
 assert.equal(await page.locator('[data-carnival-go]').getAttribute('href'),'/Fc-27/Coins.html');
 assert.match(page.url(),/\/events\/Carnival\.html/);
 assert.equal(site.cart.clears,0,'nothing touches the cart before the member asks to check out');
 await page.evaluate(()=>closeMysteryFlow());
 assert.equal(await page.locator('#spendVal').textContent(),'$150.00');
 assert.equal(await page.locator('#drawBtn').isDisabled(),true,'capsule draws stay closed until the claim interface exists');
 assert.deepEqual(errors,[]);
});

test('checkout now empties the cart, adds the claimed item and opens the cart with the coupon',async t=>{
 const {page,site}=await open(t);
 await page.locator('.store-categories [data-category="currency"]').click();
 await page.waitForFunction(()=>!document.querySelector('#flashGrid [data-carnival-product]:disabled'));
 await page.locator('#flashGrid [data-carnival-product]').first().click();
 await page.locator('#mysteryFlowMask.show [data-carnival-buy]').click();
 await page.waitForURL('**/Cart.html');
 assert.equal(site.cart.clears,1);
 assert.equal(site.cart.adds.length,1);
 assert.equal(site.cart.adds[0].category,'new_gold');
 assert.equal(await page.evaluate(()=>sessionStorage.getItem('pending_member_coupon_id')),String(site.claimed.get(1513)));
});

test('the home coupon is claimed once, then the button is grey and says so',async t=>{
 const {page,site}=await open(t);
 await page.locator('#heroEarlyBtn').click();await page.locator('#couponClaimBtn').click();
 await page.waitForFunction(()=>document.getElementById('heroEarlyBtn').disabled);
 await page.reload();
 await page.waitForFunction(()=>document.getElementById('heroEarlyBtn').disabled&&document.getElementById('heroEarlyBtn').classList.contains('claimed'));
 assert.match(await page.locator('#couponSpeech').textContent(),/CLAIMED/);
 assert.equal(await page.locator('#heroEarlyBtn').evaluate(b=>getComputedStyle(b).backgroundImage),'none','the gold gradient is replaced by grey');
 assert.equal(site.claims.length,1);
});

test('switching Mystery Shop games moves the selection and loads that game',async t=>{
 const {page,errors}=await open(t);
 for(const id of ['aion2','d4','wow','fc27']){
  await page.locator(`.gtab.game-${id}`).first().dispatchEvent('click');
  await page.waitForFunction(g=>curGame===g&&!!document.querySelector('.gtab.on.game-'+g),id);
 }
 assert.deepEqual(errors,[]);
});

test('before Black Friday no products reach the page',async t=>{
 const {page}=await open(t,{clock:'2026-11-20T10:00:00-05:00'});
 await page.locator('a[href="#flash"]').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid .flash-mystery').length===4);
 assert.equal(await page.locator('#flashGrid [data-carnival-product]').count(),0);
});

test('placeholder cards keep the ? centred',async t=>{
 const {page}=await open(t,{clock:'2026-11-20T10:00:00-05:00'});
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid .flash-mystery').length===4);
 const gap=await page.evaluate(()=>{const card=document.querySelector('#flashGrid .flash-mystery').getBoundingClientRect(),icon=document.querySelector('#flashGrid .flash-mystery .ficon').getBoundingClientRect();return Math.abs((icon.left-card.left)-(card.right-icon.right));});
 assert.ok(gap<=2,'left and right space differ by '+gap+'px');
});

test('header follows the main site: sign-in state, cart, no language switch',async t=>{
 const {page}=await open(t,{clock:'2026-11-20T10:00:00-05:00'});
 assert.equal(await page.locator('#langEn, #langZh, .lang-sw').count(),0);
 assert.equal(await page.locator('.fca-demo-header .fca-brand img').getAttribute('src'),'assets/mmoexp-logo.png');
 await page.waitForFunction(()=>document.querySelector('.fca-demo-header [data-account-login]').hidden);
 assert.equal(await page.locator('.fca-demo-header .fca-account-user').isVisible(),true);
 // FC27 platform choice is shown and switches the platform.
 const trigger=page.locator('#fc27PlatformBar .game-select-trigger');
 assert.equal(await trigger.isVisible(),true,'FC27 platform choice is shown');
 assert.match(await trigger.textContent(),/PlayStation/);
 await trigger.click();await page.locator('.game-select-menu [role="option"]',{hasText:'Xbox'}).click();
 assert.equal(await page.locator('#fc27Platform').inputValue(),'xbox');
});

test('a guest sees Log In in the header and it opens the sign-in box',async t=>{
 const {page}=await open(t,{clock:'2026-11-20T10:00:00-05:00',signedIn:false});
 await page.locator('.fca-demo-header [data-account-login]').click();
 await page.waitForSelector('#loginRequiredMask.show form.carnival-login');
});

test('internal test before the event: everything open and every claim uses the test coupon',async t=>{
 const {page,site,errors}=await open(t,{clock:'2026-11-17T10:00:00-05:00',internalTest:{open_until:'2026-11-18T23:00:00-05:00',coupon_id:1601,slot:'carnival_test'}});
 await page.waitForFunction(()=>document.documentElement.hasAttribute('data-carnival-test'));
 await page.locator('#heroEarlyBtn').click();await page.locator('#couponClaimBtn').click();
 await page.waitForFunction(()=>document.getElementById('heroEarlyBtn').classList.contains('claimed'));
 assert.deepEqual(site.claims.at(-1),{slot:'carnival_test',coupon_id:1601});
 await page.locator('a[href="#flash"]').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid [data-carnival-product]:not(:disabled)').length>0);
 await page.locator('#flashGrid [data-carnival-product]').first().click();
 await page.waitForSelector('#mysteryFlowMask.show [data-carnival-go]');
 assert.deepEqual(site.claims.at(-1),{slot:'carnival_test',coupon_id:1601});
 assert.deepEqual(errors,[]);
});

test('first visit asks the analytics question on the carnival page',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'carnival-consent-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const carnival=createCarnival({dir,publishedDir:dir,now:()=>Date.parse('2026-11-20T10:00:00-05:00')}),site=mainSite();
 const browser=await chromium.launch({headless:true});t.after(()=>browser.close());
 const page=await browser.newPage();await page.clock.setFixedTime(new Date('2026-11-20T10:00:00-05:00'));
 await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());if(url.origin!=='https://www.mmoexp.com')return route.fulfill({status:204,body:''});
  if(url.pathname==='/events/api/carnival/schedule')return route.fulfill({json:carnival.schedule()});
  if(url.pathname==='/events/api/carnival/mystery')return route.fulfill({json:carnival.state(url.searchParams)});
  const answer=site.handle(url,req);if(answer!==null)return typeof answer==='string'?route.fulfill({body:answer}):route.fulfill({json:answer});
  const file=path.join(app,url.pathname.replace(/^\/events\//,''));return fs.existsSync(file)?route.fulfill({contentType:types[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)}):route.fulfill({status:404,body:''});});
 await page.goto('https://www.mmoexp.com/events/Carnival.html');
 await page.waitForSelector('dialog#seasonal-analytics-choice[open]');
 await page.getByRole('button',{name:'No thanks'}).click();
 assert.equal(await page.evaluate(()=>localStorage.getItem('mmoexp-event-analytics-consent-v1')),'denied');
 assert.equal(await page.evaluate(()=>window.FCActivityAnalytics.status().consent),false);
});
