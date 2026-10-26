/* Observed native transport, not a discount grant or cart writer. Not wired live.
 * Cart currently attempts Apply after consuming this key. Require explicit
 * consumer-behavior confirmation; never represent this as prefill-only.
 */
(function(root){
  'use strict';
  const KEY='pending_discount_code';
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
  async function checkout({storage,options,operationId,items,host,navigate,liveVerified=false}){
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
      if(!o||!['id','group','quantity','aid'].every(k=>Number.isSafeInteger(o[k])&&o[k]>0))throw new Error('NATIVE_LINE_INVALID');
      return [o.id,o.group,o.quantity,o.aid];
    });
    items.forEach(item=>{Object.freeze(item.offer);Object.freeze(item);});Object.freeze(items);
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
      navigate(handoff.cartUrl);
      return record;
    }catch(error){
      // Preserve the durable last checkpoint; no retry, cleanup or cart clearing.
      return {id:operationId,state:'unknown',replayed:false,error:'INSPECT_ORIGINAL_CART_AND_OPERATION'};
    }
  }
  const api={plan,stage,stageDurable,checkout};if(typeof module==='object'&&module.exports)module.exports=api;else root.CampaignNativeCodeHandoff=api;
})(typeof globalThis==='undefined'?this:globalThis);
