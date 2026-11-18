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
 assert.equal(await page.locator('#mysteryFlowMask a[href]').count(),0,'no product-page link');
 assert.match(page.url(),/\/events\/Carnival\.html/);
 assert.equal(site.cart.clears,0,'nothing touches the cart before the member asks to check out');
 await page.evaluate(()=>closeMysteryFlow());
 assert.equal(await page.locator('#spendVal').textContent(),'$150.00');
 assert.equal(await page.locator('#drawBtn').isDisabled(),true,'capsule draws open on Nov 30');
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

test('capsule tiers follow the paid total the main site reports, and grow as it grows',async t=>{
 const {page,site,errors}=await open(t);
 const read=()=>page.evaluate(()=>({spend:document.getElementById('spendVal').textContent,hit:[...document.querySelectorAll('#spendMarks span.hit')].map(s=>s.firstChild.textContent)}));
 // Each reload is a later visit after more paid orders; the tiers reached so far stay lit.
 for(const [spend,hit] of [[0,[]],[0.99,[]],[1,['$1']],[99.99,['$1']],[100,['$1','$100']],[520,['$1','$100','$300','$500']],[1000,['$1','$100','$300','$500','$800','$1000']],[1500,['$1','$100','$300','$500','$800','$1000']]]){
  site.spend=spend;await page.reload();
  await page.waitForFunction(s=>document.getElementById('spendVal').textContent===s,'$'+spend.toFixed(2));
  assert.deepEqual(await read(),{spend:'$'+spend.toFixed(2),hit},'paid total $'+spend);
 }
 assert.equal(await page.locator('#drawBtn').isDisabled(),true,'capsule draws open on Nov 30');
 assert.deepEqual(errors,[]);
});

const CM='2026-11-30T10:00:00-05:00';
test('capsule: a $1.54 order before Nov 30 shows one draw ready and a full first segment',async t=>{
 const {page,site,errors}=await open(t);
 site.spend=1.54;await page.reload();
 await page.waitForFunction(()=>/READY/.test(document.getElementById('drawBtn').textContent));
 const v=await page.evaluate(()=>({
  draws:document.querySelector('#mCost strong').textContent,
  btn:document.getElementById('drawBtn').textContent,
  disabled:document.getElementById('drawBtn').disabled,
  segs:[...document.querySelectorAll('.spendbar .seg b')].map(b=>b.style.width),
  mark:document.querySelector('#spendMarks span.hit small').textContent,
  next:document.getElementById('nextAt').textContent}));
 assert.deepEqual(v,{draws:'1',btn:'1 DRAW READY · OPENS NOV 30',disabled:true,segs:['100%','0.5%','0%','0%','0%','0%'],mark:'✓ Unlocked',next:'Next draw at $100 · $98.46 to go'});
 assert.equal(capsuleClaims(site).length,0);
 assert.deepEqual(errors,[]);
});
const capsuleClaims=site=>site.claims.filter(c=>c.slot==='capsule').map(c=>c.coupon_id);
async function draw(page){
 await page.waitForFunction(()=>!document.getElementById('drawBtn').disabled);
 await page.locator('#drawBtn').click();
 await page.waitForSelector('#modalMask.show');
 const won=await page.locator('#gachaCoupon .unified-coupon').count();
 await page.evaluate(()=>closeModal());return won;
}

test('capsule: one $1000 order claims all six tiers in one draw',async t=>{
 const {page,site,errors}=await open(t,{clock:CM});
 site.spend=1000;await page.reload();
 await page.waitForFunction(()=>document.getElementById('drawBtn').textContent.includes('6'));
 assert.equal(await draw(page),6);
 assert.deepEqual(capsuleClaims(site),[1501,1503,1505,1507,1509,1511]);
 await page.waitForFunction(()=>document.getElementById('drawBtn').disabled&&/POOL CLEARED/.test(document.getElementById('drawBtn').textContent));
 assert.equal(await page.locator('#pool .pitem.gone').count(),6);
 assert.deepEqual(errors,[]);
});

test('capsule: spend that grows claims only the newly reached tiers, never twice',async t=>{
 const {page,site,errors}=await open(t,{clock:CM});
 // $150 → $1 and $100 tiers.
 assert.equal(await draw(page),2);assert.deepEqual(capsuleClaims(site),[1501,1503]);
 // No new spend: nothing to draw.
 await page.reload();await page.waitForFunction(()=>/SPEND MORE/.test(document.getElementById('drawBtn').textContent));
 assert.equal(await page.locator('#drawBtn').isDisabled(),true);
 // $610 crosses two tiers at once.
 site.spend=610;await page.reload();
 assert.equal(await draw(page),2);assert.deepEqual(capsuleClaims(site),[1501,1503,1505,1507]);
 // $1000 reaches the last two.
 site.spend=1000;await page.reload();
 assert.equal(await draw(page),2);assert.deepEqual(capsuleClaims(site),[1501,1503,1505,1507,1509,1511]);
 // A refund lowers the paid total; coupons already issued stay issued (Admin revokes by hand).
 site.spend=200;await page.reload();await page.waitForFunction(()=>/POOL CLEARED/.test(document.getElementById('drawBtn').textContent));
 assert.equal(capsuleClaims(site).length,6);
 assert.deepEqual(errors,[]);
});

test('capsule: below $1 nothing is drawn; without the Admin capsule slot draws stay closed',async t=>{
 const {page,site,errors}=await open(t,{clock:CM});
 site.spend=0.99;await page.reload();
 await page.waitForFunction(()=>/SPEND MORE/.test(document.getElementById('drawBtn').textContent));
 assert.equal(await page.locator('#drawBtn').isDisabled(),true);
 site.spend=1000;site.capsuleSlot=false;await page.reload();
 await page.waitForFunction(()=>/OPEN SOON/.test(document.getElementById('drawBtn').textContent));
 assert.equal(await page.locator('#drawBtn').isDisabled(),true);
 assert.equal(capsuleClaims(site).length,0);
 assert.deepEqual(errors,[]);
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

test('an ended Black Friday session still shows its line-up, greyed, stamped and closed',async t=>{
 const {page,site,errors}=await open(t);
 // Session 1 (Nov 27, 12:00–16:00 ET) ended before the clock (Nov 28, 13:00 ET).
 await page.evaluate(()=>{curSess=0;renderSessTabs();renderFlash();});
 await page.locator('.store-categories [data-category="currency"]').click();
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid .flash-real.flash-ended').length===4);
 const cards=await page.evaluate(()=>[...document.querySelectorAll('#flashGrid .flash-real')].map(c=>({stamp:c.querySelector('.flash-ended-stamp')?.textContent,button:c.querySelector('[data-carnival-product]').disabled,selects:[...c.querySelectorAll('select')].every(s=>s.disabled),grey:getComputedStyle(c).filter})));
 assert.ok(cards.every(c=>c.stamp==='ENDED'&&c.button&&c.selects&&/grayscale/.test(c.grey)),JSON.stringify(cards));
 await page.locator('#flashGrid [data-carnival-product]').first().click({force:true});
 await page.locator('.store-categories [data-category="voucher"]').click();
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid .flash-coupon.flash-ended [data-carnival-voucher]:disabled').length===4);
 assert.equal(site.claims.length,0,'nothing can be claimed from an ended session');
 assert.deepEqual(errors,[]);
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
 // The capsule opens for the internal test too (user, 11/18): tier claims use the real capsule slot.
 site.spend=1000;await page.reload();
 await page.locator('a[href="#gacha"]').first().click();
 await page.waitForFunction(()=>!document.getElementById('drawBtn').disabled&&/DRAW 6/.test(document.getElementById('drawBtn').textContent));
 await page.locator('#drawBtn').click();
 await page.waitForFunction(()=>document.getElementById('modalMask').classList.contains('show'));
 assert.deepEqual(capsuleClaims(site),[1501,1503,1505,1507,1509,1511]);
 await page.evaluate(()=>document.getElementById('modalMask').classList.remove('show'));
 await page.locator('a[href="#flash"]').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid [data-carnival-product]:not(:disabled)').length>0);
 await page.locator('#flashGrid [data-carnival-product]').first().click();
 await page.waitForSelector('#mysteryFlowMask.show [data-carnival-buy]');
 // Every claim outside the capsule still goes to the test coupon.
 assert.deepEqual([...new Set(site.claims.filter(c=>c.slot!=='capsule').map(c=>c.slot+':'+c.coupon_id))],['carnival_test:1601']);
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
