// Carnival landing page against a simulated main site and the real FS carnival runtime logic.
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

export function mainSite({signedIn=true}={}){
 const claims=[],claimed=new Map(),cart={clears:0,adds:[]};let memberCoupon=9000;
 const coupons={carnival_home:[1399],ms_fc27:[1401,1403,1405],bf_items:[1513,1443,1445,1447,1515,1455,1457,1459],bf_vouchers_1128:[1469,1471,1473,1475],carnival_test:[1601]};
 // Every goods id the page asks for gets one listed row; currency rows carry quantity tiers.
 // A tier's _format price is the visitor-currency/new-user display price; price_discount is USD.
 function goods(form){
  const top=Number(form.get('top_cid')),row=id=>({id,status:1,auto_off:0,min_qty:1,price_discount_format:'10.00',game_area_format:'Israphel - Asmodian',
   goods_list:top===1?Object.fromEntries([3,5,8,10,20,30,50,70,100,200,300,500,600,800,1000,1500,2000].map(q=>[String(q),{price_discount:Math.round(q*12)/100,price_discount_format:(q*0.1).toFixed(2)}])):undefined});
  const ids={9623:[163329311,163329277,163329345],9627:[170015253,170015245,170015249,170017913,170015181,170015205],9661:[165167189],6955:[105267633],9991:[187090053],10079:[186209371],1338:[186208657],3955:[170070065],7111:[185981107,185981139,185981171]}[form.get('category_id')]||[];
  return {goods:{index:{total:ids.length,perpage:28,list:ids.map(row)}}};
 }
 // Tier coupons (Admin 档位配券): spend-checked by the main site, as in its API document.
 const tierSpend={1501:1,1503:100,1505:300,1507:500,1509:800,1511:1000};
 // site.spend: the member's carnival paid total as the main site reports it (tests change it).
 // site.capsuleSlot=false models Admin without the "capsule" 入口 (invalid_slot).
 const site={claims,claimed,cart,spend:150,capsuleSlot:true,handle(url,req){
  if(url.pathname==='/ajax/carnival/user')return {code:1,data:{enabled:true,logged_in:signedIn,uid:signedIn?'123456':'',spend_amount:site.spend,tier_thresholds:[1,100,300,500,800,1000]}};
  const slots={...coupons,...(site.capsuleSlot?{capsule:[1501,1503,1505,1507,1509,1511]}:{})};
  const row=id=>{const tier=tierSpend[id]!==undefined?{required_spend:tierSpend[id],unlocked:site.spend>=tierSpend[id]}:{};
   if(claimed.has(id))return {coupon_id:id,can_claim:false,claim_status:'claimed',member_coupon_id:claimed.get(id),...tier};
   if(tier.unlocked===false)return {coupon_id:id,can_claim:false,claim_status:signedIn?'locked':'guest',...tier};
   return {coupon_id:id,can_claim:true,claim_status:'claimable',...tier};};
  if(url.pathname==='/ajax/carnival/coupon'){const slot=url.searchParams.get('slot');
   if(!slots[slot])return {code:1,data:{enabled:true,logged_in:signedIn,slot:'',list:[],error:'invalid_slot'}};
   return {code:1,data:{enabled:true,logged_in:signedIn,slot,spend_amount:site.spend,list:slots[slot].map(row)}};}
  if(url.pathname==='/ajax/carnival/claim'){const body=new URLSearchParams(req.postData()),id=Number(body.get('coupon_id')),slot=body.get('slot');
   if(!slots[slot]?.includes(id))return {code:0,msg:'Invalid slot.',data:{error:'invalid_slot'}};
   if(tierSpend[id]!==undefined&&site.spend<tierSpend[id])return {code:0,msg:'Spend more to unlock this coupon.',data:{claim_status:'locked',required_spend:tierSpend[id],spend_amount:site.spend}};
   if(claimed.has(id))return {code:1,msg:'Coupon already claimed.',data:{claim_status:'claimed',coupon_id:id,member_coupon_id:claimed.get(id)}};
   claims.push({slot,coupon_id:id});claimed.set(id,++memberCoupon);return {code:1,data:{claim_status:'claimed',coupon_id:id,member_coupon_id:memberCoupon}};}
  if(url.pathname==='/Cart/clear'){cart.clears++;cart.adds.length=0;return {code:1};}
  if(url.pathname==='/Cart/add.html'){cart.adds.push(Object.fromEntries(new URLSearchParams(req.postData())));return {code:1,data:{cart:{add:{status:true,total:cart.adds.length}}}};}
  if(url.pathname==='/Cart.html')return '<!doctype html><title>Cart</title>';
  if(url.pathname==='/ajax/goods')return goods(new URLSearchParams(req.postData()));
  if(url.pathname==='/ajax/html')return '';
  return null;
 }};
 return site;
}

export async function open(t,{clock='2026-11-28T13:00:00-05:00',signedIn=true,internalTest=null,viewport={width:1280,height:900},failGoods=0}={}){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'carnival-page-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 if(internalTest)fs.writeFileSync(path.join(dir,'carnival-test.json'),JSON.stringify(internalTest));
 const tick={ms:Date.parse(clock)},paidUses=[];
 const carnival=createCarnival({dir,publishedDir:dir,now:()=>tick.ms}),site=mainSite({signedIn});
 // The dashboard side of "verify": answers queued requests from a simulated Admin coupon log.
 const verifier=createCarnivalVerifier({publicDir:dir,requestDir:path.join(dir,'carnival-verify'),now:()=>tick.ms,read:async()=>({status:'available',generated_at:'t',uses:paidUses})});
 const browser=await chromium.launch({headless:true});t.after(()=>browser.close());
 const page=await browser.newPage({viewport});page.setDefaultTimeout(8000);
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
  // failGoods: the first n catalog reads fail, as a busy CDN answers some of a page's burst.
  if(url.pathname==='/ajax/goods'&&failGoods>0){failGoods--;return route.fulfill({status:503,body:'busy'});}
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
export {app,types,chromium};
