// Carnival landing page against a simulated main site and the real FS carnival runtime logic.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {createCarnival} from '../runtime/carnival.mjs';
import {createCarnivalVerifier} from '../analytics/carnival-unlocks.mjs';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const types={'.js':'application/javascript','.html':'text/html','.css':'text/css','.webp':'image/webp'};

function mainSite({signedIn=true}={}){
 const claims=[];let memberCoupon=9000;
 const coupons={carnival_home:[1399],ms_fc27:[1401,1403,1405],bf_items:[1513,1443,1445,1447,1515,1455,1457,1459],bf_vouchers_1128:[1469,1471,1473,1475]};
 // Every goods id the page asks for gets one listed row; currency rows carry quantity tiers.
 function goods(form){
  const top=Number(form.get('top_cid')),row=id=>({id,status:1,auto_off:0,min_qty:1,price_discount_format:'10.00',game_area_format:'Israphel - Asmodian',
   goods_list:top===1?Object.fromEntries([3,5,8,10,20,30,50,70,100,200,300,500,600,800,1000,1500,2000].map(q=>[String(q),{price_discount_format:(q*0.1).toFixed(2)}])):undefined});
  const ids={9623:[163329311,163329277,163329345],9627:[170015253,170015245,170015249,170017913,170015181,170015205],9661:[165167189],6955:[105267633],9991:[187090053],10079:[186209371],1338:[186208657],3955:[170070065]}[form.get('category_id')]||[];
  return {goods:{index:{total:ids.length,perpage:28,list:ids.map(row)}}};
 }
 return {claims,handle(url,req){
  if(url.pathname==='/ajax/carnival/user')return {code:1,data:{enabled:true,logged_in:signedIn,uid:signedIn?'123456':'',spend_amount:150,tier_thresholds:[1,100,300,500,800,1000]}};
  if(url.pathname==='/ajax/carnival/coupon'){const slot=url.searchParams.get('slot');return {code:1,data:{enabled:true,logged_in:signedIn,slot,list:(coupons[slot]||[]).map(id=>({coupon_id:id,can_claim:true,claim_status:'claimable'}))}};}
  if(url.pathname==='/ajax/carnival/claim'){const body=new URLSearchParams(req.postData());claims.push({slot:body.get('slot'),coupon_id:Number(body.get('coupon_id'))});return {code:1,data:{claim_status:'claimed',coupon_id:Number(body.get('coupon_id')),member_coupon_id:++memberCoupon}};}
  if(url.pathname==='/ajax/goods')return goods(new URLSearchParams(req.postData()));
  if(url.pathname==='/ajax/html')return '';
  return null;
 }};
}

async function open(t,{clock='2026-11-28T13:00:00-05:00',signedIn=true}={}){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'carnival-page-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const tick={ms:Date.parse(clock)},paidUses=[];
 const carnival=createCarnival({dir,publishedDir:dir,now:()=>tick.ms}),site=mainSite({signedIn});
 // The dashboard side of "verify": answers queued requests from a simulated Admin coupon log.
 const verifier=createCarnivalVerifier({publicDir:dir,requestDir:path.join(dir,'carnival-verify'),now:()=>tick.ms,read:async()=>({status:'available',generated_at:'t',uses:paidUses})});
 const browser=await chromium.launch({headless:true});t.after(()=>browser.close());
 const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(8000);
 await page.clock.setFixedTime(new Date(clock));
 // A returning visitor who already answered the analytics question (the dialog is covered separately).
 await page.addInitScript(()=>{try{localStorage.setItem('mmoexp-event-analytics-consent-v1','denied');localStorage.setItem('mmoexp-event-google-consent-v1','denied');}catch{}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.origin!=='https://www.mmoexp.com')return route.fulfill({status:204,body:''});
  try{
   if(url.pathname==='/events/api/carnival/schedule')return route.fulfill({json:carnival.schedule()});
   if(url.pathname==='/events/api/carnival/mystery')return route.fulfill({json:carnival.state(url.searchParams)});
   if(url.pathname==='/events/api/carnival/mystery/draw')return route.fulfill({json:carnival.draw(JSON.parse(req.postData()))});
   if(url.pathname==='/events/api/carnival/mystery/verify'){const answer=carnival.verify(JSON.parse(req.postData()));verifies++;await verifier.refresh();return route.fulfill({json:answer});}
  }catch(e){return route.fulfill({status:e.status||500,json:{code:e.code}});}
  const answer=site.handle(url,req);if(answer!==null)return typeof answer==='string'?route.fulfill({body:answer}):route.fulfill({json:answer});
  const file=path.join(app,url.pathname.replace(/^\/events\//,''));
  if(!url.pathname.startsWith('/events/')||!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({contentType:types[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
 });
 let verifies=0;
 await page.goto('https://www.mmoexp.com/events/Carnival.html');
 await page.waitForFunction(()=>document.querySelectorAll('#msPool .pcard').length===9);
 return {page,site,errors,carnival,tick,paidUses,verifies:()=>verifies};
}

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
 await page.waitForSelector('[data-carnival-go]');
 assert.deepEqual(site.claims,[{slot:'ms_fc27',coupon_id:saved.picks[0].coupon_id}]);
 assert.equal(await page.evaluate(()=>sessionStorage.getItem('pending_member_coupon_id')),'9001');
 assert.equal(await page.locator('[data-carnival-go]').getAttribute('href'),'/Fc-27/Coins.html');
 assert.deepEqual(errors,[]);
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
 // A product coupon is claimed and the page stays put; going to the product is the member's click.
 await page.locator('.store-categories [data-category="currency"]').click();
 await page.locator('#flashGrid [data-carnival-product]').first().click();
 await page.waitForSelector('#mysteryFlowMask.show [data-carnival-go]');
 assert.deepEqual(site.claims.at(-1),{slot:'bf_items',coupon_id:1513});
 assert.equal(await page.locator('[data-carnival-go]').getAttribute('href'),'/Fc-27/Coins.html');
 assert.match(page.url(),/\/events\/Carnival\.html/);
 await page.evaluate(()=>closeMysteryFlow());
 assert.equal(await page.locator('#spendVal').textContent(),'$150.00');
 assert.equal(await page.locator('#drawBtn').isDisabled(),true,'capsule draws stay closed until the claim interface exists');
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

test('before Black Friday no products reach the page',async t=>{
 const {page}=await open(t,{clock:'2026-11-20T10:00:00-05:00'});
 await page.locator('a[href="#flash"]').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('#flashGrid .flash-mystery').length===4);
 assert.equal(await page.locator('#flashGrid [data-carnival-product]').count(),0);
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
