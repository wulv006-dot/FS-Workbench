const {test}=require('node:test');
const assert=require('node:assert/strict');
const {checkout,claimActivityCoupon,mainSiteLogin,socialLoginUrl}=require('../native-code-handoff.js');
const origin='https://www.mmoexp.com';
// Synthetic main-site /ajax/carnival responses; no real coupon or account data.
function site({enabled=true,logged_in=true,list=[{coupon_id:9001,can_claim:true}],claim=id=>({claim_status:'claimed',coupon_id:id,member_coupon_id:77}),http=200}={}){
 const calls=[];
 const fetchImpl=async(path,init)=>{calls.push({path,method:init.method,body:init.body,credentials:init.credentials});
  const data=path.startsWith('/ajax/carnival/coupon')?{enabled,logged_in,slot:new URLSearchParams(path.split('?')[1]).get('slot'),list}:claim(Number(new URLSearchParams(init.body).get('coupon_id')));
  return {ok:http===200,json:async()=>({code:1,msg:'ok',data})};};
 return {fetchImpl,calls};
}
test('signed-in page claims each whitelisted coupon once for its slot',async()=>{
 const s=site();const r=await claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:s.fetchImpl});
 assert.deepEqual(r,{state:'claimed',slot:'fc_weekly',coupons:[{coupon_id:9001,member_coupon_id:77}]});
 assert.deepEqual(s.calls.map(c=>[c.method,c.path,c.body??null,c.credentials]),[['GET','/ajax/carnival/coupon?slot=fc_weekly',null,'same-origin'],['POST','/ajax/carnival/claim','slot=fc_weekly&coupon_id=9001','same-origin']]);
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
 await assert.rejects(claimActivityCoupon({pageId:'fc27-weekly',origin,fetchImpl:site({http:500}).fetchImpl}),/COUPON_HTTP_REJECTED/);
});
test('coupon-claimed checkout adds to cart and navigates without staging the code',async()=>{
 const data=new Map(),storage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)};let posts=0,navigated=null;
 const opts={storage,options:{origin,cartUrl:'/Cart.html',sameTab:true,code:'SYNTHETIC',consumerBehaviorConfirmed:true},operationId:'coupon-1',items:[{offer:{id:123,group:1,quantity:1,aid:456}}],liveVerified:true,couponClaimed:true,
  host:{batch:()=>({run:async()=>{posts++;return [{id:123,state:'confirmed'}];}})},navigate:url=>navigated=url};
 const r=await checkout(opts);
 assert.equal(r.state,'navigation_attempted_coupon_claimed');assert.equal(data.has('pending_discount_code'),false);assert.equal(navigated,origin+'/Cart.html');
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
 assert.deepEqual(Object.fromEntries(new URLSearchParams(s.calls[0].init.body)),{usname:'a@b.co',passwd:'secret1',remPwd:'true',loginbindkey:'',site_id:'266'});
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
