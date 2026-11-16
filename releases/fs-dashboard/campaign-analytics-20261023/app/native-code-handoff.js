/* Observed native transport. Production remains unconfigured until a separately
 * approved private policy is published; reference prices never grant commerce.
 * Cart currently attempts Apply after consuming this key. Require explicit
 * consumer-behavior confirmation; never represent this as prefill-only.
 */
(function(root){
  'use strict';
  const KEY='pending_discount_code';
  const fail=code=>{throw Object.assign(new Error(code),{code});};
  const stable=value=>JSON.stringify(value,(_key,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
  const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).every(k=>keys.includes(k));
  const positive=v=>typeof v==='string'&&/^[1-9]\d{0,14}$/.test(v)&&Number.isSafeInteger(Number(v));
  const decimal=v=>{if(typeof v!=='string'||!/^\d{1,12}(?:\.\d{1,6})?$/.test(v))fail('NATIVE_CONFIGURATION_INVALID');const [a,b='']=v.split('.');return BigInt(a)*1000000n+BigInt(b.padEnd(6,'0'));};
  function nativeBody(body,observed=false){
    if(!exact(body,['category','id','group','num','attr','aid'])||!['id','group','num'].every(k=>positive(body[k])))fail('NATIVE_LINE_INVALID');
    if(observed){
      if(!['new_items','new_gold'].includes(body.category)||typeof body.attr!=='string'||body.attr.length>4000||/[\x00-\x1f\x7f]/.test(body.attr)||body.aid!==''&&!positive(body.aid))fail('NATIVE_LINE_INVALID');
      return Object.fromEntries(['category','id','group','num','attr','aid'].map(k=>[k,body[k]]));
    }
    if(body.attr!=='')fail('NATIVE_LINE_INVALID');
    if(body.category==='new_items'){if(!positive(body.aid))fail('NATIVE_LINE_INVALID');}
    else if(body.category!=='new_gold'||stable(body)!==stable({category:'new_gold',id:'163329311',group:'1000',num:'1',attr:'',aid:''}))fail('NATIVE_LINE_INVALID');
    return Object.fromEntries(['category','id','group','num','attr','aid'].map(k=>[k,body[k]]));
  }
  // Shared browser/server whitelist. This is a controlled publication contract,
  // not proof inferred from browser flags, catalog prices or a demo quote.
  function projectConfiguration(input,pages=[],products=[]){
    if(input==null)return {status:'unconfigured'};
    if(input.status==='unconfigured'&&exact(input,['status']))return {status:'unconfigured'};
    if(!exact(input,['status','verification_ref','valid_from','valid_until','origin','cart_path','consumer_behavior_confirmed','bindings'])||input.status!=='configured'
      ||!/^[-A-Za-z0-9_.:]{1,128}$/.test(input.verification_ref||'')||input.origin!=='https://www.mmoexp.com'||!['/Cart.html','/uk/Cart.html'].includes(input.cart_path)
      ||input.consumer_behavior_confirmed!==true||!Number.isFinite(Date.parse(input.valid_from))||!Number.isFinite(Date.parse(input.valid_until))||Date.parse(input.valid_from)>=Date.parse(input.valid_until)
      ||!Array.isArray(input.bindings)||!input.bindings.length||input.bindings.length>3000)fail('NATIVE_CONFIGURATION_INVALID');
    const seen=new Set(),bindings=input.bindings.map(b=>{
      if(!exact(b,['activity_id','page_id','product_key','quantity','attributes','off_percent','code','native','observed_serialization'])||!exact(b.quantity,['value','unit'])||!positive(b.quantity.value)||typeof b.quantity.unit!=='string'
        ||!Array.isArray(b.attributes)||b.attributes.length>30||b.attributes.some(a=>!exact(a,['attribute_id','value_id'])||!positive(a.attribute_id)||!positive(a.value_id))||new Set(b.attributes.map(a=>a.attribute_id)).size!==b.attributes.length||![8,10,15].includes(b.off_percent))fail('NATIVE_CONFIGURATION_INVALID');
      plan({origin:input.origin,cartUrl:input.cart_path,sameTab:true,code:b.code,consumerBehaviorConfirmed:true});
      const proof=b.observed_serialization;
      if(proof&&(!exact(proof,['verification_ref','game_id','model_id','region','currency'])||!/^[-A-Za-z0-9_.:]{1,128}$/.test(proof.verification_ref||'')||!positive(proof.game_id)||!positive(proof.model_id)||proof.region!=='us'||proof.currency!=='USD'))fail('NATIVE_CONFIGURATION_INVALID');
      const page=pages.find(p=>p.page_id===b.page_id&&p.activity_id===b.activity_id),product=products.find(p=>p.key===b.product_key),body=nativeBody(b.native,Boolean(proof)),key=stable([b.page_id,b.product_key,b.quantity,b.attributes,b.off_percent]);
      if(!page?.product_keys?.includes(b.product_key)||!product||product.preview_only||product.product_ref?.site_id!=='266'||product.product_ref.goods_id!==body.id||seen.has(key))fail('NATIVE_CONFIGURATION_INVALID');seen.add(key);
      if(proof){
        if(b.page_id!=='seasonal-vault'||b.activity_id!=='mmoexp-seasonal'||input.cart_path!=='/Cart.html'||product.product_ref.game_id!==proof.game_id||product.product_ref.model_id!==proof.model_id
          ||Boolean(b.attributes.length)!==Boolean(body.attr)||!Array.isArray(product.attributes)||b.attributes.some(a=>!product.attributes.some(s=>s.attribute_id===a.attribute_id&&s.values.includes(a.value_id)))
          ||product.attributes.some(a=>a.required&&!b.attributes.some(b=>b.attribute_id===a.attribute_id)))fail('NATIVE_CONFIGURATION_INVALID');
        if(proof.game_id==='1327'&&proof.model_id==='41217957'&&(stable(body)!==stable({category:'new_gold',id:product.product_ref.goods_id,group:'1000',num:'1',attr:'',aid:''})||!['21587','21585','21589'].includes(product.platform?.attribute_id)||b.quantity.value!=='1000'||b.quantity.unit!=='K'))fail('NATIVE_CONFIGURATION_INVALID');
      }else if(body.category==='new_items'){
        if(!['fc27-weekly','fc27-sbc','fc27-trio'].includes(b.page_id)||b.activity_id!=='fc27-season2'||b.off_percent!==10||product.product_ref.game_id!=='1327'
          ||product.platform?.attribute_id!==body.aid||b.quantity.unit!=='item'||body.num!==b.quantity.value||body.group!==product.quantity?.group)fail('NATIVE_CONFIGURATION_INVALID');
      }else if(b.page_id!=='seasonal-vault'||b.activity_id!=='mmoexp-seasonal'||input.cart_path!=='/Cart.html'||product.product_ref.game_id!=='1327'||product.product_ref.model_id!=='41217957'
        ||product.platform?.attribute_id!=='21587'||b.quantity.value!=='1000'||b.quantity.unit!=='K')fail('NATIVE_CONFIGURATION_INVALID');
      const q=product.quantity;if(!q||q.unit!==b.quantity.unit||!Array.isArray(product.attributes)||!proof&&(product.attributes.length||b.attributes.length)||decimal(q.step)<=0n||decimal(b.quantity.value)<decimal(q.min)||decimal(b.quantity.value)>decimal(q.max)||(decimal(b.quantity.value)-decimal(q.min))%decimal(q.step)!==0n)fail('NATIVE_CONFIGURATION_INVALID');
      return {activity_id:b.activity_id,page_id:b.page_id,product_key:b.product_key,quantity:{...b.quantity},attributes:b.attributes.map(a=>({...a})),off_percent:b.off_percent,code:b.code.trim(),native:body,...(proof?{observed_serialization:{...proof}}:{})};
    });
    return {status:'configured',verification_ref:input.verification_ref,valid_from:new Date(input.valid_from).toISOString(),valid_until:new Date(input.valid_until).toISOString(),origin:input.origin,cart_path:input.cart_path,consumer_behavior_confirmed:true,bindings};
  }
  function publishedPlan(snapshot,selection,{origin=root.location?.origin,now=Date.now()}={}){
    const config=projectConfiguration(snapshot?.native_checkout,snapshot?.pages,snapshot?.products),page=snapshot?.pages?.find(p=>p.page_id===selection?.page_id&&p.activity_id===selection?.activity_id);
    if(config.status!=='configured')fail('NATIVE_CHECKOUT_UNCONFIGURED');
    if(!snapshot.release_id||!snapshot.config_hash||origin!==config.origin)fail('HANDOFF_ORIGIN_UNVERIFIED');
    if(!Number.isFinite(now)||now<Date.parse(config.valid_from)||now>Date.parse(config.valid_until)||!page?.active||page.starts_at&&now<Date.parse(page.starts_at)||page.ends_at&&now>Date.parse(page.ends_at))fail('NATIVE_CONFIGURATION_EXPIRED');
    if(!Array.isArray(selection.lines)||!selection.lines.length||selection.lines.length>50)fail('CART_LINES_REQUIRED');
    let reveal_request=null;
    if(selection.page_id==='seasonal-vault'){
      const h=snapshot.halloween,game=h?.games?.find(g=>selection.slot==='fixed'?g.fixed_model===selection.model_id&&g.fixed_off_percent===selection.off_percent:g.admin_game_id===selection.game_id&&(g.random_source.mode==='quantity_tiers'&&g.fixed_model===selection.model_id||g.random_source.mode==='category_dynamic'||g.random_models.includes(selection.model_id)));
      if(h?.status!=='configured'||!game||now<Date.parse(h.starts_at)||now>Date.parse(h.ends_at))fail('NATIVE_SCOPE_MISMATCH');
      if(game.random_source.mode==='quantity_tiers'){
        const quantity=selection.quantity,allowed=selection.slot==='fixed'?[game.fixed_quantity]:game.random_quantities;
        if(!quantity||!allowed.some(q=>q.value===quantity.value&&q.unit===quantity.unit)||selection.lines.some(line=>line.quantity?.value!==quantity.value||line.quantity?.unit!==quantity.unit))fail('NATIVE_SCOPE_MISMATCH');
      }else if(selection.quantity)fail('NATIVE_SCOPE_MISMATCH');
      if(selection.slot!=='fixed'){
        if(!['random-1','random-2'].includes(selection.slot)||!h.probabilities.some(p=>p.off_percent===selection.off_percent&&p.weight>0)||!/^[-a-f0-9]{36}$/i.test(selection.reveal_request_id||''))fail('HALLOWEEN_REVEAL_REQUIRED');
        reveal_request={request_id:selection.reveal_request_id,game_id:game.id,slot:selection.slot,model_id:selection.model_id,off_percent:selection.off_percent,...(selection.quantity?{quantity:selection.quantity}:{})};
      }
    }
    const bindings=selection.lines.map(line=>{
      const matches=config.bindings.filter(b=>b.page_id===selection.page_id&&b.activity_id===selection.activity_id&&b.product_key===line.product_key&&b.off_percent===selection.off_percent
        &&b.quantity.value===line.quantity?.value&&b.quantity.unit===line.quantity?.unit&&stable(b.attributes)===stable(line.attributes||[]));
      if(matches.length!==1||selection.page_id==='seasonal-vault'&&snapshot.products.find(p=>p.key===line.product_key)?.product_ref?.model_id!==selection.model_id)fail('NATIVE_SCOPE_MISMATCH');return matches[0];
    });
    if(new Set(bindings.map(b=>b.code)).size!==1||new Set(bindings.map(b=>b.product_key)).size!==bindings.length)fail('NATIVE_SCOPE_MISMATCH');
    const options={origin,cartUrl:config.cart_path,sameTab:true,code:bindings[0].code,consumerBehaviorConfirmed:true};plan(options);
    return {options,items:bindings.map(b=>({product_key:b.product_key,native_payload:{...b.native},...(b.observed_serialization?{observed_serialization:true}:{}),offer:{id:Number(b.native.id),group:Number(b.native.group),quantity:Number(b.native.num),aid:b.native.aid?Number(b.native.aid):null}})),
      signature:stable([snapshot.release_id,snapshot.config_hash,{verification_ref:config.verification_ref,valid_from:config.valid_from,valid_until:config.valid_until,origin:config.origin,cart_path:config.cart_path,consumer_behavior_confirmed:config.consumer_behavior_confirmed},bindings,selection]),page_id:selection.page_id,activity_id:selection.activity_id,...(reveal_request?{reveal_request}:{})};
  }
  async function checkoutPublished({snapshot,selection,storage,host,navigate,origin,onCartConfirmed,cartGuard,couponClaimed=false,memberCouponId=null}){
    if(snapshot?.native_checkout_claim_required){
      if(typeof host?.claimSelection!=='function')fail('NATIVE_SELECTION_CLAIM_REQUIRED');
      const receipt=await host.claimSelection(selection);
      if(receipt?.status!=='native_selection_prepared'||receipt.release_id!==snapshot.release_id||receipt.config_hash!==snapshot.config_hash||receipt.rule_hash!==snapshot.rule_hash)fail('RULE_VERSION_CONFLICT');
      snapshot={...snapshot,native_checkout:receipt.native_checkout,native_checkout_claim_required:false};
    }
    const approved=publishedPlan(snapshot,selection,{origin}),key='fs-native-page:'+approved.activity_id+':'+approved.page_id+(selection.page_id==='seasonal-vault'?':'+selection.model_id+':'+selection.slot+':'+(selection.reveal_request_id||'fixed'):'');
    const pending=storage.getItem(KEY);if(pending&&pending!==approved.options.code)fail('PENDING_CODE_CONFLICT');
    if(typeof host?.batch!=='function'||typeof navigate!=='function')fail('NATIVE_HOST_UNAVAILABLE');
    if(approved.reveal_request){
      if(typeof host.verifySelection!=='function')fail('HALLOWEEN_REVEAL_REQUIRED');
      const verified=await host.verifySelection(approved.reveal_request);
      if(verified?.status!=='selection_confirmed'||verified.release_id!==snapshot.release_id||verified.config_hash!==snapshot.config_hash||Object.entries(approved.reveal_request).some(([key,value])=>stable(verified[key])!==stable(value)))fail('HALLOWEEN_REVEAL_MISMATCH');
    }
    if(cartGuard&&selection.page_id==='seasonal-vault')return cartGuard.checkout({snapshot,selection,approved,storage,host,navigate,onCartConfirmed});
    let operation;try{operation=JSON.parse(storage.getItem(key)||'null');}catch{fail('OPERATION_RECORD_UNREADABLE');}
    if(operation&&operation.signature!==approved.signature)fail('OPERATION_CONFLICT');
    if(!operation){operation={id:root.crypto.randomUUID(),signature:approved.signature};const text=JSON.stringify(operation);storage.setItem(key,text);if(storage.getItem(key)!==text)fail('OPERATION_RECORD_UNCONFIRMED');}
    return checkout({storage,options:approved.options,operationId:operation.id,items:approved.items,host,navigate,onCartConfirmed,liveVerified:true,couponClaimed:couponClaimed===true&&selection.page_id!=='seasonal-vault',memberCouponId});
  }
  function plan({origin,cartUrl,sameTab,code,consumerBehaviorConfirmed=false}){
    if(typeof cartUrl!=='string')throw new Error('HANDOFF_ORIGIN_UNVERIFIED');
    const target=new URL(cartUrl,origin);
    if(origin!=='https://www.mmoexp.com'||target.origin!==origin||!['/Cart.html','/uk/Cart.html'].includes(target.pathname)||target.search||target.hash||target.username||target.password)throw new Error('HANDOFF_ORIGIN_UNVERIFIED');
    if(sameTab!==true)throw new Error('SAME_TAB_REQUIRED');
    if(typeof code!=='string'||!code.trim()||code.length>128||/[\x00-\x1f\x7f]/.test(code))throw new Error('CODE_INVALID');
    if(consumerBehaviorConfirmed!==true)throw new Error('NATIVE_AUTO_APPLY_REQUIRES_CONFIRMATION');
    return {key:KEY,value:code.trim(),cartUrl:target.href,state:'prepared_not_applied',nativeMayApply:true};
  }
  function stage(storage,options,operation,persist=()=>{}){
    const handoff=plan(options);
    if(!operation||typeof operation.id!=='string'||!operation.id)throw new Error('OPERATION_ID_REQUIRED');
    const signature=JSON.stringify([handoff.value,handoff.cartUrl]);
    if(operation.signature&&operation.signature!==signature)throw new Error('OPERATION_CONFLICT');
    // The native cart removes the pending key before Apply. Absence after a
    // handoff is NOT evidence of failure and must never cause automatic replay.
    if(operation.state)return {...handoff,state:operation.state,replayed:false};
    const existing=storage.getItem(KEY);
    // Unlike the original last-write-wins handler, do not silently replace a
    // different offer. Do not touch cart, identity, or other storage keys.
    if(existing&&existing!==handoff.value)throw new Error('PENDING_CODE_CONFLICT');
    operation.signature=signature;operation.state='unknown';persist(operation);
    if(!existing)storage.setItem(KEY,handoff.value);
    if(storage.getItem(KEY)!==handoff.value)throw new Error('HANDOFF_STORAGE_UNCONFIRMED');
    operation.state='staged_not_applied';persist(operation);
    return {...handoff,state:'staged_not_applied'};
  }
  function stageDurable(storage,options,operationId){
    if(typeof operationId!=='string'||!/^[-a-zA-Z0-9_]{1,100}$/.test(operationId))throw new Error('OPERATION_ID_REQUIRED');
    const recordKey='fs-native-code:'+operationId,raw=storage.getItem(recordKey);
    let operation;try{operation=raw?JSON.parse(raw):{id:operationId};}catch{throw new Error('OPERATION_RECORD_UNREADABLE');}
    if(operation.id!==operationId||operation.state&&!['unknown','staged_not_applied'].includes(operation.state))throw new Error('OPERATION_RECORD_UNREADABLE');
    const persist=value=>{const encoded=JSON.stringify(value);storage.setItem(recordKey,encoded);if(storage.getItem(recordKey)!==encoded)throw new Error('OPERATION_RECORD_UNCONFIRMED');};
    // Journal UNKNOWN before touching the native consumer key. Reloads must
    // reconcile the same ID, never restage a consumed key or auto-navigate.
    return stage(storage,options,operation,persist);
  }
  // Account coupon in place of the pending code (2026-11-16). The main-site Admin
  // "entry coupons" whitelist per slot decides which coupon is granted; this page
  // only maps its page to a slot. Anything other than a confirmed claim returns a
  // non-claimed state so the caller keeps the existing code handoff (no lost 10%).
  const COUPON_SLOTS={'fc27-weekly':'fc_weekly','fc27-sbc':'fc_sbc','fc27-trio':'fc_trio'};
  // Guests sign in on this page through the main-site login endpoints (same origin,
  // so the main-site session cookie is set directly; nothing passes through FS).
  const LOGIN_PROVIDERS=['google','facebook'];
  // Byte-for-byte the request the main-site jQuery login box sends (observed
  // 2026-11-16 on /Fc-27/Coins.html): these headers and only usname/passwd/remPwd/site_id.
  const loginHeaders={'X-Requested-With':'XMLHttpRequest','Accept':'application/json, text/javascript, */*; q=0.01','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'};
  const loginMessage=json=>typeof json?.msg==='string'&&json.msg.trim()&&json.msg.length<300?json.msg.trim():'Sign-in failed. Please try again.';
  const LOGIN_TIMEOUT_MS=15000;
  async function loginFetch(fetchImpl,path,init,timeoutMs){
    const controller=typeof AbortController==='function'?new AbortController():null,timer=controller?setTimeout(()=>controller.abort(),timeoutMs):null;
    try{return await fetchImpl(path,{...init,...(controller?{signal:controller.signal}:{})});}
    catch(error){if(error?.name==='AbortError')fail('LOGIN_TIMEOUT');throw error;}
    finally{if(timer)clearTimeout(timer);}
  }
  // RiskGuard fields are attached the same way when that main-site script is
  // present (it is not loaded on current main-site pages). Single POST, no retry.
  async function mainSiteLogin({email,password,remember=true,origin=root.location?.origin,fetchImpl=root.fetch?.bind(root),siteId='266',timeoutMs=LOGIN_TIMEOUT_MS}={}){
    if(origin!=='https://www.mmoexp.com'||typeof fetchImpl!=='function')fail('LOGIN_ORIGIN_UNVERIFIED');
    const fields={usname:String(email??'').trim(),passwd:String(password??''),remPwd:remember?'true':'false',site_id:siteId};
    try{if(typeof root.RiskGuard?.attach==='function')root.RiskGuard.attach(fields);}catch{}
    const response=await loginFetch(fetchImpl,'/user/login.html',{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',headers:loginHeaders,body:new URLSearchParams(fields).toString()},timeoutMs);
    let json;try{json=await response.json();}catch{fail('LOGIN_RESPONSE_INVALID');}
    return Number(json?.code)===1?{state:'signed_in'}:{state:'rejected',message:loginMessage(json)};
  }
  // Header state for the event pages: signed-in flag from the carnival user API,
  // cart count and avatar from the same /ajax/html fragment the main-site header uses.
  async function mainSiteAccount({origin=root.location?.origin,fetchImpl=root.fetch?.bind(root)}={}){
    if(origin!=='https://www.mmoexp.com'||typeof fetchImpl!=='function')return {state:'unavailable'};
    const get=path=>loginFetch(fetchImpl,path,{credentials:'same-origin',cache:'no-store',redirect:'error',headers:{'X-Requested-With':'XMLHttpRequest'}},LOGIN_TIMEOUT_MS);
    const user=await (await get('/ajax/carnival/user')).json();
    if(Number(user?.code)!==1||typeof user.data?.logged_in!=='boolean')fail('ACCOUNT_RESPONSE_INVALID');
    let cart=0,avatar=null;
    try{
      const html=await (await get('/ajax/html')).text();
      const count=/class="[^"]*\bcart-total\b[^"]*"[^>]*>\s*(\d{1,4})\s*</.exec(html);if(count)cart=Number(count[1]);
      const area=html.indexOf('jq-user-area'),img=area>=0?/<img\b[^>]*\bsrc="([^"]+)"/.exec(html.slice(area,area+4000)):null;
      if(img){const url=new URL(img[1].replace(/&amp;/g,'&'),origin);if(url.protocol==='https:'&&!/\/img\/user\.png$/.test(url.pathname))avatar=url.href;}
    }catch{}
    return {state:user.data.logged_in?'signed_in':'guest',cart,avatar};
  }
  // Main-site social login: the endpoint returns the provider authorize URL and
  // brings the shopper back to returnUrl (this event page) after sign-in.
  async function socialLoginUrl({provider,returnUrl,origin=root.location?.origin,fetchImpl=root.fetch?.bind(root),siteId='266'}={}){
    if(!LOGIN_PROVIDERS.includes(provider))fail('LOGIN_PROVIDER_INVALID');
    if(origin!=='https://www.mmoexp.com'||typeof fetchImpl!=='function')fail('LOGIN_ORIGIN_UNVERIFIED');
    const back=new URL(returnUrl,origin);if(back.origin!==origin)fail('LOGIN_ORIGIN_UNVERIFIED');
    const path='/user/login.html?act=loginapp&selfurl='+encodeURIComponent(back.origin+back.pathname)+'&site_id='+siteId+'&type='+provider;
    const response=await loginFetch(fetchImpl,path,{method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',headers:loginHeaders},LOGIN_TIMEOUT_MS);
    let json;try{json=await response.json();}catch{fail('LOGIN_RESPONSE_INVALID');}
    const target=Number(json?.code)===1&&typeof json.data?.redirect_url==='string'?new URL(json.data.redirect_url,origin):null;
    if(!target||target.protocol!=='https:')return {state:'rejected',message:loginMessage(json)};
    return {state:'redirect',url:target.href};
  }
  async function claimActivityCoupon({pageId,origin=root.location?.origin,fetchImpl=root.fetch?.bind(root)}={}){
    const slot=COUPON_SLOTS[pageId];
    if(!slot||origin!=='https://www.mmoexp.com'||typeof fetchImpl!=='function')return {state:'unavailable'};
    const call=async(path,body)=>{
      const response=await fetchImpl(path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',redirect:'error',
        headers:{'X-Requested-With':'XMLHttpRequest',...(body?{'Content-Type':'application/x-www-form-urlencoded'}:{})},...(body?{body}:{})});
      if(!response.ok)fail('COUPON_HTTP_REJECTED');
      const json=await response.json();
      if(json?.code!==1||!json.data||typeof json.data!=='object')fail('COUPON_RESPONSE_INVALID');
      return json.data;
    };
    // A failed read means the coupon service is unreachable and nothing was claimed:
    // treat it as switched off. Only a claim POST with an unknown result stops checkout.
    let listed;try{listed=await call('/ajax/carnival/coupon?slot='+encodeURIComponent(slot));}catch{return {state:'unavailable'};}
    if(listed.enabled!==true||listed.error||listed.slot!==slot)return {state:'unavailable'};
    if(listed.logged_in!==true)return {state:'login_required',slot};
    const coupons=(Array.isArray(listed.list)?listed.list:[]).filter(c=>Number.isSafeInteger(c?.coupon_id)&&c.coupon_id>0&&c.can_claim===true);
    if(!coupons.length)return {state:'unavailable'};
    const claimed=[];
    for(const coupon of coupons){
      // Single POST, no retry: an unknown claim falls back to the code path.
      const data=await call('/ajax/carnival/claim','slot='+encodeURIComponent(slot)+'&coupon_id='+coupon.coupon_id);
      if(data.claim_status!=='claimed'||data.coupon_id!==coupon.coupon_id||!Number.isSafeInteger(data.member_coupon_id)||data.member_coupon_id<=0)fail('COUPON_CLAIM_UNCONFIRMED');
      claimed.push({coupon_id:data.coupon_id,member_coupon_id:data.member_coupon_id});
    }
    return {state:'claimed',slot,coupons:claimed};
  }
  // Compose the existing native batch and native code consumer. The caller must
  // supply current, validated native lines; this does not enable a live gate.
  // couponClaimed=true: an account coupon was confirmed before Cart/add, so the
  // pending code is not staged (code and coupon are exclusive in the native cart).
  // memberCouponId is handed to the cart's own pending_member_coupon_id consumer,
  // which selects that coupon on load (the cart does not pick one by itself).
  const MEMBER_COUPON_KEY='pending_member_coupon_id';
  async function checkout({storage,options,operationId,items,host,navigate,onCartConfirmed,liveVerified=false,couponClaimed=false,memberCouponId=null}){
    if(liveVerified!==true)throw new Error('NATIVE_CHECKOUT_NOT_VERIFIED');
    // The UI may change while a native POST is pending. Freeze this operation's
    // source values before any await; its journal must describe every sent line.
    options=Object.freeze({...options});
    items=structuredClone(items);
    const handoff=plan(options);
    if(typeof operationId!=='string'||!/^[-a-zA-Z0-9_]{1,100}$/.test(operationId))throw new Error('OPERATION_ID_REQUIRED');
    if(!Array.isArray(items)||!items.length||items.length>50)throw new Error('CART_LINES_REQUIRED');
    const identities=items.map(x=>{
      const o=x?.offer;
      if(x?.native_payload){const body=nativeBody(x.native_payload,x.observed_serialization===true);if(o?.id!==Number(body.id)||o?.group!==Number(body.group)||o?.quantity!==Number(body.num)||o?.aid!==(body.aid?Number(body.aid):null))throw new Error('NATIVE_LINE_INVALID');return body;}
      if(!o||!['id','group','quantity','aid'].every(k=>Number.isSafeInteger(o[k])&&o[k]>0))throw new Error('NATIVE_LINE_INVALID');
      return [o.id,o.group,o.quantity,o.aid];
    });
    items.forEach(item=>{Object.freeze(item.offer);if(item.native_payload)Object.freeze(item.native_payload);Object.freeze(item);});Object.freeze(items);
    if(new Set(identities.map(x=>JSON.stringify(x))).size!==identities.length)throw new Error('DUPLICATE_CART_LINE');
    const key='fs-native-cart:'+operationId,signature=JSON.stringify([identities,handoff.value,handoff.cartUrl]);
    let old;try{old=JSON.parse(storage.getItem(key)||'null');}catch{throw new Error('OPERATION_RECORD_UNREADABLE');}
    if(old){if(old.signature!==signature)throw new Error('OPERATION_CONFLICT');return {...old,replayed:false};}
    const pending=storage.getItem(KEY);
    if(pending&&pending!==handoff.value)throw new Error('PENDING_CODE_CONFLICT');
    const persist=record=>{const text=JSON.stringify(record);storage.setItem(key,text);if(storage.getItem(key)!==text)throw new Error('OPERATION_RECORD_UNCONFIRMED');return record;};
    let record={id:operationId,signature,state:'unknown',outcomes:[]};
    // Journal before the first cart POST. A timeout/reload can never submit again.
    persist(record);
    try{
      const outcomes=await host.batch().run(items,rows=>{record={...record,outcomes:rows.map(r=>({id:r.id,state:r.state}))};persist(record);});
      record={...record,outcomes:outcomes.map(r=>({id:r.id,state:r.state}))};
      if(outcomes.length!==items.length||outcomes.some((r,i)=>r.id!==items[i].offer.id||r.state!=='confirmed'))return persist({...record,state:'cart_incomplete_inspect_original'});
      if(couponClaimed===true){
        if(Number.isSafeInteger(memberCouponId)&&memberCouponId>0){try{storage.setItem(MEMBER_COUPON_KEY,String(memberCouponId));}catch{}}
        record=persist({...record,state:'navigation_attempted_coupon_claimed'});
        try{if(typeof onCartConfirmed==='function')onCartConfirmed({code:null,coupon:true,items:structuredClone(items)});}catch{}
        navigate(handoff.cartUrl);
        return record;
      }
      persist({...record,state:'cart_confirmed_code_pending'});
      const staged=stageDurable(storage,options,operationId);
      if(staged.state!=='staged_not_applied')return persist({...record,state:'code_unknown_inspect_original'});
      // Never claim Apply succeeded: the original cart owns the response/amount.
      record=persist({...record,state:'navigation_attempted_not_applied'});
      // Optional observation after confirmed Cart/add and code staging; never
      // grant eligibility, change transport, retry, or claim Apply/payment.
      try{if(typeof onCartConfirmed==='function')onCartConfirmed({code:handoff.value,items:structuredClone(items)});}catch{}
      navigate(handoff.cartUrl);
      return record;
    }catch(error){
      // Preserve the durable last checkpoint; no retry, cleanup or cart clearing.
      return {id:operationId,state:'unknown',replayed:false,error:'INSPECT_ORIGINAL_CART_AND_OPERATION'};
    }
  }
  // This journal coordinates this browser's native cart, not a daily/person limit
  // or an authority for coupon eligibility. The original native claim stays required.
  function createCartGuard({storage,legacyStorage,locks=root.navigator?.locks,now=Date.now}={}){
    try{storage ||= root.localStorage;}catch{fail('CART_JOURNAL_UNAVAILABLE');}
    try{legacyStorage ||= root.sessionStorage;}catch{fail('CART_JOURNAL_UNAVAILABLE');}
    const key='fs-seasonal-native-cart-v1',lockName='fs-seasonal-native-cart';
    const read=()=>{let v;try{v=JSON.parse(storage.getItem(key)||'null');}catch{fail('CART_JOURNAL_UNAVAILABLE');}
      if(v&&(!['idle','confirmed','unknown'].includes(v.state)||!Array.isArray(v.items)||!Array.isArray(v.history)||v.state==='unknown'&&(!v.attempt?.id||!Array.isArray(v.attempt.items))))fail('CART_JOURNAL_UNAVAILABLE');return v;};
    const save=v=>{try{const raw=JSON.stringify(v);storage.setItem(key,raw);if(storage.getItem(key)!==raw)fail('CART_JOURNAL_UNAVAILABLE');}catch{fail('CART_JOURNAL_UNAVAILABLE');}};
    const identity=item=>Object.fromEntries(['category','id','num','group','attr','aid'].map(k=>[k,item.native_payload[k]]));
    const sameLine=(a,b)=>a.category===b.category&&a.id===b.id&&(a.category!=='new_gold'||(a.group||null)===(b.group||null));
    const matches=(rows,items)=>rows.length===items.length&&items.every(x=>rows.filter(r=>sameLine(r,x)&&r.num===x.num).length===1);
    // A SKU/quantity match can identify a known-success cart, but cannot prove
    // that an UNKNOWN POST created the same variant. Missing native fields are
    // unknown, never empty strings inferred from a title or an opaque key hash.
    const completeMatch=(rows,items)=>rows.length===items.length&&items.every(x=>rows.filter(r=>['category','id','num','group','attr','aid'].every(k=>typeof r[k]==='string'&&r[k]===x[k])).length===1);
    // Upgrade the old page/cart journals before creating ANY new native ID. An
    // empty cart cannot disprove an older timed-out POST still reaching the store.
    // Keep the old records intact; acknowledged IDs survive the bounded UI history.
    function upgrade(session,journal,rows=null){
      if(!session)return journal;
      const resolved=journal?.legacy_resolved_ids||[],pending=[],confirmed=[];
      try{for(let i=0;i<session.length;i++){
        const k=session.key(i);if(!k?.startsWith('fs-native-page:')||!k.includes(':seasonal-vault:'))continue;
        const page=JSON.parse(session.getItem(k));if(!page?.id)fail('CART_JOURNAL_UNAVAILABLE');
        if(resolved.includes(page.id))continue;
        const old=JSON.parse(session.getItem('fs-native-cart:'+page.id)||'null');
        let items=[],context={};
        try{const signature=JSON.parse(old?.signature),source=JSON.parse(page.signature);
          if(Array.isArray(signature?.[0]))items=signature[0].map(body=>Object.fromEntries(['category','id','num','group','attr','aid'].map(k=>[k,body[k]])));
          if(items.some(x=>!['new_items','new_gold'].includes(x.category)||!positive(x.id)||!positive(x.num)))items=[];
          context={code:signature[1],release:source[0],hash:source[1],selection:source.at(-1)};
        }catch{ /* An unreadable legacy result remains unresolved, never empty. */ }
        const outcomes=old?.outcomes;
        if(old?.state==='cart_incomplete_inspect_original'&&outcomes?.length===1&&outcomes[0].state==='rejected')continue;
        const record={...context,items:[],history:journal?.history||[],legacy_resolved_ids:resolved,state:'unknown',attempt:{id:page.id,items,legacy:true}};
        if(['navigation_attempted_not_applied','cart_confirmed_code_pending','code_unknown_inspect_original'].includes(old?.state)&&items.length&&outcomes?.length===items.length&&outcomes.every(x=>x.state==='confirmed'))confirmed.push({...record,state:'confirmed',items,attempt:null});
        else pending.push(record);
      }}catch{fail('CART_JOURNAL_UNAVAILABLE');}
      // Any unresolved old operation takes priority over a newer confirmed cart.
      if(pending.length){
        if(journal?.state==='unknown'&&!pending.some(x=>x.attempt.id===journal.attempt.id))return {...journal,legacy_pending_ids:[journal.attempt.id,...pending.map(x=>x.attempt.id)]};
        return {...pending[0],legacy_pending_ids:pending.map(x=>x.attempt.id)};
      }
      if(journal)return journal;
      return (rows?confirmed.find(x=>matches(rows,x.items)):confirmed[0])||null;
    }
    const blocked=(state,cartUrl)=>({state,cartUrl,suppressAnalytics:true});
    return {known(){return upgrade(legacyStorage,read());},async inspect(readCart){
      const cart=await readCart();if(cart?.status!=='native_cart_read'||!Array.isArray(cart.items))fail('NATIVE_CART_READ_UNAVAILABLE');
      const journal=upgrade(legacyStorage,read(),cart.items);
      if(journal?.state==='unknown')return {state:journal.attempt.items.length&&(!journal.legacy_pending_ids||journal.legacy_pending_ids.length===1)&&completeMatch(cart.items,[...journal.items,...journal.attempt.items])?'recoverable':'unknown',selection:journal.selection};
      if(!cart.items.length)return {state:'empty'};
      return journal?.state==='confirmed'&&matches(cart.items,journal.items)?{state:'selected',selection:journal.selection}:{state:'occupied'};
    },async checkout({snapshot,selection,approved,storage:session,host,navigate,onCartConfirmed}){
      if(!locks?.request)fail('CART_SYNC_UNAVAILABLE');
      if(typeof host.readCart!=='function')fail('NATIVE_CART_READ_REQUIRED');
      if(approved.items.length!==1)fail('CART_SELECTION_UNSUPPORTED');
      return locks.request(lockName,{mode:'exclusive',ifAvailable:true},async lock=>{
        if(!lock)return blocked('cart_busy_inspect_original',approved.options.cartUrl);
        const cart=await host.readCart();if(cart?.status!=='native_cart_read'||!Array.isArray(cart.items))fail('NATIVE_CART_READ_UNAVAILABLE');
        const wanted=approved.items.map(identity),rows=cart.items;let journal=upgrade(session,read(),rows);
        if(journal?.state==='unknown'){
          const expected=[...journal.items,...journal.attempt.items];
          // Presence of every exact new line can reconcile success. Empty is not
          // proof that a timed-out native POST will never complete.
          if(!journal.attempt.items.length||journal.legacy_pending_ids?.length>1||!completeMatch(rows,expected))return blocked('cart_unknown_inspect_original',approved.options.cartUrl);
          journal={...journal,state:'confirmed',items:expected,legacy_resolved_ids:[...new Set([...(journal.legacy_resolved_ids||[]),...(journal.attempt.legacy?[journal.attempt.id]:[])])],history:[...journal.history,{id:journal.attempt.id,state:'confirmed_by_cart_read',at:now()}].slice(-20),attempt:null};save(journal);
        }
        if(rows.length){
          if(!journal||journal.state!=='confirmed'||!matches(rows,journal.items)||journal.code!==approved.options.code||journal.release!==snapshot.release_id||journal.hash!==snapshot.config_hash)return blocked('cart_code_conflict',approved.options.cartUrl);
          if(stable(journal.selection)!==stable(selection))return blocked('cart_offer_conflict',approved.options.cartUrl);
          if(wanted.some(w=>rows.some(r=>sameLine(r,w)))){
            if(!matches(rows.filter(r=>wanted.some(w=>sameLine(w,r))),wanted))return blocked('cart_quantity_changed',approved.options.cartUrl);
            // A deliberate return to an existing confirmed line only opens the
            // cart; it never repeats Cart/add. Restage this same verified code.
            stageDurable(session,approved.options,root.crypto.randomUUID());navigate(plan(approved.options).cartUrl);
            return {state:'navigation_attempted_not_applied',existingCart:true};
          }
          return blocked('cart_offer_conflict',approved.options.cartUrl);
        }else{
          journal={state:'idle',items:[],history:journal?.history||[],legacy_resolved_ids:journal?.legacy_resolved_ids||[]};
        }
        const previous=journal||{state:'idle',items:[],history:[]},operationId=root.crypto.randomUUID();
        const context={code:approved.options.code,release:snapshot.release_id,hash:snapshot.config_hash,...(selection?{selection:structuredClone(selection)}:{})};
        let dispatched=false,settled=false;
        const record=()=>({...previous,...context,state:'unknown',attempt:{id:operationId,items:wanted,at:now()}});
        // Commit UNKNOWN before the actual native POST, across reloads/tabs.
        save(record());
        const wrapped={...host,batch(){const batch=host.batch();return {async run(items,progress){dispatched=true;const outcomes=await batch.run(items,progress);
          if(outcomes.length===items.length&&outcomes.every(r=>r.state==='confirmed')){save({...previous,...context,state:'confirmed',items:[...previous.items,...wanted],attempt:null,history:[...previous.history,{id:operationId,state:'confirmed',at:now()}].slice(-20)});settled=true;}
          else if(outcomes.length===1&&outcomes[0].state==='rejected'){save({...previous,history:[...previous.history,{id:operationId,state:'rejected',at:now()}].slice(-20)});settled=true;}
          return outcomes;
        }};}};
        try{return await checkout({storage:session,options:approved.options,operationId,items:approved.items,host:wrapped,navigate,onCartConfirmed,liveVerified:true});}
        finally{if(!dispatched&&!settled)save({...previous,history:[...previous.history,{id:operationId,state:'not_dispatched',at:now()}].slice(-20)});}
      });
    }};
  }
  const api={plan,stage,stageDurable,checkout,projectConfiguration,publishedPlan,checkoutPublished,createCartGuard,claimActivityCoupon,COUPON_SLOTS,mainSiteLogin,socialLoginUrl,mainSiteAccount,LOGIN_PROVIDERS};if(typeof module==='object'&&module.exports)module.exports=api;else root.CampaignNativeCodeHandoff=api;
})(typeof globalThis==='undefined'?this:globalThis);
