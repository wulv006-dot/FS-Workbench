// Carnival landing page browser checks (run as its own script by pr_fast; see carnival-browser-harness.mjs).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createCarnival} from '../runtime/carnival.mjs';
import {mainSite,open,app,types,chromium} from './carnival-browser-harness.mjs';

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

test('guests are asked to sign in before drawing and nothing is written',async t=>{
 const {page,site,carnival}=await open(t,{signedIn:false});
 await page.locator('a[href="#mystery"]').first().click(); // on Nov 28 the page opens on Black Friday
 for(const i of [0,1,2])await page.locator('#msPool .pcard').nth(i).click();
 await page.locator('.drawdeal-btn').click();
 await page.waitForSelector('#loginRequiredMask.show form.carnival-login');
 assert.deepEqual(site.claims,[]);
 assert.equal(carnival.state(new URLSearchParams({uid:'123456'})).games.fc27.rounds_drawn,0);
});
