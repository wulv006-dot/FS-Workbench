// End-to-end coupon checkout on the real event page with a synthetic main site:
// header account states, login errors, login -> claim -> Cart/add -> cart handoff.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const app=path.resolve(__dirname,'..'),key='model-266-1327-81',quantity={min:'1',max:'1',step:'1',unit:'item',group:'1'};
const refs=['ps','xbox','pc'].map((code,i)=>({code,aid:['21587','21585','21589'][i],ref:{site_id:'266',game_id:'1327',model_id:'81',goods_id:String(801+i)}}));
function fixture(){
 const config=JSON.parse(fs.readFileSync(path.join(app,'catalog.json')));
 config.products[key]={key,title:'Coupon fixture bundle',name:'Coupon fixture bundle',kind:'bundle',preview_only:true,model_id:'81',native_offers:Object.fromEntries(refs.map(({code})=>[code,{checkout_ready:false}])),platforms:Object.fromEntries(refs.map(({code,aid,ref})=>[code,{id:ref.goods_id,aid,binding_state:'verified',product_ref:ref}]))};
 config.bundles.ids=[key];config.weekly.bundleIds=[key];
 const products=refs.flatMap(({code,aid,ref})=>[{key:'fc-'+key+'-'+code,preview_only:true,product_ref:ref,platform:{code,attribute_id:aid},available:false},{key:'admin-'+ref.goods_id,product_ref:ref,platform:{code,attribute_id:aid},quantity,attributes:[],available:false}]);
 const snapshot={schema_version:1,release_id:'coupon-fixture',config_hash:'c'.repeat(64),pages:[{page_id:'fc27-weekly',activity_id:'fc27-season2',active:true,product_keys:products.map(p=>p.key)}],products,
  seasonal_model_contracts:{81:{verified:true,model_ref:{site_id:'266',game_id:'1327',model_id:'81'},combinations:refs.map(({ref},i)=>({product_key:'admin-'+ref.goods_id,quantity,attributes:[],price:{source:'admin_current',base_minor:1000+500*i,currency:'USD',minor_unit_scale:2,quantity_value:'1',expires_at:'2099-01-01T00:00:00Z'}}))}},
  native_checkout:{status:'configured',verification_ref:'coupon-fixture',valid_from:'2020-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z',origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,
   bindings:refs.map(({ref,aid})=>({activity_id:'fc27-season2',page_id:'fc27-weekly',product_key:'admin-'+ref.goods_id,quantity:{value:'1',unit:'item'},attributes:[],off_percent:10,code:'FCSCOUT10',native:{category:'new_items',id:ref.goods_id,group:'1',num:'1',aid,attr:''}}))}};
 return {config,snapshot};
}
async function openPage(browser,site){
 const {config,snapshot}=fixture(),context=await browser.newContext(),page=await context.newPage();page.setDefaultTimeout(5000);
 page.on('pageerror',e=>site.errors.push(e.message));
 await page.route('**/*',route=>{
  const req=route.request(),u=new URL(req.url());
  // Only the avatar fixture lives on the asset host; anything else off-site is a failure.
  if(u.origin==='https://assets.mmoexp.com'&&u.pathname.startsWith('/avatar/'))return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=','base64')});
  if(u.origin!=='https://www.mmoexp.com'){site.errors.push('off-site request '+u.origin);return route.abort();}
  if(u.pathname.endsWith('/api/campaign/config'))return route.fulfill({json:snapshot});
  if(u.pathname.endsWith('/api/campaign/capabilities'))return route.fulfill({json:{integration_mode:'preview',live_checkout:false}});
  if(u.pathname==='/ajax/carnival/user')return route.fulfill({json:{code:1,data:{logged_in:site.loggedIn,enabled:true}}});
  if(u.pathname==='/ajax/html')return route.fulfill({contentType:'text/html',body:'<li class="cart-area area"><span class="cart-total">'+site.cart+'</span></li>'+(site.loggedIn?'<li class="user-areas area"><span class="member-level-avatar"><img class="user-avatar-img member-level-avatar__face" src="https://assets.mmoexp.com/avatar/fixture.png"><img class="member-level-avatar__frame" src="https://assets.mmoexp.com/avatar/frame.png"></span></li>':'<li class="user-area jq-user-area area"><img class="userimg" src="/mmoexp-v250528/img/user.png"></li>')});
  if(u.pathname==='/ajax/carnival/coupon')return route.fulfill({json:{code:1,data:{enabled:true,logged_in:site.loggedIn,slot:u.searchParams.get('slot'),list:[{coupon_id:1395,can_claim:site.loggedIn}]}}});
  if(u.pathname==='/ajax/carnival/claim'){site.claims.push(Object.fromEntries(new URLSearchParams(req.postData())));return route.fulfill({json:{code:1,data:{claim_status:'claimed',coupon_id:1395,member_coupon_id:555}}});}
  if(u.pathname==='/user/login.html'){const body=Object.fromEntries(new URLSearchParams(req.postData()));site.logins.push({fields:Object.keys(body).sort(),accept:req.headers()['accept']});const ok=body.passwd===site.password;if(ok)site.loggedIn=true;return route.fulfill({json:ok?{code:1,msg:'ok',data:{}}:{code:0,msg:'Invalid email or password'}});}
  if(u.pathname==='/Cart/add.html'){site.posts.push(Object.fromEntries(new URLSearchParams(req.postData())));return route.fulfill({json:{code:1}});}
  if(u.pathname==='/Cart.html')return route.fulfill({contentType:'text/html',body:'<!doctype html><p>Isolated coupon cart</p>'});
  if(req.method()==='POST')return route.abort();
  const asset=u.pathname.replace(/^\/events\//,''),file=path.join(app,asset);if(!file.startsWith(app)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({contentType:({'.html':'text/html','.js':'application/javascript','.css':'text/css'})[path.extname(file)]||'application/octet-stream',body:asset==='catalog.js'?'window.FC_ACTIVITY_CONFIG='+JSON.stringify(config)+';':fs.readFileSync(file)});
 });
 await page.goto('https://www.mmoexp.com/events/Weekly-Scout.html');
 return {page,context};
}
test('guest: Log In header, wrong password feedback, login continues to coupon claim and cart',async()=>{
 const browser=await chromium.launch({headless:true}),site={loggedIn:false,cart:2,password:'right-pass-123',posts:[],claims:[],logins:[],errors:[]};
 try{
  const {page}=await openPage(browser,site);
  await page.locator('.fca-account-login').waitFor({state:'visible'});
  assert.equal(await page.locator('.fca-account-user').isVisible(),false);
  assert.equal(await page.locator('.fca-account-count').innerText(),'2');
  await page.locator('#bundle-grid [data-preview-model]').waitFor();await page.locator('input[name=platform][value=ps]').check();
  await page.locator('#bundle-grid [data-toggle-bundle]').click();await page.locator('#review-dialog[open]').waitFor();
  assert.doesNotMatch(await page.locator('#review-dialog').innerText(),/activity code/i,'coupon only: no code wording');
  await page.locator('#submit-selection').click();
  await page.locator('#login-dialog[open]').waitFor();
  assert.equal(site.posts.length,0,'guests never reach Cart/add before logging in');assert.equal(site.claims.length,0);
  assert.equal(await page.locator('[data-login-guest]').count(),0,'no guest code checkout');
  await page.locator('#login-dialog input[name=email]').fill('shopper@example.com');
  await page.locator('#login-dialog input[name=password]').fill('wrong-pass-1');
  await page.locator('#login-dialog [data-login-submit]').click();
  const error=page.locator('#login-dialog [data-login-error]');await error.waitFor({state:'visible'});
  assert.match(await error.innerText(),/Incorrect email or password/);
  assert.equal(await page.locator('#login-dialog input[name=password]').getAttribute('aria-invalid'),'true');
  assert.equal(await page.locator('#login-dialog input[name=password]').inputValue(),'wrong-pass-1','typed values are kept after a failed login');
  assert.equal(await page.locator('#login-dialog [data-login-submit]').isEnabled(),true,'the button is usable again');
  assert.deepEqual(site.logins[0],{fields:['passwd','remPwd','site_id','usname'],accept:'application/json, text/javascript, */*; q=0.01'});
  await page.locator('#login-dialog input[name=password]').fill('right-pass-123');
  assert.equal(await error.isVisible(),false,'editing clears the error');
  await page.locator('#login-dialog [data-login-submit]').click();
  await page.waitForURL('**/Cart.html');
  assert.deepEqual(site.claims,[{slot:'fc_weekly',coupon_id:'1395'}]);
  assert.deepEqual(site.posts,[{category:'new_items',id:'801',group:'1',num:'1',attr:'',aid:'21587'}]);
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('pending_member_coupon_id')),'555');
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('pending_discount_code')),null,'no code once the coupon is claimed');
  assert.deepEqual(site.errors,[]);
 }finally{await browser.close();}
});
test('signed in: avatar header, checkout claims without a dialog; mobile header fits',async()=>{
 const browser=await chromium.launch({headless:true}),site={loggedIn:true,cart:5,password:'x',posts:[],claims:[],logins:[],errors:[]};
 try{
  const {page}=await openPage(browser,site);
  await page.locator('.fca-account-user').waitFor({state:'visible'});
  assert.equal(await page.locator('.fca-account-login').isVisible(),false);
  assert.equal(await page.locator('.fca-account-face').getAttribute('src'),'https://assets.mmoexp.com/avatar/fixture.png');
  assert.equal(await page.locator('.fca-account-frame').getAttribute('src'),'https://assets.mmoexp.com/avatar/frame.png');
  assert.equal(await page.locator('.fca-account-count').innerText(),'5');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'header fits at phone width');
  assert(await page.locator('.fca-account-user').isVisible());
  await page.setViewportSize({width:1280,height:800});
  await page.locator('#bundle-grid [data-preview-model]').waitFor();await page.locator('input[name=platform][value=xbox]').check();
  await page.locator('#bundle-grid [data-toggle-bundle]').click();await page.locator('#review-dialog[open]').waitFor();
  await page.locator('#submit-selection').click();await page.waitForURL('**/Cart.html');
  assert.equal(site.logins.length,0);assert.equal(site.claims.length,1);
  assert.deepEqual(site.posts,[{category:'new_items',id:'802',group:'1',num:'1',attr:'',aid:'21585'}]);
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('pending_member_coupon_id')),'555');
  assert.deepEqual(site.errors,[]);
 }finally{await browser.close();}
});
