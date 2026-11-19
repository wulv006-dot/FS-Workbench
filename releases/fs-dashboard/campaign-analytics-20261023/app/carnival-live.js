/* MMOEXP Carnival 2026: live wiring for the handoff prototype (carnival-proto.js).
 * The prototype keeps its layout and animations; this file replaces its simulated
 * parts with the real ones:
 *  - account: main-site session (same origin); sign-in through the main-site login
 *    endpoints (CampaignNativeCodeHandoff), never a copy of the password anywhere else;
 *  - coupons: main-site /ajax/carnival/coupon + /ajax/carnival/claim per slot; the
 *    granted member coupon is handed to the cart through pending_member_coupon_id;
 *  - prices: main-site public /ajax/goods (same request the store pages make);
 *  - Mystery Shop draws and Black Friday sessions: FS runtime (api/carnival/*).
 * Every write is a single request without retry; unknown outcomes stop with a message. */
(function(){
'use strict';
const H=window.CampaignNativeCodeHandoff;
const runtime=document.documentElement.dataset.campaignRuntime||'/events/';
const SITE='266',PLAT={ps:21587,xbox:21585,pc:21589};
const xhr={'X-Requested-With':'XMLHttpRequest'};
const zh=()=>LANG==='zh';
const say=(en,cn)=>zh()?cn:en;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const track=(name,detail)=>{try{document.getElementById('fc-activity')?.dispatchEvent(new CustomEvent(name,{detail}));}catch{}};

/* ---------------- account ---------------- */
let account={state:'unknown',uid:null,spend:null,tiers:null};
async function getJSON(url,init={}){
  const r=await fetch(url,{credentials:'same-origin',cache:'no-store',redirect:'error',...init,headers:{...xhr,...(init.headers||{})}});
  if(!r.ok)throw Error('HTTP_'+r.status);return r.json();
}
async function refreshAccount(){
  try{
    const j=await getJSON('/ajax/carnival/user');
    if(Number(j?.code)!==1||typeof j.data?.logged_in!=='boolean')throw Error('ACCOUNT');
    const d=j.data,uid=String(d.uid??'');
    account={state:d.logged_in&&/^[1-9]\d{0,19}$/.test(uid)?'signed_in':'guest',uid:d.logged_in?uid:null,
      spend:d.logged_in&&Number.isFinite(Number(d.spend_amount))?Number(d.spend_amount):null,
      tiers:Array.isArray(d.tier_thresholds)?d.tier_thresholds.map(Number):null};
  }catch{account={state:'unavailable',uid:null,spend:null,tiers:null};}
  return account;
}
// Header sign-in state, same component and data as the FC activity pages (activity.js).
async function refreshHeader(){
  const area=document.querySelector('.fca-demo-header .fca-account');if(!area)return;
  let a;try{a=await H.mainSiteAccount({origin:location.origin});}catch{return;}
  if(!a||a.state==='unavailable')return;
  const count=area.querySelector('.fca-account-count');count.hidden=!(a.cart>0);count.textContent=a.cart>99?'99+':String(a.cart||'');
  area.querySelector('[data-account-login]').hidden=a.state==='signed_in';
  const user=area.querySelector('.fca-account-user');user.hidden=a.state!=='signed_in';
  if(a.avatar)user.querySelector('.fca-account-face').src=a.avatar;
  const frame=user.querySelector('.fca-account-frame');frame.hidden=!a.frame;if(a.frame)frame.src=a.frame;
}
document.querySelector('.fca-demo-header [data-account-login]')?.addEventListener('click',()=>requireLogin(null));
let resume=null;
function requireLogin(then){resume=then;openLogin();}
function openLogin(message){
  const box=document.querySelector('#loginRequiredMask .login-required-modal');
  box.innerHTML=`<div class="login-required-icon" aria-hidden="true">👤</div><h3 id="loginRequiredTitle">${say('Sign in to continue','登录后继续')}</h3>
  <p>${say('Use your MMOEXP account. Your draws and coupons are saved to it.','使用 MMOEXP 账号登录，抽奖结果和优惠券都会记录在账号下。')}</p>
  <form class="carnival-login" novalidate><label>${say('Email','邮箱')}<input name="email" type="email" autocomplete="username" required></label>
  <label>${say('Password','密码')}<input name="password" type="password" autocomplete="current-password" required></label>
  <p class="carnival-login-error" role="alert"${message?'':' hidden'}>${esc(message||'')}</p>
  <button type="submit" class="login-required-go">${say('SIGN IN','登录')}</button></form>
  <div class="carnival-login-social"><button type="button" data-provider="google">Google</button><button type="button" data-provider="facebook">Facebook</button></div>
  <a class="carnival-login-register" href="/user/register.html">${say('Create an account','注册账号')}</a>
  <button type="button" class="btn-ghost coupon-close" data-close>${say('Not now','暂不登录')}</button>`;
  const form=box.querySelector('form'),err=box.querySelector('.carnival-login-error'),submit=form.querySelector('button');
  form.addEventListener('submit',async e=>{
    e.preventDefault();err.hidden=true;submit.disabled=true;submit.textContent=say('SIGNING IN…','登录中…');
    try{
      const result=await H.mainSiteLogin({email:form.email.value,password:form.password.value});
      if(result.state!=='signed_in'){err.textContent=result.message;err.hidden=false;return;}
      await afterLogin();
    }catch{err.textContent=say('Sign-in did not respond. Please try again.','登录没有响应，请稍后再试。');err.hidden=false;}
    finally{submit.disabled=false;submit.textContent=say('SIGN IN','登录');}
  });
  box.querySelectorAll('[data-provider]').forEach(b=>b.addEventListener('click',async()=>{
    b.disabled=true;
    try{saveResume();const r=await H.socialLoginUrl({provider:b.dataset.provider,returnUrl:location.href});
      if(r.state==='redirect'){location.assign(r.url);return;}err.textContent=r.message;err.hidden=false;}
    catch{err.textContent=say('Sign-in is unavailable right now.','暂时无法登录。');err.hidden=false;}
    finally{b.disabled=false;}
  }));
  box.querySelector('[data-close]').addEventListener('click',closeLogin);
  document.getElementById('loginRequiredMask').classList.add('show');
  form.email.focus();
}
function closeLogin(){document.getElementById('loginRequiredMask').classList.remove('show');resume=null;}
function saveResume(){try{if(resume)sessionStorage.setItem('carnival-login-resume',JSON.stringify({...resume,at:Date.now()}));}catch{}}
async function afterLogin(){
  await refreshAccount();if(account.state!=='signed_in')return;
  document.getElementById('loginRequiredMask').classList.remove('show');
  toast(say('Signed in.','已登录。'));
  await Promise.all([loadMystery(),refreshHomeCoupon(),refreshHeader(),loadCapsule()]);refreshDrawState();
  const next=resume;resume=null;if(next)runResume(next);
}
function runResume(r){
  if(r.kind==='home')claimCoupon();
  else if(r.kind==='draw'&&r.game===curGame){picked=r.picked;drawDeal();}
}

/* ---------------- internal test ---------------- */
// Before the event the server may publish a time-limited internal test (carnival-test.json on
// 187). While it is valid every act shows as live and every claim uses the one test coupon,
// so only the coupon delivery chain is exercised. It ends by itself at open_until.
let TEST=null;const TEST_START='2026-11-01T00:00:00Z',REAL_EVENTS=JSON.parse(JSON.stringify(CONFIG.events));
function applyTest(test){
  TEST=test&&Number.isInteger(test.coupon_id)&&typeof test.slot==='string'&&Date.parse(test.open_until)>Date.now()?test:null;
  for(const k of Object.keys(REAL_EVENTS))CONFIG.events[k]=TEST?{start:TEST_START,end:TEST.open_until}:{...REAL_EVENTS[k]};
  document.documentElement.toggleAttribute('data-carnival-test',!!TEST);
}
// With every act open the prototype would jump to the last one; during a test the visitor
// stays on the act they chose.
const realFeaturedEvent=currentFeaturedEvent;
currentFeaturedEvent=function(){return TEST?featuredEvent:realFeaturedEvent();};

/* ---------------- coupons ---------------- */
// One claim POST, never retried. Returns {state:'claimed'|'login_required'|'unavailable', memberCouponId}.
async function claimSlot(slot,couponId){
  if(TEST){slot=TEST.slot;couponId=TEST.coupon_id;}
  let info;
  try{info=await getJSON('/ajax/carnival/coupon?slot='+encodeURIComponent(slot));}catch{return {state:'unavailable'};}
  const d=info?.data;
  if(Number(info?.code)!==1||d?.enabled!==true||d.slot!==slot)return {state:'unavailable'};
  if(d.logged_in!==true)return {state:'login_required'};
  const row=(d.list||[]).find(c=>Number(c.coupon_id)===couponId);
  if(!row)return {state:'unavailable'};
  if(row.claim_status==='claimed'&&Number(row.member_coupon_id)>0)return {state:'claimed',memberCouponId:Number(row.member_coupon_id),reused:true};
  if(row.can_claim!==true)return {state:'unavailable',status:row.claim_status};
  let res;
  try{res=await getJSON('/ajax/carnival/claim',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},body:new URLSearchParams({slot,coupon_id:String(couponId)}).toString()});}
  catch{return {state:'unknown'};}
  const c=res?.data;
  if(Number(res?.code)===1&&c?.claim_status==='claimed'&&Number(c.member_coupon_id)>0)return {state:'claimed',memberCouponId:Number(c.member_coupon_id),reused:false};
  return {state:Number(res?.code)===1?'unknown':'rejected',message:typeof res?.msg==='string'?res.msg.slice(0,200):''};
}
/* Buy now: the member asked for the claimed item to go straight to checkout. The cart is
 * emptied (a member coupon applies to the whole order, so other lines would block or dilute
 * it), the exact goods row is added once, and the cart page opens with the coupon selected.
 * Each request is sent once; any failure stops with a "try again" message. */
const postForm=(url,form)=>fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8',...xhr},body:new URLSearchParams(form)}).then(r=>{if(!r.ok)throw Error('HTTP_'+r.status);return r.json().catch(()=>({}));});
function cartLine(spec,row){
  if(spec.top===1)return {category:'new_gold',id:String(row.id),group:String(spec.qty),num:'1',attr:'',aid:''};
  return {category:'new_items',id:String(row.id),group:'1',num:String(Math.max(1,Number(row.min_qty)||1)),attr:'',aid:String(row.aid??spec.aid??'')};
}
async function buyNow(spec,memberCouponId){
  let row;try{row=spec&&await specRow(spec);}catch{}
  if(!row||rowPrice(row,spec.top,spec.qty)===null)return {state:'unavailable'};
  const line=cartLine(spec,row);
  try{const c=await postForm('/Cart/clear',{});if(Number(c?.code)===0||c?.status===false)return {state:'clear_failed'};}catch{return {state:'clear_failed'};}
  let res;try{res=await postForm('/Cart/add.html',line);}catch{return {state:'unknown'};}
  const value=res?.data?.cart?.add||res?.cart?.add;
  if(res?.code===0||res?.status===false||value?.status===false)return {state:'rejected',message:String(value?.msg||res?.msg||'').slice(0,200)};
  if(!(Number(res?.code)===1||value&&(value.details||value.cart||value.total!=null)))return {state:'unknown'};
  handToCart(memberCouponId);track('fcactivity:selection',{action:'buy_now',ids:[String(row.id)]});
  location.assign('/Cart.html');return {state:'navigating'};
}
function buyNowBlock(){
  return `<button type="button" class="buybtn" data-carnival-buy>${say('CHECKOUT NOW','立即结算')}</button>`;
}
function wireBuyNow(spec,memberCouponId){
  const b=document.querySelector('#mysteryFlowMask [data-carnival-buy]');if(!b)return;
  b.addEventListener('click',async()=>{
    b.disabled=true;b.textContent=say('ADDING TO CART…','正在加入购物车…');
    const r=await buyNow(spec,memberCouponId);
    if(r.state==='navigating')return;
    b.disabled=false;b.textContent=say('CHECKOUT NOW','立即结算');
    toast(r.state==='unknown'?say('We could not confirm the cart. Open your cart before trying again.','无法确认是否已加入购物车，请先打开购物车查看再重试。')
      :r.state==='rejected'&&r.message?r.message
      :say('This item cannot be added right now. Please try again in a moment.','暂时无法加入购物车，请稍后再试。'));
  });
}
function handToCart(memberCouponId){try{sessionStorage.setItem('pending_member_coupon_id',String(memberCouponId));sessionStorage.removeItem('pending_discount_code');}catch{}}
function couponOutcome(result,couponId,slot){
  track('fcactivity:coupon-claim',{state:result.state,reused:!!result.reused,couponId});
  if(result.state==='claimed')return true;
  if(result.state==='unknown')toast(say('We could not confirm the coupon. Check My Coupons before trying again.','无法确认是否领到券，请先到「我的优惠券」查看再重试。'));
  else if(result.state==='rejected')toast(result.message||say('This coupon cannot be claimed right now.','暂时无法领取这张券。'));
  else toast(say('This coupon is not available right now.','这张券暂时不可领取。'));
  return false;
}

/* Home 10% coupon */
const HOME={slot:'carnival_home',coupon:1399};
// One per member: once the account holds the coupon the button stays grey and says so.
// During an internal test the claim goes to the test coupon, so that is what is checked.
async function refreshHomeCoupon(){
  const slot=TEST?TEST.slot:HOME.slot,coupon=TEST?TEST.coupon_id:HOME.coupon;
  try{const d=(await getJSON('/ajax/carnival/coupon?slot='+encodeURIComponent(slot))).data,row=(d?.list||[]).find(c=>Number(c.coupon_id)===coupon);
    earlyAccess=d?.logged_in===true&&row?.can_claim!==true&&/^(claimed|used|received|limit)/.test(String(row?.claim_status||''));}catch{}
  renderEarlyBtn();
}
claimCoupon=async function(){
  if(phaseStatus(CONFIG.events.tg).k!=='live'){closeCoupon();toast(say('The event is not active.','活动未开始或已结束'));return;}
  if(account.state!=='signed_in'){closeCoupon();requireLogin({kind:'home'});return;}
  const btn=document.getElementById('couponClaimBtn');btn.disabled=true;
  try{
    const r=await claimSlot(HOME.slot,HOME.coupon);
    if(r.state==='login_required'){closeCoupon();requireLogin({kind:'home'});return;}
    if(couponOutcome(r,HOME.coupon,HOME.slot)){earlyAccess=true;renderEarlyBtn();closeCoupon();toast(say('10% OFF coupon added to your account.','10% OFF 优惠券已发到你的账户。'));}
  }finally{btn.disabled=false;}
};
document.getElementById('couponClaimBtn').replaceWith(document.getElementById('couponClaimBtn').cloneNode(true));
document.getElementById('couponClaimBtn').addEventListener('click',()=>claimCoupon());

/* ---------------- live prices (/ajax/goods) ---------------- */
// Goods scope observed in Admin 2026-11-17: id → [game_id, top_cid, category_id, aid, keyword?].
// Large categories exceed the 10-page list cap, so those rows are found by title keyword.
const GOODS={
 170070065:[456,2,3955,15943,'Resplendent Spark x100'],186050303:[456,5,9975,15943,'Cuddly Conduit'],187495953:[456,2,3675,15943,'Crux of the False Prophet'],187496117:[456,2,3675,15943,'Flawless Horadric Skull'],187496035:[456,2,3675,15943,'Common Base Gear x15'],187495871:[456,2,3675,15943,'Flawless Horadric Emerald'],187495789:[456,2,3675,15943,'Flawless Horadric Sapphire'],187495707:[456,2,3675,15943,'Flawless Horadric Ruby'],187495379:[456,2,3675,15943,'Runeword Set'],
 71488531:[157,2,2473,17725,'Divine Orb'],38588459:[157,2,2473,17725,'Divine Orb'],71488587:[157,2,2473,17725,'Chaos Orb'],38588315:[157,2,2473,17725,'Chaos Orb'],38588383:[157,2,2473,17725,'Mirror of Kalandra'],40602987:[157,2,2473,17725,'Exalted Orb'],187535323:[157,2,2473,17725,'Divine Orb'],45283535:[157,2,3349,17725,'Bow Starter Pack'],45283527:[157,2,3349,17725,'Melee Phys Starter Pack'],
 117074411:[552,2,1338,20137],186208657:[552,2,1338,20137],186208735:[552,2,1338,20137],169682813:[552,2,1338,20137],169644111:[552,2,1338,20137],187497011:[552,2,1338,20137],169547725:[552,2,1338,20137],169547649:[552,2,1338,20137],169547573:[552,2,1338,20137],
 165167189:[1333,1,9661,21627],186209371:[1333,2,10079,21627],186282265:[1333,2,10403,21627],186282115:[1333,2,10403,21627],186282205:[1333,2,10403,21627],186209281:[1333,2,10079,21627],186282235:[1333,2,10403,21627],186282175:[1333,2,10403,21627],
 185981107:[925,2,7111,19835,'Stencil Parts'],185382277:[925,2,7115,19835,'Fossilized Lightning'],112802085:[925,2,7013,19835,'Looting Mk.3'],112802373:[925,2,7013,19835,'Medium Shield'],185383333:[925,2,7113,19835,'ARC Data Module'],112807773:[925,2,7117,19835,'Advanced Mechanical'],112811421:[925,2,7113,19835,'Queen Reactor'],105267633:[925,1,6955,19835],
 165175543:[1335,2,9665,21629],186374427:[1335,2,10431,21629,'Binding Catalyst'],186374619:[1335,2,10431,21629,'High-Tenacity Fibers'],165175575:[1335,2,9665,21631],186372891:[1335,2,10431,21629,'Comms Module'],186372603:[1335,2,10431,21629,'Alloyed Plating'],186372507:[1335,2,10431,21629,'Stock Rod'],186372699:[1335,2,10431,21629,'Structural Alloy'],186373083:[1335,2,10431,21629,'Power Regulator'],
};
const lists=new Map(),quotes=new Map(),LIST_TTL=120000;
// A page asks for many catalogs at once; a few at a time keeps phones and the CDN from failing some.
let goodsActive=0;const goodsQueue=[];
async function goodsPage(form){
  if(goodsActive>=4)await new Promise(r=>goodsQueue.push(r));
  goodsActive++;
  try{
    const r=await fetch('/ajax/goods',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8',...xhr},body:new URLSearchParams(form)});
    if(!r.ok)throw Error('HTTP_'+r.status);return await r.json();
  }finally{goodsActive--;goodsQueue.shift()?.();}
}
async function listRows(scope){
  const key=JSON.stringify(scope),hit=lists.get(key);
  if(hit&&(hit.promise||Date.now()-hit.at<LIST_TTL))return hit.promise||hit.rows;
  const promise=(async()=>{
    const rows=[];let pages=1;
    for(let page=1;page<=pages&&page<=10;page++){
      const form={site_id:SITE,Game_id:String(scope.game),page:String(page),top_cid:String(scope.top),category_id:String(scope.cid),level:'1',get_about_multi_by_cid:'1',perpage:'28',...(scope.aid?{aid:String(scope.aid)}:{}),...(scope.keyword?{keyword:scope.keyword}:{})};
      const index=(await goodsPage(form))?.goods?.index;if(!index||!Array.isArray(index.list))throw Error('CATALOG');
      rows.push(...index.list);pages=Math.ceil(Number(index.total)/Number(index.perpage||28))||1;
    }
    return rows;
  })();
  lists.set(key,{promise});
  try{const rows=await promise;lists.set(key,{rows,at:Date.now()});return rows;}catch(e){lists.delete(key);throw e;}
}
// Public price of an exact goods row and quantity; null when that tier is not sold.
function rowPrice(row,top,qty){
  if(!row||Number(row.status)!==1||Number(row.auto_off)!==0)return null;
  // price_discount is the USD list price; the _format field is converted to the visitor's
  // currency and, for guests, already takes the main site's new-user coupon off.
  if(top===1){const tier=row.goods_list?.[String(qty)];const v=Number(tier?.price_discount??tier?.price_discount_format);return Number.isFinite(v)&&v>0?Math.round(v*100)/100:null;}
  // The formatted price is rounded to cents, which zeroes tiny unit prices (POE orbs); use the raw one.
  const unit=Number(row.price_discount??row.price_discount_format),v=unit*Math.max(1,Number(row.min_qty)||1);return Number.isFinite(v)&&v>0?Math.round(v*100)/100:null;
}
// spec: {game,top,cid,aid?,keyword?,goods?,area?,sid?,qty}
function quoteKey(spec){return JSON.stringify(spec);}
// The one goods row a spec names, or null when it is missing or ambiguous.
async function specRow(spec){
  const find=rows=>{const m=spec.goods?rows.filter(r=>Number(r.id)===spec.goods)
    :rows.filter(r=>String(r.game_area_format||'').trim()===spec.area&&(!spec.sid||Number(r.sid)===spec.sid));return m.length===1?m[0]:null;};
  const row=find(await listRows({game:spec.game,top:spec.top,cid:spec.cid,aid:spec.aid,keyword:spec.keyword}));
  // FC 27 players: the category is longer than the page cap, so a missing row is looked up by name.
  return row||(spec.search?find(await listRows({game:spec.game,top:spec.top,cid:spec.cid,aid:spec.aid,keyword:spec.search})):null);
}
// ?price_debug=1 lists every price lookup on the page, to diagnose a device that shows none.
const PRICE_DEBUG=new URLSearchParams(location.search).has('price_debug'),diag=new Map();
function priceDiag(key,spec,state){
  if(!PRICE_DEBUG)return;diag.set(key,(spec.goods||spec.area||'')+' q'+spec.qty+' a'+(spec.aid||'')+': '+state);
  let box=document.getElementById('priceDebug');
  if(!box){box=document.createElement('pre');box.id='priceDebug';box.style.cssText='position:fixed;left:0;right:0;bottom:0;max-height:45vh;overflow:auto;margin:0;padding:8px;z-index:99999;background:#000e;color:#7f7;font:11px/1.35 monospace;white-space:pre-wrap';document.body.append(box);}
  box.textContent=[navigator.userAgent,...diag.values()].join(String.fromCharCode(10));
}
function cachedQuote(spec,rerender){
  if(!spec)return null;const key=quoteKey(spec),hit=quotes.get(key);
  if(hit&&Date.now()-hit.at<LIST_TTL)return hit.price;
  if(!hit?.pending){
    quotes.set(key,{...(hit||{price:null,at:0}),pending:true});
    priceDiag(key,spec,'loading');
    specRow(spec).then(row=>{
      const price=rowPrice(row,spec.top,spec.qty);
      priceDiag(key,spec,price!==null?'ok '+price:!row?'no row':'no price (status '+row.status+', off '+row.auto_off+', tiers '+Object.keys(row.goods_list||{}).join('/')+')');
      quotes.set(key,{price,at:Date.now()});rerender();
    }).catch(e=>{
      priceDiag(key,spec,'error '+String(e?.message||e).slice(0,80));
      // A failed read retries on its own (2s, 4s, 6s); waiting for an unrelated re-render left
      // a price pending for good when nothing else on the page changed.
      const fails=(hit?.fails||0)+1;
      quotes.set(key,{price:hit?.price??null,at:fails<4?0:Date.now(),fails});
      if(fails<4)setTimeout(rerender,2000*fails);else rerender();
    });
  }
  return hit?.price??null;
}
const amountOf=name=>{const m=/(\d+(?:\.\d+)?)\s*K\b/i.exec(name||'');return m?Number(m[1]):null;};
function mysterySpec(it){
  if(it.modelId==='41217957'){const p=document.getElementById('fc27Platform').value;return {game:1327,top:1,cid:9623,aid:PLAT[p],goods:Number(it.productIds?.[p]),qty:amountOf(it.name)};}
  if(it.productIds&&typeof it.productIds==='object'){const p=document.getElementById('fc27Platform').value;return {game:1327,top:2,cid:9627,aid:PLAT[p],goods:Number(it.productIds[p]),search:String(it.name||'').trim().split(/\s+/).pop(),qty:1};}
  // The same server name exists in several regions; the region is the goods row's sid.
  if(it.aionAmount){const region=document.getElementById('aionRegion').value,server=document.getElementById('aionServer').value,faction=document.getElementById('aionFaction').value;return server&&AION_SID[region]?{game:891,top:1,cid:6527,area:server+' - '+faction,sid:AION_SID[region],qty:it.aionAmount}:null;}
  if(it.wowAmount){const c=it.wowChoice||wowChoice(),entry=WOW_PRICE_SNAPSHOT?.[c.region]?.[c.faction]?.[c.realm];return entry?{game:1367,top:1,cid:9991,goods:Number(entry[0]),qty:it.wowAmount}:null;}
  const id=Number(it.goodsId||it.productId||it.poeGoodsId),g=GOODS[id];
  if(!g)return null;
  // Market games: only the configured listing (PC / Windia) has a verified goods id.
  if(it.marketGame&&(it.marketChoice||marketSelections[it.marketGame])!==(it.marketGame==='maple'?'Windia':'PC'))return null;
  return {game:g[0],top:g[1],cid:g[2],aid:g[3],...(g[4]?{keyword:g[4]}:{}),goods:id,qty:g[1]===1?amountOf(it.name):1};
}
const AION_SID={EU:7741,'NA West':7743,'NA East':7745,'South America':7747,Asia:7749};
let msRender=0;const rerenderMs=()=>{cancelAnimationFrame(msRender);msRender=requestAnimationFrame(()=>{if(!msBusy)renderMsZone();});};
fc27Price=function(it){
  const price=cachedQuote(mysterySpec(it),rerenderMs);
  if(it.aionAmount)it.price=price;
  it.fromPrice=false;return price;
};
// Market games: only PC (ARC, COD) and Windia (MapleStory) listings are configured.
marketOptions.arc=['PC'];marketOptions.codmw4=['PC'];
aionSelectionChanged=function(resetServer){
  if(curGame!=='aion2')return;const r=document.getElementById('aionRegion').value,f=document.getElementById('aionFaction').value,select=document.getElementById('aionServer');
  const choices=AION_SERVERS[r]?.[f]||[],old=select.value;select.innerHTML=choices.map(x=>'<option value="'+esc(x)+'">'+esc(x)+'</option>').join('');select.value=(!resetServer&&choices.includes(old))?old:choices[0];
  if(!revealed){picked=[];renderMsZone();}
};
function livePriceNotes(){
  // Only the note; the platform dropdown is also built from spans (.game-select-wrap).
  document.querySelectorAll('.wow-note,#fc27PlatformBar>span:not(.game-select-wrap)').forEach(n=>{n.textContent=say('Live MMOEXP prices. The final price is confirmed at checkout.','价格实时取自 MMOEXP，最终以结算页为准。');});
}

/* ---------------- Mystery Shop ---------------- */
let mystery={};
async function loadMystery(){
  if(account.state!=='signed_in'){mystery={};restoreMysteryResult();renderMsZone();tickMs();return;}
  try{const j=await getJSON(runtime+'api/carnival/mystery?uid='+encodeURIComponent(account.uid));mystery=j.games||{};}catch{mystery={};}
  if(!msBusy){restoreMysteryResult();renderMsZone();tickMs();}
}
const choiceKey=(game,round)=>'carnival-mystery-choice:'+account.uid+':'+game+':'+round;
function currentChoice(){
  return {platform:document.getElementById('fc27Platform').value,wow:wowChoice(),market:marketSelections[curGame],aion:{region:document.getElementById('aionRegion').value,faction:document.getElementById('aionFaction').value,server:document.getElementById('aionServer').value}};
}
function applyChoice(c){
  if(!c)return;
  if(curGame==='fc27'&&PLAT[c.platform])document.getElementById('fc27Platform').value=c.platform;
  if(curGame==='wow'&&c.wow)for(const [k,id] of [['region','wowRegion'],['faction','wowFaction'],['realm','wowRealm']])document.getElementById(id).value=c.wow[k];
  if(curGame==='aion2'&&c.aion){document.getElementById('aionRegion').value=c.aion.region;document.getElementById('aionFaction').value=c.aion.faction;aionSelectionChanged(true);document.getElementById('aionServer').value=c.aion.server;}
}
function itemWithChoice(i,c){
  const it=gameItems().items[i];if(!it)return null;
  if(marketGames.includes(curGame))return {...it,marketChoice:c?.market||marketSelections[curGame]};
  if(curGame==='wow')return {...it,wowChoice:c?.wow||wowChoice()};
  return it;
}
mysteryGameState=function(){return {rounds:mystery[curGame]?.rounds_drawn||0,pending:mystery[curGame]?.current||null};};
syncMysteryCooldown=function(){msDrawsLeft=mystery[curGame]?.current?0:1;};
restoreMysteryResult=function(){
  picked=[];revealed=null;const cur=mystery[curGame]?.current;
  if(cur){let c=null;try{c=JSON.parse(localStorage.getItem(choiceKey(curGame,cur.round))||'null');}catch{}
    applyChoice(c);revealed=cur.picks.map(p=>({it:itemWithChoice(p.item,c),off:p.off,couponId:p.coupon_id})).filter(r=>r.it);picked=cur.picks.map(p=>p.item);}
  syncMysteryCooldown();
};
persistMysteryProgress=function(){};
resetMysteryDemo=function(){};
drawDeal=async function(){
  if(msBusy||revealed)return;
  if(picked.length<CONFIG.mystery.pickCount){toast(t('pickFirst'));return;}
  if(account.state!=='signed_in'){requireLogin({kind:'draw',game:curGame,picked:[...picked]});return;}
  syncMysteryCooldown();if(msDrawsLeft<=0){toast(t('noDraws'));return;}
  msBusy=true;const choice=currentChoice(),game=curGame;
  let j;
  try{j=await getJSON(runtime+'api/carnival/mystery/draw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:account.uid,game,items:[...picked]})});}
  catch{msBusy=false;toast(say('The draw did not respond. Refresh to see if it was saved.','抽奖没有响应，请刷新页面查看是否已保存。'));return;}
  msBusy=false;
  if(!j?.current){toast(say('The draw is not available right now.','暂时无法抽奖。'));return;}
  mystery[game]=j;if(curGame!==game)return;
  try{localStorage.setItem(choiceKey(game,j.current.round),JSON.stringify(choice));}catch{}
  track('fcactivity:selection',{action:'mystery_draw',ids:j.current.picks.map(p=>String(p.item))});
  revealed=j.current.picks.map(p=>({it:itemWithChoice(p.item,choice),off:p.off,couponId:p.coupon_id}));picked=j.current.picks.map(p=>p.item);
  syncMysteryCooldown();
  ['marketChoiceSelect','fc27Platform','wowRegion','wowFaction','wowRealm','aionRegion','aionFaction','aionServer'].forEach(id=>{const el=document.getElementById(id);if(el)el.disabled=true;});
  document.getElementById('msPool').style.display='none';
  const res=document.getElementById('msResult');res.style.display='grid';res.innerHTML=revealed.map(r=>revealCardHTML(r,false)).join('');renderMsMeta();
  msBusy=true;const cards=res.querySelectorAll('.fcard');
  [300,1000,1700].forEach((ms,i)=>setTimeout(()=>cards[i]?.classList.add('open'),ms));
  setTimeout(()=>{msBusy=false;renderMsActions();toast(j.repeated?say('This round was already drawn.','本轮已经抽过了。'):t('revealDone'));},2400);
};
startMysteryPurchase=async function(index){
  const r=revealed?.[index];if(!r)return;
  if(account.state!=='signed_in'){requireLogin(null);return;}
  const slot=mystery[curGame]?.coupon_slot;if(!slot||!r.couponId){toast(say('This discount is not available right now.','这个折扣暂时不可用。'));return;}
  mysteryBox(`<div class="mystery-flow-label">${say('ITEM COUPON','商品专属优惠券')}</div><h3 id="mysteryFlowTitle">${say('Getting your coupon…','正在领取优惠券…')}</h3>`);
  const result=await claimSlot(slot,r.couponId);
  if(result.state==='login_required'){closeMysteryFlow();requireLogin(null);return;}
  if(!couponOutcome(result,r.couponId,slot)){closeMysteryFlow();return;}
  handToCart(result.memberCouponId);
  const price=fc27Price(r.it),spec=mysterySpec(r.it);
  mysteryBox(`<div class="mystery-flow-label">${say('ITEM COUPON','商品专属优惠券')}</div><h3 id="mysteryFlowTitle">${say('Your '+r.off+'% OFF coupon is in your account','你的 '+r.off+'% OFF 优惠券已到账')}</h3>
  ${couponCard({amount:r.off+'% OFF',description:esc(nm(r.it))})}
  <div class="mystery-flow-box"><p>${esc(nm(gameItems()))} · ${esc(nm(r.it))}</p>${price!==null?`<p>${say('Current price','当前价格')}: $${price.toFixed(2)} → <b>$${(price*(1-r.off/100)).toFixed(2)}</b></p>`:''}
  <p class="mystery-flow-disclaimer">${say('The final price is confirmed at checkout. Coupons cannot be combined with other coupons or codes.','最终价格以结算页为准；不能与其他优惠券或折扣码叠加。')}</p></div>
  ${buyNowBlock()}
  <button type="button" class="btn-ghost coupon-close" onclick="closeMysteryFlow()">${say('Later','稍后')}</button>`);
  wireBuyNow(spec,result.memberCouponId);
};
tickMs=function(){syncMysteryCooldown();document.getElementById('msTimer').textContent=msDrawsLeft?say('READY','可以翻牌'):say('VERIFY AFTER PAYMENT TO UNLOCK','付款后点下方按钮校验解锁');};
// A drawn round unlocks only when the member presses "verify" after paying: the order is
// checked against Admin once per press (no background polling of Admin).
let verifying=false;
const originalRenderMsActions=renderMsActions;
renderMsActions=function(){
  originalRenderMsActions();
  if(!revealed||!mystery[curGame]?.current)return;
  document.getElementById('msActions').innerHTML=`<button type="button" class="drawdeal-btn" id="msVerifyBtn" ${verifying?'disabled':''} onclick="carnivalVerifyPurchase()">${verifying?say('CHECKING YOUR ORDER…','正在校验订单…'):say('I\'VE PAID · VERIFY & RESET','已完成购买 · 校验并重置')}</button>`;
};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
window.carnivalVerifyPurchase=async function(){
  if(verifying)return;
  if(account.state!=='signed_in'){requireLogin(null);return;}
  const game=curGame,label=`<div class="mystery-flow-label">${say('PURCHASE CHECK','购买校验')}</div>`;
  verifying=true;renderMsActions();
  mysteryBox(`${label}<h3 id="mysteryFlowTitle">${say('Checking your order…','正在校验订单…')}</h3><p>${say('This usually takes a few seconds.','通常需要几秒钟。')}</p>`);
  let outcome='error';
  try{
    let g=await getJSON(runtime+'api/carnival/mystery/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:account.uid,game})});
    for(let attempt=0;attempt<16;attempt++){
      if(g?.can_draw){outcome='unlocked';break;}
      const s=g?.verify?.status;if(s==='not_found'||s==='error'){outcome=s;break;}
      await pause(2500);
      const all=await getJSON(runtime+'api/carnival/mystery?uid='+encodeURIComponent(account.uid));mystery=all.games||mystery;g=mystery[game];
    }
  }catch{}
  verifying=false;
  track('fcactivity:selection',{action:'mystery_verify_'+outcome,ids:[]});
  const close=`<button type="button" class="buybtn" onclick="closeMysteryFlow()">${say('OK','知道了')}</button>`;
  if(outcome==='unlocked'){
    try{const all=await getJSON(runtime+'api/carnival/mystery?uid='+encodeURIComponent(account.uid));mystery=all.games||mystery;}catch{}
    if(curGame===game){restoreMysteryResult();renderMsZone();tickMs();}
    mysteryBox(`${label}<h3 id="mysteryFlowTitle">${say('Purchase verified!','校验成功！')}</h3><p>${say('Your next round is ready. Pick 3 new cards and draw again.','新一轮机会已重置，重新选 3 张牌再翻吧。')}</p>${close}`);
    return;
  }
  renderMsActions();
  mysteryBox(outcome==='not_found'
    ?`${label}<h3 id="mysteryFlowTitle">${say('Purchase not completed yet','还未完成购买')}</h3><p>${say('We couldn\'t find a paid order using this round\'s coupon. Please complete your order first, then verify again to reset.','没有找到使用本轮优惠券的已付款订单。请先完成下单付款，再回来校验重置。')}</p>${close}`
    :`${label}<h3 id="mysteryFlowTitle">${say('We couldn\'t check right now','暂时无法校验')}</h3><p>${say('Please try again in a minute.','请稍后再试。')}</p>${close}`);
};
const originalSelGame=selGame;selGame=function(id){originalSelGame(id);};

/* ---------------- Black Friday ---------------- */
let schedule=null;
async function loadSchedule(){
  try{schedule=await getJSON(runtime+'api/carnival/schedule');
    applyTest(schedule.test);
    schedule.sessions.forEach((s,i)=>{if(CONFIG.flash.sessions[i]){CONFIG.flash.sessions[i].start=TEST?TEST_START:s.starts_at;CONFIG.flash.sessions[i].end=TEST?TEST.open_until:s.ends_at;}});
    try{updateEventGates();}catch{}
    window.dispatchEvent(new CustomEvent('carnival:schedule',{detail:schedule}));
  }catch{schedule=null;}
  renderSessTabs();renderFlash();
}
const flashPick={fc27:'ps'};
function flashSpec(p){
  const q=p.quote;
  if(q.server_choice==='wow'){const c=flashSelections.wow,entry=WOW_PRICE_SNAPSHOT?.[c.region]?.[c.faction]?.[c.realm];return entry?{game:q.game_id,top:q.top_cid,cid:q.category_id,goods:Number(entry[0]),qty:q.quantity}:null;}
  const keys=Object.keys(q.options),k=keys.includes(flashPick[p.key])?flashPick[p.key]:keys[0],o=q.options[k];
  return {game:q.game_id,top:q.top_cid,cid:q.category_id,aid:o.aid,goods:o.goods_id,qty:q.quantity};
}
let flashFrame=0;const rerenderFlash=()=>{cancelAnimationFrame(flashFrame);flashFrame=requestAnimationFrame(()=>renderFlash());};
window.carnivalFlashOption=(key,value)=>{flashPick[key]=value;renderFlash();};
renderFlash=function(){
  const grid=document.getElementById('flashGrid'),saved=grid.scrollLeft;
  const s=schedule?.sessions?.[curSess],st=phaseStatus(CONFIG.flash.sessions[curSess]),live=st.k==='live';
  document.querySelectorAll('.store-categories [data-category]').forEach(b=>b.classList.toggle('on',b.dataset.category===flashCategory));
  const demo=document.querySelector('.store-demo');if(demo)demo.textContent=say('Live MMOEXP prices · final price at checkout','价格实时取自 MMOEXP · 以结算为准');
  if(!s||!s.products.length&&!s.vouchers.length){
    grid.innerHTML=Array.from({length:4},()=>`<div class="fitem flash-mystery"><div class="ficon">?</div><h4>${st.k==='soon'?say('Revealed when the session starts','开场后揭晓'):say('Not available','暂不可用')}</h4></div>`).join('');
    requestAnimationFrame(syncFlashScroll);return;
  }
  const label=live?null:st.k==='soon'?t('notStarted'):t('sessOver');
  // An ended session keeps its line-up visible, greyed and stamped, so members see what was on sale.
  const over=st.k==='over',endedCls=over?' flash-ended':'',stamp=over?`<div class="flash-ended-stamp">${say('ENDED','已结束')}</div>`:'';
  const cards=flashCategory==='voucher'?s.vouchers.map(v=>`<div class="fitem flash-coupon${endedCls}">${stamp}<div class="fgame">${t('couponGame')}</div><div class="flash-ticket"><span class="flash-ticket-tag">${say('COUPON','优惠券')}</span><span class="flash-ticket-amount"><b>$${esc(v.reduce)}</b><i>OFF</i></span></div><p class="flash-ticket-min">${say('Min. spend','满')} $${esc(v.attain)}</p><p class="flash-note">${say('Use by 23:59:59 ET on the day you claim it.','领取当天 23:59:59（美东）前使用。')}</p><button class="buybtn" ${label?'disabled':''} data-carnival-voucher="${v.coupon_id}" data-slot="${esc(v.slot)}">${label||t('free')}</button></div>`)
   :s.products.filter(p=>p.category===flashCategory).map(p=>{
    const price=cachedQuote(flashSpec(p),rerenderFlash),now=price!==null?Math.round(price*(100-p.off))/100:null;
    const opts=p.quote.server_choice==='wow'?['region','faction','realm'].map(k=>flashSelect('wow',k,{region:[['US','US'],['EU','EU'],['Asia','Asia'],['KR','KR']],faction:[['Alliance','Alliance'],['Horde','Horde']],realm:[['Normal','Normal'],['PVP','PVP'],['Roleplay','Roleplay'],['Roleplay-PVP','Roleplay-PVP']]}[k],flashSelections.wow[k])).join('')
      :Object.keys(p.quote.options).length>1?`<select aria-label="${say('Platform','平台')}" onchange="carnivalFlashOption('${esc(p.key)}',this.value)">${Object.entries(p.quote.options).map(([k,o])=>`<option value="${esc(k)}"${(flashPick[p.key]||Object.keys(p.quote.options)[0])===k?' selected':''}>${esc(o.label)}</option>`).join('')}</select>`
      :`<span class="flash-fixed">${esc(Object.values(p.quote.options)[0].label)}</span>`;
    return `<div class="fitem flash-real${endedCls}" data-product="${esc(p.key)}">${stamp}<div class="off-badge">-${p.off}%</div><div class="fgame">${esc(p.game)}</div><div class="ficon flash-coin-art"><img src="${esc(p.image)}" alt="" loading="lazy"></div><h4>${esc(p.name)}</h4><div class="flash-options">${opts}</div><div class="fprice">${price!==null?`<span class="now">$${now.toFixed(2)}</span><span class="old">$${price.toFixed(2)}</span>`:`<span class="now">${say('PRICE PENDING','价格加载中')}</span>`}</div><button class="buybtn" ${label||price===null?'disabled':''} data-carnival-product="${esc(p.key)}">${label||t('grab')}</button></div>`;
   });
  grid.innerHTML=cards.join('')||`<div class="flash-empty">${say('Products for this category are to be announced.','本场该分类商品待公布')}</div>`;
  if(over)grid.querySelectorAll('select').forEach(x=>{x.disabled=true;});
  grid.scrollLeft=saved;requestAnimationFrame(syncFlashScroll);
};
document.getElementById('flashGrid').addEventListener('click',async e=>{
  const pb=e.target.closest('[data-carnival-product]'),vb=e.target.closest('[data-carnival-voucher]');if(!pb&&!vb)return;
  e.preventDefault();e.stopPropagation();
  const s=schedule?.sessions?.[curSess];if(!s||phaseStatus(CONFIG.flash.sessions[curSess]).k!=='live')return;
  if(account.state!=='signed_in'){requireLogin(null);return;}
  const btn=pb||vb;btn.disabled=true;
  try{
    if(vb){const id=Number(vb.dataset.carnivalVoucher),r=await claimSlot(vb.dataset.slot,id);
      if(r.state==='login_required'){requireLogin(null);return;}
      if(couponOutcome(r,id,vb.dataset.slot))toast(say('Coupon added to your account.','优惠券已发到你的账户。'));return;}
    const p=s.products.find(x=>x.key===pb.dataset.carnivalProduct);if(!p)return;
    const r=await claimSlot('bf_items',p.coupon_id);
    if(r.state==='login_required'){requireLogin(null);return;}
    if(!couponOutcome(r,p.coupon_id,'bf_items'))return;
    // Stay on the page after claiming (main-site API guide, point 2); buying is the member's next click.
    handToCart(r.memberCouponId);
    mysteryBox(`<div class="mystery-flow-label">${say('BLACK FRIDAY COUPON','黑五商品优惠券')}</div><h3 id="mysteryFlowTitle">${say('Your '+p.off+'% OFF coupon is in your account','你的 '+p.off+'% OFF 优惠券已到账')}</h3>
    ${couponCard({amount:p.off+'% OFF',description:esc(p.name)})}
    <div class="mystery-flow-box"><p class="mystery-flow-disclaimer">${say('The final price is confirmed at checkout. Use it within 1 day.','最终价格以结算页为准。领取后 1 天内有效。')}</p></div>
    ${buyNowBlock()}
    <button type="button" class="btn-ghost coupon-close" onclick="closeMysteryFlow()">${say('Later','稍后')}</button>`);
    wireBuyNow(flashSpec(p),r.memberCouponId);
  }finally{btn.disabled=false;}
},true);

/* ---------------- Gacha ---------------- */
// Spend comes from /ajax/carnival/user. The tier coupons come from the main-site slot
// "capsule" (Admin 入口配券), whose rows carry required_spend / unlocked / claim_status.
// One draw claims every unlocked, unclaimed tier, one claim call each, lowest first; the main
// site checks the spend and never issues a tier twice. Nothing is simulated on the page.
// Internal tests (carnival-test.json) open it as well (user, 11/18): claims are real tier coupons
// through the capsule slot, so it is open to every visitor until the test file expires.
const CAPSULE_SLOT='capsule';
let capsule={state:'unknown',rows:[]},capsuleBusy=false;
async function loadCapsule(){
  try{
    const j=await getJSON('/ajax/carnival/coupon?slot='+CAPSULE_SLOT),d=j?.data;
    if(Number(j?.code)!==1||d?.enabled!==true||d.slot!==CAPSULE_SLOT||d.error)throw Error('CAPSULE');
    // Each row is placed on the tier whose threshold equals its required_spend.
    const rows=(d.list||[]).map(r=>({row:r,tier:CONFIG.gacha.thresholds.indexOf(Number(r.required_spend))})).filter(x=>x.tier>=0).sort((a,b)=>a.tier-b.tier);
    capsule={state:d.logged_in===true?'ready':'guest',rows};
  }catch{capsule={state:'unavailable',rows:[]};}
  CONFIG.gacha.prizes.forEach((p,i)=>{p.left=capsule.rows.some(x=>x.tier===i&&tierClaimed(x.row))?0:1;});
  renderGlobe();renderPool();refreshDrawState();
}
const tierClaimed=r=>r.claim_status==='claimed';
const tierDue=r=>r.unlocked===true&&r.can_claim===true&&!tierClaimed(r);
async function claimTier(r){
  let res;
  try{res=await getJSON('/ajax/carnival/claim',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},body:new URLSearchParams({slot:CAPSULE_SLOT,coupon_id:String(Number(r.coupon_id))}).toString()});}
  catch{return {state:'unknown'};}
  if(Number(res?.code)===1)return {state:'claimed'};
  return {state:'rejected',status:String(res?.data?.claim_status||res?.data?.error||''),message:typeof res?.msg==='string'?res.msg.slice(0,200):''};
}
getAuthenticatedCouponUser=function(){return account.state==='signed_in'?{uid:account.uid}:null;};
getVerifiedOrderTotal=function(){return account.state==='signed_in'&&Number.isFinite(account.spend)?account.spend:null;};
const originalRefreshDraw=refreshDrawState;
refreshDrawState=function(){
  originalRefreshDraw();
  const btn=document.getElementById('drawBtn');btn.disabled=true;delete btn.dataset.carnivalLogin;
  const due=capsule.rows.filter(x=>tierDue(x.row)).length,ready=unlockedDraws();
  // Before draws open, the count is the milestones reached by spend and not yet claimed, so a
  // member sees the draw their order earned; once open, it is what the main site says is claimable.
  const open=capsule.state==='ready'&&phaseStatus(CONFIG.events.cm).k==='live',shown=open?due:ready;
  document.getElementById('mCost').innerHTML=say('My available draws','我的可抽次数')+` <strong>${shown}</strong>`;
  renderSpendProgress();
  if(account.state!=='signed_in'){btn.textContent=say('SIGN IN TO SEE YOUR SPEND','登录查看累计消费');btn.disabled=false;btn.dataset.carnivalLogin='1';return;}
  if(!open){
    const soon=!TEST&&phaseStatus(CONFIG.events.cm).k==='soon';
    btn.textContent=ready&&soon?say(`${ready} DRAW${ready>1?'S':''} READY · OPENS NOV 30`,`已解锁 ${ready} 次 · 11/30 开抽`):say('CAPSULE DRAWS OPEN SOON','扭蛋抽奖即将开放');
    return;
  }
  if(capsuleBusy){btn.textContent=t('mShaking');return;}
  if(due){btn.disabled=false;btn.textContent=due>1?say(`DRAW ${due} CAPSULES`,`抽取 ${due} 颗扭蛋`):t('draw');return;}
  const all=capsule.rows.length>0&&capsule.rows.every(x=>tierClaimed(x.row));
  btn.textContent=all?t('poolEmpty'):t('spendMore');
};
// Milestones reached by spend, less the tiers the main site already shows as claimed.
function unlockedDraws(){
  const spend=getVerifiedOrderTotal();if(!Number.isFinite(spend))return 0;
  return CONFIG.gacha.thresholds.filter((v,i)=>spend>=v&&!capsule.rows.some(x=>x.tier===i&&tierClaimed(x.row))).length;
}
// One equal segment per milestone, each filling from the previous threshold to its own, so the
// first $1 reads as a full segment instead of 0.1% of $1000.
function renderSpendProgress(){
  const bar=document.querySelector('.spendbar'),marks=document.getElementById('spendMarks');if(!bar||!marks)return;
  const th=CONFIG.gacha.thresholds,spend=getVerifiedOrderTotal(),has=Number.isFinite(spend);
  bar.classList.add('spendbar-seg');
  bar.querySelectorAll('.seg').forEach(x=>x.remove());
  bar.insertAdjacentHTML('beforeend',th.map((v,i)=>{
    const lo=i?th[i-1]:0,p=has?Math.max(0,Math.min(1,(spend-lo)/(v-lo))):0;
    return `<span class="seg${p>=1?' full':''}"><b style="width:${(p*100).toFixed(1)}%"></b></span>`;
  }).join(''));
  marks.innerHTML=th.map((v,i)=>{
    const hit=has&&spend>=v,claimed=capsule.rows.some(x=>x.tier===i&&tierClaimed(x.row));
    return `<span class="${hit?'hit':''}">$${v}${hit?`<small>${claimed?say('✓ Claimed','✓ 已领'):say('✓ Unlocked','✓ 已解锁')}</small>`:''}</span>`;
  }).join('');
  const next=document.getElementById('nextAt');if(!has||!next)return;
  const nt=th.find(v=>spend<v);
  next.innerHTML=nt===undefined?say(`All ${th.length} milestones unlocked! 🎉`,`${th.length} 个里程碑已全部解锁！🎉`)
    :say(`Next draw at <b>$${nt}</b> · $${(nt-spend).toFixed(2)} to go`,`下一抽：累计达 <b>$${nt}</b> · 还差 $${(nt-spend).toFixed(2)}`);
}
function capsuleResult(won,failed){
  const amount=i=>(CONFIG.gacha.prizes[i]?.name.match(/\$[0-9]+/)||[''])[0]+' OFF';
  document.getElementById('mIcon').style.display=won.length?'none':'';
  document.getElementById('gachaCoupon').innerHTML=won.map(x=>couponCard({amount:amount(x.tier),description:say('No-minimum coupon','无门槛优惠券'),minText:say('Min. spend: $0.00','最低消费：$0.00')})).join('');
  document.getElementById('mTitle').textContent=won.length?say(won.length>1?`You won ${won.length} coupons!`:'You won a coupon!',won.length>1?`抽中 ${won.length} 张优惠券！`:'抽中一张优惠券！'):say('No coupon this time','本次未领到优惠券');
  const unknown=failed.some(x=>x.res.state==='unknown');
  document.getElementById('mDesc').textContent=(won.length?say('They are in your account and apply at checkout.','已存入你的账户，结算时可用。'):'')
    +(failed.length?' '+(unknown?say('Some coupons could not be confirmed. Check My Coupons before trying again.','部分优惠券未能确认，请先到「我的优惠券」查看再重试。'):failed[0].res.message||say('Some coupons are not available right now.','部分优惠券暂时不可领取。')):'');
  document.getElementById('modalMask').classList.add('show');
}
document.getElementById('drawBtn').addEventListener('click',async e=>{
  e.stopImmediatePropagation();e.preventDefault();
  const btn=e.currentTarget;
  if(btn.dataset.carnivalLogin){requireLogin(null);return;}
  if(capsuleBusy||btn.disabled)return;
  const due=capsule.rows.filter(x=>tierDue(x.row));if(!due.length)return;
  capsuleBusy=true;refreshDrawState();
  const machine=document.getElementById('machine');machine.classList.add('shaking');document.getElementById('mScreen').textContent=t('mShaking');
  const won=[],failed=[];
  for(const x of due){const res=await claimTier(x.row);(res.state==='claimed'?won:failed).push({...x,res});
    track('fcactivity:coupon-claim',{state:res.state,reused:false,couponId:Number(x.row.coupon_id)});}
  await new Promise(r=>setTimeout(r,900));
  machine.classList.remove('shaking');document.getElementById('mScreen').textContent=t('mIdle');
  capsuleBusy=false;await loadCapsule();
  capsuleResult(won,failed);
},true);

/* ---------------- codes ---------------- */
document.getElementById('codesGrid')?.addEventListener('click',e=>{const b=e.target.closest('button');if(b)track('fcactivity:selection',{action:'code_copy',ids:[]});},true);

/* ---------------- start ---------------- */
document.getElementById('mysteryDemoNotice')?.remove();
livePriceNotes();
(async()=>{
  try{await H.adoptSocialLogin();}catch{}
  await refreshAccount();
  // The schedule says whether an internal test is on, which decides the home coupon checked.
  await Promise.all([loadMystery(),loadSchedule().then(refreshHomeCoupon),refreshHeader(),loadCapsule()]);
  refreshDrawState();
  try{const saved=JSON.parse(sessionStorage.getItem('carnival-login-resume')||'null');sessionStorage.removeItem('carnival-login-resume');
    if(saved&&account.state==='signed_in'&&Date.now()-saved.at<20*60*1000){if(saved.game&&saved.game!==curGame)selGame(saved.game);runResume(saved);}}catch{}
  setInterval(async()=>{const before=schedule?.sessions?.map(s=>s.products.length).join();await loadSchedule().catch(()=>{});if(before!==schedule?.sessions?.map(s=>s.products.length).join())renderFlash();refreshDrawState();},60000);
})();
})();
