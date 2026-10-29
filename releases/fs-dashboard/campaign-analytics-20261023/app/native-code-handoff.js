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
  async function checkoutPublished({snapshot,selection,storage,host,navigate,origin,onCartConfirmed}){
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
    let operation;try{operation=JSON.parse(storage.getItem(key)||'null');}catch{fail('OPERATION_RECORD_UNREADABLE');}
    if(operation&&operation.signature!==approved.signature)fail('OPERATION_CONFLICT');
    if(!operation){operation={id:root.crypto.randomUUID(),signature:approved.signature};const text=JSON.stringify(operation);storage.setItem(key,text);if(storage.getItem(key)!==text)fail('OPERATION_RECORD_UNCONFIRMED');}
    return checkout({storage,options:approved.options,operationId:operation.id,items:approved.items,host,navigate,onCartConfirmed,liveVerified:true});
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
  // Compose the existing native batch and native code consumer. The caller must
  // supply current, validated native lines; this does not enable a live gate.
  async function checkout({storage,options,operationId,items,host,navigate,onCartConfirmed,liveVerified=false}){
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
  const api={plan,stage,stageDurable,checkout,projectConfiguration,publishedPlan,checkoutPublished};if(typeof module==='object'&&module.exports)module.exports=api;else root.CampaignNativeCodeHandoff=api;
})(typeof globalThis==='undefined'?this:globalThis);
