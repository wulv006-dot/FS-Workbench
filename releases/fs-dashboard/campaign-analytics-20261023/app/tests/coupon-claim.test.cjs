const {test}=require('node:test');
const assert=require('node:assert/strict');
const {checkout,claimActivityCoupon,mainSiteLogin,socialLoginUrl,mainSiteAccount}=require('../native-code-handoff.js');
const origin='https://www.mmoexp.com';
// Synthetic main-site /ajax/carnival responses; no real coupon or account data.
function site({enabled=true,logged_in=true,uid=4242,list=[{coupon_id:9001,can_claim:true}],claim=id=>({claim_status:'claimed',coupon_id:id,member_coupon_id:77}),http=200}={}){
 const calls=[];
 const fetchImpl=async(path,init)=>{calls.push({path,method:init.method,body:init.body,credentials:init.credentials});
  const data=path==='/ajax/carnival/user'?{logged_in,uid,enabled}:path.startsWith('/ajax/carnival/coupon')?{enabled,logged_in,slot:new URLSearchParams(path.split('?')[1]).get('slot'),list}:claim(Number(new URLSearchParams(init.body).get('coupon_id')));
  return {ok:http===200,json:async()=>({code:1,msg:'ok',data})};};
 return {fetchImpl,calls};
}
test('signed-in page claims each whitelisted coupon once for its slot',async()=>{
 const s=site();const r=await claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:s.fetchImpl});
 assert.deepEqual(r,{state:'claimed',slot:'fc_weekly',coupons:[{coupon_id:9001,member_coupon_id:77}]});
 assert.deepEqual(s.calls.map(c=>[c.method,c.path,c.body??null,c.credentials]),[['GET','/ajax/carnival/coupon?slot=fc_weekly',null,'same-origin'],['GET','/ajax/carnival/user',null,'same-origin'],['POST','/ajax/carnival/claim','slot=fc_weekly&coupon_id=9001','same-origin']]);
});
test('guest gets login_required without any claim POST',async()=>{
 const s=site({logged_in:false});const r=await claimActivityCoupon({pageId:'fc27-sbc',origin,fetchImpl:s.fetchImpl});
 assert.equal(r.state,'login_required');assert.equal(r.slot,'fc_sbc');assert.equal(s.calls.length,1);
});
test('disabled activity, empty slot, unknown page or other origin never claims',async()=>{
 for(const [args,opts] of [[{pageId:'fc27-trio',origin},{enabled:false}],[{pageId:'fc27-trio',origin},{list:[]}],[{pageId:'seasonal-vault',origin},{}],[{pageId:'fc27-weekly',origin:'https://mmoexp.com'},{}]]){
  const s=site(opts);assert.equal((await claimActivityCoupon({...args,fetchImpl:s.fetchImpl})).state,'unavailable');assert.equal(s.calls.filter(c=>c.method==='POST').length,0);
 }
});
test('unconfirmed claim or HTTP failure throws so the caller keeps the code path',async()=>{
 await assert.rejects(claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:site({claim:()=>({claim_status:'failed'})}).fetchImpl}),/COUPON_CLAIM_UNCONFIRMED/);
 // A failed coupon read claims nothing, so it is the switched-off state, not a stop.
 assert.equal((await claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:site({http:500}).fetchImpl})).state,'unavailable');
 let posts=0;const claimDown=async(path,init)=>{if(init.method==='POST'){posts++;throw new TypeError('network down');}return {ok:true,json:async()=>({code:1,data:{enabled:true,logged_in:true,slot:'fc_weekly',list:[{coupon_id:9001,can_claim:true}]}})};};
 await assert.rejects(claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:claimDown}),/network down/);assert.equal(posts,1);
});
test('coupon-claimed checkout adds to cart and navigates without staging the code',async()=>{
 const data=new Map(),storage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)};let posts=0,navigated=null;
 const opts={storage,options:{origin,cartUrl:'/Cart.html',sameTab:true,code:'SYNTHETIC',consumerBehaviorConfirmed:true},operationId:'coupon-1',items:[{offer:{id:123,group:1,quantity:1,aid:456}}],liveVerified:true,couponClaimed:true,memberCouponId:77,
  host:{batch:()=>({run:async()=>{posts++;return [{id:123,state:'confirmed'}];}})},navigate:url=>navigated=url};
 const r=await checkout(opts);
 assert.equal(r.state,'navigation_attempted_coupon_claimed');assert.equal(data.has('pending_discount_code'),false);assert.equal(navigated,origin+'/Cart.html');
 // The native cart selects this member coupon from its own pending key on load.
 assert.equal(data.get('pending_member_coupon_id'),'77');
 await checkout(opts);assert.equal(posts,1);
});
test('a failed cart add with a claimed coupon does not navigate',async()=>{
 const data=new Map(),storage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)};let navigated=0;
 const r=await checkout({storage,options:{origin,cartUrl:'/Cart.html',sameTab:true,code:'SYNTHETIC',consumerBehaviorConfirmed:true},operationId:'coupon-2',items:[{offer:{id:123,group:1,quantity:1,aid:456}}],liveVerified:true,couponClaimed:true,
  host:{batch:()=>({run:async()=>[{id:123,state:'rejected'}]})},navigate:()=>navigated++});
 assert.equal(r.state,'cart_incomplete_inspect_original');assert.equal(navigated,0);
});
function loginSite(response){const calls=[];return {calls,fetchImpl:async(path,init)=>{calls.push({path,init});return {ok:true,json:async()=>response};}};}
test('email sign-in posts the main-site login fields once, same origin',async()=>{
 const s=loginSite({code:1,msg:'ok',data:{}});
 assert.deepEqual(await mainSiteLogin({email:' a@b.co ',password:'secret1',origin,fetchImpl:s.fetchImpl}),{state:'signed_in'});
 assert.equal(s.calls.length,1);assert.equal(s.calls[0].path,'/user/login.html');assert.equal(s.calls[0].init.method,'POST');assert.equal(s.calls[0].init.credentials,'same-origin');
 // Exactly the main-site jQuery login request (captured 2026-11-16): no loginbindkey.
 assert.deepEqual(Object.fromEntries(new URLSearchParams(s.calls[0].init.body)),{usname:'a@b.co',passwd:'secret1',remPwd:'true',site_id:'266'});
 assert.equal(s.calls[0].init.headers.Accept,'application/json, text/javascript, */*; q=0.01');
 assert.equal(s.calls[0].init.headers['Content-Type'],'application/x-www-form-urlencoded; charset=UTF-8');
});
test('a hung login request ends with LOGIN_TIMEOUT instead of spinning forever',async()=>{
 const hang=async(_path,init)=>new Promise((_resolve,reject)=>init.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));
 await assert.rejects(mainSiteLogin({email:'a@b.co',password:'secret1',origin,fetchImpl:hang,timeoutMs:20}),/LOGIN_TIMEOUT/);
});
test('header account state: guest, signed in with avatar and cart count',async()=>{
 const page=(logged_in,html)=>async path=>({ok:true,json:async()=>({code:1,data:{logged_in}}),text:async()=>html});
 const guestHtml='<li class="cart-area area"><span class="cart-total">2</span></li><li class="user-area jq-user-area area"><img class="userimg" src="/mmoexp-v250528/img/user.png"></li>';
 assert.deepEqual(await mainSiteAccount({origin,fetchImpl:page(false,guestHtml)}),{state:'guest',cart:2,avatar:null,frame:null});
 // Signed-in markup as served by /ajax/html on 2026-11-16 (structure only).
 const userHtml='<span class="cart-total" style="">5</span><li class="user-areas area"><a class="userche jq-userche userche-photo"><span class="member-level-avatar member-level-avatar--2"><img class="user-avatar-img member-level-avatar__face" src="/mmoexp-v250528/images/vip/2/avatar.png"><img class="member-level-avatar__frame" src="/mmoexp-v250528/images/vip/2/avatar-frame.png"></span></a></li>';
 assert.deepEqual(await mainSiteAccount({origin,fetchImpl:page(true,userHtml)}),{state:'signed_in',cart:5,avatar:origin+'/mmoexp-v250528/images/vip/2/avatar.png',frame:origin+'/mmoexp-v250528/images/vip/2/avatar-frame.png'});
 assert.equal((await mainSiteAccount({origin:'https://evil.example',fetchImpl:page(true,userHtml)})).state,'unavailable');
});
test('rejected sign-in returns the main-site message; other origins never post',async()=>{
 assert.deepEqual(await mainSiteLogin({email:'a@b.co',password:'wrong12',origin,fetchImpl:loginSite({code:0,msg:'Wrong password!'}).fetchImpl}),{state:'rejected',message:'Wrong password!'});
 const s=loginSite({code:1});await assert.rejects(mainSiteLogin({email:'a@b.co',password:'secret1',origin:'https://evil.example',fetchImpl:s.fetchImpl}),/LOGIN_ORIGIN_UNVERIFIED/);assert.equal(s.calls.length,0);
});
test('social sign-in returns the provider URL with this page as selfurl',async()=>{
 const s=loginSite({code:1,msg:'authorize url',data:{redirect_url:'https://www.facebook.com/dialog/oauth?x=1'}});
 assert.deepEqual(await socialLoginUrl({provider:'facebook',returnUrl:origin+'/events/Weekly-Scout.html?utm=a#top',origin,fetchImpl:s.fetchImpl}),{state:'redirect',url:'https://www.facebook.com/dialog/oauth?x=1'});
 assert.equal(s.calls[0].path,'/user/login.html?act=loginapp&selfurl='+encodeURIComponent(origin+'/events/Weekly-Scout.html')+'&site_id=266&type=facebook');
});
test('social sign-in rejects unknown providers, foreign return pages and non-https targets',async()=>{
 await assert.rejects(socialLoginUrl({provider:'steam',returnUrl:origin+'/events/x.html',origin,fetchImpl:loginSite({}).fetchImpl}),/LOGIN_PROVIDER_INVALID/);
 await assert.rejects(socialLoginUrl({provider:'google',returnUrl:'https://evil.example/x',origin,fetchImpl:loginSite({}).fetchImpl}),/LOGIN_ORIGIN_UNVERIFIED/);
 assert.equal((await socialLoginUrl({provider:'google',returnUrl:origin+'/events/x.html',origin,fetchImpl:loginSite({code:1,data:{redirect_url:'javascript:alert(1)'}}).fetchImpl})).state,'rejected');
});
test('social login token is stripped from the address and handed to the main site once',async()=>{
 const {takeSocialLoginToken,adoptSocialLogin}=require('../native-code-handoff.js');
 const replaced=[];const history={state:null,replaceState:(_s,_t,url)=>replaced.push(url)};
 const loc={origin,pathname:'/events/Player-Trio.html',search:'?utm_source=x&ba-user-token=abcDEF12-3456-7890&member_welcome=1',hash:'#build'};
 assert.equal(takeSocialLoginToken(loc,history),'abcDEF12-3456-7890');
 assert.deepEqual(replaced,['/events/Player-Trio.html?utm_source=x#build']);
 assert.equal(takeSocialLoginToken({...loc,search:'?utm_source=x'},history),null);assert.equal(replaced.length,1,'no token, no rewrite');
 assert.equal(takeSocialLoginToken({...loc,origin:'https://evil.example'},history),null);
 assert.equal(takeSocialLoginToken({...loc,search:'?ba-user-token=%3Cscript%3E&member_welcome=1'},history),null,'malformed tokens are dropped, still stripped');
 const calls=[];const fetchImpl=async(path,init)=>{calls.push({path,credentials:init.credentials});return {ok:true};};
 assert.deepEqual(await adoptSocialLogin({fetchImpl,token:'abcDEF12-3456-7890'}),{state:'adopted'});
 assert.deepEqual(calls,[{path:'/ajax/html?ba-user-token=abcDEF12-3456-7890&member_welcome=1',credentials:'same-origin'}]);
 assert.deepEqual(await adoptSocialLogin({fetchImpl,token:null}),{state:'none'});assert.equal(calls.length,1);
});
function memoryStorage(){const rows=new Map();return {getItem:k=>rows.has(k)?rows.get(k):null,setItem:(k,v)=>rows.set(k,String(v)),rows};}
test('one coupon per account per 24h across pages: reuse inside the window, claim again after it',async()=>{
 const storage=memoryStorage(),day=24*60*60*1000,t0=Date.UTC(2026,10,16,12);let member=100;
 const s=site({claim:id=>({claim_status:'claimed',coupon_id:id,member_coupon_id:++member})});
 const first=await claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:s.fetchImpl,storage,now:t0});
 assert.deepEqual(first.coupons,[{coupon_id:9001,member_coupon_id:101}]);assert.equal(first.reused,undefined);
 const again=await claimActivityCoupon({pageId:'fc27-trio',origin,fetchImpl:s.fetchImpl,storage,now:t0+day-1});
 assert.equal(again.reused,true,'a second checkout on another page inside 24h reuses the same coupon');
 assert.deepEqual(again.coupons,[{coupon_id:9001,member_coupon_id:101}]);assert.equal(again.next_claim_at,t0+day);
 assert.equal(s.calls.filter(c=>c.method==='POST').length,1,'no second claim POST inside the window');
 const next=await claimActivityCoupon({pageId:'fc27-sbc',origin,fetchImpl:s.fetchImpl,storage,now:t0+day});
 assert.deepEqual(next.coupons,[{coupon_id:9001,member_coupon_id:102}],'a new coupon once 24h have passed');
 assert.equal(s.calls.filter(c=>c.method==='POST').length,2);
});
test('the 24h window is per account and an unreadable ledger never blocks a claim',async()=>{
 const storage=memoryStorage(),t0=Date.UTC(2026,10,16,12);
 await claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:site({uid:1}).fetchImpl,storage,now:t0});
 const other=await claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:site({uid:2}).fetchImpl,storage,now:t0+1000});
 assert.equal(other.reused,undefined,'another account on the same browser still gets its own coupon');
 storage.setItem('fs-fc27-coupon-claims-v1','{not json');
 const s=site({uid:1});const r=await claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:s.fetchImpl,storage,now:t0+2000});
 assert.equal(r.reused,undefined);assert.equal(s.calls.filter(c=>c.method==='POST').length,1);
});
